#!/usr/bin/env python3
"""Non-parametric hypothesis tests for observed character-pair networks.

The input network is an observed edge list, not an inferred complete graph.
Consequently this module never materialises an absent pair as a zero.  Group
membership comes from configurable expressions over the audited structural
pair-feature table.  Monte Carlo nulls permute node attributes while keeping
the observed edges and their metric values fixed.

Only the Python standard library is used.  The implementation intentionally
computes Mann--Whitney U and Cliff's delta from pairwise comparisons rather
than using an asymptotic independent-sample p-value.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import random
import re
import statistics
import unicodedata
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    from scripts_pipeline.model_run_manifest import write_model_run_manifest
except ImportError:  # direct execution from scripts_pipeline/
    from model_run_manifest import write_model_run_manifest


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "metadata" / "network_hypothesis_tests.json"
DEFAULT_COVOTE_PATH = ROOT / "vote_explorer" / "data" / "analysis_covote_pairs_all.csv"
DEFAULT_FEATURE_PATH = ROOT / "vote_explorer" / "data" / "analysis_character_pair_structure_features_all.csv"
DEFAULT_METADATA_PATH = ROOT / "metadata" / "character_structure_metadata.csv"
DEFAULT_OUTPUT_PATH = ROOT / "analysis_results" / "network_inference" / "hypothesis_tests.csv"
DEFAULT_MANIFEST_PATH = ROOT / "analysis_results" / "network_inference" / "hypothesis_tests_manifest.json"

OUTPUT_FIELDS = [
    "analysis_name",
    "region",
    "round",
    "metric",
    "hypothesis",
    "observation_n",
    "control_n",
    "observation_median",
    "control_median",
    "u_statistic",
    "cliffs_delta",
    "ci_low",
    "ci_high",
    "raw_p",
    "adjusted_p",
    "adjustment_family",
    "permutations",
    "valid_permutations",
    "random_seed",
    "inference_status",
    "data_status",
    "metric_scope",
]

UNKNOWN_TOKENS = frozenset(
    {"", "unknown", "unk", "na", "n/a", "null", "none", "未确认", "未知", "不详", "未提供"}
)
SET_ATTRIBUTES = frozenset({"region", "community"})
NODE_ATTRIBUTE_ALIASES = {
    "first_appearance_work": "reference_first_appearance_work",
    "character_type": "reference_character_type",
    "source_group": "reference_source_group",
}

# A pair feature is derived from these endpoint attributes.  Keeping this map
# explicit prevents arbitrary CSV columns from becoming node-level covariates.
PAIR_FEATURE_BASES = {
    "crosswalk_first_appearance_work_id": "crosswalk_first_appearance_work_id",
    "reference_first_appearance_work": "reference_first_appearance_work",
    "reference_identity_or_title": "reference_identity_or_title",
    "reference_character_type": "reference_character_type",
    "reference_source_group": "reference_source_group",
    "stage": "stage",
    "boss_identity": "boss_identity",
    "region": "region",
    "region_type": "region_type",
    "community": "community",
    "community_type": "community_type",
    **NODE_ATTRIBUTE_ALIASES,
}


class HypothesisConfigError(ValueError):
    """Raised for an invalid or unsafe hypothesis expression/configuration."""


class ExpressionConfigError(HypothesisConfigError):
    """Raised when an expression contains unsupported syntax."""


@dataclass(frozen=True)
class CompiledExpression:
    source: str
    tree: ast.Expression
    names: frozenset[str]


@dataclass(frozen=True)
class PairRecord:
    region: str
    round_value: str
    pair_key: str
    row: Mapping[str, str]
    feature: Mapping[str, str] | None


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _is_unknown(value: Any) -> bool:
    return _clean(value).casefold() in UNKNOWN_TOKENS


def normalize_entity(value: Any) -> str:
    """Match the repository's unordered character-pair identity policy."""
    text = unicodedata.normalize("NFKC", _clean(value)).casefold()
    return re.sub(r"[\s・･·\-—_]+", "", text)


def pair_key_from_values(value_a: Any, value_b: Any) -> str:
    values = [normalize_entity(value_a), normalize_entity(value_b)]
    if not all(values) or values[0] == values[1]:
        return ""
    return "|".join(sorted(values))


def endpoint_value(row: Mapping[str, Any], side: str) -> str:
    for field in (f"canonical_{side}", f"name_{side}_cn", f"name_{side}"):
        value = _clean(row.get(field, ""))
        if value:
            return value
    return ""


def row_pair_key(row: Mapping[str, Any]) -> str:
    return pair_key_from_values(endpoint_value(row, "a"), endpoint_value(row, "b"))


