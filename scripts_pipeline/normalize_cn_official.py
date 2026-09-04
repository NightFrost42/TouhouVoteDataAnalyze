"""Normalize the Chinese official round 10/11 result archive.

The crawler stores provenance-wrapped JSON checkpoints.  This program turns
those checkpoints into analysis-ready CSV tables without making network
requests.  Large tables are streamed into gzip-compressed CSV files so every
published numeric record can be retained without loading the whole corpus in
memory.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


WORKSPACE = Path(__file__).resolve().parents[1]
RAW_ROOT = WORKSPACE / "data_raw" / "cn_official"
OUT_ROOT = WORKSPACE / "data_processed" / "cn_official"
REPORT_PATH = WORKSPACE / "metadata" / "cn_official_normalization_report.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scalar(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


@contextmanager
def atomic_text_writer(path: Path, *, gzip_compressed: bool = False) -> Iterator[Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = ".tmp.gz" if gzip_compressed else ".tmp"
    fd, temporary_name = tempfile.mkstemp(prefix=path.stem + ".", suffix=suffix, dir=path.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        if gzip_compressed:
            handle = gzip.open(temporary, "wt", encoding="utf-8-sig", newline="")
        else:
            handle = temporary.open("w", encoding="utf-8-sig", newline="")
        with handle:
            yield handle
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    with atomic_text_writer(path, gzip_compressed=path.suffix == ".gz") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: scalar(row.get(key)) for key in fieldnames})
            count += 1
    return count


def normalize_question_id(value: Any) -> str:
    text = str(value)
    return text[1:] if text.startswith("q") else text


def cp_name(value: Any) -> tuple[Any, Any, Any, str]:
    if not isinstance(value, Mapping):
        return None, None, None, str(value or "")
    members = [value.get("a"), value.get("b"), value.get("c")]
    display = " × ".join(str(item) for item in members if item)
    return members[0], members[1], members[2], display


def safe_divide(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def association_metrics(item: Mapping[str, Any]) -> dict[str, Any]:
    """Compute association metrics using the official API's cell convention.

    The result service encodes ``0`` as selected and ``1`` as not selected:
    ``m00`` is therefore the co-selection/intersection cell, while ``m11`` is
    neither selected.  This is verified against official conditional ranking
    counts during crawling and must not be silently replaced by the more common
    binary convention where ``m11`` denotes the intersection.
    """
    m00 = int(item.get("m00") or 0)
    m01 = int(item.get("m01") or 0)
    m10 = int(item.get("m10") or 0)
    m11 = int(item.get("m11") or 0)
    universe = m00 + m01 + m10 + m11
    count_a = m00 + m10
    count_b = m00 + m01
    union = m00 + m10 + m01
    expected = safe_divide(count_a * count_b, universe)
    lift = safe_divide(m00 * universe, count_a * count_b)
    pmi = math.log(lift) if lift is not None and lift > 0 else None
    joint_probability = safe_divide(m00, universe)
    if pmi is None or joint_probability is None or not 0 < joint_probability < 1:
        npmi = None
    else:
        npmi = pmi / -math.log(joint_probability)
    phi_denominator = math.sqrt(
        count_a * (universe - count_a) * count_b * (universe - count_b)
    )
    phi = (
        (m11 * m00 - m10 * m01) / phi_denominator
        if phi_denominator
        else None
    )
    return {
        "m00": m00,
        "m01": m01,
        "m10": m10,
        "m11": m11,
        "universe_n": universe,
        "count_a": count_a,
        "count_b": count_b,
        "count_ab": m00,
        "p_b_given_a": safe_divide(m00, count_a),
        "p_a_given_b": safe_divide(m00, count_b),
        "lift": lift,
        "jaccard": safe_divide(m00, union),
        "pmi": pmi,
        "npmi": npmi,
        "expected_independent": expected,
        "cosine": safe_divide(m00, math.sqrt(count_a * count_b)),
        "phi": phi,
    }


def iter_rankings(round_number: int, base: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    data = base["data"]
    keys = {
        "character": "queryCharacterRanking",
        "music": "queryMusicRanking",
        "cp": "queryCPRanking",
    }
    for category, key in keys.items():
        result = data[key]
        department_n = data["queryGlobalStats"].get(
            {"character": "numChar", "music": "numMusic", "cp": "numCp"}[category]
        )
        for entry in result.get("entries", []):
            cp_a, cp_b, cp_c, cp_display = cp_name(entry.get("cp"))
            yield {
                "round": round_number,
                "category": category,
                "rank": entry.get("rank"),
                "display_rank": entry.get("displayRank"),
                "name": entry.get("name") or cp_display,
                "name_jpn": entry.get("nameJpn"),
                "cp_a": cp_a,
                "cp_b": cp_b,
                "cp_c": cp_c,
                "vote_count": entry.get("voteCount"),
                "first_vote_count": entry.get("firstVoteCount"),
                "first_vote_percentage": entry.get("firstVotePercentage"),
                "first_vote_count_weighted": entry.get("firstVoteCountWeighted"),
                "vote_percentage": entry.get("votePercentage"),
                "first_percentage": entry.get("firstPercentage"),
                "male_vote_count": entry.get("maleVoteCount"),
                "male_percentage_per_item": entry.get("malePercentagePerChar"),
                "male_percentage_per_total": entry.get("malePercentagePerTotal"),
                "female_vote_count": entry.get("femaleVoteCount"),
                "female_percentage_per_item": entry.get("femalePercentagePerChar"),
                "female_percentage_per_total": entry.get("femalePercentagePerTotal"),
                "department_voter_n": department_n,
                "album": entry.get("album"),
                "character_type": entry.get("characterType"),
                "character_origin": entry.get("characterOrigin"),
                "first_appearance": entry.get("firstAppearance"),
                "a_active": entry.get("aActive"),
                "b_active": entry.get("bActive"),
                "c_active": entry.get("cActive"),
                "none_active": entry.get("noneActive"),
            }


def iter_questionnaire_rows(
    round_number: int,
    root: Path,
    question_by_id: Mapping[str, Mapping[str, Any]],
    option_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
) -> Iterator[dict[str, Any]]:
    path = root / "questionnaire" / "categorical_results.json"
    if not path.exists():
        return
    data = load_json(path)["data"]["queryQuestionnaire"]
    for entry in data.get("entries", []):
        question_id = normalize_question_id(entry.get("questionId"))
        question = question_by_id.get(question_id, {})
        total_answers = entry.get("totalAnswers")
        total_male = entry.get("totalMale")
        total_female = entry.get("totalFemale")
        for answer in entry.get("answersCat") or []:
            answer_id = normalize_question_id(answer.get("aid"))
            option = option_by_key.get((question_id, answer_id), {})
            count = answer.get("totalVotes")
            male_count = answer.get("maleVotes")
            female_count = answer.get("femaleVotes")
            yield {
                "round": round_number,
                "question_id": question_id,
                "answer_id": answer_id,
                "questionnaire_id": question.get("questionnaireId"),
                "questionnaire_name": question.get("questionnaireName"),
                "section_key": question.get("sectionKey"),
                "question_type": question.get("type"),
                "question": question.get("question"),
                "answer": option.get("content"),
                "option_index": option.get("optionIndex"),
                "count": count,
                "male_count": male_count,
                "female_count": female_count,
                "respondent_n": total_answers,
                "respondent_male_n": total_male,
                "respondent_female_n": total_female,
                "share": safe_divide(float(count or 0), float(total_answers or 0)),
                "male_share_within_answer": safe_divide(
                    float(male_count or 0), float(count or 0)
                ),
                "female_share_within_answer": safe_divide(
                    float(female_count or 0), float(count or 0)
                ),
            }


def iter_open_answers(
    round_number: int,
    root: Path,
    question_by_id: Mapping[str, Mapping[str, Any]],
) -> Iterator[dict[str, Any]]:
    path = root / "questionnaire" / "open_text_results.json"
    if not path.exists():
        return
    entries = load_json(path)["data"]["queryQuestionnaire"].get("entries", [])
    for entry in entries:
        question_id = normalize_question_id(entry.get("questionId"))
        question = question_by_id.get(question_id, {})
        for answer_index, answer in enumerate(entry.get("answersStr") or [], start=1):
            yield {
                "round": round_number,
                "question_id": question_id,
                "questionnaire_id": question.get("questionnaireId"),
                "questionnaire_name": question.get("questionnaireName"),
                "question": question.get("question"),
                "answer_index": answer_index,
                "answer_text": answer,
                "respondent_n": entry.get("totalAnswers"),
                "respondent_male_n": entry.get("totalMale"),
                "respondent_female_n": entry.get("totalFemale"),
            }


def iter_trends(round_number: int, root: Path) -> Iterator[dict[str, Any]]:
    path = root / "questionnaire" / "trends.json"
    if not path.exists():
        return
    for entry in load_json(path).get("entries", []):
        question_id = normalize_question_id(entry.get("questionId"))
        for series_name in ("trend", "trendFirst"):
            for point in entry.get(series_name) or []:
                yield {
                    "round": round_number,
                    "question_id": question_id,
                    "series": series_name,
                    "hours_since_open": point.get("hrs"),
                    "count": point.get("cnt"),
                }


def iter_conditions(round_number: int, root: Path) -> tuple[Iterator[dict[str, Any]], Iterator[dict[str, Any]]]:
    files = sorted((root / "conditions").glob("q*_a*.json"))

    def summaries() -> Iterator[dict[str, Any]]:
        for path in files:
            payload = load_json(path)
            context = payload.get("context") or {}
            stats = payload.get("data", {}).get("queryGlobalStats") or {}
            yield {
                "round": round_number,
                "question_id": context.get("questionId"),
                "answer_id": context.get("answerId"),
                "question_type": context.get("questionType"),
                "question": context.get("question"),
                "answer": context.get("answer"),
                "num_vote": stats.get("numVote"),
                "num_char": stats.get("numChar"),
                "num_music": stats.get("numMusic"),
                "num_cp": stats.get("numCp"),
                "num_doujin": stats.get("numDoujin"),
                "num_male": stats.get("numMale"),
                "num_female": stats.get("numFemale"),
                "source_file": path.relative_to(WORKSPACE).as_posix(),
            }

    def rankings() -> Iterator[dict[str, Any]]:
        category_keys = {
            "character": "queryCharacterRanking",
            "music": "queryMusicRanking",
            "cp": "queryCPRanking",
        }
        for path in files:
            payload = load_json(path)
            context = payload.get("context") or {}
            data = payload.get("data") or {}
            for category, key in category_keys.items():
                result = data.get(key) or {}
                global_stats = result.get("global") or {}
                for entry in result.get("entries") or []:
                    cp_a, cp_b, cp_c, cp_display = cp_name(entry.get("cp"))
                    yield {
                        "round": round_number,
                        "question_id": context.get("questionId"),
                        "answer_id": context.get("answerId"),
                        "category": category,
                        "rank": entry.get("rank"),
                        "display_rank": entry.get("displayRank"),
                        "name": entry.get("name") or cp_display,
                        "cp_a": cp_a,
                        "cp_b": cp_b,
                        "cp_c": cp_c,
                        "vote_count": entry.get("voteCount"),
                        "first_vote_count": entry.get("firstVoteCount"),
                        "filtered_department_n": global_stats.get("totalVotes"),
                        "filtered_unique_items": global_stats.get("totalUniqueItems"),
                        "source_file": path.relative_to(WORKSPACE).as_posix(),
                    }

    return summaries(), rankings()


def iter_covote(round_number: int, root: Path) -> Iterator[dict[str, Any]]:
    for category, filename, key in (
        ("character", "characters.json", "queryCharsCovote"),
        ("music", "music.json", "queryMusicsCovote"),
    ):
        path = root / "covote" / filename
        if not path.exists():
            continue
        payload = load_json(path)
        context = payload.get("context") or {}
        items = (payload.get("data", {}).get(key) or {}).get("items") or []
        for item in items:
            metrics = association_metrics(item)
            yield {
                "round": round_number,
                "category": category,
                "a": item.get("a"),
                "b": item.get("b"),
                **metrics,
                "official_cs": item.get("cs"),
                "official_mi": item.get("mi"),
                "official_cv": item.get("cv"),
                "response_mode": context.get("responseMode"),
                "source_file": path.relative_to(WORKSPACE).as_posix(),
            }


def normalize_round(round_number: int) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    root = RAW_ROOT / f"round_{round_number}"
    base_path = root / "graphql" / "base.json"
    if not base_path.exists():
        return {}, {"round": round_number, "available": False, "missing": [str(base_path)]}

    base = load_json(base_path)
    questions_path = root / "questionnaire" / "questions.json"
    options_path = root / "questionnaire" / "options.json"
    questions = load_json(questions_path) if questions_path.exists() else []
    options = load_json(options_path) if options_path.exists() else []
    question_by_id = {normalize_question_id(item.get("id")): item for item in questions}
    option_by_key = {
        (normalize_question_id(item.get("questionId")), normalize_question_id(item.get("answerId"))): item
        for item in options
    }

    stats = base["data"]["queryGlobalStats"]
    ballot_rows = [
        {"round": round_number, "category": category, "ballots": stats.get(field)}
        for category, field in (
            ("all", "numVote"),
            ("character", "numChar"),
            ("music", "numMusic"),
            ("cp", "numCp"),
            ("doujin", "numDoujin"),
            ("male", "numMale"),
            ("female", "numFemale"),
        )
    ]
    question_rows = []
    for item in questions:
        question_rows.append(
            {
                "round": round_number,
                "question_id": item.get("id"),
                "questionnaire_id": item.get("questionnaireId"),
                "questionnaire_name": item.get("questionnaireName"),
                "section_key": item.get("sectionKey"),
                "questionnaire_key": item.get("questionnaireKey"),
                "group_index": item.get("groupIndex"),
                "branch_index": item.get("branchIndex"),
                "question_type": item.get("type"),
                "question": item.get("question"),
                "introduction": item.get("introduction"),
                "input": item.get("input"),
                "option_count": item.get("optionCount"),
            }
        )
    option_rows = []
    for item in options:
        option_rows.append(
            {
                "round": round_number,
                "question_id": item.get("questionId"),
                "answer_id": item.get("answerId"),
                "question_type": item.get("questionType"),
                "question": item.get("question"),
                "option_index": item.get("optionIndex"),
                "answer": item.get("content"),
                "related_json": item.get("related"),
                "mutex_json": item.get("mutex"),
            }
        )

    completion_rows: list[dict[str, Any]] = []
    categorical_path = root / "questionnaire" / "categorical_results.json"
    if categorical_path.exists():
        completion = load_json(categorical_path)["data"].get("queryCompletionRates") or {}
        for item in completion.get("items") or []:
            completion_rows.append(
                {
                    "round": round_number,
                    "questionnaire_key": item.get("name"),
                    "rate": item.get("rate"),
                    "num_complete": item.get("numComplete"),
                    "eligible_n": item.get("total"),
                }
            )

    doujin_rows: list[dict[str, Any]] = []
    doujin_path = root / "doujin" / "summary.json"
    if doujin_path.exists():
        doujin = load_json(doujin_path)
        for item in doujin.get("entries") or []:
            doujin_rows.append(
                {
                    "round": round_number,
                    "rank": item.get("rank"),
                    "name": item.get("name"),
                    "author": item.get("author"),
                    "url": item.get("url"),
                    "image_url": item.get("pic"),
                    "official_page_displayed_total_votes": doujin.get(
                        "officialPageDisplayedTotalVotes"
                    ),
                }
            )

    condition_files = sorted((root / "conditions").glob("q*_a*.json"))
    covote_summary = {}
    for category, filename, key in (
        ("character", "characters.json", "queryCharsCovote"),
        ("music", "music.json", "queryMusicsCovote"),
    ):
        path = root / "covote" / filename
        items = []
        if path.exists():
            items = (load_json(path).get("data", {}).get(key) or {}).get("items") or []
        expected_items = len(base["data"][{"character": "queryCharacterRanking", "music": "queryMusicRanking"}[category]]["entries"])
        covote_summary[category] = {
            "observed_pairs": len(items),
            "expected_pairs": expected_items * (expected_items - 1) // 2,
            "complete": len(items) == expected_items * (expected_items - 1) // 2,
        }

    categorical_entries = []
    if categorical_path.exists():
        categorical_entries = load_json(categorical_path)["data"]["queryQuestionnaire"].get("entries", [])
    single_mismatches = []
    question_types = {normalize_question_id(item.get("id")): item.get("type") for item in questions}
    for entry in categorical_entries:
        qid = normalize_question_id(entry.get("questionId"))
        if question_types.get(qid) == "Single":
            observed = sum(int(answer.get("totalVotes") or 0) for answer in entry.get("answersCat") or [])
            expected = int(entry.get("totalAnswers") or 0)
            if observed != expected:
                single_mismatches.append({"question_id": qid, "sum_option_count": observed, "respondent_n": expected})

    report = {
        "round": round_number,
        "available": True,
        "questions": len(questions),
        "options": len(options),
        "categorical_questions": len(categorical_entries),
        "condition_files": len(condition_files),
        "condition_files_expected": len(options),
        "conditions_complete": len(condition_files) == len(options),
        "single_question_sum_mismatches": single_mismatches,
        "covote": covote_summary,
    }
    tables = {
        "ballot_counts": ballot_rows,
        "questions": question_rows,
        "options": option_rows,
        "completion": completion_rows,
        "doujin": doujin_rows,
    }
    tables["_iter_questionnaire"] = [question_by_id, option_by_key]  # type: ignore[list-item]
    return tables, report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", default="10,11")
    args = parser.parse_args(argv)
    rounds = [int(value.strip()) for value in args.rounds.split(",") if value.strip()]
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    aggregate: dict[str, list[dict[str, Any]]] = {
        "ballot_counts": [],
        "questions": [],
        "options": [],
        "completion": [],
        "doujin": [],
    }
    round_context: dict[int, tuple[Path, Mapping[str, Any], Mapping[tuple[str, str], Any]]] = {}
    reports = []
    for round_number in rounds:
        tables, report = normalize_round(round_number)
        reports.append(report)
        if not tables:
            continue
        for key in aggregate:
            aggregate[key].extend(tables[key])
        question_by_id, option_by_key = tables["_iter_questionnaire"]  # type: ignore[misc]
        round_context[round_number] = (
            RAW_ROOT / f"round_{round_number}",
            question_by_id,
            option_by_key,
        )

    fieldsets = {
        "ballot_counts": ["round", "category", "ballots"],
        "questions": ["round", "question_id", "questionnaire_id", "questionnaire_name", "section_key", "questionnaire_key", "group_index", "branch_index", "question_type", "question", "introduction", "input", "option_count"],
        "options": ["round", "question_id", "answer_id", "question_type", "question", "option_index", "answer", "related_json", "mutex_json"],
        "completion": ["round", "questionnaire_key", "rate", "num_complete", "eligible_n"],
        "doujin": ["round", "rank", "name", "author", "url", "image_url", "official_page_displayed_total_votes"],
    }
    output_names = {
        "ballot_counts": "ballot_counts.csv",
        "questions": "questionnaire_questions.csv",
        "options": "questionnaire_options.csv",
        "completion": "questionnaire_completion.csv",
        "doujin": "doujin_rankings.csv",
    }
    row_counts: dict[str, int] = {}
    for key, rows in aggregate.items():
        output = OUT_ROOT / output_names[key]
        row_counts[output.name] = write_csv(output, fieldsets[key], rows)

    questionnaire_fields = ["round", "question_id", "answer_id", "questionnaire_id", "questionnaire_name", "section_key", "question_type", "question", "answer", "option_index", "count", "male_count", "female_count", "respondent_n", "respondent_male_n", "respondent_female_n", "share", "male_share_within_answer", "female_share_within_answer"]
    open_fields = ["round", "question_id", "questionnaire_id", "questionnaire_name", "question", "answer_index", "answer_text", "respondent_n", "respondent_male_n", "respondent_female_n"]
    trend_fields = ["round", "question_id", "series", "hours_since_open", "count"]
    condition_summary_fields = ["round", "question_id", "answer_id", "question_type", "question", "answer", "num_vote", "num_char", "num_music", "num_cp", "num_doujin", "num_male", "num_female", "source_file"]
    condition_ranking_fields = ["round", "question_id", "answer_id", "category", "rank", "display_rank", "name", "cp_a", "cp_b", "cp_c", "vote_count", "first_vote_count", "filtered_department_n", "filtered_unique_items", "source_file"]
    covote_fields = ["round", "category", "a", "b", "m00", "m01", "m10", "m11", "universe_n", "count_a", "count_b", "count_ab", "p_b_given_a", "p_a_given_b", "lift", "jaccard", "pmi", "npmi", "expected_independent", "cosine", "phi", "official_cs", "official_mi", "official_cv", "response_mode", "source_file"]

    def chain_questionnaire() -> Iterator[dict[str, Any]]:
        for round_number, (root, questions, options) in round_context.items():
            yield from iter_questionnaire_rows(round_number, root, questions, options)

    def chain_open() -> Iterator[dict[str, Any]]:
        for round_number, (root, questions, _options) in round_context.items():
            yield from iter_open_answers(round_number, root, questions)

    def chain_trends() -> Iterator[dict[str, Any]]:
        for round_number, (root, _questions, _options) in round_context.items():
            yield from iter_trends(round_number, root)

    def chain_condition(kind: str) -> Iterator[dict[str, Any]]:
        for round_number, (root, _questions, _options) in round_context.items():
            summaries, rankings = iter_conditions(round_number, root)
            yield from summaries if kind == "summary" else rankings

    def chain_covote() -> Iterator[dict[str, Any]]:
        for round_number, (root, _questions, _options) in round_context.items():
            yield from iter_covote(round_number, root)

    large_outputs = (
        ("questionnaire_long.csv", questionnaire_fields, chain_questionnaire()),
        ("open_text_answers.csv.gz", open_fields, chain_open()),
        ("questionnaire_trends.csv.gz", trend_fields, chain_trends()),
        ("condition_option_summary.csv", condition_summary_fields, chain_condition("summary")),
        ("condition_rankings.csv.gz", condition_ranking_fields, chain_condition("rankings")),
        ("covote_metrics.csv.gz", covote_fields, chain_covote()),
    )
    for filename, fields, rows in large_outputs:
        row_counts[filename] = write_csv(OUT_ROOT / filename, fields, rows)

    rankings_path = OUT_ROOT / "rankings.csv"
    ranking_fields = ["round", "category", "rank", "display_rank", "name", "name_jpn", "cp_a", "cp_b", "cp_c", "vote_count", "first_vote_count", "first_vote_percentage", "first_vote_count_weighted", "vote_percentage", "first_percentage", "male_vote_count", "male_percentage_per_item", "male_percentage_per_total", "female_vote_count", "female_percentage_per_item", "female_percentage_per_total", "department_voter_n", "album", "character_type", "character_origin", "first_appearance", "a_active", "b_active", "c_active", "none_active"]

    def all_rankings() -> Iterator[dict[str, Any]]:
        for round_number in round_context:
            yield from iter_rankings(round_number, load_json(RAW_ROOT / f"round_{round_number}" / "graphql" / "base.json"))

    row_counts[rankings_path.name] = write_csv(rankings_path, ranking_fields, all_rankings())

    output_files = sorted(path for path in OUT_ROOT.iterdir() if path.is_file())
    report = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "normalizer": "scripts_pipeline/normalize_cn_official.py",
        "rounds": reports,
        "row_counts": row_counts,
        "outputs": [
            {
                "path": path.relative_to(WORKSPACE).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in output_files
        ],
        "metric_definitions": {
            "cell_convention": "official API: 0=selected, 1=not selected; m00=intersection, m11=neither",
            "count_a": "m00 + m10",
            "count_b": "m00 + m01",
            "count_ab": "m00",
            "lift": "m00 * N / (count_a * count_b)",
            "jaccard": "m00 / (m00 + m01 + m10)",
            "pmi": "ln(lift)",
            "npmi": "pmi / -ln(m00 / N)",
        },
        "complete": all(
            item.get("available")
            and item.get("conditions_complete")
            and not item.get("single_question_sum_mismatches")
            and all(value.get("complete") for value in item.get("covote", {}).values())
            for item in reports
        ),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"row_counts": row_counts, "complete": report["complete"]}, ensure_ascii=False, indent=2))
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
