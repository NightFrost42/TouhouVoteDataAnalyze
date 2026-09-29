#!/usr/bin/env python3
"""Exploratory threshold sensitivity for observed character-pair networks."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from scripts_pipeline import network_hypothesis_tests as inference
except ImportError:  # direct execution from scripts_pipeline/
    import network_hypothesis_tests as inference


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "metadata" / "network_sensitivity_scan.json"
DEFAULT_CP = ROOT / "vote_explorer" / "data" / "analysis_vote_combinations_all.csv"
DEFAULT_OUTPUT = ROOT / "analysis_results" / "network_inference" / "sensitivity_scan.csv"
FIELDS = [
    "analysis_name", "region", "round", "metric", "threshold_type", "threshold",
    "hypothesis", "observation_n", "control_n", "effect_size", "raw_p",
    "adjusted_p", "pair_coverage", "status", "warning", "node_set",
    "data_completeness", "adjustment_method", "adjustment_family",
    "eligible_pair_n", "effective_pair_n", "valid_permutations", "inference_status",
]
SUMMARY_FIELDS = [
    "region", "round", "metric", "threshold_type", "hypothesis", "node_set",
    "data_completeness", "adjustment_method", "tested_thresholds",
    "direction_stability", "significance_stability", "interpretation",
]
COMPLETE_METRICS = frozenset({"share", "lift", "cosine", "jaccard", "phi", "pmi", "npmi"})
THRESHOLD_COLUMNS = {"intersection_count": "intersection_count", "lift": "lift", "cp_vote_count": "cp_vote_count"}


def bh_adjust(p_values: Mapping[Any, float | None]) -> dict[Any, float | None]:
    """Benjamini-Hochberg step-up adjusted p values, including missing keys."""
    valid = sorted(
        ((key, float(value)) for key, value in p_values.items() if value is not None),
        key=lambda item: (item[1], str(item[0])),
    )
    adjusted: dict[Any, float | None] = {key: None for key in p_values}
    running = 1.0
    for rank in range(len(valid), 0, -1):
        key, value = valid[rank - 1]
        running = min(running, value * len(valid) / rank)
        adjusted[key] = running
    return adjusted


def _read_selected(path: Path, regions: set[str], rounds: set[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [
            row for row in csv.DictReader(handle)
            if (not regions or row.get("region") in regions)
            and (not rounds or row.get("round") in rounds)
            and row.get("pair_category", "character") == "character"
        ]


def _cp_counts(rows: Sequence[Mapping[str, str]]) -> dict[tuple[str, str, str], float]:
    counts: dict[tuple[str, str, str], float] = {}
    for row in rows:
        if row.get("data_source") != "official_cp" or str(row.get("name_c") or "").strip():
            continue
        key = inference.pair_key_from_values(row.get("name_a"), row.get("name_b"))
        value = inference._numeric(row.get("cp_vote_count") or row.get("comparison_count"))
        if key and value is not None:
            identity = (str(row.get("region", "")), str(row.get("round", "")), key)
            counts[identity] = max(value, counts.get(identity, -math.inf))
    return counts


def _validate(config: Mapping[str, Any], covote_rows: Sequence[Mapping[str, str]],
              feature_rows: Sequence[Mapping[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    hypotheses, metrics = inference._validate_config(
        config, inference._config_allowed_names(feature_rows, covote_rows)
    )
    if not config.get("scans") or not isinstance(config["scans"], list):
        raise ValueError("scans must be a non-empty list")
    for scan in config["scans"]:
        if scan.get("threshold_type") not in THRESHOLD_COLUMNS:
            raise ValueError(f"unsupported threshold_type {scan.get('threshold_type')!r}")
        if not isinstance(scan.get("thresholds"), list) or not scan["thresholds"]:
            raise ValueError("each scan needs thresholds")
        if any(inference._numeric(value) is None or float(value) < 0 for value in scan["thresholds"]):
            raise ValueError("thresholds must be finite and non-negative")
    node_sets = config.get("node_sets", [{"name": "all_observed"}])
    conditions = config.get("data_completeness", ["complete_matrix"])
    methods = config.get("adjustments", ["holm"])
    if not node_sets or not conditions or not methods:
        raise ValueError("node_sets, data_completeness and adjustments must be non-empty")
    for node_set in node_sets:
        if node_set.get("name") not in {"all_observed", "top_ranked", "explicit"}:
            raise ValueError(f"unsupported node set {node_set!r}")
        if node_set["name"] == "top_ranked" and (inference._numeric(node_set.get("rank_max")) is None or float(node_set["rank_max"]) < 1):
            raise ValueError("top_ranked needs positive rank_max")
        if node_set["name"] == "explicit" and not node_set.get("ids"):
            raise ValueError("explicit node set needs ids")
    for condition in conditions:
        if condition not in {"complete_matrix", "observed_only", "partial_observed_pairs"}:
            raise ValueError(f"unsupported data completeness {condition!r}")
    for method in methods:
        if method not in {"holm", "bh", "none"}:
            raise ValueError(f"unsupported adjustment {method!r}")
    return hypotheses, metrics


def _node_eligible(record: inference.PairRecord, node_set: Mapping[str, Any]) -> bool:
    kind = node_set["name"]
    if kind == "all_observed":
        return True
    if kind == "top_ranked":
        maximum = float(node_set["rank_max"])
        ranks = [inference._numeric(record.row.get(f"rank_{side}")) for side in ("a", "b")]
        return all(rank is not None and rank <= maximum for rank in ranks)
    ids = {inference.normalize_entity(value) for value in node_set["ids"]}
    return all(inference.normalize_entity(inference.endpoint_value(record.row, side)) in ids for side in ("a", "b"))


def _threshold_eligible(record: inference.PairRecord, kind: str, threshold: float,
                        cp_counts: Mapping[tuple[str, str, str], float]) -> bool:
    if kind == "cp_vote_count":
        value = cp_counts.get((record.region, record.round_value, record.pair_key))
    else:
        value = inference._numeric(record.row.get(THRESHOLD_COLUMNS[kind]))
        if kind == "lift" and not inference._is_complete(record):
            # JP leading-list rate-ratio lift is a different estimand.
            value = None
    return value is not None and value >= threshold


def scan_analysis(config: Mapping[str, Any], *, covote_rows: Sequence[Mapping[str, str]],
                  feature_rows: Sequence[Mapping[str, str]],
                  cp_rows: Sequence[Mapping[str, str]] = ()) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    hypotheses, metrics = _validate(config, covote_rows, feature_rows)
    records, _ = inference.build_records(covote_rows, feature_rows)
    cp_counts = _cp_counts(cp_rows)
    parameters = config.get("parameters", {})
    permutations = int(parameters.get("permutations", 199))
    min_group_n = int(parameters.get("min_group_n", 10))
    alpha = float(parameters.get("alpha", 0.05))
    seed = int(parameters.get("random_seed", 0))
    tail = str(parameters.get("tail", "two-sided"))
    if permutations < 0 or min_group_n < 1 or not 0 < alpha < 1 or tail not in {"two-sided", "greater", "less"}:
        raise ValueError("invalid scan parameters")
    methods = list(dict.fromkeys(config.get("adjustments", ["holm"])))
    by_stratum: dict[tuple[str, str], list[inference.PairRecord]] = defaultdict(list)
    for record in records:
        by_stratum[(record.region, record.round_value)].append(record)
    output: list[dict[str, Any]] = []
    for (region, round_value), stratum in sorted(by_stratum.items()):
        for node_set in config.get("node_sets", [{"name": "all_observed"}]):
            node_name = node_set["name"] if node_set["name"] != "top_ranked" else f"top_ranked_{node_set['rank_max']}"
            node_records = [record for record in stratum if _node_eligible(record, node_set)]
            for condition in config.get("data_completeness", ["complete_matrix"]):
                base = [
                    record for record in node_records
                    if condition == "observed_only"
                    or inference._is_complete(record) == (condition == "complete_matrix")
                ]
                for scan in config["scans"]:
                    kind = scan["threshold_type"]
                    for threshold in scan["thresholds"]:
                        limit = float(threshold)
                        selected = [record for record in base if _threshold_eligible(record, kind, limit, cp_counts)]
                        family = f"sensitivity:{region}:{round_value}:{node_name}:{condition}:{kind}:{limit:g}"
                        family_rows: list[dict[str, Any]] = []
                        for metric in metrics:
                            metric_name = str(metric["name"])
                            requires_complete = metric.get("minimum_scope") in {"complete_matrix", "complete"} or metric["column"] in COMPLETE_METRICS
                            metric_base = [record for record in base if not requires_complete or inference._is_complete(record)]
                            metric_selected = [record for record in selected if not requires_complete or inference._is_complete(record)]
                            eligible_n = sum(inference._metric_value(record, metric) is not None for record in metric_base)
                            for hypothesis in hypotheses:
                                scoped = inference._scope_records(metric_selected, str(hypothesis.get("scope", "all_pairs")))
                                obs, control, _, _ = inference._group_values(
                                    scoped, metric, hypothesis["_observation"], hypothesis["_control"]
                                )
                                effective_n = len(obs) + len(control)
                                delta = inference.cliffs_delta(obs, control)
                                status = inference._status_for_groups("ok", obs, control)
                                if condition != "complete_matrix" and requires_complete and not metric_selected:
                                    status = "metric_requires_complete_matrix"
                                raw_p = None
                                valid = 0
                                if delta is not None and permutations:
                                    raw_p, valid, permutation_status = inference.node_attribute_permutation_p(
                                        scoped, metric, hypothesis["_observation"], hypothesis["_control"], delta,
                                        permutations=permutations,
                                        seed=inference._stable_seed(seed, region, round_value,
                                                                    metric_name, hypothesis["name"]),
                                        tail=tail,
                                    )
                                    if permutation_status != "ok":
                                        status = permutation_status
                                warnings = []
                                if min(len(obs), len(control)) < min_group_n:
                                    warnings.append(f"low_power_heuristic:min_group_n<{min_group_n}")
                                if kind == "cp_vote_count":
                                    warnings.append("official_cp_published_pairs_only;unlisted_unknown")
                                if condition != "complete_matrix" and any(not inference._is_complete(record) for record in selected):
                                    warnings.append("partial_matrix_observed_only")
                                if raw_p is None:
                                    warnings.append("p_unavailable")
                                family_rows.append({
                                    "analysis_name": str(config.get("analysis_name", "character_pair_network_sensitivity")),
                                    "region": region, "round": round_value, "metric": metric_name,
                                    "threshold_type": kind, "threshold": limit, "hypothesis": hypothesis["name"],
                                    "observation_n": len(obs), "control_n": len(control), "effect_size": delta,
                                    "raw_p": raw_p, "adjusted_p": None,
                                    "pair_coverage": effective_n / eligible_n if eligible_n else None,
                                    "status": status, "warning": ";".join(warnings), "node_set": node_name,
                                    "data_completeness": condition, "adjustment_method": "",
                                    "adjustment_family": family, "eligible_pair_n": eligible_n,
                                    "effective_pair_n": effective_n, "valid_permutations": valid,
                                    "inference_status": "exploratory_sensitivity",
                                })
                        p_values = {index: row["raw_p"] for index, row in enumerate(family_rows)}
                        for method in methods:
                            adjusted = (inference.holm_adjust(p_values) if method == "holm" else
                                        bh_adjust(p_values) if method == "bh" else p_values)
                            for index, row in enumerate(family_rows):
                                output.append({**row, "adjustment_method": method, "adjusted_p": adjusted[index]})
    output.sort(key=lambda row: (row["region"], inference._round_sort_key(row["round"]),
                                 row["node_set"], row["data_completeness"], row["threshold_type"],
                                 row["threshold"], row["metric"], row["hypothesis"], row["adjustment_method"]))
    return output, summarize(output, alpha=alpha)


def summarize(rows: Sequence[Mapping[str, Any]], *, alpha: float = 0.05) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[Mapping[str, Any]]] = defaultdict(list)
    keys = ("region", "round", "metric", "threshold_type", "hypothesis", "node_set",
            "data_completeness", "adjustment_method")
    for row in rows:
        grouped[tuple(str(row[key]) for key in keys)].append(row)
    summary = []
    for key, variants in sorted(grouped.items()):
        effects = [float(row["effect_size"]) for row in variants if row["effect_size"] is not None]
        p_values = [float(row["adjusted_p"]) for row in variants if row["adjusted_p"] is not None]
        if len(effects) < 2 or len(effects) != len(variants):
            direction = "insufficient"
        elif all(value > 0 for value in effects):
            direction = "stable_positive"
        elif all(value < 0 for value in effects):
            direction = "stable_negative"
        elif all(value == 0 for value in effects):
            direction = "stable_zero"
        else:
            direction = "mixed"
        if len(p_values) < 2 or len(p_values) != len(variants):
            significance = "insufficient"
        elif all(value < alpha for value in p_values):
            significance = "consistently_significant"
        elif all(value >= alpha for value in p_values):
            significance = "never_significant"
        else:
            significance = "mixed"
        summary.append({**dict(zip(keys, key)), "tested_thresholds": len(variants),
                        "direction_stability": direction, "significance_stability": significance,
                        "interpretation": "sensitivity_only_not_independent_validation"})
    return summary


def _round_filter_from_scope(scope: Mapping[str, Any]) -> set[str]:
    configured_rounds = scope.get("round", [])
    if configured_rounds in ("all", "all_observed"):
        return set()
    return {str(value) for value in configured_rounds}


def _write_csv(path: Path, fields: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_from_files(config_path: Path = DEFAULT_CONFIG, output_path: Path = DEFAULT_OUTPUT,
                   covote_path: Path = inference.DEFAULT_COVOTE_PATH,
                   feature_path: Path = inference.DEFAULT_FEATURE_PATH,
                   cp_path: Path = DEFAULT_CP) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    config = inference.load_config(config_path)
    scope = config.get("scope", {})
    regions = set(scope.get("region", []))
    rounds = _round_filter_from_scope(scope)
    covote_rows = _read_selected(covote_path, regions, rounds)
    feature_rows = _read_selected(feature_path, regions, rounds)
    cp_rows = _read_selected(cp_path, regions, rounds) if any(
        scan.get("threshold_type") == "cp_vote_count" for scan in config.get("scans", [])
    ) else []
    rows, summary = scan_analysis(config, covote_rows=covote_rows, feature_rows=feature_rows,
                                  cp_rows=cp_rows)
    _write_csv(output_path, FIELDS, rows)
    summary_path = output_path.with_name("sensitivity_summary.csv")
    _write_csv(summary_path, SUMMARY_FIELDS, summary)
    report = [
        "# Network sensitivity scan", "",
        "Threshold variants are exploratory sensitivity analyses of the same observed data, not independent validation.",
        "Adjusted p values are calculated within each region, round, node set, completeness condition and threshold scenario; they are never added to the primary hypothesis family.",
        "Effect size is Cliff's delta. Pair coverage is classified usable pairs divided by observed pairs with a finite metric before the threshold is applied.",
        "A low-power warning is a sample-size heuristic, not a formal power calculation. Missing and unpublished pairs are never treated as zero.",
        "For lift thresholds, only complete-matrix independence lift is eligible. CP thresholds use only published official two-person combinations.",
        "", "## Stability", "",
        "Direction stability and significance stability are separate: stable direction alone does not establish significance.",
        "", "| Region | Round | Metric | Scan | Hypothesis | Node set | Completeness | Correction | Direction | Significance |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in summary:
        report.append("| " + " | ".join(str(row[key]) for key in (
            "region", "round", "metric", "threshold_type", "hypothesis", "node_set", "data_completeness",
            "adjustment_method", "direction_stability", "significance_stability"
        )) + " |")
    output_path.with_name("sensitivity_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return rows, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--covote", type=Path, default=inference.DEFAULT_COVOTE_PATH)
    parser.add_argument("--features", type=Path, default=inference.DEFAULT_FEATURE_PATH)
    parser.add_argument("--cp", type=Path, default=DEFAULT_CP)
    args = parser.parse_args(argv)
    rows, summary = run_from_files(args.config, args.output, args.covote, args.features, args.cp)
    print(f"sensitivity rows: {len(rows)}; stability groups: {len(summary)}; output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