def _numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        text = _clean(value)
        if not text or _is_unknown(text):
            return None
        try:
            result = float(text)
        except (TypeError, ValueError):
            return None
    return result if math.isfinite(result) else None


def _boolish(value: Any) -> int | None | Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)) and value in (0, 1):
        return int(value)
    text = _clean(value).casefold()
    if text in {"true", "yes", "y", "1"}:
        return 1
    if text in {"false", "no", "n", "0"}:
        return 0
    if text in UNKNOWN_TOKENS:
        return None
    return value


def _comparison_key(value: Any) -> str:
    return normalize_entity(value)


def _split_set(value: Any) -> set[str] | None:
    if _is_unknown(value):
        return None
    values = {_comparison_key(part) for part in _clean(value).split(";") if _clean(part)}
    return values or None


def same_structural_value(value_a: Any, value_b: Any, base_attribute: str) -> int | None:
    if base_attribute in SET_ATTRIBUTES:
        left, right = _split_set(value_a), _split_set(value_b)
        if left is None or right is None:
            return None
        return int(left == right)
    if _is_unknown(value_a) or _is_unknown(value_b):
        return None
    return int(_comparison_key(value_a) == _comparison_key(value_b))


def shared_structural_value(value_a: Any, value_b: Any, base_attribute: str) -> int | None:
    left, right = _split_set(value_a), _split_set(value_b)
    if left is None or right is None:
        return None
    return int(bool(left & right))


_ALLOWED_AST_NODES = {
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.UnaryOp,
    ast.Not,
    ast.Compare,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Set,
    ast.Tuple,
    ast.List,
    ast.Eq,
    ast.NotEq,
    ast.In,
    ast.NotIn,
}


def _normalise_expression_source(source: str) -> str:
    if not isinstance(source, str) or not source.strip():
        raise ExpressionConfigError("expression must be a non-empty string")
    return source.strip()


def compile_expression(source: str, allowed_names: Iterable[str] | None = None) -> CompiledExpression:
    normalised = _normalise_expression_source(source)
    try:
        tree = ast.parse(normalised, mode="eval")
    except SyntaxError as exc:
        raise ExpressionConfigError(f"invalid expression {source!r}: {exc.msg}") from exc
    names: set[str] = set()
    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_AST_NODES:
            raise ExpressionConfigError(
                f"unsupported syntax {type(node).__name__} in expression {source!r}"
            )
        if isinstance(node, ast.Name) and node.id not in {"True", "False", "true", "false"}:
            names.add(node.id)
    if allowed_names is not None:
        allowed = set(allowed_names)
        unknown = sorted(names - allowed)
        if unknown:
            raise ExpressionConfigError(
                f"unknown expression field(s) {unknown!r} in {source!r}"
            )
    return CompiledExpression(source=source, tree=tree, names=frozenset(names))


def _eval_ast(node: ast.AST, context: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body, context)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in {"True", "true"}:
            return True
        if node.id in {"False", "false"}:
            return False
        return context.get(node.id)
    if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
        return [_eval_ast(item, context) for item in node.elts]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        value = _eval_ast(node.operand, context)
        return None if value is None else not bool(value)
    if isinstance(node, ast.BoolOp):
        values = [_eval_ast(item, context) for item in node.values]
        # Strict unknown propagation is intentional: a missing structural value
        # must never become membership in either comparison group.
        if any(value is None for value in values):
            return None
        if isinstance(node.op, ast.And):
            return all(bool(value) for value in values)
        return any(bool(value) for value in values)
    if isinstance(node, ast.Compare):
        left = _eval_ast(node.left, context)
        if left is None:
            return None
        for operator, comparator in zip(node.ops, node.comparators):
            right = _eval_ast(comparator, context)
            if right is None:
                return None
            if isinstance(operator, ast.Eq):
                result = left == right
            elif isinstance(operator, ast.NotEq):
                result = left != right
            elif isinstance(operator, ast.In):
                result = left in right
            elif isinstance(operator, ast.NotIn):
                result = left not in right
            else:  # guarded by compile_expression
                raise ExpressionConfigError(f"unsupported comparison {type(operator).__name__}")
            if not result:
                return False
            left = right
        return True
    raise ExpressionConfigError(f"unsupported AST node {type(node).__name__}")


def evaluate_expression(expression: CompiledExpression | str, context: Mapping[str, Any]) -> bool | None:
    compiled = expression if isinstance(expression, CompiledExpression) else compile_expression(expression)
    value = _eval_ast(compiled.tree, context)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ExpressionConfigError(
            f"expression {compiled.source!r} must evaluate to a boolean, got {value!r}"
        )
    return value


