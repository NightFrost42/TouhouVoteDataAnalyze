"""Package completed network analyses; never run an estimator or load raw matrices.

Each table/round/scope is fetched independently. Source cells remain strings so
blank values and 64-bit permutation seeds survive the Python/JS boundary.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

LEVELS = {
    "matrix_correlations": "矩阵相关（节点置换）",
    "hypothesis_tests": "结构假设检验",
    "mrqap_coefficients": "MRQAP / QAP 系数",
    "sensitivity_scan": "阈值敏感性（探索性）",
    "community_summary": "结构社区汇总",
    "community_assignments": "社区成员",
    "node_centrality": "节点中心性",
    "modularity_summary": "网络整体统计",
    "coverage": "数据覆盖与不可用原因",
}
MANIFESTS = {
    "hypothesis_tests": "hypothesis_tests_manifest.json",
    "matrix_correlations": "matrix_correlations_run_manifest.json",
    "mrqap_coefficients": "model_run_manifest.json",
}
CAVEATS = [
    "普通同投网络描述共同投票关系；研究型网络展示已完成的统计运行。",
    "缺失、未公开与删失不等于真实 0；完整性未知的结果不能进入完整矩阵筛选。",
    "结构社区不是原作阵营，共同投票不等于 CP 或原作关系，显著性不代表因果。",
    "探索性阈值扫描不是独立验证；p 值和校正后 p 值不在浏览器中重新计算。",
]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def within(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"source escapes repository: {value}")
    return path


def round_label(row: dict) -> str:
    value = row.get("round_label") or str(row.get("round", ""))
    if not value.upper().startswith(("CN", "JP")):
        value = str(row.get("region", "")).upper() + value
    if not re.fullmatch(r"(?:CN|JP)\d+(?:(?:_vs_|_to_|[-/→])(?:CN|JP)?\d+)?", value, re.I):
        raise ValueError(f"invalid round label: {value!r}")
    return value


def first(row: dict, *keys: str):
    return next((row[k] for k in keys if row.get(k) not in (None, "")), "")


def truth(value) -> bool:
    return str(value).lower() in {"true", "1"}


def normalize(level: str, raw: dict, manifest: dict) -> dict:
    """Add display/filter metadata without overwriting the estimator's cells."""
    row = dict(raw)
    par = manifest.get("parameters", {})
    test = manifest.get("statistical_test", {})
    inclusion = manifest.get("pair_inclusion", {})
    integrity = manifest.get("data_integrity", {})
    scope = first(row, "pair_category", "scope") or par.get("scope", "character")
    if level == "matrix_correlations" and not row.get("pair_category"):
        scope = "music" if all("music" in row.get(k, "") for k in ("matrix_a", "matrix_b")) else "character"
    completeness = first(row, "data_completeness", "metric_scope", "data_scope", "data_status") or par.get("data_policy", "not_reported")
    complete = completeness in {"complete_matrix", "exact_complete_2x2"}
    if level == "matrix_correlations":
        complete = truth(row.get("complete_pair_matrix"))
        completeness = "complete_matrix" if complete else "common_observed_pairs_only"
    if level == "mrqap_coefficients":
        # Source dyads and the fitted complete-case submatrix are different.
        complete = truth(row.get("complete_pair_matrix"))
        completeness = "complete_matrix" if complete else "model_complete_cases_only"
    pairs = first(row, "n_pairs", "pair_count", "effective_pair_n", "edge_count")
    pair_basis = "source_reported_pairs"
    if level == "hypothesis_tests":
        a, b = row.get("observation_n"), row.get("control_n")
        pairs = str(int(a) + int(b)) if a not in (None, "") and b not in (None, "") else ""
        pair_basis = "observation_n + control_n"
    elif level == "mrqap_coefficients":
        pairs = row.get("complete_case_n", "")
        pair_basis = "model_complete_case_n"
    elif level == "sensitivity_scan":
        pairs = row.get("effective_pair_n", row.get("n_pairs", ""))
        pair_basis = "effective_pair_n"
    elif level in {"community_assignments", "node_centrality"}:
        pairs = row.get("unweighted_degree", "")
        pair_basis = "node_incident_edges"
    elif level in {"community_summary", "modularity_summary"}:
        pair_basis = "community_internal_edges" if level == "community_summary" else "network_edges"
    elif level == "coverage":
        pairs = row.get("observed_pair_rows", "")
        pair_basis = "official_observed_pair_rows"
    elif level == "coverage":
        pairs = row.get("observed_pair_rows", "")
        pair_basis = "official_observed_pair_rows"
    method = first(row, "method", "correlation_method") or test.get("method", "not_reported")
    if level == "mrqap_coefficients":
        method = f"{row.get('model_type', '')}:{row.get('permutation_scheme', '')}"
    if level == "sensitivity_scan" and method == "not_reported":
        method = "node_attribute_permutation"
    metric = first(row, "metric", "dependent_metric", "metric_a", "weight_metric")
    threshold = first(row, "threshold")
    threshold_key = f"{first(row, 'threshold_type', 'weight_metric') or metric} ≥ {threshold}" if threshold != "" else "not_reported"
    exploratory = level == "sensitivity_scan" or "exploratory" in str(row.get("inference_status", "")).lower()
    warning = first(row, "warning")
    if integrity.get("status") not in (None, "passed"):
        warning = "; ".join(filter(None, [warning, f"source_integrity:{integrity['status']}"]))
    row.update({
        "web_round": round_label(row), "web_scope": scope, "web_metric": metric,
        "web_method": method, "web_threshold": threshold_key,
        "web_algorithm": first(row, "algorithm") or par.get("algorithm", "not_applicable"),
        "web_n_pairs": pairs, "web_pair_basis": pair_basis,
        "web_completeness": completeness, "web_complete_matrix": complete,
        "web_exploratory": exploratory,
        "web_censoring": first(row, "censoring_status") or "not_reported",
        "web_missing_policy": first(row, "missing_policy", "missing_pair_rule") or inclusion.get("missing_pair_policy", "not_reported"),
        "web_permutations": first(row, "permutations") if row.get("permutations") not in (None, "") else test.get("permutations", ""),
        "web_random_seed": first(row, "random_seed") if row.get("random_seed") not in (None, "") else test.get("random_seed", ""),
        "web_warning": warning,
        "web_adjustment": first(row, "adjustment_method") or ("holm" if par.get("holm") else "not_reported"),
        "web_adjustment": first(row, "adjustment_method") or ("holm" if par.get("holm") else "not_reported"),
    })
    return row


