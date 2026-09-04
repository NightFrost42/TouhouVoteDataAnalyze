#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { sanitizedDefaultExport } from "./parse_jp_literal_module.mjs";

const SITE = "https://toho-vote.info";
export const DEFAULT_ROUNDS = [17, 18, 19, 20, 21, 22];
// Keep the default aligned with the article's full historical scope.  The
// official index exposes numeric detail modules for every modern round, and
// those modules contain the per-item questionnaire/association tables needed
// for reproducible analysis.  Existing files are checksum-aware cached on a
// resumed run, so a full default does not redownload completed rounds.
export const DEFAULT_DETAIL_ROUNDS = [17, 18, 19, 20, 21, 22];
const DETAIL_CATEGORIES = new Set(["character", "music", "work"]);
const AGGREGATE_CATEGORIES = new Set([
  "character",
  "music",
  "work",
  "count",
  "questionnaire",
]);
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const WORKSPACE = path.resolve(SCRIPT_DIR, "..");
const OUTPUT_ROOT = path.join(WORKSPACE, "data_raw", "jp_official");
const METADATA_ROOT = path.join(WORKSPACE, "metadata");
const STATUS_PATH = path.join(METADATA_ROOT, "jp_official_queue_status.json");
let statusState = {};
let statusWrite = Promise.resolve();

function parseRoundList(value, fallback) {
  if (!value) return fallback;
  const rounds = value
    .split(",")
    .map((item) => Number.parseInt(item.trim(), 10))
    .filter(Number.isInteger);
  if (!rounds.length) throw new Error(`invalid round list: ${value}`);
  return [...new Set(rounds)].sort((a, b) => a - b);
}

function parseArgs(argv) {
  const args = {
    rounds: DEFAULT_ROUNDS,
    detailRounds: DEFAULT_DETAIL_ROUNDS,
    concurrency: 6,
    force: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === "--rounds") args.rounds = parseRoundList(argv[++index], DEFAULT_ROUNDS);
    else if (token === "--detail-rounds") {
      args.detailRounds = parseRoundList(argv[++index], DEFAULT_DETAIL_ROUNDS);
    } else if (token === "--concurrency") {
      args.concurrency = Number.parseInt(argv[++index], 10);
    } else if (token === "--force") args.force = true;
    else if (token === "--help") {
      console.log(
        "Usage: crawl_jp_official.mjs [--rounds 17,18,19,20,21,22] " +
          "[--detail-rounds 17,18,19,20,21,22] [--concurrency 6] [--force]",
      );
      process.exit(0);
    } else throw new Error(`unknown argument: ${token}`);
  }
  if (!Number.isInteger(args.concurrency) || args.concurrency < 1 || args.concurrency > 12) {
    throw new Error("concurrency must be an integer from 1 to 12");
  }
  return args;
}

function sha256(text) {
  return crypto.createHash("sha256").update(text).digest("hex");
}