def context_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for key, value in row.items():
        parsed = _boolish(value) if key.startswith(("same_", "shared_", "complete_")) else value
        context[key] = parsed
    return context


def mann_whitney_u(observation: Sequence[float], control: Sequence[float]) -> float | None:
    """Return U for observation relative to control, counting ties as 0.5."""
    if not observation or not control:
        return None
    control_sorted = sorted(control)
    less = sum(bisect_left(control_sorted, value) for value in observation)
    greater = sum(len(control_sorted) - bisect_right(control_sorted, value) for value in observation)
    return less + 0.5 * (len(observation) * len(control) - less - greater)


def cliffs_delta(observation: Sequence[float], control: Sequence[float]) -> float | None:
    u = mann_whitney_u(observation, control)
    if u is None:
        return None
    return 2.0 * u / (len(observation) * len(control)) - 1.0


def _cliffs_delta_sorted(observation: Sequence[float], control_sorted: Sequence[float]) -> float | None:
    if not observation or not control_sorted:
        return None
    less = sum(bisect_left(control_sorted, value) for value in observation)
    greater = sum(len(control_sorted) - bisect_right(control_sorted, value) for value in observation)
    return (less - greater) / (len(observation) * len(control_sorted))


def bootstrap_cliffs_delta_ci(
    observation: Sequence[float],
    control: Sequence[float],
    *,
    repetitions: int = 1000,
    confidence_level: float = 0.95,
    seed: int = 0,
) -> tuple[float | None, float | None]:
    """Percentile bootstrap interval for Cliff's delta.

    Resampling is independent within each group.  A zero-width interval is a
    valid result for an all-tied sample; it is not converted to missing.
    """
    if not observation or not control:
        return None, None
    if repetitions < 1:
        raise ValueError("bootstrap repetitions must be positive")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between 0 and 1")
    rng = random.Random(seed)
    left_tail = (1.0 - confidence_level) / 2.0
    estimates: list[float] = []
    n_observation, n_control = len(observation), len(control)
    for _ in range(repetitions):
        sample_observation = [observation[rng.randrange(n_observation)] for _ in range(n_observation)]
        sample_control = [control[rng.randrange(n_control)] for _ in range(n_control)]
        estimate = _cliffs_delta_sorted(sample_observation, sorted(sample_control))
        if estimate is not None and math.isfinite(estimate):
            estimates.append(estimate)
    if not estimates:
        return None, None
    estimates.sort()
    return (
        _quantile_sorted(estimates, left_tail),
        _quantile_sorted(estimates, 1.0 - left_tail),
    )


def _quantile_sorted(values: Sequence[float], probability: float) -> float:
    if len(values) == 1:
        return float(values[0])
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(values[lower])
    weight = position - lower
    return float(values[lower] * (1.0 - weight) + values[upper] * weight)


def holm_adjust(p_values: Mapping[Any, float | None]) -> dict[Any, float | None]:
    """Holm step-down adjusted p values, preserving the input keys."""
    valid = [(key, float(value)) for key, value in p_values.items() if value is not None]
    valid.sort(key=lambda item: (item[1], str(item[0])))
    adjusted: dict[Any, float | None] = {key: None for key in p_values}
    running = 0.0
    total = len(valid)
    for index, (key, p_value) in enumerate(valid):
        candidate = min(1.0, (total - index) * p_value)
        running = max(running, candidate)
        adjusted[key] = running
    return adjusted


def _stable_seed(base_seed: int, *parts: Any) -> int:
    payload = "|".join([str(base_seed), *(str(part) for part in parts)]).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _feature_pair_key(row: Mapping[str, Any]) -> str:
    existing = _clean(row.get("canonical_pair_key", ""))
    if existing:
        return existing
    return row_pair_key(row)


