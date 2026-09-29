#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { sanitizedDefaultExport } from "./parse_jp_literal_module.mjs";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const WORKSPACE = path.resolve(SCRIPT_DIR, "..");
const DEFAULT_MANIFEST = path.join(WORKSPACE, "metadata", "jp_official_download_manifest.json");
const SITE = "https://toho-vote.info";
const MAX_WORKERS = 8;
const USER_AGENT = "TouhouVoteResearch/1.0 (public character comment archive)";

function parseRounds(value) {
  if (!value) return [17, 18, 19, 20, 21, 22];
  const result = new Set();
  for (const part of value.split(",")) {
    const token = part.trim();
    if (!token) continue;
    if (token.includes("-")) {
      const [left, right] = token.split("-", 2).map((item) => Number.parseInt(item, 10));
      for (let round = Math.min(left, right); round <= Math.max(left, right); round += 1) result.add(round);
    } else result.add(Number.parseInt(token, 10));
  }
  const rounds = [...result].filter((round) => Number.isInteger(round) && round >= 17 && round <= 22).sort((a, b) => a - b);
  if (!rounds.length) throw new Error(`invalid modern JP rounds: ${value}`);
  return rounds;
}

function parseArgs(argv) {
  const args = {
    rounds: [17, 18, 19, 20, 21, 22],
    outputRoot: path.join(WORKSPACE, "data_raw", "character_comments"),
    manifest: DEFAULT_MANIFEST,
    workers: 4,
    refresh: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === "--rounds") args.rounds = parseRounds(argv[++index]);
    else if (token === "--output-root") args.outputRoot = path.resolve(argv[++index]);
    else if (token === "--manifest") args.manifest = path.resolve(argv[++index]);
    else if (token === "--workers") args.workers = Number.parseInt(argv[++index], 10);
    else if (token === "--refresh") args.refresh = true;
    else if (token === "--help") {
      console.log("Usage: crawl_jp_character_comments.mjs [--rounds 17-22] [--workers 4] [--refresh] [--output-root path]");
      process.exit(0);
    } else throw new Error(`unknown argument: ${token}`);
  }
  if (!Number.isInteger(args.workers) || args.workers < 1 || args.workers > MAX_WORKERS) {
    throw new Error(`workers must be an integer from 1 to ${MAX_WORKERS}`);
  }
  return args;
}

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function cleanText(value) {
  return String(value ?? "").replaceAll("\r", "").replaceAll("\u0000", "").trim();
}

function atomicJson(pathname, value) {
  return fs.mkdir(path.dirname(pathname), { recursive: true }).then(async () => {
    const temporary = `${pathname}.${process.pid}.tmp`;
    await fs.writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
    await fs.rename(temporary, pathname);
  });
}

async function fetchText(url, attempts = 4) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetch(url, {
        headers: {
          accept: "application/javascript,application/json;q=0.9,*/*;q=0.8",
          "user-agent": USER_AGENT,
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
      if (attempt < attempts) await new Promise((resolve) => setTimeout(resolve, 500 * 2 ** (attempt - 1)));
    }
  }
  throw lastError;
}

async function loadManifest(pathname) {
  const value = JSON.parse(await fs.readFile(pathname, "utf8"));
  return Array.isArray(value.records) ? value.records : [];
}

async function loadAggregateMap(round, outputRoot, manifest, force) {
  const localPath = path.join(WORKSPACE, "data_raw", "jp_official", `round_${round}`, "aggregate", "character.json");
  let value;
  try {
    value = JSON.parse(await fs.readFile(localPath, "utf8"));
  } catch {
    const aggregate = manifest.find((item) => Number(item.round) === round && item.kind === "aggregate" && item.category === "character");
    if (!aggregate) return new Map();
    const response = await fetchText(aggregate.url);
    const source = response.text;
    // The aggregate module is only used for rank/name provenance.  It is
    // parsed with the same safe literal-only evaluator as detail modules.
    value = { data: sanitizedDefaultExport(source) };
  }
  const rows = Array.isArray(value.data) ? value.data : [];
  const result = new Map();
  for (const row of rows) {
    const id = String(row.code ?? row.id ?? "");
    if (id) result.set(id, { rank: Number.isInteger(row.rank) ? row.rank : null, name: row.name ?? "" });
  }
  return result;
}

function entityOutputPath(outputRoot, round, id) {
  const safe = String(id).replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^\.+|\.+$/g, "") || "entity";
  return path.join(outputRoot, "jp", `round_${String(round).padStart(2, "0")}`, "entities", `${safe}.json`);
}

