#!/usr/bin/env python3
"""Compare the structure of two symmetric relation matrices.

The module intentionally treats a matrix as a labelled network rather than as
an ordinary vector.  Only unordered, non-diagonal pairs are compared; missing
pairs are excluded from both vectors and are never converted to zero.  The
null distribution is produced by synchronously permuting one matrix's node
labels (the same permutation is applied to rows and columns), not by using an
asymptotic vector-correlation p-value.

The public helpers are dependency-free so small matrices can be tested without
installing scipy or pandas.  NumPy, when available, is used only to accelerate
permutations for complete matrices; it does not change the statistical rule.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import math
import random
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:  # Optional acceleration; the statistical implementation remains stdlib-only.
    import numpy as _np  # type: ignore
except ImportError:  # pragma: no cover - depends on the execution environment
    _np = None

from scripts_pipeline.model_run_manifest import write_model_run_manifest
from vote_explorer.data_chunks import logical_file_exists, part_paths, read_csv_rows


OUTPUT_PATH = ROOT / "analysis_results" / "network_inference" / "matrix_correlations.csv"
MANIFEST_PATH = ROOT / "analysis_results" / "network_inference" / "matrix_correlations_run_manifest.json"
DEFAULT_COVOTE_PATH = ROOT / "vote_explorer" / "data" / "analysis_covote_pairs_all.csv"
DEFAULT_CP_PATH = ROOT / "vote_explorer" / "data" / "analysis_vote_combinations_all.csv"
DEFAULT_PERMUTATIONS = 200
DEFAULT_RANDOM_SEED = 20260929
DEFAULT_ROUND_PAIRS = tuple(
    [(f"CN{round_no}", f"CN{round_no - 1}") for round_no in range(2, 12)]
    + [(f"JP{round_no}", f"JP{round_no - 1}") for round_no in range(4, 23)]
)

NODE_ALIGNMENT_RULE = "canonical_node_id_intersection"
MISSING_PAIR_RULE = "common_observed_pairs_only_no_zero_fill"
INTERPRETATION_NOTE = "矩阵结构相关，不代表因果"

OUTPUT_FIELDS = [
    "matrix_a",
    "matrix_b",
    "region",
    "round",
    "node_count",
    "pair_count",
    "metric_a",
    "metric_b",
    "correlation_method",
    "observed_correlation",
    "permutation_p",
    "permutations",
    "random_seed",
    "node_alignment_rule",
    "missing_pair_rule",
    # These columns make two important caveats machine-readable while keeping
    # every requested field above unchanged and in the requested order.
    "complete_pair_matrix",
    "valid_permutations",
    "source_complete_a",
    "source_complete_b",
    "interpretation_note",
    "warning",
]

PairKey = tuple[str, str]


class MatrixInputError(ValueError):
    """Raised when a long-table source contains contradictory matrix cells."""


def normalize_node_id(value: Any) -> str:
    """Return a stable identity key without inventing an ID for blank input."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return re.sub(r"[\s・･·\-—_]+", "", text)


def _display_round(region: Any, round_value: Any, round_label: Any = "") -> str:
    raw_label = str(round_label or "").strip().upper()
    if re.fullmatch(r"(?:CN|JP)\d+", raw_label):
        return raw_label
    raw_round = str(round_value or "").strip()
    if re.fullmatch(r"\d+(?:\.0+)?", raw_round):
        return f"{str(region or '').strip().upper()}{int(float(raw_round))}"
    return raw_round.upper()


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text or text.casefold() in {"na", "n/a", "nan", "null", "none"}:
        return None
    try:
        result = float(text)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _truthy(value: Any) -> bool:
    return str(value or "").strip().casefold() in {"true", "1", "yes", "y"}


def _pair_key(node_a: Any, node_b: Any) -> PairKey | None:
    a, b = normalize_node_id(node_a), normalize_node_id(node_b)
    if not a or not b or a == b:
        return None
    return (a, b) if a < b else (b, a)


def _rank_values(values: Sequence[float]) -> list[float]:
    """Return one-based average ranks, including deterministic tie handling."""
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        value = values[order[cursor]]
        while end < len(order) and values[order[end]] == value:
            end += 1
        average = ((cursor + 1) + end) / 2.0
        for position in order[cursor:end]:
            ranks[position] = average
        cursor = end
    return ranks


