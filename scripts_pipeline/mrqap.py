#!/usr/bin/env python3
"""MRQAP/QAP inference for undirected character co-vote dyads.

This module deliberately keeps data preparation and inference separate from the
large vote-data builder.  It accepts a dyad CSV directly for small, synthetic
networks and can also join the repository's character co-vote, structure and
popularity tables.  Only explicitly complete, undirected matrices are eligible
for permutation inference.  In particular, a published leading list is not a
matrix and an unlisted pair is never interpreted as zero.

The implementation uses NumPy and the Python standard library only.  Ordinary
OLS and linear-probability estimates are reported alongside studentized QAP
permutation p-values; the ordinary p-value is never used as a QAP substitute.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

try:  # Imports work both from the repository root and as a script.
    from scripts_pipeline.model_run_manifest import (
        create_model_run_manifest,
        node_ids_sha256,
        write_model_run_manifest,
    )
    from vote_explorer.data_chunks import iter_csv_rows, part_paths
except ImportError:  # pragma: no cover - direct ``python scripts_pipeline/mrqap.py``
    from model_run_manifest import create_model_run_manifest, node_ids_sha256, write_model_run_manifest
    _ROOT_FOR_IMPORT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(_ROOT_FOR_IMPORT))
    from vote_explorer.data_chunks import iter_csv_rows, part_paths


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COVOTE_PATH = ROOT / "vote_explorer" / "data" / "analysis_covote_pairs_all.csv"
DEFAULT_STRUCTURE_PATH = ROOT / "vote_explorer" / "data" / "analysis_character_pair_structure_features_all.csv"
DEFAULT_METRICS_PATH = ROOT / "vote_explorer" / "data" / "analysis_character_metrics_all.csv"
DEFAULT_OUTPUT_PATH = ROOT / "analysis_results" / "network_inference" / "mrqap_coefficients.csv"
DEFAULT_MANIFEST_PATH = ROOT / "analysis_results" / "network_inference" / "model_run_manifest.json"

CONTINUOUS_METRICS = ("lift", "cosine", "phi")
BINARY_METRICS = ("formed",)
STRUCTURE_PREDICTORS = (
    "same_work",
    "same_stage",
    "same_work_adjacent_stage",
    "same_community",
    "same_region",
    "log_count_a",
    "log_count_b",
)
PERMUTATION_SCHEMES = ("node", "freedman_lane")
UNKNOWN_TOKENS = frozenset(
    {"", "unknown", "unk", "na", "n/a", "null", "none", "nan", "未确认", "未知", "不详", "未提供", "unverified", "unverified_blank"}
)
TRUE_TOKENS = frozenset({"true", "t", "yes", "y", "1"})
FALSE_TOKENS = frozenset({"false", "f", "no", "n", "0"})

RESULT_FIELDS = (
    "region",
    "round",
    "dependent_metric",
    "model_type",
    "predictor",
    "coefficient",
    "ordinary_se",
    "ordinary_t",
    "ordinary_p",
    "qap_p",
    "permutations",
    "permutations_used",
    "random_seed",
    "permutation_seed",
    "permutation_scheme",
    "r_squared",
    "n_pairs",
    "complete_case_n",
    "n_nodes",
    "status",
    "collinearity_diagnostic",
)


class MRQAPError(ValueError):
    """Base error for invalid MRQAP inputs or model specifications."""


class MatrixValidationError(MRQAPError):
    """Raised when an input group cannot be interpreted as one undirected matrix."""


@dataclass(frozen=True)
class ModelSpec:
    """One dependent variable/model family and its predictors."""

    dependent_metric: str
    model_type: str = "ols"
    predictors: tuple[str, ...] = STRUCTURE_PREDICTORS
    permutation_schemes: tuple[str, ...] = PERMUTATION_SCHEMES

    def __post_init__(self) -> None:
        if not str(self.dependent_metric).strip():
            raise MRQAPError("dependent_metric must be non-empty")
        if self.model_type not in {"ols", "linear_probability"}:
            raise MRQAPError(f"unsupported model_type: {self.model_type!r}")
        predictors = tuple(str(value).strip() for value in self.predictors if str(value).strip())
        schemes = tuple(str(value).strip() for value in self.permutation_schemes if str(value).strip())
        if len(set(predictors)) != len(predictors):
            raise MRQAPError("predictors must not contain duplicates")
        if not predictors:
            raise MRQAPError("at least one predictor is required")
        if not schemes or any(value not in PERMUTATION_SCHEMES for value in schemes):
            raise MRQAPError(f"permutation_schemes must use {PERMUTATION_SCHEMES}")
        object.__setattr__(self, "predictors", predictors)
        object.__setattr__(self, "permutation_schemes", schemes)


@dataclass(frozen=True)
class MatrixGroup:
    key: tuple[str, str, str]
    rows: tuple[dict[str, Any], ...]
    nodes: tuple[str, ...]
    complete: bool
    expected_pairs: int


@dataclass(frozen=True)
class MatrixValidation:
    groups: tuple[MatrixGroup, ...]
    excluded: tuple[dict[str, Any], ...]


@dataclass
class FitResult:
    success: bool
    beta: np.ndarray | None = None
    standard_error: np.ndarray | None = None
    t_statistic: np.ndarray | None = None
    p_value: np.ndarray | None = None
    fitted: np.ndarray | None = None
    residual: np.ndarray | None = None
    r_squared: float | None = None
    rank: int = 0
    degrees_of_freedom: int = 0
    diagnostic: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass(frozen=True)
class AnalysisRun:
    rows: tuple[dict[str, Any], ...]
    validation: MatrixValidation
    warnings: tuple[str, ...]
    group_reports: tuple[dict[str, Any], ...]
    nodes: tuple[str, ...]


# ---------------------------------------------------------------------------
# Parsing and deterministic identifiers


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _id_key(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    # Match the existing canonical-name identity policy without allowing an
    # empty value to match another empty value.
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\s・･·\-—_]+", "", text)
    return text.casefold()


def _pair_key(node_a: Any, node_b: Any) -> str:
    values = sorted((_id_key(node_a), _id_key(node_b)))
    if not values[0] or not values[1] or values[0] == values[1]:
        return ""
    return "|".join(values)


def _parse_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    text = _text(value)
    if text.casefold() in UNKNOWN_TOKENS:
        return None
    try:
        result = float(text)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _parse_binary(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    text = _text(value).casefold()
    if text in TRUE_TOKENS:
        return 1.0
    if text in FALSE_TOKENS:
        return 0.0
    return None


def _parse_complete_marker(row: Mapping[str, Any]) -> bool | None:
    """Parse an explicit completeness marker, rejecting contradictions."""
    complete = _parse_binary(row.get("complete_pair_matrix"))
    complete_value = None if complete is None else bool(complete)
    completeness = _text(row.get("data_completeness")).casefold()
    from_completeness: bool | None
    if not completeness:
        from_completeness = None
    elif completeness == "complete_matrix":
        from_completeness = True
    elif completeness in {"official_published_leading_list", "partial_matrix", "incomplete_matrix"}:
        from_completeness = False
    else:
        from_completeness = None
    if complete_value is not None and from_completeness is not None and complete_value != from_completeness:
        raise MatrixValidationError(
            f"completeness markers disagree for {_text(row.get('canonical_pair_key')) or _text(row.get('pair_key'))}"
        )
    return complete_value if complete_value is not None else from_completeness


def _first_numeric(row: Mapping[str, Any], *fields: str) -> float | None:
    for field_name in fields:
        value = _parse_float(row.get(field_name))
        if value is not None:
            return value
    return None


def _stable_seed(base_seed: int | None, *parts: Any) -> int | None:
    if base_seed is None:
        return None
    payload = json.dumps([int(base_seed), *parts], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    # NumPy's Generator accepts uint64 seeds.  Keep the value in signed 63-bit
    # range as well so it remains portable through CSV and JSON.
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % (2**63 - 1)


# ---------------------------------------------------------------------------
# Dyad preparation


def _stage_number(value: Any) -> float | None:
    """Parse only an unambiguous numeric stage label.

    Labels containing several numbers (for example a range) and symbolic EX
    stages are intentionally left unknown rather than guessed.
    """
    text = _text(value)
    if not text or text.casefold() in UNKNOWN_TOKENS:
        return None
    normalized = text.casefold().replace("　", " ")
    match = re.fullmatch(r"(?:stage|stg|第)?\s*(\d+)(?:\.0+)?\s*(?:stage|关|面)?", normalized)
    if not match:
        return None
    return float(match.group(1))


def _feature_value(row: Mapping[str, Any], field_name: str) -> float | None:
    return _parse_binary(row.get(field_name))


def _same_work_value(row: Mapping[str, Any]) -> float | None:
    for field_name in (
        "same_work",
        "same_crosswalk_first_appearance_work_id",
        "same_reference_first_appearance_work",
        "same_first_appearance_work",
    ):
        value = _feature_value(row, field_name)
        if value is not None:
            return value
    work_a = next((row.get(field) for field in ("a_reference_first_appearance_work", "a_work", "work_a") if _text(row.get(field))), None)
    work_b = next((row.get(field) for field in ("b_reference_first_appearance_work", "b_work", "work_b") if _text(row.get(field))), None)
    if work_a is None or work_b is None or _id_key(work_a) in UNKNOWN_TOKENS or _id_key(work_b) in UNKNOWN_TOKENS:
        return None
    return float(_id_key(work_a) == _id_key(work_b))


def _same_community_value(row: Mapping[str, Any]) -> float | None:
    """Use shared membership for "same community", not equal whole sets."""
    for field_name in ("shared_community", "same_community"):
        value = _feature_value(row, field_name)
        if value is not None:
            return value
    value_a = next((row.get(field) for field in ("a_community", "community_a") if _text(row.get(field))), None)
    value_b = next((row.get(field) for field in ("b_community", "community_b") if _text(row.get(field))), None)
    if value_a is None or value_b is None:
        return None
    values_a = {_id_key(part) for part in re.split(r"\s*;\s*", _text(value_a)) if _id_key(part)}
    values_b = {_id_key(part) for part in re.split(r"\s*;\s*", _text(value_b)) if _id_key(part)}
    if not values_a or not values_b or any(value in UNKNOWN_TOKENS for value in values_a | values_b):
        return None
    return float(bool(values_a & values_b))


def _same_endpoint_value(row: Mapping[str, Any], feature: str, endpoint_a: Sequence[str], endpoint_b: Sequence[str]) -> float | None:
    value = _feature_value(row, feature)
    if value is not None:
        return value
    a = next((row.get(field) for field in endpoint_a if _text(row.get(field))), None)
    b = next((row.get(field) for field in endpoint_b if _text(row.get(field))), None)
    if a is None or b is None:
        return None
    if _text(a).casefold() in UNKNOWN_TOKENS or _text(b).casefold() in UNKNOWN_TOKENS:
        return None
    return float(_id_key(a) == _id_key(b))


def _adjacent_stage_value(row: Mapping[str, Any]) -> float | None:
    existing = _feature_value(row, "same_work_adjacent_stage")
    if existing is not None:
        return existing
    work_a = next((row.get(field) for field in ("a_reference_first_appearance_work", "a_work", "work_a") if _text(row.get(field))), None)
    work_b = next((row.get(field) for field in ("b_reference_first_appearance_work", "b_work", "work_b") if _text(row.get(field))), None)
    stage_a = next((row.get(field) for field in ("a_stage", "stage_a" ) if _text(row.get(field))), None)
    stage_b = next((row.get(field) for field in ("b_stage", "stage_b" ) if _text(row.get(field))), None)
    number_a, number_b = _stage_number(stage_a), _stage_number(stage_b)
    if work_a is None or work_b is None or number_a is None or number_b is None:
        return None
    if _text(work_a).casefold() in UNKNOWN_TOKENS or _text(work_b).casefold() in UNKNOWN_TOKENS:
        return None
    return float(_id_key(work_a) == _id_key(work_b) and abs(number_a - number_b) == 1)


def _copy_structure_features(target: dict[str, Any], structure: Mapping[str, Any] | None) -> None:
    if structure is None:
        return
    # Preserve the pair identity from the co-vote source, but copy all audited
    # endpoint/features needed for derivation and later diagnostics.
    for key, value in structure.items():
        if key not in {"region", "round", "canonical_pair_key", "pair_key", "name_a", "name_b"}:
            if _text(target.get(key)) == "":
                target[key] = value


def _popularity_index(metrics_rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str, str], float]:
    index: dict[tuple[str, str, str], float] = {}
    for row in metrics_rows:
        if _text(row.get("category")) != "character":
            continue
        region, round_value = _text(row.get("region")), _text(row.get("round"))
        if not region or not round_value:
            continue
        count = _first_numeric(row, "selection_count", "vote_count")
        if count is None:
            continue
        for field_name in ("canonical_name", "name_cn", "name_jp", "entity_id"):
            key = _id_key(row.get(field_name))
            if key:
                index.setdefault((region, round_value, key), count)
    return index


def build_character_dyads(
    covote_rows: Iterable[Mapping[str, Any]],
    structure_rows: Iterable[Mapping[str, Any]] | None = None,
    metrics_rows: Iterable[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Join repository tables into normalized character dyad rows.

    No rows are invented: the result contains exactly the observed character
    pairs in ``covote_rows``.  In particular this function does not infer a
    binary CP/formed relation from an absent CP or association-list row.
    """
    structure_index: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for source in structure_rows or ():
        if _text(source.get("pair_category")) not in {"", "character"}:
            continue
        key = _pair_key(
            source.get("canonical_a") or source.get("name_a_cn") or source.get("name_a"),
            source.get("canonical_b") or source.get("name_b_cn") or source.get("name_b"),
        )
        if not key:
            supplied_key = _text(source.get("canonical_pair_key"))
            parts = supplied_key.split("|")
            key = _pair_key(*parts) if len(parts) == 2 else ""
        if key:
            structure_index.setdefault((_text(source.get("region")), _text(source.get("round")), key), source)
    popularity = _popularity_index(metrics_rows or ())
    output: list[dict[str, Any]] = []
    for source in covote_rows:
        category = _text(source.get("pair_category")) or "character"
        if category != "character":
            continue
        region, round_value = _text(source.get("region")), _text(source.get("round"))
        source_a = _text(source.get("canonical_a")) or _text(source.get("name_a_cn")) or _text(source.get("name_a"))
        source_b = _text(source.get("canonical_b")) or _text(source.get("name_b_cn")) or _text(source.get("name_b"))
        node_a, node_b = _id_key(source_a), _id_key(source_b)
        pair_key = _pair_key(source_a, source_b)
        supplied_pair_key = _text(source.get("canonical_pair_key"))
        if supplied_pair_key:
            if len(supplied_pair_key.split("|")) != 2 or _pair_key(*supplied_pair_key.split("|")) != pair_key:
                raise MatrixValidationError(f"dyad pair key disagrees with its endpoints: {supplied_pair_key!r}")
            # Keep the input key; stored display punctuation may differ.
            pair_key = supplied_pair_key
        if not region or not round_value or not node_a or not node_b or not pair_key:
            raise MatrixValidationError("character dyad has a blank region, round, endpoint, or pair key")
        if _pair_key(node_a, node_b) != _pair_key(*pair_key.split("|", 1)):
            raise MatrixValidationError(f"dyad pair key disagrees with its endpoints: {pair_key!r}")
        # Resolve the endpoint order from the audited feature row.  Co-vote
        # inputs frequently put A/B in a different order; using their counts
        # with the feature row's endpoints without reorientation is unsafe.
        feature = structure_index.get((region, round_value, _pair_key(node_a, node_b)))
        raw_a, raw_b = source_a, source_b
        if feature is not None:
            feature_a = _id_key(feature.get("canonical_a") or feature.get("name_a_cn") or feature.get("name_a"))
            feature_b = _id_key(feature.get("canonical_b") or feature.get("name_b_cn") or feature.get("name_b"))
            if feature_a and feature_b:
                if (feature_a, feature_b) not in {(node_a, node_b), (node_b, node_a)}:
                    raise MatrixValidationError(f"feature endpoints disagree with co-vote pair: {pair_key!r}")
                if (feature_a, feature_b) == (node_b, node_a):
                    raw_a, raw_b = source_b, source_a
        # With no matched feature row, impose the same canonical A/B order.
        # Both log-count controls then mean the same thing for every dyad.
        if feature is None and node_a > node_b:
            raw_a, raw_b = source_b, source_a
        node_a, node_b = _id_key(raw_a), _id_key(raw_b)
        target: dict[str, Any] = dict(source)
        if raw_a != source_a:
            for first, second in (("count_a", "count_b"), ("selection_count_a", "selection_count_b"), ("vote_count_a", "vote_count_b")):
                target[first], target[second] = target.get(second, ""), target.get(first, "")
        target.update({
            "region": region,
            "round": round_value,
            "pair_category": "character",
            "node_a": _id_key(raw_a),
            "node_b": _id_key(raw_b),
            "canonical_pair_key": _pair_key(node_a, node_b),
        })
        _copy_structure_features(target, feature)
        count_a = _first_numeric(target, "count_a", "selection_count_a", "vote_count_a")
        count_b = _first_numeric(target, "count_b", "selection_count_b", "vote_count_b")
        if count_a is None:
            count_a = popularity.get((region, round_value, node_a))
        if count_b is None:
            count_b = popularity.get((region, round_value, node_b))
        target["count_a"] = count_a if count_a is not None else ""
        target["count_b"] = count_b if count_b is not None else ""
        target["same_work"] = _same_work_value(target)
        target["same_stage"] = _same_endpoint_value(
            target,
            "same_stage",
            ("a_stage", "stage_a"),
            ("b_stage", "stage_b"),
        )
        target["same_community"] = _same_community_value(target)
        target["same_region"] = _same_endpoint_value(
            target,
            "same_region",
            ("a_region", "region_a"),
            ("b_region", "region_b"),
        )
        target["same_work_adjacent_stage"] = _adjacent_stage_value(target)
        target["log_count_a"] = math.log(count_a) if count_a is not None and count_a > 0 else None
        target["log_count_b"] = math.log(count_b) if count_b is not None and count_b > 0 else None
        output.append(target)
    return output