function normalizeComment(comment) {
  if (typeof comment === "string") {
    return { text: cleanText(comment), raw_text: cleanText(comment), author: null, is_primary: null, submitted_at: null };
  }
  if (!comment || typeof comment !== "object") return null;
  const text = cleanText(comment.body ?? comment.text ?? "");
  if (!text) return null;
  return {
    text,
    raw_text: text,
    author: comment.name == null ? null : cleanText(comment.name),
    is_primary: comment.primary == null ? null : Boolean(comment.primary),
    submitted_at: comment.time == null ? null : String(comment.time),
  };
}

export function normalizeModernComments(data) {
  const comments = Array.isArray(data?.comments) ? data.comments : [];
  return comments.map(normalizeComment).filter(Boolean);
}

export function buildModernEntity({ round, id, aggregate, data, source }) {
  const comments = normalizeModernComments(data);
  const name = cleanText(data?.name || aggregate?.name || "");
  return {
    schema_version: 1,
    region: "jp",
    round,
    category: "character",
    entity_id: String(id),
    entity_name: name,
    rank: aggregate?.rank ?? null,
    source_kind: "jp_modern_literal_module",
    source,
    comment_count: comments.length,
    comments,
    error: null,
  };
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

async function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  const records = await loadManifest(args.manifest);
  const selected = records.filter((item) => args.rounds.includes(Number(item.round)) && item.kind === "detail" && item.category === "character");
  if (!selected.length) throw new Error("modern JP manifest has no selected character detail modules");
  const aggregateMaps = new Map();
  for (const round of args.rounds) aggregateMaps.set(round, await loadAggregateMap(round, args.outputRoot, records, args.refresh));

  let completed = 0;
  const results = await mapConcurrent(selected, args.workers, async (record) => {
    const round = Number(record.round);
    const id = String(record.id);
    const url = String(record.url);
    const pathname = entityOutputPath(args.outputRoot, round, id);
    if (!args.refresh) {
      try {
        const cached = JSON.parse(await fs.readFile(pathname, "utf8"));
        if (cached?.source?.url === url && cached?.source?.sha256 && cached?.schema_version === 1) {
          completed += 1;
          if (completed % 100 === 0 || completed === selected.length) console.log(`jp modern comments: ${completed}/${selected.length} (cached)`);
          return { round, id, status: "cached", commentCount: cached.comment_count ?? 0 };
        }
      } catch {
        // Missing or incomplete entity output is fetched below.
      }
    }
    try {
      const response = await fetchText(url);
      const source = {
        url,
        final_url: response.finalUrl,
        sha256: sha256(response.text),
        bytes_utf8: Buffer.byteLength(response.text, "utf8"),
        content_type: response.contentType,
        last_modified: response.lastModified,
        etag: response.etag,
        fetched_at: new Date().toISOString(),
      };
      const data = sanitizedDefaultExport(response.text);
      const entity = buildModernEntity({ round, id, aggregate: aggregateMaps.get(round)?.get(id), data, source });
      await atomicJson(pathname, entity);
      completed += 1;
      if (completed % 100 === 0 || completed === selected.length) console.log(`jp modern comments: ${completed}/${selected.length}`);
      return { round, id, status: "downloaded", commentCount: entity.comment_count };
    } catch (error) {
      const aggregate = aggregateMaps.get(round)?.get(id) ?? {};
      const entity = {
        schema_version: 1,
        region: "jp",
        round,
        category: "character",
        entity_id: id,
        entity_name: cleanText(aggregate.name || ""),
        rank: aggregate.rank ?? null,
        source_kind: "jp_modern_literal_module",
        source: { url, fetched_at: new Date().toISOString() },
        comment_count: 0,
        comments: [],
        error: `${error?.name ?? "Error"}: ${error?.message ?? String(error)}`,
      };
      await atomicJson(pathname, entity);
      completed += 1;
      console.error(`jp modern comments failed ${round}/${id}: ${entity.error}`);
      return { round, id, status: "error", error: entity.error };
    }
  });
  const errors = results.filter((item) => item.status === "error").length;
  console.log(`jp modern comments finished: entities=${results.length}, errors=${errors}`);
  if (errors) process.exitCode = 1;
}

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : null;
if (invokedPath === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(error?.stack ?? String(error));
    process.exitCode = 1;
  });
}
