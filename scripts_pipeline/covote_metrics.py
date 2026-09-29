"""Shared co-vote contingency-table formulas and evidence statuses.

The raw CN matrix uses the official cell convention ``m00=both``,
``m01=b-only``, ``m10=a-only`` and ``m11=neither``.  This module contains
only deterministic arithmetic so the data builder and independent audit use
exactly the same formulas.
"""

from __future__ import annotations

import math
from typing import Any


EXACT_2X2_FIELDS = (
    "m00_both_selected",
    "m01_b_only",
    "m10_a_only",
    "m11_neither_selected",
    "cosine",
    "cosine_ochiai",
    "ochiai",
    "jaccard",
    "pmi",
    "pmi_nats",
    "npmi",
    "phi",
    "baseline_count",
    "excess_count",
)


CN_CELL_CONVENTION = {
    "m00": "both selected (intersection)",
    "m01": "a not selected, b selected",
    "m10": "a selected, b not selected",
    "m11": "neither selected",
}


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer, not bool")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer: {value!r}") from exc
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError(f"{field} must be a finite integer: {value!r}")
    result = int(number)
    if result < 0:
        raise ValueError(f"{field} must be non-negative: {value!r}")
    return result


def _finite_or_none(value: float | None) -> float | None:
    return value if value is not None and math.isfinite(value) else None


def exact_2x2_metrics(m00: Any, m01: Any, m10: Any, m11: Any) -> dict[str, Any]:
    """Compute all common pair metrics from four verified raw cells.

    ``m01`` is the B-only cell and ``m10`` is the A-only cell.  Keeping this
    order explicit is important because the official CN payload's labels do
    not use the same ``source-only/target-only`` wording used by some older
    analysis scripts.
    """
    cells = {
        "m00_both_selected": _integer(m00, "m00"),
        "m01_b_only": _integer(m01, "m01"),
        "m10_a_only": _integer(m10, "m10"),
        "m11_neither_selected": _integer(m11, "m11"),
    }
    both = cells["m00_both_selected"]
    b_only = cells["m01_b_only"]
    a_only = cells["m10_a_only"]
    neither = cells["m11_neither_selected"]
    count_a = both + a_only
    count_b = both + b_only
    ballots = both + b_only + a_only + neither

    conditional_a_to_b = both / count_a if count_a else None
    conditional_b_to_a = both / count_b if count_b else None
    share = both / ballots if ballots else None
    baseline = count_a * count_b / ballots if ballots and count_a and count_b else None
    lift = both / baseline if baseline is not None and baseline > 0 else None
    union = count_a + count_b - both
    jaccard = both / union if union else None
    cosine = both / math.sqrt(count_a * count_b) if count_a and count_b else None
    pmi = math.log(lift) if lift is not None and lift > 0 else None
    npmi = (
        pmi / -math.log(share)
        if pmi is not None and share is not None and 0 < share < 1
        else None
    )
    phi_denominator = count_a * count_b * (ballots - count_a) * (ballots - count_b)
    phi = (
        (both * ballots - count_a * count_b) / math.sqrt(phi_denominator)
        if phi_denominator > 0
        else None
    )
    asymmetry = (
        conditional_a_to_b - conditional_b_to_a
        if conditional_a_to_b is not None and conditional_b_to_a is not None
        else None
    )

    result = {
        **cells,
        "count_a": count_a,
        "count_b": count_b,
        "ballots": ballots,
        "intersection_count": both,
        "raw_count": both,
        "raw_count_a_to_b": both,
        "raw_count_b_to_a": both,
        "conditional_rate": _finite_or_none(conditional_a_to_b),
        "conditional_rate_a_to_b": _finite_or_none(conditional_a_to_b),
        "conditional_rate_b_to_a": _finite_or_none(conditional_b_to_a),
        # Existing consumers use direction_*; retain the aliases while the
        # explicit conditional_* names become the documented schema.
        "direction_a_to_b": _finite_or_none(conditional_a_to_b),
        "direction_b_to_a": _finite_or_none(conditional_b_to_a),
        "share": _finite_or_none(share),
        "baseline_count": _finite_or_none(baseline),
        "lift": _finite_or_none(lift),
        "lift_a_to_b": _finite_or_none(lift),
        "lift_b_to_a": _finite_or_none(lift),
        "lift_basis": "independence_2x2",
        "excess_count": _finite_or_none(both - baseline if baseline is not None else None),
        "cosine": _finite_or_none(cosine),
        "cosine_ochiai": _finite_or_none(cosine),
        "ochiai": _finite_or_none(cosine),
        "jaccard": _finite_or_none(jaccard),
        "pmi": _finite_or_none(pmi),
        "pmi_nats": _finite_or_none(pmi),
        "npmi": _finite_or_none(npmi),
        "phi": _finite_or_none(phi),
        "asymmetry": _finite_or_none(asymmetry),
        "metric_status": "exact_complete_2x2",
        "complete_pair_matrix": True,
    }
    for field, value in result.items():
        if isinstance(value, float) and not math.isfinite(value):
            raise AssertionError(f"non-finite co-vote metric {field}: {value!r}")
    return result


def empty_exact_metrics(status: str, complete_pair_matrix: bool = False) -> dict[str, Any]:
    """Return explicit blanks for metrics requiring verified four-cell data."""
    return {
        **{field: None for field in EXACT_2X2_FIELDS},
        "metric_status": status,
        "complete_pair_matrix": complete_pair_matrix,
    }


def source_scope_label(complete_pair_matrix: bool) -> str:
    return "complete_pair_matrix" if complete_pair_matrix else "published_leading_list"
