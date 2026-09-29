#!/usr/bin/env python3
"""Build an auditable per-round coverage inventory for vote network analyses."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "analysis_results" / "network_coverage.csv"
DEFAULT_JSON = ROOT / "analysis_results" / "network_coverage.json"
DEFAULT_COVOTE = ROOT / "vote_explorer" / "data" / "analysis_covote_pairs_all.csv"
ANALYSES = (
    "hypothesis_tests",
    "mrqap",
    "sensitivity_scan",
    "communities",
    "matrix_within_round",
    "matrix_adjacent_round",
)
FIELDS = (
    "analysis", "region", "round", "comparison_round", "status",
    "observed_pair_rows", "complete_pair_rows", "matrix_source_pair_rows",
    "matrix_source_complete_pair_rows", "result_rows",
    "result_path", "reason", "source_scope",
)


def round_labels() -> list[tuple[str, str]]:
    return [("cn", f"CN{number}") for number in range(1, 12)] + [
        ("jp", f"JP{number}") for number in range(3, 23)
    ]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _count_by_round(rows: Iterable[Mapping[str, Any]], *, label_field: str = "round") -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for row in rows:
        region = str(row.get("region", "")).strip().casefold()
        label = str(row.get(label_field, "")).strip().upper()
        if not label:
            number = str(row.get("round", "")).strip()
            label = f"{region.upper()}{number}"
        if region and label:
            counts[(region, label)] += 1
    return counts


def _rows_by_round(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        region = str(row.get("region", "")).strip().casefold()
        label = str(row.get("round", "")).strip().upper()
        if re.fullmatch(r"\d+(?:\.0+)?", label):
            label = f"{region.upper()}{int(float(label))}"
        if region and label:
            grouped[(region, label)].append(row)
    return grouped


def build_coverage(
    *, root: Path = ROOT, covote_path: Path = DEFAULT_COVOTE,
) -> list[dict[str, Any]]:
    root = root.resolve()
    covote = read_csv(covote_path)
    char_pairs = [row for row in covote if row.get("pair_category") == "character"]
    pair_counts = _count_by_round(char_pairs, label_field="round_label")
    complete_counts: Counter[tuple[str, str]] = Counter(
        (str(row.get("region", "")).casefold(), str(row.get("round_label", "")).upper())
        for row in char_pairs if str(row.get("complete_pair_matrix", "")).casefold() == "true"
    )
    all_matrix_pairs = [row for row in covote if row.get("pair_category") in {"character", "music"}]
    matrix_pair_counts = _count_by_round(all_matrix_pairs, label_field="round_label")
    matrix_complete_counts: Counter[tuple[str, str]] = Counter(
        (str(row.get("region", "")).casefold(), str(row.get("round_label", "")).upper())
        for row in all_matrix_pairs if str(row.get("complete_pair_matrix", "")).casefold() == "true"
    )
    cp_rows = read_csv(root / "vote_explorer" / "data" / "analysis_vote_combinations_all.csv")
    cp_rows = [row for row in cp_rows if row.get("data_source") == "official_cp" and not str(row.get("name_c", "")).strip()]
    cp_pair_counts = _count_by_round(cp_rows, label_field="round_label")
    jp_component_path = root / "metadata" / "jp_official_legacy_component_status.json"
    jp_crawl_path = root / "metadata" / "jp_official_legacy_coverage.json"
    jp_components = json.loads(jp_component_path.read_text(encoding="utf-8-sig")).get("rounds", {}) if jp_component_path.is_file() else {}
    jp_crawls = json.loads(jp_crawl_path.read_text(encoding="utf-8-sig")).get("rounds", {}) if jp_crawl_path.is_file() else {}

    network_dir = root / "analysis_results" / "network_inference"
    outputs = {
        "hypothesis_tests": (network_dir / "hypothesis_tests.csv", read_csv(network_dir / "hypothesis_tests.csv")),
        "mrqap": (network_dir / "mrqap_coefficients.csv", read_csv(network_dir / "mrqap_coefficients.csv")),
        "sensitivity_scan": (network_dir / "sensitivity_scan.csv", read_csv(network_dir / "sensitivity_scan.csv")),
        "matrix_within_round": (network_dir / "matrix_correlations.csv", read_csv(network_dir / "matrix_correlations.csv")),
        "matrix_adjacent_round": (network_dir / "matrix_correlations.csv", read_csv(network_dir / "matrix_correlations.csv")),
    }
    result_groups = {key: _rows_by_round(value[1]) for key, value in outputs.items()}
    matrix_rows = outputs["matrix_within_round"][1]
    community_root = root / "analysis_results" / "network_communities" / "by_round"
    community_manifests = {
        path.name.upper(): path / "community_run_manifest.json"
        for path in community_root.iterdir() if path.is_dir()
    } if community_root.is_dir() else {}
    node_counts: dict[str, int] = {}
    for label in community_manifests:
        assignments = read_csv(community_root / label / "community_assignments.csv")
        node_counts[label] = len(assignments)

    rows: list[dict[str, Any]] = []
    for region, label in round_labels():
        key = (region, label)
        observed_n, complete_n = pair_counts[key], complete_counts[key]
        matrix_source_n = matrix_pair_counts[key] + cp_pair_counts[key]
        matrix_source_complete_n = matrix_complete_counts[key]
        jp_source_reason = ""
        if region == "jp":
            round_no = label[2:]
            component = jp_components.get(round_no, {})
            crawl = jp_crawls.get(round_no, {})
            if component.get("entity_numeric_profiles") == "official_not_offered":
                jp_source_reason = (
                    "official entity numeric association profiles were not offered; "
                    f"legacy crawl completeness was {crawl.get('pages_ok', 0)}/{crawl.get('pages_recorded', 0)} pages ok, "
                    f"{crawl.get('pages_error', 0)} page errors, "
                    f"{len(component.get('fetch_failures', []))} recorded fetch failures"
                )
        for analysis in ANALYSES:
            comparison = ""
            result_path = ""
            result_n = 0
            source_scope = "observed_character_pair_metrics"
            reason = ""
            status = ""
            if analysis == "communities":
                result_path_obj = community_manifests.get(label)
                result_n = node_counts.get(label, 0)
                result_path = f"analysis_results/network_communities/by_round/{label}/community_run_manifest.json"
                source_scope = "official_character_nodes_and_observed_pairs"
                if result_path_obj and result_path_obj.is_file():
                    if observed_n:
                        status = "computed_observed_network"
                    else:
                        status = "computed_isolates_only"
                        reason = jp_source_reason or "official character node universe exists, but no official co-vote pair rows are available; no edges were inferred"
                else:
                    status = "unavailable_missing_node_universe"
                    reason = "no per-round community result or character node universe was found"
            elif analysis in {"matrix_within_round", "matrix_adjacent_round"}:
                result_path = "analysis_results/network_inference/matrix_correlations.csv"
                if analysis == "matrix_within_round":
                    result_n = sum(1 for row in matrix_rows
                                   if str(row.get("region", "")).casefold() == region
                                   and str(row.get("round", "")).upper() == label)
                    if result_n:
                        status = "computed_observed_matrix_comparisons"
                    else:
                        status = "unavailable_no_matrix_sources"
                        reason = "no observed character co-vote matrices are available for within-round comparison"
                else:
                    n = int(label[2:])
                    prior = n - 1
                    comparison = f"{label[:2]}{prior}"
                    result_n = sum(1 for row in matrix_rows
                                   if str(row.get("region", "")).casefold() == region
                                   and str(row.get("round", "")).upper() == f"{label}_VS_{comparison}")
                    if result_n:
                        status = "computed_common_observed_pairs"
                    elif (region == "cn" and n == 1) or (region == "jp" and n == 3):
                        status = "not_applicable_first_in_scope_round"
                        reason = "the immediately preceding round is outside the fixed analysis scope"
                    else:
                        status = "unavailable_adjacent_matrix_pair"
                        reason = jp_source_reason or f"adjacent matrix comparison {label} vs {comparison} is unavailable because one or both official rounds lack comparable observed pair matrices"
                source_scope = "common_observed_pairs_only_no_zero_fill"
            else:
                output_path, _ = outputs[analysis]
                result_path = output_path.relative_to(root).as_posix()
                result_rows = result_groups[analysis].get(key, [])
                result_n = len(result_rows)
                if analysis == "hypothesis_tests":
                    if observed_n and result_n:
                        status = "computed_observed_pairs"
                    elif not observed_n:
                        status = "unavailable_no_official_pair_data"
                        reason = jp_source_reason or "no official character co-vote pair table is present for this round; rankings do not identify pair intersections"
                    else:
                        status = "unavailable_result_rows_missing"
                        reason = "observed pair input exists but the expected hypothesis result rows are absent"
                    source_scope = "official_pair_rows_only; partial pairs remain observed-only"
                elif analysis == "mrqap":
                    model_statuses = {str(row.get("status", "")) for row in result_rows}
                    if result_n and complete_n and model_statuses and model_statuses <= {"no_complete_cases", "metric_unavailable"}:
                        status = "unavailable_no_complete_cases"
                        reason = "complete official matrices exist, but the configured predictors yield no node-induced complete cases; coefficient rows are diagnostic only"
                    elif result_n and complete_n:
                        status = "computed_complete_matrix"
                    elif observed_n and not complete_n:
                        status = "unavailable_incomplete_official_matrix"
                        reason = "official source publishes a leading association list, not the complete dyad matrix required by MRQAP"
                    else:
                        status = "unavailable_no_official_pair_data"
                        reason = jp_source_reason or "no official character co-vote pair matrix is present for this round"
                    source_scope = "explicit_complete_undirected_matrix_required"
                else:
                    effective = sum(int(float(row.get("effective_pair_n") or 0)) for row in result_rows)
                    if result_n and effective:
                        status = "computed_complete_matrix_sensitivity"
                    elif observed_n and not complete_n:
                        status = "unavailable_incomplete_official_matrix"
                        reason = "sensitivity configuration requires complete-matrix metrics; published leading lists do not identify omitted pairs"
                    elif not observed_n:
                        status = "unavailable_no_official_pair_data"
                        reason = "no official character co-vote pair table is present for this round"
                    else:
                        status = "unavailable_no_eligible_complete_pairs"
                        reason = "pair rows exist, but no complete-matrix pairs satisfy the configured metric and scope requirements"
                    source_scope = "complete_matrix_sensitivity_only"
            rows.append({
                "analysis": analysis, "region": region, "round": label,
                "comparison_round": comparison, "status": status,
                "observed_pair_rows": observed_n, "complete_pair_rows": complete_n,
                "matrix_source_pair_rows": matrix_source_n,
                "matrix_source_complete_pair_rows": matrix_source_complete_n,
                "result_rows": result_n, "result_path": result_path,
                "reason": reason, "source_scope": source_scope,
            })
    return rows


def write_coverage(rows: list[dict[str, Any]], *, csv_path: Path, json_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary: dict[str, dict[str, int]] = {}
    for analysis in ANALYSES:
        summary[analysis] = dict(sorted(Counter(row["status"] for row in rows if row["analysis"] == analysis).items()))
    payload = {
        "schema_version": 1,
        "scope": {"cn_rounds": "CN1-CN11", "jp_rounds": "JP3-JP22", "round_count": 31},
        "source_policy": "Only official observed pair rows are analyzed. Unpublished pairs remain unknown and are never converted to zero.",
        "source_audit": [
            "vote_explorer/data/analysis_data_manifest.json",
            "metadata/jp_official_legacy_component_status.json",
            "metadata/jp_official_legacy_coverage.json",
            "analysis_results/covote_metrics_audit.json",
        ],
        "rounds": [label for _, label in round_labels()],
        "analysis_status_counts": summary,
        "coverage": rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--covote", type=Path, default=DEFAULT_COVOTE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    args = parser.parse_args(argv)
    rows = build_coverage(root=args.root, covote_path=args.covote)
    write_coverage(rows, csv_path=args.output, json_path=args.json)
    print(json.dumps({"rounds": 31, "coverage_rows": len(rows), "output": str(args.output), "json": str(args.json)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