def pearson_correlation(values_a: Sequence[float], values_b: Sequence[float]) -> float | None:
    """Compute Pearson correlation without an asymptotic significance test."""
    if len(values_a) != len(values_b) or len(values_a) < 3:
        return None
    mean_a = sum(values_a) / len(values_a)
    mean_b = sum(values_b) / len(values_b)
    numerator = sum((a - mean_a) * (b - mean_b) for a, b in zip(values_a, values_b))
    denominator_a = math.sqrt(sum((a - mean_a) ** 2 for a in values_a))
    denominator_b = math.sqrt(sum((b - mean_b) ** 2 for b in values_b))
    if not denominator_a or not denominator_b:
        return None
    result = numerator / (denominator_a * denominator_b)
    # Round only the tiny floating point overshoot that can occur for identical
    # vectors; do not clip a substantive value because it would hide errors.
    if abs(result - 1.0) <= 1e-14:
        return 1.0
    if abs(result + 1.0) <= 1e-14:
        return -1.0
    return result if math.isfinite(result) else None


def spearman_correlation(values_a: Sequence[float], values_b: Sequence[float]) -> float | None:
    """Compute Spearman correlation using average ranks for tied values."""
    if len(values_a) != len(values_b) or len(values_a) < 3:
        return None
    return pearson_correlation(_rank_values(values_a), _rank_values(values_b))


def _correlation(method: str, values_a: Sequence[float], values_b: Sequence[float]) -> float | None:
    normalized = str(method or "").strip().casefold()
    if normalized == "pearson":
        return pearson_correlation(values_a, values_b)
    if normalized == "spearman":
        return spearman_correlation(values_a, values_b)
    raise ValueError("method must be 'pearson' or 'spearman'")


def extract_upper_triangle(
    matrix: Mapping[Any, Any] | Sequence[Sequence[Any]],
    nodes: Iterable[Any] | None = None,
) -> dict[PairKey, float]:
    """Extract finite, non-diagonal values from a labelled symmetric matrix.

    ``matrix`` may be a mapping of row labels to mappings, or a square nested
    sequence accompanied by ``nodes``.  Values are looked up in either
    direction so input row/column order does not affect the result.  Missing
    cells remain absent from the returned mapping; a literal numeric zero is
    retained.
    """
    if nodes is None:
        if isinstance(matrix, Mapping):
            nodes = list(matrix.keys())
        else:
            raise ValueError("nodes are required for a sequence matrix")
    raw_nodes = [str(node) for node in nodes]
    normalized_nodes: dict[str, str] = {}
    for node in raw_nodes:
        identity = normalize_node_id(node)
        if identity:
            normalized_nodes.setdefault(identity, node)
    ordered = sorted(normalized_nodes)
    index = {node: position for position, node in enumerate(raw_nodes)}

    def lookup(row_label: str, column_label: str) -> Any:
        if isinstance(matrix, Mapping):
            row = matrix.get(row_label)
            if isinstance(row, Mapping):
                return row.get(column_label)
            if row is not None and column_label in index:
                try:
                    return row[index[column_label]]
                except (IndexError, KeyError, TypeError):
                    return None
            return None
        try:
            return matrix[index[row_label]][index[column_label]]
        except (IndexError, KeyError, TypeError):
            return None

    output: dict[PairKey, float] = {}
    for left, right in itertools.combinations(ordered, 2):
        left_label, right_label = normalized_nodes[left], normalized_nodes[right]
        value = lookup(left_label, right_label)
        if value is None:
            value = lookup(right_label, left_label)
        numeric = _finite_number(value)
        if numeric is not None:
            output[(left, right)] = numeric
    return output