def build_research_bundle(root: Path, output: Path) -> dict:
    root, output = root.resolve(), output.resolve()
    sources = []
    notices = []
    groups = defaultdict(list)
    group_sources = defaultdict(set)

    def add(level: str, path: Path, manifest_path: Path | None = None):
        if not path.is_file():
            raise ValueError(f"manifest-listed output missing: {path}")
        data = path.read_bytes()
        manifest = read_json(manifest_path) if manifest_path else {}
        rel = path.relative_to(root).as_posix()
        sha = digest(data)
        if manifest_path:
            record = next((x for x in manifest.get("outputs", []) if x.get("path") == rel), None)
            if not record or not record.get("sha256") or record["sha256"] != sha:
                raise ValueError(f"source output hash mismatch or absent from manifest: {rel}")
        metadata = {
            "id": digest(rel.encode())[:16], "source_path": rel, "sha256": sha,
            "manifest_path": manifest_path.relative_to(root).as_posix() if manifest_path else None,
            "manifest_sha256": digest(manifest_path.read_bytes()) if manifest_path else None,
            "provenance_status": "output_hash_verified" if manifest_path else "no_run_manifest",
            "generated_at_utc": manifest.get("generated_at_utc"),
            "parameters": manifest.get("parameters", {}),
            "statistical_test": manifest.get("statistical_test", {}),
            "pair_inclusion": manifest.get("pair_inclusion", {}),
            "data_integrity": manifest.get("data_integrity", {}),
            "inputs": manifest.get("inputs", []), "code": manifest.get("code", {}),
            "verification_scope": "result CSV against run manifest; raw input matrices are not opened or revalidated",
        }
        if not manifest_path:
            metadata["warning"] = "没有对应运行清单；种子、请求置换次数等未报告参数保持未知，不从当前配置反推。"
        sources.append(metadata)
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""))
        if not reader.fieldnames:
            raise ValueError(f"missing CSV header: {rel}")
        for raw in reader:
            if None in raw or any(value is None for value in raw.values()):
                raise ValueError(f"malformed CSV row: {rel}:{reader.line_num}")
            row = normalize(level, raw, manifest)
            row["web_source_id"] = metadata["id"]
            row["web_source_path"] = rel
            row["web_provenance_status"] = metadata["provenance_status"]
            if not manifest_path:
                row["web_warning"] = "; ".join(filter(None, [row["web_warning"], "no_run_manifest; unreported_run_parameters_unknown"]))
            if not manifest_path:
                row["web_warning"] = "; ".join(filter(None, [row["web_warning"], "no_run_manifest; unreported_run_parameters_unknown"]))
            key = (level, row["web_round"], row["web_scope"])
            groups[key].append(row)
            group_sources[key].add(metadata["id"])

    inference = root / "analysis_results/network_inference"
    # Read current estimator runs. The optional unified export can be older.
    for level, filename in MANIFESTS.items():
        path = inference / f"{level}.csv"
        manifest_path = inference / filename
        if path.is_file():
            add(level, path, manifest_path if manifest_path.is_file() else None)
        else:
            notices.append(f"{level}: 尚未提供离线结果")
    path = inference / "sensitivity_scan.csv"
    if path.is_file():
        add("sensitivity_scan", path)
    else:
        notices.append("sensitivity_scan: 尚未提供离线结果")
    community = root / "analysis_results/network_communities"
    batches = sorted(community.rglob("all_rounds_manifest.json")) if community.exists() else []
    manifests = set()
    for batch in batches:
        for name in read_json(batch).get("run_manifests", []):
            manifests.add(within(root, name))
    # A single-run bundle is supported only when no batch lists that scope.
    batch_parents = {p.parent for p in batches}
    for parent in (community, community / "music", community / "cross_department"):
        if parent not in batch_parents and (parent / "community_run_manifest.json").is_file():
            manifests.add(parent / "community_run_manifest.json")
    for manifest_path in sorted(manifests):
        manifest = read_json(manifest_path)
        files = manifest.get("community_contract", {}).get("output_files", {})
        for level in ("community_summary", "community_assignments", "node_centrality", "modularity_summary"):
            if level in files:
                add(level, within(root, files[level]), manifest_path)
    if not manifests:
        notices.append("community: 尚未提供离线社区运行清单")
    coverage = root / "analysis_results/network_coverage.csv"
    if coverage.is_file():
        add("coverage", coverage)

    # Validate everything before publishing; write the index last. Content
    # hashes keep an old cached index usable during an incremental deployment.
    output.mkdir(parents=True, exist_ok=True)
    entries = []
    source_map = {s["id"]: s for s in sources}
    for (level, label, scope), rows in sorted(groups.items()):
        key = (level, label, scope)
        # Repeated run parameters belong in defaults, not on every node.
        columns = list(dict.fromkeys(k for row in rows for k in row))
        defaults = {k: rows[0][k] for k in columns if all(k in r and r[k] == rows[0].get(k) for r in rows)}
        columns = [k for k in columns if k not in defaults]
        payload = {"schema_version": 1, "level": level, "round": label, "scope": scope,
                   "columns": columns, "values": [[r.get(k, "") for k in columns] for r in rows],
                   "defaults": defaults, "row_count": len(rows),
                   "sources": [source_map[s] for s in sorted(group_sources[key])]}
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        sha = digest(data)
        filename = f"{level}-{label}-{scope}-{sha[:16]}.json"
        if not re.fullmatch(r"[\w.→-]+", filename):
            filename = f"{level}-{sha[:24]}.json"
        (output / filename).write_bytes(data)
        entries.append({"level": level, "round": label, "scope": scope,
                        "path": filename, "rows": len(rows),
                        "size_bytes": len(data), "sha256": sha})
    index = {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
             "levels": LEVELS, "caveats": CAVEATS, "notices": notices,
             "entries": entries, "total_rows": sum(e["rows"] for e in entries),
             "source_count": len(sources), "client_statistics": False}
    target = output / "index.json"
    temporary = output / "index.json.tmp"
    temporary.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(target)
    return index