def build_records(
    covote_rows: Sequence[Mapping[str, str]],
    feature_rows: Sequence[Mapping[str, str]],
) -> tuple[list[PairRecord], dict[str, int]]:
    feature_by_key: dict[tuple[str, str, str], Mapping[str, str]] = {}
    duplicate_features = 0
    for row in sorted(feature_rows, key=lambda item: (_clean(item.get("region")), _clean(item.get("round")), _clean(item.get("source_path")))):
        if _clean(row.get("pair_category", "character")) != "character":
            continue
        key = (_clean(row.get("region")), _clean(row.get("round")), _feature_pair_key(row))
        if not key[0] or not key[1] or not key[2]:
            continue
        if key in feature_by_key:
            duplicate_features += 1
        else:
            feature_by_key[key] = row

    records: list[PairRecord] = []
    missing_features = 0
    duplicate_covote_keys = 0
    seen: set[tuple[str, str, str]] = set()
    for row in sorted(covote_rows, key=lambda item: (_clean(item.get("region")), _clean(item.get("round")), _clean(item.get("pair_category")), _clean(item.get("source_path")), row_pair_key(item))):
        if _clean(row.get("pair_category")) != "character":
            continue
        region, round_value, pair_key = _clean(row.get("region")), _clean(row.get("round")), row_pair_key(row)
        if not region or not round_value or not pair_key:
            continue
        unique_key = (region, round_value, pair_key)
        if unique_key in seen:
            duplicate_covote_keys += 1
            continue
        seen.add(unique_key)
        feature = feature_by_key.get(unique_key)
        if feature is None:
            missing_features += 1
        records.append(PairRecord(region, round_value, pair_key, row, feature))
    return records, {
        "duplicate_feature_rows": duplicate_features,
        "duplicate_covote_rows": duplicate_covote_keys,
        "missing_feature_rows": missing_features,
    }


def _is_complete(record: PairRecord) -> bool:
    return _clean(record.row.get("complete_pair_matrix", "")).casefold() == "true"


def _scope_records(records: Sequence[PairRecord], scope: str) -> list[PairRecord]:
    if scope in {"all_pairs", "any_observed", ""}:
        return list(records)
    if scope == "complete_matrix":
        return [record for record in records if _is_complete(record)]
    if scope in {"partial_observed_pairs", "partial_matrix"}:
        return [record for record in records if not _is_complete(record)]
    raise HypothesisConfigError(f"unsupported scope {scope!r}")


def _metric_records(records: Sequence[PairRecord], metric: Mapping[str, Any]) -> tuple[list[PairRecord], str]:
    minimum_scope = str(metric.get("minimum_scope", "any_observed"))
    if minimum_scope in {"complete_matrix", "complete"}:
        eligible = [record for record in records if _is_complete(record)]
        return eligible, "complete_matrix"
    if minimum_scope in {"partial_observed_pairs", "partial_matrix"}:
        return [record for record in records if not _is_complete(record)], "partial_matrix_observed_only"
    statuses = {_is_complete(record) for record in records}
    if statuses == {True}:
        return list(records), "complete_matrix"
    if statuses == {False}:
        return list(records), "partial_matrix_observed_only"
    if statuses == {True, False}:
        return list(records), "mixed_matrix_scope"
    return list(records), "no_observed_pairs"


def _metric_value(record: PairRecord, metric: Mapping[str, Any]) -> float | None:
    column = str(metric.get("column") or metric.get("name") or "")
    return _numeric(record.row.get(column, ""))


def _group_values(
    records: Sequence[PairRecord],
    metric: Mapping[str, Any],
    observation: CompiledExpression,
    control: CompiledExpression,
) -> tuple[list[float], list[float], list[PairRecord], dict[str, int]]:
    values_observation: list[float] = []
    values_control: list[float] = []
    classified: list[PairRecord] = []
    counts = Counter(unknown=0, neither=0, overlap=0, missing_metric=0)
    for record in records:
        value = _metric_value(record, metric)
        if value is None:
            counts["missing_metric"] += 1
            continue
        context = context_from_row(record.feature or {})
        context.update(context_from_row(record.row))
        in_observation = evaluate_expression(observation, context)
        in_control = evaluate_expression(control, context)
        if in_observation is None or in_control is None:
            counts["unknown"] += 1
            continue
        if in_observation and in_control:
            counts["overlap"] += 1
            raise HypothesisConfigError(
                f"observation/control expressions overlap for pair {record.pair_key!r}"
            )
        if not in_observation and not in_control:
            counts["neither"] += 1
            continue
        classified.append(record)
        if in_observation:
            values_observation.append(value)
        else:
            values_control.append(value)
    return values_observation, values_control, classified, dict(counts)


def _base_attribute_for_name(name: str) -> tuple[str, str] | None:
    if name.startswith("same_"):
        suffix = name[5:]
        base = PAIR_FEATURE_BASES.get(suffix)
        return ("same", base) if base else None
    if name.startswith("shared_"):
        suffix = name[7:]
        base = PAIR_FEATURE_BASES.get(suffix)
        return ("shared", base) if base else None
    if name.startswith(("a_", "b_")):
        base = name[2:]
        if base in PAIR_FEATURE_BASES.values():
            return (name[0], base)
    return None


def _node_id_from_feature(feature: Mapping[str, Any], side: str) -> str:
    value = endpoint_value(feature, side)
    return normalize_entity(value)