async function fetchText(url, attempts = 4) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetch(url, {
        headers: {
          accept: "text/html,application/javascript,application/json;q=0.9,*/*;q=0.8",
          "user-agent": "TouhouVoteResearch/1.0 (reproducible public-data audit)",
        },
        redirect: "follow",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status} ${response.statusText}`);
      return {
        text: await response.text(),
        finalUrl: response.url,
        contentType: response.headers.get("content-type"),
        lastModified: response.headers.get("last-modified"),
        etag: response.headers.get("etag"),
      };
    } catch (error) {
      lastError = error;
      if (attempt < attempts) {
        await new Promise((resolve) => setTimeout(resolve, 400 * 2 ** (attempt - 1)));
      }
    }
  }
  throw lastError;
}

async function writeJson(filePath, value) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  const body = `${JSON.stringify(value, null, 2)}\n`;
  const temporary = `${filePath}.tmp`;
  await fs.writeFile(temporary, body, "utf8");
  await fs.rename(temporary, filePath);
}

async function writeText(filePath, value) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, value, "utf8");
}

async function publishStatus(updates) {
  statusState = {
    schemaVersion: 1,
    ...statusState,
    ...updates,
    updatedAt: new Date().toISOString(),
    pid: process.pid,
    queue_stage_id: process.env.DATA_CRAWL_QUEUE_STAGE_ID ?? null,
    queue_stage_attempt: process.env.DATA_CRAWL_QUEUE_STAGE_ATTEMPT ?? null,
    queue_stage_started_at: process.env.DATA_CRAWL_QUEUE_STAGE_STARTED_AT ?? null,
  };
  const snapshot = JSON.parse(JSON.stringify(statusState));
  statusWrite = statusWrite.then(() => writeJson(STATUS_PATH, snapshot));
  await statusWrite;
}

export function extractIndexAsset(html) {
  const match = html.match(/<script[^>]+type=["']module["'][^>]+src=["']([^"']+index-[^"']+\.js)["']/i);
  if (!match) throw new Error("could not locate official index JavaScript asset");
  return new URL(match[1], SITE).href;
}

export function extractMappings(indexSource) {
  const mappings = [];
  // The generated index changed the relative import depth in round 22:
  // modern detail entries still use ../../assets while aggregate entries use
  // ../assets.  Accept either depth, but keep the path anchored to the
  // official results data tree so unrelated imports cannot be selected.
  const detailRe = /"(?:\.\.\/){1,2}assets\/data\/results\/(\d+)\/(character|music|work)\/(\d+)\.json":\(\)=>[^,]*?import\("\.\/([^"?]+\.js)"\)/g;
  const aggregateRe = /"(?:\.\.\/){1,2}assets\/data\/results\/(\d+)\/(character|music|work|count|questionnaire)\.json":\(\)=>[^,]*?import\("\.\/([^"?]+\.js)"\)/g;

  for (const match of indexSource.matchAll(detailRe)) {
    mappings.push({
      kind: "detail",
      round: Number(match[1]),
      category: match[2],
      id: match[3],
      module: match[4],
    });
  }
  for (const match of indexSource.matchAll(aggregateRe)) {
    mappings.push({
      kind: "aggregate",
      round: Number(match[1]),
      category: match[2],
      id: null,
      module: match[3],
    });
  }
  const unique = new Map();
  for (const mapping of mappings) {
    unique.set(`${mapping.kind}:${mapping.round}:${mapping.category}:${mapping.id ?? ""}`, mapping);
  }
  return [...unique.values()];
}

export function validateSelectedMappings(selected, args) {
  const keys = new Set(
    selected.map(
      (mapping) =>
        `${mapping.round}:${mapping.kind}:${mapping.category}:${mapping.id ?? ""}`,
    ),
  );
  for (const round of args.rounds) {
    for (const category of AGGREGATE_CATEGORIES) {
      if (!keys.has(`${round}:aggregate:${category}:`)) {
        throw new Error(`official index lacks round ${round} aggregate ${category}`);
      }
    }
    if (args.detailRounds.includes(round)) {
      for (const category of DETAIL_CATEGORIES) {
        const prefix = `${round}:detail:${category}:`;
        if (![...keys].some((key) => key.startsWith(prefix))) {
          throw new Error(`official index lacks round ${round} detail ${category}`);
        }
      }
    }
  }
}

function targetPath(mapping) {
  const base = path.join(OUTPUT_ROOT, `round_${mapping.round}`);
  if (mapping.kind === "detail") {
    return path.join(base, "detail", mapping.category, `${mapping.id}.json`);
  }
  return path.join(base, "aggregate", `${mapping.category}.json`);
}

async function mapConcurrent(items, limit, worker) {
  let cursor = 0;
  const results = new Array(items.length);
  async function consume() {
    while (true) {
      const index = cursor;
      cursor += 1;
      if (index >= items.length) return;
      results[index] = await worker(items[index], index);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, consume));
  return results;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const startedAt = new Date().toISOString();
  await fs.mkdir(OUTPUT_ROOT, { recursive: true });
  await fs.mkdir(METADATA_ROOT, { recursive: true });

  const indexRound = Math.max(...args.rounds);
  const page = await fetchText(`${SITE}/results/${indexRound}`);
  const indexUrl = extractIndexAsset(page.text);
  const index = await fetchText(indexUrl);
  await writeText(path.join(OUTPUT_ROOT, "site", `results_${indexRound}.html`), page.text);
  await writeText(path.join(OUTPUT_ROOT, "site", path.basename(new URL(indexUrl).pathname)), index.text);

  const allMappings = extractMappings(index.text);
  const selected = allMappings.filter((mapping) => {
    if (!args.rounds.includes(mapping.round)) return false;
    if (mapping.kind === "aggregate") return AGGREGATE_CATEGORIES.has(mapping.category);
    return args.detailRounds.includes(mapping.round) && DETAIL_CATEGORIES.has(mapping.category);
  });
  if (!selected.length) throw new Error("no official data-module mappings matched the requested rounds");
  validateSelectedMappings(selected, args);

  const expected = {};
  for (const mapping of selected) {
    const key = `${mapping.round}:${mapping.kind}:${mapping.category}`;
    expected[key] = (expected[key] ?? 0) + 1;
  }
  console.log(`official index: ${indexUrl}`);
  console.log(`selected modules: ${selected.length}`);
  console.log(JSON.stringify(expected, null, 2));

  let completed = 0;
  let cached = 0;
  let downloaded = 0;
  const recentItems = [];
  const recordProgress = async (mapping, outcome, output) => {
    completed += 1;
    if (outcome === "cached") cached += 1;
    else downloaded += 1;
    recentItems.push({
      round: mapping.round,
      kind: mapping.kind,
      category: mapping.category,
      id: mapping.id,
      status: outcome,
      output,
    });
    if (recentItems.length > 20) recentItems.shift();
    if (completed === 1 || completed % 25 === 0 || completed === selected.length) {
      await publishStatus({
        state: "running",
        stage: "jp_modern_results",
        requestedRounds: args.rounds,
        requestedDetailRounds: args.detailRounds,
        expectedCounts: expected,
        total: selected.length,
        completed,
        cached,
        downloaded,
        remaining: selected.length - completed,
        currentRound: mapping.round,
        currentKind: mapping.kind,
        currentCategory: mapping.category,
        currentId: mapping.id,
        recentItems: [...recentItems],
      });
    }
  };
  await publishStatus({
    state: "running",
    stage: "jp_modern_results",
    requestedRounds: args.rounds,
    requestedDetailRounds: args.detailRounds,
    expectedCounts: expected,
    total: selected.length,
    completed: 0,
    cached: 0,
    downloaded: 0,
    remaining: selected.length,
    recentItems: [],
  });
  const records = await mapConcurrent(selected, args.concurrency, async (mapping) => {
    const sourceUrl = new URL(`/assets/${mapping.module}`, SITE).href;
    const outputPath = targetPath(mapping);
    const relativeOutput = path.relative(WORKSPACE, outputPath).replaceAll("\\", "/");
    if (!args.force) {
      try {
        const existing = JSON.parse(await fs.readFile(outputPath, "utf8"));
        if (existing?._source?.url === sourceUrl && existing?._source?.sha256) {
          await recordProgress(mapping, "cached", relativeOutput);
          if (completed % 100 === 0 || completed === selected.length) {
            console.log(`completed ${completed}/${selected.length} (cached)`);
          }
          return {
            ...existing._source,
            round: mapping.round,
            kind: mapping.kind,
            category: mapping.category,
            id: mapping.id,
            output: relativeOutput,
            status: "cached",
          };
        }
      } catch {
        // Missing or incomplete output: fetch and replace it.
      }
    }

    const response = await fetchText(sourceUrl);
    const digest = sha256(response.text);
    const omit = mapping.kind === "detail" ? ["comments"] : [];
    const data = sanitizedDefaultExport(response.text, { omit });
    const source = {
      url: sourceUrl,
      final_url: response.finalUrl,
      sha256: digest,
      bytes_utf8: Buffer.byteLength(response.text, "utf8"),
      content_type: response.contentType,
      last_modified: response.lastModified,
      etag: response.etag,
      fetched_at: new Date().toISOString(),
      comments_omitted: mapping.kind === "detail",
    };
    await writeJson(outputPath, { _source: source, data });
    if (mapping.kind === "aggregate") {
      const rawPath = path.join(
        OUTPUT_ROOT,
        `round_${mapping.round}`,
        "aggregate_raw",
        `${mapping.category}.js`,
      );
      await writeText(rawPath, response.text);
    }

    await recordProgress(mapping, "downloaded", relativeOutput);
    if (completed % 25 === 0 || completed === selected.length) {
      console.log(`completed ${completed}/${selected.length}`);
    }
    return {
      ...source,
      round: mapping.round,
      kind: mapping.kind,
      category: mapping.category,
      id: mapping.id,
      output: relativeOutput,
      status: "downloaded",
    };
  });

  const manifest = {
    schema_version: 1,
    source_site: SITE,
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    index_url: indexUrl,
    index_sha256: sha256(index.text),
    rounds: args.rounds,
    detail_rounds: args.detailRounds,
    expected_counts: expected,
    module_count: records.length,
    records: records.sort((a, b) =>
      `${a.round}:${a.kind}:${a.category}:${a.id ?? ""}`.localeCompare(
        `${b.round}:${b.kind}:${b.category}:${b.id ?? ""}`,
        "en",
        { numeric: true },
      ),
    ),
  };
  await writeJson(path.join(METADATA_ROOT, "jp_official_download_manifest.json"), manifest);
  await publishStatus({
    state: "finished",
    stage: "jp_modern_results",
    total: selected.length,
    completed: selected.length,
    cached,
    downloaded,
    remaining: 0,
    manifest: path.relative(WORKSPACE, path.join(METADATA_ROOT, "jp_official_download_manifest.json")).replaceAll("\\", "/"),
    finishedAt: new Date().toISOString(),
  });
  console.log(`manifest: ${path.join(METADATA_ROOT, "jp_official_download_manifest.json")}`);
}

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : null;
if (invokedPath === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    const message = error?.stack ?? String(error);
    console.error(message);
    publishStatus({
      state: "failed",
      stage: "jp_modern_results",
      error: message,
      failedAt: new Date().toISOString(),
    })
      .catch((statusError) => console.error(statusError?.stack ?? String(statusError)))
      .finally(() => {
        process.exitCode = 1;
      });
  });
}
