"""Independent audit of the unified same-department co-vote metrics.

The audit reads raw CN four-cell payloads, JP published association rows, vote
marginals, and the generated portable pair table without calling the builder.
It makes the distinction between a complete CN matrix and a JP leading list
machine-checkable.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from covote_metrics import EXACT_2X2_FIELDS, CN_CELL_CONVENTION, exact_2x2_metrics


WORKSPACE = Path(__file__).resolve().parents[1]
DATA_ROOT = WORKSPACE / "vote_explorer" / "data"
PAIR_PATH = DATA_ROOT / "analysis_covote_pairs_all.csv"
CHARACTER_PATH = DATA_ROOT / "analysis_character_metrics_all.csv"
MUSIC_PATH = DATA_ROOT / "analysis_music_metrics_all.csv"
JP_ASSOCIATION_PATH = WORKSPACE / "data_processed" / "jp_unified" / "entity_association_long.csv.gz"
CROSS_DEPARTMENT_PATH = DATA_ROOT / "analysis_character_music_covote_all.csv"
REPORT_JSON = WORKSPACE / "analysis_results" / "covote_metrics_audit.json"
REPORT_MD = WORKSPACE / "analysis_results" / "covote_metrics_audit.md"


# These are the cells and exact-2x2 values that must remain empty for a JP
# leading-list row.  ``lift`` is deliberately excluded: JP publishes a
# conditional/overall rate ratio that is useful even though it is not a
# complete-matrix independence lift.
JP_EXACT_FIELDS = (
    "m00_both_selected", "m01_b_only", "m10_a_only", "m11_neither_selected",
    "baseline_count", "excess_count", "cosine", "cosine_ochiai", "ochiai",
    "jaccard", "pmi", "pmi_nats", "npmi", "phi",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_gzip_csv(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def integer(value: Any) -> int | None:
    result = number(value)
    if result is None or not result.is_integer():
        return None
    return int(result)


def normalize(value: Any) -> str:
    return "".join(
        ch for ch in str(value or "").casefold()
        if ch not in " \t\r\n・･·-—_"
    )


def pair_key(a: Any, b: Any) -> tuple[str, str]:
    return tuple(sorted((normalize(a), normalize(b))))


def blank(value: Any) -> bool:
    return value in (None, "")


def close(left: Any, right: Any, tolerance: float = 1e-10) -> bool:
    a, b = number(left), number(right)
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tolerance * max(1.0, abs(a), abs(b))


def finite_fields(row: dict[str, Any], fields: Iterable[str]) -> list[str]:
    invalid: list[str] = []
    for field in fields:
        raw = row.get(field)
        if raw in (None, ""):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            invalid.append(field)
    return invalid


def load_generated_pairs() -> list[dict[str, str]]:
    return read_csv(PAIR_PATH)


def audit_cn_matrix(
    round_number: int,
    category: str,
    generated: list[dict[str, str]],
) -> dict[str, Any]:
    filename = "characters.json" if category == "character" else "music.json"
    graphql_key = "queryCharsCovote" if category == "character" else "queryMusicsCovote"
    source_path = WORKSPACE / "data_raw" / "cn_official" / f"round_{round_number:02d}" / "covote" / filename
    validation_path = source_path.with_name(f"{category}_reconstruction_validation.json")
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    items = payload.get("data", {}).get(graphql_key, {}).get("items", [])
    expected = integer(validation.get("expectedPairs"))
    universe = integer(validation.get("universe"))
    pair_rows = [
        row for row in generated
        if row.get("region") == "cn"
        and integer(row.get("round")) == round_number
        and (row.get("pair_category") or ("music" if "music" in row.get("source_type", "") else "character")) == category
    ]
    raw_keys: set[tuple[str, str]] = set()
    duplicate_raw = 0
    cell_errors: list[dict[str, Any]] = []
    raw_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            cell_errors.append({"reason": "item_not_object"})
            continue
        key = pair_key(item.get("a"), item.get("b"))
        if key in raw_keys:
            duplicate_raw += 1
        raw_keys.add(key)
        cells = tuple(item.get(field) for field in ("m00", "m01", "m10", "m11"))
        try:
            calculated = exact_2x2_metrics(*cells)
        except (TypeError, ValueError, AssertionError) as exc:
            cell_errors.append({"pair": list(key), "reason": str(exc)})
            continue
        if universe is not None and calculated["ballots"] != universe:
            cell_errors.append({"pair": list(key), "reason": "cell_sum_not_universe"})
        raw_by_key[key] = calculated

    generated_by_key: dict[tuple[str, str], dict[str, str]] = {}
    duplicate_generated = 0
    for row in pair_rows:
        key = pair_key(row.get("name_a"), row.get("name_b"))
        if key in generated_by_key:
            duplicate_generated += 1
        generated_by_key[key] = row

    missing = sorted(raw_keys - set(generated_by_key))
    extra = sorted(set(generated_by_key) - raw_keys)
    mismatches: list[dict[str, Any]] = []
    zero_preservation_failures = 0
    exact_metric_rows = 0
    nonfinite_rows = 0
    for key, expected_values in raw_by_key.items():
        row = generated_by_key.get(key)
        if row is None:
            continue
        if row.get("metric_status") == "exact_complete_2x2":
            exact_metric_rows += 1
        if finite_fields(row, [
            "count_a", "count_b", "ballots", "intersection_count", "share", "baseline_count",
            "lift", "excess_count", "cosine", "ochiai", "jaccard", "pmi", "npmi", "phi",
        ]):
            nonfinite_rows += 1
        for field in (
            "m00_both_selected", "m01_b_only", "m10_a_only", "m11_neither_selected",
            "count_a", "count_b", "ballots", "intersection_count", "raw_count",
        ):
            if not close(row.get(field), expected_values.get(field)):
                if len(mismatches) < 20:
                    mismatches.append({"pair": list(key), "field": field, "expected": expected_values.get(field), "actual": row.get(field)})
        if expected_values["intersection_count"] == 0 and blank(row.get("raw_count")):
            zero_preservation_failures += 1
    return {
        "round": round_number,
        "category": category,
        "source_path": source_path.relative_to(WORKSPACE).as_posix(),
        "validation_path": validation_path.relative_to(WORKSPACE).as_posix(),
        "expected_pairs": expected,
        "raw_items": len(items),
        "raw_unique_pairs": len(raw_keys),
        "generated_rows": len(pair_rows),
        "generated_unique_pairs": len(generated_by_key),
        "missing_generated_pairs": len(missing),
        "extra_generated_pairs": len(extra),
        "duplicate_raw_pairs": duplicate_raw,
        "duplicate_generated_pairs": duplicate_generated,
        "cell_errors": len(cell_errors),
        "cell_error_examples": cell_errors[:10],
        "mismatch_count": len(mismatches),
        "mismatch_examples": mismatches,
        "zero_preservation_failures": zero_preservation_failures,
        "exact_metric_rows": exact_metric_rows,
        "nonfinite_rows": nonfinite_rows,
        "validation": {
            "expected_equals_observed": expected == integer(validation.get("observedPairs")),
            "cell_convention": payload.get("context", {}).get("fieldConvention"),
            "cell_convention_matches": payload.get("context", {}).get("fieldConvention") == CN_CELL_CONVENTION,
            "all_marginal_and_universe_identities_passed": validation.get("allMarginalAndUniverseIdentitiesPassed"),
            "all_conditional_symmetry_checks_passed": validation.get(
                "allConditionalSymmetryChecksPassed",
                validation.get("allAvailableConditionalSymmetryChecksPassed"),
            ),
            "universe": universe,
        },
    }


def audit_jp(
    generated: list[dict[str, str]],
    character_rows: list[dict[str, str]],
    music_rows: list[dict[str, str]],
    association_rows: list[dict[str, str]],
) -> dict[str, Any]:
    metric_rows = {"character": character_rows, "music": music_rows}
    candidate_counts: dict[tuple[int, str], int] = Counter()
    for category, rows in metric_rows.items():
        for row in rows:
            if row.get("region") == "jp" and 11 <= (integer(row.get("round")) or 0) <= 22:
                candidate_counts[(integer(row.get("round")) or 0, category)] += 1

    observed: dict[tuple[int, str], set[tuple[str, str]]] = defaultdict(set)
    direction_counts: Counter[tuple[int, str, tuple[str, str]]] = Counter()
    for row in association_rows:
        round_number = integer(row.get("round"))
        category = str(row.get("source_category") or "")
        if round_number is None or not 11 <= round_number <= 22 or category not in metric_rows:
            continue
        if row.get("target_category") != category:
            continue
        key = pair_key(row.get("source_name"), row.get("target_name"))
        if not all(key) or key[0] == key[1]:
            continue
        observed[(round_number, category)].add(key)
        direction_counts[(round_number, category, key)] += 1

    output: list[dict[str, Any]] = []
    hard_failures: list[str] = []
    for round_number in range(11, 23):
        for category in ("character", "music"):
            n = candidate_counts[(round_number, category)]
            possible = n * (n - 1) // 2
            observed_pairs = observed[(round_number, category)]
            rows = [
                row for row in generated
                if row.get("region") == "jp"
                and integer(row.get("round")) == round_number
                and row.get("pair_category") == category
            ]
            exact_nonblank = 0
            raw_count_rows = 0
            conditional_rows = 0
            lift_rows = 0
            status_counts: Counter[str] = Counter()
            for row in rows:
                status_counts[str(row.get("metric_status") or "missing_status")] += 1
                if str(row.get("complete_pair_matrix", "")).casefold() == "true":
                    hard_failures.append(f"JP{round_number} {category} row marked complete")
                if any(not blank(row.get(field)) for field in JP_EXACT_FIELDS):
                    exact_nonblank += 1
                if not blank(row.get("raw_count")):
                    raw_count_rows += 1
                if not blank(row.get("conditional_rate_a_to_b")) or not blank(row.get("conditional_rate_b_to_a")):
                    conditional_rows += 1
                if not blank(row.get("lift_a_to_b")) or not blank(row.get("lift_b_to_a")):
                    lift_rows += 1
            generated_keys = {pair_key(row.get("name_a"), row.get("name_b")) for row in rows}
            missing_in_generated = len(observed_pairs - generated_keys)
            extra_in_generated = len(generated_keys - observed_pairs)
            conflicts = sum(
                1 for row in rows if row.get("metric_status") == "conflicting_published_directions"
            )
            item = {
                "round": round_number,
                "category": category,
                "candidate_entities": n,
                "possible_pairs": possible,
                "observed_published_pairs": len(observed_pairs),
                "coverage": len(observed_pairs) / possible if possible else None,
                "published_direction_rows": sum(
                    count for (rr, cc, _key), count in direction_counts.items()
                    if rr == round_number and cc == category
                ),
                "bidirectional_pairs": sum(
                    count > 1 for (rr, cc, _key), count in direction_counts.items()
                    if rr == round_number and cc == category
                ),
                "generated_rows": len(rows),
                "missing_observed_pairs_in_generated": missing_in_generated,
                "extra_generated_pairs": extra_in_generated,
                "conflicting_published_direction_rows": conflicts,
                "metric_status_counts": dict(sorted(status_counts.items())),
                "available_metric_rows": {
                    "raw_count": raw_count_rows,
                    "conditional_rate": conditional_rows,
                    "published_rate_ratio_lift": lift_rows,
                    "complete_2x2_metrics": 0,
                },
                "complete_2x2_nonblank_cells": exact_nonblank,
            }
            output.append(item)
            if missing_in_generated or extra_in_generated:
                hard_failures.append(f"JP{round_number} {category} generated pair set differs from published rows")
            if exact_nonblank:
                hard_failures.append(f"JP{round_number} {category} emitted complete 2x2 values")
    return {"by_round_category": output, "hard_failures": hard_failures}


def audit_cross_department(generated: list[dict[str, str]]) -> dict[str, Any]:
    rows = read_csv(CROSS_DEPARTMENT_PATH) if CROSS_DEPARTMENT_PATH.exists() else []
    exact_nonblank = sum(
        any(not blank(row.get(field)) for field in JP_EXACT_FIELDS)
        for row in rows
    )
    statuses = Counter(str(row.get("metric_status") or "missing_status") for row in rows)
    return {
        "rows": len(rows),
        "exact_2x2_nonblank_rows": exact_nonblank,
        "metric_status_counts": dict(sorted(statuses.items())),
        "complete_pair_matrix_true_rows": sum(
            str(row.get("complete_pair_matrix", "")).casefold() == "true" for row in rows
        ),
    }


def make_markdown(report: dict[str, Any]) -> str:
    cn = report["cn"]
    jp = report["jp"]["by_round_category"]
    lines = [
        "# 同投指标完整性审计",
        "",
        f"结论：**{report['status']}**。本报告独立读取 CN 四格矩阵、JP 关联前列、边际榜和生成主表。",
        "",
        "## CN 完整 2×2",
        "",
        "| 届次 | 类别 | 源 pair | 输出 pair | coverage | 完整指标行 | mismatch | 零值丢失 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in cn:
        lines.append(
            f"| CN{item['round']} | {item['category']} | {item['raw_unique_pairs']:,} | {item['generated_unique_pairs']:,} | "
            f"{item['generated_unique_pairs'] / item['raw_unique_pairs']:.2%} | {item['exact_metric_rows']:,} | "
            f"{item['mismatch_count']:,} | {item['zero_preservation_failures']:,} |"
        )
    lines.extend([
        "",
        "## JP 关联前列",
        "",
        "| 届次 | 类别 | 候选实体 | 可能对数 | 已发布对数 | coverage | 双向对 | 完整2×2非空 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ])
    for item in jp:
        lines.append(
            f"| JP{item['round']} | {item['category']} | {item['candidate_entities']:,} | {item['possible_pairs']:,} | "
            f"{item['observed_published_pairs']:,} | {item['coverage']:.2%} | {item['bidirectional_pairs']:,} | "
            f"{item['complete_2x2_nonblank_cells']:,} |"
        )
    cross = report["cross_department"]
    lines.extend([
        "",
        "## 跨部门角色×曲子",
        "",
        f"行数 {cross['rows']:,}；完整 2×2 非空行 {cross['exact_2x2_nonblank_rows']:,}；标记 complete_pair_matrix=true 的行 {cross['complete_pair_matrix_true_rows']:,}。",
        "",
        "空白指标表示证据不足或数学上未定义，不表示 0。JP 未发布的实体对保持未知；JP 的 rate-ratio lift 与完整矩阵 independence lift 分开解释。",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    generated = load_generated_pairs()
    character_rows = read_csv(CHARACTER_PATH)
    music_rows = read_csv(MUSIC_PATH)
    association_rows = read_gzip_csv(JP_ASSOCIATION_PATH)
    cn = [
        audit_cn_matrix(round_number, category, generated)
        for round_number in (10, 11)
        for category in ("character", "music")
    ]
    jp = audit_jp(generated, character_rows, music_rows, association_rows)
    cross = audit_cross_department(generated)
    hard_failures: list[str] = []
    for item in cn:
        if item["expected_pairs"] != item["raw_unique_pairs"] or item["raw_unique_pairs"] != item["generated_unique_pairs"]:
            hard_failures.append(f"CN{item['round']} {item['category']} pair conservation failed")
        if item["duplicate_raw_pairs"] or item["duplicate_generated_pairs"] or item["cell_errors"] or item["mismatch_count"] or item["zero_preservation_failures"]:
            hard_failures.append(f"CN{item['round']} {item['category']} raw/cell validation failed")
        if not item["validation"]["cell_convention_matches"] or not item["validation"]["all_marginal_and_universe_identities_passed"]:
            hard_failures.append(f"CN{item['round']} {item['category']} source proof failed")
    hard_failures.extend(jp["hard_failures"])
    if cross["exact_2x2_nonblank_rows"] or cross["complete_pair_matrix_true_rows"]:
        hard_failures.append("cross-department rows emitted complete 2x2 metrics")
    report = {
        "schema_version": 1,
        "status": "FAIL" if hard_failures else "PASS",
        "hard_failures": hard_failures,
        "policy": {
            "cn_complete_matrix": "compute all exact 2x2 metrics from verified m00/m01/m10/m11",
            "jp_published_leading_list": "keep raw/conditional/rate-ratio lift; suppress complete 2x2 metrics and missing-pair zeros",
            "cross_department": "conditional/lift only because character and music use different ballot universes",
        },
        "cn": cn,
        "jp": jp,
        "cross_department": cross,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(make_markdown(report), encoding="utf-8")
    manifest_path = DATA_ROOT / "analysis_data_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["covote_metrics_audit"] = {
            "status": report["status"],
            "report": REPORT_JSON.relative_to(WORKSPACE).as_posix(),
            "report_sha256": sha256(REPORT_JSON),
            "markdown_report": REPORT_MD.relative_to(WORKSPACE).as_posix(),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "hard_failures": hard_failures}, ensure_ascii=False, indent=2))
    return 1 if hard_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
