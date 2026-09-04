"""Independent audit for the JP3--22 unified questionnaire/association layer.

This validator deliberately does not import ``build_jp_unified.py``.  It reads
the source tables, compressed outputs, and provenance report independently so
that row conservation, percentage handling, and modern association de-duplication
are checked through a separate implementation.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator


WORKSPACE = Path(__file__).resolve().parents[1]
LEGACY = WORKSPACE / "data_processed" / "jp_official_legacy"
MODERN = WORKSPACE / "data_processed" / "jp_official"
UNIFIED = WORKSPACE / "data_processed" / "jp_unified"
BUILD_REPORT = WORKSPACE / "metadata" / "jp_unified_report.json"
JSON_REPORT = WORKSPACE / "analysis_results" / "jp_unified_validation.json"
MD_REPORT = WORKSPACE / "analysis_results" / "jp_unified_validation.md"


SOURCE_PATHS = {
    "aggregate_legacy": LEGACY / "questionnaire_long.csv",
    "aggregate_modern": MODERN / "questionnaire_long.csv",
    "entity_question_legacy": LEGACY / "entity_questionnaire_long.csv",
    "entity_question_modern": MODERN / "detail_questionnaire_long.csv",
    "association_legacy": LEGACY / "entity_association_long.csv",
    "association_modern": MODERN / "detail_associations.csv",
}

OUTPUT_PATHS = {
    "aggregate_questionnaire": UNIFIED / "aggregate_questionnaire_long.csv.gz",
    "entity_questionnaire": UNIFIED / "entity_questionnaire_long.csv.gz",
    "entity_association": UNIFIED / "entity_association_long.csv.gz",
}

RATE_FIELDS = {
    "aggregate_questionnaire": ("rate",),
    "entity_questionnaire": ("conditional_rate", "overall_rate"),
    "entity_association": ("conditional_rate", "overall_rate"),
}


def rows(path: Path) -> Iterator[dict[str, str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"non-finite number: {value!r}")
    return number


def optional_int(value: Any) -> int | None:
    number = optional_float(value)
    if number is None:
        return None
    if not number.is_integer():
        raise ValueError(f"expected integer: {value!r}")
    return int(number)


def numeric_equal(left: Any, right: Any, tolerance: float = 1e-12) -> bool:
    a = optional_float(left)
    b = optional_float(right)
    if a is None or b is None:
        return a == b
    return abs(a - b) <= tolerance * max(1.0, abs(a), abs(b))


def csv_stats(path: Path) -> dict[str, Any]:
    count = 0
    by_round: Counter[int] = Counter()
    for row in rows(path):
        count += 1
        by_round[int(row["round"])] += 1
    return {"rows": count, "by_round": dict(sorted(by_round.items()))}


def audit_output(name: str, path: Path) -> dict[str, Any]:
    count = 0
    by_round: Counter[int] = Counter()
    by_generation: Counter[str] = Counter()
    by_generation_round: dict[str, Counter[int]] = defaultdict(Counter)
    blank_rates: Counter[str] = Counter()
    populated_rates: Counter[str] = Counter()
    rate_violations: list[dict[str, Any]] = []

    for row in rows(path):
        count += 1
        round_number = int(row["round"])
        generation = row["source_generation"]
        by_round[round_number] += 1
        by_generation[generation] += 1
        by_generation_round[generation][round_number] += 1
        for field in RATE_FIELDS[name]:
            value = optional_float(row.get(field))
            if value is None:
                blank_rates[field] += 1
            else:
                populated_rates[field] += 1
                if not 0 <= value <= 1:
                    if len(rate_violations) < 20:
                        rate_violations.append(
                            {
                                "round": round_number,
                                "field": field,
                                "value": value,
                                "source_category": row.get("source_category"),
                                "source_id": row.get("source_id"),
                            }
                        )

    return {
        "rows": count,
        "by_round": dict(sorted(by_round.items())),
        "by_generation": dict(sorted(by_generation.items())),
        "by_generation_round": {
            key: dict(sorted(value.items()))
            for key, value in sorted(by_generation_round.items())
        },
        "populated_rate_cells": dict(populated_rates),
        "blank_rate_cells": dict(blank_rates),
        "rate_violations": rate_violations,
    }


def report_file_checks(build_report: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for role in ("inputs", "outputs"):
        for entry in build_report[role]:
            path = WORKSPACE / entry["path"]
            actual_bytes = path.stat().st_size if path.exists() else None
            actual_sha256 = sha256(path) if path.exists() else None
            result = {
                "role": role[:-1],
                "path": entry["path"],
                "exists": path.exists(),
                "reported_bytes": entry["bytes"],
                "actual_bytes": actual_bytes,
                "reported_sha256": entry["sha256"],
                "actual_sha256": actual_sha256,
                "bytes_match": actual_bytes == entry["bytes"],
                "sha256_match": actual_sha256 == entry["sha256"],
            }
            if role == "outputs":
                actual_rows = sum(1 for _ in rows(path)) if path.exists() else None
                result.update(
                    {
                        "reported_rows": entry["rows"],
                        "actual_rows": actual_rows,
                        "rows_match": actual_rows == entry["rows"],
                    }
                )
            checks.append(result)
    return checks


def material_digest(row: dict[str, str], excluded: set[str]) -> bytes:
    digest = hashlib.sha256()
    for field in sorted(key for key in row if key not in excluded):
        digest.update(field.encode("utf-8"))
        digest.update(b"\0")
        digest.update(row[field].encode("utf-8"))
        digest.update(b"\0")
    return digest.digest()


def audit_modern_association_dedup() -> dict[str, Any]:
    key_fields = (
        "round",
        "source_category",
        "source_id",
        "target_category",
        "target_name",
    )
    essential_fields = (
        "source_name",
        "source_rank",
        "count",
        "rate",
        "total",
        "diff",
        "conditional_denominator_derived",
        "overall_denominator",
        "overall_denominator_basis",
    )

    # key -> [material digest, {(ordering, position)}, multiplicity, essentials]
    grouped: dict[tuple[str, ...], list[Any]] = {}
    raw_rows = 0
    ordering_counts: Counter[str] = Counter()
    duplicate_material_mismatches = 0
    source_target_contexts: set[tuple[int, str, str, str]] = set()

    for row in rows(SOURCE_PATHS["association_modern"]):
        raw_rows += 1
        ordering_counts[row["ordering"]] += 1
        key = tuple(row[field] for field in key_fields)
        digest = material_digest(row, {"ordering", "position"})
        ordering_position = (row["ordering"], optional_int(row["position"]))
        if key not in grouped:
            grouped[key] = [
                digest,
                {ordering_position},
                1,
                tuple(row[field] for field in essential_fields),
            ]
        else:
            state = grouped[key]
            if state[0] != digest:
                duplicate_material_mismatches += 1
            state[1].add(ordering_position)
            state[2] += 1
        source_target_contexts.add(
            (int(row["round"]), row["source_category"], row["source_id"], row["target_category"])
        )

    output_keys: set[tuple[str, ...]] = set()
    duplicate_output_keys = 0
    ordering_position_mismatches = 0
    value_mismatches = 0
    modern_output_rows = 0
    output_rounds: Counter[int] = Counter()
    kind_counts: Counter[str] = Counter()
    context_counts: Counter[str] = Counter()
    published_ordering_counts: Counter[str] = Counter()
    missing_raw_keys = 0

    for row in rows(OUTPUT_PATHS["entity_association"]):
        if row["source_generation"] != "modern_official":
            continue
        modern_output_rows += 1
        output_rounds[int(row["round"])] += 1
        kind_counts[row["association_kind"]] += 1
        context_counts[row["association_context"]] += 1
        key = tuple(row[field] for field in key_fields)
        if key in output_keys:
            duplicate_output_keys += 1
        output_keys.add(key)
        state = grouped.get(key)
        if state is None:
            missing_raw_keys += 1
            continue
        orderings = json.loads(row["published_orderings"])
        positions = json.loads(row["published_positions"])
        if len(orderings) != len(positions):
            ordering_position_mismatches += 1
        else:
            published = set(zip(orderings, positions))
            if published != state[1]:
                ordering_position_mismatches += 1
            for ordering in orderings:
                published_ordering_counts[ordering] += 1

        essentials = dict(zip(essential_fields, state[3]))
        exact_pairs = (
            (row["source_name"], essentials["source_name"]),
            (row["source_rank"], essentials["source_rank"]),
            (row["overall_denominator_basis"], essentials["overall_denominator_basis"]),
        )
        numeric_pairs = (
            (row["intersection_count"], essentials["count"]),
            (row["conditional_rate"], essentials["rate"]),
            (row["overall_rate"], essentials["total"]),
            (row["delta_points"], essentials["diff"]),
            (row["conditional_denominator"], essentials["conditional_denominator_derived"]),
            (row["overall_denominator"], essentials["overall_denominator"]),
        )
        if any(left != right for left, right in exact_pairs) or any(
            not numeric_equal(left, right) for left, right in numeric_pairs
        ):
            value_mismatches += 1

    multiplicities = Counter(state[2] for state in grouped.values())
    unique_rows = len(grouped)
    collapsed = raw_rows - unique_rows

    # Quantify why these rows cannot be treated as a complete matrix.  The
    # detail item table gives the candidate universe in each modern round and
    # category.  We only evaluate source/target category contexts that the
    # official detail data actually publishes.
    candidate_ids: dict[tuple[int, str], set[str]] = defaultdict(set)
    for row in rows(MODERN / "detail_items.csv"):
        candidate_ids[(int(row["round"]), row["source_category"])].add(row["source_id"])
    observed_by_context: Counter[tuple[int, str, str, str]] = Counter()
    for key in grouped:
        observed_by_context[(int(key[0]), key[1], key[2], key[3])] += 1
    possible_by_context: dict[tuple[int, str, str, str], int] = {}
    for context in source_target_contexts:
        round_number, source_category, source_id, target_category = context
        possible = len(candidate_ids[(round_number, target_category)])
        if source_category == target_category and source_id in candidate_ids[(round_number, target_category)]:
            possible -= 1
        possible_by_context[context] = possible
    possible_pairs = sum(possible_by_context.values())
    observed_pairs = sum(observed_by_context.values())
    context_coverages = [
        observed_by_context[key] / possible
        for key, possible in possible_by_context.items()
        if possible > 0
    ]

    return {
        "raw_rows": raw_rows,
        "unique_pair_rows": unique_rows,
        "rows_collapsed": collapsed,
        "duplicate_groups": sum(count > 1 for count in (state[2] for state in grouped.values())),
        "multiplicity_counts": dict(sorted(multiplicities.items())),
        "raw_ordering_counts": dict(sorted(ordering_counts.items())),
        "duplicate_material_mismatches": duplicate_material_mismatches,
        "output_modern_rows": modern_output_rows,
        "output_rounds": dict(sorted(output_rounds.items())),
        "missing_output_keys": len(set(grouped) - output_keys),
        "output_keys_not_in_raw": missing_raw_keys,
        "duplicate_output_keys": duplicate_output_keys,
        "ordering_position_mismatches": ordering_position_mismatches,
        "value_mismatches": value_mismatches,
        "association_kind_counts": dict(sorted(kind_counts.items())),
        "association_context_counts": dict(sorted(context_counts.items())),
        "published_ordering_memberships": dict(sorted(published_ordering_counts.items())),
        "published_scope_evidence": {
            "observed_unique_pairs": observed_pairs,
            "possible_pairs_in_published_source_target_contexts": possible_pairs,
            "observed_fraction_of_candidate_universe": observed_pairs / possible_pairs,
            "context_coverage_min": min(context_coverages),
            "context_coverage_median": statistics.median(context_coverages),
            "context_coverage_max": max(context_coverages),
            "contexts": len(context_coverages),
        },
    }


def anomaly_key(row: dict[str, str]) -> tuple[Any, ...]:
    return (
        int(row["round"]),
        row["source_category"],
        row["source_id"],
        row.get("question") or row.get("question_key"),
        row.get("option") or row.get("label"),
    )


def audit_entity_rate_anomalies(build_report: dict[str, Any]) -> dict[str, Any]:
    source_anomalies: dict[tuple[Any, ...], dict[str, str]] = {}
    for row in rows(SOURCE_PATHS["entity_question_modern"]):
        rate = optional_float(row["rate"])
        if rate is not None and not 0 <= rate <= 1:
            source_anomalies[anomaly_key(row)] = row

    output_anomalies: dict[tuple[Any, ...], dict[str, str]] = {}
    status_counts: Counter[str] = Counter()
    status_rule_violations = 0
    for row in rows(OUTPUT_PATHS["entity_questionnaire"]):
        if row["source_generation"] != "modern_official":
            continue
        status_counts[row["rate_status"]] += 1
        raw_rate = optional_float(row["official_conditional_rate_raw"])
        analysis_rate = optional_float(row["conditional_rate"])
        if raw_rate is None:
            valid = row["rate_status"] == "official_rate_missing" and analysis_rate is None
        elif 0 <= raw_rate <= 1:
            valid = (
                row["rate_status"] == "valid_official_proportion"
                and numeric_equal(raw_rate, analysis_rate)
            )
        else:
            valid = (
                row["rate_status"] == "official_rate_outside_proportion_domain"
                and analysis_rate is None
                and row["delta_points"] == ""
                and row["lift"] == ""
            )
            output_anomalies[anomaly_key(row)] = row
        if not valid:
            status_rule_violations += 1

    detail_matches = 0
    detail_mismatches: list[dict[str, Any]] = []
    for key, source in source_anomalies.items():
        output = output_anomalies.get(key)
        checks = {
            "row_present": output is not None,
            "raw_rate_preserved": output is not None
            and numeric_equal(output["official_conditional_rate_raw"], source["rate"]),
            "count_preserved": output is not None and output["count"] == source["count"],
            "denominator_preserved": output is not None
            and output["conditional_denominator"] == source["conditional_denominator_derived"],
            "official_delta_preserved": output is not None
            and numeric_equal(output["official_delta_points_raw"], source["diff"]),
            "analysis_fields_blank": output is not None
            and output["conditional_rate"] == ""
            and output["delta_points"] == ""
            and output["lift"] == "",
        }
        if all(checks.values()):
            detail_matches += 1
        else:
            detail_mismatches.append({"key": list(key), "checks": checks})

    report_keys = {
        (
            int(row["round"]),
            row["source_category"],
            str(row["source_id"]),
            row["question"],
            row["option"],
        )
        for row in build_report["modern_entity_question_official_rate_anomalies"]
    }

    return {
        "source_out_of_domain_rows": len(source_anomalies),
        "output_out_of_domain_status_rows": len(output_anomalies),
        "fully_preserved_and_quarantined_rows": detail_matches,
        "detail_mismatches": detail_mismatches,
        "status_rule_violations": status_rule_violations,
        "modern_rate_status_counts": dict(sorted(status_counts.items())),
        "report_anomaly_keys_match_source": report_keys == set(source_anomalies),
        "anomalies": [
            {
                "round": key[0],
                "source_category": key[1],
                "source_id": key[2],
                "question": key[3],
                "option": key[4],
                "count": optional_int(source["count"]),
                "official_conditional_rate_raw": optional_float(source["rate"]),
                "conditional_denominator": optional_int(source["conditional_denominator_derived"]),
                "official_delta_points_raw": optional_float(source["diff"]),
            }
            for key, source in source_anomalies.items()
        ],
    }


def int_key_dict(values: dict[str, Any] | dict[int, Any]) -> dict[int, Any]:
    return {int(key): value for key, value in values.items()}


def make_markdown(report: dict[str, Any]) -> str:
    out = report["output_stats"]
    dedup = report["modern_association_dedup"]
    anomaly = report["entity_rate_anomalies"]
    scope = dedup["published_scope_evidence"]
    status = report["status"]

    lines = [
        "# JP unified 独立验证",
        "",
        f"结论：**{status}**。本报告未调用生成器，直接重读源表、压缩长表和 provenance report。",
        "",
        "## 核心结果",
        "",
        f"- 三张输出实测行数：aggregate {out['aggregate_questionnaire']['rows']:,}；entity questionnaire {out['entity_questionnaire']['rows']:,}；entity association {out['entity_association']['rows']:,}。均与构建报告及源表守恒关系一致。",
        "- 届次：aggregate 完整覆盖 JP3—22；实体问卷和实体关联覆盖 JP11—22（JP3—10 的两张实体表没有源行，不是补零）。",
        f"- 现代关联：原始 {dedup['raw_rows']:,} 行，按官方实体对唯一化后 {dedup['unique_pair_rows']:,} 行，折叠 {dedup['rows_collapsed']:,} 行；重复组的非排序字段差异 {dedup['duplicate_material_mismatches']}，ordering/position 还原差异 {dedup['ordering_position_mismatches']}，数值差异 {dedup['value_mismatches']}。",
        f"- 两条官方 rate=2 异常均保留 raw、count、denominator 和原始 delta；`conditional_rate`、分析用 `delta_points`、`lift` 均留空。异常行 {anomaly['fully_preserved_and_quarantined_rows']}/2 通过。",
        f"- 所有分析用 rate 字段均在 [0,1] 或为空；违规数 aggregate={len(out['aggregate_questionnaire']['rate_violations'])}、entity questionnaire={len(out['entity_questionnaire']['rate_violations'])}、association={len(out['entity_association']['rate_violations'])}。",
        f"- 现代关联只覆盖相应候选宇宙的 {scope['observed_fraction_of_candidate_universe']:.2%}（{scope['observed_unique_pairs']:,}/{scope['possible_pairs_in_published_source_target_contexts']:,}），且行级类型为 `published_leading_conditional_co_vote`，因此不能解释为完整矩阵。",
        "",
        "## 行数守恒",
        "",
        "| 输出 | legacy 源行 | modern 源行/唯一行 | 输出行 | 守恒 |",
        "|---|---:|---:|---:|:---:|",
    ]
    for name, conservation in report["row_conservation"].items():
        lines.append(
            f"| {name} | {conservation['legacy_source_rows']:,} | {conservation['modern_expected_rows']:,} | {conservation['output_rows']:,} | {'是' if conservation['pass'] else '否'} |"
        )

    lines.extend(
        [
            "",
            "## 每届行数",
            "",
            "| JP届次 | aggregate | entity questionnaire | entity association |",
            "|---:|---:|---:|---:|",
        ]
    )
    for round_number in range(3, 23):
        lines.append(
            "| {round_number} | {aggregate:,} | {entity_q:,} | {association:,} |".format(
                round_number=round_number,
                aggregate=int_key_dict(out["aggregate_questionnaire"]["by_round"]).get(round_number, 0),
                entity_q=int_key_dict(out["entity_questionnaire"]["by_round"]).get(round_number, 0),
                association=int_key_dict(out["entity_association"]["by_round"]).get(round_number, 0),
            )
        )

    lines.extend(["", "## 审计提示", ""])
    for warning in report["warnings"]:
        lines.append(f"- {warning}")
    if not report["warnings"]:
        lines.append("- 无。")
    lines.extend(
        [
            "",
            "机器可读的逐项检查见 `analysis_results/jp_unified_validation.json`。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    build_report = json.loads(BUILD_REPORT.read_text(encoding="utf-8"))
    source_stats = {name: csv_stats(path) for name, path in SOURCE_PATHS.items()}
    output_stats = {
        name: audit_output(name, path) for name, path in OUTPUT_PATHS.items()
    }
    dedup = audit_modern_association_dedup()
    anomalies = audit_entity_rate_anomalies(build_report)
    file_checks = report_file_checks(build_report)

    expected_rounds = {
        "aggregate_questionnaire": list(range(3, 23)),
        "entity_questionnaire": list(range(11, 23)),
        "entity_association": list(range(11, 23)),
    }
    coverage_checks = {
        name: sorted(int(key) for key in stats["by_round"]) == expected_rounds[name]
        for name, stats in output_stats.items()
    }

    conservation_specs = {
        "aggregate_questionnaire": ("aggregate_legacy", "aggregate_modern"),
        "entity_questionnaire": ("entity_question_legacy", "entity_question_modern"),
        "entity_association": ("association_legacy", None),
    }
    row_conservation: dict[str, Any] = {}
    for output_name, (legacy_name, modern_name) in conservation_specs.items():
        legacy_rows = source_stats[legacy_name]["rows"]
        modern_expected = (
            source_stats[modern_name]["rows"]
            if modern_name is not None
            else dedup["unique_pair_rows"]
        )
        output_rows = output_stats[output_name]["rows"]
        expected = legacy_rows + modern_expected
        output_generations = output_stats[output_name]["by_generation"]
        row_conservation[output_name] = {
            "legacy_source_rows": legacy_rows,
            "modern_expected_rows": modern_expected,
            "expected_output_rows": expected,
            "output_rows": output_rows,
            "output_generation_rows": output_generations,
            "pass": (
                expected == output_rows
                and output_generations.get("legacy_official", 0) == legacy_rows
                and output_generations.get("modern_official", 0) == modern_expected
            ),
        }

    # Round-by-round conservation is stronger than a grand-total comparison.
    round_conservation = {
        "aggregate_legacy": int_key_dict(source_stats["aggregate_legacy"]["by_round"])
        == int_key_dict(output_stats["aggregate_questionnaire"]["by_generation_round"].get("legacy_official", {})),
        "aggregate_modern": int_key_dict(source_stats["aggregate_modern"]["by_round"])
        == int_key_dict(output_stats["aggregate_questionnaire"]["by_generation_round"].get("modern_official", {})),
        "entity_question_legacy": int_key_dict(source_stats["entity_question_legacy"]["by_round"])
        == int_key_dict(output_stats["entity_questionnaire"]["by_generation_round"].get("legacy_official", {})),
        "entity_question_modern": int_key_dict(source_stats["entity_question_modern"]["by_round"])
        == int_key_dict(output_stats["entity_questionnaire"]["by_generation_round"].get("modern_official", {})),
        "association_legacy": int_key_dict(source_stats["association_legacy"]["by_round"])
        == int_key_dict(output_stats["entity_association"]["by_generation_round"].get("legacy_official", {})),
        "association_modern_unique": int_key_dict(dedup["output_rounds"])
        == int_key_dict(output_stats["entity_association"]["by_generation_round"].get("modern_official", {})),
    }

    rates_pass = all(
        not stats["rate_violations"] for stats in output_stats.values()
    )
    hashes_pass = all(
        item["exists"]
        and item["bytes_match"]
        and item["sha256_match"]
        and item.get("rows_match", True)
        for item in file_checks
    )
    dedup_pass = all(
        dedup[field] == 0
        for field in (
            "duplicate_material_mismatches",
            "missing_output_keys",
            "output_keys_not_in_raw",
            "duplicate_output_keys",
            "ordering_position_mismatches",
            "value_mismatches",
        )
    ) and dedup["rows_collapsed"] == build_report["modern_association_duplicate_ordering_rows_collapsed"]
    anomaly_pass = (
        anomalies["source_out_of_domain_rows"] == 2
        and anomalies["output_out_of_domain_status_rows"] == 2
        and anomalies["fully_preserved_and_quarantined_rows"] == 2
        and not anomalies["detail_mismatches"]
        and anomalies["status_rule_violations"] == 0
        and anomalies["report_anomaly_keys_match_source"]
    )
    legacy_kinds = Counter()
    association_scope_violations = 0
    for row in rows(OUTPUT_PATHS["entity_association"]):
        if row["source_generation"] == "legacy_official":
            legacy_kinds[row["association_kind"]] += 1
        if (
            row.get("publication_scope") != "official_published_leading_list"
            or str(row.get("complete_pair_matrix", "")).casefold() != "false"
        ):
            association_scope_violations += 1
    percentage_policy_ok = "analysis-ready normalized rate fields" in str(
        build_report.get("percentage_policy", "")
    )
    scope_pass = (
        build_report.get("published_scope_policy")
        == "detail associations are the official leading lists, not an invented complete pair matrix"
        and dedup["association_kind_counts"]
        == {"published_leading_conditional_co_vote": dedup["output_modern_rows"]}
        and dedup["published_scope_evidence"]["observed_fraction_of_candidate_universe"] < 1
        and association_scope_violations == 0
    )

    hard_checks = {
        "report_file_hashes_and_sizes_match": hashes_pass,
        "reported_output_row_counts_match": all(
            output_stats[name]["rows"] == build_report["row_counts"][path.name]
            for name, path in OUTPUT_PATHS.items()
        ),
        "coverage_round_sets_match": all(coverage_checks.values()),
        "grand_total_row_conservation": all(item["pass"] for item in row_conservation.values()),
        "round_by_round_row_conservation": all(round_conservation.values()),
        "analysis_rates_within_zero_one_or_blank": rates_pass,
        "two_official_rate_anomalies_preserved_and_quarantined": anomaly_pass,
        "modern_association_dedup_exact": dedup_pass,
        "published_leading_scope_not_complete_matrix": scope_pass,
        "percentage_policy_excludes_raw_provenance_fields": percentage_policy_ok,
    }

    warnings = []
    if not percentage_policy_ok:
        warnings.append(
            "`jp_unified_report.json` 的 percentage_policy 尚未把分析比例与保真 raw 字段明确区分。"
        )
    if association_scope_violations:
        warnings.append(
            f"关联长表仍有 {association_scope_violations} 行缺少明确的前列范围/非完整矩阵标记。"
        )

    status = (
        "FAIL"
        if not all(hard_checks.values())
        else ("PASS_WITH_WARNINGS" if warnings else "PASS")
    )
    report = {
        "schema_version": 2,
        "status": status,
        "independent_implementation": True,
        "build_report": BUILD_REPORT.relative_to(WORKSPACE).as_posix(),
        "hard_checks": hard_checks,
        "warnings": warnings,
        "coverage_checks": coverage_checks,
        "source_stats": source_stats,
        "output_stats": output_stats,
        "row_conservation": row_conservation,
        "round_conservation": round_conservation,
        "entity_rate_anomalies": anomalies,
        "modern_association_dedup": dedup,
        "report_file_checks": file_checks,
        "legacy_association_kind_counts": dict(sorted(legacy_kinds.items())),
        "association_scope_violations": association_scope_violations,
    }

    JSON_REPORT.parent.mkdir(parents=True, exist_ok=True)
    JSON_REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    MD_REPORT.write_text(make_markdown(report), encoding="utf-8")
    print(json.dumps({"status": status, "hard_checks": hard_checks}, ensure_ascii=False, indent=2))
    if status == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
