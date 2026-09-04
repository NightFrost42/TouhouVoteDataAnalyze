from __future__ import annotations

import csv
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUND = 21
RAW_DIR = ROOT / "data_raw" / "jp_official" / f"round_{ROUND}"
OUTPUT_DIR = ROOT / "analysis_results" / "social_triangulation"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def pct(numerator: int, denominator: int) -> float:
    return round(100 * numerator / denominator, 4) if denominator else 0.0


def questionnaire_summary(questionnaire: dict, detail_rows: list[dict]) -> dict:
    data = questionnaire["data"]
    age_n = sum(row["count"] for row in data["age"])
    under20_n = sum(
        row["count"] for row in data["age"] if int(row["value"]) <= 19
    )
    trigger_n = sum(row["count"] for row in data["trigger"])
    youtube = next(
        row for row in data["trigger"] if row["label"].startswith("Youtube")
    )
    voted_n = sum(row["count"] for row in data["voted"])
    first_time = next(
        row for row in data["voted"] if row["label"] == "今回がはじめて"
    )

    top3 = []
    for row in sorted(detail_rows, key=lambda item: item["official_rank"])[:3]:
        detail = row["detail"]
        ages = detail["questionnaire"]["age"]
        entity_age_n = sum(item["count"] for item in ages)
        entity_under20_n = sum(
            item["count"]
            for item in ages
            if item["label"] in {"～9歳", "10～14歳", "15～19歳"}
        )
        entity_first_time = next(
            item
            for item in detail["questionnaire"]["voted"]
            if item["label"] == "今回がはじめて"
        )
        top3.append(
            {
                "official_rank": row["official_rank"],
                "name": row["name"],
                "age_respondent_n": entity_age_n,
                "under20_count": entity_under20_n,
                "under20_share_pct": pct(entity_under20_n, entity_age_n),
                "first_time_poll_share_pct": round(
                    100 * entity_first_time["rate"], 4
                ),
            }
        )

    return {
        "round": ROUND,
        "age": {
            "respondent_n": age_n,
            "under20_count": under20_n,
            "under20_share_pct": pct(under20_n, age_n),
        },
        "discovery_trigger": {
            "respondent_n": trigger_n,
            "youtube_count": youtube["count"],
            "youtube_share_pct": round(100 * youtube["rate"], 4),
        },
        "poll_history": {
            "respondent_n": voted_n,
            "first_time_count": first_time["count"],
            "first_time_share_pct": round(100 * first_time["rate"], 4),
        },
        "top3_entity_questionnaire": top3,
        "caution": (
            "All questionnaire figures describe voluntary respondents. Entity-level "
            "questionnaires have their own denominators and do not identify a causal "
            "effect of social-media exposure."
        ),
    }


def feedback_theme_summary(questionnaire: dict) -> list[dict]:
    feedback = questionnaire["data"]["feedback"]
    patterns = {
        "scoring_or_primary_secondary_pick": re.compile(
            r"一押し|一推し|1推し|イチオシ|二押し|2推し|2ポイント|3ポイント"
        ),
        "number_of_vote_slots": re.compile(r"投票枠|枠を増|持ち票"),
        "fraud_or_verification": re.compile(r"不正|複垢|フリーメール"),
        "social_media_or_post_result_discussion": re.compile(
            r"SNS|Twitter|ツイッター|YouTube|公式X"
        ),
    }
    rows = []
    for theme, pattern in patterns.items():
        mentions = sum(bool(pattern.search(comment)) for comment in feedback)
        rows.append(
            {
                "theme": theme,
                "matching_feedback_count": mentions,
                "all_feedback_count": len(feedback),
                "matching_feedback_share_pct": pct(mentions, len(feedback)),
                "interpretation_limit": (
                    "Substring-coded mentions in self-selected open text; not an "
                    "estimate of support, opposition, or population opinion share."
                ),
            }
        )
    return rows


def character_counterfactual() -> list[dict]:
    aggregate = load_json(RAW_DIR / "aggregate" / "character.json")["data"]
    official_rank = {int(row["code"]): int(row["rank"]) for row in aggregate}
    details = []
    for path in (RAW_DIR / "detail" / "character").glob("*.json"):
        detail = load_json(path)["data"]
        required = ("id", "name", "point", "primary", "secondary")
        if not all(detail.get(key) is not None for key in required):
            continue
        entity_id = int(detail["id"])
        if entity_id not in official_rank:
            continue
        published = int(detail["point"])
        primary = int(detail["primary"])
        secondary = int(detail["secondary"])
        other_one_point_votes = published - 3 * primary - 2 * secondary
        if other_one_point_votes < 0:
            raise ValueError(f"Negative one-point vote count for {detail['name']}")
        old_scheme = 2 * primary + secondary + other_one_point_votes
        if old_scheme != published - primary - secondary:
            raise AssertionError("Counterfactual scoring identity failed")
        details.append(
            {
                "entity_id": entity_id,
                "name": detail["name"],
                "official_rank": official_rank[entity_id],
                "published_points_3_2_1": published,
                "primary_count_3pt": primary,
                "secondary_count_2pt": secondary,
                "other_count_1pt": other_one_point_votes,
                "counterfactual_points_2_1": old_scheme,
                "detail": detail,
            }
        )

    ordered = sorted(
        details,
        key=lambda row: (
            -row["counterfactual_points_2_1"],
            row["official_rank"],
            row["name"],
        ),
    )
    for index, row in enumerate(ordered, start=1):
        row["counterfactual_rank_2_1"] = index
        row["rank_change_old_minus_official"] = row["official_rank"] - index
    return ordered


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    counterfactual = character_counterfactual()
    questionnaire = load_json(RAW_DIR / "aggregate" / "questionnaire.json")
    feedback = feedback_theme_summary(questionnaire)
    summary = questionnaire_summary(questionnaire, counterfactual)

    write_csv(
        OUTPUT_DIR / "round21_character_scoring_counterfactual.csv",
        counterfactual,
        [
            "entity_id",
            "name",
            "official_rank",
            "counterfactual_rank_2_1",
            "rank_change_old_minus_official",
            "published_points_3_2_1",
            "counterfactual_points_2_1",
            "primary_count_3pt",
            "secondary_count_2pt",
            "other_count_1pt",
        ],
    )
    write_csv(
        OUTPUT_DIR / "round21_feedback_theme_mentions.csv",
        feedback,
        [
            "theme",
            "matching_feedback_count",
            "all_feedback_count",
            "matching_feedback_share_pct",
            "interpretation_limit",
        ],
    )
    report = {
        "schema_version": 1,
        "round": ROUND,
        "source_files": {
            "aggregate_character": str(
                (RAW_DIR / "aggregate" / "character.json").relative_to(ROOT)
            ),
            "aggregate_questionnaire": str(
                (RAW_DIR / "aggregate" / "questionnaire.json").relative_to(ROOT)
            ),
            "character_details": str(
                (RAW_DIR / "detail" / "character").relative_to(ROOT)
            ),
        },
        "scoring": {
            "published_scheme": "primary=3, secondary=2, other selected=1",
            "counterfactual_scheme": "primary=2, all other selected=1",
            "formula": "counterfactual = published - primary - secondary",
            "top10_counterfactual": [
                {key: value for key, value in row.items() if key != "detail"}
                for row in counterfactual[:10]
            ],
        },
        "questionnaire": summary,
        "feedback_theme_mentions": feedback,
    }
    with (OUTPUT_DIR / "report.json").open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
