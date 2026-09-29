#!/usr/bin/env python3
"""Crawl public character vote reasons/comments for CN1--11 and JP3--16.

The two official sites expose the text through different historical interfaces:
old Japanese pages contain HTML comment blocks, old Chinese pages expose a
reason page per character, and Chinese rounds 10/11 expose a read-only
GraphQL reason query.  Japanese rounds 17--22 are handled by the companion
Node script because their detail data is generated JavaScript literal modules.

The crawler stores one JSON envelope per entity and a deterministic gzip JSONL
file per region/round.  User-submitted text is retained as data only; it is
never rendered as HTML by this program.  All network work is public read-only
GET/POST access, bounded by a small worker pool, retrying and resumable.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import html as html_lib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


WORKSPACE = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = WORKSPACE / "data_raw" / "character_comments"
METADATA_ROOT = WORKSPACE / "metadata"
MANIFEST_PATH = METADATA_ROOT / "character_comments_manifest.json"
COVERAGE_PATH = METADATA_ROOT / "character_comments_coverage.csv"
JP_LEGACY_MANIFEST = METADATA_ROOT / "jp_official_legacy_manifest.json"
CN_LEGACY_ROOT = WORKSPACE / "data_raw" / "cn_official_legacy"
CN_MODERN_ROOT = WORKSPACE / "data_raw" / "cn_official"
MODERN_HELPER = Path(__file__).with_name("crawl_jp_character_comments.mjs")

SCHEMA_VERSION = 1
USER_AGENT = "TouhouVoteResearch/1.0 (public character comment archive)"
MAX_WORKERS = 8
TRANSIENT_STATUSES = {408, 425, 429, 500, 502, 503, 504, 521, 522, 523, 524}

JP_COMMENT_FIELDS = ("text", "raw_text", "author", "is_primary", "submitted_at")


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node | str"] = field(default_factory=list)


class TreeParser(HTMLParser):
    """Small tolerant DOM sufficient for the stable official result layouts."""

    VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.stack: list[Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag.lower(), {key.lower(): value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if node.tag not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].children.append(
            Node(tag.lower(), {key.lower(): value or "" for key, value in attrs})
        )

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].children.append(data)


def parse_tree(payload: bytes, encoding: str = "utf-8") -> Node:
    parser = TreeParser()
    parser.feed(payload.decode(encoding, "replace"))
    parser.close()
    return parser.root


def descendants(node: Node, tag: str | None = None) -> Iterator[Node]:
    for child in node.children:
        if not isinstance(child, Node):
            continue
        if tag is None or child.tag == tag:
            yield child
        yield from descendants(child, tag)


def has_class(node: Node, value: str) -> bool:
    return value in set((node.attrs.get("class") or "").split())


def text_content(node: Node, *, preserve_breaks: bool = False) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag == "br" and preserve_breaks:
            parts.append("\n")
        else:
            parts.append(text_content(child, preserve_breaks=preserve_breaks))
    return "".join(parts)


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = value.replace("\r", "").replace("\x00", "")
    lines = [re.sub(r"[ \t　]+", " ", line).strip() for line in value.split("\n")]
    return "\n".join(line for line in lines if line)


def normalize_comment(value: str) -> str:
    return clean_text(html_lib.unescape(value))


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def atomic_gzip_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp.gz", dir=path.parent)
    os.close(fd)
    count = 0
    try:
        with open(name, "wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
                for row in rows:
                    payload = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
                    compressed.write(payload)
                    count += 1
                compressed.flush()
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return count


def parse_rounds(value: str, minimum: int, maximum: int) -> list[int]:
    result: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            result.update(range(min(int(left), int(right)), max(int(left), int(right)) + 1))
        else:
            result.add(int(part))
    invalid = sorted(value for value in result if value < minimum or value > maximum)
    if invalid:
        raise argparse.ArgumentTypeError(f"rounds outside {minimum}--{maximum}: {invalid}")
    return sorted(result)


def parse_encoding(payload: bytes) -> str:
    head = payload[:8192].decode("ascii", "ignore")
    match = re.search(r"charset\s*=\s*[\"']?([A-Za-z0-9._-]+)", head, re.I)
    value = (match.group(1).lower() if match else "utf-8").replace("shift-jis", "cp932")
    return {"euc-jp": "euc_jp", "sjis": "cp932", "shift_jis": "cp932"}.get(value, value)


class HttpClient:
    def __init__(self, *, timeout: float, retries: int, workers: int) -> None:
        self.timeout = timeout
        self.retries = max(0, retries)
        self.workers = max(1, min(MAX_WORKERS, workers))

    def fetch(self, url: str, *, method: str = "GET", body: bytes | None = None) -> tuple[bytes, int, str, str | None]:
        last_error: BaseException | None = None
        for attempt in range(self.retries + 1):
            request = Request(
                url,
                data=body if method == "POST" else None,
                method=method,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json,text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
                    **({"Content-Type": "application/json"} if method == "POST" else {}),
                },
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return response.read(), int(response.status), response.geturl(), response.headers.get_content_charset()
            except HTTPError as exc:
                last_error = exc
                if exc.code not in TRANSIENT_STATUSES or attempt >= self.retries:
                    raise
            except (URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    raise
            time.sleep(min(12.0, 0.75 * (2**attempt)))
        assert last_error is not None
        raise last_error


def source_info(url: str, payload: bytes, effective_url: str, charset: str | None) -> dict[str, Any]:
    return {
        "url": url,
        "effective_url": effective_url,
        "sha256": sha256_bytes(payload),
        "bytes": len(payload),
        "charset": charset,
        "retrieved_at": utc_now(),
    }


def comment_record(
    *,
    region: str,
    round_no: int,
    entity_id: str,
    entity_name: str,
    rank: int | None,
    index: int,
    comment: Mapping[str, Any],
    source: Mapping[str, Any],
    source_kind: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "region": region,
        "round": round_no,
        "category": "character",
        "entity_id": entity_id,
        "entity_name": entity_name,
        "rank": rank,
        "comment_index": index,
        "text": comment.get("text"),
        "raw_text": comment.get("raw_text"),
        "author": comment.get("author"),
        "is_primary": comment.get("is_primary"),
        "submitted_at": comment.get("submitted_at"),
        "source_kind": source_kind,
        "source_url": source.get("url"),
        "source_sha256": source.get("sha256"),
        "source_bytes": source.get("bytes"),
        "retrieved_at": source.get("retrieved_at"),
    }


def entity_path(output_root: Path, region: str, round_no: int, entity_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", entity_id).strip("._") or "entity"
    return output_root / region / f"round_{round_no:02d}" / "entities" / f"{safe}.json"


def write_entity(
    output_root: Path,
    *,
    region: str,
    round_no: int,
    entity_id: str,
    entity_name: str,
    rank: int | None,
    comments: list[dict[str, Any]],
    source: Mapping[str, Any],
    source_kind: str,
    error: str | None = None,
) -> Path:
    value = {
        "schema_version": SCHEMA_VERSION,
        "region": region,
        "round": round_no,
        "category": "character",
        "entity_id": entity_id,
        "entity_name": entity_name,
        "rank": rank,
        "source_kind": source_kind,
        "source": dict(source),
        "comment_count": len(comments),
        "comments": comments,
        "error": error,
    }
    path = entity_path(output_root, region, round_no, entity_id)
    atomic_json(path, value)
    return path


def load_cached_entity(path: Path, url: str) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    source = value.get("source")
    if value.get("error"):
        # Failed entities are resumable work, not valid cache entries.
        return None
    if isinstance(source, Mapping) and source.get("url") == url and value.get("schema_version") == SCHEMA_VERSION:
        return value
    return None


def parse_legacy_comment(raw: str) -> dict[str, Any] | None:
    raw_text = normalize_comment(raw)
    if not raw_text:
        return None
    is_primary = raw_text.startswith(("*", "＊"))
    text = raw_text[1:].strip() if is_primary else raw_text
    author = None
    match = re.match(r"^(.*?)[（(]([^（）()]*)[）)]$", text)
    if match and match.group(2).strip():
        text, author = match.group(1).strip(), match.group(2).strip()
    return {
        "text": text,
        "raw_text": raw_text,
        "author": author,
        "is_primary": is_primary,
        "submitted_at": None,
    }


def parse_jp_header(value: str) -> tuple[str, int | None] | None:
    header = normalize_comment(value)
    if not header:
        return None
    if "その他" in header or "以下" in header:
        return None
    rank: int | None = None
    match = re.match(r"^(\d+)\s*位\s*(.*)$", header)
    if match:
        rank = int(match.group(1))
        header = match.group(2).strip()
    header = re.sub(r"\s+[\d,]+\s*(?:ポイント|点|pt)\b.*$", "", header, flags=re.I)
    header = re.sub(r"\s+コメント数\s*[:：]?\s*[\d,]+.*$", "", header)
    header = re.sub(r"\s*（一押し.*$", "", header)
    header = header.strip()
    if not header:
        return None
    return header, rank


def parse_jp_aggregate_comments(payload: bytes, *, round_no: int, url: str) -> list[dict[str, Any]]:
    encoding = parse_encoding(payload)
    tree = parse_tree(payload, encoding)
    result: list[dict[str, Any]] = []
    section_counter = 0
    for table in descendants(tree, "table"):
        cells = list(descendants(table, "td"))
        title_index = next((i for i, cell in enumerate(cells) if has_class(cell, "title_com")), None)
        if title_index is None:
            continue
        parsed_header = parse_jp_header(text_content(cells[title_index]))
        if parsed_header is None:
            continue
        entity_name, rank = parsed_header
        section_counter += 1
        if rank is None:
            rank = section_counter
        comments: list[dict[str, Any]] = []
        for cell in cells[title_index + 1 :]:
            # The official old layout puts one section's body in the next td.
            raw_body = text_content(cell, preserve_breaks=True)
            for line in raw_body.split("\n"):
                parsed = parse_legacy_comment(line)
                if parsed is not None:
                    comments.append(parsed)
        entity_id = "legacy-" + hashlib.sha256(f"jp:{round_no}:{entity_name}".encode()).hexdigest()[:16]
        result.append({
            "entity_id": entity_id,
            "entity_name": entity_name,
            "rank": rank,
            "comments": comments,
            "section_index": section_counter,
        })
    return result


def parse_jp_detail_comments(payload: bytes) -> tuple[str, int | None, list[dict[str, Any]]]:
    encoding = parse_encoding(payload)
    tree = parse_tree(payload, encoding)
    heading = next((node for node in descendants(tree, "h2")), None)
    entity_name = ""
    rank: int | None = None
    if heading is not None:
        heading_text = normalize_comment(text_content(heading))
        match = re.match(r"^(.*?)（(\d+)位）", heading_text)
        if match:
            entity_name, rank = match.group(1).strip(), int(match.group(2))
        else:
            entity_name = heading_text
    container = next((node for node in descendants(tree, "div") if has_class(node, "result_comment")), None)
    if container is None:
        return entity_name, rank, []
    paragraphs = list(descendants(container, "p"))
    raw_comments = [text_content(node, preserve_breaks=True) for node in paragraphs]
    if not paragraphs:
        raw_comments = text_content(container, preserve_breaks=True).split("\n")
    comments = [parsed for raw in raw_comments if (parsed := parse_legacy_comment(raw)) is not None]
    return entity_name, rank, comments


def load_jp_manifest() -> list[dict[str, Any]]:
    if not JP_LEGACY_MANIFEST.exists():
        raise RuntimeError(f"missing {JP_LEGACY_MANIFEST}; run crawl_jp_official_legacy.py first")
    value = json.loads(JP_LEGACY_MANIFEST.read_text(encoding="utf-8"))
    return [dict(row) for row in value.get("entries", []) if isinstance(row, Mapping)]


def jp_legacy_jobs(rounds: Sequence[int]) -> list[dict[str, Any]]:
    entries = load_jp_manifest()
    jobs: list[dict[str, Any]] = []
    for entry in entries:
        round_no = int(entry.get("round", -1))
        if round_no not in rounds or entry.get("status") != "ok" or entry.get("category") != "character":
            continue
        role = entry.get("role")
        # The old numbered result_char2*.html pages each group multiple
        # characters; rounds 11--16 use one detail page per character.
        if role == "detail":
            jobs.append(entry)
    # The manifest can contain a repeated URL after a resumed discovery pass.
    unique: dict[str, dict[str, Any]] = {}
    for job in jobs:
        unique.setdefault(str(job["url"]), job)
    return list(unique.values())


def run_jp_legacy(
    *, output_root: Path, rounds: Sequence[int], client: HttpClient, refresh: bool
) -> list[dict[str, Any]]:
    jobs = jp_legacy_jobs(rounds)
    results: list[dict[str, Any]] = []
    lock = threading.Lock()

    def process(entry: Mapping[str, Any]) -> dict[str, Any]:
        round_no = int(entry["round"])
        url = str(entry["url"])
        # Aggregate comment pages contain multiple entities; one source hash is
        # intentionally recorded on every derived entity.
        if round_no <= 10:
            # The legacy crawler's aggregate character page is the source of
            # the per-character comment sections (not result_char2*.html).
            cached_marker = output_root / "jp" / f"round_{round_no:02d}" / "sources" / (hashlib.sha256(url.encode()).hexdigest()[:20] + ".json")
            if cached_marker.exists() and not refresh:
                try:
                    return {"round": round_no, "url": url, "status": "cached_source", "entities": json.loads(cached_marker.read_text(encoding="utf-8"))}
                except (OSError, ValueError):
                    pass
        try:
            payload, status, effective_url, charset = client.fetch(url)
            source = source_info(url, payload, effective_url, charset or parse_encoding(payload))
            if round_no <= 10:
                parsed_entities = parse_jp_aggregate_comments(payload, round_no=round_no, url=url)
            else:
                name, rank, comments = parse_jp_detail_comments(payload)
                item_id = str(entry.get("item_id") or hashlib.sha256(url.encode()).hexdigest()[:16])
                parsed_entities = [{"entity_id": item_id, "entity_name": name, "rank": rank, "comments": comments}]
            written: list[dict[str, Any]] = []
            for item in parsed_entities:
                comments = [
                    comment_record(
                        region="jp", round_no=round_no, entity_id=str(item["entity_id"]),
                        entity_name=str(item.get("entity_name") or ""), rank=item.get("rank"),
                        index=index, comment=comment, source=source,
                        source_kind="jp_legacy_html",
                    )
                    for index, comment in enumerate(item.get("comments", []), 1)
                ]
                path = write_entity(
                    output_root, region="jp", round_no=round_no,
                    entity_id=str(item["entity_id"]), entity_name=str(item.get("entity_name") or ""),
                    rank=item.get("rank"), comments=comments, source=source,
                    source_kind="jp_legacy_html",
                )
                written.append({"entity_id": item["entity_id"], "path": path.as_posix(), "comment_count": len(comments)})
            if round_no <= 10:
                cached_marker.parent.mkdir(parents=True, exist_ok=True)
                atomic_json(cached_marker, written)
            return {"round": round_no, "url": url, "status": "downloaded", "source": source, "entities": written}
        except Exception as exc:  # keep one bad historical page from losing all rounds
            return {"round": round_no, "url": url, "status": "error", "error": f"{type(exc).__name__}: {exc}", "entities": []}

    with ThreadPoolExecutor(max_workers=client.workers) as pool:
        futures = [pool.submit(process, job) for job in jobs]
        for future in as_completed(futures):
            result = future.result()
            with lock:
                results.append(result)
            print(f"jp legacy round {result['round']}: {result['status']} {result['url']}", flush=True)
    return results


def discover_cn_legacy_entities(round_no: int) -> list[dict[str, Any]]:
    root = CN_LEGACY_ROOT / f"round_{round_no:02d}" / "raw" / "details" / "chara"
    entities: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.html"), key=lambda item: (not item.stem.isdigit(), int(item.stem) if item.stem.isdigit() else item.stem)):
        payload = path.read_bytes()
        tree = parse_tree(payload, "utf-8")
        heading = next((node for node in descendants(tree, "h1")), None)
        name = normalize_comment(text_content(heading)) if heading else path.stem
        entities.append({"entity_id": path.stem, "entity_name": name, "rank": None, "detail_path": path})
    if not entities:
        raise RuntimeError(f"no CN legacy character detail files under {root}")
    return entities


def cn_legacy_reason_url(round_no: int, entity_id: str) -> str:
    if round_no == 1:
        path = f"index.php?mod=rs&type=chara&id={entity_id}"
    elif round_no in (2, 3):
        path = f"index.php?m=r&t=1&i={entity_id}"
    elif round_no == 4:
        path = f"index.php?m=reason&t=chara&i={entity_id}"
    else:
        path = f"index.php?m=reason&type=chara&id={entity_id}"
    return f"https://touhou.vote/v{round_no}/{path}"


def parse_cn_legacy_reasons(payload: bytes, round_no: int) -> tuple[str | None, list[str]]:
    text = payload.decode("utf-8", "replace")
    tree = parse_tree(payload, "utf-8")
    heading = next((node for node in descendants(tree, "p") if "该页面是" in text_content(node) or "本页面为角色" in text_content(node)), None)
    name: str | None = None
    if heading:
        match = re.search(r"(?:该页面是|本页面为角色)\s*([^<\n]+?)\s*(?:的投票|的投票原因|</b>)", text_content(heading))
        if match:
            name = normalize_comment(match.group(1))
    rows: list[str] = []
    if round_no <= 4:
        table = next((node for node in descendants(tree, "table") if node.attrs.get("id") == "stable2"), None)
        if table:
            for tr in descendants(table, "tr"):
                cells = list(descendants(tr, "td"))
                if cells:
                    value = normalize_comment(text_content(cells[0]))
                    if value:
                        rows.append(value)
    else:
        marker = text.find('"rows"')
        if marker >= 0:
            colon = text.find(":", marker)
            if colon >= 0:
                try:
                    value, _ = json.JSONDecoder().raw_decode(text[colon + 1 :].lstrip())
                    if isinstance(value, list):
                        rows = [normalize_comment(str(item.get("reason", ""))) for item in value if isinstance(item, Mapping) and item.get("reason")]
                except json.JSONDecodeError:
                    rows = []
    return name, rows


def run_cn_legacy(*, output_root: Path, rounds: Sequence[int], client: HttpClient, refresh: bool) -> list[dict[str, Any]]:
    jobs = [(round_no, entity) for round_no in rounds for entity in discover_cn_legacy_entities(round_no)]

    def process(job: tuple[int, Mapping[str, Any]]) -> dict[str, Any]:
        round_no, entity = job
        entity_id = str(entity["entity_id"])
        url = cn_legacy_reason_url(round_no, entity_id)
        path = entity_path(output_root, "cn", round_no, entity_id)
        if path.exists() and not refresh:
            cached = load_cached_entity(path, url)
            if cached is not None:
                return {"round": round_no, "entity_id": entity_id, "status": "cached", "path": path.as_posix()}
        try:
            payload, status, effective_url, charset = client.fetch(url)
            source = source_info(url, payload, effective_url, charset or "utf-8")
            discovered_name, values = parse_cn_legacy_reasons(payload, round_no)
            entity_name = discovered_name or str(entity.get("entity_name") or entity_id)
            comments = [
                comment_record(
                    region="cn", round_no=round_no, entity_id=entity_id,
                    entity_name=entity_name, rank=entity.get("rank"), index=index,
                    comment={"text": value, "raw_text": value, "author": None, "is_primary": None, "submitted_at": None},
                    source=source, source_kind="cn_legacy_reason_html",
                )
                for index, value in enumerate(values, 1)
            ]
            write_entity(output_root, region="cn", round_no=round_no, entity_id=entity_id,
                         entity_name=entity_name, rank=entity.get("rank"), comments=comments,
                         source=source, source_kind="cn_legacy_reason_html")
            return {"round": round_no, "entity_id": entity_id, "status": "downloaded", "path": path.as_posix(), "comment_count": len(comments)}
        except Exception as exc:
            source = {"url": url, "retrieved_at": utc_now()}
            write_entity(output_root, region="cn", round_no=round_no, entity_id=entity_id,
                         entity_name=str(entity.get("entity_name") or entity_id), rank=entity.get("rank"),
                         comments=[], source=source, source_kind="cn_legacy_reason_html",
                         error=f"{type(exc).__name__}: {exc}")
            return {"round": round_no, "entity_id": entity_id, "status": "error", "error": f"{type(exc).__name__}: {exc}"}

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=client.workers) as pool:
        futures = [pool.submit(process, job) for job in jobs]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"cn legacy round {result['round']}: {result['status']} {result['entity_id']}", flush=True)
    return results


def load_cn_modern_entities(round_no: int) -> list[dict[str, Any]]:
    path = CN_MODERN_ROOT / f"round_{round_no}" / "graphql" / "base.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    entries = value["data"]["queryCharacterRanking"]["entries"]
    return [dict(entry) for entry in entries]


def run_cn_modern(*, output_root: Path, rounds: Sequence[int], client: HttpClient, refresh: bool) -> list[dict[str, Any]]:
    starts = {10: "2022-06-17T10:00:00.000Z", 11: "2023-12-29T10:00:00.000Z"}
    query = """query CharacterReasons($voteStart: DateTimeUtc!, $voteYear: Int!, $rank: Int!) { queryCharacterReasons(voteStart: $voteStart, voteYear: $voteYear, rank: $rank) { reasons } }"""

    def process(job: tuple[int, Mapping[str, Any]]) -> dict[str, Any]:
        round_no, entity = job
        rank = int(entity["rank"])
        entity_id = str(rank)
        url = "https://touhou.vote/res-be/graphql"
        path = entity_path(output_root, "cn", round_no, entity_id)
        if path.exists() and not refresh:
            cached = load_cached_entity(path, url)
            if cached is not None:
                return {"round": round_no, "entity_id": entity_id, "status": "cached", "path": path.as_posix()}
        variables = {"voteStart": starts[round_no], "voteYear": round_no, "rank": rank}
        body = json.dumps({"query": query, "variables": variables}, ensure_ascii=False, separators=(",", ":")).encode()
        try:
            payload, status, effective_url, charset = client.fetch(url, method="POST", body=body)
            source = source_info(url, payload, effective_url, charset or "utf-8")
            response = json.loads(payload.decode("utf-8"))
            errors = response.get("errors")
            if errors:
                raise RuntimeError(f"GraphQL errors: {errors}")
            values = response.get("data", {}).get("queryCharacterReasons", {}).get("reasons", [])
            if not isinstance(values, list):
                raise RuntimeError("queryCharacterReasons.reasons is not a list")
            name = str(entity.get("name") or "")
            comments = [
                comment_record(
                    region="cn", round_no=round_no, entity_id=entity_id,
                    entity_name=name, rank=rank, index=index,
                    comment={"text": str(value), "raw_text": str(value), "author": None, "is_primary": None, "submitted_at": None},
                    source=source, source_kind="cn_modern_graphql_reason",
                )
                for index, value in enumerate(values, 1)
            ]
            write_entity(output_root, region="cn", round_no=round_no, entity_id=entity_id,
                         entity_name=name, rank=rank, comments=comments,
                         source={**source, "request": {"query_sha256": sha256_bytes(query.encode()), "variables": variables}},
                         source_kind="cn_modern_graphql_reason")
            return {"round": round_no, "entity_id": entity_id, "status": "downloaded", "comment_count": len(comments), "path": path.as_posix()}
        except Exception as exc:
            write_entity(output_root, region="cn", round_no=round_no, entity_id=entity_id,
                         entity_name=str(entity.get("name") or ""), rank=rank,
                         comments=[], source={"url": url, "request": {"variables": variables}, "retrieved_at": utc_now()},
                         source_kind="cn_modern_graphql_reason", error=f"{type(exc).__name__}: {exc}")
            return {"round": round_no, "entity_id": entity_id, "status": "error", "error": f"{type(exc).__name__}: {exc}"}

    jobs = [(round_no, entity) for round_no in rounds for entity in load_cn_modern_entities(round_no)]
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=client.workers) as pool:
        futures = [pool.submit(process, job) for job in jobs]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"cn modern round {result['round']}: {result['status']} {result['entity_id']}", flush=True)
    return results


def run_modern_jp_helper(*, output_root: Path, rounds: Sequence[int], refresh: bool, workers: int) -> None:
    node = shutil.which("node") or "node"
    command = [node, str(MODERN_HELPER), "--rounds", ",".join(map(str, rounds)), "--output-root", str(output_root), "--workers", str(workers)]
    if refresh:
        command.append("--refresh")
    completed = subprocess.run(command, cwd=WORKSPACE, text=True, capture_output=True)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.returncode:
        if completed.stderr:
            print(completed.stderr, file=sys.stderr, end="")
        raise RuntimeError(f"Japanese modern comment helper exited with {completed.returncode}")


def workspace_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(WORKSPACE.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def flatten_outputs(output_root: Path) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for path in sorted(output_root.glob("*/round_*/entities/*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(value, Mapping):
            continue
        comments = value.get("comments") if isinstance(value.get("comments"), list) else []
        region = str(value.get("region"))
        round_no = int(value.get("round"))
        rows = [
            {
                **comment,
                "entity_id": value.get("entity_id"),
                "entity_name": value.get("entity_name"),
                "rank": value.get("rank"),
            }
            for comment in comments
            if isinstance(comment, Mapping)
        ]
        flat_path = output_root / region / f"round_{round_no:02d}" / "comments.jsonl.gz"
        # Rebuilt below in one pass per round; retaining this marker lets the
        # manifest point to exact output files without reading huge JSONL back.
        manifest.append({
            "region": region,
            "round": round_no,
            "category": "character",
            "entity_id": value.get("entity_id"),
            "entity_name": value.get("entity_name"),
            "rank": value.get("rank"),
            "status": "error" if value.get("error") else "ok",
            "error": value.get("error"),
            "comment_count": len(rows),
            "entity_path": workspace_path(path),
            "comments_path": workspace_path(flat_path),
            "source": value.get("source"),
            "source_kind": value.get("source_kind"),
        })
    by_round: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for item in manifest:
        by_round.setdefault((str(item["region"]), int(item["round"])), []).append(item)
    for (region, round_no), items in by_round.items():
        rows: list[dict[str, Any]] = []
        for item in sorted(items, key=lambda value: (value.get("rank") is None, value.get("rank") or 0, str(value.get("entity_id")))):
            entity_path_value = WORKSPACE / str(item["entity_path"])
            try:
                entity = json.loads(entity_path_value.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for comment in entity.get("comments", []):
                if isinstance(comment, Mapping):
                    rows.append(dict(comment))
        atomic_gzip_jsonl(output_root / region / f"round_{round_no:02d}" / "comments.jsonl.gz", rows)
    return manifest


def write_metadata(manifest: list[dict[str, Any]], requested: Mapping[str, Sequence[int]]) -> None:
    available_jp = sorted({int(row["round"]) for row in manifest if str(row.get("region")) == "jp"})
    available_cn = sorted({int(row["round"]) for row in manifest if str(row.get("region")) == "cn"})
    manifest_value = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "scope": {
            "jp_rounds": available_jp,
            "cn_rounds": available_cn,
            "category": "character",
        },
        "requested_scope": {
            "jp_rounds": list(requested.get("jp", [])),
            "cn_rounds": list(requested.get("cn", [])),
        },
        "content_policy": "public official user-submitted text; stored as untrusted data and never executed/rendered as HTML",
        "comment_fields": list(JP_COMMENT_FIELDS),
        "records": sorted(manifest, key=lambda row: (row["region"], row["round"], row.get("rank") is None, row.get("rank") or 0, str(row.get("entity_id")))),
    }
    atomic_json(MANIFEST_PATH, manifest_value)
    by_round: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in manifest:
        by_round.setdefault((str(row["region"]), int(row["round"])), []).append(row)
    rows: list[dict[str, Any]] = []
    fields = ["region", "round", "entities_expected", "entities_ok", "entities_error", "comments", "comments_path"]
    for (region, round_no), entries in sorted(by_round.items()):
        rows.append({
            "region": region,
            "round": round_no,
            "entities_expected": len(entries),
            "entities_ok": sum(row["status"] == "ok" for row in entries),
            "entities_error": sum(row["status"] != "ok" for row in entries),
            "comments": sum(int(row.get("comment_count") or 0) for row in entries),
            "comments_path": entries[0]["comments_path"],
        })
    COVERAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{COVERAGE_PATH.name}.", suffix=".tmp", dir=COVERAGE_PATH.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(name, COVERAGE_PATH)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jp-rounds", default=None, help="JP rounds 3-22; defaults to all only if neither region is selected")
    parser.add_argument("--cn-rounds", default=None, help="CN rounds 1-11; defaults to all only if neither region is selected")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--skip-modern-jp", action="store_true", help="do not invoke the Node helper for JP17--22")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        jp_rounds = parse_rounds(args.jp_rounds, 3, 22) if args.jp_rounds is not None else (list(range(3, 23)) if args.cn_rounds is None else [])
        cn_rounds = parse_rounds(args.cn_rounds, 1, 11) if args.cn_rounds is not None else (list(range(1, 12)) if args.jp_rounds is None else [])
        if not 1 <= args.workers <= MAX_WORKERS:
            raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
    except (ValueError, argparse.ArgumentTypeError) as exc:
        print(f"invalid arguments: {exc}", file=sys.stderr)
        return 2

    client = HttpClient(timeout=args.timeout, retries=args.retries, workers=args.workers)
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    legacy_jp = [round_no for round_no in jp_rounds if round_no <= 16]
    modern_jp = [round_no for round_no in jp_rounds if round_no >= 17]
    legacy_cn = [round_no for round_no in cn_rounds if round_no <= 9]
    modern_cn = [round_no for round_no in cn_rounds if round_no >= 10]

    if legacy_jp:
        run_jp_legacy(output_root=output_root, rounds=legacy_jp, client=client, refresh=args.refresh)
    if modern_jp and not args.skip_modern_jp:
        run_modern_jp_helper(output_root=output_root, rounds=modern_jp, refresh=args.refresh, workers=args.workers)
    if legacy_cn:
        run_cn_legacy(output_root=output_root, rounds=legacy_cn, client=client, refresh=args.refresh)
    if modern_cn:
        run_cn_modern(output_root=output_root, rounds=modern_cn, client=client, refresh=args.refresh)

    manifest = flatten_outputs(output_root)
    # When a custom output root is used, metadata still lives in the workspace;
    # the manifest paths remain workspace-relative only for the default root.
    write_metadata(manifest, {"jp": jp_rounds, "cn": cn_rounds})
    print(f"manifest: {MANIFEST_PATH}")
    print(f"coverage: {COVERAGE_PATH}")
    print(f"entities: {len(manifest)}")
    print(f"comments: {sum(int(row.get('comment_count') or 0) for row in manifest)}")
    return 1 if any(row.get("status") != "ok" for row in manifest) else 0


if __name__ == "__main__":
    raise SystemExit(main())
