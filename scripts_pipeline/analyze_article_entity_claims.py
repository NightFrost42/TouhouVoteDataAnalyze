"""Recompute article claims that depend on JP20 per-item supplemental data.

The official detail modules publish entity-specific questionnaire marginals and
only the leading association rows.  This script therefore distinguishes exact
numeric comparisons from a mere absence in the published top lists.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


WORKSPACE = Path(__file__).resolve().parents[1]
QUESTIONNAIRE_PATH = (
    WORKSPACE / "data_processed" / "jp_official" / "detail_questionnaire_long.csv"
)
ASSOCIATION_PATH = (
    WORKSPACE / "data_processed" / "jp_official" / "detail_associations.csv"
)
OUTPUT_ROOT = WORKSPACE / "analysis_results" / "article_entity_claims"


COGNITION_WINDOWS = {
    "少名 針妙丸": [
        "求聞口授～輝針城（2013年8月）",
        "輝針城～アマノジャク（2014年5月）",
    ],
    "摩多羅隠岐奈": [
        "旧約酒場～天空璋（2017年8月）",
        "天空璋～ナイトメアダイアリー（2018年8月）",
    ],
    "ヘカーティア・ラピスラズリ": [
        "アマノジャク～紺珠伝（2015年8月）",
        "紺珠伝～旧約酒場（2016年8月）",
    ],
}

MAGUS_NIGHT_WINDOW = [
    "星蓮船～妖精大戦争（2010年8月）",
    "妖精大戦争～神霊廟（2011年8月）",
    "神霊廟～求聞口授（2012年4月）",
    "求聞口授～輝針城（2013年8月）",
    "輝針城～アマノジャク（2014年5月）",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def number(row: dict[str, str], key: str) -> float:
    value = row.get(key, "")
    if value == "":
        raise ValueError(f"missing numeric field {key}: {row}")
    return float(value)


def integer(row: dict[str, str], key: str) -> int:
    value = number(row, key)
    if not value.is_integer():
        raise ValueError(f"expected integer {key}, got {value}: {row}")
    return int(value)


def write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    materialized = list(rows)
    fields: list[str] = []
    for row in materialized:
        for key in row:
            if key not in fields:
                fields.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(materialized)
    return len(materialized)


def aggregate_window(
    rows: list[dict[str, str]], labels: list[str], *, subject: str
) -> dict[str, Any]:
    selected = [row for row in rows if row["label"] in labels]
    if {row["label"] for row in selected} != set(labels):
        missing = sorted(set(labels) - {row["label"] for row in selected})
        raise AssertionError(f"{subject}: missing labels {missing}")
    conditional_ns = {
        integer(row, "conditional_denominator_derived")
        for row in rows
        if row.get("conditional_denominator_derived", "") != ""
    }
    overall_ns = {integer(row, "overall_denominator") for row in rows}
    if len(conditional_ns) != 1 or len(overall_ns) != 1:
        raise AssertionError(
            f"{subject}: inconsistent denominators conditional={conditional_ns}, overall={overall_ns}"
        )
    conditional_n = next(iter(conditional_ns))
    overall_n = next(iter(overall_ns))
    conditional_count = sum(integer(row, "count") for row in selected)
    # Aggregate ``total`` is an exact official rate in the modern modules.
    # Recovering its numerator with the independently published questionnaire
    # denominator is safe here and is validated to integer precision below.
    overall_float_count = sum(number(row, "total") * overall_n for row in selected)
    overall_count = round(overall_float_count)
    rounding_error = abs(overall_float_count - overall_count)
    if rounding_error >= 1e-7:
        raise AssertionError(f"{subject}: aggregate numerator is not integral")
    conditional_rate = conditional_count / conditional_n
    overall_rate = overall_count / overall_n
    return {
        "subject": subject,
        "labels_json": json.dumps(labels, ensure_ascii=False),
        "conditional_count": conditional_count,
        "conditional_n": conditional_n,
        "conditional_rate": conditional_rate,
        "overall_count": overall_count,
        "overall_n": overall_n,
        "overall_rate": overall_rate,
        "difference_percentage_points": 100 * (conditional_rate - overall_rate),
        "lift": conditional_rate / overall_rate,
        "overall_count_rounding_error": rounding_error,
    }


def main() -> None:
    questionnaire = read_csv(QUESTIONNAIRE_PATH)
    associations = read_csv(ASSOCIATION_PATH)

    cognition_rows = [
        row
        for row in questionnaire
        if row["round"] == "20"
        and row["question_key"] == "cognition"
        and (
            (
                row["source_category"] == "character"
                and row["source_name"] in COGNITION_WINDOWS
            )
            or (
                row["source_category"] == "music"
                and row["source_name"] == "メイガスナイト"
            )
        )
    ]
    if not cognition_rows:
        raise AssertionError("JP20 cognition detail rows were not found")

    cognition_denominators: dict[tuple[str, str], int] = {}
    for source_category, source_name in {
        (row["source_category"], row["source_name"]) for row in cognition_rows
    }:
        candidates = {
            integer(row, "conditional_denominator_derived")
            for row in cognition_rows
            if row["source_category"] == source_category
            and row["source_name"] == source_name
            and row.get("conditional_denominator_derived", "") != ""
        }
        if len(candidates) != 1:
            raise AssertionError(
                f"{source_category}/{source_name}: inconsistent cognition denominators {candidates}"
            )
        cognition_denominators[(source_category, source_name)] = next(iter(candidates))

    profile_rows: list[dict[str, Any]] = []
    for row in cognition_rows:
        conditional_rate = number(row, "rate")
        overall_rate = number(row, "total")
        profile_rows.append(
            {
                "round": 20,
                "source_category": row["source_category"],
                "source_name": row["source_name"],
                "label": row["label"],
                "count": integer(row, "count"),
                "conditional_n": cognition_denominators[
                    (row["source_category"], row["source_name"])
                ],
                "conditional_rate": conditional_rate,
                "overall_n": integer(row, "overall_denominator"),
                "overall_rate": overall_rate,
                "difference_percentage_points": 100
                * (conditional_rate - overall_rate),
                "lift": conditional_rate / overall_rate if overall_rate else None,
            }
        )

    cohort_summaries: list[dict[str, Any]] = []
    for name, labels in COGNITION_WINDOWS.items():
        rows = [
            row
            for row in cognition_rows
            if row["source_category"] == "character" and row["source_name"] == name
        ]
        cohort_summaries.append(
            {
                "claim": "debut_period_cognition_overrepresentation",
                **aggregate_window(rows, labels, subject=name),
            }
        )

    magus_rows = [
        row
        for row in cognition_rows
        if row["source_category"] == "music" and row["source_name"] == "メイガスナイト"
    ]
    magus_summary = {
        "claim": "magus_night_roughly_10_to_15_year_cognition_window",
        **aggregate_window(
            magus_rows,
            MAGUS_NIGHT_WINDOW,
            subject="メイガスナイト（2009年8月～2014年5月に知った層）",
        ),
    }

    fairy_wars_candidates = [
        row
        for row in associations
        if row["round"] == "20"
        and row["source_category"] == "music"
        and row["source_name"] == "メイガスナイト"
        and row["target_category"] == "work"
        and row["target_name"] == "妖精大戦争"
        and row["ordering"] == "count"
    ]
    if len(fairy_wars_candidates) != 1:
        raise AssertionError(
            f"expected one Magus Night -> Fairy Wars count row, got {len(fairy_wars_candidates)}"
        )
    fairy = fairy_wars_candidates[0]
    fairy_rate = number(fairy, "rate")
    fairy_total = number(fairy, "total")
    fairy_summary = {
        "claim": "magus_night_fairy_wars_covote",
        "subject": "メイガスナイト → 妖精大戦争",
        "intersection_count": integer(fairy, "count"),
        "association_conditional_n": integer(
            fairy, "conditional_denominator_derived"
        ),
        "association_denominator_basis": (
            "derived from the official intersection count and published conditional rate; "
            "for a cross-department association it is not asserted to equal all track voters"
        ),
        "conditional_rate": fairy_rate,
        "overall_rate_published": fairy_total,
        "difference_percentage_points": 100 * (fairy_rate - fairy_total),
        "lift": fairy_rate / fairy_total,
        "published_count_position": integer(fairy, "position"),
    }

    reciprocal_specs = [("饕餮 尤魔", "八雲 藍"), ("八雲 藍", "饕餮 尤魔")]
    reciprocal_rows: list[dict[str, Any]] = []
    for source_name, target_name in reciprocal_specs:
        relevant = [
            row
            for row in associations
            if row["round"] == "20"
            and row["source_category"] == "character"
            and row["source_name"] == source_name
            and row["target_category"] == "character"
        ]
        count_rows = [row for row in relevant if row["ordering"] == "count"]
        diff_rows = [row for row in relevant if row["ordering"] == "diff"]
        exact_rows = [row for row in relevant if row["target_name"] == target_name]
        if len(count_rows) != 10 or len(diff_rows) != 5:
            raise AssertionError(
                f"{source_name}: expected official top10 count/top5 diff lists"
            )
        reciprocal_rows.append(
            {
                "round": 20,
                "source_name": source_name,
                "target_name": target_name,
                "present_in_published_count_top10": any(
                    row["target_name"] == target_name for row in count_rows
                ),
                "present_in_published_diff_top5": any(
                    row["target_name"] == target_name for row in diff_rows
                ),
                "exact_pair_metrics_published": bool(exact_rows),
                "count_top10_last_count": min(integer(row, "count") for row in count_rows),
                "count_top10_last_rate": min(number(row, "rate") for row in count_rows),
                "diff_top5_last_difference_points": min(
                    number(row, "diff") for row in diff_rows
                ),
                "interpretation": (
                    "only absence from the official leading lists is established; "
                    "the exact pair intersection is not published in this detail module"
                ),
            }
        )

    output_counts = {
        "cognition_profiles.csv": write_csv(
            OUTPUT_ROOT / "cognition_profiles.csv", profile_rows
        ),
        "cohort_claim_summary.csv": write_csv(
            OUTPUT_ROOT / "cohort_claim_summary.csv",
            [*cohort_summaries, magus_summary],
        ),
        "yuma_ran_published_bounds.csv": write_csv(
            OUTPUT_ROOT / "yuma_ran_published_bounds.csv", reciprocal_rows
        ),
        "claim_metrics.csv": write_csv(
            OUTPUT_ROOT / "claim_metrics.csv",
            [*cohort_summaries, magus_summary, fairy_summary],
        ),
    }

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "scope": "JP20 entity-level supplemental data used by article V3.5.2",
        "inputs": [
            {
                "path": QUESTIONNAIRE_PATH.relative_to(WORKSPACE).as_posix(),
                "bytes": QUESTIONNAIRE_PATH.stat().st_size,
                "sha256": sha256_file(QUESTIONNAIRE_PATH),
            },
            {
                "path": ASSOCIATION_PATH.relative_to(WORKSPACE).as_posix(),
                "bytes": ASSOCIATION_PATH.stat().st_size,
                "sha256": sha256_file(ASSOCIATION_PATH),
            },
        ],
        "output_rows": output_counts,
        "cohort_summaries": cohort_summaries,
        "magus_night_cognition": magus_summary,
        "magus_night_fairy_wars": fairy_summary,
        "yuma_ran": reciprocal_rows,
        "validations": {
            "all_expected_cognition_profiles_present": len(profile_rows) == 100,
            "all_cohort_windows_have_exact_integer_numerators": all(
                row["overall_count_rounding_error"] < 1e-7
                for row in [*cohort_summaries, magus_summary]
            ),
            "magus_night_fairy_wars_exact_row_present": True,
            "yuma_ran_exact_pair_not_published_both_directions": all(
                not row["exact_pair_metrics_published"] for row in reciprocal_rows
            ),
        },
    }
    if not all(report["validations"].values()):
        raise AssertionError(json.dumps(report["validations"], ensure_ascii=False))
    report_path = OUTPUT_ROOT / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# 文章实体级附加数据复算",
        "",
        "所有数值由 `scripts_pipeline/analyze_article_entity_claims.py` 从日文官方第20回实体详情长表计算。",
        "",
        "## 入坑时期与角色",
        "",
        "| 角色 | 登场前后窗口 | 角色回答者 | 全体回答者 | 差值 | lift |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in cohort_summaries:
        lines.append(
            f"| {row['subject']} | {row['labels_json']} | "
            f"{row['conditional_count']}/{row['conditional_n']} "
            f"({row['conditional_rate']:.2%}) | "
            f"{row['overall_count']}/{row['overall_n']} ({row['overall_rate']:.2%}) | "
            f"{row['difference_percentage_points']:+.2f}个百分点 | {row['lift']:.3f} |"
        )
    lines.extend(
        [
            "",
            "三名角色的登场前后入坑桶都高于全体基线，支持‘队列关联’，但不证明对应作品使这些人入坑，也不证明这种关联会维持未来人气。",
            "",
            "## Magus Night",
            "",
            f"2009年8月至2014年5月间知晓东方者为 {magus_summary['conditional_count']}/{magus_summary['conditional_n']} "
            f"({magus_summary['conditional_rate']:.2%})，全体基线为 {magus_summary['overall_count']}/{magus_summary['overall_n']} "
            f"({magus_summary['overall_rate']:.2%})，lift={magus_summary['lift']:.3f}。该时期确有过度代表，但并非多数。",
            "",
            f"在官方作品关联表的可比条件总体中，有 {fairy_summary['intersection_count']}/{fairy_summary['association_conditional_n']} "
            f"({fairy_summary['conditional_rate']:.2%}) 的 Magus Night 投票与《妖精大战争》共现；其总体率为 "
            f"{fairy_summary['overall_rate_published']:.2%}；差值 {fairy_summary['difference_percentage_points']:+.2f}个百分点，"
            f"lift={fairy_summary['lift']:.3f}。这里的可验证对象是作品《妖精大战争》，不能扩写成对所有妖精角色的共投。",
            "",
            "## 尤魔—八云蓝",
            "",
            "两者在双向的官方‘共投数前10’和‘超额百分点前5’列表中都未出现；但详情模块没有发布这对组合的精确交集。因而只能写‘未进入彼此关联前列’，不能据此推出‘多数人只投其中一方’。",
            "",
        ]
    )
    (OUTPUT_ROOT / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({"output_rows": output_counts, "validations": report["validations"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