def build_character_dyads_from_files(
    covote_path: Path = DEFAULT_COVOTE_PATH,
    structure_path: Path = DEFAULT_STRUCTURE_PATH,
    metrics_path: Path = DEFAULT_METRICS_PATH,
) -> list[dict[str, Any]]:
    """Load the repository's logical CSVs without merging stale partitions."""
    if not part_paths(covote_path):
        raise FileNotFoundError(covote_path)
    covote_rows = (row for row in iter_csv_rows(covote_path))
    structure_rows = list(iter_csv_rows(structure_path)) if part_paths(structure_path) else []
    metrics_rows = list(iter_csv_rows(metrics_path)) if part_paths(metrics_path) else []
    return build_character_dyads(covote_rows, structure_rows, metrics_rows)


# ---------------------------------------------------------------------------
# Matrix validation and ordinary regression


def validate_matrix_groups(rows: Iterable[Mapping[str, Any]], *, strict_partial: bool = False) -> MatrixValidation:
    """Validate explicit complete undirected matrix groups.

    A group with a published leading-list/partial marker is excluded rather
    than treated as a zero-filled matrix.  A group that mixes complete and
    partial markers is an error because it is impossible to know which node
    universe the rows describe.
    """
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for raw in rows:
        row = dict(raw)
        key = (_text(row.get("region")), _text(row.get("round")), _text(row.get("pair_category")) or "character")
        if not all(key):
            raise MatrixValidationError(f"matrix row has incomplete group key: {key!r}")
        grouped[key].append(row)
    valid: list[MatrixGroup] = []
    excluded: list[dict[str, Any]] = []
    for key in sorted(grouped):
        group_rows = grouped[key]
        markers = {_parse_complete_marker(row) for row in group_rows}
        if None in markers:
            raise MatrixValidationError(f"group {key} lacks an explicit matrix-completeness marker")
        if len(markers) != 1:
            raise MatrixValidationError(f"group {key} mixes complete and partial matrix rows")
        complete = bool(next(iter(markers)))
        if key[2] != "character":
            excluded.append({"group": list(key), "rows": len(group_rows), "reason": "unsupported_pair_category"})
            continue
        if not complete:
            item = {"group": list(key), "rows": len(group_rows), "reason": "partial_or_right_censored_matrix"}
            excluded.append(item)
            if strict_partial:
                raise MatrixValidationError(f"group {key} is not a complete matrix")
            continue
        seen: set[str] = set()
        nodes: set[str] = set()
        for row in group_rows:
            node_a = _text(row.get("node_a")) or _id_key(row.get("canonical_a") or row.get("name_a"))
            node_b = _text(row.get("node_b")) or _id_key(row.get("canonical_b") or row.get("name_b"))
            if not node_a or not node_b or node_a == node_b:
                raise MatrixValidationError(f"group {key} contains a self-loop or blank endpoint")
            pair = _pair_key(node_a, node_b)
            if not pair:
                raise MatrixValidationError(f"group {key} contains an invalid pair")
            if pair in seen:
                raise MatrixValidationError(f"group {key} contains a duplicate unordered pair: {pair}")
            seen.add(pair)
            nodes.update((node_a, node_b))
            row["node_a"], row["node_b"] = node_a, node_b
        expected = len(nodes) * (len(nodes) - 1) // 2
        if len(seen) != expected:
            raise MatrixValidationError(
                f"group {key} is not a complete node matrix: {len(seen)} rows for {len(nodes)} nodes; expected {expected}"
            )
        valid.append(MatrixGroup(key, tuple(group_rows), tuple(sorted(nodes)), True, expected))
    return MatrixValidation(tuple(valid), tuple(excluded))