def _node_attribute_table(
    records: Sequence[PairRecord],
    bases: Sequence[str],
) -> tuple[dict[str, tuple[str, ...]], set[str], dict[str, int]]:
    values: dict[str, list[str | None]] = {}
    conflicts: set[str] = set()
    for record in records:
        if record.feature is None:
            continue
        for side in ("a", "b"):
            node = _node_id_from_feature(record.feature, side)
            if not node:
                continue
            candidate = tuple(_clean(record.feature.get(f"{side}_{base}", "")) or None for base in bases)
            if any(value is None or _is_unknown(value) for value in candidate):
                continue
            previous = values.get(node)
            if previous is None:
                values[node] = list(candidate)
            elif any(_comparison_key(left) != _comparison_key(right) for left, right in zip(previous, candidate)):
                conflicts.add(node)
    table = {
        node: tuple(str(value) for value in value_list)
        for node, value_list in values.items()
        if node not in conflicts
    }
    return table, set(table), {"ambiguous_nodes": len(conflicts), "known_nodes": len(table)}


def _permuted_context(
    record: PairRecord,
    assignment: Mapping[str, tuple[str, ...]],
    bases: Sequence[str],
    referenced_names: Iterable[str],
) -> dict[str, Any] | None:
    if record.feature is None:
        return None
    context = context_from_row(record.feature)
    context.update(context_from_row(record.row))
    endpoint_values: dict[str, dict[str, Any]] = {"a": {}, "b": {}}
    for side in ("a", "b"):
        node = _node_id_from_feature(record.feature, side)
        if node not in assignment:
            return None
        values = assignment[node]
        endpoint_values[side] = dict(zip(bases, values))
        for base, value in endpoint_values[side].items():
            context[f"{side}_{base}"] = value
    for name in referenced_names:
        descriptor = _base_attribute_for_name(name)
        if not descriptor:
            continue
        kind, base = descriptor
        if kind in {"same", "shared"}:
            if kind == "same":
                context[name] = same_structural_value(endpoint_values["a"][base], endpoint_values["b"][base], base)
            else:
                context[name] = shared_structural_value(endpoint_values["a"][base], endpoint_values["b"][base], base)
    return context


def node_attribute_permutation_p(
    records: Sequence[PairRecord],
    metric: Mapping[str, Any],
    observation: CompiledExpression,
    control: CompiledExpression,
    observed_delta: float,
    *,
    permutations: int,
    seed: int,
    tail: str,
) -> tuple[float | None, int, str]:
    names = observation.names | control.names
    descriptors = [_base_attribute_for_name(name) for name in names]
    if any(descriptor is None for descriptor in descriptors):
        return None, 0, "node_permutation_requires_structural_attribute_expression"
    bases = sorted({descriptor[1] for descriptor in descriptors if descriptor and descriptor[0] in {"same", "shared"}})
    if not bases:
        return None, 0, "node_permutation_requires_pair_structural_attribute"
    table, nodes, table_counts = _node_attribute_table(records, bases)
    if len(nodes) < 2:
        return None, 0, "insufficient_known_nodes_for_node_permutation"
    usable_records = [
        record
        for record in records
        if _metric_value(record, metric) is not None
        and record.feature is not None
        and _node_id_from_feature(record.feature, "a") in nodes
        and _node_id_from_feature(record.feature, "b") in nodes
    ]
    if not usable_records:
        return None, 0, "no_pairs_with_known_permutation_attributes"
    rng = random.Random(seed)
    ordered_nodes = sorted(nodes)
    values = [table[node] for node in ordered_nodes]
    extreme = 0
    valid = 0
    for _ in range(permutations):
        shuffled = list(values)
        rng.shuffle(shuffled)
        assignment = dict(zip(ordered_nodes, shuffled))
        perm_observation: list[float] = []
        perm_control: list[float] = []
        for record in usable_records:
            context = _permuted_context(record, assignment, bases, names)
            if context is None:
                continue
            in_observation = evaluate_expression(observation, context)
            in_control = evaluate_expression(control, context)
            if in_observation is None or in_control is None or (in_observation and in_control):
                continue
            value = _metric_value(record, metric)
            assert value is not None
            if in_observation:
                perm_observation.append(value)
            elif in_control:
                perm_control.append(value)
        perm_delta = cliffs_delta(perm_observation, perm_control)
        if perm_delta is None:
            continue
        valid += 1
        if tail == "greater":
            extreme += int(perm_delta >= observed_delta - 1e-15)
        elif tail == "less":
            extreme += int(perm_delta <= observed_delta + 1e-15)
        else:
            extreme += int(abs(perm_delta) >= abs(observed_delta) - 1e-15)
    if not valid:
        return None, 0, "no_valid_node_permutations"
    return (extreme + 1) / (valid + 1), valid, "ok"


