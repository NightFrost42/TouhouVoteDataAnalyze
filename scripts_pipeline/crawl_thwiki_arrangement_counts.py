"""Count THBWiki arrangements per original song without downloading track rows.

The public ``cd.thwiki.cc`` search page is backed by Semantic MediaWiki data on
``thwiki.cc``.  Its per-original result total is equivalent to::

    {{#ask:[[曲目原曲::<original page>]]|format=count}}

Original-song pages also expose a release-date distribution based on ``发售日期``.
This crawler asks the server for exact-date aggregate values, then derives both
half-year totals and Japanese-vote-window totals locally.  It never requests the
matching arrangement titles, album covers, or individual track records.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import requests


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_URL = "https://cd.thwiki.cc/"
API_URL = "https://thwiki.cc/api.php"
OUT_DIR = ROOT / "data_raw" / "thwiki_music"
TOTALS_PATH = OUT_DIR / "original_song_arrangement_counts.csv"
TIMELINE_PATH = OUT_DIR / "original_song_arrangement_counts_half_year.csv"
JP_VOTE_WINDOWS_PATH = (
    OUT_DIR / "original_song_arrangement_counts_jp_vote_windows.csv"
)
CN_VOTE_WINDOWS_PATH = (
    OUT_DIR / "original_song_arrangement_counts_cn_vote_windows.csv"
)
CHECKPOINT_PATH = ROOT / "metadata" / ".thwiki_arrangement_counts_checkpoint.json"
MANIFEST_PATH = ROOT / "metadata" / "thwiki_arrangement_counts_manifest.json"
RUN_STATE_PATH = ROOT / "metadata" / "thwiki_arrangement_counts_queue_status.json"
QUEUE_STAGE_ID = "thwiki_arrangement_counts"
INTERFACE_FAMILY = "THBWiki Semantic MediaWiki 聚合计数接口"
USER_AGENT = (
    "TouhouDataResearch/1.0 "
    "(count-only public Semantic MediaWiki snapshot; no track-detail download)"
)

ORIGINAL_QUERY_FIELDS = (
    "?原曲名称|?原曲译名|?原曲首发作品|?原曲首发日期"
)
COUNT_MARKER = "THWIKI_TOTAL_"
VOCAL_MARKER = "THWIKI_VOCAL_"
RELEASE_DAY_MARKER = "THWIKI_RELEASE_DAY_"
CHECKPOINT_SCHEMA_VERSION = 2
CHART_CONFIG_RE = re.compile(
    r'"jqplot-line-\d+":("(?:\\.|[^"\\])*")'
)

# Voting dates are inclusive and come from the corresponding THBWiki pages.
# Round 1–2 have no music vote and are deliberately absent.
JP_VOTE_WINDOWS: tuple[dict[str, Any], ...] = (
    {"round": 3, "start": "2004-10-17", "end": "2004-10-23", "slug": "第三回"},
    {"round": 4, "start": "2005-12-18", "end": "2005-12-24", "slug": "第四回"},
    {"round": 5, "start": "2008-02-10", "end": "2008-02-16", "slug": "第五回"},
    {"round": 6, "start": "2009-01-18", "end": "2009-01-24", "slug": "第六回"},
    {"round": 7, "start": "2010-02-07", "end": "2010-02-13", "slug": "第七回"},
    {"round": 8, "start": "2011-02-13", "end": "2011-02-19", "slug": "第八回"},
    {"round": 9, "start": "2012-02-19", "end": "2012-02-25", "slug": "第九回"},
    {"round": 10, "start": "2014-02-23", "end": "2014-03-01", "slug": "第十回"},
    {"round": 11, "start": "2015-05-24", "end": "2015-05-31", "slug": "第十一回"},
    {"round": 12, "start": "2016-01-10", "end": "2016-01-16", "slug": "第十二回"},
    {"round": 13, "start": "2017-01-15", "end": "2017-01-21", "slug": "第十三回"},
    {"round": 14, "start": "2018-01-14", "end": "2018-01-20", "slug": "第十四回"},
    {"round": 15, "start": "2019-01-27", "end": "2019-02-02", "slug": "第十五回"},
    {"round": 16, "start": "2020-06-07", "end": "2020-06-13", "slug": "第十六回"},
    {"round": 17, "start": "2021-09-26", "end": "2021-10-03", "slug": "第十七回"},
    {"round": 18, "start": "2022-09-17", "end": "2022-09-24", "slug": "第十八回"},
    {"round": 19, "start": "2023-09-17", "end": "2023-09-30", "slug": "第十九回"},
    {"round": 20, "start": "2024-08-10", "end": "2024-08-23", "slug": "第二十回"},
    {"round": 21, "start": "2025-08-16", "end": "2025-08-29", "slug": "第二十一回"},
    {"round": 22, "start": "2026-08-22", "end": "2026-08-28", "slug": "第二十二回"},
)

# Chinese-region vote windows.  Dates are calendar dates in the published
# result pages/navigation (the modern pages additionally expose exact UTC
# starts).  As with JP, the derived interval for round N is (end(N-1), end(N)]
# and the first round is retained only as a pre-first-end baseline.
CN_VOTE_WINDOWS: tuple[dict[str, Any], ...] = (
    {"round": 1, "start": "2012-07-23", "end": "2012-07-30", "slug": "第一回"},
    {"round": 2, "start": "2013-10-01", "end": "2013-10-07", "slug": "第二回"},
    {"round": 3, "start": "2014-08-22", "end": "2014-08-28", "slug": "第三回"},
    {"round": 4, "start": "2015-10-01", "end": "2015-10-15", "slug": "第四回"},
    {"round": 5, "start": "2016-10-01", "end": "2016-10-16", "slug": "第五回"},
    {"round": 6, "start": "2017-10-01", "end": "2017-10-15", "slug": "第六回"},
    {"round": 7, "start": "2018-09-30", "end": "2018-10-15", "slug": "第七回"},
    {"round": 8, "start": "2019-09-30", "end": "2019-10-15", "slug": "第八回"},
    {"round": 9, "start": "2020-12-18", "end": "2020-12-31", "slug": "第九回"},
    {"round": 10, "start": "2022-06-17", "end": "2022-07-04", "slug": "第十回"},
    {"round": 11, "start": "2023-12-29", "end": "2024-01-15", "slug": "第十一回"},
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv_atomic(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


@dataclass
class AdaptivePacer:
    """Persist one adaptive request interval across the whole crawl."""

    minimum: float = 0.05
    initial: float = 0.25
    maximum: float = 4.0
    speedup_after: int = 4
    slowdown_after: int = 2

    def __post_init__(self) -> None:
        if not 0 <= self.minimum <= self.initial <= self.maximum:
            raise ValueError("require 0 <= minimum <= initial <= maximum")
        self.delay = self.initial
        self.success_streak = 0
        self.failure_streak = 0
        self.total_failures = 0
        self.last_request_at = 0.0

    def wait(self) -> None:
        remaining = self.delay - (time.monotonic() - self.last_request_at)
        if remaining > 0:
            time.sleep(remaining)

    def requested(self) -> None:
        self.last_request_at = time.monotonic()

    def succeeded(self) -> None:
        self.failure_streak = 0
        self.success_streak += 1
        if self.success_streak >= self.speedup_after:
            self.delay = max(self.minimum, self.delay * 0.8)
            self.success_streak = 0

    def failed(self, retry_after: float | None = None) -> None:
        self.success_streak = 0
        self.failure_streak += 1
        self.total_failures += 1
        # One isolated failure does not reduce speed.  Repeated failures first
        # enlarge the cooldown; this count-only crawler has no concurrency tier.
        if self.failure_streak >= self.slowdown_after:
            self.delay = min(self.maximum, max(self.delay * 1.8, retry_after or 0))


class ThwikiClient:
    def __init__(
        self,
        *,
        timeout: float = 90.0,
        max_retries: int = 5,
        pacer: AdaptivePacer | None = None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.pacer = pacer or AdaptivePacer()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8",
            }
        )

    def request_json(
        self,
        data: dict[str, str],
        *,
        method: str = "GET",
    ) -> dict[str, Any]:
        payload = {**data, "format": "json"}
        last_error: BaseException | None = None
        for attempt in range(self.max_retries + 1):
            self.pacer.wait()
            try:
                if method == "POST":
                    response = self.session.post(API_URL, data=payload, timeout=self.timeout)
                else:
                    response = self.session.get(API_URL, params=payload, timeout=self.timeout)
                self.pacer.requested()
                if response.status_code == 429 or response.status_code >= 500:
                    retry_after = parse_retry_after(response.headers.get("Retry-After"))
                    raise RetryableHttpError(response.status_code, retry_after)
                response.raise_for_status()
                result = response.json()
                if "error" in result:
                    raise RuntimeError(f"THBWiki API error: {result['error']!r}")
                self.pacer.succeeded()
                return result
            except (requests.RequestException, ValueError, RetryableHttpError) as exc:
                self.pacer.requested()
                last_error = exc
                retry_after = exc.retry_after if isinstance(exc, RetryableHttpError) else None
                self.pacer.failed(retry_after)
                if attempt >= self.max_retries:
                    break
                backoff = retry_after or min(30.0, (2**attempt) + random.random())
                time.sleep(backoff)
        assert last_error is not None
        raise RuntimeError(
            f"THBWiki request failed after {self.max_retries + 1} attempts"
        ) from last_error


class RetryableHttpError(RuntimeError):
    def __init__(self, status: int, retry_after: float | None) -> None:
        super().__init__(f"retryable HTTP {status}")
        self.retry_after = retry_after


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def printout_text(printouts: dict[str, Any], key: str) -> str:
    values = printouts.get(key) or []
    rendered: list[str] = []
    for value in values:
        if isinstance(value, dict):
            text = value.get("displaytitle") or value.get("fulltext") or value.get("raw")
        else:
            text = value
        if text is not None and str(text).strip():
            rendered.append(str(text).strip())
    return " | ".join(dict.fromkeys(rendered))


def release_date(printouts: dict[str, Any]) -> tuple[str, str]:
    values = printouts.get("原曲首发日期") or []
    dates: list[tuple[float, str, str]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        raw = str(value.get("raw") or "").strip()
        try:
            timestamp = float(value["timestamp"])
            iso = datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
            dates.append((timestamp, iso, raw))
        except (KeyError, TypeError, ValueError, OSError):
            match = re.search(r"(?:^|/)(\d{4})/(\d{1,2})/(\d{1,2})$", raw)
            if match:
                iso = f"{int(match[1]):04d}-{int(match[2]):02d}-{int(match[3]):02d}"
                dates.append((float("inf"), iso, raw))
    if not dates:
        return "", ""
    _, iso, raw = min(dates, key=lambda item: (item[0], item[1]))
    return iso, raw


def parse_original_results(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    results = payload.get("query", {}).get("results", {})
    for page_name, item in results.items():
        printouts = item.get("printouts", {})
        date_iso, date_raw = release_date(printouts)
        rows.append(
            {
                "original_page": page_name,
                "original_name_jp": printout_text(printouts, "原曲名称"),
                "original_name_cn": printout_text(printouts, "原曲译名") or page_name,
                "first_release_work": printout_text(printouts, "原曲首发作品"),
                "first_release_date": date_iso,
                "first_release_date_raw": date_raw,
                "source_page_url": item.get("fullurl", ""),
            }
        )
    return rows


def fetch_originals(client: ThwikiClient, page_size: int = 500) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    offset = 0
    while True:
        query = (
            f"[[原曲名称::+]]|limit={page_size}|offset={offset}|"
            f"{ORIGINAL_QUERY_FIELDS}"
        )
        payload = client.request_json({"action": "ask", "query": query})
        rows.extend(parse_original_results(payload))
        next_offset = payload.get("query-continue-offset")
        if next_offset is None:
            break
        offset = int(next_offset)
    unique = {row["original_page"]: row for row in rows}
    return [unique[key] for key in sorted(unique, key=str.casefold)]


def safe_smw_page_name(value: str) -> str:
    if not value or any(char in value for char in "[]{}|"):
        raise ValueError(f"unsafe Semantic MediaWiki page value: {value!r}")
    return value


def build_count_wikitext(originals: list[dict[str, str]]) -> str:
    parts: list[str] = []
    for index, original in enumerate(originals):
        page = safe_smw_page_name(original["original_page"])
        condition = f"[[曲目原曲::{page}]]"
        parts.append(
            f"{COUNT_MARKER}{index}={{{{#ask:{condition}|format=count}}}}"
        )
        parts.append(
            f"{VOCAL_MARKER}{index}="
            f"{{{{#ask:{condition}[[曲目类型::Vocal]]|format=count}}}}"
        )
        parts.append(
            "{{#ask:"
            + condition
            + "|?发售日期#-F[Y-m-d]"
            + "|format=jqplotchart|limit=10000|link=none|headers=show"
            + "|mainlabel=-|searchlabel=|distribution=1|distributionsort=none"
            + "|direction=vertical|valueformat=%d|charttype=line"
            + "|sort=发售日期|order=asc"
            + f"|charttitle={RELEASE_DAY_MARKER}{index}"
            + "}}"
        )
    return "\n".join(parts)


def decode_chart_configs(head_html: str) -> dict[int, dict[str, Any]]:
    charts: dict[int, dict[str, Any]] = {}
    for encoded in CHART_CONFIG_RE.findall(head_html):
        try:
            config = json.loads(json.loads(encoded))
            title = str(config.get("parameters", {}).get("charttitle", ""))
            if not title.startswith(RELEASE_DAY_MARKER):
                continue
            charts[int(title.removeprefix(RELEASE_DAY_MARKER))] = config
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
    return charts


def aggregate_half_year(
    release_days: Iterable[dict[str, int | str]],
) -> list[dict[str, int | str]]:
    """Derive the old half-year output from exact release-day counts."""

    counts: dict[str, int] = {}
    for row in release_days:
        released = date.fromisoformat(str(row["release_date"]))
        bucket = f"{released.year:04d}H{1 if released.month <= 6 else 2}"
        counts[bucket] = counts.get(bucket, 0) + int(row["arrangement_count"])
    return [
        {"half_year": bucket, "arrangement_count": counts[bucket]}
        for bucket in sorted(counts)
    ]


def vote_calendar_source_url(slug: str, *, region: str = "jp", round_no: int | None = None) -> str:
    """Return the published calendar page for a region's vote window."""
    if str(region).lower() == "cn" and round_no:
        return f"https://touhou.vote/v{int(round_no)}/"
    return f"https://thwiki.cc/东方系列人气投票/{slug}"