def _diagnostic(design: np.ndarray, predictor_names: Sequence[str], *, status: str | None = None) -> dict[str, Any]:
    names = ["intercept", *predictor_names]
    rank = int(np.linalg.matrix_rank(design)) if design.size else 0
    try:
        condition = float(np.linalg.cond(design)) if design.size else None
        if condition is not None and not math.isfinite(condition):
            condition = None
    except np.linalg.LinAlgError:
        condition = None
    constants = [names[index] for index in range(1, len(names)) if design.shape[0] and float(np.ptp(design[:, index])) <= 1e-12]
    near_collinear: list[list[str]] = []
    if design.shape[1] > 1 and design.shape[0] > 1:
        for left in range(1, design.shape[1]):
            for right in range(left + 1, design.shape[1]):
                left_values, right_values = design[:, left], design[:, right]
                if np.std(left_values) <= 1e-12 or np.std(right_values) <= 1e-12:
                    continue
                correlation = float(np.corrcoef(left_values, right_values)[0, 1])
                if math.isfinite(correlation) and abs(correlation) >= 0.999999:
                    near_collinear.append([names[left], names[right]])
    if status is None:
        status = "ok" if rank == design.shape[1] else "rank_deficient"
    return {
        "status": status,
        "columns": names,
        "column_count": int(design.shape[1]) if design.ndim == 2 else 0,
        "rank": rank,
        "condition_number": condition,
        "constant_predictors": constants,
        "near_perfect_correlations": near_collinear,
    }