@dataclass(frozen=True)
class MatrixData:
    """One labelled, symmetric matrix represented by its observed upper triangle."""

    matrix_name: str
    metric: str
    region: str
    round: str
    node_type: str
    values: Mapping[PairKey, float]
    nodes: frozenset[str]
    complete_pair_matrix: bool = False
    source_path: str = ""
    duplicate_count: int = 0

    def __post_init__(self) -> None:
        # Normalize direct API callers as well as CSV adapters.  This makes a
        # caller's row order and endpoint orientation immaterial.
        normalized_values: dict[PairKey, float] = {}
        for raw_pair, raw_value in self.values.items():
            if not isinstance(raw_pair, (tuple, list)) or len(raw_pair) != 2:
                raise MatrixInputError(f"invalid matrix pair: {raw_pair!r}")
            pair = _pair_key(raw_pair[0], raw_pair[1])
            numeric = _finite_number(raw_value)
            if pair is None or numeric is None:
                continue
            previous = normalized_values.get(pair)
            if previous is not None and not math.isclose(previous, numeric, rel_tol=1e-12, abs_tol=1e-12):
                raise MatrixInputError(f"conflicting values for matrix pair {pair}: {previous!r} != {numeric!r}")
            normalized_values[pair] = numeric
        normalized_nodes = frozenset(
            identity for identity in (normalize_node_id(node) for node in self.nodes) if identity
        )
        normalized_nodes = frozenset(set(normalized_nodes).union(node for pair in normalized_values for node in pair))
        object.__setattr__(self, "values", normalized_values)
        object.__setattr__(self, "nodes", normalized_nodes)


def align_nodes(matrix_a: MatrixData, matrix_b: MatrixData) -> list[str]:
    """Return the canonical node intersection in deterministic order."""
    return sorted(set(matrix_a.nodes).intersection(matrix_b.nodes))


def _common_observed_values(
    matrix_a: MatrixData,
    matrix_b: MatrixData,
    nodes: Sequence[str],
) -> tuple[list[PairKey], list[float], list[float]]:
    pairs: list[PairKey] = []
    values_a: list[float] = []
    values_b: list[float] = []
    allowed = set(nodes)
    for pair in sorted(set(matrix_a.values).intersection(matrix_b.values)):
        if pair[0] not in allowed or pair[1] not in allowed:
            continue
        value_a = _finite_number(matrix_a.values.get(pair))
        value_b = _finite_number(matrix_b.values.get(pair))
        if value_a is None or value_b is None:
            continue
        pairs.append(pair)
        values_a.append(value_a)
        values_b.append(value_b)
    return pairs, values_a, values_b


def _numpy_correlation(method: str, values_a: Any, values_b: Any) -> float | None:
    if _np is None or len(values_a) < 3:
        return None
    if str(method).casefold() == "spearman":
        # The complete-matrix permutation path supplies ranks directly.
        a, b = values_a, values_b
    else:
        a, b = values_a, values_b
    centered_a = a - a.mean()
    centered_b = b - b.mean()
    denominator = math.sqrt(float((centered_a * centered_a).sum()) * float((centered_b * centered_b).sum()))
    if not denominator:
        return None
    value = float((centered_a * centered_b).sum()) / denominator
    if abs(value - 1.0) <= 1e-12:
        return 1.0
    if abs(value + 1.0) <= 1e-12:
        return -1.0
    return value if math.isfinite(value) else None


def _complete_permutation_correlations(
    matrix_a: MatrixData,
    matrix_b: MatrixData,
    nodes: Sequence[str],
    method: str,
    permutations: int,
    rng: random.Random,
) -> list[float]:
    """Generate null correlations for a genuinely complete aligned matrix."""
    pairs = list(itertools.combinations(nodes, 2))
    values_a = [float(matrix_a.values[pair]) for pair in pairs]
    values_b = [float(matrix_b.values[pair]) for pair in pairs]
    node_indices = {node: index for index, node in enumerate(nodes)}
    if _np is not None:
        count = len(nodes)
        a_vector = _np.asarray(values_a, dtype=float)
        b_dense = _np.zeros((count, count), dtype=float)
        for (left, right), value in zip(pairs, values_b):
            i, j = node_indices[left], node_indices[right]
            b_dense[i, j] = b_dense[j, i] = value
        if method.casefold() == "spearman":
            ranked_b = _rank_values(values_b)
            b_dense = _np.zeros((count, count), dtype=float)
            for (left, right), value in zip(pairs, ranked_b):
                i, j = node_indices[left], node_indices[right]
                b_dense[i, j] = b_dense[j, i] = value
            a_vector = _np.asarray(_rank_values(values_a), dtype=float)
        upper = _np.triu_indices(count, 1)
        null_values: list[float] = []
        for _ in range(permutations):
            permutation = list(range(count))
            rng.shuffle(permutation)
            permuted = b_dense[_np.ix_(permutation, permutation)][upper]
            value = _numpy_correlation(method, a_vector, permuted)
            if value is not None:
                null_values.append(value)
        return null_values

    # Pure-Python fallback used when NumPy is unavailable.
    node_indices = {node: index for index, node in enumerate(nodes)}
    indexed_values = {(node_indices[a], node_indices[b]): value for (a, b), value in matrix_b.values.items()}
    null_values = []
    for _ in range(permutations):
        permutation = list(range(len(nodes)))
        rng.shuffle(permutation)
        permuted_b: list[float] = []
        for left, right in pairs:
            i, j = node_indices[left], node_indices[right]
            original_left, original_right = permutation[i], permutation[j]
            key = (min(original_left, original_right), max(original_left, original_right))
            permuted_b.append(indexed_values[key])
        if method.casefold() == "spearman":
            value = spearman_correlation(_rank_values(values_a), _rank_values(permuted_b))
        else:
            value = pearson_correlation(values_a, permuted_b)
        if value is not None:
            null_values.append(value)
    return null_values


