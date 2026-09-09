/*
 * Static GitHub Pages front-end for the Touhou vote research data.
 *
 * This file deliberately does not import the desktop Tk application. It reads
 * generated CSV files for the lightweight views and a build-time JSON bundle
 * for the full desktop-template catalogue, so the web version stays isolated.
 */

const params = new URLSearchParams(window.location.search);
const DATA_BASE = new URL(params.get("data") || "../vote_explorer/data/", document.baseURI).href;
const DATA_VERSION = "2026-09-09-50";

const ROUND_LABELS = [
  ...Array.from({ length: 11 }, (_, i) => `CN${i + 1}`),
  ...Array.from({ length: 20 }, (_, i) => `JP${i + 3}`),
];

const QUESTION_LABELS = {
  age: "年龄分布", sex: "性别构成", cognition: "入坑时间", usertype: "参与东方的方式",
  voted: "历届投票经验", intention: "线下活动参与", location: "居住地区",
  trigger: "最初知道东方的途径", books: "官方书籍阅读情况", purchase_method: "原作购买方式",
  magazine: "官方连载阅读方式", charm: "东方的魅力所在", cleared_title: "整数作通关难度",
  subnumber: "小数点作游玩情况", th21: "新作体验版", parents: "是否由家人传教",
  event: "线下活动参与", friends: "东方同好关系", lastVote: "历届投票经验", triggerVote: "参与投票动机",
};

const METRIC_LABELS = {
  rank: "官方名次", points: "官方分数", primary_count: "第一顺位票", secondary_count: "第二顺位票",
  selection_count: "实际选择人数", selection_rate: "选择率", primary_rate: "第一顺位率",
  comment_count: "评论数", arrangement_count: "届间新增同人曲数",
  arrangement_cumulative_count: "截至投票结束累计同人曲数", arrangement_total_count: "同人曲累计总数（抓取时点）",
  vote_count: "CP投票人数", vote_rate: "CP投票比例", comparison_count: "组合对比人数",
  comparison_rate: "组合对比比例", cp_vote_count: "CP官方人数", covote_count: "同投替代人数",
  count: "回答人数", rate: "比例", secondary_rate: "第二顺位率", top2_rate: "前两顺位集中率",
  female_rate: "女性比例", male_rate: "男性比例", other_gender_rate: "其他性别比例",
  under20_rate: "未满20岁比例", overall_male_rate: "全体男性比例", overall_female_rate: "全体女性比例",
  overall_other_gender_rate: "全体其他性别比例", other_count: "其他顺位票", ballots: "有效票数",
  equal_rank: "等权排名", old_2_1_rank: "旧2:1排名", old_2_1_points: "旧2:1分数",
  intersection_count: "共同投票人数", share: "同投占比", lift: "同投集中倍数",
  excess_count: "超出人气基准人数", phi: "综合重合分数 φ", asymmetry: "方向同投率差",
  direction_a_to_b: "A→B方向同投率", direction_b_to_a: "B→A方向同投率",
  anomaly_difference: "双向人数差", correlation: "皮尔逊相关系数", difference_points: "相对全体差值（百分点）",
  denominator: "问卷有效人数", member_count: "组合成员数", source_type: "数据来源", value: "数值",
};

const DATA_FILES = {
  character: "analysis_character_metrics_all.csv",
  factions: "analysis_character_factions.csv",
  music: "analysis_music_metrics_all.csv",
  cp: "analysis_cp_metrics_all.csv",
  combination: "analysis_vote_combinations_all.csv",
  questionnaire: "analysis_questionnaire_all.csv",
  entity_questionnaire: "analysis_entity_questionnaire_all.csv.gz",
  character_music_links: "analysis_character_music_links_all.csv",
  character_music_covote: "analysis_character_music_covote_all.csv",
};

// The pair matrix is intentionally loaded lazily (only for a co-vote view).
// It is split into two CSV parts in the repository; loadCSV("covote_pairs")
// joins both parts and removes their repeated headers.

// The complete same-department co-vote matrix is split into two files because
// GitHub Pages and common static hosts have awkward limits around very large
// single files.  It is fetched only when the music-internal cluster view is
// selected; the ordinary lightweight views never pay the 145 MB transfer.
const COVOTE_PAIR_PARTS = [
  "analysis_covote_pairs_all.csv.part-001",
  "analysis_covote_pairs_all.csv.part-002",
];

// The desktop workbench has two natural scopes.  Single-round metrics belong
// to the root of a round's analysis project; anything that compares rounds is
// kept together in the comparison-table project.  The static bundle remains
// the source of truth for the actual 72-template catalogue.
const DESKTOP_SINGLE_KEYS = new Set([
  "c02_selection_top", "c02_equal_rank", "c03_primary_rate", "c04_secondary_rate", "c05_top2_rate",
  "c11_structure", "c11_metric_heatmap", "c12_gender_structure", "c12_gender_lean",
  "r01_character_question_scatter", "r02_character_question_diff", "r03_character_question_corr",
  "m01_metric", "m04_primary_rate", "m05_character_music_cross", "m06_music_character_cross",
  "m07_character_music_covote", "m08_character_carryover", "m09_music_arrangement_cross",
  "m10_character_arrangement_cross", "r04_music_question_scatter", "r05_music_question_diff",
  "r06_music_question_corr", "r07_character_cognition", "r08_work_question_matrix",
  "r09_character_question_matrix", "r10_music_question_matrix", "a01_direction_matrix", "a01_count_matrix",
  "a02_network", "a17_concentration_clusters", "a18_music_concentration_clusters", "a03_bubble",
  "a03_count_top", "a06_lift", "a07_excess", "a08_phi", "a11_asymmetry", "a12_cumulative",
  "a14_count_top10", "a15_lift_top10", "a16_anomalies", "p01_cp_metric", "x_character", "x_covote",
]);

// These templates consume config.compare_round in the desktop repository.
// The web bundle contains a precomputed pair snapshot for every two rounds in
// the same region, so the selector below is a real comparison control rather
// than a cosmetic label that always means "previous round".
const COMPARISON_TEMPLATE_KEYS = new Set([
  "c00_round_compare", "c01_rank_change", "c03_primary_rate_change",
  "c06_primary_change", "c07_selection_change", "c07_selection_yoy",
  "c08_points_change", "c09_selection_rate_change", "c12_gender_change",
  "m02_round_compare", "a04_count_dumbbell", "a04_count_change",
  "a05_largest_change", "a09_phi_change", "a13_quadrant",
  "p02_combination_compare", "q01_age", "q02_cognition", "q03_usertype",
  "q04_new", "q_custom",
]);

const ENTITY_RELATION_TEMPLATE_KEYS = new Set([
  "r01_character_question_scatter", "r02_character_question_diff", "r03_character_question_corr",
  "r04_music_question_scatter", "r05_music_question_diff", "r06_music_question_corr",
  "r07_character_cognition", "r08_work_question_matrix", "r09_character_question_matrix",
  "r10_music_question_matrix",
]);

function isDesktopMode(mode = currentMode()) {
  return ["desktop", "desktop_single", "desktop_compare"].includes(mode);
}

function desktopScope(mode = currentMode()) {
  if (mode === "desktop_single") return "single";
  // The former desktop-single and desktop-compare entries exposed two
  // overlapping catalogues.  Keep the legacy mode readable for old links,
  // but make the visible desktop entry contain the complete catalogue.
  if (mode === "desktop_compare") return "all";
  return "all";
}

function projectLabel(mode = currentMode()) {
  if (mode === "desktop_compare") return "桌面版完整分析（单届结果根目录 + 对比分析表）";
  return "单届结果（分析项目根目录）";
}

const state = {
  cache: new Map(),
  bundle: null,
  rows: [],
  resultRows: [],
  tableRows: [],
  headers: [],
  chartZoom: 1,
  lastMode: "ranking",
  heavyCacheProfile: "",
};

// Every control change can start another asynchronous CSV/bundle read.  Keep
// a monotonically increasing token so a slower, obsolete read can never paint
// over the result for the user's latest selection.
let refreshSerial = 0;

const DYNAMIC_COVOTE_TEMPLATE_KEYS = new Set([
  "a01_direction_matrix", "a01_count_matrix", "a02_network", "a03_bubble", "a03_count_top",
  "a04_count_dumbbell", "a04_count_change", "a05_largest_change", "a06_lift", "a07_excess",
  "a08_phi", "a09_phi_change", "a10_direction", "a11_asymmetry", "a12_cumulative",
  "a13_quadrant", "a14_count_top10", "a15_lift_top10", "a16_anomalies", "x_covote",
]);

// These desktop templates used to render a precomputed 20-row snapshot even
// when the user asked for a larger Top N.  Keep the snapshot for labels and
// explanatory copy, but calculate the actual rows from the complete metric
// CSVs and slice only at the final display step.
const DYNAMIC_METRIC_TEMPLATE_KEYS = new Set([
  "c00_round_compare", "c00_rank_trend", "c00_all_trend", "c01_rank_change", "c02_selection_top",
  "c02_equal_rank", "c03_primary_rate", "c03_primary_rate_change", "c04_secondary_rate", "c05_top2_rate",
  "c06_primary_change", "c07_selection_change", "c07_selection_yoy", "c08_points_change",
  "c09_selection_rate_change", "c10_growth_lag", "c11_structure", "c11_metric_heatmap",
  "c12_gender_structure", "c12_gender_lean", "c12_gender_change", "m01_metric", "m02_round_compare",
  "m03_rank_trend", "m03_all_trend", "m04_primary_rate",
]);

// Cross-analysis and CP templates also need the complete source tables.  Their
// old desktop snapshots were intentionally small (usually 20 rows), which
// meant changing Top N could only re-slice an already truncated result.  These
// templates now calculate from the full CSV and apply Top N as the last step.
const DYNAMIC_CROSS_TEMPLATE_KEYS = new Set([
  "m05_character_music_cross", "m06_music_character_cross", "m07_character_music_covote",
  "m08_character_carryover", "m09_music_arrangement_cross", "m10_character_arrangement_cross",
  "p01_cp_metric", "p02_combination_compare",
]);

function releaseInactiveHeavyCaches(mode = currentMode(), templateKey = controls.template.value) {
  let profile = "none";
  if (isDesktopMode(mode)) {
    if (ENTITY_RELATION_TEMPLATE_KEYS.has(templateKey)) profile = "entity";
    else if (templateKey === "a17_concentration_clusters") profile = "music_covote";
    else if (templateKey === "a18_music_concentration_clusters" || DYNAMIC_COVOTE_TEMPLATE_KEYS.has(templateKey)) profile = "covote";
  }
  if (profile === state.heavyCacheProfile) return;
  if (profile !== "entity") state.cache.delete("entity_questionnaire");
  if (profile !== "covote") state.cache.delete("covote_pairs");
  if (profile !== "music_covote") state.cache.delete("character_music_covote");
  state.heavyCacheProfile = profile;
}

const $ = (id) => document.getElementById(id);
const controls = {
  kind: $("analysis-kind"), round: $("round"), subject: $("subject"), metric: $("metric"),
  xMetric: $("x-metric"), yMetric: $("y-metric"), question: $("question"), topN: $("top-n"),
  minVotes: $("min-votes"), search: $("search"), template: $("template"),
  compareRound: $("compare-round"), faction: $("faction"), rankStart: $("rank-start"), rankEnd: $("rank-end"),
  minCount: $("min-count"), sort: $("sort"), changeDirection: $("change-direction"), language: $("language"),
  relationQuestion: $("relation-question"), relationAnswer: $("relation-answer"),
  relationValueMode: $("relation-value-mode"), relationSort: $("relation-sort"),
};

// Keep the network's table and SVG in lock-step.  The network follows the
// desktop workbench convention: Top N is the number of ranked role nodes in
// the cohort (up to the shared 100-row control limit), and both views use the
// strongest relationships found inside that same cohort.
const NETWORK_TOP_N_MAX = 100;

function topNLimit(templateKey = controls.template.value) {
  const max = templateKey === "a02_network" ? NETWORK_TOP_N_MAX : 100;
  return Math.max(3, Math.min(max, integer(controls.topN.value, 20)));
}

function syncTopNLimit(templateKey = controls.template.value) {
  const max = templateKey === "a02_network" ? NETWORK_TOP_N_MAX : 100;
  controls.topN.max = String(max);
  const value = integer(controls.topN.value, 20);
  const clamped = Math.max(3, Math.min(max, value));
  if (String(clamped) !== String(controls.topN.value)) controls.topN.value = String(clamped);
  return clamped;
}

