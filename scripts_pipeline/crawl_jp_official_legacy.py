#!/usr/bin/env python3
"""Reproducibly crawl official Touhou popularity-poll results, rounds 3--16.

The crawler deliberately keeps full HTML only for index/list/questionnaire/
aggregate pages.  Detail pages are represented by a small source envelope,
their summary lines, and every numeric table that appears before the
"投票コメント" section.  Free-text voter comments are never written.

Only Python's standard library and lxml are required.  The command is safe to
resume: full HTML and parsed detail JSON files are reused unless --refresh is
specified.  Network concurrency is capped at eight workers.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from lxml import html


PARSER_VERSION = "jp-official-legacy-v3"
USER_AGENT = (
    "Mozilla/5.0 (compatible; TouhouVoteResearch/1.0; "
    "+https://toho-vote.info/)"
)
MAX_WORKERS = 8

OLD_BASE = "http://thwiki.info/th/vote{round_no}/"
NEW_BASE = "https://toho-vote.info/result{round_no}/"

SPACE_RE = re.compile(r"[\s\u3000]+")
CHARSET_RE = re.compile(br"charset\s*=\s*[\"']?([A-Za-z0-9._-]+)", re.I)
NUMBER_RE = re.compile(
    r"(?<![\w.])(?P<number>[+＋\-−]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|"
    r"[+＋\-−]?\d+(?:\.\d+)?)\s*"
    r"(?P<unit>%|％|pt|点|票|件|人|名|位|歳|回)?",
    re.I,
)
# Historical pages use several variants, including 投票コメント,
# 一押しコメント, and simply 部門コメント.
COMMENT_HEADING = "コメント"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return SPACE_RE.sub(" ", value.replace("\r", " ").replace("\x00", " ")).strip()


def element_text(node: Any) -> str:
    return clean_text(" ".join(node.itertext()))


def json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}-{threading.get_ident()}")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=False)
        handle.write("\n")
    os.replace(tmp, path)


def bytes_dump(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}-{threading.get_ident()}")
    with tmp.open("wb") as handle:
        handle.write(value)
    os.replace(tmp, path)


def relpath(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    return path.resolve().relative_to(root.resolve()).as_posix()


def source_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def url_hash(url: str, length: int = 14) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:length]


def normalize_url(url: str) -> str:
    """Strip fragments/control characters and quote non-ASCII URL bytes."""
    url = "".join(ch for ch in url.strip() if ord(ch) >= 0x20)
    url, _fragment = urllib.parse.urldefrag(url)
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parts.path, safe="/%:@!$&'()*+,;=-._~")
    query = urllib.parse.quote(parts.query, safe="=&;%:+,/?@!$'()*-._~")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, ""))


def canonical_discovery_url(url: str) -> str:
    """Normalize URL spelling without decoding meaningful query text."""
    parts = urllib.parse.urlsplit(normalize_url(url))
    # The old server treats a trailing slash as the canonical index.
    path = re.sub(r"/{2,}", "/", parts.path)
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def detect_charset(payload: bytes, header_charset: str | None = None) -> str:
    candidates: list[str] = []
    if header_charset:
        candidates.append(header_charset)
    match = CHARSET_RE.search(payload[:8192])
    if match:
        candidates.append(match.group(1).decode("ascii", "ignore"))
    candidates.extend(["utf-8", "cp932", "euc_jp"])
    aliases = {
        "shift_jis": "cp932",
        "shift-jis": "cp932",
        "sjis": "cp932",
        "x-sjis": "cp932",
        "euc-jp": "euc_jp",
    }
    seen: set[str] = set()
    for candidate in candidates:
        encoding = aliases.get(candidate.lower(), candidate)
        if encoding.lower() in seen:
            continue
        seen.add(encoding.lower())
        try:
            payload.decode(encoding, "strict")
            return encoding
        except (LookupError, UnicodeDecodeError):
            continue
    return "utf-8"


def parse_number_tokens(text: str) -> list[dict[str, Any]]:
    tokens: list[dict[str, Any]] = []
    for match in NUMBER_RE.finditer(text):
        raw_number = match.group("number")
        normalized = (
            raw_number.replace(",", "")
            .replace("＋", "+")
            .replace("−", "-")
        )
        try:
            number: int | float
            number = float(normalized) if "." in normalized else int(normalized)
        except ValueError:
            continue
        raw_unit = match.group("unit") or ""
        unit = "%" if raw_unit == "％" else raw_unit.lower()
        kind = "percentage" if unit == "%" else "number"
        tokens.append(
            {
                "raw": match.group(0).strip(),
                "value": number,
                "unit": unit or None,
                "kind": kind,
            }
        )
    return tokens


def parse_document(payload: bytes, charset: str, url: str) -> Any:
    decoded = payload.decode(charset, "replace")
    try:
        return html.fromstring(decoded, base_url=url)
    except Exception:
        return html.fromstring("<html><body></body></html>", base_url=url)


def discover_links(tree: Any, base_url: str) -> list[tuple[str, str]]:
    links: dict[str, str] = {}
    for anchor in tree.xpath("//a[@href]"):
        href = anchor.get("href") or ""
        href = clean_text(href)
        if not href or href.startswith(("javascript:", "mailto:")):
            continue
        try:
            resolved = canonical_discovery_url(urllib.parse.urljoin(base_url, href))
        except Exception:
            continue
        label = element_text(anchor)
        links.setdefault(resolved, label)
    return sorted(links.items())


def heading_before(table: Any) -> str:
    headings = table.xpath("preceding::h1 | preceding::h2 | preceding::h3 | preceding::h4 | preceding::h5 | preceding::h6")
    return element_text(headings[-1]) if headings else ""


def tables_before_comments(tree: Any) -> list[dict[str, Any]]:
    """Extract numeric tables while excluding everything after comment Hx."""
    result: list[dict[str, Any]] = []
    for source_index, table in enumerate(tree.xpath("//table")):
        # lxml can create more than one Python proxy for the same libxml node,
        # so comparing object ids from separate XPath calls is unsafe.  Ask
        # libxml directly whether a comment heading precedes this table.
        preceding_headings = table.xpath(
            "preceding::h1 | preceding::h2 | preceding::h3 | "
            "preceding::h4 | preceding::h5 | preceding::h6"
        )
        if any(COMMENT_HEADING in element_text(node) for node in preceding_headings):
            continue
        rows: list[dict[str, Any]] = []
        any_number = False
        for row_index, row in enumerate(table.xpath(".//tr")):
            ancestors = row.xpath("ancestor::table[1]")
            if not ancestors or ancestors[0] is not table:
                continue
            cell_nodes = row.xpath("./th | ./td")
            if not cell_nodes:
                continue
            cells: list[dict[str, Any]] = []
            for cell in cell_nodes:
                text = element_text(cell)
                numbers = parse_number_tokens(text)
                any_number = any_number or bool(numbers)
                cells.append(
                    {
                        "text": text,
                        "is_header": cell.tag.lower() == "th",
                        "rowspan": int(cell.get("rowspan", "1")) if (cell.get("rowspan", "1").isdigit()) else 1,
                        "colspan": int(cell.get("colspan", "1")) if (cell.get("colspan", "1").isdigit()) else 1,
                        "numbers": numbers,
                    }
                )
            rows.append({"row_index": row_index, "cells": cells})
        if any_number and rows:
            result.append(
                {
                    "table_index": source_index,
                    "context_heading": heading_before(table),
                    "rows": rows,
                }
            )
    return result


def detail_summary(tree: Any) -> list[dict[str, Any]]:
    """Extract short structural summaries, never free-text comment bodies."""
    values: list[tuple[str, str]] = []
    title = clean_text(tree.xpath("string(//title)"))
    if title:
        values.append(("title", title))

    # Old comment-only pages put one numeric item header per title_com cell.
    title_cells = tree.xpath(
        "//*[contains(concat(' ', normalize-space(@class), ' '), ' title_com ')]"
    )
    for node in title_cells:
        text = element_text(node)
        if text:
            values.append(("item_header", text))

    article = tree.xpath("//article")
    scope = article[0] if article else tree
    h2_nodes = scope.xpath(".//h2")
    if h2_nodes:
        item_heading = element_text(h2_nodes[0])
        if item_heading:
            values.append(("item_heading", item_heading))
        # Official detail pages keep points/votes/continuation rate in the
        # first paragraph following the item H2, before any comment section.
        paragraphs = h2_nodes[0].xpath("following::p[1]")
        if paragraphs:
            summary = element_text(paragraphs[0])
            if summary and len(summary) <= 2000:
                values.append(("item_statistics", summary))

    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for kind, text in values:
        key = (kind, text)
        if key in seen:
            continue
        seen.add(key)
        result.append({"kind": kind, "text": text, "numbers": parse_number_tokens(text)})
    return result


def table_row_count(tables: list[dict[str, Any]]) -> int:
    return sum(len(table["rows"]) for table in tables)


@dataclass(frozen=True)
class PageSpec:
    round_no: int
    url: str
    role: str
    category: str | None = None
    item_id: str | None = None
    discovery_label: str = ""


@dataclass
class PageResult:
    spec: PageSpec
    manifest: dict[str, Any]
    links: list[tuple[str, str]] = field(default_factory=list)
    parsed: dict[str, Any] | None = None


class HttpClient:
    def __init__(self, refresh: bool, timeout: float, retries: int) -> None:
        self.refresh = refresh
        self.timeout = timeout
        self.retries = retries

    def fetch(self, url: str) -> tuple[bytes, int, str, str | None, str]:
        quoted = normalize_url(url)
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            request = urllib.request.Request(
                quoted,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
                    "Connection": "close",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = response.read()
                    charset = response.headers.get_content_charset()
                    return payload, int(response.status), response.geturl(), charset, utc_now()
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                time.sleep(min(8.0, 0.5 * (2**attempt)))
        assert last_error is not None
        raise last_error


class LegacyCrawler:
    def __init__(
        self,
        workspace: Path,
        data_dir: Path,
        metadata_dir: Path,
        workers: int,
        refresh: bool,
        timeout: float,
        retries: int,
        limit_details: int | None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.data_dir = data_dir.resolve()
        self.metadata_dir = metadata_dir.resolve()
        self.workers = max(1, min(workers, MAX_WORKERS))
        self.client = HttpClient(refresh=refresh, timeout=timeout, retries=retries)
        self.refresh = refresh
        self.limit_details = limit_details
        self.results: list[PageResult] = []
        self.discovered_detail_urls: dict[int, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    def round_dir(self, round_no: int) -> Path:
        return self.data_dir / f"round_{round_no:02d}"

    @staticmethod
    def raw_filename(spec: PageSpec) -> str:
        parts = urllib.parse.urlsplit(spec.url)
        name = "index.html" if parts.path.endswith("/") else (Path(parts.path).name or "index.html")
        if name.lower().endswith(".php"):
            name += ".html"
        if parts.query:
            name = f"{name}__{url_hash(parts.query, 10)}"
        return re.sub(r"[^A-Za-z0-9._-]+", "_", name)

    def raw_paths(self, spec: PageSpec) -> tuple[Path, Path]:
        folder = "lists" if spec.role == "list" else "aggregate"
        if spec.role == "questionnaire":
            folder = "questionnaire"
        raw = self.round_dir(spec.round_no) / folder / self.raw_filename(spec)
        parsed = raw.with_name(raw.name + ".tables.json")
        return raw, parsed

    def detail_path(self, spec: PageSpec) -> Path:
        category = spec.category or "other"
        item_id = spec.item_id or url_hash(spec.url)
        safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", item_id).strip("._")
        if not safe_id:
            safe_id = url_hash(spec.url)
        return self.round_dir(spec.round_no) / "details" / category / f"{safe_id}.json"

    def _load_or_fetch_raw(self, spec: PageSpec) -> tuple[bytes, int, str, str | None, str, bool]:
        raw_path, parsed_path = self.raw_paths(spec)
        if raw_path.exists() and not self.refresh:
            metadata: dict[str, Any] = {}
            if parsed_path.exists():
                try:
                    metadata = json.loads(parsed_path.read_text(encoding="utf-8")).get("source", {})
                except (OSError, json.JSONDecodeError):
                    metadata = {}
            payload = raw_path.read_bytes()
            retrieved = metadata.get("retrieved_at") or datetime.fromtimestamp(
                raw_path.stat().st_mtime, tz=timezone.utc
            ).isoformat(timespec="seconds")
            return payload, 200, metadata.get("effective_url", spec.url), metadata.get("header_charset"), retrieved, True
        payload, status, effective, header_charset, retrieved = self.client.fetch(spec.url)
        bytes_dump(raw_path, payload)
        return payload, status, effective, header_charset, retrieved, False

    def process_full_page(self, spec: PageSpec) -> PageResult:
        raw_path, parsed_path = self.raw_paths(spec)
        try:
            payload, status, effective, header_charset, retrieved, cached = self._load_or_fetch_raw(spec)
            charset = detect_charset(payload, header_charset)
            tree = parse_document(payload, charset, spec.url)
            tables = tables_before_comments(tree)
            parsed = {
                "parser_version": PARSER_VERSION,
                "source": {
                    "url": spec.url,
                    "effective_url": effective,
                    "retrieved_at": retrieved,
                    "http_status": status,
                    "bytes": len(payload),
                    "sha256": source_hash(payload),
                    "charset": charset,
                    "header_charset": header_charset,
                },
                "round": spec.round_no,
                "role": spec.role,
                "category": spec.category,
                "title": clean_text(tree.xpath("string(//title)")),
                "numeric_tables": tables,
            }
            json_dump(parsed_path, parsed)
            links = discover_links(tree, spec.url)
            manifest = {
                "round": spec.round_no,
                "url": spec.url,
                "effective_url": effective,
                "role": spec.role,
                "category": spec.category,
                "item_id": spec.item_id,
                "status": "ok",
                "http_status": status,
                "source_bytes": len(payload),
                "sha256": source_hash(payload),
                "charset": charset,
                "retrieved_at": retrieved,
                "cached": cached,
                "raw_html_path": relpath(raw_path, self.workspace),
                "parsed_json_path": relpath(parsed_path, self.workspace),
                "numeric_table_count": len(tables),
                "numeric_row_count": table_row_count(tables),
                "summary_line_count": 0,
                "error": None,
            }
            return PageResult(spec=spec, manifest=manifest, links=links)
        except Exception as exc:
            return self.error_result(spec, exc)

    def process_detail(self, spec: PageSpec) -> PageResult:
        output = self.detail_path(spec)
        if output.exists() and not self.refresh:
            try:
                parsed = json.loads(output.read_text(encoding="utf-8"))
                source = parsed["source"]
                if source.get("url") == spec.url and parsed.get("parser_version") == PARSER_VERSION:
                    tables = parsed.get("numeric_tables", [])
                    summary = parsed.get("summary", [])
                    manifest = {
                        "round": spec.round_no,
                        "url": spec.url,
                        "effective_url": source.get("effective_url", spec.url),
                        "role": spec.role,
                        "category": spec.category,
                        "item_id": spec.item_id,
                        "status": "ok",
                        "http_status": source.get("http_status", 200),
                        "source_bytes": source["bytes"],
                        "sha256": source["sha256"],
                        "charset": source.get("charset"),
                        "retrieved_at": source.get("retrieved_at"),
                        "cached": True,
                        "raw_html_path": None,
                        "parsed_json_path": relpath(output, self.workspace),
                        "numeric_table_count": len(tables),
                        "numeric_row_count": table_row_count(tables),
                        "summary_line_count": len(summary),
                        "error": None,
                    }
                    return PageResult(spec=spec, manifest=manifest)
            except (OSError, KeyError, TypeError, json.JSONDecodeError):
                pass
        try:
            payload, status, effective, header_charset, retrieved = self.client.fetch(spec.url)
            charset = detect_charset(payload, header_charset)
            tree = parse_document(payload, charset, spec.url)
            tables = tables_before_comments(tree)
            summary = detail_summary(tree)
            parsed = {
                "parser_version": PARSER_VERSION,
                "source": {
                    "url": spec.url,
                    "effective_url": effective,
                    "retrieved_at": retrieved,
                    "http_status": status,
                    "bytes": len(payload),
                    "sha256": source_hash(payload),
                    "charset": charset,
                    "header_charset": header_charset,
                },
                "round": spec.round_no,
                "role": spec.role,
                "category": spec.category,
                "item_id": spec.item_id,
                "discovery_label": spec.discovery_label,
                "summary": summary,
                "numeric_tables": tables,
                "omitted": ["free_text_vote_comments"],
            }
            json_dump(output, parsed)
            manifest = {
                "round": spec.round_no,
                "url": spec.url,
                "effective_url": effective,
                "role": spec.role,
                "category": spec.category,
                "item_id": spec.item_id,
                "status": "ok",
                "http_status": status,
                "source_bytes": len(payload),
                "sha256": source_hash(payload),
                "charset": charset,
                "retrieved_at": retrieved,
                "cached": False,
                "raw_html_path": None,
                "parsed_json_path": relpath(output, self.workspace),
                "numeric_table_count": len(tables),
                "numeric_row_count": table_row_count(tables),
                "summary_line_count": len(summary),
                "error": None,
            }
            # Links are needed only while traversing old result*.html pages;
            # they are discarded after discovery and never written as comments.
            links = discover_links(tree, spec.url) if spec.round_no <= 10 else []
            return PageResult(spec=spec, manifest=manifest, links=links)
        except Exception as exc:
            return self.error_result(spec, exc)

    @staticmethod
    def error_result(spec: PageSpec, exc: Exception) -> PageResult:
        manifest = {
            "round": spec.round_no,
            "url": spec.url,
            "effective_url": None,
            "role": spec.role,
            "category": spec.category,
            "item_id": spec.item_id,
            "status": "error",
            "http_status": getattr(exc, "code", None),
            "source_bytes": None,
            "sha256": None,
            "charset": None,
            "retrieved_at": None,
            "cached": False,
            "raw_html_path": None,
            "parsed_json_path": None,
            "numeric_table_count": 0,
            "numeric_row_count": 0,
            "summary_line_count": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }
        return PageResult(spec=spec, manifest=manifest)

    @staticmethod
    def old_category(url: str) -> str:
        name = Path(urllib.parse.urlsplit(url).path).name.lower()
        for token, category in (
            ("char", "character"),
            ("music", "music"),
            ("spell", "spell"),
            ("anq", "questionnaire"),
            ("etc", "other"),
        ):
            if token in name:
                return category
        if name == "show.php":
            return "questionnaire_comment"
        return "other"

    @staticmethod
    def old_page_spec(round_no: int, url: str, label: str = "") -> PageSpec:
        parts = urllib.parse.urlsplit(url)
        name = Path(parts.path).name.lower()
        category = LegacyCrawler.old_category(url)
        is_comment_detail = name == "show.php" or bool(
            re.match(r"^result_(?:char|music|spell|anq)2[a-z]*\.html$", name)
        )
        if is_comment_detail:
            if name == "show.php":
                item_id = "show_" + re.sub(r"[^A-Za-z0-9_-]+", "_", parts.query)
            else:
                item_id = Path(name).stem
            return PageSpec(round_no, url, "detail", category, item_id, label)
        role = "questionnaire" if name == "result_anq.html" else "aggregate"
        return PageSpec(round_no, url, role, category, Path(name).stem or "index", label)

    @staticmethod
    def is_old_result_link(round_no: int, url: str) -> bool:
        parts = urllib.parse.urlsplit(url)
        expected_prefix = f"/th/vote{round_no}/"
        if parts.netloc.lower() != "thwiki.info" or not parts.path.startswith(expected_prefix):
            return False
        name = Path(parts.path).name.lower()
        return bool(re.match(r"^result.*\.html$", name) or name == "show.php")

    def run_old_round(self, round_no: int) -> None:
        base = OLD_BASE.format(round_no=round_no)
        index_spec = PageSpec(round_no, base, "index", None, "index")
        index_result = self.process_full_page(index_spec)
        self.results.append(index_result)
        if index_result.manifest["status"] != "ok":
            return

        queue: deque[PageSpec] = deque()
        seen = {canonical_discovery_url(base)}
        for url, label in index_result.links:
            if self.is_old_result_link(round_no, url) and url not in seen:
                seen.add(url)
                queue.append(self.old_page_spec(round_no, url, label))
        # result_anq.html is part of every requested round even if an archived
        # index happens not to expose the link.
        explicit_anq = canonical_discovery_url(urllib.parse.urljoin(base, "result_anq.html"))
        if explicit_anq not in seen:
            seen.add(explicit_anq)
            queue.append(self.old_page_spec(round_no, explicit_anq))

        while queue:
            frontier = list(queue)
            queue.clear()
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                futures = {
                    pool.submit(
                        self.process_detail if spec.role == "detail" else self.process_full_page,
                        spec,
                    ): spec
                    for spec in frontier
                }
                for future in as_completed(futures):
                    result = future.result()
                    self.results.append(result)
                    if result.spec.role == "detail":
                        self.discovered_detail_urls[round_no][result.spec.category or "other"].add(result.spec.url)
                    for url, label in result.links:
                        if self.is_old_result_link(round_no, url) and url not in seen:
                            seen.add(url)
                            queue.append(self.old_page_spec(round_no, url, label))

    @staticmethod
    def list_specs(round_no: int) -> list[PageSpec]:
        base = OLD_BASE.format(round_no=round_no) if round_no <= 12 else NEW_BASE.format(round_no=round_no)
        if round_no == 11:
            names = [
                ("result_list_character.php", "character"),
                ("result_list_music.php", "music"),
            ]
            questionnaire = "result_questionnaire.php"
        else:
            names = [
                ("result_list_character.php", "character"),
                ("result_list_music.php", "music"),
                ("result_list_title.php", "work"),
            ]
            if round_no == 13:
                names.append(("result_list_partner.php", "partner"))
            questionnaire = "result_list_questionnaire.php"
        specs = [PageSpec(round_no, base, "index", None, "index")]
        specs.extend(
            PageSpec(round_no, canonical_discovery_url(urllib.parse.urljoin(base, name)), "list", category, name)
            for name, category in names
        )
        specs.append(
            PageSpec(
                round_no,
                canonical_discovery_url(urllib.parse.urljoin(base, questionnaire)),
                "questionnaire",
                "questionnaire",
                questionnaire,
            )
        )
        return specs

    @staticmethod
    def detail_from_link(round_no: int, url: str, label: str) -> PageSpec | None:
        parts = urllib.parse.urlsplit(url)
        path = parts.path
        if round_no == 11:
            if not path.endswith("/vote11/result_details.php"):
                return None
            query = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
            category = (query.get("class") or [""])[0]
            if category not in {"character", "music"}:
                return None
            item_name = (query.get("name") or query.get("sname") or [label])[0]
            item_id = f"{url_hash(url)}"
            return PageSpec(round_no, url, "detail", category, item_id, clean_text(item_name or label))

        if round_no == 12:
            match = re.search(r"/vote12/result/(character|music|title)/([^/]+)\.php$", path)
        else:
            match = re.search(rf"/result{round_no}/(character|music|title|partner)/([^/]+)\.php$", path)
        if not match:
            return None
        source_category, item_id = match.groups()
        category = "work" if source_category == "title" else source_category
        return PageSpec(round_no, url, "detail", category, item_id, label)

    def run_structured_round(self, round_no: int) -> None:
        seed_specs = self.list_specs(round_no)
        seed_results: list[PageResult] = []
        with ThreadPoolExecutor(max_workers=min(self.workers, len(seed_specs))) as pool:
            futures = {pool.submit(self.process_full_page, spec): spec for spec in seed_specs}
            for future in as_completed(futures):
                result = future.result()
                self.results.append(result)
                seed_results.append(result)

        details_by_url: dict[str, PageSpec] = {}
        for result in seed_results:
            if result.spec.role != "list" or result.manifest["status"] != "ok":
                continue
            for url, label in result.links:
                spec = self.detail_from_link(round_no, url, label)
                if spec:
                    details_by_url.setdefault(spec.url, spec)
                    self.discovered_detail_urls[round_no][spec.category or "other"].add(spec.url)
        details = [details_by_url[url] for url in sorted(details_by_url)]
        if self.limit_details is not None:
            details = details[: self.limit_details]

        completed = 0
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(self.process_detail, spec): spec for spec in details}
            for future in as_completed(futures):
                result = future.result()
                self.results.append(result)
                completed += 1
                if completed % 100 == 0 or completed == len(details):
                    print(f"  round {round_no}: {completed}/{len(details)} detail pages", flush=True)

    def run(self, rounds: Iterable[int]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        for round_no in rounds:
            print(f"round {round_no}: crawl started", flush=True)
            before = len(self.results)
            if round_no <= 10:
                self.run_old_round(round_no)
            else:
                self.run_structured_round(round_no)
            current = self.results[before:]
            errors = sum(result.manifest["status"] != "ok" for result in current)
            print(f"round {round_no}: {len(current)} pages recorded, {errors} errors", flush=True)

    def write_consolidated_round_files(self) -> None:
        by_round: dict[int, list[PageResult]] = defaultdict(list)
        for result in self.results:
            if result.manifest["status"] == "ok" and result.manifest.get("parsed_json_path"):
                by_round[result.spec.round_no].append(result)

        def load_parsed(result: PageResult) -> dict[str, Any]:
            parsed_rel = result.manifest.get("parsed_json_path")
            if not parsed_rel:
                return {}
            try:
                return json.loads((self.workspace / parsed_rel).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}

        for round_no, results in sorted(by_round.items()):
            round_dir = self.round_dir(round_no)
            summary_path = round_dir / "detail_index.csv"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            with summary_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "round",
                        "role",
                        "category",
                        "item_id",
                        "url",
                        "title",
                        "summary_json",
                        "source_bytes",
                        "sha256",
                    ],
                )
                writer.writeheader()
                for result in sorted(results, key=lambda item: item.spec.url):
                    if result.spec.role != "detail":
                        continue
                    parsed = load_parsed(result)
                    summary = parsed.get("summary", [])
                    title = next((line["text"] for line in summary if line["kind"] == "title"), "")
                    writer.writerow(
                        {
                            "round": round_no,
                            "role": result.spec.role,
                            "category": result.spec.category or "",
                            "item_id": result.spec.item_id or "",
                            "url": result.spec.url,
                            "title": title,
                            "summary_json": json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
                            "source_bytes": result.manifest["source_bytes"],
                            "sha256": result.manifest["sha256"],
                        }
                    )

            rows_path = round_dir / "numeric_table_rows.csv.gz"
            with gzip.open(rows_path, "wt", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "round",
                        "role",
                        "category",
                        "item_id",
                        "url",
                        "table_index",
                        "context_heading",
                        "row_index",
                        "cells_json",
                        "numbers_json",
                    ],
                )
                writer.writeheader()
                for result in sorted(results, key=lambda item: item.spec.url):
                    parsed = load_parsed(result)
                    for table in parsed.get("numeric_tables", []):
                        for row in table.get("rows", []):
                            cells = row.get("cells", [])
                            numbers = [
                                {"cell_index": index, **number}
                                for index, cell in enumerate(cells)
                                for number in cell.get("numbers", [])
                            ]
                            writer.writerow(
                                {
                                    "round": round_no,
                                    "role": result.spec.role,
                                    "category": result.spec.category or "",
                                    "item_id": result.spec.item_id or "",
                                    "url": result.spec.url,
                                    "table_index": table.get("table_index"),
                                    "context_heading": table.get("context_heading", ""),
                                    "row_index": row.get("row_index"),
                                    "cells_json": json.dumps(cells, ensure_ascii=False, separators=(",", ":")),
                                    "numbers_json": json.dumps(numbers, ensure_ascii=False, separators=(",", ":")),
                                }
                            )

    def write_metadata(self, requested_rounds: list[int]) -> tuple[Path, Path, Path]:
        entries = sorted((result.manifest for result in self.results), key=lambda item: (item["round"], item["url"]))
        manifest = {
            "schema_version": 1,
            "parser_version": PARSER_VERSION,
            "generated_at": utc_now(),
            "workspace": ".",
            "data_root": relpath(self.data_dir, self.workspace),
            "requested_rounds": requested_rounds,
            "network_concurrency": self.workers,
            "detail_storage_policy": (
                "summary and numeric tables only; free-text voter comments omitted; "
                "source URL/SHA-256/byte length retained"
            ),
            "entries": entries,
        }
        manifest_path = self.metadata_dir / "jp_official_legacy_manifest.json"
        json_dump(manifest_path, manifest)

        rounds_value: dict[str, Any] = {}
        for round_no in requested_rounds:
            round_entries = [entry for entry in entries if entry["round"] == round_no]
            role_counts = Counter(entry["role"] for entry in round_entries)
            ok_role_counts = Counter(entry["role"] for entry in round_entries if entry["status"] == "ok")
            detail_categories: dict[str, Any] = {}
            categories = sorted(self.discovered_detail_urls[round_no])
            for category in categories:
                expected_urls = self.discovered_detail_urls[round_no][category]
                category_entries = [
                    entry
                    for entry in round_entries
                    if entry["role"] == "detail" and entry.get("category") == category
                ]
                fetched_urls = {entry["url"] for entry in category_entries if entry["status"] == "ok"}
                detail_categories[category] = {
                    "discovered": len(expected_urls),
                    "recorded": len(category_entries),
                    "fetched_ok": len(fetched_urls),
                    "missing": sorted(expected_urls - fetched_urls),
                    "numeric_tables": sum(entry["numeric_table_count"] for entry in category_entries),
                    "numeric_rows": sum(entry["numeric_row_count"] for entry in category_entries),
                }
            rounds_value[str(round_no)] = {
                "pages_recorded": len(round_entries),
                "pages_ok": sum(entry["status"] == "ok" for entry in round_entries),
                "pages_error": sum(entry["status"] != "ok" for entry in round_entries),
                "roles_recorded": dict(sorted(role_counts.items())),
                "roles_ok": dict(sorted(ok_role_counts.items())),
                "detail_categories": detail_categories,
                "numeric_tables": sum(entry["numeric_table_count"] for entry in round_entries),
                "numeric_rows": sum(entry["numeric_row_count"] for entry in round_entries),
                "errors": [
                    {"url": entry["url"], "error": entry["error"]}
                    for entry in round_entries
                    if entry["status"] != "ok"
                ],
            }
        coverage = {
            "schema_version": 1,
            "generated_at": utc_now(),
            "requested_rounds": requested_rounds,
            "rounds": rounds_value,
            "complete": all(
                round_value["pages_error"] == 0
                and all(not category["missing"] for category in round_value["detail_categories"].values())
                for round_value in rounds_value.values()
            ),
        }
        coverage_path = self.metadata_dir / "jp_official_legacy_coverage.json"
        json_dump(coverage_path, coverage)

        validation_errors: list[dict[str, Any]] = []
        checked_raw = 0
        checked_parsed = 0
        for entry in entries:
            if entry["status"] != "ok":
                continue
            raw_rel = entry.get("raw_html_path")
            parsed_rel = entry.get("parsed_json_path")
            if raw_rel:
                raw_path = self.workspace / raw_rel
                if not raw_path.exists():
                    validation_errors.append({"url": entry["url"], "error": "raw file missing"})
                else:
                    checked_raw += 1
                    if source_hash(raw_path.read_bytes()) != entry["sha256"]:
                        validation_errors.append({"url": entry["url"], "error": "raw SHA-256 mismatch"})
            if parsed_rel:
                parsed_path = self.workspace / parsed_rel
                if not parsed_path.exists():
                    validation_errors.append({"url": entry["url"], "error": "parsed file missing"})
                else:
                    checked_parsed += 1
                    try:
                        parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
                        if parsed.get("source", {}).get("sha256") != entry["sha256"]:
                            validation_errors.append({"url": entry["url"], "error": "parsed source SHA-256 mismatch"})
                        if entry["role"] == "detail" and "comments" in parsed:
                            validation_errors.append({"url": entry["url"], "error": "unexpected comments field"})
                    except (OSError, json.JSONDecodeError) as exc:
                        validation_errors.append({"url": entry["url"], "error": f"invalid parsed JSON: {exc}"})
        validation = {
            "schema_version": 1,
            "generated_at": utc_now(),
            "manifest_entries": len(entries),
            "raw_files_sha256_checked": checked_raw,
            "parsed_json_checked": checked_parsed,
            "network_concurrency_at_most_8": self.workers <= MAX_WORKERS,
            "detail_comment_payload_fields": 0,
            "errors": validation_errors,
            "valid": not validation_errors and coverage["complete"],
        }
        validation_path = self.metadata_dir / "jp_official_legacy_validation.json"
        json_dump(validation_path, validation)
        return manifest_path, coverage_path, validation_path


def parse_rounds(value: str) -> list[int]:
    result: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text), int(end_text)
            result.update(range(min(start, end), max(start, end) + 1))
        else:
            result.add(int(part))
    invalid = sorted(number for number in result if not 3 <= number <= 16)
    if invalid:
        raise argparse.ArgumentTypeError(f"rounds outside 3--16: {invalid}")
    return sorted(result)


def build_parser() -> argparse.ArgumentParser:
    script = Path(__file__).resolve()
    default_workspace = script.parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", default="3-16", help="comma/range expression, default: 3-16")
    parser.add_argument("--workers", type=int, default=8, help="download workers, hard-capped at 8")
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--refresh", action="store_true", help="ignore reusable local pages")
    parser.add_argument("--workspace", type=Path, default=default_workspace)
    parser.add_argument("--data-dir", type=Path, default=default_workspace / "data_raw" / "jp_official_legacy")
    parser.add_argument("--metadata-dir", type=Path, default=default_workspace / "metadata")
    parser.add_argument(
        "--limit-details",
        type=int,
        default=None,
        help="development-only cap per structured round; omit for complete coverage",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rounds = parse_rounds(args.rounds)
    except (ValueError, argparse.ArgumentTypeError) as exc:
        print(f"invalid --rounds: {exc}", file=sys.stderr)
        return 2
    crawler = LegacyCrawler(
        workspace=args.workspace,
        data_dir=args.data_dir,
        metadata_dir=args.metadata_dir,
        workers=args.workers,
        refresh=args.refresh,
        timeout=args.timeout,
        retries=max(0, args.retries),
        limit_details=args.limit_details,
    )
    crawler.run(rounds)
    crawler.write_consolidated_round_files()
    manifest, coverage, validation = crawler.write_metadata(rounds)
    error_count = sum(result.manifest["status"] != "ok" for result in crawler.results)
    print(f"manifest: {manifest}")
    print(f"coverage: {coverage}")
    print(f"validation: {validation}")
    print(f"pages: {len(crawler.results)}, errors: {error_count}")
    return 1 if error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