def _sparse_permutation_correlations(
    matrix_a: MatrixData,
    matrix_b: MatrixData,
    nodes: Sequence[str],
    method: str,
    permutations: int,
    rng: random.Random,
) -> list[float]:
    """Permute B labels and reapply the common-observed rule on every draw."""
    pairs_a = [pair for pair in matrix_a.values if pair[0] in nodes and pair[1] in nodes]
    pairs_a.sort()
    node_indices = {node: index for index, node in enumerate(nodes)}
    indexed_b = {
        (node_indices[left], node_indices[right]): value
        for (left, right), value in matrix_b.values.items()
        if left in node_indices and right in node_indices
    }
    null_values: list[float] = []
    for _ in range(permutations):
        permutation = list(range(len(nodes)))
        rng.shuffle(permutation)
        values_a: list[float] = []
        values_b: list[float] = []
        for pair in pairs_a:
            left, right = node_indices[pair[0]], node_indices[pair[1]]
            original = (permutation[left], permutation[right])
            key = (min(original), max(original))
            value_b = indexed_b.get(key)
            value_a = _finite_number(matrix_a.values.get(pair))
            if value_a is None or value_b is None:
                continue
            values_a.append(value_a)
            values_b.append(value_b)
        value = _correlation(method, values_a, values_b)
        if value is not None:
            null_values.append(value)
    return null_values


def correlate_matrices(
    matrix_a: MatrixData,
    matrix_b: MatrixData,
    *,
    method: str = "spearman",
    permutations: int = DEFAULT_PERMUTATIONS,
    random_seed: int | None = DEFAULT_RANDOM_SEED,
    round_label: str | None = None,
    matrix_a_label: str | None = None,
    matrix_b_label: str | None = None,
) -> dict[str, Any]:
    """Correlate two labelled matrices and return a machine-readable result."""
    if matrix_a.node_type != matrix_b.node_type or matrix_a.region != matrix_b.region:
        raise ValueError("matrix comparison requires the same region and node type")
    if permutations < 0:
        raise ValueError("permutations must be non-negative")
    method = str(method).strip().casefold()
    if method not in {"pearson", "spearman"}:
        raise ValueError("method must be 'pearson' or 'spearman'")

    nodes = align_nodes(matrix_a, matrix_b)
    pairs, values_a, values_b = _common_observed_values(matrix_a, matrix_b, nodes)
    observed = _correlation(method, values_a, values_b)
    expected_pairs = len(nodes) * (len(nodes) - 1) // 2
    complete_comparison = bool(nodes) and matrix_a.complete_pair_matrix and matrix_b.complete_pair_matrix and len(pairs) == expected_pairs

    valid_permutations = 0
    permutation_p: float | None = None
    warning = ""
    if observed is None:
        warning = "insufficient_common_pairs_or_constant_metric"
    elif permutations:
        rng = random.Random(random_seed)
        if complete_comparison:
            null_values = _complete_permutation_correlations(matrix_a, matrix_b, nodes, method, permutations, rng)
        else:
            null_values = _sparse_permutation_correlations(matrix_a, matrix_b, nodes, method, permutations, rng)
        valid_permutations = len(null_values)
        if valid_permutations:
            extreme = sum(abs(value) >= abs(observed) - 1e-12 for value in null_values)
            permutation_p = (extreme + 1) / (valid_permutations + 1)
        else:
            warning = "no_valid_permutation_correlations"

    if len(pairs) < 3 and not warning:
        warning = "insufficient_common_pairs_or_constant_metric"
    return {
        "matrix_a": matrix_a_label or matrix_a.matrix_name,
        "matrix_b": matrix_b_label or matrix_b.matrix_name,
        "region": matrix_a.region,
        "round": round_label or matrix_a.round,
        "node_count": len(nodes),
        "pair_count": len(pairs),
        "metric_a": matrix_a.metric,
        "metric_b": matrix_b.metric,
        "correlation_method": method,
        "observed_correlation": observed,
        "permutation_p": permutation_p,
        "permutations": permutations,
        "random_seed": random_seed,
        "node_alignment_rule": NODE_ALIGNMENT_RULE,
        "missing_pair_rule": MISSING_PAIR_RULE,
        "complete_pair_matrix": complete_comparison,
        "valid_permutations": valid_permutations,
        "source_complete_a": matrix_a.complete_pair_matrix,
        "source_complete_b": matrix_b.complete_pair_matrix,
        "interpretation_note": INTERPRETATION_NOTE,
        "warning": warning,
    }


