#!/usr/bin/env python3
"""Reproducible gender/demographic audit for the Touhou vote workbooks.

This script intentionally uses only the Python standard library.  It reads the
OOXML members inside .xlsx files directly, leaves all source workbooks intact,
and writes machine-readable audit outputs under analysis_results/.

The central denominator distinction is deliberate:

* TouhouVoteGenderInfo.xlsx contains Japanese *respondent counts*.
* TouhouVote_cn.xlsx contains Chinese gender-split *character ballot marks*.

Those quantities are useful, but they are not interchangeable population
shares.  See the generated data dictionary and summary for details.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import posixpath
import random
import re
import statistics
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"m": MAIN_NS, "r": DOC_REL_NS}

SOURCE_NAMES = (
    "TouhouVoteGenderInfo.xlsx",
    "TouhouVote_cn.xlsx",
    "TouhouVote_cn_grouped.xlsx",
    "TouhouVote_jp.xlsx",
    "TouhouVote_jp_grouped.xlsx",
    "Character_tag.xlsx",
)

# Character_tag.xlsx uses three names that differ from the comparable latest
# CN/JP grouped roster.  These are spelling/alias joins only, not fuzzy matches.
TAG_NAME_ALIASES = {
    "小恶魔(东方Project)#": "小恶魔",
    "因幡帝": "因幡天为（因幡帝）",
    "莉莉霍瓦特": "莉莉霍瓦特（莉莉白）",
}

LITERAL_NEUTRAL_TERMS = ("中性", "性别不明", "性别未知", "无性别", "双性")
PRESENTATION_PROXY_TERMS = ("伪郎", "伪娘", "可爱的男孩子")
EXPANDED_PROXY_TERMS = PRESENTATION_PROXY_TERMS + ("跨性别者",)

CN_LATEST_SESSION = "11"
JP_LATEST_SESSION = "20"
WORK13 = "13"
PERMUTATIONS = 20_000
RANDOM_SEED = 20_260_815


def cell_column_index(reference: str) -> int:
    match = re.match(r"[A-Z]+", reference)
    if match is None:
        raise ValueError(f"Invalid cell reference: {reference!r}")
    value = 0
    for char in match.group(0):
        value = value * 26 + ord(char) - 64
    return value - 1


def _sheet_target(target: str) -> str:
    target = target.replace("\\", "/").lstrip("/")
    if target.startswith("xl/"):
        return target
    return posixpath.normpath("xl/" + target)


def read_xlsx(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Read simple tabular .xlsx sheets without importing a spreadsheet package."""
    workbook: dict[str, list[dict[str, Any]]] = {}
    with zipfile.ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in shared_root.findall("m:si", NS):
                shared_strings.append(
                    "".join(node.text or "" for node in item.iterfind(".//m:t", NS))
                )

        workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships_root = ET.fromstring(
            archive.read("xl/_rels/workbook.xml.rels")
        )
        targets = {
            relationship.attrib["Id"]: relationship.attrib["Target"]
            for relationship in relationships_root
        }

        sheets = workbook_root.find("m:sheets", NS)
        if sheets is None:
            raise ValueError(f"No worksheets in {path}")

        for sheet in sheets:
            sheet_name = sheet.attrib["name"]
            relationship_id = sheet.attrib[f"{{{DOC_REL_NS}}}id"]
            xml_path = _sheet_target(targets[relationship_id])
            sheet_root = ET.fromstring(archive.read(xml_path))
            raw_rows: list[list[Any]] = []

            for row in sheet_root.findall(".//m:sheetData/m:row", NS):
                values: dict[int, Any] = {}
                for cell in row.findall("m:c", NS):
                    column = cell_column_index(cell.attrib["r"])
                    cell_type = cell.attrib.get("t")
                    value_element = cell.find("m:v", NS)
                    inline_element = cell.find("m:is", NS)
                    value: Any = None
                    if cell_type == "s" and value_element is not None:
                        value = shared_strings[int(value_element.text or "0")]
                    elif cell_type == "inlineStr" and inline_element is not None:
                        value = "".join(
                            node.text or ""
                            for node in inline_element.iterfind(".//m:t", NS)
                        )
                    elif cell_type == "b" and value_element is not None:
                        value = value_element.text == "1"
                    elif value_element is not None:
                        value = value_element.text
                    values[column] = value

                if values:
                    raw_rows.append(
                        [values.get(index) for index in range(max(values) + 1)]
                    )

            if not raw_rows:
                workbook[sheet_name] = []
                continue
            headers = [str(value or "").strip() for value in raw_rows[0]]
            if len(set(headers)) != len(headers):
                raise ValueError(f"Duplicate normalized headers in {path}:{sheet_name}")
            workbook[sheet_name] = [
                dict(zip(headers, row, strict=False)) for row in raw_rows[1:]
            ]
    return workbook


def locate_source(root: Path, filename: str) -> Path:
    direct = root / filename
    if direct.is_file():
        return direct
    matches = sorted(root.rglob(filename))
    if len(matches) != 1:
        raise FileNotFoundError(
            f"Expected exactly one {filename!r} under {root}, found {len(matches)}"
        )
    return matches[0]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def session_number(sheet_name: str) -> str:
    match = re.match(r"^(\d+)", sheet_name)
    if match is None:
        raise ValueError(f"Sheet does not start with a session number: {sheet_name!r}")
    return match.group(1)


def as_int(value: Any) -> int:
    if value is None or value == "" or value == "-":
        raise ValueError(f"Expected integer, got {value!r}")
    return int(float(str(value)))


