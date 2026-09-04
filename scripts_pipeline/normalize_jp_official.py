"""Normalize official Japanese result modules into analysis-ready CSV files.

Input is produced by ``crawl_jp_official.mjs``.  No network access is used.
Conditional denominators may be recovered from an official intersection
count/conditional-rate pair.  Overall denominators are never recovered from
that same intersection count: association baselines instead use the official
target ranking count and department ballot count, while questionnaire baseline
denominators are populated only when the aggregate question has one unique
response denominator.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Iterator


WORKSPACE = Path(__file__).resolve().parents[1]
RAW_ROOT = WORKSPACE / "data_raw" / "jp_official"
OUT_ROOT = WORKSPACE / "data_processed" / "jp_official"
METADATA_ROOT = WORKSPACE / "metadata"


def load_data(path: Path) -> Any:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "_source" not in payload or "data" not in payload:
        raise ValueError(f"not a crawler output: {path}")
    return payload["data"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def derived_denominators(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    count = row.get("count")
    rate = row.get("rate")
    if isinstance(count, (int, float)) and isinstance(rate, (int, float)) and rate > 0:
        result["conditional_denominator_derived"] = round(count / rate)
    return result


def normalized_label(value: Any) -> str:
    return "".join(str(value or "").split())


def walk_records(
    node: Any,
    *,
    path: tuple[str, ...] = (),
    context: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield scalar records from arbitrarily nested questionnaire structures."""
    context = dict(context or {})
    if isinstance(node, dict):
        local = {key: value for key, value in node.items() if scalar(value)}
        nested = {key: value for key, value in node.items() if not scalar(value)}
        merged = {**context, **local}
        if not nested:
            yield {"node_path": "/".join(path), **merged}
            return
        # Parent scalars (for example valid_count/name) are context for options.
        for key, value in nested.items():
            yield from walk_records(value, path=(*path, key), context=merged)
        return
    if isinstance(node, list):
        for index, value in enumerate(node):
            # Long free-text feedback is deliberately retained in raw JSON but
            # is not copied into the numeric CSV.
            if isinstance(value, str):
                continue
            yield from walk_records(value, path=(*path, str(index)), context=context)
        return
    if not isinstance(node, str):
        yield {"node_path": "/".join(path), **context, "value": node}


def write_csv(path: Path, rows: Iterable[dict[str, Any]], preferred: list[str]) -> int:
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(preferred)
    extra = sorted({key for row in materialized for key in row} - set(fields))
    fields.extend(extra)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(materialized)
    return len(materialized)


