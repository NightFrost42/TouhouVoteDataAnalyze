"""Recompute the article's character--music statistics from local workbooks.

This is a clean-room replacement for ``Character-MusicAnalyze.py``.  It emits
both the weighted sum actually used by that script and the correctly
normalised weighted mean, records every contributing character aggregate, and
reports the exact analysis universe instead of silently filling missing music
associations with zero.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


WORKSPACE = Path(__file__).resolve().parents[1]
OUT_ROOT = WORKSPACE / "analysis_results" / "character_music_recomputed"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def load_last_sheet(path: Path) -> pd.DataFrame:
    workbook = pd.ExcelFile(path)
    return pd.read_excel(workbook, sheet_name=workbook.sheet_names[-1])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def zscore(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").astype(float)
    standard_deviation = numeric.std(ddof=0)
    if not standard_deviation:
        return pd.Series(np.zeros(len(numeric)), index=numeric.index)
    return (numeric - numeric.mean()) / standard_deviation


def weights(length: int) -> np.ndarray:
    if length <= 0:
        return np.array([], dtype=float)
    result = np.full(length, 0.25, dtype=float)
    result[0] = 1.0
    if length > 1:
        result[1] = 0.75
    if length > 2:
        result[2] = 0.50
    return result


def average_ranks(values: np.ndarray) -> np.ndarray:
    """Return one-based average ranks, matching scipy.stats.rankdata."""
    values = np.asarray(values)
    order = np.argsort(values, kind="mergesort")
    ordered = values[order]
    ranks = np.empty(len(values), dtype=float)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and ordered[end] == ordered[start]:
            end += 1
        average = (start + 1 + end) / 2.0
        ranks[order[start:end]] = average
        start = end
    return ranks


def beta_continued_fraction(a: float, b: float, x: float) -> float:
    """Numerical Recipes continued fraction for the incomplete beta."""
    maximum_iterations = 300
    epsilon = 3.0e-14
    floor = 1.0e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < floor:
        d = floor
    d = 1.0 / d
    result = d
    for iteration in range(1, maximum_iterations + 1):
        twice = 2 * iteration
        coefficient = iteration * (b - iteration) * x / (
            (qam + twice) * (a + twice)
        )
        d = 1.0 + coefficient * d
        if abs(d) < floor:
            d = floor
        c = 1.0 + coefficient / c
        if abs(c) < floor:
            c = floor
        d = 1.0 / d
        result *= d * c
        coefficient = -(a + iteration) * (qab + iteration) * x / (
            (a + twice) * (qap + twice)
        )
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


def regularized_incomplete_beta(x: float, a: float, b: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * beta_continued_fraction(a, b, x) / a
    return 1.0 - front * beta_continued_fraction(b, a, 1.0 - x) / b


def spearman_statistic(x: np.ndarray, y: np.ndarray) -> float:
    x_rank = average_ranks(np.asarray(x))
    y_rank = average_ranks(np.asarray(y))
    if np.std(x_rank) == 0 or np.std(y_rank) == 0:
        return float("nan")
    return float(np.corrcoef(x_rank, y_rank)[0, 1])


def spearman_p_value(rho: float, n: int) -> float:
    """Two-sided asymptotic t p-value, the convention used by scipy."""
    if n < 3 or not math.isfinite(rho):
        return float("nan")
    if abs(rho) >= 1:
        return 0.0
    degrees_of_freedom = n - 2
    t_squared = rho * rho * degrees_of_freedom / ((1.0 + rho) * (1.0 - rho))
    x = degrees_of_freedom / (degrees_of_freedom + t_squared)
    return min(1.0, max(0.0, regularized_incomplete_beta(x, degrees_of_freedom / 2.0, 0.5)))


def bootstrap_spearman(
    x: np.ndarray,
    y: np.ndarray,
    *,
    seed: int = 352,
    repetitions: int = 5000,
) -> tuple[float | None, float | None]:
    generator = np.random.default_rng(seed)
    estimates = []
    size = len(x)
    for _ in range(repetitions):
        indices = generator.integers(0, size, size=size)
        estimate = spearman_statistic(x[indices], y[indices])
        if np.isfinite(estimate):
            estimates.append(float(estimate))
    if not estimates:
        return None, None
    return tuple(float(value) for value in np.quantile(estimates, [0.025, 0.975]))


def correlation_record(
    frame: pd.DataFrame,
    x_column: str,
    y_column: str,
    *,
    site: str,
    metric: str,
    universe: str,
) -> dict[str, Any]:
    subset = frame[[x_column, y_column]].dropna()
    rho = spearman_statistic(
        subset[x_column].to_numpy(float), subset[y_column].to_numpy(float)
    )
    low, high = bootstrap_spearman(
        subset[x_column].to_numpy(float), subset[y_column].to_numpy(float)
    )
    return {
        "site": site,
        "metric": metric,
        "universe": universe,
        "n": len(subset),
        "spearman_rho": rho,
        "p_value": spearman_p_value(rho, len(subset)),
        "bootstrap_95_ci_low": low,
        "bootstrap_95_ci_high": high,
        "bootstrap_repetitions": 5000,
    }


def build_site(
    *,
    site: str,
    character_raw: Path,
    character_grouped: Path,
    music_raw: Path,
    music_grouped: Path,
    character_name_column: str,
    music_vote_column: str,
    name_map: dict[str, str],
) -> pd.DataFrame:
    char_raw = load_last_sheet(character_raw)
    char = load_last_sheet(character_grouped).copy()
    music_raw_frame = load_last_sheet(music_raw)
    music = load_last_sheet(music_grouped).copy()

    total_character_score = pd.to_numeric(char_raw["票数"], errors="coerce").sum()
    total_music_score = pd.to_numeric(
        music_raw_frame[music_vote_column], errors="coerce"
    ).sum()
    char["character_score"] = pd.to_numeric(char["票数"], errors="coerce")
    char["character_rate"] = char["character_score"] / total_character_score
    char["character_z"] = zscore(char["character_rate"])
    music["music_score"] = pd.to_numeric(music[music_vote_column], errors="coerce")
    music["music_rate"] = music["music_score"] / total_music_score
    music["music_z"] = zscore(music["music_rate"])

    if site == "cn":
        char["character"] = char[character_name_column].astype(str).str.strip()
    else:
        original = char[character_name_column].astype(str).str.strip()
        char["character"] = original.map(name_map).fillna(original)

    by_character: dict[str, list[dict[str, float]]] = {}
    for _, row in music.iterrows():
        association = row.get("所属角色")
        if pd.isna(association):
            continue
        for original_name in str(association).split("|"):
            original_name = original_name.strip()
            if not original_name:
                continue
            character = original_name if site == "cn" else name_map.get(original_name, original_name)
            by_character.setdefault(character, []).append(
                {"z": float(row["music_z"]), "rate": float(row["music_rate"])}
            )

    aggregates = []
    for character, records in by_character.items():
        ordered = sorted(records, key=lambda record: record["z"], reverse=True)
        item_weights = weights(len(ordered))
        z_values = np.array([record["z"] for record in ordered])
        rate_values = np.array([record["rate"] for record in ordered])
        weight_sum = float(item_weights.sum())
        weighted_z_sum = float(np.dot(z_values, item_weights))
        weighted_rate_sum = float(np.dot(rate_values, item_weights))
        aggregates.append(
            {
                "character": character,
                "music_count": len(ordered),
                "weight_sum": weight_sum,
                "music_weighted_z_sum": weighted_z_sum,
                "music_weighted_rate_sum": weighted_rate_sum,
                "music_weighted_z_mean": weighted_z_sum / weight_sum,
                "music_weighted_rate_mean": weighted_rate_sum / weight_sum,
            }
        )
    aggregate = pd.DataFrame(aggregates)
    merged = char.merge(aggregate, on="character", how="left")
    merged["has_music_association"] = merged["music_count"].notna()
    for column in (
        "music_count",
        "weight_sum",
        "music_weighted_z_sum",
        "music_weighted_rate_sum",
        "music_weighted_z_mean",
        "music_weighted_rate_mean",
    ):
        merged[column] = merged[column].fillna(0)
    merged["music_count"] = merged["music_count"].astype(int)
    merged.insert(0, "site", site)
    merged["character_total_score"] = float(total_character_score)
    merged["music_total_score"] = float(total_music_score)
    return merged[
        [
            "site",
            "character",
            "character_score",
            "character_total_score",
            "character_rate",
            "character_z",
            "has_music_association",
            "music_count",
            "weight_sum",
            "music_weighted_z_sum",
            "music_weighted_z_mean",
            "music_weighted_rate_sum",
            "music_weighted_rate_mean",
            "music_total_score",
        ]
    ]


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    mapping = load_last_sheet(WORKSPACE / "fun.xlsx")
    name_map = dict(
        zip(
            mapping["日文名"].astype(str).str.strip(),
            mapping["译名"].astype(str).str.strip(),
        )
    )
    inputs = [
        WORKSPACE / "TouhouVote_cn.xlsx",
        WORKSPACE / "TouhouVote_cn_grouped.xlsx",
        WORKSPACE / "TouhouVote_jp.xlsx",
        WORKSPACE / "TouhouVote_jp_grouped.xlsx",
        WORKSPACE / "TouhouVote_music_cn.xlsx",
        WORKSPACE / "TouhouVote_music_cn_grouped.xlsx",
        WORKSPACE / "TouhouVote_music_jp.xlsx",
        WORKSPACE / "TouhouVote_music_jp_grouped.xlsx",
        WORKSPACE / "fun.xlsx",
    ]
    cn = build_site(
        site="cn",
        character_raw=inputs[0],
        character_grouped=inputs[1],
        music_raw=inputs[4],
        music_grouped=inputs[5],
        character_name_column="译名",
        music_vote_column="票数",
        name_map=name_map,
    )
    jp = build_site(
        site="jp",
        character_raw=inputs[2],
        character_grouped=inputs[3],
        music_raw=inputs[6],
        music_grouped=inputs[7],
        character_name_column="日文名",
        music_vote_column="得票数",
        name_map=name_map,
    )
    long = pd.concat([cn, jp], ignore_index=True)
    long_path = OUT_ROOT / "character_music_metrics.csv"
    long.to_csv(long_path, index=False, encoding="utf-8-sig")

    correlations = []
    for site, frame in (("cn", cn), ("jp", jp)):
        observed = frame[frame["has_music_association"]].copy()
        for universe_name, universe_frame in (
            ("matched_characters_only", observed),
            ("all_characters_missing_music_as_zero", frame),
        ):
            correlations.append(
                correlation_record(
                    universe_frame,
                    "character_z",
                    "music_weighted_z_sum",
                    site=site,
                    metric="weighted_sum",
                    universe=universe_name,
                )
            )
            correlations.append(
                correlation_record(
                    universe_frame,
                    "character_z",
                    "music_weighted_z_mean",
                    site=site,
                    metric="weighted_mean",
                    universe=universe_name,
                )
            )
        correlations.append(
            correlation_record(
                observed,
                "music_count",
                "music_weighted_z_sum",
                site=site,
                metric="song_count_vs_weighted_sum",
                universe="matched_characters_only",
            )
        )
        correlations.append(
            correlation_record(
                observed,
                "music_count",
                "music_weighted_z_mean",
                site=site,
                metric="song_count_vs_weighted_mean",
                universe="matched_characters_only",
            )
        )

    correlations_path = OUT_ROOT / "correlations.csv"
    pd.DataFrame(correlations).to_csv(correlations_path, index=False, encoding="utf-8-sig")
    report = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "method": {
            "weights": [1.0, 0.75, 0.5, "0.25 for every subsequent associated track"],
            "weighted_sum": "sum(weight_i * music_z_i)",
            "weighted_mean": "sum(weight_i * music_z_i) / sum(weight_i)",
            "ordering": "associated tracks sorted by within-site music z-score descending",
            "bootstrap": "paired nonparametric percentile interval; seed=352; B=5000",
        },
        "correlations": correlations,
        "input_files": [
            {
                "path": path.relative_to(WORKSPACE).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in inputs
        ],
        "output_files": [
            {
                "path": path.relative_to(WORKSPACE).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in (long_path, correlations_path)
        ],
    }
    with (OUT_ROOT / "report.json").open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(correlations, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