def _status_for_groups(
    base_status: str,
    observation: Sequence[float],
    control: Sequence[float],
) -> str:
    if base_status.startswith("metric_requires_") or base_status == "no_observed_pairs":
        return base_status
    if not observation and not control:
        return "both_groups_empty_or_unknown"
    if not observation:
        return "empty_observation_group"
    if not control:
        return "empty_control_group"
    return base_status


def _adjustment_family(
    config: Mapping[str, Any], region: str, round_value: str, metric: str, hypothesis: str
) -> str:
    rule = str(config.get("parameters", {}).get("adjustment_family", "region_round_metric"))
    if rule == "region_round":
        return f"{region}:{round_value}"
    if rule == "metric":
        return metric
    if rule == "all":
        return "all_tests"
    if rule == "hypothesis":
        return hypothesis
    return f"{region}:{round_value}:{metric}"


def _config_allowed_names(feature_rows: Sequence[Mapping[str, str]], covote_rows: Sequence[Mapping[str, str]]) -> set[str]:
    names: set[str] = set()
    for row in (*feature_rows[:1], *covote_rows[:1]):
        names.update(row.keys())
    names.update({"True", "False"})
    return names


def _validate_config(config: Mapping[str, Any], allowed_names: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    hypotheses = config.get("hypotheses")
    metrics = config.get("metrics")
    if not isinstance(hypotheses, list) or not hypotheses:
        raise HypothesisConfigError("config.hypotheses must be a non-empty list")
    if not isinstance(metrics, list) or not metrics:
        raise HypothesisConfigError("config.metrics must be a non-empty list")
    compiled_hypotheses: list[dict[str, Any]] = []
    for item in hypotheses:
        if not isinstance(item, Mapping):
            raise HypothesisConfigError("each hypothesis must be an object")
        name = _clean(item.get("name"))
        if not name:
            raise HypothesisConfigError("hypothesis.name must be non-empty")
        observation = compile_expression(str(item.get("observation", "")), allowed_names)
        control = compile_expression(str(item.get("control", "")), allowed_names)
        status = str(item.get("inference_status", "exploratory"))
        if status not in {"exploratory", "confirmatory"}:
            raise HypothesisConfigError(f"unsupported inference_status {status!r}")
        compiled_hypotheses.append({**dict(item), "name": name, "_observation": observation, "_control": control, "inference_status": status})
    validated_metrics: list[dict[str, Any]] = []
    for item in metrics:
        if not isinstance(item, Mapping):
            raise HypothesisConfigError("each metric must be an object")
        name = _clean(item.get("name"))
        column = _clean(item.get("column") or name)
        if not name or not column:
            raise HypothesisConfigError("metric.name and metric.column must be non-empty")
        validated_metrics.append({**dict(item), "name": name, "column": column})
    return compiled_hypotheses, validated_metrics


def run_analysis(
    config: Mapping[str, Any],
    *,
    covote_rows: Sequence[Mapping[str, str]],
    feature_rows: Sequence[Mapping[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    allowed_names = _config_allowed_names(feature_rows, covote_rows)
    hypotheses, metrics = _validate_config(config, allowed_names)
    records, record_counts = build_records(covote_rows, feature_rows)
    parameters = config.get("parameters") if isinstance(config.get("parameters"), Mapping) else {}
    base_seed = int(parameters.get("random_seed", 0))
    permutations = int(parameters.get("permutations", 0))
    bootstrap_repetitions = int(parameters.get("bootstrap_repetitions", 1000))
    confidence_level = float(parameters.get("confidence_level", 0.95))
    tail = str(parameters.get("tail", "two-sided"))
    if tail not in {"two-sided", "greater", "less"}:
        raise HypothesisConfigError(f"unsupported tail {tail!r}")
    if permutations < 0 or bootstrap_repetitions < 1:
        raise HypothesisConfigError("permutations must be >= 0 and bootstrap_repetitions must be positive")

    by_stratum: dict[tuple[str, str], list[PairRecord]] = defaultdict(list)
    for record in records:
        by_stratum[(record.region, record.round_value)].append(record)
    output: list[dict[str, Any]] = []
    integrity = {
        **record_counts,
        "strata": len(by_stratum),
        "rows": len(records),
        "empty_groups": 0,
        "metric_missing_values": 0,
        "valid_permutations": 0,
        "skipped_permutations": 0,
        "data_status_counts": Counter(),
    }

    for (region, round_value), stratum_records in sorted(by_stratum.items()):
        for metric in metrics:
            metric_records, metric_status = _metric_records(stratum_records, metric)
            metric_name = str(metric["name"])
            for hypothesis in hypotheses:
                observation = hypothesis["_observation"]
                control = hypothesis["_control"]
                hypothesis_scope = str(hypothesis.get("scope", "all_pairs"))
                scoped = _scope_records(metric_records, hypothesis_scope)
                obs_values, control_values, _, group_counts = _group_values(scoped, metric, observation, control)
                integrity["metric_missing_values"] += group_counts["missing_metric"]
                if not obs_values or not control_values:
                    integrity["empty_groups"] += 1
                u = mann_whitney_u(obs_values, control_values)
                delta = cliffs_delta(obs_values, control_values)
                family = _adjustment_family(config, region, round_value, metric_name, str(hypothesis["name"]))
                row_status = _status_for_groups(metric_status, obs_values, control_values)
                if metric_status == "complete_matrix" and not metric_records and stratum_records:
                    row_status = "metric_requires_complete_matrix"
                if hypothesis_scope == "complete_matrix" and not scoped and metric_records:
                    row_status = "scope_requires_complete_matrix"
                elif hypothesis_scope in {"partial_observed_pairs", "partial_matrix"} and not scoped and metric_records:
                    row_status = "scope_requires_partial_matrix"
                raw_p: float | None = None
                valid_permutations = 0
                if delta is not None and permutations:
                    permutation_seed = _stable_seed(base_seed, region, round_value, metric_name, hypothesis["name"], "permutation")
                    raw_p, valid_permutations, permutation_status = node_attribute_permutation_p(
                        scoped,
                        metric,
                        observation,
                        control,
                        delta,
                        permutations=permutations,
                        seed=permutation_seed,
                        tail=tail,
                    )
                    if permutation_status != "ok":
                        row_status = f"{row_status};{permutation_status}"
                    integrity["valid_permutations"] += valid_permutations
                    integrity["skipped_permutations"] += permutations - valid_permutations
                ci_low = ci_high = None
                if obs_values and control_values:
                    ci_seed = _stable_seed(base_seed, region, round_value, metric_name, hypothesis["name"], "bootstrap")
                    ci_low, ci_high = bootstrap_cliffs_delta_ci(
                        obs_values,
                        control_values,
                        repetitions=bootstrap_repetitions,
                        confidence_level=confidence_level,
                        seed=ci_seed,
                    )
                if row_status.startswith(("both_groups", "empty_")):
                    integrity["data_status_counts"][row_status] += 1
                else:
                    integrity["data_status_counts"][metric_status] += 1
                output.append({
                    "analysis_name": str(config.get("analysis_name", "network_pair_hypothesis_tests")),
                    "region": region,
                    "round": round_value,
                    "metric": metric_name,
                    "hypothesis": str(hypothesis["name"]),
                    "observation_n": len(obs_values),
                    "control_n": len(control_values),
                    "observation_median": statistics.median(obs_values) if obs_values else None,
                    "control_median": statistics.median(control_values) if control_values else None,
                    "u_statistic": u,
                    "cliffs_delta": delta,
                    "ci_low": ci_low,
                    "ci_high": ci_high,
                    "raw_p": raw_p,
                    "adjusted_p": None,
                    "adjustment_family": family,
                    "permutations": permutations,
                    "valid_permutations": valid_permutations,
                    "random_seed": base_seed,
                    "inference_status": str(hypothesis.get("inference_status", "exploratory")),
                    "data_status": row_status,
                    "metric_scope": metric_status,
                })

    families: dict[str, dict[int, float | None]] = defaultdict(dict)
    for index, row in enumerate(output):
        families[str(row["adjustment_family"])][index] = row["raw_p"]
    for family, values in families.items():
        adjusted = holm_adjust(values)
        for index, value in adjusted.items():
            output[index]["adjusted_p"] = value
    output.sort(key=lambda row: (row["region"], _round_sort_key(row["round"]), row["metric"], row["hypothesis"]))
    integrity["data_status_counts"] = dict(integrity["data_status_counts"])
    return output, integrity


def _round_sort_key(value: Any) -> tuple[int, str]:
    text = _clean(value)
    try:
        return int(float(text)), text
    except ValueError:
        return 999999, text


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig") as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise HypothesisConfigError("configuration root must be an object")
    return config


def _manifest_node_ids(records: Sequence[PairRecord]) -> list[str]:
    nodes: set[str] = set()
    for record in records:
        for side in ("a", "b"):
            source = record.feature or record.row
            value = normalize_entity(endpoint_value(source, side))
            if value:
                nodes.add(value)
    return sorted(nodes)


def run_from_files(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    covote_path: Path = DEFAULT_COVOTE_PATH,
    feature_path: Path = DEFAULT_FEATURE_PATH,
    metadata_path: Path = DEFAULT_METADATA_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    permutations_override: int | None = None,
    bootstrap_override: int | None = None,
    seed_override: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = load_config(config_path)
    config = json.loads(json.dumps(config))
    config.setdefault("parameters", {})
    if permutations_override is not None:
        config["parameters"]["permutations"] = permutations_override
    if bootstrap_override is not None:
        config["parameters"]["bootstrap_repetitions"] = bootstrap_override
    if seed_override is not None:
        config["parameters"]["random_seed"] = seed_override
    covote_rows = read_csv(covote_path)
    feature_rows = read_csv(feature_path)
    rows, integrity = run_analysis(config, covote_rows=covote_rows, feature_rows=feature_rows)
    write_csv(output_path, rows)
    records, _ = build_records(covote_rows, feature_rows)
    params = config.get("parameters", {})
    output_fields = OUTPUT_FIELDS
    manifest = write_model_run_manifest(
        manifest_path,
        root=ROOT,
        analysis=str(config.get("analysis_name", "network_pair_hypothesis_tests")),
        analysis_version=str(config.get("analysis_version", "1.0.0")),
        inputs=[
            {"path": config_path.relative_to(ROOT).as_posix(), "role": "hypothesis_configuration"},
            {"path": covote_path.relative_to(ROOT).as_posix(), "role": "observed_pair_metrics"},
            {"path": feature_path.relative_to(ROOT).as_posix(), "role": "structural_pair_features"},
            {"path": metadata_path.relative_to(ROOT).as_posix(), "role": "structural_metadata"},
        ],
        outputs=[
            {"path": output_path.relative_to(ROOT).as_posix(), "role": "hypothesis_test_results", "row_count": len(rows), "columns": output_fields},
        ],
        parameters={
            "configuration": config,
            "integrity_summary": integrity,
            "ci_method": "independent_group_percentile_bootstrap_cliffs_delta",
            "p_value_method": "node_attribute_monte_carlo_permutation",
            "holm": True,
        },
        test_method="node_attribute_monte_carlo_permutation",
        random_seed=int(params.get("random_seed", 0)),
        permutations=int(params.get("permutations", 0)),
        tail=str(params.get("tail", "two-sided")),
        node_set={
            "entity_type": "character",
            "source": feature_path.relative_to(ROOT).as_posix(),
            "selection_rule": "endpoints of observed character pairs; unknown structural covariates excluded from each null",
            "ids": _manifest_node_ids(records),
        },
        pair_inclusion={
            "rule": "observed character pairs with a published metric value and a non-overlapping expression group",
            "directed": False,
            "self_pairs": False,
            "deduplication": "unordered region/round/canonical_pair_key first deterministic row",
            "missing_pair_policy": "exclude_unobserved_and_right_censored_pairs; never infer zero",
            "included_pairs": len(records),
            "excluded_pairs": integrity.get("missing_feature_rows", 0),
        },
        data_integrity={
            "status": "passed" if not integrity.get("duplicate_covote_rows") else "passed_with_deduplication",
            "checks": [
                {"name": "unknown_is_not_zero", "ok": True},
                {"name": "holms_applied_after_raw_p_values", "ok": True},
                {"name": "node_permutation_not_asymptotic", "ok": True},
            ],
            "coverage": integrity,
            "missing": {"feature_rows": integrity.get("missing_feature_rows", 0)},
            "duplicate_count": integrity.get("duplicate_covote_rows", 0) + integrity.get("duplicate_feature_rows", 0),
            "invalid_count": 0,
            "warnings": ["Rows marked partial_matrix_observed_only contain published pairs only; absent pairs are not zeros."],
        },
        script=Path(__file__).relative_to(ROOT).as_posix(),
    )
    return rows, manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--covote", type=Path, default=DEFAULT_COVOTE_PATH)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURE_PATH)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--permutations", type=int, default=None)
    parser.add_argument("--bootstrap-repetitions", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rows, manifest = run_from_files(
        config_path=args.config,
        covote_path=args.covote,
        feature_path=args.features,
        metadata_path=args.metadata,
        output_path=args.output,
        manifest_path=args.manifest,
        permutations_override=args.permutations,
        bootstrap_override=args.bootstrap_repetitions,
        seed_override=args.seed,
    )
    print(f"network hypothesis rows: {len(rows)}")
    print(f"manifest: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