def numeric_paths(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.json"), key=lambda path: int(path.stem))


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    METADATA_ROOT.mkdir(parents=True, exist_ok=True)

    manifest_path = METADATA_ROOT / "jp_official_download_manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {}
    )

    rankings: list[dict[str, Any]] = []
    counts: list[dict[str, Any]] = []
    questionnaire: list[dict[str, Any]] = []
    questionnaire_feedback: list[dict[str, Any]] = []

    available_rounds = sorted(
        int(path.name.removeprefix("round_"))
        for path in RAW_ROOT.glob("round_*")
        if path.is_dir()
    )
    for round_number in available_rounds:
        aggregate = RAW_ROOT / f"round_{round_number}" / "aggregate"
        for category in ("character", "music", "work"):
            source = aggregate / f"{category}.json"
            if not source.exists():
                continue
            for item in load_data(source):
                rankings.append({"round": round_number, "category": category, **item})

        count_path = aggregate / "count.json"
        if count_path.exists():
            for category, value in load_data(count_path).items():
                counts.append({"round": round_number, "category": category, "ballots": value})

        questionnaire_path = aggregate / "questionnaire.json"
        if questionnaire_path.exists():
            data = load_data(questionnaire_path)
            for question_key, value in data.items():
                if question_key == "feedback" and isinstance(value, list):
                    questionnaire_feedback.append(
                        {
                            "round": round_number,
                            "question_key": question_key,
                            "response_count": len(value),
                        }
                    )
                    continue
                for row in walk_records(value, path=(question_key,)):
                    questionnaire.append(
                        derived_denominators(
                            {"round": round_number, "question_key": question_key, **row}
                        )
                    )

    detail_items: list[dict[str, Any]] = []
    detail_questionnaire: list[dict[str, Any]] = []
    associations: list[dict[str, Any]] = []
    breakdowns: list[dict[str, Any]] = []
    detail_file_counts: dict[str, int] = {}

    questionnaire_denominators: dict[tuple[int, str], set[int]] = {}
    for row in questionnaire:
        denominator = row.get("conditional_denominator_derived")
        if isinstance(denominator, int):
            questionnaire_denominators.setdefault(
                (int(row["round"]), str(row["question_key"])), set()
            ).add(denominator)

    ballot_count_map = {
        (int(row["round"]), str(row["category"])): int(row["ballots"])
        for row in counts
        if isinstance(row.get("ballots"), (int, float))
    }
    # This is only a historical formula candidate, not a universal vote-count
    # reconstruction.  Round 17 detail modules and today's aggregate modules
    # are different official snapshots, while round 21 introduced a secondary
    # preference whose extra weight is not present in the aggregate row.  The
    # detail module's published ``total`` remains the authoritative baseline.
    target_points_minus_primary_map: dict[tuple[int, str, str], int] = {}
    for row in rankings:
        point = row.get("point")
        primary = row.get("primary_num")
        if isinstance(point, (int, float)) and isinstance(primary, (int, float)):
            target_points_minus_primary_map[
                (
                    int(row["round"]),
                    str(row["category"]),
                    normalized_label(row.get("name")),
                )
            ] = int(point - primary)

    for round_number in available_rounds:
        detail_root = RAW_ROOT / f"round_{round_number}" / "detail"
        if not detail_root.exists():
            continue
        for category in ("character", "music", "work"):
            directory = detail_root / category
            files = numeric_paths(directory) if directory.exists() else []
            detail_file_counts[f"{round_number}:{category}"] = len(files)
            for source in files:
                item = load_data(source)
                base = {
                    "round": round_number,
                    "source_category": category,
                    "source_id": item.get("id", source.stem),
                    "source_name": item.get("name"),
                    "source_rank": item.get("rank"),
                }
                scalars = {key: value for key, value in item.items() if scalar(value)}
                detail_items.append({**base, **scalars})

                for question_key, value in (item.get("questionnaire") or {}).items():
                    for row in walk_records(value, path=(question_key,)):
                        normalized = derived_denominators(
                            {**base, "question_key": question_key, **row}
                        )
                        denominator_candidates = questionnaire_denominators.get(
                            (round_number, question_key), set()
                        )
                        if len(denominator_candidates) == 1:
                            normalized["overall_denominator"] = next(
                                iter(denominator_candidates)
                            )
                            normalized["overall_denominator_basis"] = (
                                "unique_official_aggregate_question_denominator"
                            )
                        elif denominator_candidates:
                            normalized["overall_denominator_basis"] = (
                                "not_populated_multiple_aggregate_subquestion_denominators"
                            )
                        else:
                            normalized["overall_denominator_basis"] = (
                                "not_available_in_aggregate_questionnaire"
                            )
                        detail_questionnaire.append(normalized)

                for target_category, orderings in (item.get("others") or {}).items():
                    for ordering, values in (orderings or {}).items():
                        for position, value in enumerate(values, start=1):
                            normalized = derived_denominators(
                                {
                                    **base,
                                    "target_category": target_category,
                                    "ordering": ordering,
                                    "position": position,
                                    "target_name": value.get("label"),
                                    **{key: val for key, val in value.items() if key != "label"},
                                }
                            )
                            points_minus_primary_candidate = (
                                target_points_minus_primary_map.get(
                                (
                                    round_number,
                                    target_category,
                                    normalized_label(value.get("label")),
                                )
                            )
                            )
                            overall_denominator = ballot_count_map.get(
                                (round_number, target_category)
                            )
                            published_total = normalized.get("total")
                            if isinstance(published_total, (int, float)):
                                normalized["overall_rate_published"] = published_total
                            if overall_denominator:
                                normalized["current_aggregate_department_ballots"] = (
                                    overall_denominator
                                )
                                normalized["current_aggregate_department_ballots_basis"] = (
                                    "official_current_aggregate_count_module"
                                )
                            if (
                                isinstance(published_total, (int, float))
                                and overall_denominator
                            ):
                                current_count = published_total * overall_denominator
                                current_count_rounded = round(current_count)
                                current_count_error = abs(
                                    current_count - current_count_rounded
                                )
                                normalized[
                                    "published_total_times_current_ballots"
                                ] = current_count
                                normalized[
                                    "published_total_current_ballots_rounding_error"
                                ] = current_count_error
                                if current_count_error < 1e-7:
                                    normalized[
                                        "target_vote_count_from_published_total"
                                    ] = current_count_rounded
                                    normalized[
                                        "target_vote_count_from_published_total_basis"
                                    ] = (
                                        "official_detail_total_times_matching_current_department_ballots"
                                    )
                                    normalized["overall_denominator"] = (
                                        overall_denominator
                                    )
                                    normalized["overall_denominator_basis"] = (
                                        "current_official_aggregate_count_matches_detail_total_snapshot"
                                    )
                                else:
                                    normalized["overall_denominator_basis"] = (
                                        "not_populated_detail_and_current_aggregate_snapshots_differ"
                                    )
                            elif isinstance(published_total, (int, float)):
                                normalized["overall_denominator_basis"] = (
                                    "published_detail_total_only_no_aggregate_department_count"
                                )
                            else:
                                normalized["overall_denominator_basis"] = (
                                    "published_detail_total_not_available"
                                )
                            if points_minus_primary_candidate is not None:
                                normalized[
                                    "aggregate_points_minus_primary_candidate"
                                ] = points_minus_primary_candidate
                                if overall_denominator:
                                    candidate_rate = (
                                        points_minus_primary_candidate
                                        / overall_denominator
                                    )
                                    normalized[
                                        "aggregate_points_minus_primary_candidate_rate"
                                    ] = candidate_rate
                                    if isinstance(
                                        published_total, (int, float)
                                    ):
                                        normalized[
                                            "aggregate_candidate_minus_published_rate"
                                        ] = candidate_rate - published_total
                            associations.append(normalized)

                for position, value in enumerate(item.get("breakdown") or [], start=1):
                    if isinstance(value, dict):
                        breakdowns.append({**base, "position": position, **value})
                    else:
                        breakdowns.append({**base, "position": position, "value": value})

    row_counts = {
        "rankings.csv": write_csv(
            OUT_ROOT / "rankings.csv", rankings, ["round", "category", "rank", "code", "name"]
        ),
        "ballot_counts.csv": write_csv(
            OUT_ROOT / "ballot_counts.csv", counts, ["round", "category", "ballots"]
        ),
        "questionnaire_long.csv": write_csv(
            OUT_ROOT / "questionnaire_long.csv",
            questionnaire,
            ["round", "question_key", "node_path", "label", "value", "count", "rate", "total", "diff"],
        ),
        "questionnaire_feedback_counts.csv": write_csv(
            OUT_ROOT / "questionnaire_feedback_counts.csv",
            questionnaire_feedback,
            ["round", "question_key", "response_count"],
        ),
        "detail_items.csv": write_csv(
            OUT_ROOT / "detail_items.csv",
            detail_items,
            ["round", "source_category", "source_id", "source_name", "source_rank", "point", "primary", "secondary", "comment"],
        ),
        "detail_questionnaire_long.csv": write_csv(
            OUT_ROOT / "detail_questionnaire_long.csv",
            detail_questionnaire,
            ["round", "source_category", "source_id", "source_name", "source_rank", "question_key", "label", "count", "rate", "total", "diff"],
        ),
        "detail_associations.csv": write_csv(
            OUT_ROOT / "detail_associations.csv",
            associations,
            ["round", "source_category", "source_id", "source_name", "source_rank", "target_category", "ordering", "position", "target_name", "count", "rate", "total", "diff"],
        ),
        "detail_breakdowns.csv": write_csv(
            OUT_ROOT / "detail_breakdowns.csv",
            breakdowns,
            ["round", "source_category", "source_id", "source_name", "source_rank", "position"],
        ),
    }

    output_files = [OUT_ROOT / name for name in row_counts]
    expected_detail_file_counts: dict[str, int] = {}
    for key, value in (manifest.get("expected_counts") or {}).items():
        parts = str(key).split(":")
        if len(parts) == 3 and parts[1] == "detail":
            expected_detail_file_counts[f"{parts[0]}:{parts[2]}"] = int(value)

    manifest_records = manifest.get("records") or []
    manifest_outputs_present = True
    manifest_source_hashes_match = True
    for record in manifest_records:
        relative = record.get("output")
        if not relative:
            manifest_outputs_present = False
            continue
        output_path = WORKSPACE / relative
        if not output_path.exists():
            manifest_outputs_present = False
            continue
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        if payload.get("_source", {}).get("sha256") != record.get("sha256"):
            manifest_source_hashes_match = False

    checks = {
        "schema_version": 1,
        "normalizer": {
            "path": "scripts_pipeline/normalize_jp_official.py",
            "sha256": sha256_file(Path(__file__)),
        },
        "input_root": RAW_ROOT.relative_to(WORKSPACE).as_posix(),
        "output_root": OUT_ROOT.relative_to(WORKSPACE).as_posix(),
        "available_rounds": available_rounds,
        "manifest_rounds": manifest.get("rounds", []),
        "manifest_detail_rounds": manifest.get("detail_rounds", []),
        "expected_detail_file_counts": expected_detail_file_counts,
        "detail_file_counts": detail_file_counts,
        "row_counts": row_counts,
        "outputs": [
            {
                "path": path.relative_to(WORKSPACE).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "rows": row_counts[path.name],
            }
            for path in output_files
        ],
        "validations": {
            "all_manifest_outputs_present": manifest_outputs_present,
            "all_manifest_source_hashes_match": manifest_source_hashes_match,
            "all_requested_detail_counts_match_manifest": bool(
                expected_detail_file_counts
            )
            and all(
                detail_file_counts.get(key) == expected
                for key, expected in expected_detail_file_counts.items()
            ),
            "all_rates_finite": all(
                not isinstance(row.get("rate"), float) or math.isfinite(row["rate"])
                for row in questionnaire + detail_questionnaire + associations
            ),
            "no_invalid_intersection_overall_denominator_field": all(
                "overall_denominator_derived" not in row
                for row in questionnaire + detail_questionnaire + associations
            ),
            "published_association_baselines_retained_without_overwrite": all(
                not isinstance(row.get("total"), (int, float))
                or row.get("overall_rate_published") == row.get("total")
                for row in associations
            ),
        },
    }
    checks["association_scope_diagnostics"] = {
        "rows": len(associations),
        "rows_matching_current_aggregate_ballot_snapshot": sum(
            "target_vote_count_from_published_total" in row for row in associations
        ),
        "rows_with_detail_vs_current_aggregate_snapshot_difference": sum(
            row.get("overall_denominator_basis")
            == "not_populated_detail_and_current_aggregate_snapshots_differ"
            for row in associations
        ),
        "rows_where_points_minus_primary_is_not_the_published_baseline": sum(
            isinstance(row.get("aggregate_candidate_minus_published_rate"), float)
            and abs(row["aggregate_candidate_minus_published_rate"]) >= 1e-12
            for row in associations
        ),
    }
    if not all(checks["validations"].values()):
        raise AssertionError(json.dumps(checks["validations"], ensure_ascii=False))
    (METADATA_ROOT / "jp_official_normalization_report.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