def as_float(value: Any) -> float:
    if value is None or value == "" or value == "-":
        raise ValueError(f"Expected float, got {value!r}")
    return float(str(value))


def safe_ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def schema_for(workbook: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for sheet_name, rows in workbook.items():
        result[sheet_name] = {
            "row_count": len(rows),
            "columns": list(rows[0].keys()) if rows else [],
        }
    return result


def average_ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        end = index + 1
        while end < len(order) and values[order[end]] == values[order[index]]:
            end += 1
        average = (index + 1 + end) / 2
        for original_index in order[index:end]:
            ranks[original_index] = average
        index = end
    return ranks


def pearson_correlation(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("Correlation inputs must have the same length >= 2")
    x_mean = statistics.fmean(x)
    y_mean = statistics.fmean(y)
    numerator = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y))
    x_ss = sum((a - x_mean) ** 2 for a in x)
    y_ss = sum((b - y_mean) ** 2 for b in y)
    return numerator / math.sqrt(x_ss * y_ss)


def spearman_correlation(x: Sequence[float], y: Sequence[float]) -> float:
    return pearson_correlation(average_ranks(x), average_ranks(y))


def permutation_spearman_p(
    x: Sequence[float],
    y: Sequence[float],
    *,
    permutations: int,
    seed: int,
) -> tuple[float, float]:
    observed = spearman_correlation(x, y)
    shuffled = list(y)
    rng = random.Random(seed)
    extreme = 0
    for _ in range(permutations):
        rng.shuffle(shuffled)
        statistic = spearman_correlation(x, shuffled)
        if abs(statistic) >= abs(observed) - 1e-15:
            extreme += 1
    return observed, (extreme + 1) / (permutations + 1)