def collinearity_diagnostic(x: Sequence[Sequence[float]] | np.ndarray, predictor_names: Sequence[str]) -> dict[str, Any]:
    """Return a JSON-safe design-matrix rank/conditioning diagnostic."""
    values = np.asarray(x, dtype=float)
    if values.ndim != 2:
        raise MRQAPError("x must be a two-dimensional predictor matrix")
    return _diagnostic(np.column_stack((np.ones(values.shape[0]), values)), predictor_names)


def _regularized_incomplete_beta(x: float, a: float, b: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    max_iterations, epsilon, floor = 300, 3.0e-14, 1.0e-300
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))

    def fraction(first_a: float, first_b: float, z: float) -> float:
        qab, qap, qam = first_a + first_b, first_a + 1.0, first_a - 1.0
        c, d = 1.0, 1.0 - qab * z / qap
        if abs(d) < floor:
            d = floor
        d, result = 1.0 / d, 1.0 / d
        for iteration in range(1, max_iterations + 1):
            twice = 2 * iteration
            coefficient = iteration * (first_b - iteration) * z / ((qam + twice) * (first_a + twice))
            d = 1.0 + coefficient * d
            if abs(d) < floor:
                d = floor
            c = 1.0 + coefficient / c
            if abs(c) < floor:
                c = floor
            d = 1.0 / d
            result *= d * c
            coefficient = -(first_a + iteration) * (qab + iteration) * z / ((first_a + twice) * (qap + twice))
            d = 1.0 + coefficient * d
            if abs(d) < floor:
                d = floor
            c = 1.0 + coefficient / c
            if abs(c) < floor:
                c = floor
            d = 1.0 / d
            delta = d * c
            result *= delta
            if abs(delta - 1.0) < epsilon:
                return result
        raise ArithmeticError("incomplete-beta continued fraction did not converge")

    if x < (a + 1.0) / (a + b + 2.0):
        return max(0.0, min(1.0, front * fraction(a, b, x) / a))
    reflected = 1.0 - front * fraction(b, a, 1.0 - x) / b
    return max(0.0, min(1.0, reflected))


def _student_two_sided_p(t_value: float | None, degrees_of_freedom: int) -> float | None:
    if t_value is None or not math.isfinite(t_value) or degrees_of_freedom <= 0:
        return None
    if abs(t_value) == 0:
        return 1.0
    if math.isinf(t_value):
        return 0.0
    x = degrees_of_freedom / (degrees_of_freedom + t_value * t_value)
    return _regularized_incomplete_beta(x, degrees_of_freedom / 2.0, 0.5)