def aggregate_vote_windows(
    release_days: Iterable[dict[str, int | str]],
    undated_arrangement_count: int,
    *,
    region: str,
    windows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Assign exact-date aggregate counts to end-to-end vote intervals.

    Round N owns the half-open interval ``(end(N-1), end(N)]``.  This gives
    every dated arrangement exactly one round label while matching the user's
    requested "结束到结束" (vote-end to vote-end) comparison.  The first
    configured round has no lower bound; releases after the last configured
    round are kept in a separate waiting bucket.
    """

    dated_counts = [
        (date.fromisoformat(str(row["release_date"])), int(row["arrangement_count"]))
        for row in release_days
    ]
    output: list[dict[str, Any]] = []
    round_field = f"{region}_vote_round"
    period_field = f"{region}_vote_period_label"
    previous_end: date | None = None
    windows = tuple(windows)
    for vote in windows:
        vote_start = date.fromisoformat(str(vote["start"]))
        vote_end = date.fromisoformat(str(vote["end"]))
        release_start = previous_end
        interval_count = sum(
            count
            for released, count in dated_counts
            if (release_start is None or released > release_start)
            and released <= vote_end
        )
        cumulative_count = sum(
            count for released, count in dated_counts if released <= vote_end
        )
        output.append(
            {
                round_field: int(vote["round"]),
                period_field: f"第{int(vote['round'])}届",
                "vote_window_status": "end_to_end" if release_start else "before_first_vote_end",
                "vote_start_date": vote_start.isoformat(),
                "vote_end_date": vote_end.isoformat(),
                "release_window_start_date": (
                    release_start.isoformat() if release_start else ""
                ),
                "release_window_end_date": vote_end.isoformat(),
                "release_window_start_inclusive": False if release_start else True,
                "release_window_end_inclusive": True,
                "arrangement_count": interval_count,
                "arrangement_cumulative_count": cumulative_count,
                "undated_arrangement_count": undated_arrangement_count,
                "vote_calendar_source_url": vote_calendar_source_url(
                    str(vote["slug"]), region=region, round_no=int(vote["round"])
                ),
            }
        )
        previous_end = vote_end

    assert previous_end is not None
    waiting_start = previous_end + timedelta(days=1)
    waiting_count = sum(
        count for released, count in dated_counts if released >= waiting_start
    )
    output.append(
        {
            round_field: "",
            period_field: "等待下一届",
            "vote_window_status": "waiting_next_vote",
            "vote_start_date": "",
            "vote_end_date": "",
            "release_window_start_date": waiting_start.isoformat(),
            "release_window_end_date": "",
            "arrangement_count": waiting_count,
            "arrangement_cumulative_count": sum(
                count for released, count in dated_counts if released <= previous_end
            ),
            "release_window_start_inclusive": False,
            "release_window_end_inclusive": "",
            "undated_arrangement_count": undated_arrangement_count,
            "vote_calendar_source_url": "",
        }
    )
    return output


def aggregate_jp_vote_windows(
    release_days: Iterable[dict[str, int | str]],
    undated_arrangement_count: int,
) -> list[dict[str, Any]]:
    """Backward-compatible JP wrapper used by existing callers/tests."""
    return aggregate_vote_windows(
        release_days, undated_arrangement_count, region="jp", windows=JP_VOTE_WINDOWS
    )


def aggregate_cn_vote_windows(
    release_days: Iterable[dict[str, int | str]],
    undated_arrangement_count: int,
) -> list[dict[str, Any]]:
    return aggregate_vote_windows(
        release_days, undated_arrangement_count, region="cn", windows=CN_VOTE_WINDOWS
    )


def parse_count_batch(
    payload: dict[str, Any], expected_count: int
) -> list[dict[str, Any]]:
    parsed = payload.get("parse", {})
    rendered_html = parsed.get("text", {}).get("*", "")
    plain = html.unescape(re.sub(r"<[^>]+>", " ", rendered_html))
    totals = {
        int(index): int(value)
        for index, value in re.findall(rf"{COUNT_MARKER}(\d+)\s*=\s*([0-9,]+)", plain)
    }
    vocals = {
        int(index): int(value)
        for index, value in re.findall(rf"{VOCAL_MARKER}(\d+)\s*=\s*([0-9,]+)", plain)
    }
    charts = decode_chart_configs(parsed.get("headhtml", {}).get("*", ""))
    output: list[dict[str, Any]] = []
    for index in range(expected_count):
        if index not in totals or index not in vocals:
            raise ValueError(f"aggregate response is missing count marker {index}")
        daily_counts: dict[str, int] = {}
        for item in (charts.get(index) or {}).get("numbers", []):
            if not isinstance(item, list) or len(item) != 2:
                continue
            release_day, value = str(item[0]), int(item[1])
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", release_day):
                continue
            try:
                date.fromisoformat(release_day)
            except ValueError:
                continue
            if value < 0:
                raise ValueError(
                    f"negative release-day count {value} at marker {index}"
                )
            daily_counts[release_day] = daily_counts.get(release_day, 0) + value
        release_days: list[dict[str, int | str]] = [
            {"release_date": release_day, "arrangement_count": daily_counts[release_day]}
            for release_day in sorted(daily_counts)
        ]
        periods = aggregate_half_year(release_days)
        total = totals[index]
        vocal = vocals[index]
        dated = sum(int(row["arrangement_count"]) for row in release_days)
        if not 0 <= vocal <= total:
            raise ValueError(f"invalid Vocal count {vocal}/{total} at marker {index}")
        if dated > total:
            raise ValueError(f"timeline total {dated} exceeds total {total} at marker {index}")
        output.append(
            {
                "arrangement_count": total,
                "vocal_count": vocal,
                "arrange_count": total - vocal,
                "dated_arrangement_count": dated,
                "undated_arrangement_count": total - dated,
                "timeline_available": bool(periods) or total == 0,
                "periods": periods,
                "release_days": release_days,
                "vote_windows": aggregate_jp_vote_windows(release_days, total - dated),
                "cn_vote_windows": aggregate_cn_vote_windows(release_days, total - dated),
            }
        )
    return output


def fetch_count_batch(
    client: ThwikiClient, originals: list[dict[str, str]]
) -> list[dict[str, Any]]:
    payload = client.request_json(
        {
            "action": "parse",
            "text": build_count_wikitext(originals),
            "contentmodel": "wikitext",
            "prop": "text|headhtml",
        },
        method="POST",
    )
    return parse_count_batch(payload, len(originals))


def originals_fingerprint(originals: list[dict[str, str]]) -> str:
    compact = json.dumps(originals, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(compact.encode("utf-8")).hexdigest()


def load_checkpoint(path: Path, fingerprint: str) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if (
            value.get("schema_version") != CHECKPOINT_SCHEMA_VERSION
            or value.get("originals_sha256") != fingerprint
        ):
            return {}
        records = value.get("records", {})
        return records if isinstance(records, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def load_checkpoint_originals(path: Path) -> list[dict[str, str]]:
    """Reuse the catalog saved with a checkpoint instead of fetching it again."""

    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        originals = value.get("originals")
        expected = value.get("originals_sha256")
        if value.get("schema_version") not in (1, CHECKPOINT_SCHEMA_VERSION) or not isinstance(
            originals, list
        ):
            return []
        if not all(
            isinstance(row, dict) and isinstance(row.get("original_page"), str)
            for row in originals
        ):
            return []
        typed = [dict(row) for row in originals]
        return typed if originals_fingerprint(typed) == expected else []
    except (OSError, ValueError, TypeError):
        return []


def save_checkpoint(
    path: Path,
    fingerprint: str,
    records: dict[str, dict[str, Any]],
    *,
    complete: bool,
    originals: list[dict[str, str]] | None = None,
) -> None:
    value = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "source_frontend_url": FRONTEND_URL,
        "source_api_url": API_URL,
        "originals_sha256": fingerprint,
        "status": "complete" if complete else "running",
        "completed_originals": len(records),
        "updated_at_utc": utc_now(),
        "records": records,
    }
    if originals is not None:
        value["originals"] = originals
    write_json_atomic(path, value)


def refresh_derived_statistics(records: dict[str, dict[str, Any]]) -> None:
    """Rebuild local buckets when a checkpoint is resumed after a rule change."""

    for stats in records.values():
        release_days = stats.get("release_days")
        if not isinstance(release_days, list):
            continue
        dated = sum(int(row["arrangement_count"]) for row in release_days)
        total = int(stats.get("arrangement_count", dated))
        stats["periods"] = aggregate_half_year(release_days)
        stats["dated_arrangement_count"] = dated
        stats["undated_arrangement_count"] = max(0, total - dated)
        stats["timeline_available"] = bool(stats["periods"]) or total == 0
        stats["vote_windows"] = aggregate_jp_vote_windows(release_days, stats["undated_arrangement_count"])
        stats["cn_vote_windows"] = aggregate_cn_vote_windows(release_days, stats["undated_arrangement_count"])


def chunks(values: list[Any], size: int) -> Iterable[list[Any]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def build_content_items(
    originals: list[dict[str, str]],
    records: dict[str, dict[str, Any]],
    batch_size: int,
    *,
    catalog_status: str = "completed",
    current_batch_index: int | None = None,
    failed_batch_index: int | None = None,
) -> list[dict[str, Any]]:
    """Build a stable, explicitly classified work list for the dashboard."""

    rows: list[dict[str, Any]] = [
        {
            "id": "thwiki-original-catalog",
            "label": "原曲目录与首发作品、首发日期",
            "status": catalog_status,
            "current": catalog_status == "current",
        }
    ]
    for batch_index, batch in enumerate(chunks(originals, batch_size), start=1):
        first = (batch_index - 1) * batch_size + 1
        last = first + len(batch) - 1
        completed = sum(row["original_page"] in records for row in batch)
        if completed == len(batch):
            status = "completed"
        elif batch_index == failed_batch_index:
            status = "failed"
        elif batch_index == current_batch_index:
            status = "current"
        else:
            status = "pending"
        rows.append(
            {
                "id": f"thwiki-count-batch-{batch_index:04d}",
                "label": f"同人曲计数、半年与日区结束区间 · 原曲 {first}–{last}",
                "status": status,
                "current": status == "current",
                "completed": completed,
                "total": len(batch),
            }
        )
    return rows


def write_run_status(
    *,
    originals: list[dict[str, str]],
    records: dict[str, dict[str, Any]],
    pacer: AdaptivePacer,
    batch_size: int,
    phase: str,
    activity_label: str,
    catalog_status: str = "completed",
    current_batch_index: int | None = None,
    failed_batch_index: int | None = None,
    current_source_name: str | None = None,
    current_query: str | None = None,
    state: str = "running",
    stopped_reason: str | None = None,
) -> None:
    total = len(originals) if originals else None
    completed = len(records)
    write_json_atomic(
        RUN_STATE_PATH,
        {
            "schemaVersion": 1,
            "queue_stage_id": os.environ.get("DATA_CRAWL_QUEUE_STAGE_ID")
            or QUEUE_STAGE_ID,
            "queue_stage_attempt": os.environ.get("DATA_CRAWL_QUEUE_STAGE_ATTEMPT"),
            "queue_stage_started_at": os.environ.get(
                "DATA_CRAWL_QUEUE_STAGE_STARTED_AT"
            ),
            "pid": os.getpid(),
            "updated_at": utc_now(),
            "state": state,
            "phase": phase,
            "activityLabel": activity_label,
            "interfaceFamily": INTERFACE_FAMILY,
            "completed": completed if total is not None else None,
            "successful": completed if total is not None else None,
            "processed": completed if total is not None else None,
            "total": total,
            "remaining": total - completed if total is not None else None,
            "failed": pacer.total_failures,
            "currentSourceIndex": current_batch_index,
            "currentSourceName": current_source_name,
            "currentQuery": current_query,
            "minimum_seconds_between_request_starts": round(pacer.delay, 6),
            "batch_size": batch_size,
            "batch_pause_seconds": pacer.initial,
            "adaptive_batch_pause_seconds": round(pacer.delay, 6),
            "adaptive_tuning": True,
            "resumable": True,
            "stoppedReason": stopped_reason,
            "contentItems": build_content_items(
                originals,
                records,
                batch_size,
                catalog_status=catalog_status,
                current_batch_index=current_batch_index,
                failed_batch_index=failed_batch_index,
            ),
        },
    )


def emit_outputs(
    originals: list[dict[str, str]], records: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    observed_at = utc_now()
    total_rows: list[dict[str, Any]] = []
    timeline_rows: list[dict[str, Any]] = []
    vote_window_rows: list[dict[str, Any]] = []
    cn_vote_window_rows: list[dict[str, Any]] = []
    excluded_baseline_count = 0
    excluded_waiting_count = 0
    for original in originals:
        stats = records[original["original_page"]]
        base = {
            **original,
            "source_frontend_url": FRONTEND_URL,
            "count_basis": "THBWiki曲目原曲匹配；多原曲混曲会分别计入每个原曲",
            "observed_at_utc": observed_at,
        }
        internal_fields = {"periods", "release_days", "vote_windows", "cn_vote_windows"}
        total_rows.append(
            {**base, **{k: v for k, v in stats.items() if k not in internal_fields}}
        )
        for period in stats.get("periods", []):
            timeline_rows.append(
                {
                    "original_page": original["original_page"],
                    "original_name_jp": original["original_name_jp"],
                    "original_name_cn": original["original_name_cn"],
                    **period,
                    "source_page_url": original["source_page_url"],
                    "observed_at_utc": observed_at,
                }
            )
        for vote_window in stats.get("vote_windows", []):
            status = vote_window.get("vote_window_status")
            if status == "before_first_vote_end":
                excluded_baseline_count += int(vote_window.get("arrangement_count", 0))
                continue
            if status == "waiting_next_vote":
                excluded_waiting_count += int(vote_window.get("arrangement_count", 0))
                continue
            if status != "end_to_end":
                continue
            vote_window_rows.append(
                {
                    "original_page": original["original_page"],
                    "original_name_jp": original["original_name_jp"],
                    "original_name_cn": original["original_name_cn"],
                    **vote_window,
                    "source_page_url": original["source_page_url"],
                    "source_frontend_url": FRONTEND_URL,
                    "observed_at_utc": observed_at,
                }
            )
        for vote_window in stats.get("cn_vote_windows", []):
            status = vote_window.get("vote_window_status")
            if status not in {"end_to_end"}:
                continue
            cn_vote_window_rows.append(
                {
                    "original_page": original["original_page"],
                    "original_name_jp": original["original_name_jp"],
                    "original_name_cn": original["original_name_cn"],
                    **vote_window,
                    "source_page_url": original["source_page_url"],
                    "source_frontend_url": FRONTEND_URL,
                    "observed_at_utc": observed_at,
                }
            )

    total_fields = [
        "original_page",
        "original_name_jp",
        "original_name_cn",
        "first_release_work",
        "first_release_date",
        "first_release_date_raw",
        "arrangement_count",
        "vocal_count",
        "arrange_count",
        "dated_arrangement_count",
        "undated_arrangement_count",
        "timeline_available",
        "source_page_url",
        "source_frontend_url",
        "count_basis",
        "observed_at_utc",
    ]
    timeline_fields = [
        "original_page",
        "original_name_jp",
        "original_name_cn",
        "half_year",
        "arrangement_count",
        "source_page_url",
        "observed_at_utc",
    ]
    vote_window_fields = [
        "original_page",
        "original_name_jp",
        "original_name_cn",
        "jp_vote_round",
        "jp_vote_period_label",
        "vote_window_status",
        "vote_start_date",
        "vote_end_date",
        "release_window_start_date",
        "release_window_end_date",
        "release_window_start_inclusive",
        "release_window_end_inclusive",
        "arrangement_count",
        "arrangement_cumulative_count",
        "undated_arrangement_count",
        "source_page_url",
        "source_frontend_url",
        "vote_calendar_source_url",
        "observed_at_utc",
    ]
    write_csv_atomic(TOTALS_PATH, total_rows, total_fields)
    write_csv_atomic(TIMELINE_PATH, timeline_rows, timeline_fields)
    write_csv_atomic(JP_VOTE_WINDOWS_PATH, vote_window_rows, vote_window_fields)
    cn_vote_window_fields = [field.replace("jp_vote_", "cn_vote_") if field.startswith("jp_vote_") else field for field in vote_window_fields]
    write_csv_atomic(CN_VOTE_WINDOWS_PATH, cn_vote_window_rows, cn_vote_window_fields)

    release_dates = [row["first_release_date"] for row in total_rows if row["first_release_date"]]
    manifest = {
        "schema_version": 2,
        "status": "complete",
        "source_frontend_url": FRONTEND_URL,
        "source_api_url": API_URL,
        "method": "Semantic MediaWiki exact release-date aggregate counts only; no arrangement rows downloaded",
        "count_basis": "one match per arrangement track using the original; multi-original tracks count for each original",
        "date_aggregation": "exact arrangement 发售日期 (YYYY-MM-DD), retained only as aggregate counts in the checkpoint",
        "timeline_bucket": "calendar half-year derived locally from exact-date aggregates (YYYYH1/YYYYH2)",
        "jp_vote_window_rule": "only true end-to-end interval counts are emitted: round N (N=4..22) owns (end of round N-1, end of round N]; all boundaries use previous-end exclusive/current-end inclusive. Each row also carries arrangement_cumulative_count for all dated releases on or before that vote end.",
        "jp_vote_round_3_lower_bound": "releases on or before 2004-10-23 are retained only as an internal pre-first-end baseline and are excluded from the interval CSV",
        "cn_vote_window_rule": "only true end-to-end interval counts are emitted: round N (N=2..11) owns (end of round N-1, end of round N]; CN1 is retained only as an internal pre-first-end baseline and is excluded from the interval CSV. Each row also carries arrangement_cumulative_count for all dated releases on or before that vote end.",
        "cn_vote_round_1_lower_bound": "releases on or before 2012-07-30 are retained only as an internal pre-first-end baseline and are excluded from the interval CSV",
        "post_round_22_rule": "releases after 2026-08-28 are retained only as an internal waiting_next_vote bucket and are excluded from the interval CSV",
        "jp_vote_calendar": [
            {
                "round": vote["round"],
                "start": vote["start"],
                "end": vote["end"],
                "source_url": vote_calendar_source_url(
                    str(vote["slug"]), region="jp", round_no=int(vote["round"])
                ),
            }
            for vote in JP_VOTE_WINDOWS
        ],
        "cn_vote_calendar": [
            {
                "round": vote["round"],
                "start": vote["start"],
                "end": vote["end"],
                "source_url": vote_calendar_source_url(
                    str(vote["slug"]), region="cn", round_no=int(vote["round"])
                ),
            }
            for vote in CN_VOTE_WINDOWS
        ],
        "observed_at_utc": observed_at,
        "original_song_count": len(total_rows),
        "timeline_row_count": len(timeline_rows),
        "jp_vote_window_row_count": len(vote_window_rows),
        "cn_vote_window_row_count": len(cn_vote_window_rows),
        "missing_original_release_date_count": sum(
            not row["first_release_date"] for row in total_rows
        ),
        "originals_without_dated_arrangements_count": sum(
            not row["timeline_available"] for row in total_rows
        ),
        "sum_per_original_arrangement_counts": sum(
            int(row["arrangement_count"]) for row in total_rows
        ),
        "sum_note": "not a distinct-track total because a multi-original track is counted under every original",
        "earliest_original_release_date": min(release_dates) if release_dates else "",
        "latest_original_release_date": max(release_dates) if release_dates else "",
        "arrangements_after_latest_vote_count": excluded_waiting_count,
        "arrangements_before_first_vote_end_count": excluded_baseline_count,
        "outputs": {
            "totals_csv": str(TOTALS_PATH.relative_to(ROOT)).replace("\\", "/"),
            "half_year_csv": str(TIMELINE_PATH.relative_to(ROOT)).replace("\\", "/"),
            "jp_vote_windows_csv": str(JP_VOTE_WINDOWS_PATH.relative_to(ROOT)).replace(
                "\\", "/"
            ),
            "cn_vote_windows_csv": str(CN_VOTE_WINDOWS_PATH.relative_to(ROOT)).replace(
                "\\", "/"
            ),
        },
    }
    write_json_atomic(MANIFEST_PATH, manifest)
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--min-delay", type=float, default=0.05)
    parser.add_argument("--initial-delay", type=float, default=0.25)
    parser.add_argument("--max-delay", type=float, default=4.0)
    parser.add_argument("--refresh", action="store_true", help="ignore a matching checkpoint")
    parser.add_argument(
        "--max-batches",
        type=int,
        help="stop after this many new batches while retaining the checkpoint",
    )
    args = parser.parse_args(argv)
    if args.batch_size < 1 or args.batch_size > 25:
        parser.error("--batch-size must be between 1 and 25")
    if args.max_retries < 0:
        parser.error("--max-retries must be non-negative")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    pacer = AdaptivePacer(
        minimum=args.min_delay,
        initial=args.initial_delay,
        maximum=args.max_delay,
    )
    client = ThwikiClient(timeout=args.timeout, max_retries=args.max_retries, pacer=pacer)
    originals: list[dict[str, str]] = []
    records: dict[str, dict[str, Any]] = {}
    current_batch_index: int | None = None
    try:
        originals = [] if args.refresh else load_checkpoint_originals(CHECKPOINT_PATH)
        if not originals:
            write_run_status(
                originals=[],
                records={},
                pacer=pacer,
                batch_size=args.batch_size,
                phase="original_catalog",
                activity_label="抓取原曲目录与首发时间",
                catalog_status="current",
                current_query="原曲名称、译名、首发作品、首发日期",
            )
            originals = fetch_originals(client)

        fingerprint = originals_fingerprint(originals)
        records = {} if args.refresh else load_checkpoint(CHECKPOINT_PATH, fingerprint)
        refresh_derived_statistics(records)
        save_checkpoint(
            CHECKPOINT_PATH,
            fingerprint,
            records,
            complete=len(records) == len(originals),
            originals=originals,
        )
        all_batches = list(chunks(originals, args.batch_size))
        pending_count = len(originals) - len(records)
        print(
            f"THBWiki originals={len(originals)}; resumed={len(records)}; "
            f"pending={pending_count}; count-only batches={len(all_batches)}"
        )

        executed_batches = 0
        for batch_index, full_batch in enumerate(all_batches, start=1):
            batch = [
                row
                for row in full_batch
                if row["original_page"] not in records
            ]
            if not batch:
                continue
            if args.max_batches is not None and executed_batches >= args.max_batches:
                break
            current_batch_index = batch_index
            first = (batch_index - 1) * args.batch_size + 1
            last = first + len(full_batch) - 1
            source_name = f"原曲 {first}–{last}"
            write_run_status(
                originals=originals,
                records=records,
                pacer=pacer,
                batch_size=args.batch_size,
                phase="count_batches",
                activity_label=f"统计{source_name}的同人曲数量与精确发售日",
                current_batch_index=batch_index,
                current_source_name=source_name,
                current_query="曲目原曲计数、Vocal 计数、发售日期精确日与日区结束区间聚合",
            )
            stats = fetch_count_batch(client, batch)
            for original, values in zip(batch, stats, strict=True):
                records[original["original_page"]] = values
            executed_batches += 1
            complete = len(records) == len(originals)
            save_checkpoint(
                CHECKPOINT_PATH,
                fingerprint,
                records,
                complete=complete,
                originals=originals,
            )
            write_run_status(
                originals=originals,
                records=records,
                pacer=pacer,
                batch_size=args.batch_size,
                phase="count_batches",
                activity_label=f"已完成{source_name}，准备下一批",
            )
            print(
                f"[batch {batch_index}/{len(all_batches)}] "
                f"completed={len(records)}/{len(originals)} "
                f"delay={client.pacer.delay:.3f}s",
                flush=True,
            )

        if len(records) != len(originals):
            write_run_status(
                originals=originals,
                records=records,
                pacer=pacer,
                batch_size=args.batch_size,
                phase="checkpoint_saved",
                activity_label="已保存断点，可从未完成批次继续",
                state="paused",
            )
            print(
                f"checkpoint retained: {len(records)}/{len(originals)} originals complete",
                file=sys.stderr,
            )
            return 2

        write_run_status(
            originals=originals,
            records=records,
            pacer=pacer,
            batch_size=args.batch_size,
            phase="writing_outputs",
            activity_label="写入原曲总表、半年统计与日区结束区间表",
        )
        manifest = emit_outputs(originals, records)
        save_checkpoint(
            CHECKPOINT_PATH,
            fingerprint,
            records,
            complete=True,
            originals=originals,
        )
        write_run_status(
            originals=originals,
            records=records,
            pacer=pacer,
            batch_size=args.batch_size,
            phase="finished",
            activity_label="THBWiki 原曲同人曲计数、半年与日区结束区间已完成",
            state="complete",
        )
        print(
            f"complete: originals={manifest['original_song_count']}; "
            f"half-year rows={manifest['timeline_row_count']}; "
            f"vote-window rows={manifest['jp_vote_window_row_count']}; "
            f"missing release dates={manifest['missing_original_release_date_count']}"
        )
        print(TOTALS_PATH)
        print(TIMELINE_PATH)
        print(JP_VOTE_WINDOWS_PATH)
        print(CN_VOTE_WINDOWS_PATH)
        return 0
    except BaseException as exc:
        write_run_status(
            originals=originals,
            records=records,
            pacer=pacer,
            batch_size=args.batch_size,
            phase="failed",
            activity_label="THBWiki 聚合计数请求失败，断点已保留",
            failed_batch_index=current_batch_index,
            state="failed",
            stopped_reason=str(exc),
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