def permutation_mean_difference_p(
    values: Sequence[float],
    group_size: int,
    observed_group_indexes: set[int],
    *,
    permutations: int,
    seed: int,
) -> tuple[float, float]:
    def difference(indexes: set[int]) -> float:
        inside = [value for index, value in enumerate(values) if index in indexes]
        outside = [value for index, value in enumerate(values) if index not in indexes]
        return statistics.fmean(inside) - statistics.fmean(outside)

    observed = difference(observed_group_indexes)
    rng = random.Random(seed)
    extreme = 0
    population = list(range(len(values)))
    for _ in range(permutations):
        indexes = set(rng.sample(population, group_size))
        if abs(difference(indexes)) >= abs(observed) - 1e-15:
            extreme += 1
    return observed, (extreme + 1) / (permutations + 1)


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p using the probability-ordering definition."""
    row_one = a + b
    row_two = c + d
    column_one = a + c
    total = row_one + row_two
    lower = max(0, row_one - row_two - (d - c))
    # The simpler support bounds below are equivalent and easier to audit.
    lower = max(0, row_one - (b + d))
    upper = min(row_one, column_one)

    def probability(x: int) -> float:
        return (
            math.comb(column_one, x)
            * math.comb(total - column_one, row_one - x)
            / math.comb(total, row_one)
        )

    observed_probability = probability(a)
    return sum(
        probability(x)
        for x in range(lower, upper + 1)
        if probability(x) <= observed_probability + 1e-15
    )


def odds_ratio(a: int, b: int, c: int, d: int) -> float | None:
    return (a * d) / (b * c) if b and c else None


def competition_ranks(scores: dict[str, float]) -> dict[str, int]:
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    result: dict[str, int] = {}
    previous_score: float | None = None
    previous_rank = 0
    for ordinal, (name, score) in enumerate(ordered, start=1):
        if previous_score is None or score != previous_score:
            previous_rank = ordinal
            previous_score = score
        result[name] = previous_rank
    return result


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_audit(root: Path) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    source_paths = {name: locate_source(root, name) for name in SOURCE_NAMES}
    books = {name: read_xlsx(path) for name, path in source_paths.items()}

    cn_raw = books["TouhouVote_cn.xlsx"]
    cn_grouped = books["TouhouVote_cn_grouped.xlsx"]
    jp_grouped = books["TouhouVote_jp_grouped.xlsx"]
    gender = books["TouhouVoteGenderInfo.xlsx"]
    tag_rows = books["Character_tag.xlsx"]["Sheet1"]

    # Japanese respondent demographics.
    jp_demographics: list[dict[str, Any]] = []
    for sheet_name, rows in gender.items():
        counts = {str(row["性别"]): as_int(row["票数"]) for row in rows}
        male = counts.get("男", 0)
        female = counts.get("女", 0)
        other_value = counts.get("其他")
        other_for_total = other_value or 0
        total = male + female + other_for_total
        jp_demographics.append(
            {
                "session": int(session_number(sheet_name)),
                "male_respondents": male,
                "female_respondents": female,
                "other_respondents": other_value,
                "reported_total_respondents": total,
                "female_share_all_reported_categories": female / total,
                "female_share_binary_only": female / (male + female),
                "other_category_reported": other_value is not None,
            }
        )

    # Chinese composition uses the raw, full candidate list.  Session 1 has
    # rounded proportions only; sessions 2--4 have no gender fields; sessions
    # 5--11 have exact male/female character-mark counts.
    cn_composition: list[dict[str, Any]] = []
    cn_exact_totals: dict[str, dict[str, int]] = {}
    for sheet_name, rows in cn_raw.items():
        session = session_number(sheet_name)
        vote_marks = sum(as_int(row["票数"]) for row in rows)
        columns = set(rows[0]) if rows else set()
        base: dict[str, Any] = {
            "session": int(session),
            "candidate_rows": len(rows),
            "all_character_vote_marks": vote_marks,
        }
        if {"男性数", "女性数"}.issubset(columns):
            male = sum(as_int(row["男性数"]) for row in rows)
            female = sum(as_int(row["女性数"]) for row in rows)
            known = male + female
            unknown = vote_marks - known
            base.update(
                {
                    "gender_data_status": "exact_character_mark_counts",
                    "male_character_marks": male,
                    "female_character_marks": female,
                    "unassigned_character_marks": unknown,
                    "known_gender_mark_coverage": known / vote_marks,
                    "female_share_known_binary_character_marks": female / known,
                }
            )
            cn_exact_totals[session] = {"male": male, "female": female}
        elif {"男性比例", "女性比例"}.issubset(columns):
            male_estimate = sum(
                as_int(row["票数"]) * as_float(row["男性比例"]) for row in rows
            )
            female_estimate = sum(
                as_int(row["票数"]) * as_float(row["女性比例"]) for row in rows
            )
            known_estimate = male_estimate + female_estimate
            base.update(
                {
                    "gender_data_status": "estimated_from_rounded_character_ratios",
                    "male_character_marks": male_estimate,
                    "female_character_marks": female_estimate,
                    "unassigned_character_marks": vote_marks - known_estimate,
                    "known_gender_mark_coverage": known_estimate / vote_marks,
                    "female_share_known_binary_character_marks": (
                        female_estimate / known_estimate
                    ),
                }
            )
        else:
            base.update(
                {
                    "gender_data_status": "missing",
                    "male_character_marks": None,
                    "female_character_marks": None,
                    "unassigned_character_marks": None,
                    "known_gender_mark_coverage": None,
                    "female_share_known_binary_character_marks": None,
                }
            )
        cn_composition.append(base)

    # Normalize tag names, retaining exact source tags.  No semantic inference
    # is made beyond the explicitly declared exploratory proxy sets.
    tags_by_name: dict[str, set[str]] = {}
    tag_aliases_applied: list[dict[str, str]] = []
    for row in tag_rows:
        source_name = str(row["译名"]).strip()
        canonical_name = TAG_NAME_ALIASES.get(source_name, source_name)
        if source_name != canonical_name:
            tag_aliases_applied.append(
                {"source_name": source_name, "canonical_name": canonical_name}
            )
        tags_by_name[canonical_name] = {
            tag.strip()
            for tag in str(row["keywords"]).split("、")
            if tag.strip()
        }

    cn_latest = {
        str(row["译名"]).strip(): row for row in cn_grouped[CN_LATEST_SESSION]
    }
    jp_latest = {
        str(row["译名"]).strip(): row for row in jp_grouped[JP_LATEST_SESSION]
    }
    cn_names = set(cn_latest)
    jp_names = set(jp_latest)
    tag_names = set(tags_by_name)
    if cn_names != jp_names:
        raise ValueError(
            "Latest comparable CN/JP grouped rosters do not match: "
            f"CN-only={sorted(cn_names - jp_names)}, JP-only={sorted(jp_names - cn_names)}"
        )
    if cn_names != tag_names:
        raise ValueError(
            "Normalized tag roster does not match latest comparable roster: "
            f"vote-only={sorted(cn_names - tag_names)}, tag-only={sorted(tag_names - cn_names)}"
        )

    work13_names = sorted(
        name
        for name, row in cn_latest.items()
        if str(row["首次出现作品"]).strip() == WORK13
    )
    if len(work13_names) != 7:
        raise ValueError(f"Expected 7 work-13 characters, found {len(work13_names)}")

    def tag_hits(terms: Sequence[str]) -> dict[str, list[str]]:
        term_set = set(terms)
        return {
            name: sorted(tag for tag in tags if tag in term_set)
            for name, tags in tags_by_name.items()
            if tags & term_set
        }

    literal_hits = {
        name: sorted(
            tag
            for tag in tags
            if any(term in tag for term in LITERAL_NEUTRAL_TERMS)
        )
        for name, tags in tags_by_name.items()
    }
    literal_hits = {name: hits for name, hits in literal_hits.items() if hits}

    def proxy_audit(terms: Sequence[str]) -> dict[str, Any]:
        hits = tag_hits(terms)
        flagged = set(hits)
        work_flagged = flagged & set(work13_names)
        a = len(work_flagged)
        b = len(work13_names) - a
        c = len(flagged - set(work13_names))
        d = len(cn_names) - len(work13_names) - c
        return {
            "terms": list(terms),
            "flagged_count": len(flagged),
            "flagged_characters": hits,
            "work13_flagged_count": a,
            "work13_total": len(work13_names),
            "other_flagged_count": c,
            "other_total": len(cn_names) - len(work13_names),
            "two_by_two": {
                "work13_flagged": a,
                "work13_not_flagged": b,
                "other_flagged": c,
                "other_not_flagged": d,
            },
            "odds_ratio": odds_ratio(a, b, c, d),
            "fisher_exact_two_sided_p": fisher_two_sided(a, b, c, d),
        }

    presentation_proxy = proxy_audit(PRESENTATION_PROXY_TERMS)
    expanded_proxy = proxy_audit(EXPANDED_PROXY_TERMS)

    # Work-13 female relative preference across all exact-count CN sessions.
    work13_sessions: list[dict[str, Any]] = []
    for sheet_name, rows in cn_grouped.items():
        session = session_number(sheet_name)
        if session not in cn_exact_totals:
            continue
        work_rows = [
            row
            for row in rows
            if str(row["首次出现作品"]).strip() == WORK13
        ]
        male = sum(as_int(row["男性数"]) for row in work_rows)
        female = sum(as_int(row["女性数"]) for row in work_rows)
        all_male = cn_exact_totals[session]["male"]
        all_female = cn_exact_totals[session]["female"]
        relative_preference = (female / all_female) / (male / all_male)
        work13_sessions.append(
            {
                "session": int(session),
                "character_count": len(work_rows),
                "work13_male_character_marks": male,
                "work13_female_character_marks": female,
                "work13_female_share_known_binary_marks": female / (male + female),
                "all_male_character_marks_raw_roster": all_male,
                "all_female_character_marks_raw_roster": all_female,
                "all_female_share_known_binary_marks": all_female
                / (all_male + all_female),
                "female_relative_preference_ratio": relative_preference,
            }
        )

    pooled_work_male = sum(row["work13_male_character_marks"] for row in work13_sessions)
    pooled_work_female = sum(
        row["work13_female_character_marks"] for row in work13_sessions
    )
    pooled_all_male = sum(
        row["all_male_character_marks_raw_roster"] for row in work13_sessions
    )
    pooled_all_female = sum(
        row["all_female_character_marks_raw_roster"] for row in work13_sessions
    )
    pooled_work_relative_preference = (pooled_work_female / pooled_all_female) / (
        pooled_work_male / pooled_all_male
    )

    # Latest character-level preference and CN-JP rank gaps.
    latest_totals = cn_exact_totals[CN_LATEST_SESSION]
    latest_male_total = latest_totals["male"]
    latest_female_total = latest_totals["female"]
    expanded_flagged_names = set(expanded_proxy["flagged_characters"])
    presentation_flagged_names = set(presentation_proxy["flagged_characters"])
    latest_characters: list[dict[str, Any]] = []
    for name in sorted(cn_names):
        cn_row = cn_latest[name]
        jp_row = jp_latest[name]
        male = as_int(cn_row["男性数"])
        female = as_int(cn_row["女性数"])
        cn_rank = as_int(cn_row["名次"])
        jp_rank = as_int(jp_row["名次"])
        relative_preference = (female / latest_female_total) / (
            male / latest_male_total
        )
        latest_characters.append(
            {
                "character": name,
                "first_appearance_work": str(cn_row["首次出现作品"]).strip(),
                "cn11_official_rank": cn_rank,
                "jp20_official_rank": jp_rank,
                "rank_gap_cn_minus_jp": cn_rank - jp_rank,
                "cn11_male_character_marks": male,
                "cn11_female_character_marks": female,
                "cn11_female_share_known_binary_marks": female / (male + female),
                "female_relative_preference_ratio": relative_preference,
                "literal_neutral_tag_hit": name in literal_hits,
                "presentation_proxy_hit": name in presentation_flagged_names,
                "expanded_proxy_hit": name in expanded_flagged_names,
                "matched_tags": sorted(tags_by_name[name]),
            }
        )

    preference_values = [
        row["female_relative_preference_ratio"] for row in latest_characters
    ]
    rank_gaps = [row["rank_gap_cn_minus_jp"] for row in latest_characters]
    rank_rho, rank_rho_p = permutation_spearman_p(
        preference_values,
        rank_gaps,
        permutations=PERMUTATIONS,
        seed=RANDOM_SEED,
    )
    work13_indexes = {
        index
        for index, row in enumerate(latest_characters)
        if row["first_appearance_work"] == WORK13
    }
    work13_gap_difference, work13_gap_p = permutation_mean_difference_p(
        rank_gaps,
        len(work13_indexes),
        work13_indexes,
        permutations=PERMUTATIONS,
        seed=RANDOM_SEED + 1,
    )

    def latest_group_summary(names: set[str]) -> dict[str, Any]:
        rows = [row for row in latest_characters if row["character"] in names]
        male = sum(row["cn11_male_character_marks"] for row in rows)
        female = sum(row["cn11_female_character_marks"] for row in rows)
        return {
            "character_count": len(rows),
            "characters": sorted(names),
            "male_character_marks": male,
            "female_character_marks": female,
            "female_share_known_binary_marks": female / (male + female),
            "female_relative_preference_ratio": (female / latest_female_total)
            / (male / latest_male_total),
            "mean_rank_gap_cn_minus_jp": statistics.fmean(
                row["rank_gap_cn_minus_jp"] for row in rows
            ),
            "median_rank_gap_cn_minus_jp": statistics.median(
                row["rank_gap_cn_minus_jp"] for row in rows
            ),
        }

    work13_set = set(work13_names)
    work13_proxy_set = work13_set & expanded_flagged_names
    work13_nonproxy_set = work13_set - expanded_flagged_names
    work13_latest_summary = latest_group_summary(work13_set)
    work13_proxy_summary = latest_group_summary(work13_proxy_set)
    work13_nonproxy_summary = latest_group_summary(work13_nonproxy_set)

    # Illustrative raw-vote reweighting.  This cannot reproduce the official CN
    # rank because the official rank also uses a first-choice bonus and the
    # workbook has no gender x first-choice cross-tabulation.
    jp20 = next(row for row in jp_demographics if row["session"] == 20)
    cn11 = next(row for row in cn_composition if row["session"] == 11)
    cn_binary_female_weight = cn11["female_share_known_binary_character_marks"]
    jp_binary_female_weight = jp20["female_share_binary_only"]

    baseline_scores = {
        row["character"]: (
            (1 - cn_binary_female_weight)
            * row["cn11_male_character_marks"]
            / latest_male_total
            + cn_binary_female_weight
            * row["cn11_female_character_marks"]
            / latest_female_total
        )
        for row in latest_characters
    }
    reweighted_scores = {
        row["character"]: (
            (1 - jp_binary_female_weight)
            * row["cn11_male_character_marks"]
            / latest_male_total
            + jp_binary_female_weight
            * row["cn11_female_character_marks"]
            / latest_female_total
        )
        for row in latest_characters
    }
    baseline_ranks = competition_ranks(baseline_scores)
    reweighted_ranks = competition_ranks(reweighted_scores)
    jp_rank_list = [row["jp20_official_rank"] for row in latest_characters]
    baseline_rank_list = [baseline_ranks[row["character"]] for row in latest_characters]
    reweighted_rank_list = [
        reweighted_ranks[row["character"]] for row in latest_characters
    ]
    reweighting_character_rows: list[dict[str, Any]] = []
    for row in latest_characters:
        name = row["character"]
        row["cn11_raw_vote_baseline_rank_within_comparable_roster"] = baseline_ranks[
            name
        ]
        row["cn11_raw_vote_reweighted_rank_at_jp20_binary_female_share"] = (
            reweighted_ranks[name]
        )
        row["reweighted_rank_change_negative_is_improvement"] = (
            reweighted_ranks[name] - baseline_ranks[name]
        )
        if name in work13_set:
            reweighting_character_rows.append(
                {
                    "character": name,
                    "baseline_raw_vote_rank": baseline_ranks[name],
                    "reweighted_raw_vote_rank": reweighted_ranks[name],
                    "rank_change_negative_is_improvement": reweighted_ranks[name]
                    - baseline_ranks[name],
                    "cn11_official_rank": row["cn11_official_rank"],
                    "jp20_official_rank": row["jp20_official_rank"],
                }
            )

    latest_rank_relationship = {
        "comparable_character_count": len(latest_characters),
        "rank_gap_definition": "CN11 rank minus JP20 rank; positive means better rank in JP20",
        "spearman_female_preference_vs_rank_gap": rank_rho,
        "spearman_permutation_two_sided_p": rank_rho_p,
        "permutations": PERMUTATIONS,
        "random_seed": RANDOM_SEED,
        "work13_mean_rank_gap": work13_latest_summary[
            "mean_rank_gap_cn_minus_jp"
        ],
        "work13_median_rank_gap": work13_latest_summary[
            "median_rank_gap_cn_minus_jp"
        ],
        "work13_mean_gap_minus_other_characters": work13_gap_difference,
        "work13_gap_permutation_two_sided_p": work13_gap_p,
    }

    reweighting = {
        "status": "illustrative_sensitivity_not_causal_estimate",
        "cn11_binary_female_character_mark_weight": cn_binary_female_weight,
        "jp20_binary_female_respondent_weight": jp_binary_female_weight,
        "assumptions": [
            "CN gender-specific raw-vote preference profiles transport to the JP population",
            "female and male respondents cast comparable numbers of character marks",
            "the JP binary respondent share may be used as a character-mark mixture weight",
            "first-choice bonus and all other CN/JP ballot-rule differences are ignored",
        ],
        "baseline_raw_rank_spearman_vs_jp20_official_rank": spearman_correlation(
            baseline_rank_list, jp_rank_list
        ),
        "reweighted_raw_rank_spearman_vs_jp20_official_rank": spearman_correlation(
            reweighted_rank_list, jp_rank_list
        ),
        "spearman_change": spearman_correlation(reweighted_rank_list, jp_rank_list)
        - spearman_correlation(baseline_rank_list, jp_rank_list),
        "characters_with_any_rank_change": sum(
            baseline_ranks[name] != reweighted_ranks[name] for name in cn_names
        ),
        "mean_absolute_rank_change": statistics.fmean(
            abs(reweighted_ranks[name] - baseline_ranks[name]) for name in cn_names
        ),
        "work13_character_changes": sorted(
            reweighting_character_rows, key=lambda row: row["character"]
        ),
    }

    source_metadata = {}
    for filename, path in source_paths.items():
        stat = path.stat()
        source_metadata[filename] = {
            "relative_path": str(path.relative_to(root)),
            "size_bytes": stat.st_size,
            "sha256": sha256_file(path),
        }

    audit: dict[str, Any] = {
        "metadata": {
            "analysis_version": "1.0.0",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "python_version": sys.version.split()[0],
            "script_relative_path": "scripts_pipeline/demographic_audit.py",
            "source_files": source_metadata,
            "source_priority": {
                "japanese_vote_data": "TouhouVote_jp.xlsx retained as the raw Japanese source; TouhouVote_jp_grouped.xlsx is used only for the 122-character comparable roster",
                "chinese_vote_data": "TouhouVote_cn.xlsx supplies full-roster gender-mark denominators; TouhouVote_cn_grouped.xlsx supplies work labels and comparable ranks",
                "tags": "Character_tag.xlsx is fan-wiki-derived descriptive metadata, not an official gender field",
            },
        },
        "definitions": {
            "jp_female_share_all_reported_categories": "female respondents / (male + female + other respondents)",
            "jp_female_share_binary_only": "female respondents / (male + female respondents)",
            "cn_female_share_known_binary_character_marks": "sum of female character ballot marks / sum of male and female character ballot marks across the raw candidate roster",
            "female_relative_preference_ratio": "(group female marks / all female marks) / (group male marks / all male marks); >1 means women devote a larger share of their known-gender character marks to the group",
            "rank_gap_cn_minus_jp": "CN11 official rank - JP20 official rank; positive means the character ranks better in JP20",
            "literal_neutral_tag": f"a Character_tag keyword containing one of {list(LITERAL_NEUTRAL_TERMS)}",
            "presentation_proxy": f"exploratory exact-tag union {list(PRESENTATION_PROXY_TERMS)}",
            "expanded_gender_nonconforming_proxy": f"exploratory exact-tag union {list(EXPANDED_PROXY_TERMS)}; this is not a canon gender classification",
        },
        "schemas": {filename: schema_for(book) for filename, book in books.items()},
        "data_availability": {
            "jp_gender_sessions": [row["session"] for row in jp_demographics],
            "jp_missing_gender_sessions_in_vote_series": [3, 4],
            "jp_other_category_first_session": 18,
            "cn_exact_gender_mark_sessions": sorted(map(int, cn_exact_totals)),
            "cn_ratio_only_gender_session": [1],
            "cn_missing_gender_sessions": [2, 3, 4],
            "latest_cn_jp_roster_match_count": len(cn_names),
            "tag_rows": len(tag_rows),
            "tag_aliases_applied": tag_aliases_applied,
        },
        "jp_respondent_demographics_by_session": jp_demographics,
        "cn_character_mark_composition_by_session": cn_composition,
        "tag_audit": {
            "literal_neutral_terms": list(LITERAL_NEUTRAL_TERMS),
            "literal_neutral_hits": literal_hits,
            "literal_neutral_hit_count": len(literal_hits),
            "presentation_proxy": presentation_proxy,
            "expanded_gender_nonconforming_proxy": expanded_proxy,
        },
        "work13_female_preference": {
            "sessions": work13_sessions,
            "all_session_ratios_above_one": all(
                row["female_relative_preference_ratio"] > 1
                for row in work13_sessions
            ),
            "session_ratio_min": min(
                row["female_relative_preference_ratio"] for row in work13_sessions
            ),
            "session_ratio_median": statistics.median(
                row["female_relative_preference_ratio"] for row in work13_sessions
            ),
            "session_ratio_max": max(
                row["female_relative_preference_ratio"] for row in work13_sessions
            ),
            "pooled_male_character_marks": pooled_work_male,
            "pooled_female_character_marks": pooled_work_female,
            "pooled_female_share_known_binary_marks": pooled_work_female
            / (pooled_work_male + pooled_work_female),
            "pooled_female_relative_preference_ratio": pooled_work_relative_preference,
            "pooling_warning": "Pooling weights high-turnout sessions more heavily and does not deduplicate respondents across editions",
        },
        "latest_cn11_jp20": {
            "jp20_female_respondent_share_all_categories": jp20[
                "female_share_all_reported_categories"
            ],
            "jp20_female_respondent_share_binary_only": jp20[
                "female_share_binary_only"
            ],
            "cn11_female_character_mark_share_binary_only_raw_roster": cn11[
                "female_share_known_binary_character_marks"
            ],
            "numerically_observed_binary_share_gap_percentage_points": 100
            * (
                jp20["female_share_binary_only"]
                - cn11["female_share_known_binary_character_marks"]
            ),
            "denominator_comparability": "not directly comparable: JP is respondents; CN is character ballot marks",
            "work13": work13_latest_summary,
            "work13_expanded_proxy_characters": work13_proxy_summary,
            "work13_nonproxy_characters": work13_nonproxy_summary,
            "all_presentation_proxy_characters": latest_group_summary(
                presentation_flagged_names
            ),
            "all_expanded_proxy_characters": latest_group_summary(
                expanded_flagged_names
            ),
            "rank_relationship": latest_rank_relationship,
            "illustrative_reweighting": reweighting,
            "characters": latest_characters,
        },
        "claim_assessments": {
            "work13_has_many_neutral_or_unknown_gender_characters": {
                "verdict": "not established by the available tags",
                "confidence": "high",
                "reason": "There are no literal neutral/unknown-gender tags. The expanded post-hoc proxy flags 2/7 work-13 characters versus 7/115 others, but Fisher two-sided p is above 0.05 and the proxy is not a canon gender field.",
            },
            "work13_is_more_female_preferred": {
                "verdict": "supported descriptively for Chinese gender-split character ballot marks",
                "confidence": "medium-high within the Chinese datasets; not demonstrated for Japan",
                "reason": "The female relative-preference ratio is above 2 in every exact-count CN session, but Japan has no character-by-gender table in the supplied files.",
            },
            "neutral_proxy_explains_work13_female_preference": {
                "verdict": "not supported",
                "confidence": "medium",
                "reason": "In CN11, the two expanded-proxy work-13 characters and the five non-proxy work-13 characters have nearly identical female shares of their known-gender marks.",
            },
            "cn_jp_gender_mix_difference_causes_rank_difference": {
                "verdict": "causal claim not identified",
                "confidence": "high",
                "reason": "The available country measures use different units, ballots and populations. The cross-character association is weak, and the illustrative reweighting changes correlation with JP ranks only slightly under strong untestable assumptions.",
            },
        },
        "warnings": [
            "Do not label CN female character-mark share as a female respondent share.",
            "Do not treat absence of the Japanese 'other' row before session 18 as measured zero; the category was not reported.",
            "Do not infer Japanese female character preferences: the supplied JP vote workbooks have no character-by-gender cells.",
            "Do not treat Character_tag proxy terms as canon gender or gender identity.",
            "CN11 and JP20 edition numbers, ballot rules, first-choice weighting and sampling frames differ; rank gaps are descriptive.",
            "TouhouVoteGenderInfo labels are 男/女/其他, not 男性/女性/其他. Existing code that filters for 男性/女性 will silently return null totals.",
        ],
    }

    csv_outputs = {
        "jp_demographics": jp_demographics,
        "cn_composition": cn_composition,
        "work13_sessions": work13_sessions,
        "latest_characters": latest_characters,
    }
    return audit, csv_outputs


def data_dictionary_rows() -> list[dict[str, str]]:
    return [
        {
            "dataset": "jp_respondent_demographics_by_session",
            "field": "female_share_all_reported_categories",
            "type": "number [0,1]",
            "definition": "female / (male + female + other) respondent counts",
            "denominator": "reported JP respondents in that session",
            "caveat": "other is unreported, not measured zero, before session 18",
        },
        {
            "dataset": "jp_respondent_demographics_by_session",
            "field": "female_share_binary_only",
            "type": "number [0,1]",
            "definition": "female / (male + female) respondent counts",
            "denominator": "JP respondents reporting male or female",
            "caveat": "excludes other from sessions 18-20",
        },
        {
            "dataset": "cn_character_mark_composition_by_session",
            "field": "female_share_known_binary_character_marks",
            "type": "number [0,1] or null",
            "definition": "female character marks / (male + female character marks)",
            "denominator": "known-binary-gender character ballot marks over the raw roster",
            "caveat": "not a unique-voter or respondent share",
        },
        {
            "dataset": "work13_female_preference.sessions",
            "field": "female_relative_preference_ratio",
            "type": "positive number",
            "definition": "(work13 female marks/all female marks)/(work13 male marks/all male marks)",
            "denominator": "all raw-roster marks of the same reported gender in that CN session",
            "caveat": "marks from the same respondent are not independent",
        },
        {
            "dataset": "latest_cn11_jp20.characters",
            "field": "rank_gap_cn_minus_jp",
            "type": "integer",
            "definition": "CN11 official rank minus JP20 official rank",
            "denominator": "122-character exact-match grouped roster",
            "caveat": "positive means a better numeric rank in JP; not a causal effect",
        },
        {
            "dataset": "latest_cn11_jp20.characters",
            "field": "female_relative_preference_ratio",
            "type": "positive number",
            "definition": "character-level female share-of-all-female marks divided by male share-of-all-male marks",
            "denominator": "CN11 raw-roster known-gender character marks",
            "caveat": "undefined causal direction; based on CN preferences only",
        },
        {
            "dataset": "tag_audit",
            "field": "expanded_proxy_hit",
            "type": "boolean",
            "definition": "any exact tag in [伪郎, 伪娘, 可爱的男孩子, 跨性别者]",
            "denominator": "122 normalized Character_tag rows",
            "caveat": "exploratory fan-wiki proxy, not canon gender classification",
        },
        {
            "dataset": "illustrative_reweighting",
            "field": "reweighted_rank_change_negative_is_improvement",
            "type": "integer",
            "definition": "raw-vote rank at JP20 binary female weight minus raw-vote rank at CN11 mark weight",
            "denominator": "122-character comparable roster",
            "caveat": "sensitivity scenario; ignores first-choice bonus and assumes transportability",
        },
    ]


def render_summary(audit: dict[str, Any]) -> str:
    jp = audit["latest_cn11_jp20"]
    tag = audit["tag_audit"]["expanded_gender_nonconforming_proxy"]
    work = audit["work13_female_preference"]
    rank = jp["rank_relationship"]
    rw = jp["illustrative_reweighting"]
    proxy_work = jp["work13_expanded_proxy_characters"]
    nonproxy_work = jp["work13_nonproxy_characters"]
    lines = [
        "# 问卷人口统计与性别主张审计",
        "",
        "本报告由 `scripts_pipeline/demographic_audit.py` 直接读取原始 xlsx 后生成。",
        "",
        "## 核心结论",
        "",
        f"- 日方第20回女性占全部已报告投票者 {jp['jp20_female_respondent_share_all_categories']:.2%}，仅在男/女中占 {jp['jp20_female_respondent_share_binary_only']:.2%}。中方第11届女性只可算作角色投票标记的 {jp['cn11_female_character_mark_share_binary_only_raw_roster']:.2%}；它不是独立投票者比例，两者不能直接当人口结构作同口径比较。",
        f"- `Character_tag.xlsx` 没有任何“中性/性别不明”等字面标签。探索性扩展代理在神灵庙角色中为 {tag['work13_flagged_count']}/{tag['work13_total']}，其余角色为 {tag['other_flagged_count']}/{tag['other_total']}；Fisher 双侧 p={tag['fisher_exact_two_sided_p']:.4f}。这不足以把“神灵庙有大量中性角色”写成既定事实。",
        f"- 神灵庙角色在中方第5–11届的女性相对偏好比均大于1，范围 {work['session_ratio_min']:.3f}–{work['session_ratio_max']:.3f}，中位数 {work['session_ratio_median']:.3f}，合并比值 {work['pooled_female_relative_preference_ratio']:.3f}。这支持“在中方性别拆分的角色投票标记中更受女性偏好”，不支持外推到日方女性。",
        f"- 中方第11届神灵庙的2名代理角色与5名非代理角色，女性标记占比分别为 {proxy_work['female_share_known_binary_marks']:.2%} 与 {nonproxy_work['female_share_known_binary_marks']:.2%}，几乎相同；代理标签不能解释该作品的女性偏好。",
        f"- 122名共同角色中，女性相对偏好与“中方名次－日方名次”的 Spearman ρ={rank['spearman_female_preference_vs_rank_gap']:.3f}，置换 p={rank['spearman_permutation_two_sided_p']:.4f}：方向一致但关系较弱。",
        f"- 把中方性别偏好做一个强假设的日方比例重加权后，与日方名次的相关只从 {rw['baseline_raw_rank_spearman_vs_jp20_official_rank']:.4f} 变为 {rw['reweighted_raw_rank_spearman_vs_jp20_official_rank']:.4f}（Δ={rw['spearman_change']:.4f}，平均绝对名次变化 {rw['mean_absolute_rank_change']:.2f}）。该敏感性分析不能识别因果。",
        "",
        "## 必须保留的口径限制",
        "",
        "- 日本工作簿给的是投票者人数；中国工作簿给的是角色投票标记数，同一人可贡献多个标记。",
        "- 日方第3、4回无性别表；第18回才开始报告“其他”，此前应记为未报告而不是0。",
        "- 中方第1届只有四舍五入后的角色性别比例，第2–4届完全没有性别字段，第5–11届才有精确标记数。",
        "- 日方没有角色×性别交叉表，无法直接检验日方女性更喜欢哪些角色或作品。",
        "- 中日届次、抽样、投票上限与本命加权不同；名次差只作描述，不作人口比例造成的效果量。",
        "- `Character_tag.xlsx` 是粉丝维基标签；“伪郎/伪娘/可爱的男孩子/跨性别者”仅为显式、可复算的探索代理。",
        "",
        "## 文件保留判断",
        "",
        "- 保留 `TouhouVote_jp.xlsx` 作为日文原始人气数据；`TouhouVote_jp_grouped.xlsx` 仅作122角同表比较。",
        "- 保留 `TouhouVote_cn.xlsx` 作为中方全候选分母；`TouhouVote_cn_grouped.xlsx` 用于首次作品与同表排名。",
        "- 保留 `TouhouVoteGenderInfo.xlsx`，但读取标签必须使用“男/女/其他”。",
        "- 旧单体数据已归档至 `archive_legacy/monolithic_vote_json_v1/touhou_vote.json`；其中 gender 男/女值为空，不得据其做性别结论。",
        "- `Character_tag.xlsx` 可保留作软标签，但不应升级为官方性别表。",
        "",
        "详细字段定义见 `demographic_audit_data_dictionary.csv`，完整数值见 `demographic_audit.json`。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Workspace root containing the source xlsx files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: <root>/analysis_results)",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    output_dir = (args.output_dir or root / "analysis_results").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    audit, csv_outputs = build_audit(root)
    json_path = output_dir / "demographic_audit.json"
    json_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    write_csv(
        output_dir / "demographic_audit_jp_demographics.csv",
        csv_outputs["jp_demographics"],
        [
            "session",
            "male_respondents",
            "female_respondents",
            "other_respondents",
            "reported_total_respondents",
            "female_share_all_reported_categories",
            "female_share_binary_only",
            "other_category_reported",
        ],
    )
    write_csv(
        output_dir / "demographic_audit_cn_composition.csv",
        csv_outputs["cn_composition"],
        [
            "session",
            "candidate_rows",
            "all_character_vote_marks",
            "gender_data_status",
            "male_character_marks",
            "female_character_marks",
            "unassigned_character_marks",
            "known_gender_mark_coverage",
            "female_share_known_binary_character_marks",
        ],
    )
    write_csv(
        output_dir / "demographic_audit_work13_sessions.csv",
        csv_outputs["work13_sessions"],
        [
            "session",
            "character_count",
            "work13_male_character_marks",
            "work13_female_character_marks",
            "work13_female_share_known_binary_marks",
            "all_male_character_marks_raw_roster",
            "all_female_character_marks_raw_roster",
            "all_female_share_known_binary_marks",
            "female_relative_preference_ratio",
        ],
    )
    write_csv(
        output_dir / "demographic_audit_latest_characters.csv",
        csv_outputs["latest_characters"],
        [
            "character",
            "first_appearance_work",
            "cn11_official_rank",
            "jp20_official_rank",
            "rank_gap_cn_minus_jp",
            "cn11_male_character_marks",
            "cn11_female_character_marks",
            "cn11_female_share_known_binary_marks",
            "female_relative_preference_ratio",
            "literal_neutral_tag_hit",
            "presentation_proxy_hit",
            "expanded_proxy_hit",
            "cn11_raw_vote_baseline_rank_within_comparable_roster",
            "cn11_raw_vote_reweighted_rank_at_jp20_binary_female_share",
            "reweighted_rank_change_negative_is_improvement",
            "matched_tags",
        ],
    )
    write_csv(
        output_dir / "demographic_audit_data_dictionary.csv",
        data_dictionary_rows(),
        ["dataset", "field", "type", "definition", "denominator", "caveat"],
    )
    (output_dir / "demographic_audit_summary.md").write_text(
        render_summary(audit), encoding="utf-8"
    )

    print(json_path)


if __name__ == "__main__":
    main()
