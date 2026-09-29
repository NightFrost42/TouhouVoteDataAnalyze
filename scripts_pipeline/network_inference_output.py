#!/usr/bin/env python3
"""Export already-computed network statistics as auditable tables and a report.

This module does not calculate an effect, p value, or multiple-testing
correction. It preserves the estimators' source columns alongside a small
common vocabulary. The CLI reads the three existing estimator outputs and
writes to a separate directory so their original files and manifests remain
unchanged.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from scripts_pipeline.model_run_manifest import write_model_run_manifest
except ImportError:  # direct invocation from scripts_pipeline/
    from model_run_manifest import write_model_run_manifest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "analysis_results" / "network_inference"
DEFAULT_OUTPUT_DIR = SOURCE_DIR
SCHEMA_PATH = ROOT / "metadata" / "network_inference_output.schema.json"
CONTRACT_VERSION = 1
TABLES = ("hypothesis_tests", "matrix_correlations", "mrqap_coefficients", "sensitivity_scan")
SOURCE_MANIFESTS = {
    "hypothesis_tests": "hypothesis_tests_manifest.json",
    "matrix_correlations": "matrix_correlations_run_manifest.json",
    "mrqap_coefficients": "model_run_manifest.json",
}
CAVEATS = (
    "共同投票不等于 CP 或原作关系",
    "空白不等于真实 0",
    "显著性不等于因果关系",
    "不同届次和地区的投票规则可能不同",
    "部分同投数据为公开关联列表而非完整矩阵",
)
COMMON_COLUMNS = (
    "analysis_id", "result_id", "region", "round", "round_label", "pair_category",
    "name_a", "name_b", "name_a_cn", "name_b_cn", "name_a_jp", "name_b_jp",
    "canonical_pair_key", "feature_id", "feature_label_zh", "feature_label_en",
    "metric", "method", "effect_size", "effect_size_type", "n_pairs", "n_nodes",
    "p_value", "q_value", "adjustment_method", "adjustment_family",
    "permutations", "valid_permutations", "random_seed", "missing_policy",
    "data_scope", "source_path", "status", "source_status", "warning",
)
SOURCE_COLUMNS = {
    "hypothesis_tests": (
        "analysis_name", "metric", "hypothesis", "observation_n", "control_n",
        "observation_median", "control_median", "u_statistic", "cliffs_delta",
        "ci_low", "ci_high", "raw_p", "adjusted_p", "inference_status",
        "data_status", "metric_scope",
    ),
    "matrix_correlations": (
        "matrix_a", "matrix_b", "node_count", "pair_count", "metric_a", "metric_b",
        "correlation_method", "observed_correlation", "permutation_p",
        "node_alignment_rule", "missing_pair_rule", "complete_pair_matrix",
        "source_complete_a", "source_complete_b", "interpretation_note",
    ),
    "mrqap_coefficients": (
        "dependent_metric", "model_type", "predictor", "coefficient", "ordinary_se",
        "ordinary_t", "ordinary_p", "qap_p", "permutations_used",
        "permutation_seed", "permutation_scheme", "r_squared", "complete_case_n",
        "n_pairs_total", "collinearity_diagnostic",
    ),
    "sensitivity_scan": (
        "scenario", "baseline_result_id", "threshold", "network_scope",
        "parameter_delta",
    ),
}
NUMERIC_COLUMNS = frozenset({
    "effect_size", "n_pairs", "n_nodes", "p_value", "q_value", "permutations",
    "valid_permutations", "random_seed", "observation_n", "control_n",
    "observation_median", "control_median", "u_statistic", "cliffs_delta",
    "ci_low", "ci_high", "raw_p", "adjusted_p", "node_count", "pair_count",
    "observed_correlation", "permutation_p", "coefficient", "ordinary_se",
    "ordinary_t", "ordinary_p", "qap_p", "permutations_used", "permutation_seed",
    "r_squared", "complete_case_n", "n_pairs_total", "threshold",
})
COUNT_COLUMNS = frozenset({
    "n_pairs", "n_nodes", "permutations", "valid_permutations", "observation_n",
    "control_n", "node_count", "pair_count", "permutations_used",
    "complete_case_n", "n_pairs_total",
})
PROBABILITY_COLUMNS = frozenset({
    "p_value", "q_value", "raw_p", "adjusted_p", "permutation_p", "qap_p",
    "ordinary_p",
})
FEATURE_LABELS = {
    "same_work": ("首次作品相同", "same work"),
    "same_first_appearance_work": ("首次作品相同", "same first appearance work"),
    "same_character_type": ("角色类型相同", "same character type"),
    "same_source_group": ("来源组相同", "same source group"),
    "same_stage": ("关卡相同", "same stage"),
    "same_work_adjacent_stage": ("同作品相邻关卡", "adjacent stage within work"),
    "same_region": ("区域相同", "same region"),
    "same_community": ("社群有交集", "shared community"),
    "log_count_a": ("端点 A 选择人数对数", "log selection count A"),
    "log_count_b": ("端点 B 选择人数对数", "log selection count B"),
}


class OutputContractError(ValueError):
    """The result bundle cannot be explained or verified as supplied."""


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise OutputContractError(f"file is outside the workspace: {path}") from exc


def _json(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (ValueError, TypeError) as exc:
        raise OutputContractError("configuration must be finite JSON data") from exc


def _number(value: Any, field: str) -> int | float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise OutputContractError(f"{field} cannot be boolean")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise OutputContractError(f"{field} must be numeric or empty: {value!r}") from exc
    if not math.isfinite(number):
        raise OutputContractError(f"{field} must be finite: {value!r}")
    if field in COUNT_COLUMNS and (not number.is_integer() or number < 0):
        raise OutputContractError(f"{field} must be a nonnegative integer: {value!r}")
    if field in PROBABILITY_COLUMNS and not 0 <= number <= 1:
        raise OutputContractError(f"{field} must be in [0,1]: {value!r}")
    return int(number) if field in COUNT_COLUMNS else number


def _pick(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if row.get(name) not in (None, ""):
            return row[name]
    return None


def _scope(table: str, row: Mapping[str, Any], context: Mapping[str, Any]) -> str:
    if table == "hypothesis_tests":
        return _text(_pick(row, "metric_scope", "data_status")) or "unreported"
    if table == "matrix_correlations":
        complete = _text(row.get("complete_pair_matrix")).lower() in {"true", "1"}
        return "complete_matrix" if complete else "common_observed_pairs_only"
    if table == "mrqap_coefficients":
        return _text(context.get("data_scope")) or "complete_matrix_source; model_complete_cases_reported_separately"
    return _text(_pick(row, "network_scope", "data_scope")) or "unreported"


def _identity(table: str, row: Mapping[str, Any]) -> tuple[str, str, str]:
    if table == "hypothesis_tests":
        value = _text(row.get("hypothesis"))
        labels = FEATURE_LABELS.get(value, (value, value))
        return value, *labels
    if table == "mrqap_coefficients":
        value = _text(row.get("predictor"))
        labels = FEATURE_LABELS.get(value, (value, value))
        return value, *labels
    if table == "matrix_correlations":
        value = f"{_text(row.get('metric_a'))}_vs_{_text(row.get('metric_b'))}"
        return value, f"{_text(row.get('metric_a'))} 与 {_text(row.get('metric_b'))} 的矩阵相关", f"matrix correlation: {_text(row.get('metric_a'))} vs {_text(row.get('metric_b'))}"
    value = _text(_pick(row, "feature_id", "scenario"))
    labels = FEATURE_LABELS.get(value, (value, value))
    return value, *labels


def _normalize_row(table: str, raw: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    allowed = set(COMMON_COLUMNS) | set(SOURCE_COLUMNS[table]) | {
        "region", "round", "round_label", "pair_category", "name_a", "name_b",
        "name_a_cn", "name_b_cn", "name_a_jp", "name_b_jp", "canonical_pair_key",
        "valid_permutations", "permutations", "random_seed", "missing_policy",
        "source_path", "status", "warning", "data_scope", "effect", "p", "q",
        "coef", "rho", "correlation", "zero_fill",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise OutputContractError(f"{table} contains unmapped fields: {unknown}")
    if _text(raw.get("zero_fill")).lower() in {"true", "yes", "1"}:
        raise OutputContractError("unknown relation cannot be filled as observed zero")
    missing_policy = _text(_pick(raw, "missing_policy", "missing_pair_rule")) or _text(context.get("missing_policy"))
    normalized_policy = missing_policy.casefold()
    permits_zero_fill = bool(re.search(r"(?:fill.?zero|zero.?fill|missing.?as.?zero)", normalized_policy)) and not bool(
        re.search(r"(?:no|not|never|without)[_\s-]*(?:fill.?zero|zero.?fill|missing.?as.?zero)", normalized_policy)
    )
    if not missing_policy or permits_zero_fill:
        raise OutputContractError("a no-zero-fill missing_policy is required")
    region = _text(raw.get("region"))
    round_value = _text(raw.get("round"))
    if not region or not round_value:
        raise OutputContractError(f"{table} requires region and round")
    round_label = _text(raw.get("round_label"))
    if not round_label:
        round_label = round_value.upper() if round_value.upper().startswith(("CN", "JP")) else f"{region.upper()}{round_value}"
    feature, label_zh, label_en = _identity(table, raw)
    analysis_id = _text(_pick(raw, "analysis_id", "analysis_name")) or _text(context.get("analysis_id"))
    if not analysis_id or not feature:
        raise OutputContractError(f"{table} requires analysis_id and feature_id")
    metric = _text(_pick(raw, "metric", "dependent_metric", "metric_a"))
    if not metric:
        raise OutputContractError(f"{table} requires a metric")
    if table == "hypothesis_tests":
        effect, p, q = raw.get("cliffs_delta"), raw.get("raw_p"), raw.get("adjusted_p")
        left = _number(raw.get("observation_n"), "observation_n")
        right = _number(raw.get("control_n"), "control_n")
        n_pairs = left + right if left is not None and right is not None else None
        method, effect_type = "node_attribute_permutation", "cliffs_delta"
    elif table == "matrix_correlations":
        effect, p, q = _pick(raw, "observed_correlation", "rho", "correlation"), raw.get("permutation_p"), None
        n_pairs = raw.get("pair_count")
        method, effect_type = _text(raw.get("correlation_method")), "matrix_correlation"
    elif table == "mrqap_coefficients":
        effect, p, q = _pick(raw, "coef", "coefficient"), raw.get("qap_p"), None
        n_pairs = raw.get("complete_case_n")
        method = f"{_text(raw.get('model_type'))}:{_text(raw.get('permutation_scheme'))}"
        effect_type = "mrqap_coefficient"
    else:
        effect, p, q = _pick(raw, "effect", "effect_size"), _pick(raw, "p", "p_value"), _pick(raw, "q", "q_value")
        n_pairs = raw.get("n_pairs")
        method, effect_type = _text(raw.get("method")) or "sensitivity_scan", _text(raw.get("effect_size_type")) or "sensitivity_effect"
    # A caller may use the common names instead of the source-specific aliases.
    effect = _pick(raw, "effect_size") if _pick(raw, "effect_size") is not None else effect
    p = _pick(raw, "p_value") if _pick(raw, "p_value") is not None else p
    q = _pick(raw, "q_value") if _pick(raw, "q_value") is not None else q
    effect = _number(effect, "effect_size")
    p = _number(p, "p_value")
    q = _number(q, "q_value")
    source_status = _text(_pick(raw, "source_status", "data_status", "status", "inference_status")) or "unreported"
    status = "not_estimable" if effect is None else ("estimated" if p is None else "tested")
    adjustment = _text(raw.get("adjustment_method")) or _text(context.get("adjustment_method"))
    if q is not None and (not adjustment or adjustment == "not_applied"):
        raise OutputContractError(f"{table} provides corrected p without a correction method")
    if not adjustment:
        adjustment = "not_applied"
    if q is None and adjustment != "not_applied" and p is not None:
        raise OutputContractError(f"{table} declares correction {adjustment} but has no corrected p")
    if effect is None and (p is not None or q is not None):
        raise OutputContractError(f"{table} has a p/q value without an estimable effect")
    if p is None and q is not None:
        raise OutputContractError(f"{table} has a corrected value without raw p")
    category = _text(raw.get("pair_category")) or _text(context.get("pair_category"))
    if table == "matrix_correlations" and not category:
        names = (_text(raw.get("matrix_a")), _text(raw.get("matrix_b")))
        category = "music" if all("music" in name for name in names) else "character"
    category = category or "character"
    name_a = _text(raw.get("name_a"))
    name_b = _text(raw.get("name_b"))
    if table == "matrix_correlations":
        name_a = name_a or _text(raw.get("matrix_a"))
        name_b = name_b or _text(raw.get("matrix_b"))
    normalized = {key: raw.get(key) for key in SOURCE_COLUMNS[table]}
    if table == "mrqap_coefficients":
        normalized["n_pairs_total"] = _number(raw.get("n_pairs"), "n_pairs_total")
    normalized.update({
        "analysis_id": analysis_id, "region": region, "round": round_value,
        "round_label": round_label, "pair_category": category,
        "name_a": name_a, "name_b": name_b,
        "name_a_cn": _text(raw.get("name_a_cn")), "name_b_cn": _text(raw.get("name_b_cn")),
        "name_a_jp": _text(raw.get("name_a_jp")), "name_b_jp": _text(raw.get("name_b_jp")),
        "canonical_pair_key": _text(raw.get("canonical_pair_key")),
        "feature_id": feature, "feature_label_zh": _text(raw.get("feature_label_zh")) or label_zh,
        "feature_label_en": _text(raw.get("feature_label_en")) or label_en,
        "metric": metric, "method": method, "effect_size": effect,
        "effect_size_type": _text(raw.get("effect_size_type")) or effect_type,
        "n_pairs": _number(n_pairs, "n_pairs"),
        "n_nodes": _number(_pick(raw, "n_nodes", "node_count"), "n_nodes"),
        "p_value": p, "q_value": q,
        "adjustment_method": adjustment,
        "adjustment_family": _text(raw.get("adjustment_family")) or "not_applicable",
        "permutations": _number(raw.get("permutations"), "permutations"),
        "valid_permutations": _number(_pick(raw, "valid_permutations", "permutations_used"), "valid_permutations"),
        "random_seed": _number(raw.get("random_seed"), "random_seed"),
        "missing_policy": missing_policy, "data_scope": _scope(table, raw, context),
        "source_path": _text(raw.get("source_path")) or _text(context.get("source_path")),
        "status": status, "source_status": source_status,
        "warning": _text(raw.get("warning")),
    })
    # Keep source values intact but validate every numeric source column, too.
    for key in NUMERIC_COLUMNS.intersection(normalized):
        if normalized[key] not in (None, ""):
            _number(normalized[key], key)
    if normalized["permutations"] is not None and normalized["valid_permutations"] is not None:
        if normalized["valid_permutations"] > normalized["permutations"]:
            raise OutputContractError(f"{table} has more valid than requested permutations")
    identity = (
        table, analysis_id, region, round_value, category, feature, metric, method,
        _text(raw.get("matrix_a")), _text(raw.get("matrix_b")), _text(raw.get("scenario")),
    )
    generated_id = "ni_" + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]
    normalized["result_id"] = _text(raw.get("result_id")) or generated_id
    return normalized


def _fieldnames(table: str) -> list[str]:
    return list(dict.fromkeys((*COMMON_COLUMNS, *SOURCE_COLUMNS[table])))


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(_json(value), ensure_ascii=False, separators=(",", ":"))
    return value


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise OutputContractError(f"missing header: {path}")
        return list(reader)


def _preflight_files(root: Path, input_files: Sequence[Path], output_dir: Path) -> list[Path]:
    inputs: list[Path] = []
    seen: set[str] = set()
    schema_candidate = root / "metadata" / "network_inference_output.schema.json"
    paths = [schema_candidate if schema_candidate.is_file() else SCHEMA_PATH, *input_files]
    for path in paths:
        candidate = (root / path).resolve() if not path.is_absolute() else path.resolve()
        relative = _relative(root, candidate)
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        if candidate == output_dir / candidate.name or candidate.parent == output_dir:
            raise OutputContractError("an input may not be overwritten by its output")
        if relative not in seen:
            inputs.append(candidate)
            seen.add(relative)
    return inputs


def write_network_inference_outputs(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    root: Path = ROOT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    analysis_config: Mapping[str, Any],
    input_files: Sequence[Path] = (),
    source_manifests: Sequence[Path] = (),
    replace_existing: bool = False,
) -> dict[str, Any]:
    """Write four tables, an auditable Markdown summary, and a run manifest.

    The caller supplies computed rows and full parameters. This writer never
    substitutes an unobserved pair or recalculates a correction. Files are
    validated before writing; an existing output directory is never replaced.
    """
    root = Path(root).resolve()
    output_dir = Path(output_dir)
    if not output_dir.is_absolute():
        output_dir = root / output_dir
    output_dir = output_dir.resolve()
    config = _json(dict(analysis_config))
    if not isinstance(config, dict) or not _text(config.get("analysis_id")):
        raise OutputContractError("analysis_config.analysis_id is required")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise OutputContractError(f"output directory is not empty (preserving existing work): {output_dir}")
    if not output_dir.is_relative_to(root):
        raise OutputContractError("output directory must be inside the workspace")
    if set(tables) - set(TABLES):
        raise OutputContractError(f"unknown tables: {sorted(set(tables) - set(TABLES))}")
    contexts = config.get("table_context", {})
    if not isinstance(contexts, dict):
        raise OutputContractError("analysis_config.table_context must be an object")
    rows_by_table: dict[str, list[dict[str, Any]]] = {}
    ids: set[str] = set()
    for table in TABLES:
        context = {"analysis_id": config["analysis_id"], "missing_policy": config.get("missing_policy"), **contexts.get(table, {})}
        if not isinstance(context, dict):
            raise OutputContractError(f"table_context.{table} must be an object")
        rows: list[dict[str, Any]] = []
        for raw in tables.get(table, ()):
            if not isinstance(raw, Mapping):
                raise OutputContractError(f"{table} expects object rows")
            row = _normalize_row(table, raw, context)
            if row["result_id"] in ids:
                raise OutputContractError(f"duplicate result_id: {row['result_id']}")
            ids.add(row["result_id"])
            rows.append(row)
        rows_by_table[table] = rows
    manifest_paths = [Path(path) for path in source_manifests]
    inputs = _preflight_files(root, [*input_files, *manifest_paths], output_dir)
    upstream = []
    node_ids: set[str] = set()
    for path in manifest_paths:
        absolute = (root / path).resolve() if not path.is_absolute() else path.resolve()
        value = json.loads(absolute.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise OutputContractError(f"invalid source manifest: {path}")
        upstream.append({"path": _relative(root, absolute), "analysis": value.get("analysis", {}),
                         "sha256": hashlib.sha256(absolute.read_bytes()).hexdigest()})
        node_ids.update(value.get("node_set", {}).get("ids", []))
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "figures").mkdir(exist_ok=True)
    output_records = []
    for table in TABLES:
        fields = _fieldnames(table)
        path = output_dir / f"{table}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
            writer.writeheader()
            for row in rows_by_table[table]:
                writer.writerow({key: _csv_value(row.get(key)) for key in fields})
        output_records.append({"path": _relative(root, path), "role": table,
                               "row_count": len(rows_by_table[table]), "columns": fields})
    counts = {table: len(rows_by_table[table]) for table in TABLES}
    warning_counts = Counter(row["warning"] for rows in rows_by_table.values() for row in rows if row["warning"])
    scope_counts = Counter(row["data_scope"] for rows in rows_by_table.values() for row in rows)
    summary = ["# 网络统计分析审计摘要", "", "以下数值直接来自同目录 CSV；表格和运行清单是审计依据，图片不是。", "",
               "## 数据范围与缺失政策", "",
               f"- 地区：{', '.join(sorted({row['region'] for rows in rows_by_table.values() for row in rows})) or '无结果行'}",
               f"- 届次：{', '.join(sorted({row['round_label'] for rows in rows_by_table.values() for row in rows})) or '无结果行'}",
               f"- 结果范围：{', '.join(f'{key} ({count})' for key, count in sorted(scope_counts.items())) or '无结果行'}",
               f"- 缺失政策：`{config.get('missing_policy', '见各结果行')}`；每行另存 `missing_policy`。", "",
               "## 指标解释", "",
               "- 假设检验的效应量为 Cliff's delta，`p_value` 为节点属性置换原始 p；已提供的 `q_value` 沿用上游 Holm 校正及其 `adjustment_family`。",
               "- 矩阵相关的效应量为 Pearson 或 Spearman 相关；`p_value` 来自同步节点置换。",
               "- MRQAP 效应量为模型系数；`p_value` 为 QAP 置换 p，普通回归 p 保留在 `ordinary_p`，不混用。",
               "- `q_value` 空白且 `adjustment_method=not_applied` 表示该来源未提供多重校正；不是 q=0。", "",
               "## 结果（每行均可在对应 CSV 中凭 result_id 检索）", "",
               "| 表 | result_id | 地区/届次 | 指标/特征 | 有效 pair | 效应量 | p 值 | 校正值 q | 校正方式 | 状态 |",
               "|---|---|---|---|---:|---:|---:|---:|---|---|"]
    for table in TABLES:
        for row in rows_by_table[table]:
            def show(value: Any) -> str:
                return "—" if value is None or value == "" else str(value).replace("|", "\\|").replace("\n", " ")
            summary.append(f"| `{table}.csv` | `{show(row['result_id'])}` | {show(row['region'])}/{show(row['round_label'])} | {show(row['metric'])} / {show(row['feature_label_zh'])} | {show(row['n_pairs'])} | {show(row['effect_size'])} | {show(row['p_value'])} | {show(row['q_value'])} | {show(row['adjustment_method'])} | {show(row['status'])} |")
    summary.extend(["", "## 覆盖与警告", ""])
    for table in TABLES:
        summary.append(f"- `{table}.csv`：{counts[table]} 行；{sum(row['status'] == 'not_estimable' for row in rows_by_table[table])} 行无法估计。")
    if not rows_by_table["sensitivity_scan"]:
        summary.append("- 尚未提供敏感性扫描结果；`sensitivity_scan.csv` 仅有表头，不能视为稳健性证据。")
    for warning, count in sorted(warning_counts.items()):
        summary.append(f"- 来源警告（{count} 行）：{warning}")
    for caveat in CAVEATS:
        summary.append(f"- {caveat}。")
    summary.extend(["", "## 溯源", "", f"- 输入及输出的 SHA-256、版本、参数和缺失记录：`model_run_manifest.json`。",
                    "- 字段契约：`metadata/network_inference_output.schema.json`。", "- `figures/` 为可选展示，不包含独占数值。", ""])
    summary_path = output_dir / "analysis_summary.md"
    summary_path.write_text("\n".join(summary), encoding="utf-8")
    output_records.append({"path": _relative(root, summary_path), "role": "analysis_summary"})
    readme_path = output_dir / "README.md"
    readme_path.write_text(
        "# 统一网络统计输出\n\n"
        "本目录由 `scripts_pipeline/network_inference_output.py` 从已完成的统计脚本结果生成；\n"
        "它不重新计算效应量、p 值或多重校正。CSV/JSON/Markdown 是审计主输出，`figures/` 只是可选展示。\n\n"
        "- `hypothesis_tests.csv`：结构假设检验；\n"
        "- `matrix_correlations.csv`：带同步节点置换的矩阵相关；\n"
        "- `mrqap_coefficients.csv`：MRQAP/QAP 系数；\n"
        "- `sensitivity_scan.csv`：实际提供的敏感性场景（无场景时仅保留表头并在摘要警告）；\n"
        "- `analysis_summary.md`：由结果表和配置生成的摘要；\n"
        "- `model_run_manifest.json`：输入/输出哈希、参数和来源运行清单。\n\n"
        "共同投票不等于 CP 或原作关系；空白不等于真实 0；显著性不等于因果关系；"
        "不同届次和地区的投票规则可能不同；部分同投数据为公开关联列表而非完整矩阵。\n",
        encoding="utf-8",
    )
    output_records.append({"path": _relative(root, readme_path), "role": "output_readme"})
    test = config.get("statistical_test", {})
    if not isinstance(test, dict):
        raise OutputContractError("statistical_test must be an object")
    parameters = {"output_contract_version": CONTRACT_VERSION,
                  "output_contract": {
                      "name": "network-inference-output-v1",
                      "schema_version": CONTRACT_VERSION,
                      "schema_path": "metadata/network_inference_output.schema.json",
                      "tables": {table: f"{table}.csv" for table in TABLES},
                      "summary": "analysis_summary.md",
                      "figures_optional": True,
                  },
                  "schema_path": "metadata/network_inference_output.schema.json",
                  "table_order": list(TABLES),
                  "table_columns": {table: _fieldnames(table) for table in TABLES},
                  "analysis_config": config,
                  "fixed_warnings": list(CAVEATS),
                  "configuration": config,
                  "table_counts": counts, "upstream_manifests": upstream,
                  "figures_policy": "optional; not hashed as numerical evidence", "fixed_caveats": list(CAVEATS)}
    script_reference = "scripts_pipeline/network_inference_output.py"
    try:
        script_reference = _relative(root, Path(__file__))
    except OutputContractError:
        # A caller may use a temporary workspace for a fixture; the relative
        # source reference remains valid in the repository contract.
        pass
    manifest = write_model_run_manifest(
        output_dir / "model_run_manifest.json", root=root,
        analysis=config["analysis_id"], analysis_version=_text(config.get("analysis_version")) or "1.0.0",
        inputs=[{"path": _relative(root, path), "role": "source_or_schema"} for path in inputs],
        outputs=output_records, parameters=parameters,
        test_method=_text(test.get("method")) or "upstream_statistics_only",
        random_seed=test.get("random_seed"), permutations=test.get("permutations", 0),
        tail=_text(test.get("tail")) or "two-sided",
        statistical_test={"method": _text(test.get("method")) or "upstream_statistics_only",
                          "random_seed": test.get("random_seed"), "permutations": test.get("permutations", 0),
                          "tail": _text(test.get("tail")) or "two-sided",
                          "by_source": {table: contexts.get(table, {}) for table in TABLES}},
        node_set={"entity_type": "mixed_network_nodes", "source": "upstream model run manifests",
                  "selection_rule": "union of upstream reported IDs across separate analyses; not a common analysis universe",
                  "ids": sorted(node_ids)},
        pair_inclusion={"rule": "upstream scripts' observed dyads; see per-source manifests",
                        "missing_pair_policy": config.get("missing_policy", "exclude_unknown_no_zero_fill"),
                        "directed": False, "self_pairs": False,
                        "deduplication": "result_id; upstream dyad keys in source manifests"},
        data_integrity={"status": "passed_with_warnings" if warning_counts or not counts["sensitivity_scan"] else "passed",
                        "checks": [{"name": "numeric_values_finite", "ok": True},
                                   {"name": "no_unknown_pair_zero_fill", "ok": True}],
                        "coverage": counts,
                        "missing": {"sensitivity_not_run": not bool(counts["sensitivity_scan"]),
                                    "not_estimable": {table: sum(row["status"] == "not_estimable" for row in rows_by_table[table]) for table in TABLES}},
                        "warnings": list(warning_counts) + (["sensitivity scan not supplied"] if not counts["sensitivity_scan"] else [])},
        script=script_reference,
    )
    return manifest


def consolidate_existing_results(*, root: Path = ROOT, source_dir: Path = SOURCE_DIR,
                                 output_dir: Path = DEFAULT_OUTPUT_DIR,
                                 sensitivity_path: Path | None = None) -> dict[str, Any]:
    """Adapt local estimator tables without replacing their original CSVs."""
    root = Path(root).resolve()
    source_dir = Path(source_dir).resolve()
    tables = {}
    input_paths = []
    manifests = []
    contexts = {}
    for table in TABLES:
        path = Path(sensitivity_path) if table == "sensitivity_scan" and sensitivity_path else source_dir / f"{table}.csv"
        if path.is_file():
            tables[table] = _read_csv(path)
            input_paths.append(path)
        else:
            tables[table] = []
        filename = SOURCE_MANIFESTS.get(table)
        if filename:
            manifest_path = source_dir / filename
            if manifest_path.is_file():
                manifests.append(manifest_path)
                manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
                contexts[table] = {
                    "source_path": _relative(root, path),
                    "source_analysis": manifest["analysis"]["name"],
                    "test": manifest["statistical_test"],
                    "missing_policy": manifest["pair_inclusion"]["missing_pair_policy"],
                    "adjustment_method": "holm" if manifest.get("parameters", {}).get("holm") else "not_applied",
                }
                for item in manifest.get("inputs", ()):
                    candidate = root / item["path"]
                    if candidate.is_file():
                        input_paths.append(candidate)
    config = {"analysis_id": "network_inference_consolidated", "analysis_version": "1.0.0",
              "missing_policy": "exclude_unknown_no_zero_fill",
              "table_context": contexts,
              "statistical_test": {"method": "per-source; see by_source", "random_seed": None,
                                   "permutations": 0, "tail": "two-sided"}}
    return write_network_inference_outputs(
        tables, root=root, output_dir=output_dir, analysis_config=config,
        input_files=input_paths, source_manifests=manifests,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--sensitivity", type=Path)
    args = parser.parse_args(argv)
    manifest = consolidate_existing_results(root=args.root, source_dir=args.source_dir,
                                            output_dir=args.output_dir, sensitivity_path=args.sensitivity)
    print(json.dumps({"output": str(args.output_dir), "counts": manifest["parameters"]["table_counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