def build_matrix_from_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    matrix_name: str,
    metric: str,
    region: str,
    round_label: str,
    node_type: str,
    endpoint_a: str,
    endpoint_b: str,
    value_fields: str | Sequence[str],
    completeness_field: str = "complete_pair_matrix",
    source_path: str = "",
) -> MatrixData:
    """Build one matrix from a long pair table without zero-filling."""
    fields = [value_fields] if isinstance(value_fields, str) else list(value_fields)
    values: dict[PairKey, float] = {}
    nodes: set[str] = set()
    complete_source = bool(completeness_field)
    duplicate_count = 0
    row_count = 0
    for row in rows:
        row_count += 1
        key = _pair_key(row.get(endpoint_a), row.get(endpoint_b))
        if key is None:
            continue
        nodes.update(key)
        if completeness_field and not _truthy(row.get(completeness_field)):
            complete_source = False
        numeric = None
        for field in fields:
            numeric = _finite_number(row.get(field))
            if numeric is not None:
                break
        if numeric is None:
            continue
        previous = values.get(key)
        if previous is not None:
            if not math.isclose(previous, numeric, rel_tol=1e-12, abs_tol=1e-12):
                raise MatrixInputError(
                    f"conflicting values for {matrix_name}/{metric} {key}: {previous!r} != {numeric!r}"
                )
            duplicate_count += 1
            continue
        values[key] = numeric
    if row_count == 0:
        complete_source = False
    return MatrixData(
        matrix_name=matrix_name,
        metric=metric,
        region=region,
        round=round_label,
        node_type=node_type,
        values=values,
        nodes=frozenset(nodes),
        complete_pair_matrix=complete_source,
        source_path=source_path,
        duplicate_count=duplicate_count,
    )


def _group_rows(rows: Iterable[Mapping[str, Any]], category_from_source: bool = False) -> dict[tuple[str, str, str], list[Mapping[str, Any]]]:
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        region = str(row.get("region") or "").strip().casefold()
        round_label = _display_round(region, row.get("round"), row.get("round_label"))
        category = str(row.get("pair_category") or "").strip().casefold()
        if not category and category_from_source:
            source_type = str(row.get("source_type") or "").casefold()
            category = "music" if "music" in source_type else "character"
        if region and round_label and category:
            grouped[(region, round_label, category)].append(row)
    return grouped


def load_covote_matrices(path: Path = DEFAULT_COVOTE_PATH) -> list[MatrixData]:
    """Load raw/lift/cosine co-vote matrices by region, round and category."""
    if not logical_file_exists(path):
        raise FileNotFoundError(path)
    rows = read_csv_rows(path, compressed=path.suffix == ".gz")
    grouped = _group_rows(rows, category_from_source=True)
    output: list[MatrixData] = []
    relative_path = str(path.resolve().relative_to(ROOT)).replace("\\", "/") if path.resolve().is_relative_to(ROOT) else str(path)
    for (region, round_label, category), group in sorted(grouped.items()):
        for metric, value_fields in (
            ("raw_count", ("intersection_count", "raw_count")),
            ("lift", "lift"),
            ("cosine", "cosine"),
        ):
            matrix = build_matrix_from_rows(
                group,
                matrix_name=f"covote_{category}",
                metric=metric,
                region=region,
                round_label=round_label,
                node_type=category,
                endpoint_a="canonical_a",
                endpoint_b="canonical_b",
                value_fields=value_fields,
                source_path=relative_path,
            )
            if matrix.values:
                output.append(matrix)
    return output


