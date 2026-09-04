#!/usr/bin/env python3
"""Normalize locally-crawled Japanese official poll data (rounds 3--16).

This program is intentionally offline: it reads only
data_raw/jp_official_legacy plus the crawl manifest.  It produces four UTF-8
CSV long tables and machine-readable validation metadata.  No number is
manually transcribed.  Denominators are either explicitly printed by the
official page, exact sums of complete mutually-exclusive rows, exact vote
counts implied by the published scoring rule, or a *unique* integer solution
to multiple official count/rounded-percentage pairs.  Otherwise the
denominator remains blank.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Iterator

from lxml import html


NORMALIZER_VERSION = "jp-official-legacy-normalizer-v2"
SPACE_RE = re.compile(r"[\s\u3000]+")
INT_RE = re.compile(r"(?<![\d.])([+\-]?\d[\d,]*)(?![\d.])")
PERCENT_RE = re.compile(r"([+\-]?\d[\d,]*(?:\.\d+)?)\s*[%％]")
POINT_RE = re.compile(r"([+\-]?\d[\d,]*(?:\.\d+)?)\s*pt", re.I)
EXPLICIT_DENOM_RE = re.compile(
    r"有効回答(?:数)?\s*[:：]\s*([\d,]+)\s*(人|件|名|票)?"
)
TITLE_ENTITY_RE = re.compile(r"投票結果[：:]\s*(.*?)\s*-\s*第\d+回")
SUMMARY_VOTES_RE = re.compile(r"得票数\s*[:：]\s*([\d,]+)\s*票")


QUESTIONNAIRE_FIELDS = [
    "region",
    "round",
    "scope",
    "source_url",
    "source_sha256",
    "source_file",
    "source_table_index",
    "source_row_index",
    "question_id",
    "question",
    "question_path_json",
    "table_variant",
    "rank",
    "points",
    "item",
    "option",
    "count",
    "count_unit",
    "percentage",
    "official_percentage",
    "additional_official_percentages_json",
    "percentage_basis",
    "denominator",
    "denominator_unit",
    "denominator_basis",
    "denominator_candidate_min",
    "denominator_candidate_max",
    "raw_cells_json",
]

ENTITY_QUESTION_FIELDS = [
    "region",
    "round",
    "source_category",
    "source_item_id",
    "source_entity_name",
    "source_url",
    "source_sha256",
    "source_table_index",
    "source_row_index",
    "question_id",
    "question",
    "option",
    "count",
    "percentage",
    "overall_percentage",
    "delta_points",
    "denominator",
    "denominator_basis",
    "denominator_candidate_min",
    "denominator_candidate_max",
    "raw_cells_json",
]

ASSOCIATION_FIELDS = [
    "region",
    "round",
    "source_category",
    "source_item_id",
    "source_entity_name",
    "source_vote_count",
    "target_category",
    "target_entity_name",
    "association_context",
    "association_kind",
    "vote_count",
    "conditional_percentage",
    "conditional_denominator",
    "conditional_denominator_basis",
    "conditional_denominator_candidate_min",
    "conditional_denominator_candidate_max",
    "overall_percentage",
    "overall_denominator",
    "overall_denominator_basis",
    "overall_denominator_candidate_min",
    "overall_denominator_candidate_max",
    "delta_points",
    "rank",
    "points",
    "first_choice_count",
    "comment_count",
    "appearances",
    "source_table_indices_json",
    "source_row_indices_json",
    "source_url",
    "source_sha256",
    "raw_cells_json",
]

METRIC_FIELDS = [
    "region",
    "round",
    "category",
    "entity_name",
    "rank",
    "points",
    "first_choice_count",
    "vote_count",
    "vote_count_basis",
    "comment_count",
    "source_url",
    "source_sha256",
    "source_file",
]

EXCEPTION_FIELDS = [
    "round",
    "scope",
    "source_file",
    "source_url",
    "table_index",
    "row_index",
    "reason",
    "raw_cells_json",
]


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return SPACE_RE.sub(" ", value.replace("\r", " ").replace("\x00", " ")).strip()


def norm_key(value: str) -> str:
    return clean_text(unicodedata.normalize("NFKC", value)).casefold()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def parse_int(text: str) -> int | None:
    normalized = unicodedata.normalize("NFKC", clean_text(text))
    match = INT_RE.search(normalized)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


@dataclass(frozen=True)
class DisplayPercent:
    value: Decimal
    precision: int
    raw: str

    def as_float(self) -> float:
        return float(self.value)


def parse_percent(text: str) -> DisplayPercent | None:
    normalized = unicodedata.normalize("NFKC", clean_text(text))
    match = PERCENT_RE.search(normalized)
    if not match:
        return None
    raw_number = match.group(1).replace(",", "")
    try:
        value = Decimal(raw_number)
    except InvalidOperation:
        return None
    precision = len(raw_number.partition(".")[2]) if "." in raw_number else 0
    return DisplayPercent(value=value, precision=precision, raw=match.group(0))


def parse_points(text: str) -> float | None:
    normalized = unicodedata.normalize("NFKC", clean_text(text))
    match = POINT_RE.search(normalized)
    if not match:
        return None
    try:
        return float(Decimal(match.group(1).replace(",", "")))
    except InvalidOperation:
        return None


def count_unit(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", clean_text(text))
    for unit in ("人", "件", "名", "票"):
        if unit in normalized:
            return unit
    return ""


def format_decimal(value: Decimal | float | int | None) -> str:
    if value is None:
        return ""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def displayed_percent_matches(count: int, denominator: int, percent: DisplayPercent) -> bool:
    if denominator <= 0:
        return False
    # Historical PHP pages occasionally land exactly on an x.xx5 boundary
    # and display either adjacent value because the source arithmetic used a
    # binary float.  Treat both tie outcomes as compatible with the printed
    # precision.  This is a closed precision interval, not a guessed value.
    actual = Decimal(count) * Decimal(100) / Decimal(denominator)
    half = Decimal(5).scaleb(-(percent.precision + 1))
    return abs(actual - percent.value) <= half


@dataclass(frozen=True)
class DenominatorResult:
    value: int | None
    basis: str
    candidate_min: int | None = None
    candidate_max: int | None = None
    candidate_count: int | None = None


def solve_unique_denominator(
    pairs: Iterable[tuple[int, DisplayPercent]],
    upper_cap: int = 250_000,
) -> DenominatorResult:
    """Find an exact integer denominator from printed precision intervals.

    A value is returned only if all official count/rounded-percentage pairs
    admit exactly one integer. Tie boundaries are inclusive to accommodate the
    old site's binary-float formatting. Multiple candidates are reported as a
    range, never silently resolved to an estimate.
    """
    usable = [(count, percent) for count, percent in pairs if count >= 0 and percent.value > 0]
    if not usable:
        return DenominatorResult(None, "not_available")
    lower = max(count for count, _percent in usable)
    upper = upper_cap
    for count, percent in usable:
        half = Decimal(5).scaleb(-(percent.precision + 1))
        low_percent = max(Decimal("0"), percent.value - half)
        high_percent = percent.value + half
        if high_percent > 0:
            rough_low = int((Decimal(count) * 100 / high_percent).to_integral_value(rounding="ROUND_FLOOR"))
            lower = max(lower, max(1, rough_low - 2))
        if low_percent > 0:
            rough_high = int((Decimal(count) * 100 / low_percent).to_integral_value(rounding="ROUND_CEILING"))
            upper = min(upper, rough_high + 2)
    if lower > upper:
        return DenominatorResult(None, "inconsistent_count_percentage_pairs")
    candidates = [
        denominator
        for denominator in range(lower, upper + 1)
        if all(displayed_percent_matches(count, denominator, percent) for count, percent in usable)
    ]
    if len(candidates) == 1:
        return DenominatorResult(
            candidates[0],
            "derived_unique_integer_from_official_rounded_percentages",
            candidates[0],
            candidates[0],
            1,
        )
    if candidates:
        return DenominatorResult(
            None,
            "ambiguous_integer_candidates_from_official_rounded_percentages",
            min(candidates),
            max(candidates),
            len(candidates),
        )
    return DenominatorResult(None, "inconsistent_count_percentage_pairs")


def explicit_denominator(texts: Iterable[str]) -> tuple[int | None, str, str]:
    for text in reversed(list(texts)):
        match = EXPLICIT_DENOM_RE.search(unicodedata.normalize("NFKC", text))
        if match:
            return int(match.group(1).replace(",", "")), match.group(2) or "", "explicit_official_heading"
    return None, "", ""


def cells_text(row: dict[str, Any]) -> list[str]:
    return [clean_text(cell.get("text", "")) for cell in row.get("cells", [])]


def raw_cells(texts: list[str]) -> str:
    return json.dumps(texts, ensure_ascii=False, separators=(",", ":"))


def question_slug(round_no: int, question: str, prefix: str = "q") -> str:
    short_hash = hashlib.sha256(norm_key(question).encode("utf-8")).hexdigest()[:12]
    return f"jp{round_no}:{prefix}:{short_hash}"


def heading_paths(raw_path: Path, encoding: str) -> dict[int, list[str]]:
    if not raw_path.exists():
        return {}
    payload = raw_path.read_bytes()
    document = html.fromstring(payload.decode(encoding or "utf-8", "replace"))
    stack: dict[int, str] = {}
    denominator_note = ""
    table_paths: dict[int, list[str]] = {}
    table_index = 0
    for node in document.iter():
        tag = node.tag.lower() if isinstance(node.tag, str) else ""
        if re.fullmatch(r"h[1-6]", tag):
            level = int(tag[1])
            text = clean_text(" ".join(node.itertext()))
            for old_level in [key for key in stack if key >= level]:
                del stack[old_level]
            if text:
                stack[level] = text
            denominator_note = ""
        elif tag == "p":
            text = clean_text(" ".join(node.itertext()))
            if EXPLICIT_DENOM_RE.search(unicodedata.normalize("NFKC", text)):
                denominator_note = text
        elif tag == "table":
            table_paths[table_index] = [stack[level] for level in sorted(stack)] + (
                [denominator_note] if denominator_note else []
            )
            table_index += 1
    return table_paths


def content_question(path: list[str], fallback: str) -> tuple[str, str, list[str]]:
    filtered = [
        clean_text(value)
        for value in path
        if clean_text(value)
        and not ("人気投票" in value and re.search(r"第\s*\d+\s*回", value))
        and value not in {"アンケート投票結果", "アンケート部門集計結果", "アンケート集計結果"}
    ]
    fallback = clean_text(fallback)
    if fallback and fallback not in filtered:
        filtered.append(fallback)
    if not filtered:
        filtered = [fallback or "アンケート"]
    numbered = [value for value in filtered if re.match(r"^[0-9０-９]+[.．、]", value)]
    question = numbered[0] if numbered else filtered[0]
    item = filtered[-1] if len(filtered) > 1 and filtered[-1] != question else ""
    return question, item, filtered


class AtomicCsv:
    def __init__(self, path: Path, fieldnames: list[str]) -> None:
        self.path = path
        self.fieldnames = fieldnames
        self.tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
        self.handle: Any = None
        self.writer: csv.DictWriter[str] | None = None
        self.rows = 0

    def __enter__(self) -> "AtomicCsv":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.tmp.open("w", encoding="utf-8-sig", newline="")
        self.writer = csv.DictWriter(self.handle, fieldnames=self.fieldnames, extrasaction="ignore")
        self.writer.writeheader()
        return self

    def write(self, row: dict[str, Any]) -> None:
        assert self.writer is not None
        self.writer.writerow({field: row.get(field, "") for field in self.fieldnames})
        self.rows += 1

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.handle:
            self.handle.close()
        if exc_type is None:
            os.replace(self.tmp, self.path)
        elif self.tmp.exists():
            self.tmp.unlink()


@dataclass
class SourceMetric:
    round_no: int
    category: str
    entity_name: str
    rank: int | None
    points: int | None
    first_choice_count: int | None
    vote_count: int | None
    comment_count: int | None
    source_url: str
    source_sha256: str
    source_file: str


class Normalizer:
    def __init__(self, workspace: Path, raw_root: Path, output_root: Path, metadata_root: Path) -> None:
        self.workspace = workspace.resolve()
        self.raw_root = raw_root.resolve()
        self.output_root = output_root.resolve()
        self.metadata_root = metadata_root.resolve()
        self.stats: Counter[str] = Counter()
        self.by_round: dict[int, Counter[str]] = defaultdict(Counter)
        self.denom_bases: Counter[str] = Counter()
        self.validation_issues: list[dict[str, Any]] = []
        self.source_metrics: dict[tuple[int, str, str], SourceMetric] = {}
        self.crawl_manifest_path = self.metadata_root / "jp_official_legacy_manifest.json"
        self.crawl_coverage_path = self.metadata_root / "jp_official_legacy_coverage.json"

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.workspace).as_posix()

    def exception(
        self,
        output: AtomicCsv,
        round_no: int,
        scope: str,
        source_file: Path,
        source_url: str,
        table_index: int | str,
        row_index: int | str,
        reason: str,
        texts: list[str] | None = None,
    ) -> None:
        output.write(
            {
                "round": round_no,
                "scope": scope,
                "source_file": self.rel(source_file),
                "source_url": source_url,
                "table_index": table_index,
                "row_index": row_index,
                "reason": reason,
                "raw_cells_json": raw_cells(texts or []),
            }
        )
        self.stats["exceptions"] += 1

    def load_source_metrics(self, metric_output: AtomicCsv, exception_output: AtomicCsv) -> None:
        for round_no in range(11, 17):
            list_dir = self.raw_root / f"round_{round_no:02d}" / "lists"
            for parsed_path in sorted(list_dir.glob("*.tables.json")):
                data = json.loads(parsed_path.read_text(encoding="utf-8"))
                category = clean_text(data.get("category") or "")
                if category == "title":
                    category = "work"
                if category not in {"character", "music", "work", "partner"}:
                    name = parsed_path.name.lower()
                    category = (
                        "character" if "character" in name else
                        "music" if "music" in name else
                        "work" if "title" in name else
                        "partner" if "partner" in name else "other"
                    )
                source = data.get("source", {})
                for table in data.get("numeric_tables", []):
                    rows = table.get("rows", [])
                    if not rows:
                        continue
                    headers = cells_text(rows[0])
                    try:
                        name_index = headers.index("名前")
                        point_index = headers.index("ポイント")
                        first_index = headers.index("一押し")
                    except ValueError:
                        self.exception(
                            exception_output,
                            round_no,
                            "source_metric",
                            parsed_path,
                            source.get("url", ""),
                            table.get("table_index", ""),
                            rows[0].get("row_index", ""),
                            "unrecognized_ranking_header",
                            headers,
                        )
                        continue
                    rank_index = headers.index("順位") if "順位" in headers else None
                    comment_index = headers.index("コメント") if "コメント" in headers else None
                    for row in rows[1:]:
                        texts = cells_text(row)
                        if len(texts) <= max(name_index, point_index, first_index):
                            continue
                        entity_name = texts[name_index]
                        points = parse_int(texts[point_index])
                        first = parse_int(texts[first_index])
                        if not entity_name or points is None or first is None:
                            continue
                        vote_count = points - first
                        metric = SourceMetric(
                            round_no=round_no,
                            category=category,
                            entity_name=entity_name,
                            rank=parse_int(texts[rank_index]) if rank_index is not None and rank_index < len(texts) else None,
                            points=points,
                            first_choice_count=first,
                            vote_count=vote_count,
                            comment_count=parse_int(texts[comment_index]) if comment_index is not None and comment_index < len(texts) else None,
                            source_url=source.get("url", ""),
                            source_sha256=source.get("sha256", ""),
                            source_file=self.rel(parsed_path),
                        )
                        key = (round_no, category, norm_key(entity_name))
                        self.source_metrics[key] = metric
                        metric_output.write(
                            {
                                "region": "jp",
                                "round": round_no,
                                "category": category,
                                "entity_name": entity_name,
                                "rank": metric.rank if metric.rank is not None else "",
                                "points": points,
                                "first_choice_count": first,
                                "vote_count": vote_count,
                                "vote_count_basis": "published_points_minus_published_first_choice_count",
                                "comment_count": metric.comment_count if metric.comment_count is not None else "",
                                "source_url": metric.source_url,
                                "source_sha256": metric.source_sha256,
                                "source_file": metric.source_file,
                            }
                        )
                        self.stats["source_metric_rows"] += 1
                        self.by_round[round_no]["source_metric_rows"] += 1

    def questionnaire_files(self) -> Iterator[tuple[int, Path]]:
        for round_no in range(3, 17):
            directory = self.raw_root / f"round_{round_no:02d}" / "questionnaire"
            for path in sorted(directory.glob("*.tables.json")):
                yield round_no, path

    def normalize_questionnaires(self, output: AtomicCsv, exception_output: AtomicCsv) -> None:
        for round_no, parsed_path in self.questionnaire_files():
            data = json.loads(parsed_path.read_text(encoding="utf-8"))
            source = data.get("source", {})
            raw_path = Path(str(parsed_path)[: -len(".tables.json")])
            paths = heading_paths(raw_path, source.get("charset") or "utf-8")
            for table in data.get("numeric_tables", []):
                table_index = int(table.get("table_index", 0))
                rows = table.get("rows", [])
                if not rows:
                    continue
                path = paths.get(table_index, [])
                context = table.get("context_heading", "")
                question, item, full_path = content_question(path, context)
                normalized = self._normalize_questionnaire_table(
                    round_no,
                    parsed_path,
                    source,
                    table,
                    question,
                    item,
                    full_path,
                    output,
                )
                if normalized == 0:
                    self.exception(
                        exception_output,
                        round_no,
                        "overall_questionnaire",
                        parsed_path,
                        source.get("url", ""),
                        table_index,
                        "",
                        "numeric_table_not_normalized",
                        cells_text(rows[0]),
                    )

    def _normalize_questionnaire_table(
        self,
        round_no: int,
        parsed_path: Path,
        source: dict[str, Any],
        table: dict[str, Any],
        question: str,
        item: str,
        full_path: list[str],
        output: AtomicCsv,
    ) -> int:
        rows = table.get("rows", [])
        table_index = int(table.get("table_index", 0))
        first = cells_text(rows[0])
        explicit, explicit_unit, explicit_basis = explicit_denominator(full_path + [table.get("context_heading", "")])
        base = {
            "region": "jp",
            "round": round_no,
            "scope": "overall_questionnaire",
            "source_url": source.get("url", ""),
            "source_sha256": source.get("sha256", ""),
            "source_file": self.rel(parsed_path),
            "source_table_index": table_index,
            "question_id": question_slug(round_no, question),
            "question": question,
            "question_path_json": json.dumps(full_path, ensure_ascii=False, separators=(",", ":")),
            "table_variant": f"table_{table_index}",
        }

        # Cross-tabulations are encoded as alternating count and percentage
        # rows beneath one option header row.  Normalize one cell per cohort ×
        # option and retain the exact cohort denominator.
        if len(rows) >= 3 and len(first) >= 3:
            second = cells_text(rows[1])
            third = cells_text(rows[2])
            percent_cells = [parse_percent(text) for text in third]
            looks_like_cross_tab = (
                len(second) >= len(first)
                and all(parse_int(text) is not None for text in second[1 : len(first)])
                and len(third) in {len(first) - 1, len(first)}
                and bool(percent_cells)
                and all(value is not None for value in percent_cells)
            )
            if looks_like_cross_tab:
                written = 0
                pair_index = 1
                while pair_index + 1 < len(rows):
                    count_row = rows[pair_index]
                    percent_row = rows[pair_index + 1]
                    count_texts = cells_text(count_row)
                    percent_texts = cells_text(percent_row)
                    parsed_percents = [parse_percent(text) for text in percent_texts]
                    if (
                        len(count_texts) < len(first)
                        or len(percent_texts) not in {len(first) - 1, len(first)}
                        or not all(value is not None for value in parsed_percents)
                    ):
                        pair_index += 1
                        continue
                    pairs: list[tuple[int, DisplayPercent]] = []
                    for column in range(1, len(first)):
                        count = parse_int(count_texts[column])
                        percent_index = column - 1 if len(percent_texts) == len(first) - 1 else column
                        percent = parsed_percents[percent_index]
                        if count is not None and percent is not None:
                            pairs.append((count, percent))
                    summed = sum(count for count, _percent in pairs)
                    if summed > 0 and all(
                        displayed_percent_matches(count, summed, percent) for count, percent in pairs
                    ):
                        denominator = DenominatorResult(
                            summed,
                            "sum_of_complete_cross_tab_row",
                        )
                    else:
                        denominator = solve_unique_denominator(pairs)
                    for column in range(1, len(first)):
                        count = parse_int(count_texts[column])
                        percent_index = column - 1 if len(percent_texts) == len(first) - 1 else column
                        percent = parsed_percents[percent_index]
                        if count is None or percent is None:
                            continue
                        output.write(
                            {
                                **base,
                                "source_row_index": count_row.get("row_index", ""),
                                "item": count_texts[0],
                                "option": first[column],
                                "count": count,
                                "count_unit": "",
                                "percentage": format_decimal(percent.value),
                                "official_percentage": format_decimal(percent.value),
                                "percentage_basis": "official",
                                "denominator": denominator.value if denominator.value is not None else "",
                                "denominator_unit": "",
                                "denominator_basis": denominator.basis,
                                "denominator_candidate_min": denominator.candidate_min or "",
                                "denominator_candidate_max": denominator.candidate_max or "",
                                "raw_cells_json": json.dumps(
                                    {"counts": count_texts, "percentages": percent_texts},
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ),
                            }
                        )
                        self.record_row(round_no, "questionnaire_rows", denominator.basis)
                        written += 1
                    pair_index += 2
                if written:
                    return written

        # Event-purpose tables mix a top-level attendance split with options
        # conditional on the attendee base.  Column placement changed across
        # rounds 12--16, so normalize the structural parent and children
        # explicitly instead of applying one denominator to the whole table.
        if "即売会に参加する際の目当て" in question or "即売会に参加する際の目当て" in table.get("context_heading", ""):
            row_texts = [(row, cells_text(row)) for row in rows]
            first_row, first_texts = row_texts[0]
            nonparticipant_count: int | None = None
            nonparticipant_percent: DisplayPercent | None = None
            if len(first_texts) >= 5 and parse_int(first_texts[3]) is not None:
                nonparticipant_count = parse_int(first_texts[3])
                nonparticipant_percent = parse_percent(first_texts[4])
            elif len(first_texts) >= 3:
                nonparticipant_count = parse_int(first_texts[1])
                nonparticipant_percent = next(
                    (value for text in first_texts[2:] if (value := parse_percent(text)) is not None),
                    None,
                )

            parent_count: int | None = None
            parent_percent: DisplayPercent | None = None
            option_entries: list[tuple[dict[str, Any], list[str], str, int, DisplayPercent, list[DisplayPercent]]] = []
            if len(row_texts) >= 2:
                second_row, second_texts = row_texts[1]
                # Round 14: option in columns 1/2; parent in 3/4.
                if len(second_texts) >= 5 and parse_int(first_texts[1]) is None:
                    parent_count = parse_int(second_texts[3])
                    parent_percent = parse_percent(second_texts[4])
                    option_count = parse_int(second_texts[1])
                    option_percent = parse_percent(second_texts[2])
                # Rounds 15/16: parent in 1/2; first option in 3/4.
                elif len(second_texts) >= 5:
                    parent_count = parse_int(second_texts[1])
                    parent_percent = parse_percent(second_texts[2])
                    option_count = parse_int(second_texts[3])
                    option_percent = parse_percent(second_texts[4])
                # Rounds 12/13: option in 1/2; the unlabeled conditional
                # base is the published count in the first row.
                else:
                    parent_count = nonparticipant_count
                    option_count = parse_int(second_texts[1]) if len(second_texts) > 1 else None
                    option_percent = parse_percent(second_texts[2]) if len(second_texts) > 2 else None
                    extra = [value for text in second_texts[3:] if (value := parse_percent(text)) is not None]
                    if extra:
                        parent_percent = extra[0]
                if option_count is not None and option_percent is not None:
                    extras = [
                        value
                        for text in second_texts[3:]
                        if (value := parse_percent(text)) is not None and value != option_percent
                    ]
                    option_entries.append(
                        (second_row, second_texts, second_texts[0], option_count, option_percent, extras)
                    )
                for child_row, child_texts in row_texts[2:]:
                    if len(child_texts) < 3:
                        continue
                    child_count = parse_int(child_texts[1])
                    child_percent = parse_percent(child_texts[2])
                    if child_count is not None and child_percent is not None:
                        option_entries.append(
                            (child_row, child_texts, child_texts[0], child_count, child_percent, [])
                        )

            top_pairs = [
                (count, percent)
                for count, percent in (
                    (nonparticipant_count, nonparticipant_percent),
                    (parent_count, parent_percent),
                )
                if count is not None and percent is not None
            ]
            if explicit is not None:
                top_denominator = DenominatorResult(explicit, explicit_basis)
            elif top_pairs and sum(count for count, _percent in top_pairs) > 0 and all(
                displayed_percent_matches(count, sum(pair[0] for pair in top_pairs), percent)
                for count, percent in top_pairs
            ):
                top_denominator = DenominatorResult(
                    sum(count for count, _percent in top_pairs),
                    "sum_of_published_attendance_split",
                )
            else:
                top_denominator = solve_unique_denominator(top_pairs)

            written = 0
            if nonparticipant_count is not None and nonparticipant_percent is not None:
                output.write(
                    {
                        **base,
                        "source_row_index": first_row.get("row_index", ""),
                        "item": "attendance_split",
                        "option": first_texts[0],
                        "count": nonparticipant_count,
                        "percentage": format_decimal(nonparticipant_percent.value),
                        "official_percentage": format_decimal(nonparticipant_percent.value),
                        "percentage_basis": "official",
                        "denominator": top_denominator.value if top_denominator.value is not None else "",
                        "denominator_unit": explicit_unit,
                        "denominator_basis": top_denominator.basis,
                        "denominator_candidate_min": top_denominator.candidate_min or "",
                        "denominator_candidate_max": top_denominator.candidate_max or "",
                        "raw_cells_json": raw_cells(first_texts),
                    }
                )
                self.record_row(round_no, "questionnaire_rows", top_denominator.basis)
                written += 1
            if parent_count is not None and parent_percent is not None and len(row_texts[1][1]) >= 5:
                output.write(
                    {
                        **base,
                        "source_row_index": row_texts[1][0].get("row_index", ""),
                        "item": "attendance_split",
                        "option": "__UNLABELED_PARENT_GROUP__",
                        "count": parent_count,
                        "percentage": format_decimal(parent_percent.value),
                        "official_percentage": format_decimal(parent_percent.value),
                        "percentage_basis": "official_unlabeled_structural_parent",
                        "denominator": top_denominator.value if top_denominator.value is not None else "",
                        "denominator_unit": explicit_unit,
                        "denominator_basis": top_denominator.basis,
                        "denominator_candidate_min": top_denominator.candidate_min or "",
                        "denominator_candidate_max": top_denominator.candidate_max or "",
                        "raw_cells_json": raw_cells(row_texts[1][1]),
                    }
                )
                self.record_row(round_no, "questionnaire_rows", top_denominator.basis)
                written += 1
            child_denominator = DenominatorResult(
                parent_count,
                "published_table_conditional_base_count" if parent_count is not None else "not_available",
            )
            for child_row, child_texts, label, child_count, child_percent, extras in option_entries:
                output.write(
                    {
                        **base,
                        "source_row_index": child_row.get("row_index", ""),
                        "item": "attendance_purpose",
                        "option": label,
                        "count": child_count,
                        "percentage": format_decimal(child_percent.value),
                        "official_percentage": format_decimal(child_percent.value),
                        "additional_official_percentages_json": json.dumps(
                            [format_decimal(value.value) for value in extras], separators=(",", ":")
                        ),
                        "percentage_basis": "official_conditional_on_table_parent_group",
                        "denominator": child_denominator.value if child_denominator.value is not None else "",
                        "denominator_unit": "",
                        "denominator_basis": child_denominator.basis,
                        "raw_cells_json": raw_cells(child_texts),
                    }
                )
                self.record_row(round_no, "questionnaire_rows", child_denominator.basis)
                written += 1
            if written:
                return written

        # Ranked questionnaire matrix: each work has rank/points and separate
        # first-, second-, and third-place vote counts with official shares.
        if (
            len(first) >= 9
            and first[:3] == ["順位", "作品名", "ポイント"]
            and first[3] in {"1位票", "１位票"}
        ):
            written = 0
            denominator = DenominatorResult(
                explicit,
                explicit_basis if explicit is not None else "not_available",
            )
            for row in rows[1:]:
                texts = cells_text(row)
                if len(texts) < 9:
                    continue
                rank = parse_int(texts[0])
                points = parse_int(texts[2])
                for count_column, percent_column in ((3, 4), (5, 6), (7, 8)):
                    count = parse_int(texts[count_column])
                    percent = parse_percent(texts[percent_column])
                    if count is None:
                        continue
                    output.write(
                        {
                            **base,
                            "source_row_index": row.get("row_index", ""),
                            "rank": rank if rank is not None else "",
                            "points": points if points is not None else "",
                            "item": texts[1],
                            "option": first[count_column],
                            "count": count,
                            "count_unit": "票",
                            "percentage": format_decimal(percent.value) if percent else "",
                            "official_percentage": format_decimal(percent.value) if percent else "",
                            "percentage_basis": "official" if percent else "not_available",
                            "denominator": denominator.value if denominator.value is not None else "",
                            "denominator_unit": explicit_unit,
                            "denominator_basis": denominator.basis,
                            "raw_cells_json": raw_cells(texts),
                        }
                    )
                    self.record_row(round_no, "questionnaire_rows", denominator.basis)
                    written += 1
            return written

        # Horizontal matrix: item | explicit denominator | option columns.
        if len(first) >= 3 and any(value in {"有効回答", "有効回答数"} for value in first[1:2]):
            written = 0
            for row in rows[1:]:
                texts = cells_text(row)
                if len(texts) < 3:
                    continue
                denominator = parse_int(texts[1])
                if denominator is None:
                    continue
                for column in range(2, min(len(first), len(texts))):
                    count = parse_int(texts[column])
                    option = first[column]
                    if count is None or not option:
                        continue
                    percentage = Decimal(count) * 100 / Decimal(denominator) if denominator else None
                    output.write(
                        {
                            **base,
                            "source_row_index": row.get("row_index", ""),
                            "item": texts[0],
                            "option": option,
                            "count": count,
                            "count_unit": "",
                            "percentage": format_decimal(percentage),
                            "official_percentage": "",
                            "percentage_basis": "computed_from_exact_official_count_and_denominator",
                            "denominator": denominator,
                            "denominator_unit": "",
                            "denominator_basis": "explicit_official_table_cell",
                            "raw_cells_json": raw_cells(texts),
                        }
                    )
                    self.record_row(round_no, "questionnaire_rows", "explicit_official_table_cell")
                    written += 1
            return written

        # Vertical special case: [item, 有効回答数:N], followed by options.
        special_denominator = parse_int(first[1]) if len(first) >= 2 and "有効回答" in first[1] else None
        if special_denominator is not None:
            written = 0
            for row in rows[1:]:
                texts = cells_text(row)
                if len(texts) < 2:
                    continue
                count = parse_int(texts[1])
                if count is None:
                    continue
                percent = next((parse_percent(text) for text in texts[2:] if parse_percent(text)), None)
                computed = Decimal(count) * 100 / Decimal(special_denominator) if special_denominator else None
                output.write(
                    {
                        **base,
                        "source_row_index": row.get("row_index", ""),
                        "item": first[0] or item,
                        "option": texts[0],
                        "count": count,
                        "count_unit": count_unit(texts[1]),
                        "percentage": format_decimal(percent.value if percent else computed),
                        "official_percentage": format_decimal(percent.value) if percent else "",
                        "percentage_basis": "official" if percent else "computed_from_exact_official_count_and_denominator",
                        "denominator": special_denominator,
                        "denominator_unit": count_unit(first[1]),
                        "denominator_basis": "explicit_official_table_cell",
                        "raw_cells_json": raw_cells(texts),
                    }
                )
                self.record_row(round_no, "questionnaire_rows", "explicit_official_table_cell")
                written += 1
            return written

        simple: list[tuple[dict[str, Any], list[str], int, DisplayPercent | None]] = []
        for row in rows:
            texts = cells_text(row)
            if len(texts) < 2:
                continue
            count = parse_int(texts[1])
            if count is None or any(token in texts[1] for token in ("回答数", "投票数", "有効回答")):
                continue
            percent = next((value for text in texts[2:] if (value := parse_percent(text)) is not None), None)
            simple.append((row, texts, count, percent))
        if not simple:
            return 0

        if explicit is not None:
            denominator = DenominatorResult(explicit, explicit_basis)
            denominator_unit = explicit_unit
        else:
            sum_percent = sum((entry[3].value for entry in simple if entry[3]), Decimal(0))
            all_have_percent = all(entry[3] is not None for entry in simple)
            if all_have_percent and Decimal("99.5") <= sum_percent <= Decimal("100.5"):
                summed = sum(entry[2] for entry in simple)
                if all(displayed_percent_matches(count, summed, percent) for _row, _text, count, percent in simple if percent):
                    denominator = DenominatorResult(summed, "sum_of_complete_mutually_exclusive_official_counts")
                else:
                    denominator = solve_unique_denominator((count, percent) for _row, _text, count, percent in simple if percent)
            else:
                denominator = solve_unique_denominator((count, percent) for _row, _text, count, percent in simple if percent)
            denominator_unit = ""

        written = 0
        for row, texts, count, percent in simple:
            computed = (
                Decimal(count) * 100 / Decimal(denominator.value)
                if percent is None and denominator.value
                else None
            )
            output.write(
                {
                    **base,
                    "source_row_index": row.get("row_index", ""),
                    "item": item,
                    "option": texts[0],
                    "count": count,
                    "count_unit": count_unit(texts[1]),
                    "percentage": format_decimal(percent.value if percent else computed),
                    "official_percentage": format_decimal(percent.value) if percent else "",
                    "percentage_basis": "official" if percent else (
                        "computed_from_exact_official_count_and_denominator" if computed is not None else "not_available"
                    ),
                    "denominator": denominator.value if denominator.value is not None else "",
                    "denominator_unit": denominator_unit,
                    "denominator_basis": denominator.basis,
                    "denominator_candidate_min": denominator.candidate_min or "",
                    "denominator_candidate_max": denominator.candidate_max or "",
                    "raw_cells_json": raw_cells(texts),
                }
            )
            self.record_row(round_no, "questionnaire_rows", denominator.basis)
            written += 1
        return written

    def record_row(self, round_no: int, kind: str, denominator_basis: str | None = None) -> None:
        self.stats[kind] += 1
        self.by_round[round_no][kind] += 1
        if denominator_basis:
            self.denom_bases[denominator_basis] += 1

    @staticmethod
    def detail_entity_name(data: dict[str, Any]) -> str:
        summary = data.get("summary", [])
        title = next((line.get("text", "") for line in summary if line.get("kind") == "title"), "")
        match = TITLE_ENTITY_RE.search(title)
        if match:
            return clean_text(match.group(1))
        heading = next((line.get("text", "") for line in summary if line.get("kind") == "item_heading"), "")
        return re.sub(r"（\d+位）$", "", clean_text(heading))

    @staticmethod
    def summary_vote_count(data: dict[str, Any]) -> int | None:
        for line in data.get("summary", []):
            match = SUMMARY_VOTES_RE.search(unicodedata.normalize("NFKC", line.get("text", "")))
            if match:
                return int(match.group(1).replace(",", ""))
        return None

    @staticmethod
    def association_target_category(context: str, source_category: str) -> str:
        if "人妖部門" in context:
            return "character"
        if "音楽部門" in context:
            return "music"
        if "作品部門" in context:
            return "work"
        if "同一票として" in context:
            return "variant"
        if "ベストパートナー" in context:
            return "partner"
        if "他の投票状況" in context:
            return source_category
        return "other"

    def normalize_details(
        self,
        question_output: AtomicCsv,
        association_output: AtomicCsv,
        exception_output: AtomicCsv,
    ) -> None:
        for round_no in range(11, 17):
            detail_root = self.raw_root / f"round_{round_no:02d}" / "details"
            for parsed_path in sorted(detail_root.glob("*/*.json")):
                data = json.loads(parsed_path.read_text(encoding="utf-8"))
                source_category = parsed_path.parent.name
                entity_name = self.detail_entity_name(data)
                source = data.get("source", {})
                source_vote_count = self.summary_vote_count(data)
                metric = self.source_metrics.get((round_no, source_category, norm_key(entity_name)))
                if source_vote_count is None and metric:
                    source_vote_count = metric.vote_count

                question_tables: list[dict[str, Any]] = []
                association_tables: list[dict[str, Any]] = []
                for table in data.get("numeric_tables", []):
                    rows = table.get("rows", [])
                    first = cells_text(rows[0]) if rows else []
                    if len(first) >= 2 and "回答数" in first[1]:
                        question_tables.append(table)
                    elif (
                        (first and first[0] in {"投票対象", "順位"})
                        or "投票状況" in table.get("context_heading", "")
                        or "ベストパートナー順位" in table.get("context_heading", "")
                    ):
                        association_tables.append(table)
                    else:
                        self.exception(
                            exception_output,
                            round_no,
                            "entity_detail",
                            parsed_path,
                            source.get("url", ""),
                            table.get("table_index", ""),
                            "",
                            "unclassified_entity_numeric_table",
                            first,
                        )

                for table in question_tables:
                    self._write_entity_question_table(
                        round_no,
                        parsed_path,
                        data,
                        entity_name,
                        source_category,
                        table,
                        question_output,
                    )
                self._write_entity_associations(
                    round_no,
                    parsed_path,
                    data,
                    entity_name,
                    source_category,
                    source_vote_count,
                    association_tables,
                    association_output,
                    exception_output,
                )

    def _write_entity_question_table(
        self,
        round_no: int,
        parsed_path: Path,
        data: dict[str, Any],
        entity_name: str,
        source_category: str,
        table: dict[str, Any],
        output: AtomicCsv,
    ) -> None:
        rows = table.get("rows", [])
        if len(rows) < 2:
            return
        header = cells_text(rows[0])
        parsed_rows: list[tuple[dict[str, Any], list[str], int, DisplayPercent | None]] = []
        for row in rows[1:]:
            texts = cells_text(row)
            if len(texts) < 2:
                continue
            count = parse_int(texts[1])
            if count is None:
                continue
            percent = parse_percent(texts[2]) if len(texts) > 2 else None
            parsed_rows.append((row, texts, count, percent))
        if not parsed_rows:
            return
        summed = sum(row[2] for row in parsed_rows)
        hierarchical = any(texts[0].startswith("うち") for _row, texts, _count, _percent in parsed_rows)
        row_denominators: dict[int, DenominatorResult] = {}
        if hierarchical:
            parent_rows = [entry for entry in parsed_rows if not entry[1][0].startswith("うち")]
            parent_solution = solve_unique_denominator(
                (count, percent) for _row, _texts, count, percent in parent_rows if percent
            )
            parent_count = parent_rows[0][2] if parent_rows else None
            for row, texts, _count, _percent in parsed_rows:
                if texts[0].startswith("うち") and parent_count is not None:
                    row_denominators[id(row)] = DenominatorResult(
                        parent_count,
                        "published_parent_option_count",
                    )
                else:
                    row_denominators[id(row)] = parent_solution
        elif summed > 0 and all(
            row[3] and displayed_percent_matches(row[2], summed, row[3]) for row in parsed_rows
        ):
            denominator = DenominatorResult(summed, "sum_of_complete_entity_question_options")
            row_denominators = {id(row): denominator for row, _texts, _count, _percent in parsed_rows}
        else:
            denominator = solve_unique_denominator(
                (count, percent) for _row, _text, count, percent in parsed_rows if percent
            )
            row_denominators = {id(row): denominator for row, _texts, _count, _percent in parsed_rows}
        question = header[0]
        source = data.get("source", {})
        for row, texts, count, percent in parsed_rows:
            denominator = row_denominators[id(row)]
            overall = parse_percent(texts[3]) if len(texts) > 3 else None
            delta = parse_points(texts[4]) if len(texts) > 4 else None
            output.write(
                {
                    "region": "jp",
                    "round": round_no,
                    "source_category": source_category,
                    "source_item_id": data.get("item_id", ""),
                    "source_entity_name": entity_name,
                    "source_url": source.get("url", ""),
                    "source_sha256": source.get("sha256", ""),
                    "source_table_index": table.get("table_index", ""),
                    "source_row_index": row.get("row_index", ""),
                    "question_id": question_slug(round_no, question, "entityq"),
                    "question": question,
                    "option": texts[0],
                    "count": count,
                    "percentage": format_decimal(percent.value) if percent else "",
                    "overall_percentage": format_decimal(overall.value) if overall else "",
                    "delta_points": delta if delta is not None else "",
                    "denominator": denominator.value if denominator.value is not None else "",
                    "denominator_basis": denominator.basis,
                    "denominator_candidate_min": denominator.candidate_min or "",
                    "denominator_candidate_max": denominator.candidate_max or "",
                    "raw_cells_json": raw_cells(texts),
                }
            )
            self.record_row(round_no, "entity_question_rows", denominator.basis)

    def _write_entity_associations(
        self,
        round_no: int,
        parsed_path: Path,
        data: dict[str, Any],
        entity_name: str,
        source_category: str,
        source_vote_count: int | None,
        tables: list[dict[str, Any]],
        output: AtomicCsv,
        exception_output: AtomicCsv,
    ) -> None:
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        source = data.get("source", {})
        for table in tables:
            context = clean_text(table.get("context_heading", ""))
            target_category = self.association_target_category(context, source_category)
            rows = table.get("rows", [])
            first = cells_text(rows[0]) if rows else []
            if first and first[0] == "投票対象":
                kind = "conditional_co_vote"
                data_rows = rows[1:]
            elif first and first[0] == "順位" and len(first) > 1 and first[1] == "名前":
                kind = "partner_ranking"
                data_rows = rows[1:]
            elif "同一票として" in context:
                kind = "merged_entry_component"
                data_rows = rows
            else:
                self.exception(
                    exception_output,
                    round_no,
                    "entity_association",
                    parsed_path,
                    source.get("url", ""),
                    table.get("table_index", ""),
                    "",
                    "unrecognized_association_table",
                    first,
                )
                continue
            for row in data_rows:
                texts = cells_text(row)
                record: dict[str, Any] | None = None
                if kind == "conditional_co_vote" and len(texts) >= 3:
                    record = {
                        "target": texts[0],
                        "count": parse_int(texts[1]),
                        "percent": parse_percent(texts[2]),
                        "overall": parse_percent(texts[3]) if len(texts) > 3 else None,
                        "delta": parse_points(texts[4]) if len(texts) > 4 else None,
                    }
                elif kind == "merged_entry_component" and len(texts) >= 3:
                    record = {
                        "target": texts[0],
                        "count": parse_int(texts[1]),
                        "percent": parse_percent(texts[2]),
                        "overall": None,
                        "delta": None,
                    }
                elif kind == "partner_ranking" and len(texts) >= 5:
                    record = {
                        "target": texts[1],
                        "rank": parse_int(texts[0]),
                        "points": parse_int(texts[2]),
                        "first": parse_int(texts[3]),
                        "comments": parse_int(texts[4]),
                        "count": None,
                        "percent": None,
                        "overall": None,
                        "delta": None,
                    }
                if not record or not record.get("target"):
                    continue
                record.update(
                    {
                        "table_index": table.get("table_index", ""),
                        "row_index": row.get("row_index", ""),
                        "texts": texts,
                    }
                )
                groups[(context, target_category, kind)].append(record)

        for (context, target_category, kind), records in groups.items():
            deduped: dict[tuple[Any, ...], dict[str, Any]] = {}
            for record in records:
                percent = record.get("percent")
                overall = record.get("overall")
                key = (
                    norm_key(record["target"]),
                    record.get("count"),
                    str(percent.value) if percent else None,
                    str(overall.value) if overall else None,
                    record.get("delta"),
                    record.get("rank"),
                    record.get("points"),
                    record.get("first"),
                    record.get("comments"),
                )
                existing = deduped.get(key)
                if existing:
                    existing["table_indices"].append(record["table_index"])
                    existing["row_indices"].append(record["row_index"])
                    existing["raw_views"].append(record["texts"])
                else:
                    copied = dict(record)
                    copied["table_indices"] = [record["table_index"]]
                    copied["row_indices"] = [record["row_index"]]
                    copied["raw_views"] = [record["texts"]]
                    deduped[key] = copied
            unique = list(deduped.values())

            if kind == "partner_ranking":
                conditional = DenominatorResult(None, "not_applicable")
                overall_denom = DenominatorResult(None, "not_applicable")
            elif kind == "merged_entry_component":
                counts = [record["count"] for record in unique if record.get("count") is not None]
                percentages = [record.get("percent") for record in unique]
                summed = sum(counts)
                if counts and all(percentages) and all(
                    displayed_percent_matches(record["count"], summed, record["percent"])
                    for record in unique
                    if record.get("count") is not None and record.get("percent")
                ):
                    conditional = DenominatorResult(summed, "sum_of_complete_merged_entry_components")
                else:
                    conditional = solve_unique_denominator(
                        (record["count"], record["percent"])
                        for record in unique
                        if record.get("count") is not None and record.get("percent")
                    )
                overall_denom = DenominatorResult(None, "not_applicable")
            else:
                if target_category == source_category and source_vote_count:
                    pairs = [
                        (record["count"], record["percent"])
                        for record in unique
                        if record.get("count") is not None and record.get("percent")
                    ]
                    if pairs and all(displayed_percent_matches(count, source_vote_count, percent) for count, percent in pairs):
                        conditional = DenominatorResult(
                            source_vote_count,
                            "published_source_vote_count_from_points_minus_first_choice",
                        )
                    else:
                        conditional = solve_unique_denominator(pairs)
                else:
                    conditional = solve_unique_denominator(
                        (record["count"], record["percent"])
                        for record in unique
                        if record.get("count") is not None and record.get("percent")
                    )
                # The published "overall percentage" uses the target's global
                # vote count, not the conditional intersection count in this
                # row. Join the official main ranking metric before solving.
                overall_pairs: list[tuple[int, DisplayPercent]] = []
                for record in unique:
                    overall = record.get("overall")
                    target_metric = self.source_metrics.get(
                        (round_no, target_category, norm_key(record["target"]))
                    )
                    if overall and target_metric and target_metric.vote_count is not None:
                        overall_pairs.append((target_metric.vote_count, overall))
                overall_denom = solve_unique_denominator(overall_pairs)

            for record in unique:
                percent = record.get("percent")
                overall = record.get("overall")
                output.write(
                    {
                        "region": "jp",
                        "round": round_no,
                        "source_category": source_category,
                        "source_item_id": data.get("item_id", ""),
                        "source_entity_name": entity_name,
                        "source_vote_count": source_vote_count if source_vote_count is not None else "",
                        "target_category": target_category,
                        "target_entity_name": record["target"],
                        "association_context": context,
                        "association_kind": kind,
                        "vote_count": record.get("count") if record.get("count") is not None else "",
                        "conditional_percentage": format_decimal(percent.value) if percent else "",
                        "conditional_denominator": conditional.value if conditional.value is not None else "",
                        "conditional_denominator_basis": conditional.basis,
                        "conditional_denominator_candidate_min": conditional.candidate_min or "",
                        "conditional_denominator_candidate_max": conditional.candidate_max or "",
                        "overall_percentage": format_decimal(overall.value) if overall else "",
                        "overall_denominator": overall_denom.value if overall_denom.value is not None else "",
                        "overall_denominator_basis": overall_denom.basis,
                        "overall_denominator_candidate_min": overall_denom.candidate_min or "",
                        "overall_denominator_candidate_max": overall_denom.candidate_max or "",
                        "delta_points": record.get("delta") if record.get("delta") is not None else "",
                        "rank": record.get("rank") if record.get("rank") is not None else "",
                        "points": record.get("points") if record.get("points") is not None else "",
                        "first_choice_count": record.get("first") if record.get("first") is not None else "",
                        "comment_count": record.get("comments") if record.get("comments") is not None else "",
                        "appearances": len(record["table_indices"]),
                        "source_table_indices_json": json.dumps(record["table_indices"], separators=(",", ":")),
                        "source_row_indices_json": json.dumps(record["row_indices"], separators=(",", ":")),
                        "source_url": source.get("url", ""),
                        "source_sha256": source.get("sha256", ""),
                        "raw_cells_json": json.dumps(record["raw_views"], ensure_ascii=False, separators=(",", ":")),
                    }
                )
                self.record_row(round_no, "entity_association_rows", conditional.basis)
                self.denom_bases["overall:" + overall_denom.basis] += 1

    def validate_output_csv(self, path: Path, expected_rows: int) -> dict[str, Any]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = sum(1 for _ in reader)
        result = {
            "path": self.rel(path),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "rows": rows,
            "expected_rows": expected_rows,
            "row_count_matches": rows == expected_rows,
        }
        if rows != expected_rows:
            self.validation_issues.append(
                {"file": self.rel(path), "issue": f"row count {rows} != expected {expected_rows}"}
            )
        return result

    def validate_semantics(self, question_path: Path, entity_question_path: Path, association_path: Path) -> dict[str, Any]:
        checks = Counter()
        failures: list[dict[str, Any]] = []

        def add_failure(file: Path, row_no: int, issue: str) -> None:
            if len(failures) < 200:
                failures.append({"file": self.rel(file), "row": row_no, "issue": issue})

        for path, kind in (
            (question_path, "questionnaire"),
            (entity_question_path, "entity_question"),
        ):
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row_no, row in enumerate(csv.DictReader(handle), start=2):
                    checks[kind + "_rows"] += 1
                    count = int(row["count"]) if row.get("count") else None
                    denominator = int(row["denominator"]) if row.get("denominator") else None
                    percent_text = row.get("official_percentage") or row.get("percentage")
                    if count is not None and count < 0:
                        add_failure(path, row_no, "negative count")
                    if denominator is not None and count is not None and count > denominator:
                        add_failure(path, row_no, "count exceeds denominator")
                    if percent_text:
                        value = Decimal(percent_text)
                        if value < 0 or value > 100:
                            add_failure(path, row_no, "percentage outside 0..100")

        with association_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row_no, row in enumerate(csv.DictReader(handle), start=2):
                checks["association_rows"] += 1
                count = int(row["vote_count"]) if row.get("vote_count") else None
                denominator = int(row["conditional_denominator"]) if row.get("conditional_denominator") else None
                if count is not None and denominator is not None and count > denominator:
                    add_failure(association_path, row_no, "association count exceeds conditional denominator")
                if row.get("conditional_percentage"):
                    value = Decimal(row["conditional_percentage"])
                    if value < 0 or value > 100:
                        add_failure(association_path, row_no, "conditional percentage outside 0..100")
                if row.get("overall_percentage"):
                    value = Decimal(row["overall_percentage"])
                    if value < 0 or value > 100:
                        add_failure(association_path, row_no, "overall percentage outside 0..100")
                if row.get("delta_points") and row.get("conditional_percentage") and row.get("overall_percentage"):
                    delta = Decimal(row["delta_points"])
                    expected = Decimal(row["conditional_percentage"]) - Decimal(row["overall_percentage"])
                    if abs(delta - expected) > Decimal("0.03"):
                        add_failure(association_path, row_no, "published delta inconsistent with percentages")
        self.validation_issues.extend(failures)
        return {"checks": dict(checks), "semantic_failures": failures}

    def component_status(self) -> dict[str, Any]:
        coverage = json.loads(self.crawl_coverage_path.read_text(encoding="utf-8"))
        canonical = {"character", "music", "work", "partner", "spell"}
        rounds: dict[str, Any] = {}
        for round_no in range(3, 17):
            crawl = coverage["rounds"][str(round_no)]
            if round_no <= 10:
                available_rankings = {"character", "music"}
                # Discover exceptional historical departments from manifest categories.
                manifest = json.loads(self.crawl_manifest_path.read_text(encoding="utf-8"))
                available_rankings.update(
                    entry.get("category")
                    for entry in manifest["entries"]
                    if entry["round"] == round_no
                    and entry["role"] == "aggregate"
                    and entry.get("category") in canonical
                )
            else:
                available_rankings = set(crawl.get("detail_categories", {}))
            detail_categories = sorted(crawl.get("detail_categories", {}))
            rounds[str(round_no)] = {
                "questionnaire": "available_crawled" if crawl.get("roles_ok", {}).get("questionnaire", 0) else "fetch_failed",
                "ranking_categories_available_crawled": sorted(available_rankings),
                "ranking_categories_official_not_offered": sorted(canonical - available_rankings),
                "entity_detail_categories_available_crawled": detail_categories,
                "entity_numeric_profiles": (
                    "official_not_offered"
                    if round_no <= 10
                    else "available_crawled"
                ),
                "questionnaire_rows": self.by_round[round_no]["questionnaire_rows"],
                "source_metric_rows": self.by_round[round_no]["source_metric_rows"],
                "entity_questionnaire_rows": self.by_round[round_no]["entity_question_rows"],
                "entity_association_rows": self.by_round[round_no]["entity_association_rows"],
                "fetch_failures": crawl.get("errors", []),
            }
        return {
            "schema_version": 1,
            "normalizer_version": NORMALIZER_VERSION,
            "meaning": {
                "available_crawled": "the official site exposed the component and the local crawl succeeded",
                "official_not_offered": "the archived official site did not expose this component; this is not a crawler failure",
                "fetch_failed": "the component was expected but the request failed",
            },
            "rounds": rounds,
        }

    def run(self) -> int:
        if not self.crawl_manifest_path.exists() or not self.crawl_coverage_path.exists():
            raise FileNotFoundError("crawl manifest/coverage is required; normalization never downloads data")
        question_path = self.output_root / "questionnaire_long.csv"
        entity_question_path = self.output_root / "entity_questionnaire_long.csv"
        association_path = self.output_root / "entity_association_long.csv"
        metric_path = self.output_root / "source_entity_metrics.csv"
        exception_path = self.output_root / "normalization_exceptions.csv"

        with (
            AtomicCsv(question_path, QUESTIONNAIRE_FIELDS) as questionnaire,
            AtomicCsv(entity_question_path, ENTITY_QUESTION_FIELDS) as entity_question,
            AtomicCsv(association_path, ASSOCIATION_FIELDS) as association,
            AtomicCsv(metric_path, METRIC_FIELDS) as metric,
            AtomicCsv(exception_path, EXCEPTION_FIELDS) as exceptions,
        ):
            self.load_source_metrics(metric, exceptions)
            self.normalize_questionnaires(questionnaire, exceptions)
            self.normalize_details(entity_question, association, exceptions)

        outputs = [
            self.validate_output_csv(question_path, self.stats["questionnaire_rows"]),
            self.validate_output_csv(entity_question_path, self.stats["entity_question_rows"]),
            self.validate_output_csv(association_path, self.stats["entity_association_rows"]),
            self.validate_output_csv(metric_path, self.stats["source_metric_rows"]),
            self.validate_output_csv(exception_path, self.stats["exceptions"]),
        ]
        semantics = self.validate_semantics(question_path, entity_question_path, association_path)
        component_status_path = self.metadata_root / "jp_official_legacy_component_status.json"
        json_dump(component_status_path, self.component_status())
        outputs.append(
            {
                "path": self.rel(component_status_path),
                "bytes": component_status_path.stat().st_size,
                "sha256": sha256_file(component_status_path),
                "rows": None,
            }
        )

        script_path = Path(__file__).resolve()
        metadata = {
            "schema_version": 1,
            "normalizer_version": NORMALIZER_VERSION,
            "offline_only": True,
            "input": {
                "raw_root": self.rel(self.raw_root),
                "crawl_manifest": self.rel(self.crawl_manifest_path),
                "crawl_manifest_sha256": sha256_file(self.crawl_manifest_path),
                "crawl_coverage": self.rel(self.crawl_coverage_path),
                "crawl_coverage_sha256": sha256_file(self.crawl_coverage_path),
            },
            "program": {"path": self.rel(script_path), "sha256": sha256_file(script_path)},
            "output_root": self.rel(self.output_root),
            "outputs": outputs,
            "row_counts": dict(sorted(self.stats.items())),
            "row_counts_by_round": {
                str(round_no): dict(sorted(counts.items()))
                for round_no, counts in sorted(self.by_round.items())
            },
            "denominator_basis_counts": dict(sorted(self.denom_bases.items())),
            "source_numeric_anomalies": {
                "conditional_or_question_rows_with_inconsistent_published_pairs": self.denom_bases[
                    "inconsistent_count_percentage_pairs"
                ],
                "overall_baseline_rows_with_inconsistent_published_pairs": self.denom_bases[
                    "overall:inconsistent_count_percentage_pairs"
                ],
                "interpretation": (
                    "These rows preserve official values but leave the denominator blank because no integer "
                    "is compatible with all printed counts/percentages. They are source-data warnings, not "
                    "normalizer failures."
                ),
            },
            "denominator_policy": {
                "official": "explicit values printed in a heading or table cell",
                "exact_sum": "sum only when published percentages prove a complete mutually-exclusive partition",
                "scoring_rule": "vote_count = published points - published first-choice count",
                "rounded_percent_solver": (
                    "populate only when all official count/percentage pairs yield one and only one integer "
                    "inside their printed-precision intervals (tie boundaries inclusive); ambiguous cases "
                    "stay blank and retain candidate bounds"
                ),
                "manual_or_estimated_values": 0,
            },
        }
        metadata_path = self.metadata_root / "jp_official_legacy_normalization.json"
        json_dump(metadata_path, metadata)

        validation = {
            "schema_version": 1,
            "normalizer_version": NORMALIZER_VERSION,
            "offline_only": True,
            "crawl_coverage_complete": json.loads(self.crawl_coverage_path.read_text(encoding="utf-8")).get("complete"),
            "files": outputs,
            "semantics": semantics,
            "normalization_exceptions": self.stats["exceptions"],
            "source_data_warnings": {
                "inconsistent_published_count_percentage_rows": self.denom_bases[
                    "inconsistent_count_percentage_pairs"
                ],
                "inconsistent_published_overall_baseline_rows": self.denom_bases[
                    "overall:inconsistent_count_percentage_pairs"
                ],
                "do_not_treat_as_pipeline_failure": True,
            },
            "issues": self.validation_issues,
            "valid": not self.validation_issues,
        }
        validation_path = self.metadata_root / "jp_official_legacy_normalization_validation.json"
        json_dump(validation_path, validation)
        print(json.dumps({"rows": dict(self.stats), "valid": validation["valid"]}, ensure_ascii=False))
        print(metadata_path)
        print(validation_path)
        return 0 if validation["valid"] else 1


def build_parser() -> argparse.ArgumentParser:
    workspace = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=workspace)
    parser.add_argument("--raw-root", type=Path, default=workspace / "data_raw" / "jp_official_legacy")
    parser.add_argument("--output-root", type=Path, default=workspace / "data_processed" / "jp_official_legacy")
    parser.add_argument("--metadata-root", type=Path, default=workspace / "metadata")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    normalizer = Normalizer(args.workspace, args.raw_root, args.output_root, args.metadata_root)
    try:
        return normalizer.run()
    except Exception as exc:
        print(f"normalization failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
