"""Compute analysis-ready metrics from the unified JP supplemental data.

No absent pair is treated as zero: the official association tables are leading
lists.  Metrics requiring a full 2x2 table are emitted only when every count is
published or uniquely recoverable from the official rounded percentage.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import os
import statistics
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


WORKSPACE = Path(__file__).resolve().parents[1]
JP_ROOT = WORKSPACE / "data_processed" / "jp_unified"
OUT_ROOT = WORKSPACE / "analysis_results" / "jp_supplemental_metrics"

ASSOCIATION_INPUT = JP_ROOT / "entity_association_long.csv.gz"
QUESTIONNAIRE_INPUT = JP_ROOT / "entity_questionnaire_long.csv.gz"


def as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    number = float(value)
    if not number.is_integer():
        return None
    return int(number)


def as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rows(path: Path) -> Iterator[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def atomic_csv(path: Path, fields: list[str], source: Iterable[dict[str, Any]], gzip_output: bool) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = ".tmp.gz" if gzip_output else ".tmp"
    fd, temporary_name = tempfile.mkstemp(prefix=path.stem + ".", suffix=suffix, dir=path.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    count = 0
    try:
        opener = gzip.open if gzip_output else open
        with opener(temporary, "wt", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in source:
                writer.writerow(row)
                count += 1
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return count


def unique_integer_from_rounded_rate(rate: float, denominator: int, half_step: float) -> int | None:
    """Return a count only when the published rounded rate permits one integer."""
    if denominator < 0 or not 0 <= rate <= 1:
        return None
    center = rate * denominator
    radius = half_step * denominator
    lower = max(0, math.ceil(center - radius - 1e-12))
    upper = min(denominator, math.floor(center + radius + 1e-12))
    candidates = [
        value
        for value in range(lower, upper + 1)
        if abs(value / denominator - rate) <= half_step + 1e-12
    ]
    return candidates[0] if len(candidates) == 1 else None


def recover_target_count(row: dict[str, str]) -> tuple[int | None, str]:
    denominator = as_int(row.get("overall_denominator"))
    rate = as_float(row.get("overall_rate"))
    if denominator is None or rate is None:
        return None, "missing_overall_denominator_or_rate"
    if row["source_generation"] == "modern_official":
        candidate = round(rate * denominator)
        if 0 <= candidate <= denominator and abs(candidate / denominator - rate) <= 1e-12:
            return candidate, "exact_modern_official_rate_times_denominator"
        return None, "modern_rate_denominator_not_integer_consistent"
    # Legacy percentages were published to two decimal places on a 0--100
    # scale, hence half a display unit is 0.00005 on the 0--1 scale.
    candidate = unique_integer_from_rounded_rate(rate, denominator, 0.00005)
    if candidate is not None:
        return candidate, "unique_integer_from_legacy_two_decimal_percentage"
    return None, "legacy_rounded_percentage_allows_multiple_or_no_counts"


ASSOCIATION_FIELDS = [
    "round",
    "source_generation",
    "source_category",
    "source_id",
    "source_name",
    "source_rank",
    "target_category",
    "target_name",
    "association_context",
    "publication_scope",
    "complete_pair_matrix",
    "intersection_count",
    "source_count",
    "target_count",
    "universe_count",
    "target_count_basis",
    "metric_status",
    "conditional_rate_official",
    "overall_rate_official",
    "delta_points_official",
    "lift_official_rate_ratio",
    "support_exact",
    "lift_exact_2x2",
    "jaccard_exact",
    "pmi_nats_exact",
    "npmi_exact",
    "phi_exact",
    "odds_ratio_exact",
    "m00_both_selected",
    "m01_source_only",
    "m10_target_only",
    "m11_neither",
    "source_url",
    "source_sha256",
]


def association_metrics() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    exact_round_counts: Counter[int] = Counter()
    invalid_2x2 = 0
    nonfinite_metrics = 0
    for row in rows(ASSOCIATION_INPUT):
        n = as_int(row.get("overall_denominator"))
        a = as_int(row.get("conditional_denominator"))
        ab = as_int(row.get("intersection_count"))
        b, b_basis = recover_target_count(row)
        metric_status = "exact_2x2_available"
        cells: tuple[int, int, int, int] | None = None
        metrics: dict[str, float | None] = {
            "support_exact": None,
            "lift_exact_2x2": None,
            "jaccard_exact": None,
            "pmi_nats_exact": None,
            "npmi_exact": None,
            "phi_exact": None,
            "odds_ratio_exact": None,
        }
        if None in (n, a, b, ab):
            metric_status = "insufficient_exact_counts"
        else:
            assert n is not None and a is not None and b is not None and ab is not None
            m00 = ab
            m01 = a - ab
            m10 = b - ab
            m11 = n - a - b + ab
            if min(m00, m01, m10, m11) < 0:
                metric_status = "invalid_2x2_counts"
                invalid_2x2 += 1
            else:
                cells = (m00, m01, m10, m11)
                support = ab / n if n else None
                lift = ab * n / (a * b) if a and b else None
                union = a + b - ab
                jaccard = ab / union if union else None
                pmi = math.log(lift) if lift is not None and lift > 0 else None
                npmi = (
                    pmi / -math.log(support)
                    if pmi is not None and support is not None and 0 < support < 1
                    else None
                )
                phi_denominator = a * b * (n - a) * (n - b)
                phi = (
                    (ab * n - a * b) / math.sqrt(phi_denominator)
                    if phi_denominator > 0
                    else None
                )
                odds_denominator = m01 * m10
                odds = m00 * m11 / odds_denominator if odds_denominator else None
                metrics.update(
                    support_exact=support,
                    lift_exact_2x2=lift,
                    jaccard_exact=jaccard,
                    pmi_nats_exact=pmi,
                    npmi_exact=npmi,
                    phi_exact=phi,
                    odds_ratio_exact=odds,
                )
                if any(value is not None and not math.isfinite(value) for value in metrics.values()):
                    nonfinite_metrics += 1
                exact_round_counts[int(row["round"])] += 1
        status_counts[metric_status] += 1
        output.append(
            {
                "round": int(row["round"]),
                "source_generation": row["source_generation"],
                "source_category": row["source_category"],
                "source_id": row["source_id"],
                "source_name": row["source_name"],
                "source_rank": row["source_rank"],
                "target_category": row["target_category"],
                "target_name": row["target_name"],
                "association_context": row["association_context"],
                "publication_scope": row["publication_scope"],
                "complete_pair_matrix": row["complete_pair_matrix"],
                "intersection_count": ab,
                "source_count": a,
                "target_count": b,
                "universe_count": n,
                "target_count_basis": b_basis,
                "metric_status": metric_status,
                "conditional_rate_official": as_float(row.get("conditional_rate")),
                "overall_rate_official": as_float(row.get("overall_rate")),
                "delta_points_official": as_float(row.get("delta_points")),
                "lift_official_rate_ratio": as_float(row.get("lift")),
                **metrics,
                "m00_both_selected": cells[0] if cells else None,
                "m01_source_only": cells[1] if cells else None,
                "m10_target_only": cells[2] if cells else None,
                "m11_neither": cells[3] if cells else None,
                "source_url": row["source_url"],
                "source_sha256": row["source_sha256"],
            }
        )
    return output, {
        "input_rows": len(output),
        "metric_status_counts": dict(sorted(status_counts.items())),
        "exact_2x2_by_round": dict(sorted(exact_round_counts.items())),
        "invalid_2x2_rows": invalid_2x2,
        "nonfinite_metric_rows": nonfinite_metrics,
    }


SYMMETRY_FIELDS = [
    "round",
    "left_category",
    "left_name",
    "right_category",
    "right_name",
    "left_to_right_intersection",
    "right_to_left_intersection",
    "intersection_difference",
    "intersection_symmetric",
]


def symmetry_audit(metrics: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    directions: dict[tuple[int, tuple[str, str], tuple[str, str]], list[int]] = defaultdict(list)
    for row in metrics:
        count = row["intersection_count"]
        if count is None:
            continue
        source = (str(row["source_category"]), str(row["source_name"]))
        target = (str(row["target_category"]), str(row["target_name"]))
        directions[(int(row["round"]), source, target)].append(int(count))
    output: list[dict[str, Any]] = []
    seen: set[tuple[int, tuple[str, str], tuple[str, str]]] = set()
    for (round_number, source, target), counts in directions.items():
        if source == target:
            continue
        pair = (round_number, *sorted((source, target)))
        if pair in seen:
            continue
        seen.add(pair)
        reverse = directions.get((round_number, target, source))
        if not reverse or len(counts) != 1 or len(reverse) != 1:
            continue
        difference = counts[0] - reverse[0]
        left, right = sorted((source, target))
        left_to_right = directions[(round_number, left, right)][0]
        right_to_left = directions[(round_number, right, left)][0]
        output.append(
            {
                "round": round_number,
                "left_category": left[0],
                "left_name": left[1],
                "right_category": right[0],
                "right_name": right[1],
                "left_to_right_intersection": left_to_right,
                "right_to_left_intersection": right_to_left,
                "intersection_difference": left_to_right - right_to_left,
                "intersection_symmetric": left_to_right == right_to_left,
            }
        )
    output.sort(key=lambda row: (row["round"], row["left_category"], row["left_name"], row["right_category"], row["right_name"]))
    return output, {
        "bidirectionally_published_unique_pairs": len(output),
        "exact_intersection_matches": sum(bool(row["intersection_symmetric"]) for row in output),
        "intersection_mismatches": sum(not bool(row["intersection_symmetric"]) for row in output),
    }


QUESTION_SUMMARY_FIELDS = [
    "round",
    "source_generation",
    "source_category",
    "question_id",
    "question",
    "row_count",
    "entity_count",
    "option_count",
    "valid_effect_rows",
    "known_conditional_denominator_rows",
    "positive_delta_rows",
    "negative_delta_rows",
    "zero_delta_rows",
    "mean_abs_delta_points",
    "median_abs_delta_points",
    "maximum_abs_delta_points",
    "maximum_effect_source_name",
    "maximum_effect_option",
    "maximum_effect_delta_points",
    "maximum_effect_lift",
]


def questionnaire_summaries() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups: dict[tuple[str, ...], dict[str, Any]] = {}
    total_rows = 0
    for row in rows(QUESTIONNAIRE_INPUT):
        total_rows += 1
        key = (
            row["round"],
            row["source_generation"],
            row["source_category"],
            row["question_id"],
            row["question"],
        )
        group = groups.setdefault(
            key,
            {
                "entities": set(),
                "options": set(),
                "rows": 0,
                "denominators": 0,
                "deltas": [],
                "positive": 0,
                "negative": 0,
                "zero": 0,
                "maximum": None,
            },
        )
        group["rows"] += 1
        group["entities"].add((row["source_id"], row["source_name"]))
        group["options"].add((row["node_path"], row["option"]))
        if as_int(row.get("conditional_denominator")) is not None:
            group["denominators"] += 1
        conditional = as_float(row.get("conditional_rate"))
        overall = as_float(row.get("overall_rate"))
        delta = as_float(row.get("delta_points"))
        lift = as_float(row.get("lift"))
        if conditional is None or overall is None or delta is None:
            continue
        group["deltas"].append(delta)
        if delta > 0:
            group["positive"] += 1
        elif delta < 0:
            group["negative"] += 1
        else:
            group["zero"] += 1
        current = group["maximum"]
        if current is None or abs(delta) > abs(current["delta"]):
            group["maximum"] = {
                "source_name": row["source_name"],
                "option": row["option"],
                "delta": delta,
                "lift": lift,
            }
    output: list[dict[str, Any]] = []
    for key, group in groups.items():
        deltas = group["deltas"]
        maximum = group["maximum"] or {}
        output.append(
            {
                "round": int(key[0]),
                "source_generation": key[1],
                "source_category": key[2],
                "question_id": key[3],
                "question": key[4],
                "row_count": group["rows"],
                "entity_count": len(group["entities"]),
                "option_count": len(group["options"]),
                "valid_effect_rows": len(deltas),
                "known_conditional_denominator_rows": group["denominators"],
                "positive_delta_rows": group["positive"],
                "negative_delta_rows": group["negative"],
                "zero_delta_rows": group["zero"],
                "mean_abs_delta_points": statistics.fmean(abs(value) for value in deltas) if deltas else None,
                "median_abs_delta_points": statistics.median(abs(value) for value in deltas) if deltas else None,
                "maximum_abs_delta_points": abs(maximum["delta"]) if maximum else None,
                "maximum_effect_source_name": maximum.get("source_name"),
                "maximum_effect_option": maximum.get("option"),
                "maximum_effect_delta_points": maximum.get("delta"),
                "maximum_effect_lift": maximum.get("lift"),
            }
        )
    output.sort(key=lambda row: (row["round"], row["source_generation"], row["source_category"], row["question_id"]))
    return output, {
        "input_rows": total_rows,
        "summary_groups": len(output),
        "valid_effect_rows": sum(row["valid_effect_rows"] for row in output),
    }


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    metrics, association_report = association_metrics()
    symmetry, symmetry_report = symmetry_audit(metrics)
    questionnaire, questionnaire_report = questionnaire_summaries()

    association_path = OUT_ROOT / "association_metrics.csv.gz"
    symmetry_path = OUT_ROOT / "association_symmetry_audit.csv"
    questionnaire_path = OUT_ROOT / "questionnaire_effect_summary.csv"
    output_counts = {
        association_path.name: atomic_csv(association_path, ASSOCIATION_FIELDS, metrics, True),
        symmetry_path.name: atomic_csv(symmetry_path, SYMMETRY_FIELDS, symmetry, False),
        questionnaire_path.name: atomic_csv(questionnaire_path, QUESTION_SUMMARY_FIELDS, questionnaire, False),
    }
    validations = {
        "association_row_conservation": output_counts[association_path.name] == association_report["input_rows"],
        "questionnaire_row_conservation": questionnaire_report["input_rows"] == 313624,
        "no_invalid_2x2_rows_emitted_as_exact": association_report["invalid_2x2_rows"] == 0,
        "no_nonfinite_metrics": association_report["nonfinite_metric_rows"] == 0,
        "all_jaccard_within_zero_one": all(
            row["jaccard_exact"] is None or 0 <= row["jaccard_exact"] <= 1 for row in metrics
        ),
        "all_phi_within_minus_one_one": all(
            row["phi_exact"] is None or -1 - 1e-12 <= row["phi_exact"] <= 1 + 1e-12 for row in metrics
        ),
        "all_npmi_within_minus_one_one": all(
            row["npmi_exact"] is None or -1 - 1e-12 <= row["npmi_exact"] <= 1 + 1e-12 for row in metrics
        ),
        "official_scope_preserved_as_incomplete_lists": all(
            row["publication_scope"] == "official_published_leading_list"
            and str(row["complete_pair_matrix"]).casefold() == "false"
            for row in metrics
        ),
    }
    if not all(validations.values()):
        raise AssertionError(json.dumps(validations, ensure_ascii=False))

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "scope": "Japanese official supplemental entity data, rounds 11-21",
        "policy": {
            "missing_pairs": "never treated as zero because official association tables are leading lists",
            "rounded_legacy_percentages": "2x2 metrics computed only when a unique integer target count is consistent with the published rounded percentage",
            "manual_or_estimated_numbers": 0,
            "pmi_log_base": "natural logarithm",
        },
        "association": association_report,
        "symmetry": symmetry_report,
        "questionnaire": questionnaire_report,
        "output_counts": output_counts,
        "validations": validations,
        "inputs": [
            {
                "path": path.relative_to(WORKSPACE).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in (ASSOCIATION_INPUT, QUESTIONNAIRE_INPUT)
        ],
        "outputs": [
            {
                "path": path.relative_to(WORKSPACE).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "rows": output_counts[path.name],
            }
            for path in (association_path, symmetry_path, questionnaire_path)
        ],
    }
    (OUT_ROOT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT_ROOT / "README.md").write_text(
        "\n".join(
            [
                "# 日文实体附加数据数值分析",
                "",
                f"- 关联前列输入/输出：{association_report['input_rows']:,}行；可唯一恢复完整四格并计算Jaccard、PMI/NPMI、φ和odds ratio：{association_report['metric_status_counts'].get('exact_2x2_available', 0):,}行。",
                f"- 双向均被官网发布的唯一实体对：{symmetry_report['bidirectionally_published_unique_pairs']:,}；交集数完全一致：{symmetry_report['exact_intersection_matches']:,}；不一致：{symmetry_report['intersection_mismatches']:,}。",
                f"- 实体アンケート输入：{questionnaire_report['input_rows']:,}行；逐届/类别/题目汇总：{questionnaire_report['summary_groups']:,}组。",
                "- 官网未发布的关联对从不补零；不能唯一恢复整数四格的行只保留官方rate/lift，不输出伪精确Jaccard或NPMI。",
                "- 所有结果均由本地脚本计算，公式与强校验见 `report.json`。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps({"association": association_report, "symmetry": symmetry_report, "questionnaire": questionnaire_report, "validations": validations}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