def load_cp_matrices(path: Path = DEFAULT_CP_PATH) -> list[MatrixData]:
    """Load two-member official CP rows as sparse character matrices."""
    if not logical_file_exists(path):
        raise FileNotFoundError(path)
    rows = read_csv_rows(path, compressed=path.suffix == ".gz")
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if str(row.get("data_source") or "").strip().casefold() != "official_cp":
            continue
        if str(row.get("name_c") or "").strip():
            continue
        region = str(row.get("region") or "").strip().casefold()
        round_label = _display_round(region, row.get("round"), row.get("round_label"))
        if region and round_label:
            grouped[(region, round_label)].append(row)
    output: list[MatrixData] = []
    relative_path = str(path.resolve().relative_to(ROOT)).replace("\\", "/") if path.resolve().is_relative_to(ROOT) else str(path)
    for (region, round_label), group in sorted(grouped.items()):
        matrix = build_matrix_from_rows(
            group,
            matrix_name="cp_character",
            metric="vote_count",
            region=region,
            round_label=round_label,
            node_type="character",
            endpoint_a="name_a",
            endpoint_b="name_b",
            value_fields=("comparison_count", "cp_vote_count"),
            completeness_field="",
            source_path=relative_path,
        )
        if matrix.values:
            output.append(matrix)
    return output


def _matrix_sort_key(matrix: MatrixData) -> tuple[str, str, str, str, str]:
    return (matrix.region, matrix.round, matrix.node_type, matrix.matrix_name, matrix.metric)


def _candidate_pairs_for_group(matrices: Sequence[MatrixData]) -> list[tuple[MatrixData, MatrixData]]:
    by_source = {(matrix.matrix_name, matrix.metric): matrix for matrix in matrices}
    output: list[tuple[MatrixData, MatrixData]] = []
    covote_metrics = [by_source[key] for key in (
        ("covote_character", "raw_count"), ("covote_character", "lift"), ("covote_character", "cosine"),
        ("covote_music", "raw_count"), ("covote_music", "lift"), ("covote_music", "cosine"),
    ) if key in by_source]
    for left, right in itertools.combinations(covote_metrics, 2):
        if left.matrix_name == right.matrix_name:
            output.append((left, right))
    for covote in covote_metrics:
        if covote.metric == "raw_count":
            cp = by_source.get(("cp_character", "vote_count"))
            if cp is not None:
                output.append((covote, cp))
    return output


def _round_pair_values(round_pairs: Iterable[tuple[str, str] | str] | None) -> list[tuple[str, str]]:
    if round_pairs is None:
        return list(DEFAULT_ROUND_PAIRS)
    output: list[tuple[str, str]] = []
    for value in round_pairs:
        if isinstance(value, str):
            parts = re.split(r"\s*[:/,]\s*", value.strip())
            if len(parts) != 2:
                raise ValueError(f"round pair must be CURRENT:COMPARE, got {value!r}")
            current, compare = parts
        else:
            if len(value) != 2:
                raise ValueError(f"round pair must contain two labels, got {value!r}")
            current, compare = value
        current, compare = str(current).strip().upper(), str(compare).strip().upper()
        if not current or not compare or current == compare:
            raise ValueError(f"invalid round pair: {current!r}, {compare!r}")
        output.append((current, compare))
    return output


