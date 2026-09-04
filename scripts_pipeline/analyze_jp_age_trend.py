"""Build a comparable under-20 share series from official JP questionnaires."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


WORKSPACE = Path(__file__).resolve().parents[1]
LEGACY_PATH = WORKSPACE / "data_processed" / "jp_official_legacy" / "questionnaire_long.csv"
MODERN_PATH = WORKSPACE / "data_processed" / "jp_official" / "questionnaire_long.csv"
OUT_ROOT = WORKSPACE / "analysis_results" / "jp_age_trend"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + 1 + end) / 2.0
        for position in order[start:end]:
            ranks[position] = rank
        start = end
    return ranks


def pearson(x: list[float], y: list[float]) -> float:
    x_mean = mean(x)
    y_mean = mean(y)
    numerator = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y))
    denominator = math.sqrt(
        sum((a - x_mean) ** 2 for a in x) * sum((b - y_mean) ** 2 for b in y)
    )
    return numerator / denominator if denominator else float("nan")


def summarize(rows: list[dict[str, Any]], start: int, end: int) -> dict[str, Any]:
    selected = [row for row in rows if start <= row["round"] <= end]
    x = [float(row["round"]) for row in selected]
    y = [float(row["under20_share"]) for row in selected]
    x_mean = mean(x)
    y_mean = mean(y)
    slope = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y)) / sum(
        (a - x_mean) ** 2 for a in x
    )
    return {
        "round_start": start,
        "round_end": end,
        "n_rounds": len(selected),
        "start_share": y[0],
        "end_share": y[-1],
        "change_percentage_points": (y[-1] - y[0]) * 100,
        "ols_slope_percentage_points_per_round": slope * 100,
        "spearman_round_vs_under20_share": pearson(average_ranks(x), average_ranks(y)),
        "minimum": min(y),
        "maximum": max(y),
    }


def legacy_rows() -> list[dict[str, Any]]:
    rows = read_csv(LEGACY_PATH)
    groups: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        primary_age = row["question"] in {"1.年齢", "01.年齢"}
        player_age = row["question"] == "１．プレイヤー層調査" and "■年齢" in row["item"]
        if not (primary_age or player_age):
            continue
        key = (row["round"], row["question_id"], row["source_table_index"], row["item"])
        groups[key].append(row)

    by_round: dict[int, list[list[dict[str, str]]]] = defaultdict(list)
    for (round_text, _question_id, _table, _item), group in groups.items():
        denominators = {row["denominator"] for row in group if row["denominator"]}
        if len(denominators) != 1:
            continue
        denominator = float(next(iter(denominators)))
        if not math.isclose(sum(float(row["count"]) for row in group), denominator):
            continue
        by_round[int(round_text)].append(group)

    result = []
    for round_number in sorted(by_round):
        # The official pages often publish both 10 broad bins and an exact-age
        # table.  Select the shortest complete table to keep a stable 3-bin
        # definition: <10, 10--14, 15--19.
        group = min(by_round[round_number], key=len)
        group.sort(key=lambda row: int(row["source_row_index"] or 0))
        denominator = int(float(group[0]["denominator"]))
        under20_count = sum(int(float(row["count"])) for row in group[:3])
        result.append(
            {
                "round": round_number,
                "under20_count": under20_count,
                "respondent_n": denominator,
                "under20_share": under20_count / denominator,
                "source_generation": "legacy_official",
                "age_representation": "official broad bins; first three bins through 15-19",
                "source_url": group[0]["source_url"],
                "source_file": group[0]["source_file"],
            }
        )
    return result


def modern_rows() -> list[dict[str, Any]]:
    rows = [row for row in read_csv(MODERN_PATH) if row["question_key"] == "age"]
    by_round: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_round[int(row["round"])].append(row)
    result = []
    for round_number in sorted(by_round):
        group = by_round[round_number]
        denominator_values = {
            int(float(row["conditional_denominator_derived"]))
            for row in group
            if row["conditional_denominator_derived"]
        }
        if len(denominator_values) != 1:
            raise ValueError(f"round {round_number}: non-unique age denominator")
        denominator = next(iter(denominator_values))
        under20_count = sum(
            int(float(row["count"]))
            for row in group
            if row["value"] and float(row["value"]) <= 19
        )
        result.append(
            {
                "round": round_number,
                "under20_count": under20_count,
                "respondent_n": denominator,
                "under20_share": under20_count / denominator,
                "source_generation": "modern_official",
                "age_representation": "official exact ages; summed ages <=19",
                "source_url": "https://toho-vote.info/",
                "source_file": "data_processed/jp_official/questionnaire_long.csv",
            }
        )
    return result


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = legacy_rows() + modern_rows()
    rows.sort(key=lambda row: row["round"])
    expected = list(range(5, 22))
    observed = [row["round"] for row in rows]
    if observed != expected:
        raise ValueError(f"age series coverage mismatch: expected {expected}, observed {observed}")

    csv_path = OUT_ROOT / "under20_share_by_round.csv"
    fields = list(rows[0])
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    summaries = [summarize(rows, 5, 20), summarize(rows, 17, 20), summarize(rows, 5, 21)]
    report = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "definition": "share of age-question respondents aged 19 or younger",
        "scope_warning": (
            "repeated cross-sectional voluntary respondents; this is not personal retention, "
            "and changes can reflect response composition or questionnaire design"
        ),
        "rounds_3_4": "the official questionnaires did not publish a comparable age table",
        "series": rows,
        "trend_summaries": summaries,
        "inputs": [
            {
                "path": path.relative_to(WORKSPACE).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in (LEGACY_PATH, MODERN_PATH)
        ],
        "output": {
            "path": csv_path.relative_to(WORKSPACE).as_posix(),
            "bytes": csv_path.stat().st_size,
            "sha256": sha256_file(csv_path),
        },
    }
    report_path = OUT_ROOT / "report.json"
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    primary = summaries[0]
    recent = summaries[1]
    summary_path = OUT_ROOT / "summary.md"
    summary_path.write_text(
        "\n".join(
            [
                "# 日文官方问卷年龄趋势",
                "",
                "口径：每届年龄题回答者中19岁及以下的比例。第3、4回没有可比年龄表；第5—16回来自日本官方旧站，第17回以后来自现官方站。",
                "",
                f"- 第5回：{primary['start_share']:.2%}；第20回：{primary['end_share']:.2%}，相差{primary['change_percentage_points']:.2f}个百分点。",
                f"- 第5—20回线性斜率：每届{primary['ols_slope_percentage_points_per_round']:.3f}个百分点；届次与比例的Spearman ρ={primary['spearman_round_vs_under20_share']:.4f}。",
                f"- 仅看第17—20回：{recent['start_share']:.2%}→{recent['end_share']:.2%}，相差{recent['change_percentage_points']:.2f}个百分点，不能据此替代完整时间序列。",
                "- 这是自愿问卷的重复横截面，只能称回答者年龄构成变化，不能称个人留存或世代交替已经完成。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(report["trend_summaries"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
