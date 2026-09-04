"""Build one analysis-ready JP3--22 layer from legacy and modern official data.

The two official result generations use different column names and percentage
scales.  This script harmonizes them without translating or merging entities,
and preserves every published denominator/provenance distinction.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import os
import tempfile
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping


WORKSPACE = Path(__file__).resolve().parents[1]
LEGACY_ROOT = WORKSPACE / "data_processed" / "jp_official_legacy"
MODERN_ROOT = WORKSPACE / "data_processed" / "jp_official"
MANIFEST_PATH = WORKSPACE / "metadata" / "jp_official_download_manifest.json"
OUTPUT_ROOT = WORKSPACE / "data_processed" / "jp_unified"
REPORT_PATH = WORKSPACE / "metadata" / "jp_unified_report.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    number = float(value)
    if not number.is_integer():
        raise ValueError(f"expected integer, got {value!r}")
    return int(number)


def as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"non-finite number: {value!r}")
    return number


def divide(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def load_rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


@contextmanager
def atomic_gzip_csv(path: Path, fields: list[str]) -> Iterator[csv.DictWriter]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=path.stem + ".", suffix=".tmp.gz", dir=path.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with gzip.open(temporary, "wt", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            yield writer
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_gzip_csv(path: Path, fields: list[str], rows: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    with atomic_gzip_csv(path, fields) as writer:
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def manifest_maps() -> tuple[dict[tuple[int, str], dict[str, Any]], dict[tuple[int, str, str], dict[str, Any]]]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    aggregates: dict[tuple[int, str], dict[str, Any]] = {}
    details: dict[tuple[int, str, str], dict[str, Any]] = {}
    for record in manifest.get("records", []):
        round_number = int(record["round"])
        if record["kind"] == "aggregate":
            aggregates[(round_number, str(record["category"]))] = record
        elif record["kind"] == "detail":
            details[
                (round_number, str(record["category"]), str(record["id"]))
            ] = record
    return aggregates, details


def source_rank_map() -> dict[tuple[int, str, str], int]:
    result: dict[tuple[int, str, str], int] = {}
    for row in load_rows(LEGACY_ROOT / "source_entity_metrics.csv"):
        rank = as_int(row.get("rank"))
        if rank is not None:
            result[(int(row["round"]), row["category"], row["entity_name"])] = rank
    return result


AGGREGATE_FIELDS = [
    "region",
    "round",
    "source_generation",
    "scope",
    "question_id",
    "question",
    "node_path",
    "item",
    "option",
    "count",
    "rate",
    "denominator",
    "denominator_basis",
    "count_unit",
    "source_url",
    "source_file",
    "source_sha256",
    "source_table_index",
    "source_row_index",
]

ENTITY_QUESTION_FIELDS = [
    "region",
    "round",
    "source_generation",
    "source_category",
    "source_id",
    "source_name",
    "source_rank",
    "question_id",
    "question",
    "node_path",
    "option",
    "count",
    "conditional_rate",
    "official_conditional_rate_raw",
    "rate_status",
    "conditional_denominator",
    "conditional_denominator_basis",
    "overall_rate",
    "overall_denominator",
    "overall_denominator_basis",
    "delta_points",
    "official_delta_points_raw",
    "lift",
    "source_url",
    "source_file",
    "source_sha256",
    "source_table_index",
    "source_row_index",
]

ASSOCIATION_FIELDS = [
    "region",
    "round",
    "source_generation",
    "source_category",
    "source_id",
    "source_name",
    "source_rank",
    "target_category",
    "target_name",
    "association_context",
    "association_kind",
    "publication_scope",
    "complete_pair_matrix",
    "published_orderings",
    "published_positions",
    "intersection_count",
    "conditional_rate",
    "conditional_denominator",
    "conditional_denominator_basis",
    "overall_rate",
    "overall_denominator",
    "overall_denominator_basis",
    "delta_points",
    "lift",
    "source_url",
    "source_file",
    "source_sha256",
]


def legacy_aggregate_rows() -> Iterator[dict[str, Any]]:
    for row in load_rows(LEGACY_ROOT / "questionnaire_long.csv"):
        rate = as_float(row.get("percentage"))
        yield {
            "region": "jp",
            "round": int(row["round"]),
            "source_generation": "legacy_official",
            "scope": row.get("scope"),
            "question_id": row.get("question_id"),
            "question": row.get("question"),
            "node_path": row.get("question_path_json"),
            "item": row.get("item"),
            "option": row.get("option"),
            "count": as_int(row.get("count")),
            "rate": rate / 100 if rate is not None else None,
            "denominator": as_int(row.get("denominator")),
            "denominator_basis": row.get("denominator_basis"),
            "count_unit": row.get("count_unit"),
            "source_url": row.get("source_url"),
            "source_file": row.get("source_file"),
            "source_sha256": row.get("source_sha256"),
            "source_table_index": row.get("source_table_index"),
            "source_row_index": row.get("source_row_index"),
        }


def modern_aggregate_rows(aggregate_sources: Mapping[tuple[int, str], Mapping[str, Any]]) -> Iterator[dict[str, Any]]:
    rows = list(load_rows(MODERN_ROOT / "questionnaire_long.csv"))
    denominator_sets: dict[tuple[int, str], set[int]] = defaultdict(set)
    for row in rows:
        denominator = as_int(row.get("conditional_denominator_derived"))
        if denominator is not None:
            denominator_sets[(int(row["round"]), row["question_key"])].add(denominator)
    for row in rows:
        round_number = int(row["round"])
        question_key = row["question_key"]
        denominator = as_int(row.get("conditional_denominator_derived"))
        candidates = denominator_sets[(round_number, question_key)]
        if denominator is None and len(candidates) == 1:
            denominator = next(iter(candidates))
            denominator_basis = "filled_from_unique_same_round_question_denominator"
        elif denominator is not None:
            denominator_basis = "derived_from_official_count_and_rate"
        else:
            denominator_basis = "not_populated_multiple_or_missing_subquestion_denominators"
        source = aggregate_sources[(round_number, "questionnaire")]
        yield {
            "region": "jp",
            "round": round_number,
            "source_generation": "modern_official",
            "scope": "overall_questionnaire",
            "question_id": f"jp{round_number}:modern:{question_key}",
            "question": question_key,
            "node_path": row.get("node_path"),
            "item": row.get("name"),
            "option": row.get("label"),
            "count": as_int(row.get("count")),
            "rate": as_float(row.get("rate")),
            "denominator": denominator,
            "denominator_basis": denominator_basis,
            "count_unit": "respondent selections",
            "source_url": source.get("url"),
            "source_file": source.get("output"),
            "source_sha256": source.get("sha256"),
        }


def legacy_entity_question_rows(ranks: Mapping[tuple[int, str, str], int]) -> Iterator[dict[str, Any]]:
    for row in load_rows(LEGACY_ROOT / "entity_questionnaire_long.csv"):
        conditional = as_float(row.get("percentage"))
        overall = as_float(row.get("overall_percentage"))
        official_delta_points = as_float(row.get("delta_points"))
        conditional_rate = conditional / 100 if conditional is not None else None
        overall_rate = overall / 100 if overall is not None else None
        yield {
            "region": "jp",
            "round": int(row["round"]),
            "source_generation": "legacy_official",
            "source_category": row.get("source_category"),
            "source_id": row.get("source_item_id"),
            "source_name": row.get("source_entity_name"),
            "source_rank": ranks.get(
                (int(row["round"]), row["source_category"], row["source_entity_name"])
            ),
            "question_id": row.get("question_id"),
            "question": row.get("question"),
            "option": row.get("option"),
            "count": as_int(row.get("count")),
            "conditional_rate": conditional_rate,
            "official_conditional_rate_raw": conditional,
            "rate_status": "valid_legacy_percentage_converted",
            "conditional_denominator": as_int(row.get("denominator")),
            "conditional_denominator_basis": row.get("denominator_basis"),
            "overall_rate": overall_rate,
            "overall_denominator": None,
            "overall_denominator_basis": "not_reconstructed_from_rounded_legacy_percentage",
            "delta_points": official_delta_points,
            "official_delta_points_raw": official_delta_points,
            "lift": divide(conditional_rate, overall_rate),
            "source_url": row.get("source_url"),
            "source_sha256": row.get("source_sha256"),
            "source_table_index": row.get("source_table_index"),
            "source_row_index": row.get("source_row_index"),
        }


def modern_entity_question_rows(detail_sources: Mapping[tuple[int, str, str], Mapping[str, Any]]) -> Iterator[dict[str, Any]]:
    rows = list(load_rows(MODERN_ROOT / "detail_questionnaire_long.csv"))
    denominator_sets: dict[tuple[int, str, str, str], set[int]] = defaultdict(set)
    for row in rows:
        denominator = as_int(row.get("conditional_denominator_derived"))
        if denominator is not None:
            denominator_sets[
                (int(row["round"]), row["source_category"], row["source_id"], row["question_key"])
            ].add(denominator)
    for row in rows:
        round_number = int(row["round"])
        key = (round_number, row["source_category"], row["source_id"], row["question_key"])
        candidates = denominator_sets[key]
        denominator = as_int(row.get("conditional_denominator_derived"))
        if denominator is None and len(candidates) == 1:
            denominator = next(iter(candidates))
            denominator_basis = "filled_from_unique_same_entity_question_denominator"
        elif denominator is not None:
            denominator_basis = "derived_from_official_count_and_rate"
        else:
            denominator_basis = "not_populated_multiple_or_missing_subquestion_denominators"
        official_conditional_rate = as_float(row.get("rate"))
        overall_rate = as_float(row.get("total"))
        official_delta_points = as_float(row.get("diff"))
        # Two sparse official detail rows currently publish rates of 2.0
        # (200%) with a derived denominator of one.  They cannot be used as
        # proportions.  Preserve the official numbers verbatim, but leave the
        # analysis-rate fields empty instead of clipping or silently changing
        # their denominator.
        if official_conditional_rate is None:
            conditional_rate = None
            rate_status = "official_rate_missing"
        elif valid_rate(official_conditional_rate):
            conditional_rate = official_conditional_rate
            rate_status = "valid_official_proportion"
        else:
            conditional_rate = None
            rate_status = "official_rate_outside_proportion_domain"
        source = detail_sources[(round_number, row["source_category"], row["source_id"])]
        yield {
            "region": "jp",
            "round": round_number,
            "source_generation": "modern_official",
            "source_category": row.get("source_category"),
            "source_id": row.get("source_id"),
            "source_name": row.get("source_name"),
            "source_rank": as_int(row.get("source_rank")),
            "question_id": f"jp{round_number}:modern:{row['question_key']}",
            "question": row.get("question_key"),
            "node_path": row.get("node_path"),
            "option": row.get("label"),
            "count": as_int(row.get("count")),
            "conditional_rate": conditional_rate,
            "official_conditional_rate_raw": official_conditional_rate,
            "rate_status": rate_status,
            "conditional_denominator": denominator,
            "conditional_denominator_basis": denominator_basis,
            "overall_rate": overall_rate,
            "overall_denominator": as_int(row.get("overall_denominator")),
            "overall_denominator_basis": row.get("overall_denominator_basis"),
            "delta_points": official_delta_points if conditional_rate is not None else None,
            "official_delta_points_raw": official_delta_points,
            "lift": divide(conditional_rate, overall_rate),
            "source_url": source.get("url"),
            "source_file": source.get("output"),
            "source_sha256": source.get("sha256"),
        }


def legacy_association_rows(ranks: Mapping[tuple[int, str, str], int]) -> Iterator[dict[str, Any]]:
    for row in load_rows(LEGACY_ROOT / "entity_association_long.csv"):
        conditional = as_float(row.get("conditional_percentage"))
        overall = as_float(row.get("overall_percentage"))
        conditional_rate = conditional / 100 if conditional is not None else None
        overall_rate = overall / 100 if overall is not None else None
        yield {
            "region": "jp",
            "round": int(row["round"]),
            "source_generation": "legacy_official",
            "source_category": row.get("source_category"),
            "source_id": row.get("source_item_id"),
            "source_name": row.get("source_entity_name"),
            "source_rank": ranks.get(
                (int(row["round"]), row["source_category"], row["source_entity_name"])
            ),
            "target_category": row.get("target_category"),
            "target_name": row.get("target_entity_name"),
            "association_context": row.get("association_context"),
            "association_kind": row.get("association_kind"),
            "publication_scope": "official_published_leading_list",
            "complete_pair_matrix": False,
            "published_orderings": row.get("association_kind"),
            "published_positions": row.get("rank"),
            "intersection_count": as_int(row.get("vote_count")),
            "conditional_rate": conditional_rate,
            "conditional_denominator": as_int(row.get("conditional_denominator")),
            "conditional_denominator_basis": row.get("conditional_denominator_basis"),
            "overall_rate": overall_rate,
            "overall_denominator": as_int(row.get("overall_denominator")),
            "overall_denominator_basis": row.get("overall_denominator_basis"),
            "delta_points": as_float(row.get("delta_points")),
            "lift": divide(conditional_rate, overall_rate),
            "source_url": row.get("source_url"),
            "source_sha256": row.get("source_sha256"),
        }


def same_numeric(left: Mapping[str, str], right: Mapping[str, str], fields: Iterable[str]) -> bool:
    for field in fields:
        left_value = as_float(left.get(field))
        right_value = as_float(right.get(field))
        if left_value is None or right_value is None:
            if left_value != right_value:
                return False
        elif abs(left_value - right_value) > 1e-12:
            return False
    return True


def modern_association_rows(detail_sources: Mapping[tuple[int, str, str], Mapping[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    grouped: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in load_rows(MODERN_ROOT / "detail_associations.csv"):
        key = (
            row["round"],
            row["source_category"],
            row["source_id"],
            row["target_category"],
            row["target_name"],
        )
        grouped[key].append(row)
    duplicate_rows_removed = 0
    output: list[dict[str, Any]] = []
    numeric_fields = ("count", "rate", "total", "diff", "conditional_denominator_derived")
    for key, rows in grouped.items():
        first = rows[0]
        for other in rows[1:]:
            if not same_numeric(first, other, numeric_fields):
                raise AssertionError(f"modern association duplicate differs: {key}")
        duplicate_rows_removed += len(rows) - 1
        round_number = int(first["round"])
        conditional_rate = as_float(first.get("rate"))
        overall_rate = as_float(first.get("total"))
        source = detail_sources[
            (round_number, first["source_category"], first["source_id"])
        ]
        ordering_positions = sorted(
            {(row.get("ordering", ""), as_int(row.get("position"))) for row in rows}
        )
        output.append(
            {
                "region": "jp",
                "round": round_number,
                "source_generation": "modern_official",
                "source_category": first.get("source_category"),
                "source_id": first.get("source_id"),
                "source_name": first.get("source_name"),
                "source_rank": as_int(first.get("source_rank")),
                "target_category": first.get("target_category"),
                "target_name": first.get("target_name"),
                "association_context": "others",
                "association_kind": "published_leading_conditional_co_vote",
                "publication_scope": "official_published_leading_list",
                "complete_pair_matrix": False,
                "published_orderings": json.dumps(
                    [item[0] for item in ordering_positions], ensure_ascii=False
                ),
                "published_positions": json.dumps(
                    [item[1] for item in ordering_positions], ensure_ascii=False
                ),
                "intersection_count": as_int(first.get("count")),
                "conditional_rate": conditional_rate,
                "conditional_denominator": as_int(
                    first.get("conditional_denominator_derived")
                ),
                "conditional_denominator_basis": "derived_from_official_intersection_and_conditional_rate",
                "overall_rate": overall_rate,
                "overall_denominator": as_int(first.get("overall_denominator")),
                "overall_denominator_basis": first.get("overall_denominator_basis"),
                "delta_points": as_float(first.get("diff")),
                "lift": divide(conditional_rate, overall_rate),
                "source_url": source.get("url"),
                "source_file": source.get("output"),
                "source_sha256": source.get("sha256"),
            }
        )
    output.sort(
        key=lambda row: (
            row["round"],
            row["source_category"],
            str(row["source_id"]),
            row["target_category"],
            row["target_name"],
        )
    )
    return output, duplicate_rows_removed


def valid_rate(value: Any) -> bool:
    return value in (None, "") or 0 <= float(value) <= 1


def main() -> None:
    aggregate_sources, detail_sources = manifest_maps()
    ranks = source_rank_map()

    output_paths = {
        "aggregate_questionnaire_long.csv.gz": OUTPUT_ROOT
        / "aggregate_questionnaire_long.csv.gz",
        "entity_questionnaire_long.csv.gz": OUTPUT_ROOT
        / "entity_questionnaire_long.csv.gz",
        "entity_association_long.csv.gz": OUTPUT_ROOT
        / "entity_association_long.csv.gz",
    }

    aggregate_rows = [*legacy_aggregate_rows(), *modern_aggregate_rows(aggregate_sources)]
    entity_question_rows = [
        *legacy_entity_question_rows(ranks),
        *modern_entity_question_rows(detail_sources),
    ]
    modern_associations, duplicate_rows_removed = modern_association_rows(detail_sources)
    association_rows = [*legacy_association_rows(ranks), *modern_associations]
    entity_rate_anomalies = [
        row
        for row in entity_question_rows
        if row.get("rate_status") == "official_rate_outside_proportion_domain"
    ]

    row_counts = {
        "aggregate_questionnaire_long.csv.gz": write_gzip_csv(
            output_paths["aggregate_questionnaire_long.csv.gz"],
            AGGREGATE_FIELDS,
            aggregate_rows,
        ),
        "entity_questionnaire_long.csv.gz": write_gzip_csv(
            output_paths["entity_questionnaire_long.csv.gz"],
            ENTITY_QUESTION_FIELDS,
            entity_question_rows,
        ),
        "entity_association_long.csv.gz": write_gzip_csv(
            output_paths["entity_association_long.csv.gz"],
            ASSOCIATION_FIELDS,
            association_rows,
        ),
    }

    aggregate_rounds = sorted({int(row["round"]) for row in aggregate_rows})
    entity_question_rounds = sorted({int(row["round"]) for row in entity_question_rows})
    association_rounds = sorted({int(row["round"]) for row in association_rows})
    validations = {
        "aggregate_rounds_exactly_3_to_22": aggregate_rounds == list(range(3, 23)),
        "entity_question_rounds_cover_all_officially_published_detail_rounds": entity_question_rounds
        == list(range(11, 23)),
        "association_rounds_cover_all_officially_published_detail_rounds": association_rounds
        == list(range(11, 23)),
        "aggregate_rates_within_zero_one": all(valid_rate(row.get("rate")) for row in aggregate_rows),
        "entity_question_rates_within_zero_one": all(
            valid_rate(row.get("conditional_rate")) and valid_rate(row.get("overall_rate"))
            for row in entity_question_rows
        ),
        "association_rates_within_zero_one": all(
            valid_rate(row.get("conditional_rate")) and valid_rate(row.get("overall_rate"))
            for row in association_rows
        ),
        "associations_explicitly_marked_as_incomplete_published_lists": all(
            row.get("publication_scope") == "official_published_leading_list"
            and row.get("complete_pair_matrix") is False
            for row in association_rows
        ),
        "all_modern_detail_sources_mapped": all(
            row.get("source_url") and row.get("source_sha256")
            for row in [
                *(
                    row
                    for row in entity_question_rows
                    if row["source_generation"] == "modern_official"
                ),
                *modern_associations,
            ]
        ),
    }
    if not all(validations.values()):
        raise AssertionError(json.dumps(validations, ensure_ascii=False))

    source_files = [
        LEGACY_ROOT / "questionnaire_long.csv",
        LEGACY_ROOT / "entity_questionnaire_long.csv",
        LEGACY_ROOT / "entity_association_long.csv",
        LEGACY_ROOT / "source_entity_metrics.csv",
        MODERN_ROOT / "questionnaire_long.csv",
        MODERN_ROOT / "detail_questionnaire_long.csv",
        MODERN_ROOT / "detail_associations.csv",
        MANIFEST_PATH,
    ]
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "scope": "Japanese official rounds 3-22",
        "name_policy": "official Japanese labels retained; no automatic translation or entity merging",
        "percentage_policy": "all analysis-ready normalized rate fields are proportions in [0,1]; out-of-domain official raw values remain in explicitly named provenance fields",
        "published_scope_policy": "detail associations are the official leading lists, not an invented complete pair matrix",
        "rounds": {
            "aggregate_questionnaire": aggregate_rounds,
            "entity_questionnaire": entity_question_rounds,
            "entity_association": association_rounds,
        },
        "row_counts": row_counts,
        "modern_association_duplicate_ordering_rows_collapsed": duplicate_rows_removed,
        "modern_entity_question_official_rate_anomalies": [
            {
                key: row.get(key)
                for key in (
                    "round",
                    "source_category",
                    "source_id",
                    "source_name",
                    "question",
                    "option",
                    "count",
                    "official_conditional_rate_raw",
                    "conditional_denominator",
                    "source_url",
                )
            }
            for row in entity_rate_anomalies
        ],
        "source_generation_counts": {
            "aggregate_questionnaire": dict(Counter(row["source_generation"] for row in aggregate_rows)),
            "entity_questionnaire": dict(Counter(row["source_generation"] for row in entity_question_rows)),
            "entity_association": dict(Counter(row["source_generation"] for row in association_rows)),
        },
        "inputs": [
            {
                "path": path.relative_to(WORKSPACE).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in source_files
        ],
        "outputs": [
            {
                "path": path.relative_to(WORKSPACE).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "rows": row_counts[name],
            }
            for name, path in output_paths.items()
        ],
        "validations": validations,
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"row_counts": row_counts, "validations": validations}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