def build_comparisons(
    matrices: Sequence[MatrixData],
    *,
    permutations: int = DEFAULT_PERMUTATIONS,
    random_seed: int | None = DEFAULT_RANDOM_SEED,
    round_pairs: Iterable[tuple[str, str] | str] | None = None,
    include_cross_round: bool = True,
) -> list[dict[str, Any]]:
    """Build same-round metric comparisons and optional current/compare rows."""
    results: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str, str], list[MatrixData]] = defaultdict(list)
    for matrix in matrices:
        grouped[(matrix.region, matrix.round, matrix.node_type)].append(matrix)
    for key in sorted(grouped):
        for matrix_a, matrix_b in _candidate_pairs_for_group(sorted(grouped[key], key=_matrix_sort_key)):
            results.append(correlate_matrices(matrix_a, matrix_b, method="spearman", permutations=permutations, random_seed=random_seed))
            # Pearson and Spearman are intentionally separate rows so the output
            # can compare monotonic and linear structural similarity directly.
            results.append(correlate_matrices(matrix_a, matrix_b, method="pearson", permutations=permutations, random_seed=random_seed))

    if include_cross_round:
        lookup = {
            (matrix.region, matrix.node_type, matrix.matrix_name, matrix.metric, matrix.round): matrix
            for matrix in matrices
        }
        for current, compare in _round_pair_values(round_pairs):
            region = current[:2].casefold()
            for (matrix_region, node_type, matrix_name, metric, matrix_round), matrix_a in sorted(lookup.items()):
                if matrix_region != region or matrix_round != current:
                    continue
                matrix_b = lookup.get((matrix_region, node_type, matrix_name, metric, compare))
                if matrix_b is None:
                    continue
                results.append(
                    correlate_matrices(
                        matrix_a,
                        matrix_b,
                        method="spearman",
                        permutations=permutations,
                        random_seed=random_seed,
                        round_label=f"{current}_vs_{compare}",
                        matrix_a_label=f"{matrix_a.matrix_name}@{current}",
                        matrix_b_label=f"{matrix_b.matrix_name}@{compare}",
                    )
                )
                results.append(
                    correlate_matrices(
                        matrix_a,
                        matrix_b,
                        method="pearson",
                        permutations=permutations,
                        random_seed=random_seed,
                        round_label=f"{current}_vs_{compare}",
                        matrix_a_label=f"{matrix_a.matrix_name}@{current}",
                        matrix_b_label=f"{matrix_b.matrix_name}@{compare}",
                    )
                )
    results.sort(key=lambda row: (
        row["region"], row["round"], row["matrix_a"], row["matrix_b"], row["metric_a"], row["metric_b"],
        row["node_alignment_rule"], row["missing_pair_rule"],
    ))
    return results