def fit_ols(y: Sequence[float] | np.ndarray, x: Sequence[Sequence[float]] | np.ndarray, predictor_names: Sequence[str]) -> FitResult:
    """Fit OLS/LPM and refuse rank-deficient designs instead of hiding them."""
    y_values = np.asarray(y, dtype=float)
    x_values = np.asarray(x, dtype=float)
    if y_values.ndim != 1 or x_values.ndim != 2 or len(y_values) != x_values.shape[0]:
        raise MRQAPError("y and x have incompatible shapes")
    if x_values.shape[1] != len(predictor_names):
        raise MRQAPError("predictor_names does not match x columns")
    design = np.column_stack((np.ones(len(y_values)), x_values))
    diagnostic = _diagnostic(design, predictor_names)
    rank, column_count = diagnostic["rank"], diagnostic["column_count"]
    if rank != column_count:
        return FitResult(False, rank=rank, diagnostic=diagnostic, error="rank_deficient")
    if len(y_values) <= column_count:
        diagnostic["status"] = "insufficient_degrees_of_freedom"
        return FitResult(False, rank=rank, diagnostic=diagnostic, error="insufficient_degrees_of_freedom")
    beta, _, _, _ = np.linalg.lstsq(design, y_values, rcond=None)
    fitted = design @ beta
    residual = y_values - fitted
    rss = float(residual @ residual)
    centered = y_values - float(np.mean(y_values))
    total = float(centered @ centered)
    r_squared = None if total <= 0 else 1.0 - rss / total
    degrees = len(y_values) - column_count
    try:
        covariance = np.linalg.inv(design.T @ design) * (rss / degrees)
        standard_error = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    except np.linalg.LinAlgError:
        diagnostic["status"] = "singular_covariance"
        return FitResult(False, rank=rank, diagnostic=diagnostic, error="singular_covariance")
    t_statistic = np.array(
        [float(beta[index] / standard_error[index]) if standard_error[index] > 0 else np.nan for index in range(column_count)],
        dtype=float,
    )
    p_value = np.array(
        [
            _student_two_sided_p(float(t), degrees)
            if math.isfinite(float(t))
            else None
            for t in t_statistic
        ],
        dtype=object,
    )
    return FitResult(
        True,
        beta=beta,
        standard_error=standard_error,
        t_statistic=t_statistic,
        p_value=p_value,
        fitted=fitted,
        residual=residual,
        r_squared=r_squared if r_squared is None or math.isfinite(r_squared) else None,
        rank=rank,
        degrees_of_freedom=degrees,
        diagnostic=diagnostic,
    )


# ---------------------------------------------------------------------------
# QAP permutation machinery


def _matrix_from_edges(values: Sequence[float], node_count: int, edge_indices: Sequence[tuple[int, int]]) -> np.ndarray:
    matrix = np.zeros((node_count, node_count), dtype=float)
    for value, (left, right) in zip(values, edge_indices):
        matrix[left, right] = value
        matrix[right, left] = value
    return matrix


def _edges_from_matrix(matrix: np.ndarray, edge_indices: Sequence[tuple[int, int]]) -> np.ndarray:
    return np.asarray([matrix[left, right] for left, right in edge_indices], dtype=float)


def _permuted_matrix(matrix: np.ndarray, permutation: np.ndarray) -> np.ndarray:
    # One permutation is applied to both axes.  Independent row shuffles would
    # destroy the observed network's node structure and are not QAP.
    return matrix[np.ix_(permutation, permutation)]


def permute_y_by_nodes(y: Sequence[float], node_count: int, edge_indices: Sequence[tuple[int, int]], permutation: Sequence[int]) -> np.ndarray:
    """Public helper used by tests to verify structure-preserving permutation."""
    matrix = _matrix_from_edges(y, node_count, edge_indices)
    return _edges_from_matrix(_permuted_matrix(matrix, np.asarray(permutation, dtype=int)), edge_indices)


def _permutation_t_statistics(
    y: np.ndarray,
    x: np.ndarray,
    predictor_names: Sequence[str],
    node_count: int,
    edge_indices: Sequence[tuple[int, int]],
    target_index: int,
    scheme: str,
    rng: np.random.Generator,
    permutations: int,
) -> np.ndarray:
    if permutations <= 0:
        return np.asarray([], dtype=float)
    y_matrix = _matrix_from_edges(y, node_count, edge_indices)
    reduced_fit: FitResult | None = None
    reduced_x: np.ndarray | None = None
    if scheme == "freedman_lane":
        target_column = x[:, target_index]
        reduced_x = np.delete(x, target_index, axis=1)
        reduced_names = tuple(name for index, name in enumerate(predictor_names) if index != target_index)
        reduced_fit = fit_ols(y, reduced_x, reduced_names)
        if not reduced_fit.success or reduced_fit.fitted is None or reduced_fit.residual is None:
            return np.asarray([], dtype=float)
    statistics: list[float] = []
    for _ in range(permutations):
        permutation = rng.permutation(node_count)
        if scheme == "node":
            permuted_y = _edges_from_matrix(_permuted_matrix(y_matrix, permutation), edge_indices)
        elif scheme == "freedman_lane":
            assert reduced_fit is not None and reduced_fit.fitted is not None and reduced_fit.residual is not None
            fitted_matrix = _matrix_from_edges(reduced_fit.fitted, node_count, edge_indices)
            residual_matrix = _matrix_from_edges(reduced_fit.residual, node_count, edge_indices)
            permuted_y = _edges_from_matrix(
                fitted_matrix + _permuted_matrix(residual_matrix, permutation), edge_indices
            )
        else:  # pragma: no cover - ModelSpec validates this
            raise MRQAPError(f"unknown permutation scheme: {scheme}")
        fit = fit_ols(permuted_y, x, predictor_names)
        if fit.success and fit.t_statistic is not None:
            value = float(fit.t_statistic[target_index + 1])
            if math.isfinite(value):
                statistics.append(value)
    return np.asarray(statistics, dtype=float)