function number(value, fallback = null) {
  if (value === null || value === undefined || String(value).trim() === "") return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function integer(value, fallback = 0) {
  const parsed = number(value, null);
  return parsed === null ? fallback : Math.trunc(parsed);
}

function escapeHTML(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function parseCSV(text) {
  const rows = [];
  let row = [], cell = "", quoted = false;
  const source = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < source.length; i += 1) {
    const ch = source[i];
    if (quoted) {
      if (ch === '"' && source[i + 1] === '"') { cell += '"'; i += 1; }
      else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"' && cell.length === 0) quoted = true;
    else if (ch === ",") { row.push(cell); cell = ""; }
    else if (ch === "\n") { row.push(cell.replace(/\r$/, "")); rows.push(row); row = []; cell = ""; }
    else cell += ch;
  }
  if (cell.length || row.length) { row.push(cell.replace(/\r$/, "")); rows.push(row); }
  if (!rows.length) return [];
  const headers = rows[0];
  return rows.slice(1).filter((items) => items.some((item) => item !== "")).map((items) => {
    const result = {};
    headers.forEach((header, index) => { result[header] = items[index] ?? ""; });
    return result;
  });
}

async function loadCSV(kind) {
  if (state.cache.has(kind)) return state.cache.get(kind);
  if (kind === "covote_pairs") {
    const promise = Promise.all(COVOTE_PAIR_PARTS.map((file) => fetch(`${DATA_BASE}${file}?v=${DATA_VERSION}`).then(async (response) => {
      if (!response.ok) throw new Error(`读取 ${file} 失败（HTTP ${response.status}）`);
      return response.text();
    }))).then((texts) => texts.flatMap((text) => parseCSV(text))
      // Each part carries its own CSV header.  parseCSV turns the repeated
      // header into a normal row, so discard it here before analysis.
      .filter((row) => row.round_label && row.round_label !== "round_label"));
    state.cache.set(kind, promise);
    return promise;
  }
  const promise = fetch(`${DATA_BASE}${DATA_FILES[kind]}?v=${DATA_VERSION}`)
    .then(async (response) => {
      if (!response.ok) throw new Error(`读取 ${DATA_FILES[kind]} 失败（HTTP ${response.status}）`);
      if (kind !== "entity_questionnaire") return response.text();
      // The entity questionnaire is kept as the repository's 69 MB gzip
      // source.  Decompress it lazily in the browser instead of baking one
      // default question/answer into the static snapshot.  Modern Chrome,
      // Edge, Firefox and Safari all expose DecompressionStream; a plain CSV
      // response is also accepted for local deployments that pre-decompress
      // the file.
      const buffer = await response.arrayBuffer();
      const bytes = new Uint8Array(buffer);
      if (bytes[0] === 0x1f && bytes[1] === 0x8b) {
        if (typeof DecompressionStream === "undefined") {
          throw new Error("当前浏览器不支持 gzip 解压，无法读取实体问卷全量数据");
        }
        const stream = new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip"));
        return new Response(stream).text();
      }
      return new TextDecoder("utf-8").decode(buffer);
    })
    .then(parseCSV);
  state.cache.set(kind, promise);
  return promise;
}

async function loadBundle() {
  if (state.bundle) return state.bundle;
  const response = await fetch(`web_data/templates.json?v=${DATA_VERSION}`);
  if (!response.ok) throw new Error(`读取桌面版模板快照失败（HTTP ${response.status}）`);
  state.bundle = await response.json();
  return state.bundle;
}

function labelForQuestion(key) {
  return QUESTION_LABELS[key] || (String(key).startsWith("cn_") ? String(key).slice(3) : key);
}

function nameFor(row) {
  return row.name_cn || row.name_jp || row.combination_label || row.canonical_name || "未命名";
}

function displayLabel(row) {
  return row.label || row.label_jp || row.combination_label || nameFor(row);
}

function formatValue(value, metric) {
  const numeric = number(value, null);
  if (numeric === null) return "—";
  if (metric.endsWith("_rate") || metric === "rate" || metric === "vote_rate" || metric === "comparison_rate") {
    return `${(numeric * 100).toFixed(2)}%`;
  }
  if (metric === "rank") return `#${Math.round(numeric)}`;
  if (Number.isInteger(numeric)) return numeric.toLocaleString("zh-CN");
  return numeric.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function metricIsPercent(metric) {
  return metric.endsWith("_rate") || metric === "rate" || metric === "vote_rate" || metric === "comparison_rate";
}

function metricIsInteger(metric) {
  return metric === "rank" || metric.endsWith("_count") || ["points", "ballots", "vote_count", "count"].includes(metric);
}

function selectedRound(row) {
  return String(row.round_label || `${String(row.region || "").toUpperCase()}${row.round || ""}`).toUpperCase();
}

function normalizeName(value) {
  return String(value || "").replace(/[\s・･·\-—_]/g, "").toLocaleLowerCase();
}

function isMusicPairRow(row) {
  return String(row?.source_type || "").includes("music_covote_matrix");
}

function isCharacterPairRow(row) {
  return Boolean(row) && !isMusicPairRow(row);
}

function pairKey(a, b) {
  return [normalizeName(a), normalizeName(b)].sort().join("||");
}

function pairAliases(row, side) {
  const suffix = side === "a" ? "a" : "b";
  return [row?.[`canonical_${suffix}`], row?.[`name_${suffix}`], row?.[`name_${suffix}_cn`]]
    .map(normalizeName).filter(Boolean);
}

function entityAliases(row) {
  return [row?.canonical_name, row?.name_cn, row?.name_jp, row?.entity_name]
    .map(normalizeName).filter(Boolean);
}

function factionLabels(row) {
  const raw = row?.factions ?? row?.faction ?? row?.faction_labels;
  if (Array.isArray(raw)) return raw.map((value) => String(value || "").trim()).filter(Boolean);
  return String(raw || "")
    .split(/[;,，、]/)
    .map((value) => value.trim())
    .filter(Boolean);
}

function pairMatchesEntity(row, side, entityKey) {
  return pairAliases(row, side).includes(entityKey) || pairAliases(row, side).some((alias) => alias === entityKey);
}

function pairLabel(row, language = "cn") {
  const a = language === "jp" ? (row.name_a || row.name_a_cn) : (row.name_a_cn || row.name_a);
  const b = language === "jp" ? (row.name_b || row.name_b_cn) : (row.name_b_cn || row.name_b);
  return `${a || "?"} × ${b || "?"}`;
}

function setOptions(select, options, selected) {
  select.innerHTML = options.map((item) => {
    const value = typeof item === "string" ? item : item.value;
    const label = typeof item === "string" ? item : item.label;
    return `<option value="${escapeHTML(value)}">${escapeHTML(label)}</option>`;
  }).join("");
  if (selected && options.some((item) => (typeof item === "string" ? item : item.value) === selected)) select.value = selected;
}

function toggle(id, visible) { $(id).classList.toggle("hidden", !visible); }

function currentMode() { return controls.kind.value; }

function updateControlVisibility() {
  const mode = currentMode();
  const questionnaire = mode === "questionnaire";
  const arrangement = mode === "arrangement";
  const cp = mode === "cp";
  const desktop = isDesktopMode(mode);
  const templateKey = controls.template.value;
  const comparison = desktop && COMPARISON_TEMPLATE_KEYS.has(templateKey);
  const faction = desktop && templateKey === "a02_network";
  const factionSelected = faction && Boolean(controls.faction.value);
  const desktopQuestion = desktop && templateKey === "q_custom";
  const customCharacter = desktop && templateKey === "x_character";
  const customCovote = desktop && templateKey === "x_covote";
  const crossMetric = desktop && ["m05_character_music_cross", "m06_music_character_cross", "m09_music_arrangement_cross", "m10_character_arrangement_cross"].includes(templateKey);
  // Keep the network's role cohort and the input bounded by the shared 100
  // row control, so every refresh has one unambiguous effective Top N value.
  syncTopNLimit(templateKey);
  $("top-n-title").textContent = templateKey === "a02_network"
    ? (factionSelected ? "显示关系数（Top N）" : "显示角色数（Top N）")
    : "Top N";
  const noRankRange = ["a17_concentration_clusters", "a18_music_concentration_clusters"].includes(templateKey);
  const relation = desktop && ["r01_character_question_scatter", "r02_character_question_diff", "r03_character_question_corr", "r04_music_question_scatter", "r05_music_question_diff", "r06_music_question_corr", "r07_character_cognition", "r08_work_question_matrix", "r09_character_question_matrix", "r10_music_question_matrix"].includes(templateKey);
  const relationMetric = relation && ["r01_character_question_scatter", "r03_character_question_corr", "r04_music_question_scatter", "r06_music_question_corr", "r07_character_cognition"].includes(templateKey);
  const relationValue = relation && !["r03_character_question_corr", "r06_music_question_corr", "r08_work_question_matrix", "r09_character_question_matrix", "r10_music_question_matrix"].includes(templateKey);
  const relationSort = relation && !["r08_work_question_matrix", "r09_character_question_matrix", "r10_music_question_matrix"].includes(templateKey);
  toggle("subject-label", !questionnaire && !cp && !arrangement && !desktop);
  toggle("metric-label", !questionnaire && !arrangement && !desktop);
  toggle("x-metric-label", arrangement || relationMetric || customCharacter || customCovote || crossMetric);
  toggle("y-metric-label", arrangement || customCharacter || customCovote || crossMetric);
  toggle("relation-value-mode-label", relationValue);
  toggle("relation-sort-label", relationSort);
  toggle("question-label", questionnaire || desktopQuestion);
  toggle("template-label", desktop);
  toggle("compare-round-label", comparison);
  toggle("faction-label", faction);
  toggle("rank-start-label", desktop && !relation && !noRankRange);
  toggle("rank-end-label", desktop && !relation && !noRankRange);
  toggle("min-count-label", desktop && ["a01_direction_matrix", "a01_count_matrix", "a02_network", "a17_concentration_clusters", "a18_music_concentration_clusters", "a03_bubble", "a03_count_top", "a04_count_dumbbell", "a04_count_change", "a05_largest_change", "a06_lift", "a07_excess", "a08_phi", "a09_phi_change", "a10_direction", "a11_asymmetry", "a12_cumulative", "a13_quadrant", "a14_count_top10", "a15_lift_top10", "a16_anomalies", "x_covote"].includes(templateKey));
  toggle("sort-label", desktop && !relation && !["a02_network", "a03_bubble"].includes(templateKey));
  toggle("change-direction-label", desktop && ["c01_rank_change", "c03_primary_rate_change", "c06_primary_change", "c07_selection_change", "c07_selection_yoy", "c08_points_change", "c09_selection_rate_change", "c12_gender_change", "a04_count_change", "a05_largest_change", "a09_phi_change"].includes(templateKey));
  toggle("language-label", desktop);
  toggle("relation-question-label", relation);
  toggle("relation-answer-label", relation && !["r08_work_question_matrix", "r09_character_question_matrix", "r10_music_question_matrix"].includes(templateKey));
  // Work-level questionnaire rows have no corresponding work vote total, so
  // the entity-vote threshold is meaningless for the work matrix.  Hiding it
  // also prevents a stale threshold from being reported as if it filtered
  // the matrix.
  const relationVoteThreshold = relation && templateKey !== "r08_work_question_matrix";
  toggle("min-votes-label", (!questionnaire && !desktop) || relationVoteThreshold);
  controls.subject.disabled = questionnaire || cp || arrangement || desktop;
  controls.metric.disabled = questionnaire || arrangement || desktop;
  controls.xMetric.disabled = !(arrangement || relationMetric || customCharacter || customCovote || crossMetric);
  controls.yMetric.disabled = !(arrangement || customCharacter || customCovote || crossMetric);
  controls.question.disabled = !(questionnaire || desktopQuestion);
  controls.template.disabled = !desktop;
  controls.compareRound.disabled = !comparison;
  controls.faction.disabled = !faction;
  controls.rankStart.disabled = !(desktop && !relation && !noRankRange && !factionSelected);
  controls.rankEnd.disabled = !(desktop && !relation && !noRankRange && !factionSelected);
  controls.minCount.disabled = !(desktop && ["a01_direction_matrix", "a01_count_matrix", "a02_network", "a17_concentration_clusters", "a18_music_concentration_clusters", "a03_bubble", "a03_count_top", "a04_count_dumbbell", "a04_count_change", "a05_largest_change", "a06_lift", "a07_excess", "a08_phi", "a09_phi_change", "a10_direction", "a11_asymmetry", "a12_cumulative", "a13_quadrant", "a14_count_top10", "a15_lift_top10", "a16_anomalies", "x_covote"].includes(templateKey));
  controls.sort.disabled = !desktop;
  controls.changeDirection.disabled = !desktop;
  controls.language.disabled = !desktop;
  controls.relationQuestion.disabled = !relation;
  controls.relationAnswer.disabled = !relation;
  controls.relationValueMode.disabled = !relationValue;
  controls.relationSort.disabled = !relationSort;
  $("min-votes-title").textContent = cp ? "最少 CP 投票人数" : "最少实体投票人数";
  $("x-metric-title").textContent = relationMetric ? "投票指标（表/相关）" : customCovote ? "同投横轴" : customCharacter ? "角色横轴" : "横轴（同人曲口径）";
  if (crossMetric) {
    $("x-metric-title").textContent = templateKey === "m05_character_music_cross" ? "角色横轴" : templateKey === "m06_music_character_cross" ? "曲子横轴" : "同人曲数量横轴";
    $("y-metric-title").textContent = templateKey === "m05_character_music_cross" ? "关联曲纵轴" : templateKey === "m06_music_character_cross" ? "所属角色纵轴" : "投票指标纵轴";
  } else if (customCharacter || customCovote) $("y-metric-title").textContent = customCovote ? "同投纵轴" : "角色纵轴";
  if (arrangement) {
    $("control-note").textContent = "横轴是同人曲数量，纵轴是投票指标；两轴均使用当前地区/届次，数量轴保持整数。CN1/JP3 为首届基线，届间新增与截至投票结束累计为空。";
  } else if (questionnaire) {
    $("control-note").textContent = "问卷题目和选项按当前地区/届次读取；不同地区的实体问卷不会合并。Top N 是图表和结果表显示的选项数。";
  } else if (desktop) {
    const compareText = comparison ? ` 当前比较：${controls.round.value} 与 ${controls.compareRound.value || "—"}；比较届次仅列同一地区，避免把中日不同口径混在一起。` : "";
    const factionText = faction ? " 原作阵营会按角色—阵营交叉表过滤网络节点与关系。" : "";
    const networkText = templateKey === "a02_network"
      ? (factionSelected
        ? ` 当前已选择阵营：完整阵营角色集合从角色—阵营交叉表读取，不受 Top N 或名次范围截断；Top N 仅控制表格和图表保留的最强关系数，节点名称仅标注高连接角色，其余可悬停查看。`
        : ` 网络先按名次取前 N 个角色（当前上限 ${NETWORK_TOP_N_MAX} 个），图表与结果表再从这批角色中使用同一组最多 N 条关系；节点名称仅标注高连接角色，其余可悬停查看。`)
      : "";
    $("control-note").textContent = desktopScope(mode) === "single"
      ? `这里显示桌面工具中的单届结果；它们放在当前届次分析项目的根目录。电脑和手机均可访问，Top N、搜索和 CSV 下载仍在浏览器端完成。${networkText}`
      : `这里显示桌面工具的完整分析目录：单届结果归入当前届次根目录，跨届、趋势和对比结果归入统一对比表。电脑和手机均可访问，Top N、搜索、阈值和 CSV 下载仍在浏览器端完成。${compareText}${factionText}${networkText}`;
  } else {
    $("control-note").textContent = "Top N 是图表和结果表最终显示的行数，不是重新计算投票总数的抽样人数。最少实体投票人数默认 0，正数时过滤低票角色/曲子。";
  }
  $("project-path").textContent = `项目层级：${projectLabel(mode)}`;
}

async function prepareControls() {
  setOptions(controls.round, ROUND_LABELS, controls.round.value || "CN11");
  updateCompareRoundOptions();
  setOptions(controls.faction, [{ value: "", label: "全部阵营" }], "");
  controls.rankStart.value = controls.rankStart.value || "1";
  controls.rankEnd.value = controls.rankEnd.value || "100";
  controls.minCount.value = controls.minCount.value || "0";
  controls.sort.value = controls.sort.value || "desc";
  controls.changeDirection.value = controls.changeDirection.value || "all";
  controls.language.value = controls.language.value || "cn";
  setOptions(controls.metric, [
    { value: "rank", label: "官方名次" }, { value: "selection_count", label: "实际选择人数" },
    { value: "selection_rate", label: "选择率" }, { value: "points", label: "官方分数" },
    { value: "primary_rate", label: "第一顺位率" },
  ], "selection_count");
  setOptions(controls.xMetric, [
    { value: "arrangement_count", label: METRIC_LABELS.arrangement_count },
    { value: "arrangement_cumulative_count", label: METRIC_LABELS.arrangement_cumulative_count },
    { value: "arrangement_total_count", label: METRIC_LABELS.arrangement_total_count },
  ], "arrangement_cumulative_count");
  setOptions(controls.yMetric, [
    { value: "selection_count", label: METRIC_LABELS.selection_count },
    { value: "selection_rate", label: METRIC_LABELS.selection_rate },
    { value: "points", label: METRIC_LABELS.points }, { value: "rank", label: METRIC_LABELS.rank },
  ], "selection_count");
  controls.relationValueMode.value = controls.relationValueMode.value || "rate";
  controls.relationSort.value = controls.relationSort.value || "count";
  await updateKindAvailability();
  await updateQuestionOptions();
  try {
    await updateDesktopTemplateOptions();
  } catch (error) {
    setOptions(controls.template, [{ value: "", label: "静态模板快照不可用" }], "");
  }
  updateRelationMetricOptions();
  updateCustomMetricOptions();
  updateControlVisibility();
}

async function updateQuestionOptions() {
  try {
    const rows = await loadCSV("questionnaire");
    const round = controls.round.value;
    const selectedRounds = isDesktopMode() && controls.template.value === "q_custom"
      ? new Set([round, controls.compareRound.value])
      : new Set([round]);
    const keys = [...new Set(rows.filter((row) => selectedRounds.has(selectedRound(row))).map((row) => row.question_key).filter(Boolean))];
    const options = keys.sort((a, b) => labelForQuestion(a).localeCompare(labelForQuestion(b), "zh-CN"))
      .map((key) => ({ value: key, label: labelForQuestion(key) }));
    setOptions(controls.question, options.length ? options : [{ value: "age", label: "年龄分布（当前届无数据）" }], controls.question.value || (options[0] || {}).value);
  } catch (error) {
    setOptions(controls.question, [{ value: "age", label: "年龄分布（读取失败）" }], "age");
  }
}

function snapshotHasData(snapshot) {
  if (!snapshot || snapshot.error) return false;
  if (Array.isArray(snapshot.points)) return snapshot.points.length > 0;
  if (Array.isArray(snapshot.nodes)) return snapshot.nodes.length > 0;
  if (Array.isArray(snapshot.row_labels)) return snapshot.row_labels.length > 0 && (snapshot.col_labels || []).length > 0;
  if (Array.isArray(snapshot.categories)) {
    const values = (snapshot.series || []).flatMap((series) => series.values || []);
    return snapshot.categories.length > 0 && values.some((value) => value !== null && value !== undefined && value !== "");
  }
  return Array.isArray(snapshot.table_rows) && snapshot.table_rows.length > 0;
}

function selectedDesktopSnapshot(bundle, specKey = controls.template.value, round = controls.round.value, compare = controls.compareRound.value) {
  const pairs = bundle.pair_snapshots?.[specKey]?.[round];
  if (COMPARISON_TEMPLATE_KEYS.has(specKey) && compare && pairs?.[compare]) return pairs[compare];
  return bundle.snapshots?.[specKey]?.[round] || null;
}

function comparisonRounds() {
  const prefix = String(controls.round.value || "").slice(0, 2);
  return ROUND_LABELS.filter((label) => label.slice(0, 2) === prefix);
}

function updateCompareRoundOptions() {
  const options = comparisonRounds();
  const previous = controls.compareRound.value;
  const fallback = options.find((label) => label !== controls.round.value && label === previous)
    || options.filter((label) => label !== controls.round.value).slice(-1)[0]
    || options[0]
    || controls.round.value;
  setOptions(controls.compareRound, options, fallback);
  if (controls.compareRound.value === controls.round.value && options.length > 1) {
    controls.compareRound.value = options.find((label) => label !== controls.round.value) || controls.round.value;
  }
}

async function updateKindAvailability() {
  const cpOption = controls.kind.querySelector('option[value="cp"]');
  if (!cpOption) return;
  try {
    const rows = await loadCSV("cp");
    const hasCP = rows.some((row) => selectedRound(row) === controls.round.value && number(row.vote_count, null) !== null && number(row.vote_count, 0) > 0);
    cpOption.hidden = !hasCP;
    cpOption.disabled = !hasCP;
    if (!hasCP && controls.kind.value === "cp") controls.kind.value = "ranking";
  } catch (_) {
    // Keep the option visible if the small CP CSV cannot be read; refresh()
    // will report the actionable data-source error instead of hiding it.
    cpOption.hidden = false;
    cpOption.disabled = false;
  }
}

function updateFactionOptions(bundle) {
  const labels = Array.isArray(bundle.faction_options) ? bundle.faction_options : [];
  setOptions(controls.faction, [{ value: "", label: "全部阵营" }, ...labels.map((label) => ({ value: label, label }))], controls.faction.value || "");
}

function relationCategoryForTemplate(key = controls.template.value) {
  if (key === "r08_work_question_matrix") return "work";
  if (["r04_music_question_scatter", "r05_music_question_diff", "r06_music_question_corr", "r10_music_question_matrix"].includes(key)) return "music";
  return "character";
}

function updateRelationOptions(bundle) {
  const category = relationCategoryForTemplate();
  const questions = bundle.entity_question_options?.[controls.round.value]?.[category] || {};
  const keys = Object.keys(questions);
  const forcedQuestion = controls.template.value === "r07_character_cognition" ? "cognition" : controls.relationQuestion.value;
  const selectedQuestion = keys.includes(forcedQuestion) ? forcedQuestion : keys[0] || "";
  setOptions(controls.relationQuestion, keys.map((key) => ({ value: key, label: labelForQuestion(key) })), selectedQuestion);
  const answers = questions[controls.relationQuestion.value] || [];
  setOptions(controls.relationAnswer, answers.map((answer) => ({ value: answer, label: answer })), answers.includes(controls.relationAnswer.value) ? controls.relationAnswer.value : answers[0] || "");
}

function updateRelationMetricOptions() {
  const key = controls.template.value;
  const category = relationCategoryForTemplate(key);
  const relationMetric = ["r01_character_question_scatter", "r03_character_question_corr", "r04_music_question_scatter", "r06_music_question_corr", "r07_character_cognition"].includes(key);
  if (!relationMetric) return;
  const fields = category === "music"
    ? ["rank", "points", "selection_count", "selection_rate", "primary_rate"]
    : ["rank", "points", "selection_count", "selection_rate", "primary_rate", "female_rate"];
  setOptions(controls.xMetric, fields.map((field) => ({ value: field, label: METRIC_LABELS[field] || field })), fields.includes(controls.xMetric.value) ? controls.xMetric.value : "rank");
}

function updateCustomMetricOptions() {
  const key = controls.template.value;
  if (key === "x_covote") {
    const fields = ["intersection_count", "share", "lift", "excess_count", "phi", "asymmetry", "direction_a_to_b", "direction_b_to_a"];
    setOptions(controls.xMetric, fields.map((field) => ({ value: field, label: METRIC_LABELS[field] || field })), fields.includes(controls.xMetric.value) ? controls.xMetric.value : "intersection_count");
    setOptions(controls.yMetric, fields.map((field) => ({ value: field, label: METRIC_LABELS[field] || field })), fields.includes(controls.yMetric.value) ? controls.yMetric.value : "lift");
  } else if (key === "x_character") {
    const fields = ["rank", "points", "selection_count", "selection_rate", "primary_rate", "secondary_rate", "top2_rate", "female_rate"];
    setOptions(controls.xMetric, fields.map((field) => ({ value: field, label: METRIC_LABELS[field] || field })), fields.includes(controls.xMetric.value) ? controls.xMetric.value : "selection_count");
    setOptions(controls.yMetric, fields.map((field) => ({ value: field, label: METRIC_LABELS[field] || field })), fields.includes(controls.yMetric.value) ? controls.yMetric.value : "primary_rate");
  } else if (["m05_character_music_cross", "m06_music_character_cross", "m09_music_arrangement_cross", "m10_character_arrangement_cross"].includes(key)) {
    const characterFields = ["rank", "points", "selection_count", "selection_rate", "primary_rate", "secondary_rate", "top2_rate", "female_rate"];
    const musicFields = ["rank", "points", "selection_count", "selection_rate", "primary_rate", "comment_count", "arrangement_count", "arrangement_cumulative_count", "arrangement_total_count"];
    const arrangementFields = ["arrangement_count", "arrangement_cumulative_count", "arrangement_total_count"];
    const xFields = key === "m05_character_music_cross" ? characterFields : key === "m06_music_character_cross" ? musicFields : arrangementFields;
    const yFields = key === "m05_character_music_cross" ? musicFields : key === "m06_music_character_cross" ? characterFields : key === "m10_character_arrangement_cross" ? characterFields : ["rank", "points", "selection_count", "selection_rate", "primary_rate"];
    const xDefault = key === "m05_character_music_cross" || key === "m06_music_character_cross" ? "selection_count" : "arrangement_cumulative_count";
    const yDefault = key === "m05_character_music_cross" || key === "m06_music_character_cross" ? "selection_count" : "selection_count";
    setOptions(controls.xMetric, xFields.map((field) => ({ value: field, label: METRIC_LABELS[field] || field })), xFields.includes(controls.xMetric.value) ? controls.xMetric.value : xDefault);
    setOptions(controls.yMetric, yFields.map((field) => ({ value: field, label: METRIC_LABELS[field] || field })), yFields.includes(controls.yMetric.value) ? controls.yMetric.value : yDefault);
  }
}

function updateLightweightMetricOptions() {
  // Lightweight projects share the same axis controls with desktop custom
  // templates. Rebuild their option lists when switching projects so a
  // previous custom co-vote metric (for example `intersection_count`) cannot
  // leak into the arrangement view and produce an empty chart.
  if (currentMode() === "arrangement") {
    setOptions(controls.xMetric, [
      { value: "arrangement_count", label: METRIC_LABELS.arrangement_count },
      { value: "arrangement_cumulative_count", label: METRIC_LABELS.arrangement_cumulative_count },
      { value: "arrangement_total_count", label: METRIC_LABELS.arrangement_total_count },
    ], "arrangement_cumulative_count");
    setOptions(controls.yMetric, [
      { value: "selection_count", label: METRIC_LABELS.selection_count },
      { value: "selection_rate", label: METRIC_LABELS.selection_rate },
      { value: "points", label: METRIC_LABELS.points }, { value: "rank", label: METRIC_LABELS.rank },
    ], "selection_count");
  } else if (currentMode() === "ranking") {
    setOptions(controls.metric, [
      { value: "rank", label: "官方名次" }, { value: "selection_count", label: "实际选择人数" },
      { value: "selection_rate", label: "选择率" }, { value: "points", label: "官方分数" },
      { value: "primary_rate", label: "第一顺位率" },
    ], "selection_count");
  }
}

async function updateDesktopTemplateOptions() {
  const bundle = await loadBundle();
  const scope = desktopScope();
  const specs = bundle.template_specs.filter((spec) => {
    if (scope === "single") return DESKTOP_SINGLE_KEYS.has(spec.key);
    if (scope === "compare") return !DESKTOP_SINGLE_KEYS.has(spec.key);
    return true;
  }).filter((spec) => {
    // Hide templates that have no renderable source for the selected round.
    // A comparison template is checked against the selected pair, so CN/JP
    // questionnaire and co-vote gaps do not appear as misleading blank charts.
    const snapshot = selectedDesktopSnapshot(bundle, spec.key, controls.round.value, controls.compareRound.value);
    return snapshotHasData(snapshot);
  });
  const options = specs.map((spec) => ({ value: spec.key, label: `${spec.group}｜${spec.title}` }));
  const selected = controls.template.value;
  controls.template.innerHTML = "";
  const groups = new Map();
  specs.forEach((spec) => {
    const scopeLabel = DESKTOP_SINGLE_KEYS.has(spec.key) ? "单届结果" : "跨届/对比表";
    if (!groups.has(scopeLabel)) groups.set(scopeLabel, []);
    groups.get(scopeLabel).push(spec);
  });
  groups.forEach((items, groupLabel) => {
    const group = document.createElement("optgroup");
    group.label = groupLabel;
    items.forEach((spec) => {
      const option = document.createElement("option");
      option.value = spec.key;
      option.textContent = `${spec.group}｜${spec.title}`;
      group.appendChild(option);
    });
    controls.template.appendChild(group);
  });
  const available = options.some((item) => item.value === selected) ? selected : options[0]?.value;
  if (available) controls.template.value = available;
  updateFactionOptions(bundle);
  updateRelationOptions(bundle);
  updateRelationMetricOptions();
  updateCustomMetricOptions();
  updateCompareRoundOptions();
}

function sortRows(rows, metric) {
  return [...rows].sort((a, b) => {
    const av = number(a[metric], null), bv = number(b[metric], null);
    if (av === null && bv === null) return nameFor(a).localeCompare(nameFor(b), "zh-CN");
    if (av === null) return 1; if (bv === null) return -1;
    if (metric === "rank") return av - bv;
    return bv - av;
  });
}

function applySearch(rows) {
  const query = controls.search.value.trim().toLocaleLowerCase();
  return query ? rows.filter((row) => Object.values(row).join(" ").toLocaleLowerCase().includes(query)) : rows;
}

function rankingResult(rows) {
  const subject = controls.subject.value;
  const metric = controls.metric.value;
  const round = controls.round.value;
  const minimum = Math.max(0, integer(controls.minVotes.value, 0));
  let filtered = rows.filter((row) => selectedRound(row) === round);
  if (minimum > 0) filtered = filtered.filter((row) => number(row.selection_count, null) !== null && number(row.selection_count) >= minimum);
  filtered = applySearch(filtered);
  const sorted = sortRows(filtered, metric).slice(0, Math.max(3, Math.min(100, integer(controls.topN.value, 20))));
  const headers = ["名称", "官方名次", METRIC_LABELS[metric]];
  const tableFields = ["name", "rank", metric];
  if (metric !== "selection_count") { headers.push("实际选择人数"); tableFields.push("selection_count"); }
  headers.push("选择率", "来源"); tableFields.push("selection_rate", "source_type");
  const table = sorted.map((row) => tableFields.map((field) => field === "name" ? nameFor(row) : field === "rank" ? formatValue(row.rank, "rank") : field === "source_type" ? (row.source_type || "—") : formatValue(row[field], field)));
  return {
    title: `${round}｜${subject === "character" ? "角色" : "曲子"} × ${METRIC_LABELS[metric]}`,
    chartType: "bar", metric, rows: sorted,
    headers, table,
    note: minimum > 0 ? `已过滤实体实际选择人数低于 ${minimum.toLocaleString("zh-CN")} 的记录；缺失人数也不纳入。` : "空白指标表示该届原始来源没有公开，不是 0。",
    xLabel: "实体", yLabel: METRIC_LABELS[metric],
  };
}

function arrangementResult(rows) {
  const round = controls.round.value;
  const xMetric = controls.xMetric.value;
  const yMetric = controls.yMetric.value;
  const minimum = Math.max(0, integer(controls.minVotes.value, 0));
  let filtered = rows.filter((row) => selectedRound(row) === round);
  if (minimum > 0) filtered = filtered.filter((row) => number(row.selection_count, null) !== null && number(row.selection_count) >= minimum);
  filtered = applySearch(filtered);
  const valid = filtered.filter((row) => number(row[xMetric], null) !== null && number(row[yMetric], null) !== null);
  const sorted = sortRows(valid, xMetric).slice(0, Math.max(3, Math.min(100, integer(controls.topN.value, 20))));
  const tableHeaders = ["曲子", "官方名次", METRIC_LABELS[xMetric], METRIC_LABELS[yMetric]];
  const tableFields = ["name", "rank", xMetric, yMetric];
  // When the vertical metric is “actual selection count”, it is already the
  // next column.  Do not append the same field a second time under a slightly
  // different heading; the download uses the same de-duplicated shape.
  if (yMetric !== "selection_count") {
    tableHeaders.push("实际选择人数"); tableFields.push("selection_count");
  }
  if (xMetric !== "arrangement_total_count") {
    tableHeaders.push("同人曲总数（抓取时点）"); tableFields.push("arrangement_total_count");
  }
  const table = sorted.map((row) => tableFields.map((field) => field === "name" ? nameFor(row) : field === "rank" ? formatValue(row.rank, "rank") : formatValue(row[field], field)));
  return {
    title: `${round}｜曲子投票 × 同人曲数量`, chartType: "scatter", metric: yMetric, rows: sorted,
    xMetric, headers: tableHeaders, table,
    note: `横轴为 ${METRIC_LABELS[xMetric]}，纵轴为 ${METRIC_LABELS[yMetric]}。CN/JP 使用独立投票窗口；CN1/JP3 的届间新增和截至结束累计为空，不会伪造为 0。${minimum > 0 ? ` 已过滤实际选择人数低于 ${minimum.toLocaleString("zh-CN")} 的曲子。` : ""}`,
    xLabel: METRIC_LABELS[xMetric], yLabel: METRIC_LABELS[yMetric],
  };
}

async function musicConcentrationClusterResult() {
  const round = controls.round.value;
  const minimum = Math.max(0, integer(controls.minCount.value, 0));
  const sourceRows = await loadCSV("covote_pairs");
  const edges = sourceRows.filter((row) => selectedRound(row) === round && row.source_type === "cn10_11_official_music_covote_matrix")
    .map((row) => {
      const count = number(row.intersection_count, null), lift = number(row.lift, null);
      const a = String(row.name_a_cn || row.name_a || "").trim();
      const b = String(row.name_b_cn || row.name_b || "").trim();
      if (!a || !b || count === null || lift === null || count < minimum || lift < 1.2) return null;
      const expected = lift > 0 ? count / lift : count;
      return { a: `曲子:${a}`, b: `曲子:${b}`, label: `${a} × ${b}`, count, lift, excess: Math.max(0, count - expected) };
    }).filter(Boolean);
  if (!edges.length) {
    return { title: `音乐内部同投集中聚类（${round}）`, chartType: "network", source_label: "全量同投分卷 CSV", nodes: [], edges: [], headers: ["聚类", "节点数", "关系数", "集中度得分"], table: [], displayTable: [], note: `${round} 没有达到共同人数≥${minimum} 且集中倍数≥1.20 的公开音乐×音乐关系；当前音乐内部完整矩阵公开范围为 CN10–11。`, xLabel: "", yLabel: "" };
  }
  const parent = new Map();
  const find = (value) => { if (!parent.has(value)) parent.set(value, value); const root = parent.get(value); if (root === value) return root; const result = find(root); parent.set(value, result); return result; };
  const union = (a, b) => { const ra = find(a), rb = find(b); if (ra !== rb) parent.set(rb, ra); };
  edges.forEach((edge) => union(edge.a, edge.b));
  const groups = new Map();
  edges.forEach((edge) => { const key = find(edge.a); if (!groups.has(key)) groups.set(key, { nodes: new Set(), edges: [], score: 0 }); const group = groups.get(key); group.nodes.add(edge.a); group.nodes.add(edge.b); group.edges.push(edge); group.score += edge.excess; });
  const ordered = [...groups.values()].sort((a, b) => b.score - a.score || b.edges.length - a.edges.length).slice(0, Math.max(1, Math.min(100, integer(controls.topN.value, 20))));
  const nodes = [], outputEdges = [], table = [], edgeCandidates = [];
  ordered.forEach((group, index) => { const cluster = `C${index + 1}`; group.nodes.forEach((node) => nodes.push({ id: `${cluster}:${node}`, label: node, value: 1, cluster })); group.edges.forEach((edge) => edgeCandidates.push({ cluster, edge })); table.push([cluster, group.nodes.size, group.edges.length, group.score]); });
  // A single music component can contain hundreds of valid links.  Keep the
  // full edge list in the downloadable/table result, but draw only the
  // strongest links per component so the visual difference in co-vote depth
  // remains legible instead of becoming a solid knot of lines.
  const drawableEdges = [];
  const edgesByCluster = new Map();
  edgeCandidates.forEach((item) => { if (!edgesByCluster.has(item.cluster)) edgesByCluster.set(item.cluster, []); edgesByCluster.get(item.cluster).push(item); });
  edgesByCluster.forEach((items) => {
    items.sort((a, b) => b.edge.count - a.edge.count || b.edge.lift - a.edge.lift)
      .slice(0, 80).forEach((item) => drawableEdges.push(item));
  });
  drawableEdges.forEach(({ cluster, edge }) => outputEdges.push({ source: `${cluster}:${edge.a}`, target: `${cluster}:${edge.b}`, value: edge.count, lift: edge.lift, label: edge.label }));
  return { title: `音乐内部同投集中聚类（${round}）`, chartType: "network", layout: "music_cluster_grid", source_label: "全量同投分卷 CSV", nodes, edges: outputEdges, headers: ["聚类", "节点数", "关系数", "集中度得分"], table, displayTable: table.map((row) => [row[0], formatAxis(row[1], "", "integer"), formatAxis(row[2], "", "integer"), formatAxis(row[3], "", "number")]), note: `${round}｜音乐内部集中聚类：网页从完整分卷 CSV 读取，保留共同人数≥${minimum}且 lift≥1.20 的边；以边为相似关系做单链接连通分量，聚类得分为组件内 max(0,共同人数−期望人数) 之和。音乐内部矩阵目前公开 CN10–11；其他届次显示空白而不是 0。图表改用分面网格：每个聚类单独占一个面板，节点按网格展开，避免所有曲子扎在同一个圆环上。${edgeCandidates.length > drawableEdges.length ? ` 全量关系 ${edgeCandidates.length.toLocaleString("zh-CN")} 条，图表为避免手机卡顿仅绘制共同人数最高的 ${drawableEdges.length.toLocaleString("zh-CN")} 条；表格统计仍使用全量。` : ""}`, xLabel: "", yLabel: "" };
}

function cpResult(rows) {
  const round = controls.round.value;
  const minimum = Math.max(0, integer(controls.minVotes.value, 0));
  let filtered = rows.filter((row) => selectedRound(row) === round);
  if (minimum > 0) filtered = filtered.filter((row) => number(row.vote_count, null) !== null && number(row.vote_count) >= minimum);
  filtered = applySearch(filtered);
  const sorted = sortRows(filtered, "vote_count").slice(0, Math.max(3, Math.min(100, integer(controls.topN.value, 20))));
  return {
    title: `${round}｜CP 投票排行`, chartType: "bar", metric: "vote_count", rows: sorted,
    headers: ["组合", "官方名次", "CP投票人数", "CP投票比例", "成员数", "来源"],
    table: sorted.map((row) => [row.combination_label || nameFor(row), formatValue(row.rank, "rank"), formatValue(row.vote_count, "vote_count"), formatValue(row.vote_rate, "vote_rate"), formatValue(row.member_count, "count"), row.source_type || "—"]),
    note: `这里只显示官方 CP 表；同投替代数据属于独立口径，不会伪装成 CP 榜。${minimum > 0 ? ` 已过滤 CP 投票人数低于 ${minimum.toLocaleString("zh-CN")} 的组合。` : ""}`,
    xLabel: "CP 组合", yLabel: METRIC_LABELS.vote_count,
  };
}

function questionnaireResult(rows) {
  const round = controls.round.value;
  const question = controls.question.value;
  const filtered = rows.filter((row) => selectedRound(row) === round && row.question_key === question);
  const sorted = [...filtered].sort((a, b) => (number(b.rate, -1) - number(a.rate, -1))).slice(0, Math.max(3, Math.min(100, integer(controls.topN.value, 20))));
  return {
    title: `${round}｜${labelForQuestion(question)}｜问卷选项`, chartType: "bar", metric: "rate", rows: sorted,
    headers: ["选项", "回答人数", "比例", "题目键", "来源"],
    table: sorted.map((row) => [row.label || row.label_jp || row.node_path, formatValue(row.count, "count"), formatValue(row.rate, "rate"), row.question_key, row.region === "cn" ? "中文区问卷" : "日文区问卷"]),
    note: "比例分母是该题有效回答人数；多选题各项不要求合计 100%。题目与选项按地区/届次分别读取。",
    xLabel: "问卷选项", yLabel: "比例",
  };
}

async function customQuestionnaireCompareResult() {
  const rows = await loadCSV("questionnaire");
  const current = controls.round.value, compare = controls.compareRound.value, question = controls.question.value;
  const byLabel = new Map(), order = [];
  rows.filter((row) => [current, compare].includes(selectedRound(row)) && row.question_key === question).forEach((row) => {
    const label = row.label || row.label_jp || row.node_path || "未命名";
    if (!order.includes(label)) order.push(label);
    byLabel.set(`${label}|${selectedRound(row)}`, number(row.rate, null));
  });
  const ordered = order.map((label) => ({ label, compare: byLabel.get(`${label}|${compare}`), current: byLabel.get(`${label}|${current}`) }))
    .filter((row) => row.compare !== null || row.current !== null)
    .sort((a, b) => Math.max(number(b.current, -1), number(b.compare, -1)) - Math.max(number(a.current, -1), number(a.compare, -1)))
    .slice(0, Math.max(3, Math.min(100, integer(controls.topN.value, 20))));
  return {
    title: `${current} ↔ ${compare}｜${labelForQuestion(question)}｜问卷选项比例`, chartType: "dumbbell", metric: "rate",
    categories: ordered.map((row) => row.label), series: [{ name: compare, values: ordered.map((row) => row.compare) }, { name: current, values: ordered.map((row) => row.current) }],
    value_format: "percent", table_headers: ["选项", compare, current], table_rows: ordered.map((row) => [row.label, row.compare, row.current]),
    note: "中文区和日文区问卷题目、选项按真实公开数据分别读取；空白表示该届没有同名选项，不会填成 0。",
    xLabel: "比例", yLabel: "问卷选项", rows: ordered, headers: ["选项", compare, current], table: ordered.map((row) => [row.label, row.compare, row.current]), displayTable: ordered.map((row) => [row.label, formatAxis(row.compare, "", "percent"), formatAxis(row.current, "", "percent")]),
  };
}

async function questionnaireCompareResult(templateKey) {
  const rows = await loadCSV("questionnaire");
  const current = controls.round.value, compare = controls.compareRound.value;
  const limit = Math.max(3, Math.min(100, integer(controls.topN.value, 20)));
  const question = templateKey === "q01_age" ? "age" : templateKey === "q02_cognition" ? "cognition" : templateKey === "q03_usertype" ? "usertype" : "th21";
  const selected = rows.filter((row) => [current, compare].includes(selectedRound(row)) && row.question_key === question);
  const byLabel = new Map(), order = [];
  selected.forEach((row) => {
    const label = row.label || row.label_jp || row.node_path || "未命名";
    if (!order.includes(label)) order.push(label);
    byLabel.set(`${label}|${selectedRound(row)}`, { rate: number(row.rate, null), value: number(row.value, null) });
  });
  const ordered = order.map((label) => ({ label, compare: byLabel.get(`${label}|${compare}`)?.rate ?? null, current: byLabel.get(`${label}|${current}`)?.rate ?? null, order: byLabel.get(`${label}|${current}`)?.value ?? byLabel.get(`${label}|${compare}`)?.value ?? 999999 }))
    .filter((row) => row.compare !== null || row.current !== null)
    .sort((a, b) => a.order - b.order || a.label.localeCompare(b.label, "zh-CN"))
    .slice(0, limit);
  const title = templateKey === "q01_age" ? "年龄结构" : templateKey === "q02_cognition" ? "入坑时间" : templateKey === "q03_usertype" ? "参与东方方式" : "新作体验版";
  const note = `${current} ↔ ${compare}｜问卷题目与选项直接来自完整问卷 CSV；空白表示该届没有这道题或选项，不是 0。${templateKey === "q03_usertype" ? "多选题各项比例不要求合计100%。" : ""}`;
  return { title: `${current} ↔ ${compare}｜${title}比例`, chartType: "dumbbell", source_label: "全量问卷 CSV", metric: "rate", categories: ordered.map((row) => row.label), series: [{ name: compare, values: ordered.map((row) => row.compare) }, { name: current, values: ordered.map((row) => row.current) }], value_format: "percent", xLabel: "比例", yLabel: "问卷选项", rows: ordered, headers: ["选项", compare, current], table: ordered.map((row) => [row.label, row.compare, row.current]), displayTable: ordered.map((row) => [row.label, formatAxis(row.compare, "rate", "percent"), formatAxis(row.current, "rate", "percent")]), note };
}

function pearson(values) {
  if (values.length < 3) return null;
  const xs = values.map((item) => item[0]), ys = values.map((item) => item[1]);
  const mx = xs.reduce((sum, value) => sum + value, 0) / xs.length;
  const my = ys.reduce((sum, value) => sum + value, 0) / ys.length;
  const numerator = xs.reduce((sum, value, index) => sum + (value - mx) * (ys[index] - my), 0);
  const dx = Math.sqrt(xs.reduce((sum, value) => sum + (value - mx) ** 2, 0));
  const dy = Math.sqrt(ys.reduce((sum, value) => sum + (value - my) ** 2, 0));
  return dx && dy ? numerator / (dx * dy) : null;
}

function relationMetricFields(category) {
  return category === "music"
    ? ["rank", "points", "selection_count", "selection_rate", "primary_rate"]
    : ["rank", "points", "selection_count", "selection_rate", "primary_rate", "female_rate"];
}

function relationName(row) {
  return row?.name_cn || row?.name_jp || row?.canonical_name || row?.entity_name || "未命名";
}

function formatRelationTable(rows, formats = []) {
  return rows.map((row) => row.map((cell, index) => {
    if (cell === null || cell === undefined || cell === "" || index === 0) return cell ?? "";
    return formatAxis(cell, "", formats[index] || "number");
  }));
}

/**
 * Rebuild entity-questionnaire templates from the full gzip CSV in the
 * browser.  The desktop JSON remains a fallback for old/offline deployments,
 * but CN10/CN11 can now switch between their real question and answer labels
 * instead of showing the build-time default (usually JP “女性”/age).
 */
async function entityQuestionnaireResult(templateKey) {
  const current = controls.round.value;
  const category = templateKey === "r08_work_question_matrix"
    ? "work" : ["r04_music_question_scatter", "r05_music_question_diff", "r06_music_question_corr", "r10_music_question_matrix"].includes(templateKey) ? "music" : "character";
  const entityRows = await loadCSV("entity_questionnaire");
  const question = templateKey === "r07_character_cognition" ? "cognition" : controls.relationQuestion.value;
  const answer = controls.relationAnswer.value || "";
  const metricRows = category === "music" ? await loadCSV("music") : category === "character" ? await loadCSV("character") : [];
  const metrics = new Map(metricRows.filter((row) => selectedRound(row) === current).map((row) => [String(row.canonical_name || ""), row]));
  const threshold = Math.max(0, integer(controls.minVotes.value, 0));
  const metric = relationMetricFields(category).includes(controls.xMetric.value) ? controls.xMetric.value : "rank";
  let rows = entityRows.filter((row) => selectedRound(row) === current && row.category === category && row.question_key === question && row.answer_label);
  const matrixTemplate = ["r08_work_question_matrix", "r09_character_question_matrix", "r10_music_question_matrix"].includes(templateKey);
  if (answer && !["r03_character_question_corr", "r06_music_question_corr"].includes(templateKey) && !matrixTemplate) rows = rows.filter((row) => row.answer_label === answer);
  if (category !== "work" && threshold > 0) rows = rows.filter((row) => {
    const entity = metrics.get(String(row.canonical_name || ""));
    const count = number(entity?.selection_count, null);
    return count !== null && count >= threshold;
  });
  const selectedAnswerLabel = answer || "全部选项";
  const titleBase = category === "music" ? "曲子" : category === "work" ? "作品" : "角色";
  const questionTitle = labelForQuestion(question);
  const commonNote = `${current}｜${questionTitle}：${selectedAnswerLabel}；实体问卷按当前地区/届次读取完整 CSV，中文区和日文区不会合并。${category !== "work" && threshold > 0 ? ` 已过滤实体实际选择人数低于 ${threshold.toLocaleString("zh-CN")} 的记录。` : ""}`;

  if (["r01_character_question_scatter", "r04_music_question_scatter", "r07_character_cognition"].includes(templateKey)) {
    const mode = controls.relationValueMode.value || "rate";
    const points = rows.map((row) => {
      const entity = metrics.get(String(row.canonical_name || ""));
      const x = number(entity?.[metric], null);
      const y = number(mode === "difference" ? row.difference_points : row.rate, null);
      if (!entity || x === null || y === null) return null;
      const label = relationName(entity);
      return { label, x, y, count: number(row.count, 0), rate: number(row.rate, null), overallRate: number(row.overall_rate, null), difference: number(row.difference_points, null), size: number(row.denominator, 0), subtitle: `${number(row.count, 0).toLocaleString("zh-CN")}人｜${(number(row.rate, 0) * 100).toFixed(2)}%`, tooltipPairs: [["官方名次", formatValue(entity.rank, "rank")], [METRIC_LABELS[metric] || metric, formatValue(entity[metric], metric)], ["该选项人数", formatValue(row.count, "count")], ["该实体比例", formatValue(row.rate, "rate")], ["相对全体差值", formatValue(row.difference_points, "number")]] };
    }).filter(Boolean);
    const sort = controls.relationSort.value || "count";
    points.sort((a, b) => sort === "rate" ? b.y - a.y : sort === "difference" ? Math.abs(b.y) - Math.abs(a.y) : b.count - a.count);
    const limited = points.slice(0, Math.max(3, Math.min(100, integer(controls.topN.value, 20))));
    const tableRows = limited.map((point) => [point.label, point.x, point.count, point.rate, point.overallRate, point.difference, point.size]);
    return {
      title: `${titleBase}投票结果 × 问卷选项（${current}）`, chartType: "scatter", metric, source_label: "全量实体问卷 CSV",
      xMetric: metric, value_format: mode === "difference" ? "number" : "percent", x_format: metric === "rank" ? "rank" : relationMetricFields(category).includes(metric) && metric.endsWith("_rate") ? "percent" : "number", y_format: mode === "difference" ? "number" : "percent",
      points: limited, rows: limited, headers: ["名称", "投票指标", "该选项人数", "该实体比例", "全体比例", "相对全体差值（百分点）", "问卷有效人数"], table: tableRows, displayTable: formatRelationTable(tableRows, ["", metric === "rank" ? "rank" : "number", "integer", "percent", "percent", "number", "integer"]),
      note: `${commonNote} 横轴为 ${METRIC_LABELS[metric] || metric}，纵轴为${mode === "difference" ? "相对全体差值" : "问卷选项比例"}；点大小为该题有效问卷人数。`, xLabel: METRIC_LABELS[metric] || metric, yLabel: mode === "difference" ? "相对全体差值（百分点）" : "问卷选项比例",
    };
  }

  if (["r02_character_question_diff", "r05_music_question_diff"].includes(templateKey)) {
    const grouped = new Map();
    rows.forEach((row) => {
      const entity = metrics.get(String(row.canonical_name || ""));
      const value = number(row.difference_points, null);
      if (entity && value !== null) grouped.set(relationName(entity), value);
    });
    const sorted = [...grouped.entries()].sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, Math.max(3, Math.min(100, integer(controls.topN.value, 20))));
    const table = sorted.map(([label, value]) => [label, value]);
    return { title: `${titleBase}问卷倾向排行（${current}）`, chartType: "bar", metric: "difference_points", source_label: "全量实体问卷 CSV", categories: sorted.map(([label]) => label), series: [{ name: "相对全体差值（百分点）", values: sorted.map(([, value]) => value), value_field: "difference_points" }], rows: sorted.map(([label, value]) => ({ label, value })), headers: ["名称", "相对全体差值（百分点）"], table, displayTable: formatRelationTable(table, ["", "number"]), note: `${commonNote} 正数表示高于全体比例，单位为百分点。`, xLabel: titleBase, yLabel: "相对全体差值（百分点）" };
  }

  if (["r03_character_question_corr", "r06_music_question_corr"].includes(templateKey)) {
    const grouped = new Map();
    rows.forEach((row) => {
      const entity = metrics.get(String(row.canonical_name || ""));
      const x = number(entity?.[metric], null), y = number(row.rate, null);
      if (x !== null && y !== null) { if (!grouped.has(row.answer_label)) grouped.set(row.answer_label, []); grouped.get(row.answer_label).push([x, y]); }
    });
    const sorted = [...grouped.entries()].map(([label, values]) => [label, pearson(values), values.length]).filter(([, value]) => value !== null).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, Math.max(3, Math.min(100, integer(controls.topN.value, 20))));
    const table = sorted.map(([label, value, n]) => [label, value, n]);
    return { title: `${titleBase}投票指标与问卷各项相关系数（${current}）`, chartType: "bar", metric: "correlation", source_label: "全量实体问卷 CSV", categories: sorted.map(([label]) => label), series: [{ name: "皮尔逊相关系数", values: sorted.map(([, value]) => value), value_field: "correlation" }], rows: sorted.map(([label, value]) => ({ label, value })), headers: ["问卷选项", "相关系数", "实体数 N"], table, displayTable: formatRelationTable(table, ["", "number", "integer"]), note: `${commonNote} 横轴使用 ${METRIC_LABELS[metric] || metric}；相关不代表因果。`, xLabel: "问卷选项", yLabel: "皮尔逊相关系数" };
  }

  // The matrix templates use every answer actually published for the selected
  // question.  Missing cells remain null so the renderer can hatch/leave them
  // blank instead of implying zero responses.
  const answers = [...new Set(rows.map((row) => row.answer_label))];
  const entities = [...new Set(rows.map((row) => String(row.canonical_name || row.entity_name || "")).filter(Boolean))];
  const entityRank = (key) => number(metrics.get(key)?.rank, 999999);
  entities.sort((a, b) => category === "work" ? a.localeCompare(b, "zh-CN") : entityRank(a) - entityRank(b));
  const limitedEntities = entities.slice(0, Math.max(3, Math.min(100, integer(controls.topN.value, 20))));
  const lookup = new Map(rows.map((row) => [`${row.canonical_name || row.entity_name}|${row.answer_label}`, number(row.rate, null)]));
  const matrix = limitedEntities.map((entity) => answers.map((item) => lookup.get(`${entity}|${item}`) ?? null));
  const labels = limitedEntities.map((entity) => relationName(metrics.get(entity) || { canonical_name: entity }));
  const table = labels.map((label, index) => [label, ...matrix[index]]);
  return { title: `${titleBase} × ${questionTitle}｜比例矩阵（${current}）`, chartType: "heatmap", source_label: "全量实体问卷 CSV", row_labels: labels, col_labels: answers, matrix, value_format: "percent", table_headers: ["名称", ...answers], table_rows: table, headers: ["名称", ...answers], table, displayTable: formatRelationTable(table, ["", ...answers.map(() => "percent")]), note: `${commonNote} 每行是一个实体，每列是该问题的实际公开选项；空白格表示没有公开数据，不是 0。`, xLabel: "问卷选项", yLabel: titleBase };
}

async function crossConcentrationClusterResult() {
  const round = controls.round.value;
  const minimum = Math.max(0, integer(controls.minCount.value, 0));
  const sourceRows = await loadCSV("character_music_covote");
  const edges = sourceRows.filter((row) => selectedRound(row) === round)
    .map((row) => {
      const count = number(row.intersection_count, null), lift = number(row.lift, null);
      const a = String(row.character_name_cn || row.character_name_jp || "").trim();
      const b = String(row.music_name_cn || row.music_name_jp || "").trim();
      if (!a || !b || count === null || lift === null || count < minimum || lift < 1.2) return null;
      return { a: `角色:${a}`, b: `曲子:${b}`, label: `${a} × ${b}`, count, lift, excess: Math.max(0, count - (lift > 0 ? count / lift : count)) };
    }).filter(Boolean);
  if (!edges.length) {
    return { title: `跨部门同投集中聚类（${round}）`, chartType: "network", source_label: "全量跨部门同投 CSV", nodes: [], edges: [], headers: ["聚类", "节点数", "关系数", "集中度得分"], table: [], displayTable: [], note: `${round} 没有达到共同人数≥${minimum} 且集中倍数≥1.20 的公开角色×曲子关系；空白不是 0。`, xLabel: "", yLabel: "" };
  }
  const parent = new Map();
  const find = (value) => { if (!parent.has(value)) parent.set(value, value); const root = parent.get(value); if (root === value) return value; const result = find(root); parent.set(value, result); return result; };
  const union = (a, b) => { const ra = find(a), rb = find(b); if (ra !== rb) parent.set(rb, ra); };
  edges.forEach((edge) => union(edge.a, edge.b));
  const groups = new Map();
  edges.forEach((edge) => { const key = find(edge.a); if (!groups.has(key)) groups.set(key, { nodes: new Set(), edges: [], score: 0 }); const group = groups.get(key); group.nodes.add(edge.a); group.nodes.add(edge.b); group.edges.push(edge); group.score += edge.excess; });
  const ordered = [...groups.values()].sort((a, b) => b.score - a.score || b.edges.length - a.edges.length).slice(0, Math.max(1, Math.min(100, integer(controls.topN.value, 20))));
  const nodes = [], outputEdges = [], table = [], edgeCandidates = [];
  ordered.forEach((group, index) => { const cluster = `C${index + 1}`; group.nodes.forEach((node) => nodes.push({ id: `${cluster}:${node}`, label: node, value: 1, cluster })); group.edges.forEach((edge) => edgeCandidates.push({ cluster, edge })); table.push([cluster, group.nodes.size, group.edges.length, group.score]); });
  const drawableEdges = edgeCandidates.sort((a, b) => b.edge.count - a.edge.count || b.edge.lift - a.edge.lift).slice(0, 5000);
  drawableEdges.forEach(({ cluster, edge }) => outputEdges.push({ source: `${cluster}:${edge.a}`, target: `${cluster}:${edge.b}`, value: edge.count, lift: edge.lift, label: edge.label }));
  return { title: `跨部门同投集中聚类（${round}）`, chartType: "network", layout: "cluster_grid", source_label: "全量跨部门同投 CSV", nodes, edges: outputEdges, headers: ["聚类", "节点数", "关系数", "集中度得分"], table, displayTable: table.map((row) => [row[0], formatAxis(row[1], "", "integer"), formatAxis(row[2], "", "integer"), formatAxis(row[3], "", "number")]), note: `${round}｜角色×音乐跨部门集中聚类：网页从全量 CSV 读取，保留共同人数≥${minimum}且 lift≥1.20 的边；以边为相似关系做单链接连通分量，聚类得分为组件内 max(0,共同人数−期望人数) 之和。图表改用按聚类分面的网格布局，避免大型聚类挤成一个圆环；${edgeCandidates.length > drawableEdges.length ? `全量关系 ${edgeCandidates.length.toLocaleString("zh-CN")} 条，图表为避免手机卡顿仅绘制共同人数最高的 ${drawableEdges.length.toLocaleString("zh-CN")} 条；表格统计仍使用全量。` : "关系线使用完整保留集合。"}`, xLabel: "", yLabel: "" };
}

function covoteRoundRows(rows, round) {
  return rows.filter((row) => selectedRound(row) === round && isCharacterPairRow(row));
}

async function loadCovoteContext(round) {
  const [pairRows, characterRows] = await Promise.all([loadCSV("covote_pairs"), loadCSV("character")]);
  const metrics = characterRows.filter((row) => selectedRound(row) === round);
  const aliasMap = new Map();
  metrics.forEach((row) => {
    const key = normalizeName(row.canonical_name || row.name_cn || row.name_jp);
    if (!key) return;
    entityAliases(row).forEach((alias) => aliasMap.set(alias, key));
  });
  return { rows: covoteRoundRows(pairRows, round), metrics, aliasMap };
}

function filteredCovoteRows(rows, metrics, aliasMap, options = {}) {
  const rankStart = Math.max(1, integer(controls.rankStart.value, 1));
  const rankEnd = Math.max(rankStart, integer(controls.rankEnd.value, 2000));
  const minimum = Math.max(0, integer(controls.minCount.value, 0));
  const query = controls.search.value.trim().toLocaleLowerCase();
  // The faction selector belongs only to the character network.  Do not let
  // a previously selected faction silently constrain bubbles, matrices or
  // other co-vote projects after the user switches templates.
  const faction = controls.template.value === "a02_network" ? (controls.faction.value || "") : "";
  const allowed = new Map();
  metrics.forEach((row) => {
    const rank = number(row.rank, null);
    const key = normalizeName(row.canonical_name || row.name_cn || row.name_jp);
    if (!key) return;
    // A faction is already a complete role cohort. Do not apply the generic
    // rank window here: otherwise a faction whose members all rank below the
    // default range produces an empty network before its edges are considered.
    if (faction) {
      if ((row.faction_labels || []).includes(faction)) allowed.set(key, row);
      return;
    }
    if (rank !== null && rank >= rankStart && rank <= rankEnd) allowed.set(key, row);
  });
  const output = [];
  rows.forEach((row) => {
    const a = aliasMap.get(pairAliases(row, "a")[0]) || pairAliases(row, "a").map((value) => aliasMap.get(value)).find(Boolean);
    const b = aliasMap.get(pairAliases(row, "b")[0]) || pairAliases(row, "b").map((value) => aliasMap.get(value)).find(Boolean);
    if (!a || !b) return;
    const aRow = allowed.get(a), bRow = allowed.get(b);
    const either = options.rangeMode === "either";
    if ((!aRow || !bRow) && !either) return;
    if (either && !aRow && !bRow) return;
    const count = number(row.intersection_count, null);
    if (count === null || count < minimum) return;
    if (faction) {
      // Faction labels are attached from the complete role×faction crosswalk
      // before this filter runs; the 20-node static snapshot is not required.
      if (!(aRow?.faction_labels || []).includes(faction) || !(bRow?.faction_labels || []).includes(faction)) return;
    }
    const label = pairLabel(row, controls.language.value || "cn");
    if (query && !`${label} ${row.name_a || ""} ${row.name_b || ""}`.toLocaleLowerCase().includes(query)) return;
    output.push({ ...row, __a: a, __b: b, __aRow: aRow, __bRow: bRow, __label: label });
  });
  return output;
}

function dynamicMetricFormat(field) {
  if (field === "rank" || field.endsWith("_rank")) return "rank";
  if (field.endsWith("_rate") || ["share", "direction_a_to_b", "direction_b_to_a", "asymmetry"].includes(field)) return "percent";
  if (["intersection_count", "excess_count", "count_a", "count_b", "ballots"].includes(field) || field.endsWith("_count")) return "integer";
  return "number";
}

function dynamicCovoteTableRows(rows, field, language) {
  return rows.map((row) => [row.__label || pairLabel(row, language), row[field]]);
}

async function dynamicCovoteResult(templateKey) {
  const round = controls.round.value;
  const language = controls.language.value || "cn";
  const { rows: sourceRows, metrics, aliasMap } = await loadCovoteContext(round);
  let factionRows = [];
  try { factionRows = await loadCSV("factions"); } catch (_) { /* optional crosswalk fallback below */ }
  // Faction labels come from the complete role×faction CSV.  Only fall back
  // to the old 20-node snapshot when an older deployment lacks that CSV.
  const factionByAlias = new Map();
  const merge = (alias, labels) => {
    if (!alias || !labels.length) return;
    factionByAlias.set(alias, [...new Set([...(factionByAlias.get(alias) || []), ...labels])]);
  };
  factionRows.forEach((row) => entityAliases(row).forEach((alias) => merge(alias, factionLabels(row))));
  if (!factionRows.length) {
    try {
      const bundle = await loadBundle();
      const factionNodes = bundle.snapshots?.a02_network?.[round]?.nodes || [];
      factionNodes.forEach((node) => entityAliases({ canonical_name: node.id, name_cn: node.label, name_jp: node.label }).forEach((alias) => merge(alias, factionLabels(node))));
    } catch (_) { /* faction filtering remains empty when no crosswalk is available */ }
  }
  metrics.forEach((row) => { row.faction_labels = factionByAlias.get(normalizeName(row.canonical_name || row.name_cn || row.name_jp)) || factionByAlias.get(normalizeName(row.name_cn)) || []; });
  const filtered = filteredCovoteRows(sourceRows, metrics, aliasMap);
  const limit = topNLimit(templateKey);
  const selectedMetrics = new Map(metrics.map((row) => [normalizeName(row.canonical_name || row.name_cn || row.name_jp), row]));

  if (["a01_direction_matrix", "a01_count_matrix"].includes(templateKey)) {
    // Read the complete role metric list first.  The old implementation had
    // an additional hard-coded 30-role cap here, so a Top-100 request still
    // rendered a Top-30 matrix even though the source CSV contained more
    // eligible roles.  The rank window remains an explicit user filter; Top N
    // is now the only final display slice, shared by both matrix dimensions.
    const entities = metrics.filter((row) => {
      const rank = number(row.rank, null); return rank !== null && rank >= Math.max(1, integer(controls.rankStart.value, 1)) && rank <= Math.max(1, integer(controls.rankEnd.value, 2000));
    }).sort((a, b) => number(a.rank, 999999) - number(b.rank, 999999)).slice(0, limit);
    const keys = entities.map((row) => normalizeName(row.canonical_name || row.name_cn || row.name_jp));
    const labels = entities.map((row) => `#${Math.round(number(row.rank, 0))} ${row.name_cn || row.name_jp || row.canonical_name}`);
    const pairMap = new Map();
    filteredCovoteRows(sourceRows, metrics, aliasMap, { rangeMode: "either" }).forEach((row) => pairMap.set(pairKey(row.__a, row.__b), row));
    const matrix = keys.map((rowKey, ri) => keys.map((colKey, ci) => {
      if (ri === ci) return null;
      const row = pairMap.get(pairKey(rowKey, colKey));
      if (!row) return null;
      if (templateKey === "a01_count_matrix") return number(row.intersection_count, null);
      const aKey = row.__a;
      return aKey === rowKey ? number(row.direction_a_to_b, null) : number(row.direction_b_to_a, null);
    }));
    const field = templateKey === "a01_count_matrix" ? "intersection_count" : "direction_a_to_b";
    const headers = ["名称", ...labels];
    const table = labels.map((label, index) => [label, ...matrix[index]]);
    return { title: `${templateKey === "a01_count_matrix" ? "共同人数" : "方向同投率"}矩阵（${round}）`, chartType: "heatmap", source_label: "全量同投分卷 CSV", row_labels: labels, col_labels: labels, matrix, value_format: templateKey === "a01_count_matrix" ? "integer" : "percent", metric: field, headers, table, displayTable: table.map((r) => r.map((v, i) => i === 0 ? v : formatAxis(v, field, templateKey === "a01_count_matrix" ? "integer" : "percent"))), note: `${round}｜角色同投矩阵按当前名次范围读取完整同投分卷；斜线/空白表示没有公开关系，不是 0。${sourceRows.length.toLocaleString("zh-CN")} 条分卷记录中仅使用角色×角色来源。`, xLabel: "角色", yLabel: "角色" };
  }

  if (templateKey === "a02_network") {
    // Top N is the ranked role cohort for the network.  Build this cohort
    // before selecting edges; otherwise a Top-100 request can accidentally
    // keep only the handful of roles that happen to occur in the first 20
    // relationships.  A faction filter narrows the cohort but does not make
    // isolated members disappear from the node list.
    const selectedFaction = controls.faction.value || "";
    const rankedRows = metrics.filter((row) => {
      const rank = number(row.rank, null); const key = normalizeName(row.canonical_name || row.name_cn || row.name_jp);
      if (!key) return false;
      if (selectedFaction) return (row.faction_labels || []).includes(selectedFaction);
      return rank !== null && rank >= Math.max(1, integer(controls.rankStart.value, 1)) && rank <= Math.max(1, integer(controls.rankEnd.value, 100));
    }).sort((a, b) => number(a.rank, 999999) - number(b.rank, 999999));
    const cohortRows = selectedFaction ? rankedRows : rankedRows.slice(0, limit);
    const allowed = new Map(cohortRows.map((row) => [normalizeName(row.canonical_name || row.name_cn || row.name_jp), row]));
    const nodes = [...allowed.entries()].map(([id, row]) => ({ id, label: row.name_cn || row.name_jp || row.canonical_name, value: number(row.selection_count, 0), rank: number(row.rank, null), factions: row.faction_labels || [] }));
    const selectedIds = new Set(allowed.keys());
    const edges = filtered.filter((row) => selectedIds.has(row.__a) && selectedIds.has(row.__b)).map((row) => ({ source: row.__a, target: row.__b, value: number(row.intersection_count, 0), lift: number(row.lift, null), label: row.__label }));
    edges.sort((a, b) => b.value - a.value || (b.lift || 0) - (a.lift || 0));
    // Top N defines the ranked role cohort; drawing a different number of
    // edges made the SVG disagree with the control. Keep the table and graph
    // on the same strongest-relationship set. The
    // selected role cohort remains visible even when a role has no retained
    // edge after the threshold/search filters.
    const tableEdges = edges.slice(0, limit);
    const graphEdges = tableEdges;
    return { title: `角色同投关联网络（${round}）`, chartType: "network", source_label: "全量同投分卷 CSV", nodes, edges: graphEdges, headers: ["关系", "共同人数", "集中倍数"], table: tableEdges.map((e) => [e.label, e.value, e.lift]), displayTable: tableEdges.map((e) => [e.label, formatAxis(e.value, "intersection_count", "integer"), formatAxis(e.lift, "lift", "number")]), note: `${round}｜${selectedFaction ? `阵营筛选直接使用该阵营的完整角色集合（${nodes.length} 个角色），不受 Top N 或默认名次范围截断；` : `Top N 先选择按名次排序的 ${nodes.length} 个角色；`}表格和图表再共同使用其中共同人数最高的 ${graphEdges.length} 条关系。无关系角色仍保留为节点，名称只标注少量高连接角色，其余可悬停查看。${selectedFaction ? `当前阵营筛选：${selectedFaction}。` : ""}`, xLabel: "", yLabel: "" };
  }

  if (templateKey === "a03_bubble") {
    const points = filtered.filter((row) => number(row.lift, null) !== null && number(row.intersection_count, null) > 0).sort((a, b) => number(b.intersection_count, 0) - number(a.intersection_count, 0)).slice(0, limit).map((row) => ({ label: row.__label, x: number(row.intersection_count), y: number(row.lift), size: Math.max(0, number(row.phi, 0)), highlight: false, anomaly: String(row.anomaly).toLowerCase() === "true", subtitle: `${Math.round(number(row.intersection_count, 0)).toLocaleString("zh-CN")}人｜${number(row.lift, 0).toFixed(2)}×` }));
    return { title: `共同人数 × 集中倍数（${round}）`, chartType: "bubble", source_label: "全量同投分卷 CSV", points, rows: points, metric: "lift", xMetric: "intersection_count", value_format: "number", x_format: "integer", y_format: "number", x_log: true, y_reference: 1, xLabel: "共同投票人数", yLabel: "同投集中倍数", headers: ["关系", "共同人数", "集中倍数", "φ", "异常"], table: points.map((p) => [p.label, p.x, p.y, p.size, p.anomaly ? "是" : "否"]), displayTable: points.map((p) => [p.label, formatAxis(p.x, "intersection_count", "integer"), formatAxis(p.y, "lift", "number"), formatAxis(p.size, "phi", "number"), p.anomaly ? "是" : "否"]), note: `${round}｜横轴共同人数使用对数尺度，气泡大小为正向 φ；图中只标注最大的 10 个气泡，其余关系可悬停或在结果表中查看；少数票高倍数关系应结合共同人数一起判断。` };
  }

  if (["a03_count_top", "a06_lift", "a07_excess", "a08_phi", "a11_asymmetry", "a14_count_top10", "a15_lift_top10"].includes(templateKey)) {
    const fields = { a03_count_top: "intersection_count", a14_count_top10: "intersection_count", a06_lift: "lift", a15_lift_top10: "lift", a07_excess: "excess_count", a08_phi: "phi", a11_asymmetry: "asymmetry" };
    const field = fields[templateKey];
    const candidates = filtered.filter((row) => number(row[field], null) !== null).map((row) => field === "asymmetry" ? { ...row, __metricValue: Math.abs(number(row[field])) } : { ...row, __metricValue: number(row[field]) });
    const ordered = candidates.sort((a, b) => controls.sort.value === "asc" ? a.__metricValue - b.__metricValue : controls.sort.value === "abs" || field === "asymmetry" ? b.__metricValue - a.__metricValue : b.__metricValue - a.__metricValue).slice(0, limit);
    const fmt = dynamicMetricFormat(field);
    return { title: `${METRIC_LABELS[field] || field}${field === "asymmetry" ? "绝对值" : ""}（${round}）`, chartType: "bar", source_label: "全量同投分卷 CSV", metric: "__metricValue", rows: ordered.map((row) => ({ label: row.__label, value: row.__metricValue })), categories: ordered.map((row) => row.__label), series: [{ name: field === "asymmetry" ? "方向比例差绝对值" : (METRIC_LABELS[field] || field), values: ordered.map((row) => row.__metricValue) }], value_format: fmt, xLabel: "角色关系", yLabel: field === "asymmetry" ? "方向比例差绝对值" : (METRIC_LABELS[field] || field), headers: ["关系", field === "asymmetry" ? "方向比例差绝对值" : METRIC_LABELS[field] || field], table: ordered.map((row) => [row.__label, row.__metricValue]), displayTable: ordered.map((row) => [row.__label, formatAxis(row.__metricValue, field, fmt)]), note: `${round}｜从完整角色同投分卷计算；空白指标不是 0。${controls.minCount.value > 0 ? ` 已过滤共同人数低于 ${controls.minCount.value} 的关系。` : ""}` };
  }

  if (["a04_count_dumbbell", "a04_count_change", "a05_largest_change", "a09_phi_change", "a10_direction", "a11_asymmetry", "a13_quadrant"].includes(templateKey)) {
    const compare = controls.compareRound.value;
    const compareContext = await loadCovoteContext(compare);
    const currentRows = filteredCovoteRows(sourceRows, metrics, aliasMap);
    const previousRows = filteredCovoteRows(compareContext.rows, compareContext.metrics, compareContext.aliasMap);
    const prevMap = new Map(previousRows.map((row) => [pairKey(row.__a, row.__b), row]));
    const joined = currentRows.map((row) => ({ current: row, previous: prevMap.get(pairKey(row.__a, row.__b)) })).filter((item) => item.previous);
    if (templateKey === "a04_count_dumbbell") {
      const selected = joined.sort((a, b) => number(b.current.intersection_count) - number(a.current.intersection_count)).slice(0, limit);
      const categories = selected.map((item) => item.current.__label);
      const series = [{ name: compare, values: selected.map((i) => number(i.previous.intersection_count, null)) }, { name: round, values: selected.map((i) => number(i.current.intersection_count, null)) }];
      return { title: `${round} ↔ ${compare}｜两届同投人数`, chartType: "dumbbell", source_label: "全量同投分卷 CSV", metric: "intersection_count", categories, series, value_format: "integer", xLabel: "共同人数", yLabel: "角色关系", headers: ["关系", compare, round], table: selected.map((i) => [i.current.__label, i.previous.intersection_count, i.current.intersection_count]), displayTable: selected.map((i) => [i.current.__label, formatAxis(i.previous.intersection_count, "intersection_count", "integer"), formatAxis(i.current.intersection_count, "intersection_count", "integer")]), note: "仅显示两届都公开的同一角色关系；网页按完整分卷 CSV 重新连接。" };
    }
    if (templateKey === "a10_direction") {
      const selected = joined.sort((a, b) => Math.abs(number(b.current.asymmetry, 0)) - Math.abs(number(a.current.asymmetry, 0))).slice(0, limit);
      return { title: `${round}｜方向同投率`, chartType: "dumbbell", source_label: "全量同投分卷 CSV", metric: "direction_a_to_b", categories: selected.map((i) => i.current.__label), series: [{ name: "A→B", values: selected.map((i) => i.current.direction_a_to_b) }, { name: "B→A", values: selected.map((i) => i.current.direction_b_to_a) }], value_format: "percent", xLabel: "方向同投率", yLabel: "角色关系", headers: ["关系", "A→B", "B→A"], table: selected.map((i) => [i.current.__label, i.current.direction_a_to_b, i.current.direction_b_to_a]), displayTable: selected.map((i) => [i.current.__label, formatAxis(i.current.direction_a_to_b, "direction_a_to_b", "percent"), formatAxis(i.current.direction_b_to_a, "direction_b_to_a", "percent")]), note: "方向分母分别是 A 与 B 的实体选择人数，两个方向不要求相等。" };
    }
    if (templateKey === "a13_quadrant") {
      const points = joined.map((i) => ({ label: i.current.__label, x: number(i.current.share, 0) - number(i.previous.share, 0), y: number(i.current.lift, 0) - number(i.previous.lift, 0), size: number(i.current.intersection_count, 0) })).sort((a, b) => Math.abs(b.x) + Math.abs(b.y) - Math.abs(a.x) - Math.abs(a.y)).slice(0, limit);
      return { title: `${round} ↔ ${compare}｜同投整体变化四象限`, chartType: "scatter", source_label: "全量同投分卷 CSV", points, rows: points, metric: "lift", xMetric: "share", xLabel: "同投占比变化", yLabel: "集中倍数变化", value_format: "number", x_format: "percent", y_format: "number", headers: ["关系", "同投占比变化", "集中倍数变化", "当前共同人数"], table: points.map((p) => [p.label, p.x, p.y, p.size]), displayTable: points.map((p) => [p.label, formatAxis(p.x, "share", "percent"), formatAxis(p.y, "lift", "number"), formatAxis(p.size, "intersection_count", "integer")]), note: "横轴是同投占比变化，纵轴是集中倍数变化；仅比较两届都公开的关系。" };
    }
    const changeField = templateKey === "a09_phi_change" ? "phi" : "intersection_count";
    const ordered = joined.map((i) => ({ label: i.current.__label, value: number(i.current[changeField], 0) - number(i.previous[changeField], 0) })).filter((r) => controls.changeDirection.value === "positive" ? r.value > 0 : controls.changeDirection.value === "negative" ? r.value < 0 : true).sort((a, b) => templateKey === "a05_largest_change" || controls.sort.value === "abs" ? Math.abs(b.value) - Math.abs(a.value) : controls.sort.value === "asc" ? a.value - b.value : b.value - a.value).slice(0, limit);
    const fmt = changeField === "phi" ? "number" : "integer";
    return { title: `${round} ↔ ${compare}｜${changeField === "phi" ? "φ变化" : "共同人数变化"}`, chartType: "bar", source_label: "全量同投分卷 CSV", metric: "value", rows: ordered, categories: ordered.map((r) => r.label), series: [{ name: "变化", values: ordered.map((r) => r.value) }], value_format: fmt, xLabel: "角色关系", yLabel: "变化", headers: ["关系", "变化"], table: ordered.map((r) => [r.label, r.value]), displayTable: ordered.map((r) => [r.label, formatAxis(r.value, "", fmt)]), note: "只纳入两届都公开的同一角色关系；正数表示当前届较对比届增加。" };
  }

  if (templateKey === "a12_cumulative") {
    const totals = new Map();
    filtered.forEach((row) => {
      const excess = number(row.excess_count, null); if (excess === null || excess <= 0) return;
      [[row.__a, row.__aRow], [row.__b, row.__bRow]].forEach(([key, entity]) => {
        const label = entity?.name_cn || entity?.name_jp || key; const current = totals.get(key) || { label, value: 0 }; current.value += excess; totals.set(key, current);
      });
    });
    const ordered = [...totals.values()].sort((a, b) => b.value - a.value).slice(0, limit);
    return { title: `角色关系超额累计（${round}）`, chartType: "bar", source_label: "全量同投分卷 CSV", metric: "value", rows: ordered, categories: ordered.map((r) => r.label), series: [{ name: "正向超额累计", values: ordered.map((r) => r.value) }], value_format: "integer", xLabel: "角色", yLabel: "正向超额累计", headers: ["角色", "正向超额累计"], table: ordered.map((r) => [r.label, r.value]), displayTable: ordered.map((r) => [r.label, formatAxis(r.value, "", "integer")]), note: `${round}｜每名角色把参与关系的 max(0,共同人数−人气期望) 累计；期望由公开 lift 反推。` };
  }

  if (templateKey === "a16_anomalies") {
    const ordered = filtered.filter((row) => String(row.anomaly).toLowerCase() === "true" || number(row.anomaly_difference, 0) > 0).sort((a, b) => number(b.anomaly_difference, 0) - number(a.anomaly_difference, 0)).slice(0, limit);
    return { title: `官方异常数据（${round}）`, chartType: "bar", source_label: "全量同投分卷 CSV", metric: "anomaly_difference", rows: ordered.map((r) => ({ label: r.__label, value: r.anomaly_difference })), categories: ordered.map((r) => r.__label), series: [{ name: "双向人数差", values: ordered.map((r) => r.anomaly_difference) }], value_format: "integer", xLabel: "角色关系", yLabel: "双向人数差", headers: ["关系", "双向人数差"], table: ordered.map((r) => [r.__label, r.anomaly_difference]), displayTable: ordered.map((r) => [r.__label, formatAxis(r.anomaly_difference, "", "integer")]), note: "异常表示官网公开的 A→B 与 B→A 共同人数不一致，不等于关系特别强。" };
  }

  if (templateKey === "x_covote") {
    const xField = ["intersection_count", "share", "lift", "excess_count", "phi", "asymmetry", "direction_a_to_b", "direction_b_to_a"].includes(controls.xMetric.value) ? controls.xMetric.value : "intersection_count";
    const yField = ["intersection_count", "share", "lift", "excess_count", "phi", "asymmetry", "direction_a_to_b", "direction_b_to_a"].includes(controls.yMetric.value) ? controls.yMetric.value : "lift";
    const points = filtered.filter((r) => number(r[xField], null) !== null && number(r[yField], null) !== null).sort((a, b) => number(b[xField], 0) - number(a[xField], 0)).slice(0, limit).map((r) => ({ label: r.__label, x: number(r[xField]), y: number(r[yField]), size: number(r.intersection_count, 0), tooltipPairs: [[METRIC_LABELS[xField] || xField, formatAxis(r[xField], xField, dynamicMetricFormat(xField))], [METRIC_LABELS[yField] || yField, formatAxis(r[yField], yField, dynamicMetricFormat(yField))], ["共同人数", formatAxis(r.intersection_count, "intersection_count", "integer")]] }));
    const xLabel = METRIC_LABELS[xField] || xField;
    const yLabel = METRIC_LABELS[yField] || yField;
    const includeSize = xField !== "intersection_count" && yField !== "intersection_count";
    const headers = ["关系", xLabel, yLabel, ...(includeSize ? ["点大小：共同人数"] : [])];
    const table = points.map((p) => [p.label, p.x, p.y, ...(includeSize ? [p.size] : [])]);
    const displayTable = points.map((p) => [p.label, formatAxis(p.x, xField, dynamicMetricFormat(xField)), formatAxis(p.y, yField, dynamicMetricFormat(yField)), ...(includeSize ? [formatAxis(p.size, "intersection_count", "integer")] : [])]);
    return { title: `自定义同投指标（${round}）`, chartType: "scatter", source_label: "全量同投分卷 CSV", points, rows: points, metric: yField, xMetric: xField, xLabel, yLabel, x_format: dynamicMetricFormat(xField), y_format: dynamicMetricFormat(yField), headers, table, displayTable, note: `横轴和纵轴均从完整角色同投分卷即时计算；散点旁仅标注共同人数最高的 ${Math.min(8, points.length)} 个关系，其余关系可悬停或查看结果表。${includeSize ? "点大小表示共同人数。" : "当前坐标轴已使用共同人数，因此不再重复显示点大小列。"}` };
  }

  return null;
}

function metricNameFor(row, language = controls.language.value || "cn") {
  return language === "jp"
    ? (row.name_jp || row.name_cn || row.canonical_name || "未命名")
    : (row.name_cn || row.name_jp || row.canonical_name || "未命名");
}

function metricRowKey(row) {
  return normalizeName(row.canonical_name || row.name_cn || row.name_jp || row.combination_key || row.combination_label);
}

function metricRowsForRound(rows, round) {
  return rows.filter((row) => selectedRound(row) === round);
}

function metricRowsFiltered(rows) {
  const rankStart = Math.max(1, integer(controls.rankStart.value, 1));
  const rankEnd = Math.max(rankStart, integer(controls.rankEnd.value, 2000));
  const query = controls.search.value.trim().toLocaleLowerCase();
  return rows.filter((row) => {
    const rank = number(row.rank, null);
    if (rank !== null && (rank < rankStart || rank > rankEnd)) return false;
    if (query && !`${row.canonical_name || ""} ${row.name_cn || ""} ${row.name_jp || ""} ${row.combination_label || ""}`.toLocaleLowerCase().includes(query)) return false;
    return true;
  });
}

function metricOrdered(items, getter, direction = controls.sort.value || "desc") {
  return [...items].sort((a, b) => {
    const av = number(getter(a), null), bv = number(getter(b), null);
    if (av === null && bv === null) return metricNameFor(a).localeCompare(metricNameFor(b), "zh-CN");
    if (av === null) return 1;
    if (bv === null) return -1;
    if (direction === "asc") return av - bv;
    if (direction === "abs") return Math.abs(bv) - Math.abs(av);
    return bv - av;
  });
}

function metricTitle(snapshot, fallback, suffix) {
  return `${snapshot?.title || fallback}${suffix ? `（${suffix}）` : ""}`;
}

function metricBarResult({ title, items, field, label, format = dynamicMetricFormat(field), note = "", chartType = "bar", sourceLabel = "全量指标 CSV" }) {
  const limit = Math.max(3, Math.min(100, integer(controls.topN.value, 20)));
  const selected = items.slice(0, limit);
  const categories = selected.map((row) => metricNameFor(row));
  const values = selected.map((row) => number(row.__value, null));
  const table = selected.map((row) => [metricNameFor(row), row.__value]);
  return {
    title, chartType, source_label: sourceLabel, metric: "__value", rows: selected.map((row) => ({ label: metricNameFor(row), value: row.__value })),
    categories, series: [{ name: label, values }], value_format: format, xLabel: "实体", yLabel: label,
    headers: ["名称", label], table, displayTable: table.map((row) => [row[0], formatAxis(row[1], field, format)]), note,
  };
}

function crossMetricField(value, allowed, fallback) {
  return allowed.includes(value) ? value : fallback;
}

function crossLinkRowsForRound(rows, round) {
  return rows.filter((row) => selectedRound(row) === round && row.character_canonical && row.music_canonical);
}

function dynamicCrossNote(snapshot, suffix) {
  return `${snapshot?.note || ""} ${suffix} Top N 仅在最终显示阶段切片。`.trim();
}

async function dynamicCrossResult(templateKey, bundle) {
  if (!DYNAMIC_CROSS_TEMPLATE_KEYS.has(templateKey)) return null;
  const current = controls.round.value;
  const compare = controls.compareRound.value;
  const snapshot = selectedDesktopSnapshot(bundle, templateKey, current, compare) || {};
  const limit = Math.max(3, Math.min(100, integer(controls.topN.value, 20)));
  const language = controls.language.value || "cn";
  const characterFields = ["rank", "points", "selection_count", "selection_rate", "primary_rate", "secondary_rate", "top2_rate", "female_rate"];
  const musicFields = ["rank", "points", "selection_count", "selection_rate", "primary_rate", "comment_count", "arrangement_count", "arrangement_cumulative_count", "arrangement_total_count"];

  if (templateKey === "m05_character_music_cross" || templateKey === "m06_music_character_cross" || templateKey === "m08_character_carryover" || templateKey === "m10_character_arrangement_cross") {
    const [metricRows, linkRows] = await Promise.all([loadCSV("character"), loadCSV("character_music_links")]);
    const links = crossLinkRowsForRound(linkRows, current);
    const filteredMetrics = metricRowsFiltered(metricRowsForRound(metricRows, current));

    if (templateKey === "m05_character_music_cross") {
      const xField = crossMetricField(controls.xMetric.value, characterFields, "selection_count");
      const yField = crossMetricField(controls.yMetric.value, musicFields, "selection_count");
      const byCharacter = new Map();
      links.forEach((link) => {
        const key = normalizeName(link.character_canonical);
        if (!key) return;
        if (!byCharacter.has(key)) byCharacter.set(key, []);
        byCharacter.get(key).push(number(link[`music_${yField}`], null));
      });
      const items = filteredMetrics.map((character) => {
        const values = (byCharacter.get(metricRowKey(character)) || []).filter((value) => value !== null);
        const avg = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
        const x = number(character[xField], null);
        return x === null || avg === null ? null : { character, x, y: avg, count: values.length };
      }).filter(Boolean).sort((a, b) => xField === "rank" ? a.x - b.x : b.x - a.x).slice(0, limit);
      const points = items.map(({ character, x, y, count }) => ({ label: metricNameFor(character, language), x, y, size: count, subtitle: `${count} 首关联曲` }));
      const table = items.map(({ character, x, y, count }) => [metricNameFor(character, language), character.rank, x, y, count]);
      return { title: `${snapshot.title || "角色人气 × 关联曲人气"}（${current}）`, chartType: "scatter", source_label: "全量角色—曲子打标 CSV", points, rows: points, metric: "__y", xMetric: xField, xLabel: METRIC_LABELS[xField] || xField, yLabel: `关联曲平均${METRIC_LABELS[yField] || yField}`, x_format: dynamicMetricFormat(xField), y_format: "number", headers: ["角色", "角色官方名次", METRIC_LABELS[xField] || xField, `关联曲平均${METRIC_LABELS[yField] || yField}`, "关联曲数量"], table, displayTable: table.map((row) => [row[0], formatAxis(row[1], "rank", "rank"), formatAxis(row[2], xField, dynamicMetricFormat(xField)), formatAxis(row[3], yField, "number"), formatAxis(row[4], "count", "integer")]), note: dynamicCrossNote(snapshot, "每个点是一名角色；关联曲平均值和关联数量均从全量打标关系即时汇总。") };
    }

    if (templateKey === "m06_music_character_cross") {
      const xField = crossMetricField(controls.xMetric.value, musicFields, "selection_count");
      const yField = crossMetricField(controls.yMetric.value, characterFields, "selection_count");
      const musicRows = await loadCSV("music");
      const filteredMusic = metricRowsFiltered(metricRowsForRound(musicRows, current));
      const byMusic = new Map();
      links.forEach((link) => {
        const key = normalizeName(link.music_canonical);
        if (!key) return;
        if (!byMusic.has(key)) byMusic.set(key, []);
        byMusic.get(key).push(number(link[`character_${yField}`], null));
      });
      const items = filteredMusic.map((music) => {
        const values = (byMusic.get(metricRowKey(music)) || []).filter((value) => value !== null);
        const avg = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
        const x = number(music[xField], null);
        return x === null || avg === null ? null : { music, x, y: avg, count: values.length };
      }).filter(Boolean).sort((a, b) => xField === "rank" ? a.x - b.x : b.x - a.x).slice(0, limit);
      const points = items.map(({ music, x, y, count }) => ({ label: metricNameFor(music, language), x, y, size: count, subtitle: `${count} 个所属角色` }));
      const table = items.map(({ music, x, y, count }) => [metricNameFor(music, language), music.rank, x, y, count]);
      return { title: `${snapshot.title || "曲子人气 × 所属角色人气"}（${current}）`, chartType: "scatter", source_label: "全量角色—曲子打标 CSV", points, rows: points, metric: "__y", xMetric: xField, xLabel: METRIC_LABELS[xField] || xField, yLabel: `所属角色平均${METRIC_LABELS[yField] || yField}`, x_format: dynamicMetricFormat(xField), y_format: "number", headers: ["曲子", "曲子官方名次", METRIC_LABELS[xField] || xField, `所属角色平均${METRIC_LABELS[yField] || yField}`, "所属角色数量"], table, displayTable: table.map((row) => [row[0], formatAxis(row[1], "rank", "rank"), formatAxis(row[2], xField, dynamicMetricFormat(xField)), formatAxis(row[3], yField, "number"), formatAxis(row[4], "count", "integer")]), note: dynamicCrossNote(snapshot, "每个点是一首曲子；所属角色平均值和关联数量均从全量打标关系即时汇总。") };
    }

    if (templateKey === "m08_character_carryover") {
      const byCharacter = new Map();
      links.forEach((link) => {
        const value = number(link.music_selection_rate, null);
        const key = normalizeName(link.character_canonical);
        if (key && value !== null) {
          if (!byCharacter.has(key)) byCharacter.set(key, []);
          byCharacter.get(key).push(value);
        }
      });
      const items = filteredMetrics.map((character) => {
        const values = byCharacter.get(metricRowKey(character)) || [];
        const own = number(character.selection_rate, null);
        if (!values.length || own === null || own === 0) return null;
        const avg = values.reduce((sum, value) => sum + value, 0) / values.length;
        return { character, own, avg, count: values.length, index: avg / own };
      }).filter(Boolean).sort((a, b) => b.avg - a.avg).slice(0, limit);
      const points = items.map(({ character, own, avg, count, index }) => ({ label: metricNameFor(character, language), x: own, y: avg, size: count, subtitle: `${count}首｜连带倍数 ${index.toFixed(2)}×` }));
      const table = items.map(({ character, own, avg, count, index }) => [metricNameFor(character, language), character.rank, own, avg, count, index]);
      return { title: `${snapshot.title || "角色连带效应"}（${current}）`, chartType: "scatter", source_label: "全量角色—曲子打标 CSV", points, rows: points, metric: "__y", xMetric: "selection_rate", xLabel: "角色选择率", yLabel: "关联曲平均选择率", x_format: "percent", y_format: "percent", headers: ["角色", "官方名次", "角色选择率", "关联曲平均选择率", "关联曲数量", "角色连带指数"], table, displayTable: table.map((row) => [row[0], formatAxis(row[1], "rank", "rank"), formatAxis(row[2], "selection_rate", "percent"), formatAxis(row[3], "selection_rate", "percent"), formatAxis(row[4], "count", "integer"), formatAxis(row[5], "lift", "number")]), note: dynamicCrossNote(snapshot, "关联曲来自全量打标关系；连带倍数=关联曲平均选择率÷角色选择率，它描述关联强弱，不证明因果。") };
    }

    if (templateKey === "m10_character_arrangement_cross") {
      const musicRows = new Map();
      links.forEach((link) => {
        const key = normalizeName(link.character_canonical);
        const musicKey = normalizeName(link.music_canonical);
        const x = number(link.music_arrangement_cumulative_count, null);
        if (!key || !musicKey || x === null) return;
        if (!musicRows.has(key)) musicRows.set(key, new Map());
        musicRows.get(key).set(musicKey, link);
      });
      const xField = crossMetricField(controls.xMetric.value, ["arrangement_count", "arrangement_cumulative_count", "arrangement_total_count"], "arrangement_cumulative_count");
      const yField = crossMetricField(controls.yMetric.value, characterFields, "selection_count");
      const items = filteredMetrics.map((character) => {
        const linksForCharacter = [...(musicRows.get(metricRowKey(character))?.values() || [])].filter((link) => number(link[`music_${xField}`], null) !== null);
        const y = number(character[yField], null);
        if (!linksForCharacter.length || y === null) return null;
        const sum = (field) => linksForCharacter.reduce((total, link) => total + (number(link[field], 0) || 0), 0);
        return { character, x: sum(`music_${xField}`), y, count: linksForCharacter.length, windowTotal: sum("music_arrangement_count"), historicalTotal: sum("music_arrangement_cumulative_count"), crawlTotal: sum("music_arrangement_total_count"), undated: sum("music_undated_arrangement_count") };
      }).filter(Boolean).sort((a, b) => b.x - a.x).slice(0, limit);
      const points = items.map((item) => ({ label: metricNameFor(item.character, language), x: item.x, y: item.y, rank: item.character.rank, size: item.count, subtitle: `${item.count} 首关联原曲｜${METRIC_LABELS[xField]} ${item.x.toLocaleString("zh-CN")} 首` }));
      const table = items.map((item) => [metricNameFor(item.character, language), item.character.rank, item.x, item.y, item.count, item.windowTotal, item.historicalTotal, item.crawlTotal, item.undated]);
      const yLabel = METRIC_LABELS[yField] || yField;
      return { title: `${snapshot.title || "角色投票 × 关联原曲同人曲数量"}（${current}）`, chartType: "scatter", source_label: "全量角色—曲子打标 CSV", points, rows: points, metric: "__y", xMetric: xField, xLabel: `关联原曲${METRIC_LABELS[xField] || xField}`, yLabel, x_format: "integer", y_format: dynamicMetricFormat(yField), headers: ["角色", "官方名次", `关联原曲${METRIC_LABELS[xField] || xField}`, yLabel, "关联原曲数", "届间新增合计", "截至投票结束累计合计", "抓取时点累计合计", "未标日期同人曲数"], table, displayTable: table.map((row) => [row[0], formatAxis(row[1], "rank", "rank"), formatAxis(row[2], xField, "integer"), formatAxis(row[3], yField, dynamicMetricFormat(yField)), formatAxis(row[4], "count", "integer"), formatAxis(row[5], "count", "integer"), formatAxis(row[6], "count", "integer"), formatAxis(row[7], "count", "integer"), formatAxis(row[8], "count", "integer")]), note: dynamicCrossNote(snapshot, "按角色—原曲 canonical key 去重后，从全量打标关系汇总所选同人曲口径。") };
    }
  }

  if (templateKey === "m07_character_music_covote") {
    const rows = await loadCSV("character_music_covote");
    const rankStart = Math.max(1, integer(controls.rankStart.value, 1));
    const rankEnd = Math.max(rankStart, integer(controls.rankEnd.value, 100));
    const query = controls.search.value.trim().toLocaleLowerCase();
    const candidates = rows.filter((row) => {
      if (selectedRound(row) !== current) return false;
      const rank = number(row.character_rank, null);
      if (rank === null || rank < rankStart || rank > rankEnd) return false;
      const label = `${row.character_name_cn || row.character_name_jp || ""} × ${row.music_name_cn || row.music_name_jp || ""}`;
      return (!query || `${label} ${row.character_name_jp || ""} ${row.music_name_jp || ""}`.toLocaleLowerCase().includes(query)) && number(row.intersection_count, null) !== null && number(row.conditional_rate, null) !== null;
    }).sort((a, b) => number(b.intersection_count, 0) - number(a.intersection_count, 0)).slice(0, limit);
    const points = candidates.map((row) => {
      const character = language === "jp" ? (row.character_name_jp || row.character_name_cn) : (row.character_name_cn || row.character_name_jp);
      const music = language === "jp" ? (row.music_name_jp || row.music_name_cn) : (row.music_name_cn || row.music_name_jp);
      return { label: `${character} × ${music}`, x: number(row.intersection_count), y: number(row.conditional_rate), size: Math.max(number(row.lift, 0), 0), subtitle: `${number(row.intersection_count).toLocaleString("zh-CN")}人｜${(number(row.conditional_rate) * 100).toFixed(2)}%` };
    });
    const table = candidates.map((row) => [language === "jp" ? (row.character_name_jp || row.character_name_cn) : (row.character_name_cn || row.character_name_jp), language === "jp" ? (row.music_name_jp || row.music_name_cn) : (row.music_name_cn || row.music_name_jp), row.intersection_count, row.conditional_rate, row.music_overall_rate, row.lift]);
    return { title: `${snapshot.title || "角色—曲子同投人数与同投率"}（${current}）`, chartType: "scatter", source_label: "全量角色—曲子同投 CSV", points, rows: points, metric: "conditional_rate", xMetric: "intersection_count", xLabel: "同投人数", yLabel: "角色条件下同投率", x_format: "integer", y_format: "percent", headers: ["角色", "曲子", "同投人数", "角色条件下同投率", "曲子总体选择率", "连带倍数"], table, displayTable: table.map((row) => [row[0], row[1], formatAxis(row[2], "intersection_count", "integer"), formatAxis(row[3], "rate", "percent"), formatAxis(row[4], "rate", "percent"), formatAxis(row[5], "lift", "number")]), note: dynamicCrossNote(snapshot, "仅显示官方公开的条件排行；未公开的角色—曲子组合不是 0。") };
  }

  if (templateKey === "m09_music_arrangement_cross") {
    const rows = metricRowsFiltered(metricRowsForRound(await loadCSV("music"), current));
    const xField = crossMetricField(controls.xMetric.value, ["arrangement_count", "arrangement_cumulative_count", "arrangement_total_count"], "arrangement_cumulative_count");
    const requestedY = crossMetricField(controls.yMetric.value, musicFields, "selection_count");
    const effectiveY = requestedY === "selection_count" && !rows.some((row) => number(row.selection_count, null) !== null) ? "points" : requestedY;
    const items = rows.map((music) => {
      const x = number(music[xField], null);
      const y = number(music[effectiveY], null);
      if (x === null || y === null) return null;
      return { music, x, y, size: number(music.selection_count, null) };
    }).filter(Boolean).sort((a, b) => b.x - a.x).slice(0, limit);
    const points = items.map(({ music, x, y, size }) => ({ label: metricNameFor(music, language), x, y, rank: music.rank, size: size === null ? null : Math.max(size, 0), subtitle: `${METRIC_LABELS[xField]} ${x.toLocaleString("zh-CN")} 首｜${METRIC_LABELS[effectiveY] || effectiveY} ${y.toLocaleString("zh-CN")}` }));
    const duplicateSize = effectiveY !== "selection_count";
    const table = items.map(({ music, x, y, size }) => [metricNameFor(music, language), music.rank, x, y, ...(duplicateSize ? [size] : [])]);
    const headers = ["曲子", "官方名次", METRIC_LABELS[xField] || xField, METRIC_LABELS[effectiveY] || effectiveY, ...(duplicateSize ? ["实际选择人数"] : [])];
    return { title: `${snapshot.title || "曲子投票 × 同人曲数量"}（${current}）`, chartType: "scatter", source_label: "全量曲子指标 CSV", points, rows: points, metric: effectiveY, xMetric: xField, xLabel: METRIC_LABELS[xField] || xField, yLabel: METRIC_LABELS[effectiveY] || effectiveY, x_format: "integer", y_format: dynamicMetricFormat(effectiveY), headers, table, displayTable: table.map((row) => [row[0], formatAxis(row[1], "rank", "rank"), formatAxis(row[2], xField, "integer"), formatAxis(row[3], effectiveY, dynamicMetricFormat(effectiveY)), ...(duplicateSize ? [formatAxis(row[4], "selection_count", "integer")] : [])]), note: dynamicCrossNote(snapshot, "曲子指标和同人曲口径均从全量曲子指标 CSV 读取；未匹配或未公开的数量保持空白。") };
  }

  if (templateKey === "p01_cp_metric") {
    const rows = await loadCSV("cp");
    const rankStart = Math.max(1, integer(controls.rankStart.value, 1));
    const rankEnd = Math.max(rankStart, integer(controls.rankEnd.value, 100));
    const query = controls.search.value.trim().toLocaleLowerCase();
    const items = rows.filter((row) => {
      if (selectedRound(row) !== current) return false;
      const rank = number(row.rank, null);
      if (rank === null || rank < rankStart || rank > rankEnd) return false;
      return !query || `${row.combination_label || ""} ${row.name_a || ""} ${row.name_b || ""} ${row.name_c || ""}`.toLocaleLowerCase().includes(query);
    }).filter((row) => number(row.vote_count, null) !== null).sort((a, b) => number(b.vote_count, 0) - number(a.vote_count, 0)).slice(0, limit);
    const table = items.map((row) => [row.combination_label || [row.name_a, row.name_b, row.name_c].filter(Boolean).join(" × "), row.vote_count, "官方CP"]);
    return { title: `${snapshot.title || "CP投票结果排行"}（${current}）`, chartType: "bar", source_label: "全量 CP 指标 CSV", metric: "vote_count", categories: table.map((row) => row[0]), series: [{ name: "CP投票/组合人数", values: table.map((row) => row[1]) }], value_format: "integer", xLabel: "组合", yLabel: "CP投票/组合人数", headers: ["组合", "CP投票/组合人数", "来源"], table, displayTable: table.map((row) => [row[0], formatAxis(row[1], "vote_count", "integer"), row[2]]), rows: items.map((row) => ({ label: row.combination_label || nameFor(row), value: row.vote_count })), note: dynamicCrossNote(snapshot, "官方 CP 指标从全量 CP CSV 读取；Top N 仅在最终显示阶段切片。") };
  }

  if (templateKey === "p02_combination_compare") {
    const rows = await loadCSV("combination");
    const rankStart = Math.max(1, integer(controls.rankStart.value, 1));
    const rankEnd = Math.max(rankStart, integer(controls.rankEnd.value, 100));
    const query = controls.search.value.trim().toLocaleLowerCase();
    const filterRound = (round) => rows.filter((row) => {
      if (selectedRound(row) !== round) return false;
      const rank = number(row.rank, null);
      if (rank !== null && (rank < rankStart || rank > rankEnd)) return false;
      return !query || String(row.combination_label || "").toLocaleLowerCase().includes(query);
    });
    const currentRows = new Map(filterRound(current).map((row) => [row.combination_key || row.combination_label, row]));
    const compareRows = new Map(filterRound(compare).map((row) => [row.combination_key || row.combination_label, row]));
    const items = [...new Set([...currentRows.keys(), ...compareRows.keys()])].map((key) => {
      const currentRow = currentRows.get(key), compareRow = compareRows.get(key), row = currentRow || compareRow;
      return { label: row?.combination_label || key, compare: number(compareRow?.comparison_count, null), current: number(currentRow?.comparison_count, null), compareSource: compareRow?.data_source || "", currentSource: currentRow?.data_source || "" };
    }).sort((a, b) => number(b.current, number(b.compare, 0)) - number(a.current, number(a.compare, 0))).slice(0, limit);
    const sourceLabel = (source) => source === "official_cp" ? "官方CP" : source === "co-vote_fallback" ? "同投替代" : "无公开数据";
    const table = items.map((item) => [item.label, item.compare, item.current, sourceLabel(item.compareSource), sourceLabel(item.currentSource), item.compare !== null && item.current !== null ? item.current - item.compare : null]);
    return { title: `${snapshot.title || "所有组合跨届对比"}（${current} ↔ ${compare}）`, chartType: "dumbbell", source_label: "全量组合指标 CSV", categories: items.map((item) => item.label), series: [{ name: compare, values: items.map((item) => item.compare) }, { name: current, values: items.map((item) => item.current) }], value_format: "integer", xLabel: "组合对比人数", yLabel: "组合", headers: ["组合", compare, current, "对比届来源", "当前届来源", "差值"], table, displayTable: table.map((row) => [row[0], formatAxis(row[1], "comparison_count", "integer"), formatAxis(row[2], "comparison_count", "integer"), row[3], row[4], formatAxis(row[5], "comparison_count", "integer")]), rows: items, note: dynamicCrossNote(snapshot, "官方 CP 优先；缺少 CP 的届次使用同投人数替代，并在结果表标记来源。") };
  }

  return null;
}

async function dynamicMetricResult(templateKey, bundle) {
  if (!DYNAMIC_METRIC_TEMPLATE_KEYS.has(templateKey)) return null;
  const current = controls.round.value;
  const compare = controls.compareRound.value;
  const snapshot = selectedDesktopSnapshot(bundle, templateKey, current, compare) || {};
  const limit = Math.max(3, Math.min(100, integer(controls.topN.value, 20)));
  const language = controls.language.value || "cn";
  const kind = templateKey.startsWith("m") ? "music" : "character";
  const sourceLabel = kind === "music" ? "全量曲子指标 CSV" : "全量角色指标 CSV";
  const allRows = await loadCSV(kind);
  const currentRows = metricRowsFiltered(metricRowsForRound(allRows, current));
  const titleSuffix = current;

  const singleSpecs = kind === "character" ? {
    c02_selection_top: ["selection_count", "实际选择人数", "integer"],
    c03_primary_rate: ["primary_rate", "第一顺位率", "percent"],
    c04_secondary_rate: ["secondary_rate", "第二顺位率", "percent"],
    c05_top2_rate: ["top2_rate", "前两顺位集中率", "percent"],
    c12_gender_lean: ["__gender_lean", "女性比例－全体女性比例", "percent"],
  } : {
    m01_metric: ["selection_count", "实际选择人数", "integer"],
    m04_primary_rate: ["primary_rate", "第一顺位率", "percent"],
  };
  if (singleSpecs[templateKey]) {
    const [field, label, format] = singleSpecs[templateKey];
    const items = metricOrdered(currentRows.map((row) => ({ ...row, __value: field === "__gender_lean" ? number(row.female_rate, null) === null || number(row.overall_female_rate, null) === null ? null : number(row.female_rate) - number(row.overall_female_rate) : row[field] }))
      .filter((row) => number(row.__value, null) !== null), (row) => row.__value);
    return metricBarResult({ title: metricTitle(snapshot, label, titleSuffix), items, field, label, format, sourceLabel, note: snapshot.note || "从完整指标 CSV 读取；Top N 仅在最终显示阶段切片。" });
  }

  if (templateKey === "c02_equal_rank") {
    const items = metricOrdered(currentRows.filter((row) => number(row.rank, null) !== null), (row) => row.rank, "asc").slice(0, limit);
    const categories = items.map((row) => metricNameFor(row, language));
    const series = [{ name: "官方规则", values: items.map((row) => number(row.rank, null)) }, { name: "等权票数", values: items.map((row) => number(row.equal_rank, null)) }];
    const table = items.map((row) => [metricNameFor(row, language), row.rank, row.equal_rank]);
    return { title: metricTitle(snapshot, "官方排名与等权排名", titleSuffix), chartType: "grouped", source_label: sourceLabel, categories, series, value_format: "rank", xLabel: "角色", yLabel: "名次", headers: ["名称", "官方规则", "等权票数"], table, displayTable: table.map((row) => [row[0], formatAxis(row[1], "rank", "rank"), formatAxis(row[2], "rank", "rank")]), rows: items.map((row) => ({ label: metricNameFor(row), value: row.equal_rank })), note: `${snapshot.note || ""} 从完整角色指标 CSV 读取；Top N 仅在最终显示阶段切片。`.trim() };
  }

  if (templateKey === "c11_structure") {
    const items = metricOrdered(currentRows.map((row) => ({ ...row, __primary: row.primary_rate, __secondary: row.secondary_rate, __rest: number(row.primary_rate, null) === null ? null : Math.max(0, 1 - number(row.primary_rate, 0) - number(row.secondary_rate, 0)) })).filter((row) => number(row.__primary, null) !== null), (row) => row.selection_count).slice(0, limit);
    const categories = items.map((row) => metricNameFor(row));
    const series = [{ name: "第一顺位", values: items.map((row) => row.__primary) }, { name: "第二顺位", values: items.map((row) => row.__secondary) }, { name: "其余顺位", values: items.map((row) => row.__rest) }];
    const table = items.map((row) => [metricNameFor(row), row.__primary, row.__secondary, row.__rest]);
    return { title: metricTitle(snapshot, "第一/第二/其余顺位结构", titleSuffix), chartType: "stacked", source_label: sourceLabel, categories, series, value_format: "percent", xLabel: "角色", yLabel: "比例", headers: ["名称", "第一顺位", "第二顺位", "其余顺位"], table, displayTable: table.map((row) => [row[0], formatAxis(row[1], "primary_rate", "percent"), formatAxis(row[2], "secondary_rate", "percent"), formatAxis(row[3], "rate", "percent")]), rows: items, note: `${snapshot.note || ""} 从完整角色指标 CSV 读取；Top N 仅在最终显示阶段切片。`.trim() };
  }

  if (templateKey === "c12_gender_structure") {
    const items = metricOrdered(currentRows.filter((row) => number(row.male_rate, null) !== null && number(row.female_rate, null) !== null), (row) => row.selection_count).slice(0, limit);
    const categories = items.map((row) => metricNameFor(row));
    const series = [{ name: "男性", values: items.map((row) => number(row.male_rate, null)) }, { name: "女性", values: items.map((row) => number(row.female_rate, null)) }, { name: "其他", values: items.map((row) => number(row.other_gender_rate, null)) }];
    const table = items.map((row) => [metricNameFor(row), row.male_rate, row.female_rate, row.other_gender_rate]);
    return { title: metricTitle(snapshot, "支持者性别构成", titleSuffix), chartType: "stacked", source_label: sourceLabel, categories, series, value_format: "percent", xLabel: "角色", yLabel: "比例", headers: ["名称", "男性", "女性", "其他"], table, displayTable: table.map((row) => [row[0], formatAxis(row[1], "rate", "percent"), formatAxis(row[2], "rate", "percent"), formatAxis(row[3], "rate", "percent")]), rows: items, note: `${snapshot.note || ""} 从完整角色指标 CSV 读取；Top N 仅在最终显示阶段切片。`.trim() };
  }

  if (templateKey === "c11_metric_heatmap") {
    const fields = ["points", "selection_count", "primary_count", "primary_rate", "secondary_rate", "top2_rate", "selection_rate"];
    const labels = ["官方分数", "实际选择人数", "第一顺位票", "第一顺位率", "第二顺位率", "前两顺位集中率", "选择率"];
    const rankMaps = fields.map((field) => new Map(metricOrdered(currentRows.filter((row) => number(row[field], null) !== null), (row) => row[field]).map((row, index) => [metricRowKey(row), index + 1])));
    const items = metricOrdered(currentRows, (row) => row.selection_count).slice(0, limit);
    const matrix = items.map((row) => rankMaps.map((rankMap) => rankMap.get(metricRowKey(row)) ?? null));
    const table = items.map((row, index) => [metricNameFor(row), ...matrix[index]]);
    return { title: metricTitle(snapshot, "TOP角色多维指标热力图", titleSuffix), chartType: "heatmap", source_label: sourceLabel, row_labels: items.map((row) => metricNameFor(row)), col_labels: labels, matrix, value_format: "rank", xLabel: "指标", yLabel: "角色", headers: ["名称", ...labels], table, displayTable: table, rows: items, note: `${snapshot.note || ""} 每列按完整角色指标 CSV 单独排名；Top N 仅在最终显示阶段切片。`.trim() };
  }

  if (["c00_round_compare", "m02_round_compare"].includes(templateKey)) {
    const field = "selection_count";
    const previous = new Map(metricRowsForRound(allRows, compare).map((row) => [metricRowKey(row), row]));
    const items = metricOrdered(currentRows.filter((row) => number(row[field], null) !== null).map((row) => ({ ...row, __current: number(row[field], null), __previous: number(previous.get(metricRowKey(row))?.[field], null) })), (row) => row.__current).slice(0, limit);
    const categories = items.map((row) => metricNameFor(row));
    const series = [{ name: compare, values: items.map((row) => row.__previous) }, { name: current, values: items.map((row) => row.__current) }];
    const table = items.map((row) => [metricNameFor(row), row.__previous, row.__current]);
    return { title: metricTitle(snapshot, "任意两届独立系列对比", `${current} ↔ ${compare}`), chartType: "dumbbell", source_label: sourceLabel, categories, series, value_format: "integer", xLabel: "实际选择人数", yLabel: kind === "music" ? "曲子" : "角色", headers: ["名称", compare, current], table, displayTable: table.map((row) => [row[0], formatAxis(row[1], field, "integer"), formatAxis(row[2], field, "integer")]), rows: items, note: `${snapshot.note || ""} 两届都从完整指标 CSV 读取，连接后才按 Top N 切片。`.trim() };
  }

  const compareSpecs = {
    c01_rank_change: ["rank", (cur, prev) => number(prev.rank, null) === null || number(cur.rank, null) === null ? null : number(prev.rank) - number(cur.rank), "名次变化", "number"],
    c03_primary_rate_change: ["primary_rate", (cur, prev) => number(cur.primary_rate, null) === null || number(prev.primary_rate, null) === null ? null : number(cur.primary_rate) - number(prev.primary_rate), "变化", "percent"],
    c06_primary_change: ["primary_count", (cur, prev) => number(cur.primary_count, null) === null || number(prev.primary_count, null) === null ? null : number(cur.primary_count) - number(prev.primary_count), "变化", "integer"],
    c07_selection_change: ["selection_count", (cur, prev) => number(cur.selection_count, null) === null || number(prev.selection_count, null) === null ? null : number(cur.selection_count) - number(prev.selection_count), "变化", "integer"],
    c07_selection_yoy: ["selection_count", (cur, prev) => number(cur.selection_count, null) === null || number(prev.selection_count, null) === null || number(prev.selection_count) === 0 ? null : number(cur.selection_count) / number(prev.selection_count) - 1, "变化", "percent"],
    c08_points_change: ["points", (cur, prev) => number(cur.points, null) === null || number(prev.points, null) === null ? null : number(cur.points) - number(prev.points), "变化", "number"],
    c09_selection_rate_change: ["selection_rate", (cur, prev) => number(cur.selection_rate, null) === null || number(prev.selection_rate, null) === null ? null : number(cur.selection_rate) - number(prev.selection_rate), "变化", "percent"],
    c12_gender_change: ["female_rate", (cur, prev) => number(cur.female_rate, null) === null || number(prev.female_rate, null) === null ? null : number(cur.female_rate) - number(prev.female_rate), "女性比例变化", "percent"],
  };
  if (compareSpecs[templateKey]) {
    const [, calculate, label, format] = compareSpecs[templateKey];
    const previous = new Map(metricRowsForRound(allRows, compare).map((row) => [metricRowKey(row), row]));
    const items = metricRowsFiltered(currentRows).map((row) => ({ ...row, __value: calculate(row, previous.get(metricRowKey(row)) || {}) })).filter((row) => number(row.__value, null) !== null);
    const ordered = metricOrdered(items, (row) => row.__value, templateKey === "c01_rank_change" ? "desc" : controls.sort.value || "desc");
    return metricBarResult({ title: metricTitle(snapshot, label, `${current} ↔ ${compare}`), items: ordered, field: compareSpecs[templateKey][0], label, format, sourceLabel, note: `${snapshot.note || ""} 从两届完整角色指标 CSV 连接后计算；Top N 仅在最终显示阶段切片。`.trim() });
  }

  if (templateKey === "c10_growth_lag") {
    const previous = new Map(metricRowsForRound(allRows, compare).map((row) => [metricRowKey(row), row]));
    const items = metricRowsFiltered(currentRows).map((row) => {
      const prev = previous.get(metricRowKey(row));
      const x = prev && number(row.selection_count, null) !== null && number(prev.selection_count, null) !== null ? number(row.selection_count) - number(prev.selection_count) : null;
      const y = prev && number(row.selection_rate, null) !== null && number(prev.selection_rate, null) !== null ? number(row.selection_rate) - number(prev.selection_rate) : null;
      return { ...row, __x: x, __y: y };
    }).filter((row) => number(row.__x, null) !== null && number(row.__y, null) !== null && row.__x > 0 && row.__y < 0).sort((a, b) => b.__x - a.__x).slice(0, limit);
    const points = items.map((row) => ({ label: metricNameFor(row), x: row.__x, y: row.__y }));
    const table = points.map((point) => [point.label, point.x, point.y]);
    return { title: metricTitle(snapshot, "人数增加但选择率下降", `${current} ↔ ${compare}`), chartType: "scatter", source_label: sourceLabel, points, rows: points, xLabel: "实际选择人数变化", yLabel: "选择率变化", x_format: "integer", y_format: "percent", headers: ["名称", "实际选择人数变化", "选择率变化"], table, displayTable: table.map((row) => [row[0], formatAxis(row[1], "count", "integer"), formatAxis(row[2], "rate", "percent")]), note: `${snapshot.note || ""} 从两届完整角色指标 CSV 连接后计算；Top N 仅在最终显示阶段切片。`.trim() };
  }

  const trendSpecs = {
    c00_rank_trend: ["rank", "官方名次", "rank"],
    c00_all_trend: ["selection_count", "实际选择人数", "integer"],
    m03_rank_trend: ["rank", "官方名次", "rank"],
    m03_all_trend: ["selection_count", "实际选择人数", "integer"],
  };
  if (trendSpecs[templateKey]) {
    const [field, label, format] = trendSpecs[templateKey];
    const prefix = current.slice(0, 2);
    const rounds = ROUND_LABELS.filter((round) => round.slice(0, 2) === prefix);
    const selected = metricOrdered(currentRows.filter((row) => number(row[field], null) !== null), (row) => row[field], field === "rank" ? "asc" : "desc").slice(0, limit);
    const byRound = new Map();
    rounds.forEach((round) => { byRound.set(round, new Map(metricRowsForRound(allRows, round).map((row) => [metricRowKey(row), row]))); });
    const series = selected.map((row) => ({ name: metricNameFor(row), values: rounds.map((round) => number(byRound.get(round)?.get(metricRowKey(row))?.[field], null)) }));
    const table = rounds.map((round, index) => [round, ...series.map((item) => item.values[index])]);
    return { title: metricTitle(snapshot, snapshot.title || label, prefix), chartType: "line", source_label: sourceLabel, categories: rounds, series, value_format: format, xLabel: "届次", yLabel: label, headers: ["届次", ...series.map((item) => item.name)], table, displayTable: table.map((row) => [row[0], ...row.slice(1).map((value) => formatAxis(value, field, format))]), rows: series, note: `${snapshot.note || ""} 角色/曲子系列从完整指标 CSV 读取；Top N 仅在最终显示阶段切片。`.trim() };
  }
  return null;
}

async function dynamicCharacterResult() {
  const round = controls.round.value;
  const rows = (await loadCSV("character")).filter((row) => selectedRound(row) === round);
  const xField = ["rank", "points", "selection_count", "selection_rate", "primary_rate", "secondary_rate", "top2_rate", "female_rate"].includes(controls.xMetric.value) ? controls.xMetric.value : "selection_count";
  const yField = ["rank", "points", "selection_count", "selection_rate", "primary_rate", "secondary_rate", "top2_rate", "female_rate"].includes(controls.yMetric.value) ? controls.yMetric.value : "primary_rate";
  const rankStart = Math.max(1, integer(controls.rankStart.value, 1)), rankEnd = Math.max(rankStart, integer(controls.rankEnd.value, 2000));
  const minimum = Math.max(0, integer(controls.minVotes.value, 0));
  const query = controls.search.value.trim().toLocaleLowerCase();
  const points = rows.filter((row) => {
    const rank = number(row.rank, null), count = number(row.selection_count, null);
    if (rank !== null && (rank < rankStart || rank > rankEnd)) return false;
    if (minimum > 0 && (count === null || count < minimum)) return false;
    if (query && !`${row.name_cn || ""} ${row.name_jp || ""} ${row.canonical_name || ""}`.toLocaleLowerCase().includes(query)) return false;
    return number(row[xField], null) !== null && number(row[yField], null) !== null;
  }).sort((a, b) => number(b[xField], 0) - number(a[xField], 0)).slice(0, Math.max(3, Math.min(100, integer(controls.topN.value, 20)))).map((row) => ({ label: row.name_cn || row.name_jp || row.canonical_name, x: number(row[xField]), y: number(row[yField]), size: number(row.selection_count, 0), tooltipPairs: [["官方名次", formatAxis(row.rank, "rank", "rank")], [METRIC_LABELS[xField] || xField, formatAxis(row[xField], xField, dynamicMetricFormat(xField))], [METRIC_LABELS[yField] || yField, formatAxis(row[yField], yField, dynamicMetricFormat(yField))], ["实际选择人数", formatAxis(row.selection_count, "selection_count", "integer")]] }));
  const xLabel = METRIC_LABELS[xField] || xField;
  const yLabel = METRIC_LABELS[yField] || yField;
  const includeSize = xField !== "selection_count" && yField !== "selection_count";
  const headers = ["角色", xLabel, yLabel, ...(includeSize ? ["点大小：实际选择人数"] : [])];
  const table = points.map((p) => [p.label, p.x, p.y, ...(includeSize ? [p.size] : [])]);
  const displayTable = points.map((p) => [p.label, formatAxis(p.x, xField, dynamicMetricFormat(xField)), formatAxis(p.y, yField, dynamicMetricFormat(yField)), ...(includeSize ? [formatAxis(p.size, "selection_count", "integer")] : [])]);
  return { title: `自定义角色指标（${round}）`, chartType: "scatter", source_label: "全量角色指标 CSV", points, rows: points, metric: yField, xMetric: xField, xLabel, yLabel, x_format: dynamicMetricFormat(xField), y_format: dynamicMetricFormat(yField), headers, table, displayTable, note: `横轴和纵轴均从完整角色指标 CSV 即时计算；散点旁显示名称，悬浮可查看完整指标。${includeSize ? "点大小表示实际选择人数。" : "当前坐标轴已使用实际选择人数，因此不再重复显示点大小列。"}` };
}

function desktopSnapshotResult(bundle) {
  const templateKey = controls.template.value;
  const currentRound = controls.round.value;
  const compareRound = controls.compareRound.value;
  const snapshot = selectedDesktopSnapshot(bundle, templateKey, currentRound, compareRound);
  if (!snapshot) {
    return {
      title: "没有当前模板快照", chartType: "bar", metric: "count", rows: [], headers: ["状态"], table: [["当前地区/届次没有预计算快照"]],
      note: "请更换模板或届次。", xLabel: "", yLabel: "",
    };
  }
  if (!snapshotHasData(snapshot)) {
    const pairText = COMPARISON_TEMPLATE_KEYS.has(templateKey) ? `（${currentRound} 与 ${compareRound || "—"}）` : `（${currentRound}）`;
    return {
      title: `${snapshot.title || "当前模板"}${pairText}`, chartType: snapshot.chart_type || "bar", metric: "count", rows: [],
      headers: ["状态"], table: [[`当前选择${pairText}没有可用的公开数据；该项目已隐藏或不支持此地区组合。`]],
      note: [snapshot.note, "空白表示原始来源未公开，不会伪造为 0。"].filter(Boolean).join(" "), xLabel: "", yLabel: "",
      desktopSnapshot: true,
    };
  }
  const chartType = snapshot.chart_type || "bar";
  const limit = Math.max(3, Math.min(100, integer(controls.topN.value, 20)));
  const query = controls.search.value.trim().toLocaleLowerCase();
  const rangeStart = Math.max(1, integer(controls.rankStart.value, 1));
  const rangeEnd = Math.max(rangeStart, integer(controls.rankEnd.value, 2000));
  const minData = Math.max(0, number(controls.minCount.value, 0) || 0);
  const sortMode = controls.sort.value || "desc";
  const changeDirection = controls.changeDirection.value || "all";
  const copy = { ...snapshot };
  // The music-internal cluster snapshot already contains the complete
  // published graph.  Keep its panel layout when rendering the static
  // fallback so the browser never needs to parse the 100+ MB raw pair dump.
  if (templateKey === "a18_music_concentration_clusters") {
    copy.layout = "music_cluster_grid";
    copy.note = `${copy.note || ""} 大型聚类不逐一绘制节点名称，完整名称可悬停查看。`.trim();
  }
  copy.table_headers = Array.isArray(snapshot.table_headers) ? snapshot.table_headers : [];
  copy.table_rows = (snapshot.table_rows || []).map((row) => Array.isArray(row) ? row : [row]);
  const originalTableRows = copy.table_rows.slice();
  const language = controls.language.value || "cn";
  const localize = (value) => snapshot.label_maps?.[String(value)]?.[language] || String(value ?? "");
  const localizePairRows = (rows) => rows.map((row) => {
    if (!Array.isArray(row) || !row.length) return row;
    const next = row.slice(); next[0] = localize(next[0]); return next;
  });
  copy.table_rows = localizePairRows(copy.table_rows);

  // Faction membership is attached to network nodes in the web bundle.  The
  // desktop renderer has its own faction control; reproducing that filter here
  // keeps the static page honest without importing Tk code into the browser.
  if (templateKey === "a02_network" && Array.isArray(snapshot.nodes)) {
    const selectedFaction = controls.faction.value;
    if (selectedFaction) {
      copy.nodes = snapshot.nodes.filter((node) => (node.factions || []).includes(selectedFaction));
      const ids = new Set(copy.nodes.map((node) => node.id));
      copy.edges = (snapshot.edges || []).filter((edge) => ids.has(edge.source) && ids.has(edge.target));
      const edgeRows = new Map(originalTableRows.map((row) => [String(row[0] ?? ""), row]));
      copy.table_rows = copy.edges.map((edge, index) => edgeRows.get(String(edge.label || "")) || originalTableRows[index] || [edge.label || "", edge.value ?? "", edge.lift ?? ""]);
      copy.note = `${copy.note || ""} 当前阵营：${selectedFaction}；仅显示该阵营角色及其内部关系。过滤后关系数：${copy.edges.length}。`.trim();
    }
  }

  if (chartType === "line") {
    let series = Array.isArray(snapshot.series) ? snapshot.series : [];
    if (query) series = series.filter((item) => String(item.name || "").toLocaleLowerCase().includes(query));
    copy.series = series.slice(rangeStart - 1, rangeEnd).slice(0, limit);
    copy.categories = Array.isArray(snapshot.categories) ? snapshot.categories : [];
    copy.table_headers = [copy.table_headers[0] || "届次", ...copy.series.map((item) => item.name)];
    copy.table_rows = query || copy.series.length !== (snapshot.series || []).length
      ? copy.categories.map((category, index) => [category, ...copy.series.map((item) => item.values?.[index] ?? "")])
      : originalTableRows.slice();
  } else if (["bar", "grouped", "stacked", "dumbbell"].includes(chartType)) {
    const categories = Array.isArray(snapshot.categories) ? snapshot.categories : [];
    let indices = categories.map((_, index) => index);
    if (query) {
      const matched = indices.filter((index) => String(categories[index]).toLocaleLowerCase().includes(query));
      indices = matched;
    }
    indices = indices.slice(rangeStart - 1, rangeEnd);
    const primary = snapshot.series?.[0]?.values || [];
    if (minData > 0) indices = indices.filter((index) => {
      const value = number(primary[index], null);
      return value !== null && Math.abs(value) >= minData;
    });
    if (changeDirection === "positive") indices = indices.filter((index) => number(primary[index], 0) > 0);
    if (changeDirection === "negative") indices = indices.filter((index) => number(primary[index], 0) < 0);
    if (chartType !== "stacked") {
      indices.sort((a, b) => {
        const av = number(primary[a], 0), bv = number(primary[b], 0);
        if (sortMode === "asc") return av - bv;
        if (sortMode === "abs") return Math.abs(bv) - Math.abs(av);
        return bv - av;
      });
    }
    indices = indices.slice(0, limit);
    copy.categories = indices.map((index) => localize(categories[index]));
    copy.series = (snapshot.series || []).map((item) => ({ ...item, values: indices.map((index) => item.values?.[index] ?? null) }));
    copy.table_rows = localizePairRows(indices.map((index) => originalTableRows[index] || [categories[index], ...copy.series.map((item) => item.values?.[indices.indexOf(index)] ?? "")]));
  } else if (["scatter", "bubble"].includes(chartType)) {
    let points = Array.isArray(snapshot.points) ? snapshot.points : [];
    if (query) points = points.filter((point) => Object.values(point || {}).join(" ").toLocaleLowerCase().includes(query));
    points = points.slice(rangeStart - 1, rangeEnd);
    if (minData > 0) points = points.filter((point) => {
      const value = number(point.count ?? point.size ?? point.x, null);
      return value !== null && Math.abs(value) >= minData;
    });
    copy.points = points.slice(0, limit).map((point) => ({ ...point, label: localize(point.label) }));
    const pointRows = new Map(originalTableRows.map((row) => [String(row[0] ?? ""), row]));
    copy.table_rows = localizePairRows(copy.points.map((point, index) => pointRows.get(String(point.label || "")) || originalTableRows[index] || [point.label || "", point.x ?? "", point.y ?? "", ...(chartType === "bubble" ? [point.size ?? ""] : [])]));
  } else if (chartType === "heatmap") {
    let indices = (snapshot.row_labels || []).map((_, index) => index);
    if (query) indices = indices.filter((index) => String(snapshot.row_labels[index]).toLocaleLowerCase().includes(query));
    indices = indices.slice(rangeStart - 1, rangeEnd);
    indices = indices.slice(0, limit);
    copy.row_labels = indices.map((index) => localize(snapshot.row_labels[index]));
    copy.matrix = indices.map((index) => (snapshot.matrix?.[index] || []).slice(0, limit));
    copy.col_labels = (snapshot.col_labels || []).slice(0, limit).map(localize);
    copy.table_headers = [copy.table_headers[0] || "名称", ...copy.col_labels];
    copy.table_rows = localizePairRows(indices.map((index) => (originalTableRows[index] || [copy.row_labels[index], ...copy.matrix[indices.indexOf(index)]]).slice(0, limit + 1)));
  } else if (chartType === "network") {
    let nodes = Array.isArray(copy.nodes) ? copy.nodes : (Array.isArray(snapshot.nodes) ? snapshot.nodes : []);
    if (query) nodes = nodes.filter((node) => Object.values(node || {}).join(" ").toLocaleLowerCase().includes(query));
    nodes = nodes.filter((node, index) => {
      const rank = number(node.rank, null);
      const position = rank === null ? index + 1 : rank;
      return position >= rangeStart && position <= rangeEnd;
    });
    const candidateIds = new Set(nodes.map((node) => node.id));
    let edges = (copy.edges || snapshot.edges || []).filter((edge) => candidateIds.has(edge.source) && candidateIds.has(edge.target));
    if (minData > 0) edges = edges.filter((edge) => number(edge.value, 0) >= minData);
    const connected = new Set(edges.flatMap((edge) => [edge.source, edge.target]));
    if (edges.length) nodes = nodes.filter((node) => connected.has(node.id));
    nodes = nodes.slice(0, Math.max(limit, chartType === "network" ? limit * 4 : limit));
    const ids = new Set(nodes.map((node) => node.id));
    copy.nodes = nodes.map((node) => ({ ...node, label: localize(node.label) }));
    copy.edges = edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
    const edgeRows = new Map(originalTableRows.map((row) => [String(row[0] ?? ""), row]));
    copy.table_rows = localizePairRows(copy.edges.map((edge, index) => edgeRows.get(String(edge.label || "")) || originalTableRows[index] || [edge.label || `${edge.source} × ${edge.target}`, edge.value ?? "", edge.lift ?? ""]));
  }
  const rows = copy.points || (copy.categories || []).map((label, index) => ({
    label,
    __value: copy.series?.[0]?.values?.[index],
  }));
  const pairSuffix = COMPARISON_TEMPLATE_KEYS.has(templateKey) ? `（${currentRound} ↔ ${compareRound}）` : `（${currentRound}）`;
  return {
    ...copy,
    title: `${copy.title || "桌面版分析"}${pairSuffix}`,
    chartType,
    metric: copy.series?.[0]?.value_field || "__value",
    rows,
    headers: copy.table_headers || ["名称", ...(copy.series || []).map((series) => series.name)],
    table: copy.table_rows || [],
    displayTable: (copy.table_rows || []).map((row) => row.map((cell, index) => {
      if (index === 0 || cell === "" || cell === null || cell === undefined) return cell;
      const numeric = number(cell, null); if (numeric === null) return cell;
      if (copy.value_format === "percent") return formatAxis(numeric, "", "percent");
      if (copy.value_format === "rank") return formatAxis(numeric, "", "rank");
      if (copy.value_format === "integer") return formatAxis(numeric, "", "integer");
      if (copy.value_format === "number") return formatAxis(numeric, "", "number");
      if (copy.value_format === "decimal") return formatAxis(numeric, "", "number");
      return cell;
    })),
    xLabel: copy.x_label || "",
    yLabel: copy.y_label || copy.series?.[0]?.name || "数值",
    note: [copy.note, copy.interpretation].filter(Boolean).join(" "),
    desktopSnapshot: true,
  };
}

function svgEl(tag, attrs = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
  return node;
}

function drawText(svg, text, x, y, attrs = {}) {
  const node = svgEl("text", { x, y, ...attrs }); node.textContent = text; svg.appendChild(node); return node;
}

function tooltipText(point, result) {
  const label = point.label || "未命名";
  if (Array.isArray(point.tooltipPairs)) {
    const lines = [`<strong>${escapeHTML(label)}</strong>`];
    point.tooltipPairs.forEach(([name, value]) => lines.push(`${escapeHTML(name)}：${escapeHTML(value)}`));
    if (point.subtitle) lines.push(escapeHTML(point.subtitle));
    if (point.anomaly) lines.push("标记：异常");
    return lines.join("<br>");
  }
  const lines = [
    `<strong>${escapeHTML(label)}</strong>`,
    `${escapeHTML(result.xLabel || "横轴")}：${escapeHTML(formatAxis(point.x, result.xMetric || "", result.x_format))}`,
    `${escapeHTML(result.yLabel || "纵轴")}：${escapeHTML(formatAxis(point.y, result.metric || "", result.y_format || result.value_format))}`,
  ];
  if (point.size !== undefined && point.size !== null) lines.push(`气泡大小：${escapeHTML(formatAxis(point.size, "", "number"))}`);
  if (point.subtitle) lines.push(escapeHTML(point.subtitle));
  if (point.anomaly) lines.push("标记：异常");
  return lines.join("<br>");
}

function hideChartTooltip() {
  const tooltip = $("chart-tooltip");
  if (!tooltip) return;
  tooltip.classList.remove("visible");
}

function showChartTooltip(event, point, result) {
  const tooltip = $("chart-tooltip"), wrap = $("chart-wrap");
  if (!tooltip || !wrap) return;
  const wrapRect = wrap.getBoundingClientRect();
  const targetRect = event?.currentTarget?.getBoundingClientRect?.();
  const clientX = Number.isFinite(event?.clientX) ? event.clientX : (targetRect ? targetRect.left + targetRect.width / 2 : wrapRect.left + wrapRect.width / 2);
  const clientY = Number.isFinite(event?.clientY) ? event.clientY : (targetRect ? targetRect.top : wrapRect.top + 30);
  tooltip.innerHTML = tooltipText(point, result);
  tooltip.classList.add("visible");
  const rawLeft = clientX - wrapRect.left + wrap.scrollLeft + 14;
  const maxLeft = wrap.scrollLeft + wrap.clientWidth - tooltip.offsetWidth - 8;
  const left = Math.max(wrap.scrollLeft + 8, Math.min(rawLeft, maxLeft));
  let top = clientY - wrapRect.top + wrap.scrollTop + 14;
  const maxTop = wrap.scrollTop + wrap.clientHeight - tooltip.offsetHeight - 8;
  if (top > maxTop) top = Math.max(wrap.scrollTop + 8, clientY - wrapRect.top + wrap.scrollTop - tooltip.offsetHeight - 14);
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}

function bindPointTooltip(node, point, result) {
  node.setAttribute("tabindex", "0");
  node.setAttribute("role", "button");
  node.addEventListener("pointerenter", (event) => showChartTooltip(event, point, result));
  node.addEventListener("pointermove", (event) => showChartTooltip(event, point, result));
  node.addEventListener("pointerleave", hideChartTooltip);
  node.addEventListener("focus", (event) => showChartTooltip(event, point, result));
  node.addEventListener("blur", hideChartTooltip);
  node.addEventListener("click", (event) => { event.stopPropagation(); showChartTooltip(event, point, result); });
}

function formatAxis(value, metric = "", explicitFormat = "") {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  value = Number(value);
  if (explicitFormat === "percent" || metricIsPercent(metric)) return `${(value * 100).toFixed(value === 0 ? 0 : 1)}%`;
  if (explicitFormat === "rank" || metricIsInteger(metric) && (metric === "rank" || metric.endsWith("_rank"))) return `#${Math.round(value)}`;
  // Snapshots created by older desktop versions used value_format="number"
  // even for count fields.  Keep all count-like axis labels integral and also
  // avoid noisy decimal ticks when the actual data are whole numbers.
  if (explicitFormat === "integer" || metricIsInteger(metric) || (explicitFormat === "number" && Number.isInteger(value))) return Math.round(value).toLocaleString("zh-CN");
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function axisIsInteger(result, metric = "", values = []) {
  if (result?.value_format === "integer" || metricIsInteger(metric)) return true;
  return result?.value_format === "number" && values.length > 0 && values.every((value) => Number.isInteger(Number(value)));
}

function niceStep(span, target = 5, integerMode = false) {
  const raw = Math.max(span, 1e-9) / Math.max(target, 1);
  if (integerMode) return Math.max(1, Math.ceil(raw));
  const power = 10 ** Math.floor(Math.log10(raw));
  const fraction = raw / power;
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
  return nice * power;
}

function axisTicks(min, max, result, metric = "", values = []) {
  const integerMode = axisIsInteger(result, metric, values);
  if (integerMode) {
    const step = niceStep(max - min, 5, true), lo = min > 0 ? Math.ceil(min) : Math.floor(min), out = [];
    for (let value = lo; value <= max + step * .001 && out.length < 8; value += step) out.push(value);
    if (!out.length || out[out.length - 1] < max) out.push(Math.ceil(max));
    return out;
  }
  const step = niceStep(max - min, 5), lo = min > 0 ? Math.ceil(min / step) * step : Math.floor(min / step) * step, out = [];
  for (let value = lo; value <= max + step * .001 && out.length < 8; value += step) out.push(value);
  return out.length ? out : [min, max];
}

// Pick a compact numeric domain for data-driven charts.  Bar charts keep their
// explicit zero baseline in drawCategorical, while lines/scatters/dumbbells
// should spend most of the plot area on the values that are actually present.
// A zero crossing is still preserved when the data (or a reference line)
// crosses zero, and non-negative series never get a gratuitous negative tail.
function paddedAxisDomain(values, options = {}) {
  const finite = (values || []).map((value) => Number(value)).filter((value) => Number.isFinite(value));
  if (!finite.length) return [0, 1];
  const rawMin = Math.min(...finite), rawMax = Math.max(...finite);
  const padding = Number.isFinite(options.padding) ? options.padding : .08;
  const minPad = Number.isFinite(options.minPad) ? options.minPad : 1;
  const span = rawMax - rawMin;
  const pad = span > 0 ? span * padding : Math.max(Math.abs(rawMin) * padding, minPad);
  let min = rawMin - pad, max = rawMax + pad;
  if (rawMin === 0) min = 0;
  else if (rawMin > 0 && min < 0) min = Math.max(rawMin * .5, Number.EPSILON);
  if (rawMin < 0 && rawMax > 0) {
    min = Math.min(min, 0);
    max = Math.max(max, 0);
  }
  if (!(max > min)) { min -= minPad; max += minPad; }
  return [min, max];
}

function drawCategoryLabel(svg, text, x, y, options = {}) {
  const value = String(text ?? "");
  const maxChars = options.maxChars || 18;
  const lines = [];
  for (let offset = 0; offset < value.length; offset += maxChars) lines.push(value.slice(offset, offset + maxChars));
  const node = svgEl("text", { x, y, "text-anchor": options.anchor || "end", fill: options.fill || "#475569", "font-size": options.fontSize || 11 });
  if (options.rotate) node.setAttribute("transform", `rotate(${options.rotate} ${x} ${y})`);
  lines.slice(0, options.maxLines || 3).forEach((line, index) => {
    const span = svgEl("tspan", { x, dy: index ? 13 : 0 }); span.textContent = line; node.appendChild(span);
  });
  if (lines.length > (options.maxLines || 3)) {
    const last = node.lastChild; if (last) last.textContent = `${last.textContent.slice(0, Math.max(1, maxChars - 1))}…`;
  }
  svg.appendChild(node);
  return node;
}

function chartMessage(svg, text) {
  drawText(svg, text, 550, 270, { "text-anchor": "middle", fill: "#64748b", "font-size": 16 });
}

function drawLegend(svg, series, x, y, colors) {
  if (!series || series.length < 2) return;
  const maxWidth = 980, itemWidth = 170;
  series.forEach((item, index) => {
    const perRow = Math.max(1, Math.floor(maxWidth / itemWidth));
    const row = Math.floor(index / perRow), col = index % perRow;
    const xx = x + col * itemWidth, yy = y + row * 20;
    svg.appendChild(svgEl("rect", { x: xx, y: yy - 10, width: 12, height: 12, rx: 3, fill: colors[index % colors.length] }));
    drawText(svg, String(item.name || `系列 ${index + 1}`), xx + 18, yy, { fill: "#475569", "font-size": 11 });
  });
}

function drawCategorical(result) {
  const svg = $("chart"); svg.innerHTML = "";
  hideChartTooltip();
  const categories = result.categories || result.rows.map((row) => displayLabel(row));
  const longLabels = categories.some((category) => String(category).length > 12);
  // Rotated category labels can extend much farther below their anchor than
  // their line height suggests (especially for CJK labels).  The old fixed
  // 570×142 layout clipped the last line into the SVG viewport, hiding parts
  // of the labels and the x-axis title.  Give long-label charts their own
  // bottom band and a little extra canvas height instead of relying on SVG
  // overflow being visible in every browser.
  const width = Math.max(1100, 92 + categories.length * (longLabels ? 76 : 54) + 130);
  const height = longLabels ? 660 : 570;
  const margin = { top: 72, right: 130, bottom: longLabels ? 190 : 108, left: 92 };
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("width", width);
  svg.style.height = `${height}px`;
  const sourceSeries = result.series?.length ? result.series : [{ name: result.yLabel || "数值", values: result.rows.map((row) => row[result.metric]) }];
  if (!categories.length || !sourceSeries.length) return chartMessage(svg, "当前筛选没有可绘制的数据");
  const plotW = width - margin.left - margin.right, plotH = height - margin.top - margin.bottom;
  const x0 = margin.left, y0 = margin.top + plotH;
  const grid = "#dbe3ec", ink = "#475569";
  const colors = ["#c2415b", "#2563eb", "#0f766e", "#d97706", "#7c3aed", "#0891b2"];
  const values = sourceSeries.flatMap((item) => (item.values || []).map((value) => number(value, null))).filter((value) => value !== null);
  if (!values.length) return chartMessage(svg, "当前筛选没有可绘制的数据");
  const rawMin = Math.min(...values, 0), rawMax = Math.max(...values, 0);
  const span = Math.max(1, rawMax - rawMin), domainMin = rawMin < 0 ? rawMin - span * .08 : 0, domainMax = rawMax > 0 ? rawMax + span * .12 : 1;
  const y = (value) => y0 - ((value - domainMin) / (domainMax - domainMin)) * plotH;
  const zeroY = y(0);
  axisTicks(domainMin, domainMax, result, result.metric, values).forEach((value) => {
    const yy = y(value);
    svg.appendChild(svgEl("line", { x1: x0, x2: x0 + plotW, y1: yy, y2: yy, stroke: grid, "stroke-dasharray": "3 4" }));
    drawText(svg, formatAxis(value, result.metric, result.value_format), x0 - 10, yy + 4, { "text-anchor": "end", fill: ink, "font-size": 12 });
  });
  svg.appendChild(svgEl("line", { x1: x0, x2: x0, y1: margin.top, y2: y0, stroke: ink }));
  svg.appendChild(svgEl("line", { x1: x0, x2: x0 + plotW, y1: y0, y2: y0, stroke: ink }));
  const slot = plotW / categories.length;
  const grouped = result.chartType === "grouped" || sourceSeries.length > 1 && result.chartType !== "stacked";
  const stacked = result.chartType === "stacked";
  categories.forEach((category, index) => {
    const center = x0 + slot * index + slot / 2;
    drawCategoryLabel(svg, category, center, y0 + 20, { maxChars: longLabels ? 15 : 18, maxLines: 3, rotate: longLabels ? -48 : -35, fill: ink });
    if (grouped) {
      const barW = Math.min(48, slot * .78 / sourceSeries.length);
      sourceSeries.forEach((series, seriesIndex) => {
        const value = number(series.values?.[index], null); if (value === null) return;
        const xx = x0 + slot * index + slot * .11 + barW * seriesIndex, yy = y(value), base = zeroY;
        const bar = svgEl("rect", { x: xx, y: Math.min(yy, base), width: barW - 2, height: Math.abs(base - yy), rx: 3, fill: colors[seriesIndex % colors.length], opacity: .88 });
        svg.appendChild(bar);
        bindPointTooltip(bar, { label: String(category), tooltipPairs: [[series.name || "数值", formatAxis(value, result.metric, result.value_format)]] }, result);
      });
    } else if (stacked) {
      const barW = Math.min(56, slot * .7); let positive = 0, negative = 0;
      sourceSeries.forEach((series, seriesIndex) => {
        const value = number(series.values?.[index], null); if (value === null) return;
        const start = value >= 0 ? positive : negative; const end = start + value;
        const yy1 = y(Math.max(start, end)), yy2 = y(Math.min(start, end));
        const segment = svgEl("rect", { x: center - barW / 2, y: yy1, width: barW, height: Math.max(1, yy2 - yy1), fill: colors[seriesIndex % colors.length], opacity: .88 });
        svg.appendChild(segment);
        bindPointTooltip(segment, { label: String(category), tooltipPairs: [[series.name || "数值", formatAxis(value, result.metric, result.value_format)]] }, result);
        if (value >= 0) positive = end; else negative = end;
      });
    } else {
      const value = number(sourceSeries[0].values?.[index], null); if (value === null) return;
      const barW = Math.min(58, slot * .65), xx = center - barW / 2, yy = y(value);
      const bar = svgEl("rect", { x: xx, y: Math.min(yy, zeroY), width: barW, height: Math.max(1, Math.abs(zeroY - yy)), rx: 5, fill: colors[0], opacity: .88 });
      svg.appendChild(bar);
      bindPointTooltip(bar, { label: String(category), tooltipPairs: [[sourceSeries[0].name || result.yLabel || "数值", formatAxis(value, result.metric, result.value_format)]] }, result);
      if (categories.length <= 35) drawText(svg, formatAxis(value, result.metric, result.value_format), center, Math.min(yy, zeroY) - 7, { "text-anchor": "middle", fill: colors[0], "font-size": 11 });
    }
  });
  drawLegend(svg, sourceSeries, x0, 34, colors);
  drawText(svg, result.xLabel, x0 + plotW / 2, height - 12, { "text-anchor": "middle", fill: ink, "font-size": 13, "font-weight": 600 });
  drawText(svg, result.yLabel, 18, margin.top + plotH / 2, { "text-anchor": "middle", transform: `rotate(-90 18 ${margin.top + plotH / 2})`, fill: ink, "font-size": 13, "font-weight": 600 });
}

function drawLine(result) {
  const svg = $("chart"); svg.innerHTML = "";
  hideChartTooltip();
  const categories = result.categories || [], series = result.series || [];
  const longLabels = categories.some((category) => String(category).length > 12);
  const width = Math.max(1100, 82 + categories.length * 62 + 130);
  const height = longLabels ? 660 : 570;
  const margin = { top: 72, right: 130, bottom: longLabels ? 178 : 112, left: 82 };
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("width", width);
  svg.style.height = `${height}px`;
  if (!categories.length || !series.length) return chartMessage(svg, "当前筛选没有可绘制的数据");
  const plotW = width - margin.left - margin.right, plotH = height - margin.top - margin.bottom, x0 = margin.left, y0 = margin.top + plotH;
  const values = series.flatMap((item) => (item.values || []).map((value) => number(value, null))).filter((value) => value !== null);
  if (!values.length) return chartMessage(svg, "当前筛选没有可绘制的数据");
  const [domainMin, domainMax] = paddedAxisDomain(values, { padding: .08, minPad: 1 });
  const x = (index) => categories.length === 1 ? x0 + plotW / 2 : x0 + (index / (categories.length - 1)) * plotW;
  const rankAxis = Boolean(result.rank_axis || result.value_format === "rank");
  const y = (value) => rankAxis ? margin.top + ((value - domainMin) / (domainMax - domainMin)) * plotH : y0 - ((value - domainMin) / (domainMax - domainMin)) * plotH;
  const colors = ["#c2415b", "#2563eb", "#0f766e", "#d97706", "#7c3aed", "#0891b2"];
  axisTicks(domainMin, domainMax, result, result.metric, values).forEach((value) => {
    const yy = y(value);
    svg.appendChild(svgEl("line", { x1: x0, x2: x0 + plotW, y1: yy, y2: yy, stroke: "#dbe3ec", "stroke-dasharray": "3 4" }));
    drawText(svg, formatAxis(value, result.metric, result.value_format), x0 - 10, yy + 4, { "text-anchor": "end", fill: "#475569", "font-size": 11 });
  });
  categories.forEach((label, index) => drawCategoryLabel(svg, label, x(index), y0 + 20, { maxChars: 16, maxLines: 3, rotate: -42, fill: "#475569" }));
  svg.appendChild(svgEl("line", { x1: x0, x2: x0, y1: margin.top, y2: y0, stroke: "#475569" }));
  svg.appendChild(svgEl("line", { x1: x0, x2: x0 + plotW, y1: y0, y2: y0, stroke: "#475569" }));
  series.forEach((item, seriesIndex) => {
    let path = "", started = false;
    (item.values || []).forEach((raw, index) => {
      const value = number(raw, null); if (value === null) { started = false; return; }
      const command = started ? "L" : "M"; path += `${command} ${x(index)} ${y(value)} `; started = true;
    });
    if (path) svg.appendChild(svgEl("path", { d: path, fill: "none", stroke: colors[seriesIndex % colors.length], "stroke-width": 2.2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    (item.values || []).forEach((raw, index) => {
      const value = number(raw, null); if (value === null) return;
      const circle = svgEl("circle", { cx: x(index), cy: y(value), r: 3.6, fill: colors[seriesIndex % colors.length], stroke: "#fff", "stroke-width": 1.5 });
      const title = document.createElementNS("http://www.w3.org/2000/svg", "title"); title.textContent = `${item.name}｜${categories[index]}｜${formatAxis(value, result.metric, result.value_format)}`; circle.appendChild(title); svg.appendChild(circle);
      bindPointTooltip(circle, { label: String(item.name || "系列"), tooltipPairs: [[String(categories[index]), formatAxis(value, result.metric, result.value_format)]] }, result);
    });
  });
  drawLegend(svg, series, x0, 34, colors);
  drawText(svg, result.xLabel, x0 + plotW / 2, height - 12, { "text-anchor": "middle", fill: "#475569", "font-size": 13, "font-weight": 600 });
  drawText(svg, result.yLabel, 18, margin.top + plotH / 2, { "text-anchor": "middle", transform: `rotate(-90 18 ${margin.top + plotH / 2})`, fill: "#475569", "font-size": 13, "font-weight": 600 });
}

function drawScatter(result, bubble = false) {
  const svg = $("chart"); svg.innerHTML = "";
  hideChartTooltip();
  const width = Math.max(1100, 1200), height = 570, margin = { top: 68, right: 170, bottom: 96, left: 92 };
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("width", width);
  svg.style.height = `${height}px`;
  const rawPoints = result.points || result.rows.map((row) => ({ label: displayLabel(row), x: row[result.xMetric], y: row[result.metric], size: row.size }));
  const points = rawPoints.map((point) => ({ point, x: number(point.x, null), y: number(point.y, null) })).filter((item) => item.x !== null && item.y !== null);
  if (!points.length) return chartMessage(svg, "当前筛选没有可绘制的数据");
  const plotW = width - margin.left - margin.right, plotH = height - margin.top - margin.bottom, x0 = margin.left, y0 = margin.top + plotH;
  const logX = Boolean(result.x_log && points.every((p) => p.x > 0));
  const xValues = points.map((p) => p.x);
  const yValues = points.map((p) => p.y);
  const xReference = number(result.x_reference, null), yReference = number(result.y_reference, null);
  if (xReference !== null) xValues.push(xReference);
  if (yReference !== null) yValues.push(yReference);
  let xMin, xMax, txMin, txMax;
  if (logX) {
    const positive = xValues.filter((value) => value > 0), logMin = Math.min(...positive.map((value) => Math.log10(value))), logMax = Math.max(...positive.map((value) => Math.log10(value)));
    const logSpan = Math.max(logMax - logMin, .5), logPad = logSpan * .06;
    txMin = logMin - logPad; txMax = logMax + logPad;
    xMin = 10 ** txMin; xMax = 10 ** txMax;
  } else {
    [xMin, xMax] = paddedAxisDomain(xValues, { padding: .06, minPad: 1 });
    txMin = xMin; txMax = xMax;
  }
  let [yMin, yMax] = paddedAxisDomain(yValues, { padding: .06, minPad: 1 });
  const tx = (value) => logX ? Math.log10(Math.max(1e-12, value)) : value;
  const x = (value) => x0 + ((tx(value) - txMin) / (txMax - txMin)) * plotW;
  const y = (value) => y0 - ((value - yMin) / (yMax - yMin)) * plotH;
  const grid = "#dbe3ec", ink = "#475569", blue = "#2563eb";
  const xTicks = logX
    ? [...new Set([1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000].filter((value) => value >= xMin && value <= xMax))]
    : axisTicks(xMin, xMax, result, result.xMetric || "", points.map((p) => p.x));
  xTicks.forEach((xv) => {
    const xx = x(xv);
    svg.appendChild(svgEl("line", { x1: xx, x2: xx, y1: margin.top, y2: y0, stroke: grid, "stroke-dasharray": "3 4" }));
    drawText(svg, formatAxis(xv, result.xMetric, result.x_format), xx, y0 + 20, { "text-anchor": "middle", fill: ink, "font-size": 11 });
  });
  axisTicks(yMin, yMax, result, result.metric, points.map((p) => p.y)).forEach((yv) => {
    const yy = y(yv);
    svg.appendChild(svgEl("line", { x1: x0, x2: x0 + plotW, y1: yy, y2: yy, stroke: grid, "stroke-dasharray": "3 4" }));
    drawText(svg, formatAxis(yv, result.metric, result.y_format || result.value_format), x0 - 10, yy + 4, { "text-anchor": "end", fill: ink, "font-size": 11 });
  });
  svg.appendChild(svgEl("line", { x1: x0, x2: x0, y1: margin.top, y2: y0, stroke: ink }));
  svg.appendChild(svgEl("line", { x1: x0, x2: x0 + plotW, y1: y0, y2: y0, stroke: ink }));
  if (result.x_reference !== undefined && number(result.x_reference, null) !== null) svg.appendChild(svgEl("line", { x1: x(result.x_reference), x2: x(result.x_reference), y1: margin.top, y2: y0, stroke: "#94a3b8", "stroke-dasharray": "5 4" }));
  if (result.y_reference !== undefined && number(result.y_reference, null) !== null) svg.appendChild(svgEl("line", { x1: x0, x2: x0 + plotW, y1: y(result.y_reference), y2: y(result.y_reference), stroke: "#94a3b8", "stroke-dasharray": "5 4" }));
  const maxSize = Math.max(...points.map((p) => number(p.point.size, 1) || 1), 1);
  const labelItems = [];
  points.forEach((item) => {
    const point = item.point, radius = bubble ? 5 + 18 * Math.sqrt(Math.max(0, number(point.size, 0) || 0) / maxSize) : 7;
    const circle = svgEl("circle", { cx: x(item.x), cy: y(item.y), r: radius, fill: point.highlight ? "#c2415b" : blue, opacity: .78, stroke: "#fff", "stroke-width": 2 });
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title"); title.textContent = `${point.label || "未命名"}｜${formatAxis(item.x, result.xMetric, result.x_format)}｜${formatAxis(item.y, result.metric, result.y_format || result.value_format)}`; circle.appendChild(title); svg.appendChild(circle);
    bindPointTooltip(circle, { ...point, x: item.x, y: item.y }, result);
    const label = String(point.label || "未命名");
    const shortLabel = label.length > (bubble ? 10 : 12) ? `${label.slice(0, bubble ? 10 : 12)}…` : label;
    labelItems.push({ point, px: x(item.x), py: y(item.y), radius, text: shortLabel });
  });
  // Labels used to be painted directly above every point, which made dense
  // questionnaire scatters unreadable.  Place them in one of four nearby
  // quadrants and choose the candidate with the fewest bounding-box clashes.
  const labelFont = bubble ? 9 : 11, lineH = labelFont + 5;
  const labelBoxes = [];
  // Bubble plots can contain many nearly coincident relationships. Keep the
  // ten largest bubbles labelled and leave every other name available via
  // hover/table, instead of painting an unreadable wall of text.
  const labelsToDraw = bubble
    ? [...labelItems].sort((a, b) => b.radius - a.radius).slice(0, 10)
    : (result.xMetric === "intersection_count" || result.metric === "intersection_count"
      ? [...labelItems].sort((a, b) => number(b.point.size, 0) - number(a.point.size, 0)).slice(0, 8)
      : labelItems);
  labelsToDraw.sort((a, b) => a.py - b.py || a.px - b.px).forEach((item) => {
    // CJK glyphs are close to a full em; the old fixed 6px estimate was
    // less than half the rendered width and let labels overlap visibly.
    const textWidth = Math.max(24, [...item.text].reduce((sum, char) => sum + (/[^\x00-\xff]/.test(char) ? (bubble ? 9.5 : 11) : (bubble ? 5.2 : 6.2)), 0));
    const candidates = [
      { x: item.px + item.radius + 4, y: item.py - item.radius - 3, anchor: "start" },
      { x: item.px - item.radius - 4, y: item.py - item.radius - 3, anchor: "end" },
      { x: item.px + item.radius + 4, y: item.py + item.radius + lineH, anchor: "start" },
      { x: item.px - item.radius - 4, y: item.py + item.radius + lineH, anchor: "end" },
    ].map((candidate) => {
      const left = candidate.anchor === "end" ? candidate.x - textWidth : candidate.x;
      return { ...candidate, left, right: left + textWidth, top: candidate.y - lineH, bottom: candidate.y + 3 };
    });
    const score = (candidate) => {
      const outside = Math.max(0, x0 - candidate.left) + Math.max(0, candidate.right - (x0 + plotW)) + Math.max(0, margin.top - candidate.top) + Math.max(0, candidate.bottom - (y0 - 2));
      const overlaps = labelBoxes.reduce((count, box) => count + (candidate.left < box.right + 3 && candidate.right > box.left - 3 && candidate.top < box.bottom + 2 && candidate.bottom > box.top - 2 ? 1 : 0), 0);
      return outside * 10 + overlaps * 100;
    };
    const best = candidates.reduce((selected, candidate) => score(candidate) < score(selected) ? candidate : selected);
    // If all nearby candidates collide, nudge the label down until it clears
    // existing labels while staying inside the plotting area.
    while (labelBoxes.some((box) => best.left < box.right + 3 && best.right > box.left - 3 && best.top < box.bottom + 2 && best.bottom > box.top - 2) && best.bottom < y0 - 2) {
      best.y += lineH; best.top += lineH; best.bottom += lineH;
    }
    labelBoxes.push(best);
    drawText(svg, item.text, best.x, best.y, { class: bubble ? "bubble-label" : "scatter-label", "text-anchor": best.anchor, "font-size": labelFont });
  });
  drawText(svg, result.xLabel, x0 + plotW / 2, height - 15, { "text-anchor": "middle", fill: ink, "font-size": 13, "font-weight": 600 });
  drawText(svg, result.yLabel, 18, margin.top + plotH / 2, { "text-anchor": "middle", transform: `rotate(-90 18 ${margin.top + plotH / 2})`, fill: ink, "font-size": 13, "font-weight": 600 });
}

function drawDumbbell(result) {
  const svg = $("chart"); svg.innerHTML = "";
  hideChartTooltip();
  const categories = result.categories || [], series = result.series || [];
  const width = Math.max(1280, 250 + categories.length * 2 + 180), rowH = 38, height = Math.max(560, 112 + categories.length * rowH), margin = { top: 72, right: 150, bottom: 68, left: 390 };
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("width", width);
  svg.style.height = `${height}px`;
  if (!categories.length || series.length < 2) return chartMessage(svg, "当前筛选没有可绘制的两端数据");
  const plotW = width - margin.left - margin.right, plotH = height - margin.top - margin.bottom, x0 = margin.left;
  const vals = series.flatMap((item) => (item.values || []).map((value) => number(value, null))).filter((value) => value !== null);
  if (!vals.length) return chartMessage(svg, "当前筛选没有可绘制的数据");
  const [dmin, dmax] = paddedAxisDomain(vals, { padding: .06, minPad: 1 });
  const x = (value) => x0 + ((value - dmin) / (dmax - dmin)) * plotW;
  axisTicks(dmin, dmax, result, result.metric, vals).forEach((value) => { const xx = x(value); svg.appendChild(svgEl("line", { x1: xx, x2: xx, y1: margin.top - 10, y2: height - margin.bottom, stroke: "#dbe3ec", "stroke-dasharray": "3 4" })); drawText(svg, formatAxis(value, result.metric, result.value_format), xx, height - 27, { "text-anchor": "middle", fill: "#475569", "font-size": 11 }); });
  categories.forEach((category, index) => {
    const yy = margin.top + index * rowH + rowH / 2;
    const label = String(category);
    drawCategoryLabel(svg, label, x0 - 12, yy - 5, { maxChars: 24, maxLines: 2, fill: "#475569", fontSize: 11 });
    const a = number(series[0].values?.[index], null), b = number(series[1].values?.[index], null);
    if (a === null || b === null) return;
    svg.appendChild(svgEl("line", { x1: x(a), x2: x(b), y1: yy, y2: yy, stroke: "#cbd5e1", "stroke-width": 4, "stroke-linecap": "round" }));
    [a, b].forEach((value, s) => {
      const circle = svgEl("circle", { cx: x(value), cy: yy, r: 6.5, fill: s === 0 ? "#c2415b" : "#2563eb", stroke: "#fff", "stroke-width": 2 });
      svg.appendChild(circle);
      bindPointTooltip(circle, { label: String(category), tooltipPairs: [[series[s].name || `系列 ${s + 1}`, formatAxis(value, result.metric, result.value_format)]] }, result);
    });
  });
  drawLegend(svg, series, x0, 36, ["#c2415b", "#2563eb"]);
}

function drawHeatmap(result) {
  const svg = $("chart"); svg.innerHTML = "";
  hideChartTooltip();
  const rows = result.row_labels || [], cols = result.col_labels || [], matrix = result.matrix || [];
  // Reserve a top band for rotated column labels.  Labels are drawn with an
  // upward-facing anchor below, so they stay above the first row instead of
  // being painted underneath the heatmap cells.  Wider matrices use shorter
  // two-line labels to avoid adjacent labels covering one another.
  const denseColumns = cols.length > 36;
  const cellW = Math.max(64, Math.min(128, 860 / Math.max(cols.length, 1))), cellH = 32, margin = { top: denseColumns ? 210 : 188, right: 150, bottom: 64, left: 230 };
  const width = Math.max(1160, margin.left + cols.length * cellW + margin.right);
  const height = Math.max(600, margin.top + rows.length * cellH + margin.bottom);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("width", width);
  svg.style.height = `${height}px`;
  if (!rows.length || !cols.length) return chartMessage(svg, "当前筛选没有可绘制的矩阵");
  const values = matrix.flat().map((value) => number(value, null)).filter((value) => value !== null), min = Math.min(...values, 0), max = Math.max(...values, 1), span = Math.max(1e-9, max - min);
  rows.forEach((label, row) => {
    const yy = margin.top + row * cellH; drawText(svg, String(label).length > 24 ? `${String(label).slice(0, 24)}…` : label, margin.left - 10, yy + cellH / 2 + 4, { "text-anchor": "end", fill: "#475569", "font-size": 11 });
    cols.forEach((_, col) => {
      const value = number(matrix[row]?.[col], null), xx = margin.left + col * cellW;
      const fill = value === null ? "#f8fafc" : `hsl(${8 + 205 * (1 - (value - min) / span)}, 72%, ${value === null ? 98 : 89 - 34 * ((value - min) / span)}%)`;
      const cell = svgEl("rect", { x: xx, y: yy, width: cellW - 2, height: cellH - 2, rx: 3, fill, stroke: "#fff" });
      svg.appendChild(cell);
      bindPointTooltip(cell, { label: String(label), tooltipPairs: [[String(cols[col]), value === null ? "—" : formatAxis(value, result.metric, result.value_format)]] }, result);
      if (value !== null) drawText(svg, formatAxis(value, result.metric, result.value_format), xx + cellW / 2, yy + cellH / 2 + 4, { "text-anchor": "middle", fill: "#334155", "font-size": 10 });
    });
  });
  // Paint the labels after the cells so a long rotated label can never be
  // hidden by the first heatmap row.  `start` + negative rotation sends the
  // text upward/right from the anchor, which is the safe orientation for a
  // label band above the matrix.
  cols.forEach((label, col) => {
    const xx = margin.left + col * cellW + cellW / 2;
    drawCategoryLabel(svg, label, xx, margin.top - 18, { anchor: "start", maxChars: denseColumns ? 8 : 12, maxLines: denseColumns ? 2 : 3, rotate: -48, fill: "#475569", fontSize: 10 });
  });
}

function drawNetwork(result) {
  const svg = $("chart"); svg.innerHTML = "";
  hideChartTooltip();
  const nodes = result.nodes || [], edges = result.edges || [], musicClusterLayout = result.layout === "music_cluster_grid", clusterGridLayout = result.layout === "cluster_grid";
  const panelLayout = musicClusterLayout || clusterGridLayout;
  const clusterNames = [...new Set(nodes.map((node) => node.cluster).filter(Boolean))];
  const clusterCount = Math.max(1, clusterNames.length);
  const panelCols = panelLayout ? Math.min(3, Math.max(1, Math.ceil(Math.sqrt(clusterCount)))) : 1;
  const panelRows = panelLayout ? Math.ceil(clusterCount / panelCols) : 1;
  const panelW = panelLayout && clusterCount === 1 ? 920 : (clusterGridLayout ? 560 : 460);
  const panelH = panelLayout && clusterCount === 1 ? 470 : (clusterGridLayout ? 420 : 300);
  const width = panelLayout ? Math.max(850, panelCols * panelW + 40) : 1280;
  const height = panelLayout ? Math.max(620, panelRows * panelH + 40) : 720;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("width", width);
  svg.style.height = `${height}px`;
  if (!nodes.length) return chartMessage(svg, "当前筛选没有可绘制的网络");
  const centerX = width / 2, centerY = height / 2 + 22, map = new Map();
  const palette = ["#7c3aed", "#c2415b", "#2563eb", "#0f766e", "#d97706", "#0891b2", "#be123c", "#4f46e5", "#15803d", "#a16207"];
  const groups = clusterNames.length ? clusterNames.map((cluster) => ({ cluster, nodes: nodes.filter((node) => node.cluster === cluster) })) : [{ cluster: "", nodes }];
  if (panelLayout) {
    // Cluster views can contain hundreds of nodes.  Give every component a
    // bounded panel and place its songs on a rectangular grid so edges do not
    // collapse into one dense circular pile.  The chart wrapper remains
    // horizontally/vertically scrollable on small screens.
    groups.forEach((group, groupIndex) => {
      const panelX = 20 + (groupIndex % panelCols) * panelW, panelY = 20 + Math.floor(groupIndex / panelCols) * panelH;
      svg.appendChild(svgEl("rect", { x: panelX, y: panelY, width: panelW - 14, height: panelH - 14, rx: 12, fill: "#f8fafc", stroke: "#dbe3ec" }));
      drawText(svg, `${group.cluster || "网络"}｜${group.nodes.length}${clusterGridLayout ? "节点" : "首曲子"}`, panelX + 14, panelY + 24, { fill: "#334155", "font-size": 12, "font-weight": 600 });
      const gridCols = Math.max(1, Math.ceil(Math.sqrt(group.nodes.length))), gridRows = Math.max(1, Math.ceil(group.nodes.length / gridCols));
      const usableW = panelW - 42, usableH = panelH - 78;
      const stepX = gridCols > 1 ? usableW / (gridCols - 1) : 0, stepY = gridRows > 1 ? usableH / (gridRows - 1) : 0;
      group.nodes.forEach((node, index) => {
        const col = index % gridCols, row = Math.floor(index / gridCols);
        const px = panelX + 21 + (gridCols > 1 ? col * stepX : usableW / 2), py = panelY + 52 + (gridRows > 1 ? row * stepY : usableH / 2);
        map.set(node.id, { ...node, x: px, y: py, color: palette[groupIndex % palette.length] });
      });
    });
  } else {
    groups.forEach((group, groupIndex) => {
      const clusterAngle = -Math.PI / 2 + (groupIndex / Math.max(groups.length, 1)) * Math.PI * 2;
      const clusterRadius = groups.length > 1 ? Math.min(250, 115 + groups.length * 10) : 0;
      const cx = centerX + clusterRadius * Math.cos(clusterAngle), cy = centerY + clusterRadius * Math.sin(clusterAngle);
      // A single role network otherwise occupies only a small island in the
      // 1280px canvas.  Use a larger ring so the remaining labels and edges
      // have room to breathe; clustered layouts keep their panel-specific
      // geometry above.
      const nodeRadius = groups.length === 1
        ? Math.min(270, 120 + group.nodes.length * 5)
        : Math.min(300, 55 + group.nodes.length * 2.4);
      group.nodes.forEach((node, index) => {
        const angle = -Math.PI / 2 + (index / Math.max(group.nodes.length, 1)) * Math.PI * 2;
        map.set(node.id, { ...node, x: cx + nodeRadius * Math.cos(angle), y: cy + nodeRadius * Math.sin(angle), color: palette[groupIndex % palette.length] });
      });
    });
  }
  // Label only a small, deterministic set of central nodes.  Rendering a
  // caption for every role is what turns a perfectly usable network into a
  // wall of overlapping text; every circle still has the full-name tooltip.
  const degreeById = new Map(nodes.map((node) => [node.id, 0]));
  edges.forEach((edge) => {
    degreeById.set(edge.source, (degreeById.get(edge.source) || 0) + 1);
    degreeById.set(edge.target, (degreeById.get(edge.target) || 0) + 1);
  });
  const labelBudget = panelLayout && nodes.length > 60 ? 0 : panelLayout ? 20 : 12;
  const labelCandidates = [...nodes].sort((a, b) => {
    const degreeDiff = (degreeById.get(b.id) || 0) - (degreeById.get(a.id) || 0);
    if (degreeDiff) return degreeDiff;
    const valueDiff = number(b.value, 0) - number(a.value, 0);
    if (valueDiff) return valueDiff;
    return number(a.rank, 999999) - number(b.rank, 999999);
  });
  const compactNetwork = nodes.length <= (panelLayout ? 28 : 20);
  const labelIds = new Set();
  if (panelLayout && compactNetwork) {
    // Small cluster panels have enough local space for all captions.
    nodes.forEach((node) => labelIds.add(node.id));
  } else {
    // Prefer at most one caption per angular sector, so high-ranked nodes at
    // the top of the rank ring do not pile all their text into one corner.
    const sectors = new Set();
    labelCandidates.forEach((node) => {
      if (labelIds.size >= labelBudget) return;
      const point = map.get(node.id);
      if (!point) return;
      const angle = (Math.atan2(point.y - centerY, point.x - centerX) + Math.PI * 2) % (Math.PI * 2);
      const sector = Math.floor(angle / (Math.PI * 2) * labelBudget);
      if (sectors.has(sector)) return;
      sectors.add(sector); labelIds.add(node.id);
    });
    // If a sparse graph left sectors empty, fill the remaining budget by
    // centrality so the annotation count stays predictable.
    labelCandidates.forEach((node) => {
      if (labelIds.size < labelBudget) labelIds.add(node.id);
    });
  }
  const maxEdge = Math.max(...edges.map((edge) => number(edge.value, 1) || 1), 1);
  edges.forEach((edge) => {
    const a = map.get(edge.source), b = map.get(edge.target); if (!a || !b) return;
    const line = svgEl("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: "#94a3b8", "stroke-width": panelLayout ? 1 + 2.8 * Math.sqrt((number(edge.value, 0) || 0) / maxEdge) : 1 + 5 * Math.sqrt((number(edge.value, 0) || 0) / maxEdge), opacity: panelLayout ? .18 : .28, "pointer-events": "stroke" });
    svg.appendChild(line);
    bindPointTooltip(line, { label: edge.label || `${a.label} × ${b.label}`, tooltipPairs: [["共同人数", formatAxis(edge.value, "", "integer")], ["集中倍数", formatAxis(edge.lift, "", "number")]] }, result);
  });
  const maxNode = Math.max(...nodes.map((node) => number(node.value, 1) || 1), 1);
  nodes.forEach((node) => {
    const p = map.get(node.id); if (!p) return;
    const degree = edges.reduce((sum, edge) => sum + (edge.source === node.id || edge.target === node.id ? 1 : 0), 0);
    const r = panelLayout
      ? 5 + Math.min(5, degree / 3)
      : 7 + 16 * Math.sqrt((number(node.value, 0) || 0) / maxNode) + Math.min(5, degree / 4);
    const fill = p.color || (node.cluster ? "#7c3aed" : "#c2415b");
    const circle = svgEl("circle", { cx: p.x, cy: p.y, r, fill, opacity: .88, stroke: "#fff", "stroke-width": 2, "data-node-id": node.id, "aria-label": node.label || node.id });
    svg.appendChild(circle);
    bindPointTooltip(circle, { label: node.label || node.id, tooltipPairs: [
      ...(number(node.rank, null) !== null ? [["官方名次", formatAxis(node.rank, "rank", "rank")]] : []),
      ["节点值", formatAxis(node.value, "", "number")],
      ...(node.cluster ? [["聚类", node.cluster]] : []),
    ] }, result);
    // Hundreds of labels make a cluster graph unreadable.  Keep labels for
    // compact networks and a bounded set of central nodes; every node still
    // has a tooltip with its complete name.
    if (labelIds.has(node.id)) {
      const text = String(node.label || node.id).replace(/^曲子:/, ""), label = text.length > 18 ? `${text.slice(0, 17)}…` : text;
      drawText(svg, label, p.x, p.y - r - 6, { "text-anchor": "middle", fill: "#334155", "font-size": 10 });
    }
  });
  if (groups.length > 1 && !panelLayout) {
    groups.slice(0, 12).forEach((group, index) => {
      const x = 24 + (index % 6) * 195, y = 28 + Math.floor(index / 6) * 20;
      svg.appendChild(svgEl("rect", { x, y: y - 10, width: 12, height: 12, rx: 3, fill: palette[index % palette.length] }));
      drawText(svg, `${group.cluster || "网络"}（${group.nodes.length}节点）`, x + 18, y, { fill: "#475569", "font-size": 11 });
    });
  }
}

function applyChartZoom() {
  const svg = $("chart"), label = $("chart-zoom-value");
  if (!svg) return;
  const viewBox = String(svg.getAttribute("viewBox") || "").trim().split(/\s+/).map(Number);
  if (viewBox.length !== 4 || !Number.isFinite(viewBox[2]) || !Number.isFinite(viewBox[3])) return;
  const zoom = Math.max(.75, Math.min(3, Number(state.chartZoom) || 1));
  state.chartZoom = zoom;
  svg.style.width = `${Math.round(viewBox[2] * zoom)}px`;
  svg.style.height = `${Math.round(viewBox[3] * zoom)}px`;
  if (label) label.textContent = `${Math.round(zoom * 100)}%`;
}

function setChartZoom(value) {
  state.chartZoom = Math.max(.75, Math.min(3, Math.round(Number(value) * 4) / 4));
  applyChartZoom();
}

function renderTable(result) {
  $("result-table").querySelector("thead").innerHTML = `<tr>${result.headers.map((header) => `<th>${escapeHTML(header)}</th>`).join("")}</tr>`;
  const displayRows = result.displayTable || result.table || [];
  $("result-table").querySelector("tbody").innerHTML = displayRows.map((row) => `<tr>${row.map((cell) => `<td>${escapeHTML(cell)}</td>`).join("")}</tr>`).join("");
  $("table-count").textContent = `${result.table.length.toLocaleString("zh-CN")} 行`;
}

function clearRenderedResult() {
  // Remove the previous graph/table immediately.  Large gzip-backed views can
  // take several seconds to parse; leaving the old result visible during that
  // interval makes a new selection look as if it failed to update.
  $("chart").innerHTML = "";
  $("result-table").querySelector("thead").innerHTML = "";
  $("result-table").querySelector("tbody").innerHTML = "";
  $("chart-title").textContent = "正在读取…";
  $("table-title").textContent = "计算结果表";
  $("chart-note").textContent = "";
  $("table-count").textContent = "";
  $("summary-count").textContent = "—";
  $("summary-chart").textContent = "—";
  $("summary-source").textContent = "正在读取…";
  state.resultRows = [];
  state.tableRows = [];
  state.headers = [];
}

function renderResult(result) {
  state.resultRows = result.rows || []; state.tableRows = result.table || []; state.headers = result.headers || []; state.lastMode = currentMode();
  $("chart-title").textContent = result.title;
  $("table-title").textContent = `${result.title}｜计算结果表`;
  $("chart-note").textContent = result.note;
  $("summary-round").textContent = controls.round.value;
  $("summary-count").textContent = (result.table?.length ?? result.rows?.length ?? 0).toLocaleString("zh-CN");
  $("summary-chart").textContent = ({ bar: "条形图", line: "折线图", scatter: "散点图", bubble: "气泡图", dumbbell: "哑铃图", grouped: "分组柱状图", stacked: "堆叠柱状图", heatmap: "热力图", network: "网络图" }[result.chartType] || result.chartType || "—");
  $("summary-source").textContent = result.source_label || (result.desktopSnapshot ? "桌面快照 JSON" : "本地 CSV");
  $("loading-state").classList.add("hidden");
  if (result.chartType === "line") drawLine(result);
  else if (result.chartType === "scatter") drawScatter(result);
  else if (result.chartType === "bubble") drawScatter(result, true);
  else if (result.chartType === "dumbbell") drawDumbbell(result);
  else if (result.chartType === "heatmap") drawHeatmap(result);
  else if (result.chartType === "network") drawNetwork(result);
  else drawCategorical(result);
  applyChartZoom();
  renderTable(result);
}

function resultAsCSV() {
  if (isDesktopMode(state.lastMode)) {
    const lines = [state.headers, ...state.tableRows];
    return lines.map((line) => line.map((cell) => `"${String(cell ?? "").replaceAll('"', '""')}"`).join(",")).join("\r\n");
  }
  const lines = [state.headers, ...state.resultRows.map((row) => {
    const mode = state.lastMode;
    if (mode === "questionnaire") return [row.label || row.label_jp || row.node_path, row.count, row.rate, row.question_key, row.region];
    if (mode === "cp") return [row.combination_label || nameFor(row), row.rank, row.vote_count, row.vote_rate, row.member_count, row.source_type];
    if (mode === "arrangement") {
      const values = [nameFor(row), row.rank, row[controls.xMetric.value], row[controls.yMetric.value]];
      if (controls.yMetric.value !== "selection_count") values.push(row.selection_count);
      if (controls.xMetric.value !== "arrangement_total_count") values.push(row.arrangement_total_count);
      return values;
    }
    const values = [nameFor(row), row.rank, row[controls.metric.value]];
    if (controls.metric.value !== "selection_count") values.push(row.selection_count);
    values.push(row.selection_rate, row.source_type);
    return values;
  })];
  return lines.map((line) => line.map((cell) => `"${String(cell ?? "").replaceAll('"', '""')}"`).join(",")).join("\r\n");
}

function downloadCSV() {
  if (!state.resultRows.length && !state.tableRows.length) return;
  const blob = new Blob(["\uFEFF" + resultAsCSV()], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob), link = document.createElement("a");
  link.href = url; link.download = `touhou-vote-${controls.round.value}-${currentMode()}.csv`; link.click(); URL.revokeObjectURL(url);
}

function scheduleRefresh() {
  window.clearTimeout(window.__voteInputTimer);
  window.__voteInputTimer = window.setTimeout(refresh, 180);
}

async function refresh() {
  const serial = ++refreshSerial;
  const mode = currentMode();
  const templateKey = controls.template.value;
  releaseInactiveHeavyCaches(mode, controls.template.value);
  clearRenderedResult();
  $("loading-state").classList.remove("hidden");
  $("status-line").classList.remove("error-text");
  if (isDesktopMode(mode)) {
    try {
      const bundle = await loadBundle();
      const result = DYNAMIC_CROSS_TEMPLATE_KEYS.has(templateKey)
        ? await dynamicCrossResult(templateKey, bundle)
        : DYNAMIC_COVOTE_TEMPLATE_KEYS.has(templateKey)
        ? await dynamicCovoteResult(templateKey)
        : DYNAMIC_METRIC_TEMPLATE_KEYS.has(templateKey)
        ? await dynamicMetricResult(templateKey, bundle)
        : templateKey === "x_character"
        ? await dynamicCharacterResult()
        : ["q01_age", "q02_cognition", "q03_usertype", "q04_new"].includes(templateKey)
        ? await questionnaireCompareResult(templateKey)
        : templateKey === "q_custom"
        ? await customQuestionnaireCompareResult()
        : templateKey === "a17_concentration_clusters"
          ? await crossConcentrationClusterResult()
        : templateKey === "a18_music_concentration_clusters"
          ? await musicConcentrationClusterResult()
        : ENTITY_RELATION_TEMPLATE_KEYS.has(templateKey)
          ? await entityQuestionnaireResult(templateKey)
          : desktopSnapshotResult(bundle);
      if (serial !== refreshSerial) return;
      renderResult(result);
      $("status-line").textContent = DYNAMIC_CROSS_TEMPLATE_KEYS.has(templateKey) || ENTITY_RELATION_TEMPLATE_KEYS.has(templateKey) || DYNAMIC_METRIC_TEMPLATE_KEYS.has(templateKey) || ["x_character", "q01_age", "q02_cognition", "q03_usertype", "q04_new", "a01_direction_matrix", "a01_count_matrix", "a02_network", "a03_bubble", "a03_count_top", "a04_count_dumbbell", "a04_count_change", "a05_largest_change", "a06_lift", "a07_excess", "a08_phi", "a09_phi_change", "a10_direction", "a11_asymmetry", "a12_cumulative", "a13_quadrant", "a14_count_top10", "a15_lift_top10", "a16_anomalies", "a17_concentration_clusters", "a18_music_concentration_clusters", "x_covote"].includes(templateKey)
        ? `已按当前地区/届次读取全量分析 CSV；当前显示 ${result.table.length.toLocaleString("zh-CN")} 行。`
        : `已加载${projectLabel(mode)}模板静态快照；当前显示 ${result.table.length.toLocaleString("zh-CN")} 行。`;
    } catch (error) {
      if (serial !== refreshSerial) return;
      $("loading-state").classList.remove("hidden"); $("status-line").classList.add("error-text"); $("status-line").textContent = `${error.message}。请确认 web_data/templates.json 已部署。`;
    }
    return;
  }
  const kind = mode === "ranking" ? controls.subject.value : mode === "arrangement" ? "music" : mode;
  $("status-line").textContent = `正在读取 ${DATA_FILES[kind]} …`;
  try {
    const rows = await loadCSV(kind);
    if (serial !== refreshSerial) return;
    state.rows = rows;
    const result = mode === "ranking" ? rankingResult(rows) : mode === "arrangement" ? arrangementResult(rows) : mode === "cp" ? cpResult(rows) : questionnaireResult(rows);
    if (serial !== refreshSerial) return;
    renderResult(result);
    $("status-line").textContent = `已加载 ${rows.length.toLocaleString("zh-CN")} 行原始分析记录；当前显示 ${result.rows.length.toLocaleString("zh-CN")} 行。`;
  } catch (error) {
    if (serial !== refreshSerial) return;
    $("loading-state").classList.remove("hidden");
    $("status-line").classList.add("error-text");
    $("status-line").textContent = `${error.message}。请确认网页与 vote_explorer/data 位于同一仓库，或使用 ?data=./data/ 指定数据目录。`;
    $("chart-title").textContent = "读取数据失败";
    $("chart-note").textContent = "";
    $("chart").innerHTML = "";
  }
}

function reset() {
  // Restoring the analysis defaults also returns the chart viewport to its
  // neutral size, so a previous large-chart zoom does not leak into a new
  // default result.
  state.chartZoom = 1;
  controls.kind.value = "ranking"; controls.round.value = "CN11"; controls.subject.value = "character";
  controls.compareRound.value = "CN10"; controls.faction.value = "";
  controls.metric.value = "selection_count"; controls.xMetric.value = "arrangement_cumulative_count"; controls.yMetric.value = "selection_count";
  controls.topN.value = "20"; controls.minVotes.value = "0"; controls.search.value = "";
  controls.rankStart.value = "1"; controls.rankEnd.value = "100"; controls.minCount.value = "0";
  controls.sort.value = "desc"; controls.changeDirection.value = "all"; controls.language.value = "cn";
  controls.relationValueMode.value = "rate"; controls.relationSort.value = "count";
  updateQuestionOptions().finally(() => { updateControlVisibility(); refresh(); });
}

controls.kind.addEventListener("change", async () => {
  updateLightweightMetricOptions();
  if (isDesktopMode()) {
    try { updateCompareRoundOptions(); await updateDesktopTemplateOptions(); } catch (error) { /* refresh shows the actionable error */ }
  }
  updateControlVisibility();
  refresh();
});
controls.round.addEventListener("change", async () => {
  updateCompareRoundOptions();
  await updateKindAvailability();
  if (isDesktopMode()) {
    try { await updateDesktopTemplateOptions(); } catch (error) { /* refresh shows the actionable error */ }
  }
  updateControlVisibility();
  updateQuestionOptions().finally(refresh);
});
controls.compareRound.addEventListener("change", async () => {
  if (isDesktopMode()) {
    try { await updateDesktopTemplateOptions(); } catch (error) { /* refresh shows the actionable error */ }
  }
  updateControlVisibility();
  updateQuestionOptions().finally(refresh);
});
controls.subject.addEventListener("change", refresh);
controls.metric.addEventListener("change", refresh);
controls.xMetric.addEventListener("change", refresh);
controls.yMetric.addEventListener("change", refresh);
controls.question.addEventListener("change", refresh);
controls.template.addEventListener("change", async () => {
  // Template-specific controls (entity questionnaire, faction, comparison
  // round, rank/threshold filters, etc.) must be recalculated immediately
  // after the template changes.  Previously only the chart was refreshed,
  // leaving the controls from the previous template hidden or enabled.
  updateControlVisibility();
  try {
    const bundle = await loadBundle();
    if (["a17_concentration_clusters", "a18_music_concentration_clusters"].includes(controls.template.value) && integer(controls.minCount.value, 0) === 0) {
      // Keep the first graph readable like the desktop default.  The source
      // CSV is still complete; the user can explicitly enter 0 afterwards to
      // inspect every published edge.
      controls.minCount.value = "100";
    }
    updateFactionOptions(bundle);
    if (controls.template.value !== "a02_network") controls.faction.value = "";
    // Match the desktop workbench defaults: both the dedicated cognition
    // view and the work-level matrix start from the 入坑时间 question.  The
    // generic character/music matrices keep the user's last question choice.
    if (["r07_character_cognition", "r08_work_question_matrix"].includes(controls.template.value)) {
      controls.relationQuestion.value = "cognition";
    }
    updateRelationOptions(bundle);
    updateRelationMetricOptions();
    updateCustomMetricOptions();
    // q_custom draws its question list from both the selected and comparison
    // rounds. Rebuild it when switching templates as well as when switching
    // rounds; otherwise a question list from the previous project can remain
    // selected (for example JP3 → JP22 still showing only “年龄分布”).
    await updateQuestionOptions();
  } catch (error) {
    // The following refresh reports the actionable bundle-loading error.
  }
  updateControlVisibility();
  refresh();
});
controls.faction.addEventListener("change", () => { updateControlVisibility(); refresh(); });
controls.rankStart.addEventListener("input", scheduleRefresh);
controls.rankStart.addEventListener("change", scheduleRefresh);
controls.rankEnd.addEventListener("input", scheduleRefresh);
controls.rankEnd.addEventListener("change", scheduleRefresh);
controls.minCount.addEventListener("input", scheduleRefresh);
controls.minCount.addEventListener("change", scheduleRefresh);
controls.sort.addEventListener("change", refresh);
controls.changeDirection.addEventListener("change", refresh);
controls.language.addEventListener("change", refresh);
controls.relationQuestion.addEventListener("change", async () => {
  try { updateRelationOptions(await loadBundle()); } catch (error) { /* refresh will show source error */ }
  refresh();
});
controls.relationAnswer.addEventListener("change", refresh);
controls.relationValueMode.addEventListener("change", refresh);
controls.relationSort.addEventListener("change", refresh);
controls.topN.addEventListener("input", scheduleRefresh);
controls.topN.addEventListener("change", scheduleRefresh);
controls.minVotes.addEventListener("input", scheduleRefresh);
controls.minVotes.addEventListener("change", scheduleRefresh);
controls.search.addEventListener("input", () => { window.clearTimeout(window.__voteSearchTimer); window.__voteSearchTimer = window.setTimeout(refresh, 180); });
$("reset-button").addEventListener("click", reset);
$("download-button").addEventListener("click", downloadCSV);
$("chart-zoom-out").addEventListener("click", () => setChartZoom(state.chartZoom - .25));
$("chart-zoom-in").addEventListener("click", () => setChartZoom(state.chartZoom + .25));
$("chart-zoom-reset").addEventListener("click", () => setChartZoom(1));
$("chart-wrap").addEventListener("click", (event) => {
  const tag = String(event.target?.tagName || "").toLowerCase();
  if (!["circle", "rect", "line"].includes(tag)) hideChartTooltip();
});

prepareControls().then(refresh);