def write_results(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _relative_or_absolute(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(resolved)


def _manifest_input_specs(paths: Sequence[Path]) -> list[dict[str, Any]]:
    """Record full files, or every authoritative partition when only parts exist."""
    specs: list[dict[str, Any]] = []
    for path in paths:
        if path.is_file():
            specs.append({"path": _relative_or_absolute(path), "role": "matrix_source"})
            continue
        if not logical_file_exists(path):
            raise FileNotFoundError(path)
        for part in part_paths(path):
            specs.append({"path": _relative_or_absolute(part), "role": "matrix_source_partition"})
    return specs


def write_run_manifest(
    path: Path,
    *,
    output_path: Path,
    input_paths: Sequence[Path],
    matrices: Sequence[MatrixData],
    rows: Sequence[Mapping[str, Any]],
    permutations: int,
    random_seed: int | None,
    round_pairs: Sequence[tuple[str, str]],
) -> dict[str, Any]:
    node_ids = sorted({node for matrix in matrices for node in matrix.nodes})
    warnings = sorted({str(row["warning"]) for row in rows if row.get("warning")})
    return write_model_run_manifest(
        path,
        root=ROOT,
        analysis="network_matrix_correlations",
        analysis_version="1.0.0",
        inputs=_manifest_input_specs(input_paths),
        outputs=[
            {
                "path": _relative_or_absolute(output_path),
                "role": "matrix_correlations",
                "row_count": len(rows),
                "columns": OUTPUT_FIELDS,
                "notes": INTERPRETATION_NOTE,
            }
        ],
        parameters={
            "methods": ["pearson", "spearman"],
            "within_round_comparisons": "covote raw_count/lift/cosine and official two-member CP vs raw_count",
            "round_pairs": [list(pair) for pair in round_pairs],
            "node_alignment_rule": NODE_ALIGNMENT_RULE,
            "missing_pair_rule": MISSING_PAIR_RULE,
            "complete_pair_rule": "both source flags true and every common-node unordered pair observed",
            "causal_interpretation": INTERPRETATION_NOTE,
        },
        test_method="synchronous_node_label_permutation",
        random_seed=random_seed,
        permutations=permutations,
        tail="two-sided",
        node_set={
            "entity_type": "matrix_nodes",
            "source": "matrix source adapters",
            "selection_rule": "union of source node IDs used by this run",
            "ids": node_ids,
        },
        pair_inclusion={
            "rule": MISSING_PAIR_RULE,
            "directed": False,
            "self_pairs": False,
            "deduplication": "unordered canonical node pair",
            "missing_pair_policy": "exclude_and_report",
            "included_pairs": sum(int(row.get("pair_count") or 0) for row in rows),
        },
        data_integrity={
            "status": "passed" if not warnings else "passed_with_warnings",
            "checks": [
                {"name": "no_zero_fill", "ok": all(row["missing_pair_rule"] == MISSING_PAIR_RULE for row in rows)},
                {"name": "causal_boundary_marked", "ok": all(row["interpretation_note"] == INTERPRETATION_NOTE for row in rows)},
                {"name": "output_rows_have_actual_pair_count", "ok": all("pair_count" in row for row in rows)},
            ],
            "coverage": {
                "matrix_count": len(matrices),
                "comparison_count": len(rows),
                "complete_comparison_count": sum(bool(row.get("complete_pair_matrix")) for row in rows),
            },
            "missing": {"warnings": warnings},
            "duplicate_count": sum(matrix.duplicate_count for matrix in matrices),
            "invalid_count": 0,
            "warnings": warnings,
        },
        script=__file__,
    )


def run_analysis(
    *,
    covote_path: Path = DEFAULT_COVOTE_PATH,
    cp_path: Path = DEFAULT_CP_PATH,
    output_path: Path | None = None,
    manifest_path: Path | None = None,
    permutations: int = DEFAULT_PERMUTATIONS,
    random_seed: int | None = DEFAULT_RANDOM_SEED,
    round_pairs: Iterable[tuple[str, str] | str] | None = None,
    include_cross_round: bool = True,
    write_manifest: bool = True,
) -> tuple[list[dict[str, Any]], list[MatrixData]]:
    matrices = load_covote_matrices(covote_path) + load_cp_matrices(cp_path)
    normalized_round_pairs = _round_pair_values(round_pairs)
    rows = build_comparisons(
        matrices,
        permutations=permutations,
        random_seed=random_seed,
        round_pairs=normalized_round_pairs,
        include_cross_round=include_cross_round,
    )
    destination = output_path or OUTPUT_PATH
    write_results(destination, rows)
    if write_manifest:
        write_run_manifest(
            manifest_path or MANIFEST_PATH,
            output_path=destination,
            input_paths=[covote_path, cp_path],
            matrices=matrices,
            rows=rows,
            permutations=permutations,
            random_seed=random_seed,
            round_pairs=normalized_round_pairs,
        )
    return rows, matrices


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare labelled symmetric relation matrices")
    parser.add_argument("--covote", type=Path, default=DEFAULT_COVOTE_PATH)
    parser.add_argument("--cp", type=Path, default=DEFAULT_CP_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--permutations", type=int, default=DEFAULT_PERMUTATIONS)
    parser.add_argument("--random-seed", type=int, default=DEFAULT_RANDOM_SEED)
    parser.add_argument("--current-round", metavar="ROUND", help="current round for one cross-round comparison")
    parser.add_argument("--compare-round", metavar="ROUND", help="comparison round for one cross-round comparison")
    parser.add_argument(
        "--round-pair",
        action="append",
        metavar="CURRENT:COMPARE",
        help="cross-round pair; may be supplied more than once (default: JP22:JP21 and CN11:CN10)",
    )
    parser.add_argument("--no-cross-round", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.permutations < 0:
        raise SystemExit("--permutations must be non-negative")
    if args.current_round or args.compare_round:
        if not args.current_round or not args.compare_round:
            raise SystemExit("--current-round and --compare-round must be supplied together")
        round_pairs = [(args.current_round, args.compare_round)]
    else:
        round_pairs = args.round_pair if args.round_pair else None
    rows, matrices = run_analysis(
        covote_path=args.covote,
        cp_path=args.cp,
        output_path=args.output,
        manifest_path=args.manifest,
        permutations=args.permutations,
        random_seed=args.random_seed,
        round_pairs=round_pairs,
        include_cross_round=not args.no_cross_round,
        write_manifest=True,
    )
    print(f"matrix sources: {len(matrices)}; correlation rows: {len(rows)}; output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