def qap_p_value(observed_t: float | None, permuted_t: Sequence[float], *, permutations: int | None = None) -> float | None:
    """Return a two-sided +1-corrected QAP p-value for a pivot t statistic."""
    if observed_t is None or not math.isfinite(observed_t):
        return None
    values = np.asarray(permuted_t, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return None
    extreme = int(np.count_nonzero(np.abs(values) >= abs(observed_t)))
    denominator = int(values.size) + 1
    return float((extreme + 1) / denominator)


def _complete_case_rows(group: MatrixGroup, metric: str, predictors: Sequence[str], model_type: str) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    """Select an induced complete submatrix with deterministic node exclusions.

    Each incomplete dyad requires dropping at least one endpoint.  Greedily
    remove the node incident to the most currently incomplete dyads (breaking
    ties by canonical ID), rather than removing *both* endpoints of every
    incomplete dyad; doing the latter can empty a useful network merely
    because every node touches some unknown metadata elsewhere.
    """
    nodes = set(group.nodes)
    missing_neighbors: dict[str, set[str]] = {node: set() for node in nodes}
    parsed: dict[int, tuple[float | None, list[float | None]]] = {}
    for index, row in enumerate(group.rows):
        y_value = _parse_binary(row.get(metric)) if model_type == "linear_probability" else _parse_float(row.get(metric))
        x_values = [_parse_float(row.get(name)) for name in predictors]
        parsed[index] = (y_value, x_values)
        if y_value is None or any(value is None for value in x_values):
            left, right = row["node_a"], row["node_b"]
            missing_neighbors[left].add(right)
            missing_neighbors[right].add(left)
    while nodes:
        most_missing = max(len(missing_neighbors[node]) for node in nodes)
        if most_missing == 0:
            break
        victim = min(node for node in nodes if len(missing_neighbors[node]) == most_missing)
        for neighbor in missing_neighbors[victim]:
            missing_neighbors[neighbor].discard(victim)
        nodes.remove(victim)
    selected = [
        row
        for index, row in enumerate(group.rows)
        if row["node_a"] in nodes and row["node_b"] in nodes
        and parsed[index][0] is not None and all(value is not None for value in parsed[index][1])
    ]
    expected_pairs = len(nodes) * (len(nodes) - 1) // 2
    if len(selected) != expected_pairs:
        raise MatrixValidationError(f"complete-case submatrix has {len(selected)} pairs; expected {expected_pairs}")
    return selected, tuple(sorted(nodes))


def _json_diagnostic(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _result_row(
    *, group: MatrixGroup, spec: ModelSpec, predictor: str, scheme: str, random_seed: int | None,
    permutation_seed: int | None, status: str, diagnostic: Mapping[str, Any], n_pairs: int,
    complete_case_n: int, n_nodes: int, fit: FitResult | None = None, qap_p: float | None = None,
    permutations: int = 0, permutations_used: int = 0,
) -> dict[str, Any]:
    predictor_index = spec.predictors.index(predictor) if predictor in spec.predictors else -1
    result: dict[str, Any] = {
        "region": group.key[0], "round": group.key[1], "dependent_metric": spec.dependent_metric,
        "model_type": spec.model_type, "predictor": predictor, "coefficient": None,
        "ordinary_se": None, "ordinary_t": None, "ordinary_p": None, "qap_p": qap_p,
        "permutations": permutations, "permutations_used": permutations_used,
        "random_seed": random_seed, "permutation_seed": permutation_seed,
        "permutation_scheme": scheme, "r_squared": None, "n_pairs": n_pairs,
        "complete_case_n": complete_case_n, "n_nodes": n_nodes, "status": status,
        "collinearity_diagnostic": _json_diagnostic(diagnostic),
    }
    if fit is not None and fit.success and fit.beta is not None and fit.standard_error is not None and fit.t_statistic is not None and fit.p_value is not None and predictor_index >= 0:
        coefficient = float(fit.beta[predictor_index + 1])
        standard_error = float(fit.standard_error[predictor_index + 1])
        t_value = float(fit.t_statistic[predictor_index + 1])
        ordinary_p = fit.p_value[predictor_index + 1]
        result.update({
            "coefficient": coefficient if math.isfinite(coefficient) else None,
            "ordinary_se": standard_error if math.isfinite(standard_error) else None,
            "ordinary_t": t_value if math.isfinite(t_value) else None,
            "ordinary_p": float(ordinary_p) if ordinary_p is not None and math.isfinite(float(ordinary_p)) else None,
            "r_squared": fit.r_squared,
        })
    return result


def run_mrqap(
    rows: Iterable[Mapping[str, Any]],
    *,
    continuous_metrics: Sequence[str] = CONTINUOUS_METRICS,
    binary_metrics: Sequence[str] = BINARY_METRICS,
    continuous_predictors: Sequence[str] = STRUCTURE_PREDICTORS,
    binary_predictors: Sequence[str] = STRUCTURE_PREDICTORS,
    permutations: int = 1000,
    random_seed: int | None = 20260928,
    permutation_schemes: Sequence[str] = PERMUTATION_SCHEMES,
    strict_partial: bool = False,
) -> AnalysisRun:
    """Run independent OLS/LPM models for every eligible matrix group."""
    if permutations < 0:
        raise MRQAPError("permutations must be non-negative")
    if permutations > 0 and random_seed is None:
        raise MRQAPError("random_seed is required when permutations are requested")
    schemes = tuple(permutation_schemes)
    if not schemes or any(scheme not in PERMUTATION_SCHEMES for scheme in schemes):
        raise MRQAPError(f"permutation_schemes must use {PERMUTATION_SCHEMES}")
    row_list = [dict(row) for row in rows]
    validation = validate_matrix_groups(row_list, strict_partial=strict_partial)
    warnings: list[str] = []
    for excluded in validation.excluded:
        warnings.append(f"excluded {excluded['reason']} group: {excluded['group']}")
    result_rows: list[dict[str, Any]] = []
    group_reports: list[dict[str, Any]] = []
    all_nodes: set[str] = set()
    specs: list[ModelSpec] = []
    for metric in continuous_metrics:
        specs.append(ModelSpec(str(metric), "ols", tuple(continuous_predictors), schemes))
    for metric in binary_metrics:
        specs.append(ModelSpec(str(metric), "linear_probability", tuple(binary_predictors), schemes))

    for group in validation.groups:
        all_nodes.update(group.nodes)
        group_report: dict[str, Any] = {
            "region": group.key[0], "round": group.key[1], "pair_category": group.key[2],
            "matrix_status": "complete_matrix", "nodes": len(group.nodes),
            "n_pairs": len(group.rows), "expected_pairs": group.expected_pairs,
            "models": [],
        }
        for spec in specs:
            metric_values = [row.get(spec.dependent_metric) for row in group.rows]
            available = any(_text(value) != "" for value in metric_values)
            if not available:
                warnings.append(f"dependent metric {spec.dependent_metric!r} is unavailable in group {group.key}")
                group_report["models"].append({"dependent_metric": spec.dependent_metric, "model_type": spec.model_type, "status": "metric_unavailable"})
                diagnostic = {
                    "status": "metric_unavailable",
                    "reason": "dependent metric is absent; no relation is inferred from missing rows",
                    "columns": ["intercept", *spec.predictors],
                    "column_count": len(spec.predictors) + 1,
                    "rank": 0,
                }
                for predictor in spec.predictors:
                    for scheme in spec.permutation_schemes:
                        result_rows.append(_result_row(
                            group=group, spec=spec, predictor=predictor, scheme=scheme,
                            random_seed=random_seed,
                            permutation_seed=_stable_seed(random_seed, *group.key, spec.dependent_metric, spec.model_type, predictor, scheme),
                            status="metric_unavailable", diagnostic=diagnostic,
                            n_pairs=len(group.rows), complete_case_n=0, n_nodes=0,
                            permutations=permutations, permutations_used=0,
                        ))
                continue
            if spec.model_type == "linear_probability" and any(_parse_binary(value) is None for value in metric_values):
                warnings.append(f"binary metric {spec.dependent_metric!r} is not explicit for every dyad in group {group.key}")
                group_report["models"].append({"dependent_metric": spec.dependent_metric, "model_type": spec.model_type, "status": "binary_matrix_incomplete"})
                for predictor in spec.predictors:
                    for scheme in spec.permutation_schemes:
                        diagnostic = {"status": "binary_matrix_incomplete", "reason": "binary Y requires explicit 0/1 for every pair; missing is never zero"}
                        result_rows.append(_result_row(
                            group=group, spec=spec, predictor=predictor, scheme=scheme,
                            random_seed=random_seed,
                            permutation_seed=_stable_seed(random_seed, *group.key, spec.dependent_metric, spec.model_type, predictor, scheme),
                            status="binary_matrix_incomplete", diagnostic=diagnostic,
                            n_pairs=len(group.rows), complete_case_n=0, n_nodes=0,
                            permutations=permutations, permutations_used=0,
                        ))
                continue
            selected, nodes = _complete_case_rows(group, spec.dependent_metric, spec.predictors, spec.model_type)
            model_report = {
                "dependent_metric": spec.dependent_metric, "model_type": spec.model_type,
                "complete_case_n": len(selected), "complete_case_nodes": len(nodes),
                "status": "ok" if selected else "no_complete_cases",
            }
            group_report["models"].append(model_report)
            if not selected:
                diagnostic = {
                    "status": "no_complete_cases", "columns": ["intercept", *spec.predictors],
                    "column_count": len(spec.predictors) + 1, "rank": 0,
                    "condition_number": None, "constant_predictors": [], "near_perfect_correlations": [],
                    "missing_value_policy": "unknown/blank is missing; node-induced complete submatrix",
                }
                for predictor in spec.predictors:
                    for scheme in spec.permutation_schemes:
                        seed = _stable_seed(random_seed, *group.key, spec.dependent_metric, spec.model_type, predictor, scheme)
                        result_rows.append(_result_row(
                            group=group, spec=spec, predictor=predictor, scheme=scheme,
                            random_seed=random_seed, permutation_seed=seed, status="no_complete_cases",
                            diagnostic=diagnostic, n_pairs=len(group.rows), complete_case_n=0, n_nodes=0,
                            permutations=permutations, permutations_used=0,
                        ))
                continue
            node_index = {node: index for index, node in enumerate(nodes)}
            edge_indices = [(node_index[_text(row["node_a"])], node_index[_text(row["node_b"])]) for row in selected]
            y_values = np.asarray([
                _parse_binary(row.get(spec.dependent_metric)) if spec.model_type == "linear_probability" else _parse_float(row.get(spec.dependent_metric))
                for row in selected
            ], dtype=float)
            x_values = np.asarray([[_parse_float(row.get(name)) for name in spec.predictors] for row in selected], dtype=float)
            fit = fit_ols(y_values, x_values, spec.predictors)
            diagnostic = dict(fit.diagnostic)
            diagnostic["missing_value_policy"] = "unknown/blank is missing; node-induced complete submatrix"
            status = "ok" if fit.success else fit.error or "fit_failed"
            if not fit.success:
                model_report["status"] = status
            for predictor_index, predictor in enumerate(spec.predictors):
                for scheme in spec.permutation_schemes:
                    derived_seed = _stable_seed(random_seed, *group.key, spec.dependent_metric, spec.model_type, predictor, scheme)
                    permuted: np.ndarray = np.asarray([], dtype=float)
                    if fit.success and derived_seed is not None and permutations > 0:
                        rng = np.random.default_rng(derived_seed)
                        permuted = _permutation_t_statistics(
                            y_values, x_values, spec.predictors, len(nodes), edge_indices,
                            predictor_index, scheme, rng, permutations,
                        )
                    observed_t = None
                    if fit.success and fit.t_statistic is not None:
                        value = float(fit.t_statistic[predictor_index + 1])
                        observed_t = value if math.isfinite(value) else None
                    result_rows.append(_result_row(
                        group=group, spec=spec, predictor=predictor, scheme=scheme,
                        random_seed=random_seed, permutation_seed=derived_seed,
                        status=status, diagnostic=diagnostic, n_pairs=len(group.rows),
                        complete_case_n=len(selected), n_nodes=len(nodes), fit=fit,
                        qap_p=qap_p_value(observed_t, permuted, permutations=permutations),
                        permutations=permutations, permutations_used=int(len(permuted)),
                    ))
        group_reports.append(group_report)
    result_rows.sort(key=lambda row: (
        row["region"], str(row["round"]), row["dependent_metric"], row["predictor"], row["permutation_scheme"],
    ))
    return AnalysisRun(tuple(result_rows), validation, tuple(warnings), tuple(group_reports), tuple(sorted(all_nodes)))


# ---------------------------------------------------------------------------
# CSV, manifest and command line interface


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    return value


def write_results(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(RESULT_FIELDS), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in RESULT_FIELDS})


def _manifest_paths(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return [candidate for candidate in part_paths(path) if candidate.is_file()]


def write_run_artifacts(
    run: AnalysisRun,
    *,
    root: Path = ROOT,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    input_paths: Sequence[Path] = (),
    parameters: Mapping[str, Any] | None = None,
    random_seed: int | None = 20260928,
    permutations: int = 1000,
) -> dict[str, Any]:
    """Write coefficients and a validated repository model-run manifest."""
    root = root.resolve()
    output_path = output_path.resolve()
    manifest_path = manifest_path.resolve()
    write_results(output_path, run.rows)
    input_specs: list[dict[str, Any]] = []
    for path in input_paths:
        for actual in _manifest_paths(path.resolve()):
            try:
                relative = actual.relative_to(root).as_posix()
            except ValueError as exc:
                raise MRQAPError(f"manifest input is outside workspace root: {actual}") from exc
            input_specs.append({"path": relative, "role": "mrqap_input"})
    try:
        output_relative = output_path.relative_to(root).as_posix()
    except ValueError as exc:
        raise MRQAPError(f"manifest output is outside workspace root: {output_path}") from exc
    complete_groups = len(run.validation.groups)
    excluded_pairs = sum(int(item.get("rows", 0)) for item in run.validation.excluded)
    warnings = list(run.warnings)
    status = "passed" if not warnings else "passed_with_warnings"
    integrity = {
        "status": status,
        "checks": [
            {"name": "complete_matrix_groups_only", "ok": True},
            {"name": "partial_matrix_groups_excluded", "ok": not any("mixed" in warning for warning in warnings)},
            {"name": "unknown_values_not_zero", "ok": True},
        ],
        "coverage": {"complete_groups": complete_groups, "group_reports": list(run.group_reports)},
        "missing": {
            "excluded_partial_groups": len(run.validation.excluded),
            "excluded_partial_rows": excluded_pairs,
            "warnings": len(warnings),
        },
        "duplicate_count": 0,
        "invalid_count": 0,
        "warnings": warnings,
    }
    schemes = sorted({str(row.get("permutation_scheme")) for row in run.rows if row.get("permutation_scheme")})
    model_types = sorted({str(row.get("model_type")) for row in run.rows if row.get("model_type")})
    base = create_model_run_manifest(
        root,
        analysis="character_covote_mrqap",
        analysis_version="1.0.0",
        inputs=input_specs,
        outputs=[{"path": output_relative, "role": "mrqap_coefficients"}],
        parameters=dict(parameters or {}),
        random_seed=random_seed,
        permutations=permutations,
        tail="two-sided",
        statistical_test={
            "method": "MRQAP studentized-t",
            "pivot": "studentized_t",
            "permutation_schemes": schemes,
            "models_run": model_types,
            "plus_one_correction": True,
        },
        node_set={
            "entity_type": "character",
            "source": "analysis_covote_pairs_all.csv",
            "selection_rule": "explicit complete_matrix character groups; no self-pairs",
            "ids": list(run.nodes),
        },
        pair_inclusion={
            "rule": "complete undirected character matrix with all n*(n-1)/2 unordered pairs",
            "directed": False,
            "self_pairs": False,
            "missing_pair_policy": "exclude partial/unknown pairs; never fill zero",
            "included_pairs": sum(len(group.rows) for group in run.validation.groups),
            "excluded_pairs": excluded_pairs,
        },
        data_integrity=integrity,
        script="scripts_pipeline/mrqap.py" if (root / "scripts_pipeline" / "mrqap.py").is_file() else None,
    )
    base["mrqap"] = {
        "model_types": {"continuous": "ols", "binary": "linear_probability"},
        "permutation_schemes": schemes,
        "ordinary_p_field": "ordinary_p",
        "qap_p_field": "qap_p",
        "unknown_policy": "blank/unknown is missing; never zero",
        "complete_case_policy": "iteratively remove nodes incident to incomplete dyads, then use the induced complete submatrix",
        "groups": list(run.group_reports),
        "excluded_groups": list(run.validation.excluded),
        "nodes_sha256": node_ids_sha256(run.nodes) if run.nodes else None,
    }
    return write_model_run_manifest(manifest_path, base, root=root)


def _split_csv_argument(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run complete-matrix character MRQAP/QAP inference")
    parser.add_argument("--input", type=Path, help="already normalized dyad CSV")
    parser.add_argument("--covote", type=Path, default=DEFAULT_COVOTE_PATH)
    parser.add_argument("--structure", type=Path, default=DEFAULT_STRUCTURE_PATH)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS_PATH)
    parser.add_argument("--continuous-metrics", default=",".join(CONTINUOUS_METRICS))
    parser.add_argument("--binary-metrics", default=",".join(BINARY_METRICS))
    parser.add_argument("--continuous-predictors", default=",".join(STRUCTURE_PREDICTORS))
    parser.add_argument("--binary-predictors", default=",".join(STRUCTURE_PREDICTORS))
    parser.add_argument("--permutations", type=int, default=1000)
    parser.add_argument("--random-seed", type=int, default=20260928)
    parser.add_argument("--permutation-scheme", choices=("node", "freedman_lane", "both"), default="both")
    parser.add_argument("--strict-partial", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if args.input:
        rows = list(iter_csv_rows(args.input))
        input_paths = [args.input]
    else:
        rows = build_character_dyads_from_files(args.covote, args.structure, args.metrics)
        input_paths = [args.covote, args.structure, args.metrics]
    schemes = PERMUTATION_SCHEMES if args.permutation_scheme == "both" else (args.permutation_scheme,)
    continuous_metrics = _split_csv_argument(args.continuous_metrics)
    binary_metrics = _split_csv_argument(args.binary_metrics)
    run = run_mrqap(
        rows,
        continuous_metrics=continuous_metrics,
        binary_metrics=binary_metrics,
        continuous_predictors=_split_csv_argument(args.continuous_predictors),
        binary_predictors=_split_csv_argument(args.binary_predictors),
        permutations=args.permutations,
        random_seed=args.random_seed,
        permutation_schemes=schemes,
        strict_partial=args.strict_partial,
    )
    manifest = write_run_artifacts(
        run,
        root=ROOT,
        output_path=args.output,
        manifest_path=args.manifest,
        input_paths=input_paths,
        parameters={
            "continuous_metrics": list(continuous_metrics), "binary_metrics": list(binary_metrics),
            "continuous_predictors": list(_split_csv_argument(args.continuous_predictors)),
            "binary_predictors": list(_split_csv_argument(args.binary_predictors)),
            "permutation_schemes": list(schemes), "strict_partial": args.strict_partial,
        },
        random_seed=args.random_seed,
        permutations=args.permutations,
    )
    print(json.dumps({"coefficient_rows": len(run.rows), "complete_groups": len(run.validation.groups), "excluded_groups": len(run.validation.excluded), "manifest": str(args.manifest), "manifest_schema_version": manifest["schema_version"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
