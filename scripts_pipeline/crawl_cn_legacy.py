#!/usr/bin/env python3
"""Crawl the official Chinese Touhou popularity-poll legacy results (rounds 1-9).

The crawler intentionally keeps the official, per-round and per-entry records intact.
Canonical-name repair and same-track aggregation belong in a later processed layer.

Outputs
-------
data_raw/cn_official_legacy/round_XX/
    raw/                 Source HTML, JavaScript and JSON returned by touhou.vote.
    processed/           Parsed tables, embedded ranking rows and numeric CSV files.
    source_index.json    URL -> local-file provenance for the round.

The detail and item-API indexes expose ``entity_key`` in the form
``cn:<round>:<canonical-category>:<official-id>`` (for example
``cn:05:character:0001``) so downstream vote tables can join items without
relying on translated names.
metadata/
    cn_official_legacy_manifest.jsonl
    cn_official_legacy_coverage.json
    cn_official_legacy_coverage.csv
    cn_official_legacy_validation.json
    cn_official_legacy_advanced_coverage.json
    cn_official_legacy_advanced_coverage.csv
    cn_official_legacy_advanced_validation.json

With ``--advanced-only``, raw advanced ranking pages are stored as deterministic
``.html.gz`` files and the questionnaire-pair API as ``.json.gz``.  Parsed numeric
rankings, pair matrices and condition indexes live under
``processed/advanced/``.  The bounded scope excludes open answers, reason prose,
zero-sized cohorts, and display-only min/max/keyword filters.

The vote-reason endpoints are deliberately never followed.  Detail HTML therefore
contains only the official summary/table page and the link/count of reasons, never
the reason prose.

The script uses only Python's standard library.  It is resumable: a successfully
downloaded file with a matching manifest record is skipped.  Normal adaptive
ceilings are configurable per invocation/stage (defaults: ten workers, thirty
requests and three seconds).  A separate absolute safety rail prevents malformed
configuration from creating an unbounded request fan-out; transient recovery may
temporarily use a cooldown above the normal ceiling.

With ``--reuse-local-workbooks`` (also ``--skip-redundant-views``), the two
hash/header/row-validated ``TouhouVote*_cn.xlsx`` files may satisfy only the
redundant round-1 step-2/3/4 ranking views.  The canonical step-1 pages, all
detail/questionnaire/time/geography/cross-vote/advanced resources, and the
official HTTP manifest remain required and are never replaced by a workbook.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import html
import json
import math
import os
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import zlib
import zipfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

try:  # package import in tests
    from .cn_advanced_contract import advanced_coverage_contract
except ImportError:  # direct script execution from scripts_pipeline/
    from cn_advanced_contract import advanced_coverage_contract


SCRIPT_PATH = Path(__file__).resolve()
WORKSPACE = SCRIPT_PATH.parents[1]
DATA_ROOT = WORKSPACE / "data_raw" / "cn_official_legacy"
METADATA_ROOT = WORKSPACE / "metadata"
LEGACY_PROBE_ROOT = WORKSPACE / "staging" / "cn_legacy_probes"
MANIFEST_PATH = METADATA_ROOT / "cn_official_legacy_manifest.jsonl"
JOURNAL_PATH = METADATA_ROOT / ".cn_official_legacy_manifest_journal.jsonl"
COVERAGE_JSON = METADATA_ROOT / "cn_official_legacy_coverage.json"
COVERAGE_CSV = METADATA_ROOT / "cn_official_legacy_coverage.csv"
VALIDATION_JSON = METADATA_ROOT / "cn_official_legacy_validation.json"
RUN_STATE_JSON = METADATA_ROOT / "cn_official_legacy_run_state.json"
ADAPTIVE_PROFILE_JSON = METADATA_ROOT / "cn_official_legacy_adaptive_profiles.json"
ADVANCED_COVERAGE_JSON = METADATA_ROOT / "cn_official_legacy_advanced_coverage.json"
ADVANCED_COVERAGE_CSV = METADATA_ROOT / "cn_official_legacy_advanced_coverage.csv"
ADVANCED_REPORT_MD = WORKSPACE / "reports" / "cn_official_legacy_advanced_coverage.md"
ADVANCED_VALIDATION_JSON = METADATA_ROOT / "cn_official_legacy_advanced_validation.json"
# This is intentionally separate from the HTTP manifest.  The HTTP manifest
# describes reproducible official responses (URL/body/hash); a workbook cannot
# provide that provenance and must never be inserted into it.
LOCAL_SOURCE_MANIFEST_PATH = METADATA_ROOT / "cn_legacy_local_source_manifest.json"

# The two repaired workbooks are useful for the numeric ranking columns, but
# they do not contain official entity ids or the detail/questionnaire fields.
# Keep the expected hashes explicit: if a workbook is edited, the optimisation
# is disabled and the crawler falls back to the official pages automatically.
LOCAL_WORKBOOK_SPECS: dict[str, dict[str, Any]] = {
    "chara": {
        "path": WORKSPACE / "TouhouVote_cn.xlsx",
        "sha256": "e9aa71505e61b5763fb72b826e4a916eea9e69578b58f29e9bbbd343b66e02e9",
        "required_headers": (
            "名次", "译名", "票数", "本命数", "本命率", "本命加权",
            "票数占比", "本命占比",
        ),
    },
    "music": {
        "path": WORKSPACE / "TouhouVote_music_cn.xlsx",
        "sha256": "08e729fbd4391e598f8eb6eff366ce9aaba439449e5362f232b973dcd2881bda",
        "required_headers": (
            "名次", "译名", "票数", "本命数", "本命率", "本命加权",
            "票数占比", "本命占比",
        ),
    },
}
LOCAL_WORKBOOK_ROUNDS = tuple(range(1, 10))
# Only these v1 pages are alternate sort/order presentations of the same
# columns already present in the workbook.  v1 step=1 remains mandatory: its
# links are the authority used to discover stable detail ids.  All other
# rounds/categories/views are intentionally left untouched because they carry
# historical comparisons, demographic groups, cross-votes, or unique ids.
LOCAL_REDUNDANT_VARIANT_STEPS = frozenset({"2", "3", "4"})

# The crawler keeps the site's short category token (``chara``) in raw and
# processed columns, while the portable vote tables use ``character``.  Stable
# joins must use one spelling everywhere; only the key is canonicalized.
ENTITY_KEY_CATEGORY = {
    "chara": "character",
    "character": "character",
    "music": "music",
    "work": "work",
    "cp": "cp",
}


def entity_key(round_no: int, category: str, item_id: str) -> str:
    canonical_category = ENTITY_KEY_CATEGORY.get(str(category), str(category))
    return f"cn:{int(round_no):02d}:{canonical_category}:{item_id}"

BASE = "https://touhou.vote/v{round_no}/"
USER_AGENT = (
    "Mozilla/5.0 (compatible; CodexTouhouResearch/1.0; "
    "+local reproducible data audit)"
)
# User-configurable defaults. Keep the old names as compatibility fallbacks for
# tests and direct callers which construct a partially initialized Crawler.
DEFAULT_WORKER_CEILING = 10
DEFAULT_REQUEST_LIMIT_CEILING = 30
DEFAULT_BATCH_PAUSE_CEILING = 3.0
MAX_WORKERS = DEFAULT_WORKER_CEILING
MAX_BATCH_REQUESTS = DEFAULT_REQUEST_LIMIT_CEILING
MAX_BATCH_PAUSE_SECONDS = DEFAULT_BATCH_PAUSE_CEILING

# Absolute program-level safety rails. These are deliberately not ordinary
# stage settings: they are the final defense against malformed queue files or
# accidental ``--workers 100000`` invocations.
ABSOLUTE_MAX_WORKERS = 32
ABSOLUTE_MAX_BATCH_REQUESTS = 300
ABSOLUTE_MAX_BATCH_PAUSE_SECONDS = 60.0
RECOVERY_MIN_PAUSE_SECONDS = 3.0
RECOVERY_MAX_WAIT_SECONDS = 120.0

# Adaptive changes deliberately use long hysteresis.  A wave of concurrent
# 502/504 responses represents one upstream incident, not ten independent
# reasons to remove ten worker slots.  Likewise, a fast host can complete a
# handful of requests in seconds, so a result-count window alone is not enough
# evidence for immediately restoring concurrency.
# Keep the controller responsive during a long queue.  A minute-scale dwell
# made a restarted stage appear stuck at its emergency speed even after the
# host had recovered.
ADAPTIVE_DECREASE_MIN_INTERVAL_SECONDS = 30.0
ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS = 30.0
ADAPTIVE_SUCCESS_WINDOW_RESULTS = 20
ADAPTIVE_PAUSE_INCREASE_STEP_SECONDS = 0.5
ADAPTIVE_PAUSE_DECREASE_STEP_SECONDS = 0.25
# A learned emergency cooldown is not permanent.  A singleton still probes
# one conservative quarter-second tier at a time, with the same long health
# dwell used for worker recovery.  The rollback marker prevents a failed probe
# from forgetting the previous stable value.
ADAPTIVE_PAUSE_PROBE_TARGET_SECONDS = 90.0
ADAPTIVE_PAUSE_PROBE_MIN_RESULTS = 6
ADAPTIVE_PAUSE_PROBE_MAX_STEP_SECONDS = 2.0
ADAPTIVE_PAUSE_PROBE_FRACTION = 0.20
# Recovery is deliberately much slower than the old result-count-only
# controller.  A faster worker/pause operating point must survive both a
# wall-clock dwell and enough *new* successful responses in its current epoch.
ADAPTIVE_HEALTHY_MIN_SECONDS = 120.0
ADAPTIVE_HEALTHY_MIN_RESULTS = 30

# HTTP gateways and the archived PHP service use a wider set of transient
# statuses than the classic 502/503/504 trio.  Treat these as retryable
# transport saturation rather than permanent semantic failures.
TRANSIENT_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504, 521, 522, 523, 524}

# Environment names are useful for one-off runs and queue launchers which
# cannot yet append the newer CLI options. CLI values take precedence.
ENV_WORKER_CEILING = "DATA_CRAWL_WORKER_CEILING"
ENV_REQUEST_LIMIT_CEILING = "DATA_CRAWL_REQUEST_LIMIT_CEILING"
ENV_BATCH_PAUSE_CEILING = "DATA_CRAWL_BATCH_PAUSE_CEILING"
# ``--workers`` is the starting point, not the adaptive controller's target.
# Keep a local emergency guard so a malformed response cannot turn a crawler
# into an unbounded request fan-out.  The controller explores up to this guard
# and backs off on upstream saturation.
MIN_ADAPTIVE_BATCH_PAUSE_SECONDS = 0.25
RUN_STATE_UPDATE_INTERVAL_SECONDS = 1.0


def _configured_ceiling(
    value: int | float | None,
    *,
    env_name: str,
    default: int | float,
    absolute: int | float,
    integer: bool,
) -> int | float:
    """Resolve a user ceiling while always respecting the absolute rail."""

    candidate: int | float | str | None = value
    if candidate is None:
        candidate = os.environ.get(env_name)
    try:
        numeric = float(candidate) if candidate is not None else float(default)
    except (TypeError, ValueError):
        numeric = float(default)
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        numeric = float(default)
    minimum = 1.0 if integer else 0.0
    numeric = max(minimum, min(float(absolute), numeric))
    return int(numeric) if integer else float(numeric)


def _requested_ceiling(
    value: int | float | None,
    *,
    env_name: str,
    default: int | float,
    absolute: int | float,
    integer: bool,
) -> int | float:
    """Resolve a CLI/environment ceiling and reject invalid explicit values.

    ``_configured_ceiling`` is intentionally forgiving for library callers;
    command-line invocations should instead fail loudly so a typo cannot make
    a run unexpectedly faster or slower than requested.
    """

    raw: int | float | str | None = value
    if raw is None:
        raw = os.environ.get(env_name)
    if raw is None:
        return default
    try:
        numeric = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{env_name} must be numeric") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"{env_name} must be finite")
    if integer and not numeric.is_integer():
        raise ValueError(f"{env_name} must be an integer")
    minimum = 1.0 if integer else 0.0
    if numeric < minimum or numeric > float(absolute):
        raise ValueError(
            f"{env_name} must be between {minimum:g} and {absolute:g}"
        )
    return int(numeric) if integer else numeric


def legacy_probe_path(filename: str) -> Path:
    """Resolve retained discovery probes from their organized staging area.

    The workspace used to keep ``.tmp_cn_*`` files loose in its root.  Keep a
    root fallback so older checkouts remain resumable while allowing the
    maintained workspace to store the probes under ``staging/``.
    """

    staged = LEGACY_PROBE_ROOT / filename
    return staged if staged.is_file() else WORKSPACE / filename


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


_XLSX_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_XLSX_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_XLSX_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _xlsx_column_index(reference: str) -> int:
    """Return a zero-based column index from an XLSX cell reference."""

    letters = re.match(r"([A-Za-z]+)", reference or "")
    if not letters:
        return 0
    value = 0
    for character in letters.group(1).upper():
        value = value * 26 + ord(character) - ord("A") + 1
    return max(0, value - 1)


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        payload = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(payload)
    return [
        clean_text("".join(node.itertext()))
        for node in root.findall(f"{{{_XLSX_MAIN_NS}}}si")
    ]


def _xlsx_cell_text(cell: ET.Element, shared_strings: Sequence[str]) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        node = cell.find(f"{{{_XLSX_MAIN_NS}}}is")
        return clean_text("".join(node.itertext())) if node is not None else ""
    value_node = cell.find(f"{{{_XLSX_MAIN_NS}}}v")
    value = "" if value_node is None or value_node.text is None else value_node.text
    if cell_type == "s":
        try:
            return shared_strings[int(value)]
        except (ValueError, IndexError):
            return ""
    return clean_text(value)


def _xlsx_sheet_rows(archive: zipfile.ZipFile, target: str, shared_strings: Sequence[str]) -> list[list[str]]:
    target = target.replace("\\", "/")
    if target.startswith("/"):
        target = target.lstrip("/")
    if not target.startswith("xl/"):
        target = f"xl/{target}"
    root = ET.fromstring(archive.read(target))
    rows: list[list[str]] = []
    for row in root.findall(f".//{{{_XLSX_MAIN_NS}}}row"):
        values: dict[int, str] = {}
        for cell in row.findall(f"{{{_XLSX_MAIN_NS}}}c"):
            text = _xlsx_cell_text(cell, shared_strings)
            if text:
                values[_xlsx_column_index(cell.attrib.get("r", ""))] = text
        if values:
            width = max(values) + 1
            materialized = [""] * width
            for index, text in values.items():
                materialized[index] = text
            rows.append(materialized)
    return rows


def inspect_xlsx_workbook(
    path: Path,
    *,
    required_rounds: Sequence[int] = LOCAL_WORKBOOK_ROUNDS,
    required_headers: Sequence[str] = (),
    expected_sha256: str = "",
) -> dict[str, Any]:
    """Inspect just enough XLSX structure to safely gate local reuse.

    This deliberately uses the standard library rather than pandas/openpyxl so
    the crawler's normal Python runtime has no extra dependency.  A malformed,
    edited, or incomplete workbook produces ``valid=False`` and therefore
    causes a normal network crawl instead of silently omitting data.
    """

    result: dict[str, Any] = {
        "path": rel_workspace(path) if path.is_absolute() and path.is_relative_to(WORKSPACE) else str(path),
        "exists": path.is_file(),
        "sha256": "",
        "expected_sha256": expected_sha256,
        "hash_ok": False,
        "required_headers": list(required_headers),
        "sheets": {},
        "valid_rounds": [],
        "errors": [],
        "valid": False,
    }
    if not path.is_file():
        result["errors"].append("workbook_missing")
        return result
    if "_grouped" in path.stem.lower():
        result["errors"].append("derived_grouped_workbook_not_allowed")
        return result
    try:
        result["sha256"] = sha256_file(path)
    except OSError as exc:
        result["errors"].append(f"workbook_unreadable:{exc}")
        return result
    result["hash_ok"] = not expected_sha256 or result["sha256"] == expected_sha256
    if not result["hash_ok"]:
        result["errors"].append("sha256_mismatch")
    try:
        with zipfile.ZipFile(path) as archive:
            shared_strings = _xlsx_shared_strings(archive)
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            rel_targets = {
                node.attrib.get("Id", ""): node.attrib.get("Target", "")
                for node in relationships.findall(f"{{{_XLSX_PACKAGE_REL_NS}}}Relationship")
            }
            sheets_node = workbook.find(f"{{{_XLSX_MAIN_NS}}}sheets")
            sheet_nodes = list(sheets_node) if sheets_node is not None else []
            by_name: dict[str, str] = {}
            for node in sheet_nodes:
                name = str(node.attrib.get("name", ""))
                rel_id = node.attrib.get(f"{{{_XLSX_REL_NS}}}id", "")
                if name and rel_id in rel_targets:
                    by_name[name] = rel_targets[rel_id]
            for round_no in required_rounds:
                sheet_name = str(round_no)
                sheet_info: dict[str, Any] = {
                    "sheet": sheet_name,
                    "header": [],
                    "header_ok": False,
                    "row_count": 0,
                    "data_row_count": 0,
                    "valid": False,
                    "errors": [],
                }
                target = by_name.get(sheet_name)
                if not target:
                    sheet_info["errors"].append("sheet_missing")
                    result["sheets"][sheet_name] = sheet_info
                    continue
                try:
                    rows = _xlsx_sheet_rows(archive, target, shared_strings)
                except (KeyError, ET.ParseError, OSError, ValueError) as exc:
                    sheet_info["errors"].append(f"sheet_unreadable:{type(exc).__name__}")
                    result["sheets"][sheet_name] = sheet_info
                    continue
                header = [clean_text(value) for value in (rows[0] if rows else [])]
                header_set = set(header)
                sheet_info["header"] = header
                sheet_info["header_ok"] = set(required_headers).issubset(header_set)
                sheet_info["row_count"] = len(rows)
                rank_column = {name: index for index, name in enumerate(header)}.get("名次")
                data_rows = []
                if rank_column is not None:
                    for candidate in rows[1:]:
                        if rank_column < len(candidate):
                            try:
                                float(candidate[rank_column])
                            except (TypeError, ValueError):
                                # Hyperlink/annotation rows can be interleaved
                                # by spreadsheet editors.  They are not ranking
                                # records and must not make a valid workbook
                                # look corrupt.
                                continue
                            data_rows.append(candidate)
                sheet_info["data_row_count"] = len(data_rows)
                if not sheet_info["header_ok"]:
                    sheet_info["errors"].append("required_headers_missing")
                if sheet_info["data_row_count"] < 1:
                    sheet_info["errors"].append("no_data_rows")
                # Check the core numeric columns and the nonnegative vote
                # domain.  This catches a shifted/corrupt worksheet without
                # imposing assumptions on optional demographic columns.
                column_map = {name: index for index, name in enumerate(header)}
                for row in data_rows:
                    for field_name in ("名次", "票数", "本命数", "本命加权"):
                        index = column_map.get(field_name)
                        if index is None or index >= len(row):
                            continue
                        raw = row[index].strip()
                        try:
                            numeric = float(raw)
                        except (TypeError, ValueError):
                            sheet_info["errors"].append(f"non_numeric:{field_name}")
                            break
                        if numeric < 0:
                            sheet_info["errors"].append(f"negative:{field_name}")
                            break
                    if sheet_info["errors"] and sheet_info["errors"][-1].startswith(("non_numeric:", "negative:")):
                        break
                sheet_info["valid"] = not sheet_info["errors"]
                result["sheets"][sheet_name] = sheet_info
                if sheet_info["valid"]:
                    result["valid_rounds"].append(round_no)
    except (KeyError, ET.ParseError, OSError, zipfile.BadZipFile) as exc:
        result["errors"].append(f"workbook_parse_error:{type(exc).__name__}")
    result["valid"] = bool(result["hash_ok"] and not result["errors"] and all(
        int(round_no) in result["valid_rounds"] for round_no in required_rounds
    ))
    return result


def validate_local_workbooks() -> dict[str, Any]:
    sources: dict[str, Any] = {}
    for category, spec in LOCAL_WORKBOOK_SPECS.items():
        sources[category] = inspect_xlsx_workbook(
            Path(spec["path"]),
            required_rounds=LOCAL_WORKBOOK_ROUNDS,
            required_headers=tuple(spec.get("required_headers", ())),
            expected_sha256=str(spec.get("sha256", "")),
        )
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "required_rounds": list(LOCAL_WORKBOOK_ROUNDS),
        "sources": sources,
        "valid": bool(sources) and all(bool(value.get("valid")) for value in sources.values()),
    }


def rel_workspace(path: Path) -> str:
    return path.resolve().relative_to(WORKSPACE).as_posix()


def display_path(path: Path) -> str:
    """Return a workspace-relative path when possible, otherwise an absolute path."""

    try:
        return rel_workspace(path)
    except ValueError:
        return path.resolve().as_posix()


def write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f".{path.name}.{threading.get_ident()}.part")
    with part.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(part, path)


def write_text_atomic(path: Path, text: str) -> None:
    write_bytes_atomic(path, text.encode("utf-8"))


def write_json_atomic(path: Path, value: Any, *, indent: int = 2) -> None:
    write_text_atomic(
        path,
        json.dumps(value, ensure_ascii=False, indent=indent, sort_keys=False) + "\n",
    )


def write_gzip_json_atomic(path: Path, value: Any) -> None:
    payload = json.dumps(
        value, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    write_bytes_atomic(path, gzip.compress(payload, compresslevel=9, mtime=0))


def write_gzip_csv_atomic(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
    fieldnames: Sequence[str],
) -> int:
    """Write a deterministic UTF-8-with-BOM CSV inside gzip."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f".{path.name}.{threading.get_ident()}.part")
    count = 0
    with part.open("wb") as raw:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw,
            compresslevel=9,
            mtime=0,
        ) as compressed:
            import io

            with io.TextIOWrapper(
                compressed, encoding="utf-8-sig", newline="", write_through=True
            ) as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=fieldnames, extrasaction="ignore"
                )
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)
                    count += 1
    os.replace(part, path)
    return count


def read_json_path(path: Path) -> Any:
    data = path.read_bytes()
    if path.suffix == ".gz":
        data = gzip.decompress(data)
    return json.loads(decode_body(data, "application/json; charset=utf-8"))


def integer_value(value: Any) -> int | None:
    """Return an integer from official numeric scalars/FooTable wrappers."""
    value = unwrap_footable(value)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        number = scalar_number(value)
        if isinstance(number, int):
            return number
        if isinstance(number, float) and number.is_integer():
            return int(number)
    return None


def decode_body(data: bytes, content_type: str = "") -> str:
    charset_match = re.search(r"charset\s*=\s*([\w.-]+)", content_type, re.I)
    encodings = [charset_match.group(1)] if charset_match else []
    encodings.extend(["utf-8", "gb18030", "big5"])
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def scalar_number(value: str) -> int | float | None:
    text = clean_text(value).replace(",", "")
    match = re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    if "." in text:
        return float(text)
    return int(text)


def percent_number(value: str) -> float | None:
    match = re.search(r"([-+]?\d+(?:\.\d+)?)\s*%", clean_text(value))
    return float(match.group(1)) if match else None


def numeric_tokens(value: str) -> list[float | int]:
    tokens: list[float | int] = []
    for raw in re.findall(r"(?<![\w.])[-+]?\d+(?:,\d{3})*(?:\.\d+)?", clean_text(value)):
        raw = raw.replace(",", "")
        tokens.append(float(raw) if "." in raw else int(raw))
    return tokens


def extract_balanced(text: str, start: int) -> str | None:
    """Return a balanced JSON object/array beginning at *start*."""
    if start >= len(text) or text[start] not in "[{":
        return None
    opening = text[start]
    closing = "]" if opening == "[" else "}"
    depth = 0
    quote: str | None = None
    escaped = False
    for pos in range(start, len(text)):
        char = text[pos]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return text[start : pos + 1]
    return None


def extract_json_after(text: str, marker: str, start_at: int = 0) -> tuple[Any, int] | None:
    marker_pos = text.find(marker, start_at)
    if marker_pos < 0:
        return None
    bracket_positions = [
        pos for pos in (text.find("[", marker_pos + len(marker)), text.find("{", marker_pos + len(marker))) if pos >= 0
    ]
    if not bracket_positions:
        return None
    start = min(bracket_positions)
    literal = extract_balanced(text, start)
    if literal is None:
        return None
    try:
        return json.loads(literal), start + len(literal)
    except json.JSONDecodeError:
        return None


def extract_all_json_after(text: str, marker: str) -> list[Any]:
    values: list[Any] = []
    cursor = 0
    while True:
        result = extract_json_after(text, marker, cursor)
        if result is None:
            break
        value, cursor = result
        values.append(value)
    return values


def query_slug(url: str, fallback: str = "page") -> str:
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if not params:
        leaf = Path(parsed.path.rstrip("/")).name
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", leaf or fallback).strip("_") or fallback
    pieces = []
    for key, value in params:
        safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", key).strip("_")
        safe_value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
        pieces.append(f"{safe_key}_{safe_value}" if safe_value else safe_key)
    result = "__".join(pieces)
    return result[:180] or fallback


def round_from_url(url: str) -> int | None:
    match = re.search(r"/v(\d+)(?:/|$)", urllib.parse.urlparse(url).path)
    return int(match.group(1)) if match else None


def same_round_url(url: str, round_no: int) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.hostname == "touhou.vote" and round_from_url(url) == round_no


def extract_links(text: str, base_url: str) -> list[str]:
    raw_links: list[str] = []
    patterns = [
        r"\bhref\s*=\s*[\"']([^\"']+)[\"']",
        r"\blocation\.href\s*=\s*[\"']([^\"']+)[\"']",
        r"\bwindow\.location\.href\s*=\s*[\"']([^\"']+)[\"']",
    ]
    for pattern in patterns:
        raw_links.extend(re.findall(pattern, text, re.I))
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_links:
        raw = html.unescape(raw).replace("\\/", "/")
        if raw.startswith(("#", "javascript:", "mailto:")):
            continue
        absolute = urllib.parse.urljoin(base_url, raw)
        parsed = urllib.parse.urlsplit(absolute)
        absolute = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
        if absolute not in seen:
            seen.add(absolute)
            result.append(absolute)
    return result


class TableHTMLParser(HTMLParser):
    """Small dependency-free HTML table/headings extractor."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict[str, Any]] = []
        self._table_stack: list[dict[str, Any]] = []
        self._heading_tag: str | None = None
        self._heading_parts: list[str] = []
        self.last_heading = ""
        self.headings: list[dict[str, str]] = []
        self._cell: dict[str, Any] | None = None
        self._cell_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {key: value or "" for key, value in attrs}
        if re.fullmatch(r"h[1-6]", tag):
            self._heading_tag = tag
            self._heading_parts = []
        elif tag == "table":
            table = {
                "index": len(self.tables),
                "heading": self.last_heading,
                "id": attr_dict.get("id", ""),
                "class": attr_dict.get("class", ""),
                "rows": [],
            }
            self.tables.append(table)
            self._table_stack.append(table)
        elif tag == "tr" and self._table_stack:
            self._table_stack[-1]["rows"].append([])
        elif tag in {"td", "th"} and self._table_stack:
            if not self._table_stack[-1]["rows"]:
                self._table_stack[-1]["rows"].append([])
            self._cell = {
                "tag": tag,
                "colspan": int(attr_dict.get("colspan") or 1),
                "rowspan": int(attr_dict.get("rowspan") or 1),
            }
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._heading_tag is not None:
            self._heading_parts.append(data)
        if self._cell is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == self._heading_tag:
            heading = clean_text("".join(self._heading_parts))
            if heading:
                self.last_heading = heading
                self.headings.append({"level": tag, "text": heading})
            self._heading_tag = None
            self._heading_parts = []
        elif tag in {"td", "th"} and self._cell is not None and self._table_stack:
            self._cell["text"] = clean_text("".join(self._cell_parts))
            self._table_stack[-1]["rows"][-1].append(self._cell)
            self._cell = None
            self._cell_parts = []
        elif tag == "table" and self._table_stack:
            self._table_stack.pop()


def parse_html_tables(text: str) -> dict[str, Any]:
    parser = TableHTMLParser()
    try:
        parser.feed(text)
    except Exception as exc:  # malformed legacy markup should not stop the crawl
        parse_error = f"{type(exc).__name__}: {exc}"
    else:
        parse_error = ""
    for table in parser.tables:
        for row in table["rows"]:
            for cell in row:
                value = cell.get("text", "")
                cell["number"] = scalar_number(value)
                cell["percent"] = percent_number(value)
                cell["numeric_tokens"] = numeric_tokens(value)
    return {
        "headings": parser.headings,
        "tables": parser.tables,
        "parse_error": parse_error,
    }


def tables_to_long_rows(parsed: Mapping[str, Any], source: str) -> Iterator[dict[str, Any]]:
    for table in parsed.get("tables", []):
        for row_index, row in enumerate(table.get("rows", [])):
            for cell_index, cell in enumerate(row):
                yield {
                    "source": source,
                    "table_index": table.get("index"),
                    "table_heading": table.get("heading", ""),
                    "table_id": table.get("id", ""),
                    "row_index": row_index,
                    "cell_index": cell_index,
                    "cell_type": cell.get("tag", ""),
                    "text": cell.get("text", ""),
                    "number": cell.get("number"),
                    "percent": cell.get("percent"),
                    "numeric_tokens": json.dumps(cell.get("numeric_tokens", []), ensure_ascii=False),
                }


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fieldnames: Sequence[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f".{path.name}.{threading.get_ident()}.part")
    count = 0
    with part.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    os.replace(part, path)
    return count


def unwrap_footable(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def flatten_summary_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: unwrap_footable(value) for key, value in record.items()}


def union_fieldnames(rows: Sequence[Mapping[str, Any]], preferred: Sequence[str] = ()) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for key in preferred:
        if any(key in row for row in rows):
            keys.append(key)
            seen.add(key)
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


@dataclass(frozen=True)
class FetchJob:
    round_no: int
    url: str
    target: Path
    method: str = "GET"
    form: tuple[tuple[str, str], ...] = ()
    expect: str = "bytes"  # bytes, html, json, js
    storage_encoding: str = ""  # empty or gzip (lossless raw-response storage)
    optional: bool = False
    label: str = ""


@dataclass
class FetchResult:
    job: FetchJob
    ok: bool
    skipped: bool = False
    # ``skipped`` traditionally means a hash-validated HTTP cache hit.  Keep a
    # separate bit for a validated local workbook substitution so callers,
    # counters, and coverage never confuse the two provenance classes.
    local_substitute: bool = False
    status: int | None = None
    error: str = ""
    bytes_count: int = 0
    transient: bool = False
    # ``fetch_one`` may absorb a transient 504/transport error and then return
    # a successful response.  This is still useful evidence that the host was
    # unhealthy: it must restart the acceleration health window, but must not
    # permanently lower the operating point by itself.
    transient_recovered: bool = False


def is_transient_network_exception(exc: BaseException) -> bool:
    """Classify retryable transport failures without hiding data/IO errors."""

    return isinstance(
        exc,
        (TimeoutError, ConnectionError, urllib.error.URLError, BrokenPipeError),
    )


@dataclass
class RoundState:
    round_no: int
    sources: dict[str, str] = field(default_factory=dict)
    page_files: set[Path] = field(default_factory=set)
    summary_files: dict[str, set[Path]] = field(default_factory=dict)
    questionnaire_file: Path | None = None
    detail_ids: dict[str, set[str]] = field(default_factory=dict)
    details: dict[str, dict[str, Path]] = field(default_factory=dict)
    modern_simple_files: dict[str, Path] = field(default_factory=dict)
    questionnaire_groups: dict[str, list[str]] = field(default_factory=dict)
    questionnaire_defs: list[dict[str, Any]] = field(default_factory=list)
    hob_tokens: list[str] = field(default_factory=list)
    expected_crossvote: dict[str, dict[str, str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    local_substitutions: list[dict[str, Any]] = field(default_factory=list)

    def add_summary(self, category: str, path: Path) -> None:
        self.page_files.add(path)
        self.summary_files.setdefault(category, set()).add(path)

    def add_detail(self, category: str, item_id: str, path: Path) -> None:
        self.detail_ids.setdefault(category, set()).add(item_id)
        self.details.setdefault(category, {})[item_id] = path


class Crawler:
    def __init__(
        self,
        *,
        rounds: Sequence[int],
        workers: int,
        refresh: bool,
        no_item_apis: bool,
        max_items: int | None,
        retries: int,
        timeout: int,
        delay: float,
        batch_size: int,
        batch_pause: float,
        transient_failure_threshold: int,
        import_existing_temp: bool,
        supplemental_only: bool,
        advanced_only: bool,
        advanced_stage: str,
        rebuild_only: bool,
        reuse_local_workbooks: bool = False,
        adaptive_tuning: bool | None = None,
        worker_ceiling: int | None = None,
        request_limit_ceiling: int | None = None,
        batch_pause_ceiling: float | None = None,
    ) -> None:
        self.worker_ceiling = int(
            _configured_ceiling(
                worker_ceiling,
                env_name=ENV_WORKER_CEILING,
                default=DEFAULT_WORKER_CEILING,
                absolute=ABSOLUTE_MAX_WORKERS,
                integer=True,
            )
        )
        self.request_limit_ceiling = int(
            _configured_ceiling(
                request_limit_ceiling,
                env_name=ENV_REQUEST_LIMIT_CEILING,
                default=DEFAULT_REQUEST_LIMIT_CEILING,
                absolute=ABSOLUTE_MAX_BATCH_REQUESTS,
                integer=True,
            )
        )
        self.batch_pause_ceiling = float(
            _configured_ceiling(
                batch_pause_ceiling,
                env_name=ENV_BATCH_PAUSE_CEILING,
                default=DEFAULT_BATCH_PAUSE_CEILING,
                absolute=ABSOLUTE_MAX_BATCH_PAUSE_SECONDS,
                integer=False,
            )
        )
        if not 1 <= workers <= self.worker_ceiling:
            raise ValueError(
                f"workers must be between 1 and configured worker ceiling "
                f"{self.worker_ceiling}"
            )
        if not 1 <= batch_size <= self.request_limit_ceiling:
            raise ValueError(
                "batch_size/request_limit must be between 1 and configured "
                f"request-limit ceiling {self.request_limit_ceiling}"
            )
        if not 0 <= batch_pause <= self.batch_pause_ceiling:
            raise ValueError(
                "batch_pause must be between 0 and configured batch-pause "
                f"ceiling {self.batch_pause_ceiling:g}"
            )
        self.rounds = list(rounds)
        self.workers = workers
        self.refresh = refresh
        self.no_item_apis = no_item_apis
        self.max_items = max_items
        self.retries = retries
        self.timeout = timeout
        # Kept only for compatibility with older direct invocations.  Request
        # pacing is count-based now: ``batch_size`` is exposed as
        # ``--request-limit`` and ``workers`` caps in-flight requests.
        self.delay = 0.0
        self.batch_size = int(batch_size)
        self.batch_pause = float(batch_pause)
        # Adaptive controller: ``workers`` is the configured starting point,
        # while these values move down quickly after upstream saturation and
        # climb one step at a time after a stable run of completed results,
        # never exceeding the program-level ten-worker guard.
        self.adaptive_workers = self.workers
        self.adaptive_batch_pause = self.batch_pause
        self.adaptive_worker_ceiling = self.worker_ceiling
        # Highest concurrency proven safe for this queue stage.  A transient
        # failure at N permanently lowers this probe ceiling to N-1 until the
        # operator changes the configured guardrail.
        self.adaptive_safe_worker_ceiling = self.worker_ceiling
        # The request budget currently is not itself auto-increased, but keep
        # its configured ceiling in state/profile for forward compatibility and
        # to make the dashboard's guardrail explicit.
        self.adaptive_request_limit_ceiling = self.request_limit_ceiling
        self.adaptive_pause_ceiling = self.batch_pause_ceiling
        self.adaptive_pause_floor = min(
            MIN_ADAPTIVE_BATCH_PAUSE_SECONDS, self.batch_pause_ceiling
        )
        # Lowest cooldown which has survived a confirmed failure for the
        # current content family.  Successful results may recover down to this
        # point, but never cross back into a speed already shown to overload
        # the host.  A real content boundary resets it below.
        self.adaptive_safe_pause_floor = self.adaptive_pause_floor
        self.adaptive_pause_success_streak = 0
        self.adaptive_pause_rollback = 0.0
        self.adaptive_success_streak = 0
        # Non-persistent health evidence for the current controller epoch.
        # The wall-clock start and count are intentionally reset on every
        # failure, speed/content boundary, restore, and replay transition.
        self.adaptive_healthy_since: float | None = None
        self.adaptive_healthy_epoch: int | None = None
        self.adaptive_epoch_successes = 0
        self.adaptive_recovery_at = 0.0
        self.adaptive_adjustments = 0
        adaptive_started_at = time.monotonic()
        self.adaptive_last_decrease_at = 0.0
        self.adaptive_next_decrease_at = 0.0
        self.adaptive_last_increase_at = adaptive_started_at
        self.adaptive_next_increase_at = (
            adaptive_started_at + ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS
        )
        self.adaptive_next_pause_probe_at = (
            adaptive_started_at + ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS
        )
        # Futures submitted before a throttle change retain their old epoch.
        # Their late failures belong to the same failure wave and must not
        # cause another downshift while they drain.
        self.adaptive_controller_epoch = 0
        self.adaptive_failure_wave_epoch: int | None = None
        # A process restarted after a circuit break must earn substantially
        # more evidence before probing the speed which just failed.  Without
        # this probation, an early success burst could raise 7 workers back to
        # 8 and the next 403/504 repeat the same 8->7 loop indefinitely.
        self.adaptive_restart_probation = False
        # Queue stages get their own learned profile.  Keeping this separate
        # from the user-editable command means a stable speed survives a
        # restart without silently changing the requested starting value in
        # the dashboard.
        self.adaptive_profile_stage_id = os.environ.get(
            "DATA_CRAWL_QUEUE_STAGE_ID", ""
        ).strip()
        self.adaptive_phase = ""
        self.adaptive_replay_active = False
        if adaptive_tuning is None:
            raw_adaptive = os.environ.get("DATA_CRAWL_ADAPTIVE_TUNING", "1")
            self.adaptive_tuning = str(raw_adaptive).strip().lower() not in {
                "0", "false", "no", "off", "disabled",
            }
        else:
            self.adaptive_tuning = bool(adaptive_tuning)
        self.transient_failure_threshold = max(1, transient_failure_threshold)
        self.import_existing_temp = import_existing_temp
        self.supplemental_only = supplemental_only
        self.advanced_only = advanced_only
        self.advanced_stage = advanced_stage
        self.rebuild_only = rebuild_only
        self.reuse_local_workbooks = bool(reuse_local_workbooks)
        self._lock = threading.RLock()
        # When the controller reaches one worker, an inter-*batch* pause after
        # 30 completed jobs is too late to protect the host.  This independent
        # lock spaces actual HTTP starts, including retries inside fetch_one.
        self._adaptive_request_gate_lock = threading.Lock()
        self._adaptive_last_request_start_at: float | None = None
        # A raw transient seen by any worker briefly gates *all* subsequent
        # request starts, including retries.  This is process-local and never
        # persisted; it gives the upstream one shared recovery window instead
        # of letting each worker immediately issue its own retry burst.
        self.adaptive_transient_recovery_gate_until = 0.0
        self.records: dict[str, dict[str, Any]] = {}
        # Coverage metadata is always global for rounds 1--9 even when a
        # resumable run fetches only one selected round.
        self.states: dict[int, RoundState] = {
            number: RoundState(number) for number in range(1, 10)
        }
        self.downloaded = 0
        self.skipped = 0
        self.local_substituted = 0
        self.failed = 0
        self.exit_ok = True
        self.circuit_open = False
        self.circuit_reason = ""
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        METADATA_ROOT.mkdir(parents=True, exist_ok=True)
        self._load_manifest_records()
        self.local_source_validation = validate_local_workbooks()
        # Keep historical workbook evidence separate from substitutions used
        # by this process.  Loading an old row into the active set made a
        # later ordinary/refresh run report local_source_used even when it
        # fetched the official resource this time.
        self.local_substitution_history: dict[str, dict[str, Any]] = {}
        self.local_substitution_records: dict[str, dict[str, Any]] = {}
        self._load_local_source_manifest()
        if self.reuse_local_workbooks and not self.local_source_validation.get("valid"):
            print(
                "[local workbook reuse] disabled: "
                + "; ".join(
                    f"{category}: {', '.join(str(item) for item in value.get('errors', [])) or 'invalid sheets'}"
                    for category, value in self.local_source_validation.get("sources", {}).items()
                    if not value.get("valid")
                ),
                file=sys.stderr,
                flush=True,
            )
        self._write_local_source_manifest()
        self._restore_adaptive_state()
        if self.import_existing_temp:
            self.import_temp_artifacts()

    def _load_local_source_manifest(self) -> None:
        """Load history, activating it only for an offline reconstruction.

        A normal crawl starts with no active substitutions and records one
        only when it actually omits a request.  This prevents a prior run's
        omission from making a later network/refresh run look workbook-backed.
        The rebuild-only stage has no request phase, so it may activate valid
        historical omissions in order to preserve coverage provenance.
        """

        self.local_substitution_records = {}
        self.local_substitution_history = {}
        try:
            payload = json.loads(LOCAL_SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return
        if not isinstance(payload, Mapping):
            return
        records = payload.get("substitutions", [])
        if not isinstance(records, list):
            return
        for record in records:
            if not isinstance(record, Mapping):
                continue
            key = str(record.get("record_key", ""))
            if key:
                self.local_substitution_history[key] = dict(record)

        # Reuse is deliberately opt-in for every network run.  Rebuild-only
        # is the sole exception because it cannot rediscover omitted pages.
        if not bool(getattr(self, "reuse_local_workbooks", False)):
            return
        if not bool(getattr(self, "rebuild_only", False)):
            return
        if not self.local_source_validation.get("valid"):
            return
        for key, record in self.local_substitution_history.items():
            if self._historical_substitution_usable(record):
                self.local_substitution_records[key] = dict(record)

    def _historical_substitution_usable(self, record: Mapping[str, Any]) -> bool:
        """Return whether a historical local row still describes an omission."""

        if str(record.get("source_kind", "")) != "local_xlsx":
            return False
        if str(record.get("status", "")) != "available_local_substitute":
            return False
        try:
            round_no = int(record.get("round", 0))
        except (TypeError, ValueError):
            return False
        category = str(record.get("category", ""))
        if category not in LOCAL_WORKBOOK_SPECS or round_no != 1:
            return False
        source = self.local_source_validation.get("sources", {}).get(category)
        if not isinstance(source, Mapping) or not source.get("valid"):
            return False
        # A changed workbook invalidates old omissions; retain the row in
        # history, but never let it affect reconstructed coverage.
        if str(record.get("workbook_sha256", "")) != str(source.get("sha256", "")):
            return False
        sheet = source.get("sheets", {}).get(str(round_no))
        if not isinstance(sheet, Mapping) or not sheet.get("valid"):
            return False
        url = str(record.get("url", ""))
        if not url:
            return False
        target_text = str(record.get("target", ""))
        if not target_text:
            return False
        target = Path(target_text)
        if not target.is_absolute():
            target = WORKSPACE / target
        # Re-run the current narrow URL policy rather than trusting fields in
        # an older/malformed JSON row (for example a round-2 or step-5 URL).
        historical_job = FetchJob(
            round_no=round_no,
            url=url,
            target=target,
            method=str(record.get("method", "GET")),
            expect="html",
            label=str(record.get("label", "")),
        )
        if self._local_substitution_info(historical_job) is None:
            return False
        # An official file that appeared after the omission supersedes the
        # historical local source.
        if target.is_file():
            return False
        return True

    def _write_local_source_manifest(self) -> None:
        validation = getattr(self, "local_source_validation", None)
        if not isinstance(validation, Mapping):
            validation = validate_local_workbooks()
        history = getattr(self, "local_substitution_history", {})
        if not isinstance(history, Mapping):
            history = {}
        active = getattr(self, "local_substitution_records", {})
        if not isinstance(active, Mapping):
            active = {}
        # ``substitutions`` remains the complete append-only evidence for
        # compatibility.  ``active_substitutions`` lets consumers distinguish
        # rows actually used by this process (or by rebuild reconstruction).
        merged = {
            str(key): dict(value)
            for key, value in history.items()
            if isinstance(value, Mapping)
        }
        merged.update(
            {
                str(key): dict(value)
                for key, value in active.items()
                if isinstance(value, Mapping)
            }
        )
        payload = {
            "schema_version": 1,
            "generated_at": utc_now(),
            "purpose": (
                "Validated local workbook substitutions for redundant v1 ranking "
                "views; this is not an HTTP response manifest."
            ),
            "validation": validation,
            "substitutions": sorted(
                merged.values(),
                key=lambda value: (
                    int(value.get("round", 0)),
                    str(value.get("category", "")),
                    str(value.get("url", "")),
                ),
            ),
            "active_substitutions": sorted(
                (dict(value) for value in active.values() if isinstance(value, Mapping)),
                key=lambda value: (
                    int(value.get("round", 0)),
                    str(value.get("category", "")),
                    str(value.get("url", "")),
                ),
            ),
        }
        try:
            write_json_atomic(LOCAL_SOURCE_MANIFEST_PATH, payload)
        except OSError:
            # Provenance is best effort; a failure to write it must never turn a
            # valid HTTP crawl into a false network failure.
            pass

    def _local_workbook_info(self, category: str, round_no: int) -> dict[str, Any] | None:
        if not bool(getattr(self, "reuse_local_workbooks", False)):
            return None
        if bool(getattr(self, "refresh", False)):
            return None
        if round_no not in LOCAL_WORKBOOK_ROUNDS:
            return None
        validation = getattr(self, "local_source_validation", {})
        if not isinstance(validation, Mapping) or not validation.get("valid"):
            return None
        source = validation.get("sources", {}).get(category)
        if not isinstance(source, Mapping):
            return None
        sheet = source.get("sheets", {}).get(str(round_no))
        if not isinstance(sheet, Mapping) or not sheet.get("valid"):
            return None
        spec = LOCAL_WORKBOOK_SPECS.get(category, {})
        return {
            "category": category,
            "round": round_no,
            "sheet": str(round_no),
            "workbook": source.get("path", str(spec.get("path", ""))),
            "workbook_sha256": source.get("sha256", ""),
            "covered_fields": list(source.get("required_headers", spec.get("required_headers", ()))),
            "row_count": int(sheet.get("row_count", 0) or 0),
            "data_row_count": int(sheet.get("data_row_count", 0) or 0),
            "header": list(sheet.get("header", [])),
        }

    def _local_substitution_info(self, job: FetchJob) -> dict[str, Any] | None:
        """Return evidence for a deliberately omitted redundant result view."""

        if job.method.upper() != "GET" or job.expect != "html":
            return None
        if job.round_no != 1:
            return None
        parsed = urllib.parse.urlparse(job.url)
        if parsed.hostname != "touhou.vote" or round_from_url(job.url) != 1:
            return None
        query = urllib.parse.parse_qs(parsed.query)
        category = str(query.get("mod", [""])[0])
        step = str(query.get("step", [""])[0])
        if category not in {"chara", "music"} or step not in LOCAL_REDUNDANT_VARIANT_STEPS:
            return None
        # ``w=2`` is the workbook's published weighted score (total + first).
        # If the site exposes another weight, it is not equivalent and must be
        # fetched.  The old endpoint omits ``w`` for the default only rarely;
        # accept that spelling as the same default but never broader values.
        if step == "4" and str(query.get("w", ["2"])[0]) not in {"", "2"}:
            return None
        workbook = self._local_workbook_info(category, 1)
        if workbook is None:
            return None
        fields_by_step = {
            "2": ["名次", "译名", "票数", "本命数", "本命率"],
            "3": ["名次", "译名", "票数", "本命数", "本命率"],
            "4": ["名次", "译名", "票数", "本命数", "本命率", "本命加权"],
        }
        return {
            **workbook,
            "source_kind": "local_xlsx",
            "status": "available_local_substitute",
            "policy": "redundant_v1_result_variant",
            "variant": f"step={step}" + ("&w=2" if step == "4" else ""),
            "covered_fields": fields_by_step.get(step, workbook["covered_fields"]),
        }

    def _record_local_substitution(self, job: FetchJob, info: Mapping[str, Any]) -> None:
        key = self.record_key(job)
        record = {
            "record_key": key,
            "round": job.round_no,
            "category": info.get("category", ""),
            "url": job.url,
            "method": job.method.upper(),
            "target": display_path(job.target),
            "label": job.label,
            "source_kind": "local_xlsx",
            "status": "available_local_substitute",
            "policy": info.get("policy", "redundant_v1_result_variant"),
            "variant": info.get("variant", ""),
            "workbook": info.get("workbook", ""),
            "workbook_sha256": info.get("workbook_sha256", ""),
            "sheet": info.get("sheet", ""),
            "row_count": info.get("row_count", 0),
            "data_row_count": info.get("data_row_count", 0),
            "covered_fields": list(info.get("covered_fields", [])),
            "header": list(info.get("header", [])),
            "recorded_at": utc_now(),
        }
        self.local_substitution_records[key] = record
        history = getattr(self, "local_substitution_history", None)
        if not isinstance(history, dict):
            history = {}
            self.local_substitution_history = history
        history[key] = dict(record)
        self.local_substituted = int(getattr(self, "local_substituted", 0)) + 1
        self._write_local_source_manifest()

    def _restore_adaptive_state(self) -> None:
        """Carry a conservative speed decision across a stage retry.

        A fresh process must not immediately return to the old concurrency
        after a 504 circuit.  Only state written for this queue stage is
        trusted; monotonic recovery timestamps are intentionally discarded.
        """

        value: Mapping[str, Any] | None = None
        try:
            run_state = json.loads(RUN_STATE_JSON.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            run_state = None
        if isinstance(run_state, Mapping):
            value = run_state
        stage_id = os.environ.get("DATA_CRAWL_QUEUE_STAGE_ID")
        if value is not None and stage_id and value.get("queue_stage_id") not in (None, stage_id):
            value = None
        # A run-state file is the most recent checkpoint for a retry.  If it
        # belongs to another stage (or does not exist after a clean shutdown),
        # use the learned profile from the previous successful attempt.  When
        # the checkpoint only contains an emergency (>3 s) recovery backoff,
        # prefer the saved normal operating point instead.
        profile_candidate: Mapping[str, Any] | None = None
        profile_key = self.adaptive_profile_stage_id
        if profile_key:
            try:
                profiles = json.loads(
                    ADAPTIVE_PROFILE_JSON.read_text(encoding="utf-8")
                )
            except (OSError, ValueError, json.JSONDecodeError):
                profiles = None
            if isinstance(profiles, Mapping):
                profile_values = profiles.get("stages", profiles)
                if isinstance(profile_values, Mapping):
                    candidate = profile_values.get(profile_key)
                    if isinstance(candidate, Mapping):
                        profile_candidate = candidate
        # A run-state checkpoint is the most recent observation, while the
        # profile is the last reusable *normal* operating point.  Do not
        # choose one mapping wholesale: a checkpoint may contain an emergency
        # pause but still have the important worker downshift that must survive
        # the queue retry.  Merge the fields independently instead.
        def _finite_float(mapping: Mapping[str, Any] | None, *keys: str) -> float | None:
            if not isinstance(mapping, Mapping):
                return None
            for key in keys:
                try:
                    candidate = float(mapping.get(key))
                except (TypeError, ValueError):
                    continue
                if math.isfinite(candidate):
                    return candidate
            return None

        def _integer(mapping: Mapping[str, Any] | None, *keys: str) -> int | None:
            if not isinstance(mapping, Mapping):
                return None
            for key in keys:
                try:
                    candidate = int(mapping.get(key))
                except (TypeError, ValueError):
                    continue
                return candidate
            return None

        checkpoint_workers = _integer(value, "adaptive_workers", "workers")
        profile_workers = _integer(
            profile_candidate, "adaptive_workers", "workers"
        )
        checkpoint_pause = _finite_float(
            value, "adaptive_batch_pause_seconds", "batch_pause_seconds"
        )
        profile_pause = _finite_float(
            profile_candidate,
            "adaptive_batch_pause_seconds",
            "batch_pause_seconds",
        )
        checkpoint_pause_ceiling = _finite_float(
            value,
            "adaptive_batch_pause_ceiling_seconds",
            "batch_pause_ceiling_seconds",
        )
        checkpoint_safe_pause_floor = _finite_float(
            value,
            "adaptive_safe_pause_floor_seconds",
        )
        checkpoint_pause_success_streak = _integer(
            value, "adaptive_pause_success_streak"
        )
        profile_pause_success_streak = _integer(
            profile_candidate, "adaptive_pause_success_streak"
        )
        checkpoint_pause_rollback = _finite_float(
            value, "adaptive_pause_rollback"
        )
        profile_pause_rollback = _finite_float(
            profile_candidate, "adaptive_pause_rollback"
        )
        profile_safe_pause_floor = _finite_float(
            profile_candidate,
            "adaptive_safe_pause_floor_seconds",
        )
        # Checkpoints created before configurable rails did not record a
        # ceiling.  Interpret their pause against this invocation's current
        # normal ceiling so a deliberately configured manual/adaptive pause
        # survives a restart instead of being mistaken for emergency state.
        if checkpoint_pause_ceiling is None:
            checkpoint_pause_ceiling = float(
                getattr(self, "batch_pause_ceiling", DEFAULT_BATCH_PAUSE_CEILING)
            )

        checkpoint_is_circuit_recovery = bool(
            isinstance(value, Mapping)
            and str(value.get("stopped_reason") or "").startswith(
                "transient circuit breaker:"
            )
        )

        restored_workers = checkpoint_workers
        if restored_workers is None:
            restored_workers = profile_workers
        if restored_workers is None:
            restored_workers = self.workers

        # A confirmed circuit's emergency pause is authoritative for the same
        # unfinished content, even when it is above the ordinary configurable
        # ceiling.  Older/unconfirmed checkpoints are still clamped so a
        # malformed value cannot silently become a 60-second operating point.
        # If the checkpoint was taken during a faster-pause probe, roll back to
        # the stable value rather than carrying that unconfirmed candidate into
        # a new process.
        if (
            checkpoint_pause is not None
            and checkpoint_pause_rollback is not None
            and checkpoint_pause_rollback > checkpoint_pause + 1e-9
        ):
            checkpoint_pause = checkpoint_pause_rollback
        if (
            profile_pause is not None
            and profile_pause_rollback is not None
            and profile_pause_rollback > profile_pause + 1e-9
        ):
            profile_pause = profile_pause_rollback
        restored_pause = checkpoint_pause
        if restored_pause is None or (
            restored_pause > checkpoint_pause_ceiling
            and not checkpoint_is_circuit_recovery
        ):
            restored_pause = profile_pause
        if restored_pause is None:
            restored_pause = self.batch_pause
        self.adaptive_workers = max(
            1,
            min(
                int(getattr(self, "adaptive_worker_ceiling", MAX_WORKERS)),
                restored_workers,
            ),
        )
        checkpoint_safe_ceiling = _integer(value, "adaptive_safe_worker_ceiling")
        profile_safe_ceiling = _integer(
            profile_candidate, "adaptive_safe_worker_ceiling"
        )
        previous_profile_ceiling = _integer(
            profile_candidate, "configured_worker_ceiling"
        )
        profile_ceiling_changed = (
            previous_profile_ceiling is not None
            and previous_profile_ceiling != self.worker_ceiling
        )
        if profile_ceiling_changed:
            # Raising/lowering the guardrail in the dashboard is an explicit
            # operator decision and starts a fresh safety search.
            restored_safe_ceiling = self.worker_ceiling
        elif profile_safe_ceiling is not None:
            restored_safe_ceiling = profile_safe_ceiling
        else:
            restored_safe_ceiling = checkpoint_safe_ceiling or self.worker_ceiling
        # Migrate older checkpoints that predate the explicit safe-ceiling
        # field: a circuit-stopped attempt's restored worker count is already
        # the last known safe point (the failed probe was one slot higher).
        if (
            checkpoint_safe_ceiling is None
            and not profile_ceiling_changed
            and isinstance(value, Mapping)
            and str(value.get("stopped_reason") or "").startswith(
                "transient circuit breaker:"
            )
            and checkpoint_workers is not None
        ):
            restored_safe_ceiling = min(restored_safe_ceiling, checkpoint_workers)
        self.adaptive_safe_worker_ceiling = max(
            1,
            min(int(self.adaptive_worker_ceiling), int(restored_safe_ceiling)),
        )
        self.adaptive_workers = min(
            self.adaptive_workers,
            self.adaptive_safe_worker_ceiling,
        )
        base_pause_floor = float(
            getattr(
                self,
                "adaptive_pause_floor",
                min(
                    MIN_ADAPTIVE_BATCH_PAUSE_SECONDS,
                    float(
                        getattr(
                            self,
                            "batch_pause_ceiling",
                            MAX_BATCH_PAUSE_SECONDS,
                        )
                    ),
                ),
            )
        )
        maximum_restored_pause = (
            ABSOLUTE_MAX_BATCH_PAUSE_SECONDS
            if checkpoint_is_circuit_recovery
            else float(
                getattr(self, "batch_pause_ceiling", MAX_BATCH_PAUSE_SECONDS)
            )
        )
        restored_pause = max(
            base_pause_floor,
            min(maximum_restored_pause, float(restored_pause)),
        )
        restored_safe_pause_floor = checkpoint_safe_pause_floor
        if restored_safe_pause_floor is None:
            restored_safe_pause_floor = profile_safe_pause_floor
        if restored_safe_pause_floor is None:
            restored_safe_pause_floor = (
                restored_pause if checkpoint_is_circuit_recovery else base_pause_floor
            )
        if profile_ceiling_changed:
            # An explicit guardrail change starts a fresh safety search, just
            # like the worker safe ceiling above.
            restored_safe_pause_floor = base_pause_floor
        self.adaptive_safe_pause_floor = max(
            base_pause_floor,
            min(
                ABSOLUTE_MAX_BATCH_PAUSE_SECONDS,
                float(restored_safe_pause_floor),
            ),
        )
        self.adaptive_batch_pause = max(
            restored_pause,
            self.adaptive_safe_pause_floor,
        )
        if not bool(getattr(self, "adaptive_tuning", True)):
            # Manual mode deliberately ignores a learned profile from an
            # earlier adaptive run; the dashboard's configured values are
            # the effective speed after restart.
            self.adaptive_workers = self.workers
            self.adaptive_batch_pause = self.batch_pause
            self.adaptive_safe_worker_ceiling = self.adaptive_worker_ceiling
            self.adaptive_safe_pause_floor = self.adaptive_pause_floor
            self.adaptive_pause_success_streak = 0
            self.adaptive_pause_rollback = 0.0
        else:
            # Health and probe-candidate evidence is process-local.  A restart
            # begins a fresh 120-second/30-result window and never reuses the
            # previous process's monotonic timestamps or success count.
            self.adaptive_pause_success_streak = 0
            self.adaptive_pause_rollback = 0.0
        self._reset_adaptive_health()
        # The previous process's monotonic clock is meaningless here.  The
        # queue runner's retry backoff is the inter-attempt recovery wait.
        self.adaptive_recovery_at = 0.0
        self.adaptive_transient_recovery_gate_until = 0.0
        # A reduced worker count restored from a failed attempt gets a full
        # settling interval before another downward adjustment is considered.
        # The timestamps themselves are intentionally not persisted because a
        # monotonic value has no meaning in a new process.
        restore_now = time.monotonic()
        # ``monotonic()`` values from the previous process cannot be reused.
        # Start a fresh dwell interval while retaining the count above.
        self.adaptive_next_pause_probe_at = (
            restore_now + ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS
        )
        self.adaptive_last_decrease_at = (
            restore_now if self.adaptive_workers < self.workers else 0.0
        )
        # A new process is a new observation wave.  Do not inherit the old
        # process's failure-wave latch or its monotonic cooldown: doing so
        # prevented a second, necessary downshift after an automatic restart.
        # The reduced worker count and learned pause are still restored.
        self.adaptive_next_decrease_at = 0.0
        self.adaptive_last_increase_at = restore_now
        self.adaptive_next_increase_at = (
            restore_now + ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS
        )
        self.adaptive_success_streak = 0
        self.adaptive_failure_wave_active = False
        self.adaptive_failure_wave_epoch = None
        self._adaptive_last_request_start_at = None
        self.adaptive_phase = (
            str(value.get("adaptive_phase") or value.get("phase") or "")
            if value
            else ""
        )
        replay_marker = value.get("adaptive_replay_active") if value else None
        if isinstance(replay_marker, bool):
            self.adaptive_replay_active = replay_marker
            # Checkpoints written by the first phase-boundary implementation
            # explicitly stored ``false`` even when the phase had failed and
            # still had work remaining.  Such a checkpoint is a restart
            # replay, not a clean phase transition: the runner will walk past
            # cached prefix phases before returning to the unfinished target.
            if (
                not self.adaptive_replay_active
                and isinstance(value, Mapping)
                and bool(value.get("resumable", False))
                and isinstance(value.get("phase_remaining"), (int, float))
                and value.get("phase_remaining", 0) > 0
                and (
                    str(value.get("stopped_reason") or "").startswith(
                        "transient circuit breaker:"
                    )
                    or self.adaptive_safe_worker_ceiling
                    < int(
                        getattr(
                            self,
                            "adaptive_worker_ceiling",
                            getattr(self, "worker_ceiling", MAX_WORKERS),
                        )
                    )
                )
            ):
                self.adaptive_replay_active = True
        else:
            # Older checkpoints did not distinguish cached-prefix replay from
            # a normal phase transition.  A different visible phase or an
            # unfinished phase is the conservative migration signal.
            self.adaptive_replay_active = bool(
                value
                and self.adaptive_phase
                and (
                    value.get("phase") != self.adaptive_phase
                    or (
                        isinstance(value.get("phase_remaining"), (int, float))
                        and value.get("phase_remaining", 0) > 0
                    )
                )
            )
        if self.adaptive_replay_active and not str(
            getattr(self, "adaptive_phase", "") or ""
        ).strip():
            self.adaptive_replay_active = False
        stopped_reason = str(value.get("stopped_reason") or "") if value else ""
        self.adaptive_restart_probation = bool(
            self.adaptive_tuning
            and stopped_reason.startswith("transient circuit breaker:")
        )
        if (
            self.adaptive_workers != self.workers
            or abs(self.adaptive_batch_pause - self.batch_pause) > 0.01
        ):
            print(
                f"[adaptive throttle] restored workers={self.adaptive_workers}; "
                f"cooldown={self.adaptive_batch_pause:.1f}s from prior attempt"
                f"{' (restart probation)' if self.adaptive_restart_probation else ''}",
                flush=True,
            )

    def _persist_adaptive_profile(self) -> None:
        """Persist the latest safe adaptive point for the next queue start.

        The profile is intentionally keyed by queue stage.  A 504 recovery
        point for the large remaining-data stage should not become the start
        speed of the smaller advanced-search stage.  Writes are best effort:
        the ordinary run-state checkpoint remains authoritative if the disk
        is temporarily unavailable.
        """

        key = getattr(self, "adaptive_profile_stage_id", "")
        # Direct command-line runs without a queue stage are intentionally not
        # mixed into the queue's per-stage profile.
        if not key:
            return
        try:
            existing = json.loads(
                ADAPTIVE_PROFILE_JSON.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, json.JSONDecodeError):
            existing = {}
        if not isinstance(existing, Mapping):
            existing = {}
        profiles = existing.get("stages")
        if not isinstance(profiles, Mapping):
            profiles = {}
        # Copy into plain dictionaries so an exotic JSON mapping cannot be
        # mutated while another process is reading the profile.
        profile_map = {str(name): dict(item) for name, item in profiles.items() if isinstance(item, Mapping)}
        current_pause = float(
            getattr(self, "adaptive_batch_pause", self.batch_pause)
        )
        # A faster pause is an unconfirmed probe until its next healthy
        # window completes.  Never carry that candidate across a restart;
        # persist the last known stable point instead.
        pause_rollback = max(
            0.0,
            float(getattr(self, "adaptive_pause_rollback", 0.0)),
        )
        if pause_rollback > current_pause + 1e-9:
            current_pause = pause_rollback
        normal_pause_ceiling = float(
            getattr(self, "batch_pause_ceiling", MAX_BATCH_PAUSE_SECONDS)
        )
        pause_floor = float(
            getattr(self, "adaptive_pause_floor", MIN_ADAPTIVE_BATCH_PAUSE_SECONDS)
        )
        # Keep a normal operating point for future clean starts.  Emergency
        # cooldowns above the ordinary ceiling remain in the run checkpoint;
        # their separately persisted safe floor lets an unfinished same-stage
        # recovery avoid forgetting what already failed.
        profile_pause = min(
            normal_pause_ceiling,
            max(pause_floor, current_pause),
        )
        profile_map[str(key)] = {
            "updated_at": utc_now(),
            "adaptive_workers": int(getattr(self, "adaptive_workers", self.workers)),
            "adaptive_safe_worker_ceiling": int(
                getattr(
                    self,
                    "adaptive_safe_worker_ceiling",
                    getattr(self, "adaptive_worker_ceiling", MAX_WORKERS),
                )
            ),
            "adaptive_batch_pause_seconds": profile_pause,
            "adaptive_safe_pause_floor_seconds": float(
                max(
                    pause_floor,
                    min(
                        ABSOLUTE_MAX_BATCH_PAUSE_SECONDS,
                        max(
                            float(
                                getattr(
                                    self,
                                    "adaptive_safe_pause_floor",
                                    pause_floor,
                                )
                            ),
                            pause_rollback,
                        ),
                    ),
                )
            ),
            "configured_workers": int(self.workers),
            "configured_worker_ceiling": int(self.worker_ceiling),
            "request_limit": int(getattr(self, "batch_size", 0)),
            "request_limit_ceiling": int(
                getattr(
                    self,
                    "adaptive_request_limit_ceiling",
                    getattr(self, "request_limit_ceiling", MAX_BATCH_REQUESTS),
                )
            ),
            "adaptive_worker_ceiling": int(
                getattr(self, "adaptive_worker_ceiling", MAX_WORKERS)
            ),
            "adaptive_batch_pause_ceiling_seconds": float(
                getattr(
                    self,
                    "adaptive_pause_ceiling",
                    getattr(self, "batch_pause_ceiling", MAX_BATCH_PAUSE_SECONDS),
                )
            ),
            "adaptive_pause_floor_seconds": float(
                getattr(self, "adaptive_pause_floor", MIN_ADAPTIVE_BATCH_PAUSE_SECONDS)
            ),
            "adaptive_decrease_min_interval_seconds": ADAPTIVE_DECREASE_MIN_INTERVAL_SECONDS,
            "adaptive_increase_min_interval_seconds": ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS,
            "adaptive_success_window_results": ADAPTIVE_SUCCESS_WINDOW_RESULTS,
            "adaptive_pause_increase_step_seconds": ADAPTIVE_PAUSE_INCREASE_STEP_SECONDS,
            "adaptive_pause_decrease_step_seconds": ADAPTIVE_PAUSE_DECREASE_STEP_SECONDS,
            # Health/candidate evidence is deliberately process-local.  The
            # field names remain for dashboard/backward compatibility, but a
            # fresh process must start with no accumulated recovery credit.
            "adaptive_pause_success_streak": 0,
            "adaptive_pause_rollback": 0.0,
            "adaptive_failure_wave_active": bool(
                getattr(self, "adaptive_failure_wave_active", False)
            ),
        }
        try:
            write_json_atomic(
                ADAPTIVE_PROFILE_JSON,
                {"schema_version": 1, "stages": profile_map},
            )
        except OSError as exc:
            print(
                f"[adaptive throttle] profile save skipped: {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )

    def _reset_adaptive_health(self) -> None:
        """Forget non-persistent acceleration evidence for the current epoch."""

        self.adaptive_healthy_since = None
        self.adaptive_healthy_epoch = None
        self.adaptive_epoch_successes = 0

    def _required_healthy_results(self, current_workers: int) -> int:
        """Return the minimum fresh successes for one recovery decision."""

        return max(
            ADAPTIVE_HEALTHY_MIN_RESULTS,
            4 * max(1, int(current_workers)),
        )

    def _adaptive_persisted_pause(self) -> float:
        """Return the last stable pause, excluding an unconfirmed probe."""

        current = float(
            getattr(self, "adaptive_batch_pause", getattr(self, "batch_pause", 0.0))
        )
        rollback = max(
            0.0,
            float(getattr(self, "adaptive_pause_rollback", 0.0)),
        )
        return rollback if rollback > current + 1e-9 else current

    def _note_transient_recovery_gate(self) -> None:
        """Extend one thread-safe process-wide quiet gate after a raw transient."""

        gate_lock = getattr(self, "_adaptive_request_gate_lock", None)
        if gate_lock is None:
            gate_lock = threading.Lock()
            self._adaptive_request_gate_lock = gate_lock
        with gate_lock:
            now = time.monotonic()
            current_pause = max(
                0.25,
                min(
                    RECOVERY_MAX_WAIT_SECONDS,
                    float(
                        getattr(
                            self,
                            "adaptive_batch_pause",
                            getattr(self, "batch_pause", 0.25),
                        )
                    ),
                ),
            )
            # Keep the shared gate meaningful even before the controller sees
            # the final FetchResult.  A later transient can extend it, but
            # several peers cannot create separate permanent speed changes.
            quiet_seconds = max(RECOVERY_MIN_PAUSE_SECONDS, current_pause)
            previous_until = float(
                getattr(self, "adaptive_transient_recovery_gate_until", 0.0)
            )
            self.adaptive_transient_recovery_gate_until = max(
                previous_until,
                now + min(RECOVERY_MAX_WAIT_SECONDS, quiet_seconds),
            )

    def _adaptive_observe(
        self,
        result: FetchResult,
        *,
        allow_adjustment: bool = True,
        confirmed_failure_wave: bool = False,
        request_epoch: int | None = None,
    ) -> None:
        """Update the bounded speed controller after one network result.

        A transient wave gets one downward adjustment and then a long probe
        gate.  This is deliberately not a per-result AIMD loop: several
        already in-flight requests can all fail while the upstream is down,
        and treating those completions as independent evidence drives the
        controller to one worker before the host has a chance to recover.
        ``request_epoch`` is captured when the HTTP future is submitted.  A
        controller change advances the epoch, so every completion from the
        operating point which just failed becomes immutable drain evidence --
        even when it arrives after the recovery timer.  ``allow_adjustment``
        is false while a circuit is draining; those late completions are
        recorded but cannot alter the controller.
        """

        configured_worker_ceiling = int(
            getattr(
                self,
                "adaptive_worker_ceiling",
                getattr(
                    self,
                    "worker_ceiling",
                    getattr(self, "workers", MAX_WORKERS),
                ),
            )
        )
        worker_ceiling = min(
            configured_worker_ceiling,
            int(
                getattr(
                    self,
                    "adaptive_safe_worker_ceiling",
                    configured_worker_ceiling,
                )
            ),
        )
        current_workers = max(
            1,
            min(worker_ceiling, int(getattr(self, "adaptive_workers", self.workers))),
        )
        current_pause = max(
            0.0,
            float(getattr(self, "adaptive_batch_pause", self.batch_pause)),
        )
        base_pause_floor = float(
            getattr(self, "adaptive_pause_floor", MIN_ADAPTIVE_BATCH_PAUSE_SECONDS)
        )
        safe_pause_floor = max(
            base_pause_floor,
            min(
                ABSOLUTE_MAX_BATCH_PAUSE_SECONDS,
                float(
                    getattr(
                        self,
                        "adaptive_safe_pause_floor",
                        base_pause_floor,
                    )
                ),
            ),
        )
        current_pause = max(current_pause, safe_pause_floor)
        now = time.monotonic()
        controller_epoch = max(
            0,
            int(getattr(self, "adaptive_controller_epoch", 0)),
        )
        observed_epoch = (
            controller_epoch
            if request_epoch is None
            else max(0, int(request_epoch))
        )
        transient = bool(
            not result.ok
            and (
                result.transient
                or result.status in TRANSIENT_HTTP_STATUSES
            )
        )
        if not result.ok and not transient:
            # A semantic/404/parse/disk failure is not a permanent throttle
            # signal, but it still breaks continuous health—even if it is a
            # late completion from an older submission epoch.
            self._reset_adaptive_health()

        # Results which arrive after a circuit has stopped accepting work are
        # only drain data.  In particular, do not let the remaining in-flight
        # 502s apply one downshift each.
        if not allow_adjustment:
            self._reset_adaptive_health()
            return

        # With tuning disabled the configured workers/pause are the manual
        # operating point.  Retries and the circuit breaker still protect the
        # network, but the controller must not silently rewrite the speed the
        # operator selected in the dashboard.
        if not bool(getattr(self, "adaptive_tuning", True)):
            self.adaptive_batch_pause = self.batch_pause
            self.adaptive_success_streak = 0
            self.adaptive_pause_success_streak = 0
            self.adaptive_pause_rollback = 0.0
            self._reset_adaptive_health()
            return

        # From here on the controller is allowed to normalize a malformed
        # checkpoint's pause up to its learned safe floor.
        self.adaptive_batch_pause = current_pause

        if transient:
            # Keep the process-wide request gate active even when a caller
            # supplies a final transient result directly (as the queue tests
            # and dashboard probes do instead of executing ``fetch_one``).
            self._note_transient_recovery_gate()
            self.adaptive_success_streak = 0
            self._reset_adaptive_health()
            # A faster-pause probe is a short experiment.  Any transient
            # response ends the healthy window immediately; the caller below
            # either returns to the last stable point or applies the ordinary
            # additive recovery step.
            self.adaptive_pause_success_streak = 0
            rollback_pause = max(
                0.0,
                float(getattr(self, "adaptive_pause_rollback", 0.0)),
            )
            rollback_active = rollback_pause > current_pause + 1e-9
            gate_until = max(
                float(getattr(self, "adaptive_next_decrease_at", 0.0)),
                float(getattr(self, "adaptive_recovery_at", 0.0)),
            )

            if confirmed_failure_wave:
                # Confirmation is circuit-breaker evidence, not a second
                # throttle observation.  The first transient completion from
                # this submission epoch has already changed both workers and
                # pause.  Confirmation may only lengthen the quiet period;
                # otherwise the same 504 wave changes pause once here and once
                # again when the threshold is reached.
                circuit_wait = max(
                    ADAPTIVE_DECREASE_MIN_INTERVAL_SECONDS,
                    RECOVERY_MIN_PAUSE_SECONDS,
                    min(RECOVERY_MAX_WAIT_SECONDS, current_pause),
                )
                next_probe_at = now + circuit_wait
                self.adaptive_failure_wave_active = True
                self.adaptive_next_decrease_at = max(
                    float(getattr(self, "adaptive_next_decrease_at", 0.0)),
                    next_probe_at,
                )
                self.adaptive_recovery_at = max(
                    float(getattr(self, "adaptive_recovery_at", 0.0)),
                    next_probe_at,
                )
                self.adaptive_next_pause_probe_at = max(
                    float(getattr(self, "adaptive_next_pause_probe_at", 0.0)),
                    now + ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS,
                )
                self.adaptive_next_increase_at = max(
                    float(getattr(self, "adaptive_next_increase_at", 0.0)),
                    now + ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS,
                )
                print(
                    f"[adaptive throttle] confirmed circuit; keep workers="
                    f"{current_workers}, cooldown={current_pause:.2f}s; "
                    f"extend recovery by {circuit_wait:.0f}s",
                    file=sys.stderr,
                    flush=True,
                )
                return

            # Only work genuinely submitted at the current operating point can
            # tune it.  Advancing the wall clock cannot turn a late completion
            # from the failed epoch into a new probe.
            if observed_epoch != controller_epoch:
                return
            failure_wave_epoch = getattr(
                self,
                "adaptive_failure_wave_epoch",
                None,
            )
            if (
                failure_wave_epoch is not None
                and observed_epoch <= int(failure_wave_epoch)
            ):
                return
            # A new epoch alone is not enough: its request must also have been
            # admitted after the recovery gate.  ``refill`` enforces this in
            # production; the explicit guard keeps direct callers safe too.
            if now < gate_until:
                return

            self.adaptive_failure_wave_active = False
            self.adaptive_last_failure_workers = None

            def failure_pause() -> tuple[float, float, bool]:
                """Return the next pause, floor, and whether it rolled back."""

                if rollback_active:
                    # The point immediately before the faster probe already
                    # survived the previous failure wave.  Restore it in one
                    # step instead of adding only 0.5 s to the failed probe.
                    restored = min(
                        ABSOLUTE_MAX_BATCH_PAUSE_SECONDS,
                        max(base_pause_floor, rollback_pause),
                    )
                    return restored, restored, True
                increased = min(
                    ABSOLUTE_MAX_BATCH_PAUSE_SECONDS,
                    max(
                        RECOVERY_MIN_PAUSE_SECONDS,
                        current_pause + ADAPTIVE_PAUSE_INCREASE_STEP_SECONDS,
                    ),
                )
                return increased, max(safe_pause_floor, increased), False

            next_workers = max(1, current_workers - 1)
            self.adaptive_last_failure_workers = current_workers
            # The speed that just failed is no longer considered safe.  This
            # cap is what prevents a success streak from immediately probing
            # 8 again after 8 has already produced a transient failure.
            self.adaptive_safe_worker_ceiling = min(
                int(getattr(self, "adaptive_safe_worker_ceiling", worker_ceiling)),
                next_workers,
            )
            # A final transient failure first returns to a conservative
            # three-second recovery interval, then grows additively on later
            # evidence.  This prevents a success streak which reached 0.25s
            # from responding to a 504 with an ineffective 0.75s pause.
            next_pause, next_safe_pause_floor, rolled_back = failure_pause()
            self.adaptive_workers = next_workers
            self.adaptive_batch_pause = next_pause
            self.adaptive_safe_pause_floor = next_safe_pause_floor
            if rolled_back:
                self.adaptive_pause_rollback = 0.0
            self.adaptive_failure_wave_active = True
            self.adaptive_failure_wave_epoch = observed_epoch
            self.adaptive_controller_epoch = controller_epoch + 1
            self.adaptive_last_decrease_at = now
            next_probe_at = now + max(
                ADAPTIVE_DECREASE_MIN_INTERVAL_SECONDS,
                RECOVERY_MIN_PAUSE_SECONDS,
                min(RECOVERY_MAX_WAIT_SECONDS, next_pause),
            )
            self.adaptive_next_decrease_at = next_probe_at
            self.adaptive_recovery_at = max(
                float(getattr(self, "adaptive_recovery_at", 0.0)),
                next_probe_at,
            )
            self.adaptive_next_pause_probe_at = max(
                float(getattr(self, "adaptive_next_pause_probe_at", 0.0)),
                now + ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS,
            )
            # An outage invalidates any success streak that might otherwise
            # immediately restore concurrency after the first probe succeeds.
            self.adaptive_next_increase_at = max(
                float(getattr(self, "adaptive_next_increase_at", 0.0)),
                now + ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS,
            )
            changed = next_workers != current_workers or next_pause != current_pause
            self.adaptive_adjustments = int(
                getattr(self, "adaptive_adjustments", 0)
            ) + int(changed)
            print(
                f"[adaptive throttle] transient={result.status or 'transport'}; "
                f"workers {current_workers}->{next_workers}; "
                f"cooldown={next_pause:.2f}s; next probe in "
                f"{max(0.0, next_probe_at - now):.0f}s",
                file=sys.stderr,
                flush=True,
            )
            return

        # Successes from the operating point which has already been replaced
        # must not bank recovery credit or undo the just-applied downshift.
        if observed_epoch != controller_epoch:
            return

        if not result.ok:
            # Semantic/blocked responses do not earn a speed increase and do
            # not close an active transient wave.
            self.adaptive_success_streak = 0
            self.adaptive_pause_success_streak = 0
            self._reset_adaptive_health()
            return

        # A transient which was absorbed by ``fetch_one`` and followed by a
        # successful response is not a permanent slowdown signal.  It does,
        # however, invalidate the continuous-health window for acceleration.
        if bool(getattr(result, "transient_recovered", False)):
            self.adaptive_success_streak = 0
            self.adaptive_pause_success_streak = 0
            self._reset_adaptive_health()
            return

        # Count only successes submitted in the live controller epoch.  The
        # first one starts a fresh continuous-health clock; a later epoch can
        # never spend evidence banked before its speed boundary.
        if getattr(self, "adaptive_healthy_epoch", None) != controller_epoch:
            self.adaptive_healthy_epoch = controller_epoch
            self.adaptive_healthy_since = now
            self.adaptive_epoch_successes = 0
        self.adaptive_epoch_successes = int(
            getattr(self, "adaptive_epoch_successes", 0)
        ) + 1
        self.adaptive_success_streak = self.adaptive_epoch_successes

        # Cooldown recovery shares the same two-part health requirement as
        # worker recovery.  The probe has its own rollback point and therefore
        # cannot make a transient failure erase the last known stable point.
        if current_workers == 1:
            self.adaptive_pause_success_streak = int(
                getattr(self, "adaptive_pause_success_streak", 0)
            ) + 1
        else:
            # The singleton probe represents request-start pacing.  Do not
            # bank a streak while parallel workers are active and then spend
            # it all at once if concurrency later falls to one.
            self.adaptive_pause_success_streak = 0
        # ``adaptive_safe_pause_floor`` is the value being tested downwards;
        # using it as the probe floor would permanently lock an emergency
        # cooldown (for example 15 s) in place.  Only the configured base
        # floor is immutable for this recovery experiment.
        pause_probe_floor = base_pause_floor
        pause_probe_window = self._required_healthy_results(current_workers)
        pause_probe_due = now >= float(
            getattr(self, "adaptive_next_pause_probe_at", 0.0)
        )
        healthy_since = getattr(self, "adaptive_healthy_since", None)
        healthy_seconds = (
            now - float(healthy_since)
            if healthy_since is not None
            else 0.0
        )
        pause_probe_changed = False
        if (
            current_workers == 1
            and current_pause > pause_probe_floor + 1e-9
            and self.adaptive_pause_success_streak >= pause_probe_window
            and healthy_seconds >= ADAPTIVE_HEALTHY_MIN_SECONDS
            and pause_probe_due
        ):
            # Keep every pause recovery step on the conservative quarter-
            # second grid.  The old proportional singleton probe could jump
            # several seconds at once and made a long cooldown disappear too
            # quickly after a restart.
            quantized_step = ADAPTIVE_PAUSE_DECREASE_STEP_SECONDS
            next_pause = max(
                pause_probe_floor,
                current_pause - quantized_step,
            )
            next_pause = round(
                math.floor((next_pause + 1e-9) / 0.25) * 0.25,
                2,
            )
            next_pause = max(pause_probe_floor, next_pause)
            if next_pause < current_pause - 1e-9:
                probe_from_pause = current_pause
                self.adaptive_pause_rollback = current_pause
                self.adaptive_batch_pause = next_pause
                self.adaptive_safe_pause_floor = next_pause
                current_pause = next_pause
                self.adaptive_pause_success_streak = 0
                # This healthy window was spent on the pause dimension.  Do
                # not reuse it to raise concurrency on the very next result.
                self.adaptive_success_streak = 0
                self._reset_adaptive_health()
                pause_probe_changed = True
                self.adaptive_next_pause_probe_at = (
                    now + ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS
                )
                self.adaptive_last_increase_at = now
                self.adaptive_next_increase_at = max(
                    float(getattr(self, "adaptive_next_increase_at", 0.0)),
                    now + ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS,
                )
                self.adaptive_adjustments = int(
                    getattr(self, "adaptive_adjustments", 0)
                ) + 1
                self.adaptive_controller_epoch = controller_epoch + 1
                print(
                    f"[adaptive throttle] stable pause window={pause_probe_window}; "
                    f"cooldown probe {probe_from_pause:.2f}s->{next_pause:.2f}s; "
                    f"rollback={probe_from_pause:.2f}s",
                    flush=True,
                )
                # Let the newly faster singleton interval earn its own dwell
                # before considering a separate concurrency increase.
                return
            else:
                self.adaptive_pause_rollback = 0.0
                self.adaptive_pause_success_streak = 0

        success_window = self._required_healthy_results(current_workers)
        healthy_since = getattr(self, "adaptive_healthy_since", None)
        healthy_seconds = (
            now - float(healthy_since)
            if healthy_since is not None
            else 0.0
        )
        if (
            self.adaptive_success_streak < success_window
            or healthy_seconds < ADAPTIVE_HEALTHY_MIN_SECONDS
        ):
            return
        # Keep the earned stable evidence while the dwell timer is active. A
        # single result after the timer expires can then make the next small
        # step; a restart probation deliberately requires four such windows.
        if now < float(getattr(self, "adaptive_next_increase_at", 0.0)):
            return

        self.adaptive_success_streak = 0
        self._reset_adaptive_health()
        self.adaptive_failure_wave_active = False
        self.adaptive_restart_probation = False
        next_workers = current_workers
        if current_workers < worker_ceiling:
            next_workers = current_workers + 1
            self.adaptive_workers = next_workers
        pause_floor = max(
            base_pause_floor,
            float(
                getattr(
                    self,
                    "adaptive_safe_pause_floor",
                    base_pause_floor,
                )
            ),
        )
        if current_workers != 1:
            # Parallel workers use the same health window and a deliberately
            # conservative quarter-second recovery step.  Unlike the
            # singleton 20% probe, this may lower an old emergency safe floor
            # or it would remain permanently locked.
            pause_floor = base_pause_floor
        next_pause = current_pause
        if (
            current_pause > pause_floor
            and not pause_probe_changed
            and next_workers == current_workers
        ):
            previous_pause = current_pause
            next_pause = max(
                pause_floor,
                current_pause - ADAPTIVE_PAUSE_DECREASE_STEP_SECONDS,
            )
            self.adaptive_batch_pause = next_pause
            self.adaptive_safe_pause_floor = max(
                base_pause_floor,
                next_pause,
            )
            self.adaptive_pause_rollback = previous_pause
        self.adaptive_last_increase_at = now
        self.adaptive_next_increase_at = (
            now + ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS
        )
        changed = next_workers != current_workers or next_pause != current_pause
        self.adaptive_adjustments = int(
            getattr(self, "adaptive_adjustments", 0)
        ) + int(changed)
        if changed:
            self._reset_adaptive_health()
            self.adaptive_controller_epoch = controller_epoch + 1
        if changed:
            print(
                f"[adaptive throttle] stable={success_window} results; "
                f"workers={next_workers}; cooldown={next_pause:.2f}s; "
                f"next increase in {ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS:.0f}s",
                flush=True,
            )

    def import_temp_artifacts(self) -> None:
        """Promote already downloaded official probes into the formal raw layer.

        These files were downloaded earlier in the same audit.  Reusing them avoids
        needless requests when the archived PHP backend is returning 504.
        """
        specs: list[tuple[str, int, str, str, str, str]] = []

        def add(name: str, number: int, url: str, relative: str, expect: str, label: str) -> None:
            specs.append((name, number, url, relative, expect, label))

        for number in range(1, 10):
            add(f".tmp_cn_v{number}_root.html", number, BASE.format(round_no=number), "pages/root.html", "html", "round root")

        # Round 2 detail probes that were not necessarily reached by the interrupted batch.
        add(".tmp_cn_v2_detail_chara1.html", 2, "https://touhou.vote/v2/?m=j&t=1&i=1", "details/chara/1.html", "html", "chara detail")
        add(".tmp_cn_v2_detail_music1.html", 2, "https://touhou.vote/v2/?m=j&t=2&i=1", "details/music/1.html", "html", "music detail")
        add(".tmp_cn_v2_detail_work1.html", 2, "https://touhou.vote/v2/?m=j&t=3&i=1", "details/work/1.html", "html", "work detail")
        add(".tmp_cn_v2_detail_cp1.html", 2, "https://touhou.vote/v2/?m=j&t=4&i=1", "details/work_characters/1.html", "html", "work_characters detail")

        # Round 4 result subpages and representative details.
        for category in ("chara", "music", "work", "cp", "paper"):
            add(f".tmp_cn_v4_{category}.html", 4, f"https://touhou.vote/v4/?m={category}", f"pages/{category}/index.html", "html", f"{category} index")
        for category, variants in {
            "chara": ("simple", "full", "paper"),
            "music": ("simple", "full", "paper"),
            "work": ("simple", "full", "game", "chara"),
        }.items():
            for variant in variants:
                add(
                    f".tmp_cn_v4_{category}_{variant}.html",
                    4,
                    f"https://touhou.vote/v4/?m={category}&t={variant}",
                    f"pages/{category}/m_{category}__t_{variant}.html",
                    "html",
                    f"{category} result variant",
                )
        for category, item_id, filename in (
            ("chara", "1", ".tmp_cn_v4_detail_chara1.html"),
            ("music", "1", ".tmp_cn_v4_detail_music1.html"),
            ("work", "1", ".tmp_cn_v4_detail_work1.html"),
            ("cp", "2", ".tmp_cn_v4_detail_cp2.html"),
        ):
            add(filename, 4, f"https://touhou.vote/v4/?v=json&m={category}&i={item_id}", f"details/{category}/{item_id}.html", "html", f"{category} detail")

        # Modern round scripts already obtained during interface discovery.
        for number in range(5, 10):
            add(f".tmp_cn_v{number}_paperinfo.js", number, f"https://touhou.vote/v{number}/js/paperinfo.js", "scripts/paperinfo.js", "js", "questionnaire API client")
        add(".tmp_cn_v5_info.js", 5, "https://touhou.vote/v5/js/info.js", "scripts/info.js", "js", "detail API client")
        add(".tmp_cn_v9_infojs.html", 9, "https://touhou.vote/v9/js/info.js", "scripts/info.js", "js", "detail API client")
        for number in (8, 9):
            add(f".tmp_cn_v{number}_crossvote_js.html", number, f"https://touhou.vote/v{number}/js/crossvote.js", "scripts/crossvote.js", "js", "crossvote API client")
            for category in ("chara", "music"):
                add(
                    f".tmp_cn_v{number}_{category}_crossvote.html",
                    number,
                    f"https://touhou.vote/v{number}/?m={category}&type=crossvote",
                    f"pages/{category}/m_{category}__type_crossvote.html",
                    "html",
                    f"{category} crossvote page",
                )

        # Round 5 and 9 complete-list/category probes. Existing formal files win.
        for number in (5, 9):
            for category in ("chara", "music", "work", "cp", "game", "paper"):
                index_probe = legacy_probe_path(
                    f".tmp_cn_v{number}_{category}_root.html"
                )
                if index_probe.exists():
                    add(index_probe.name, number, f"https://touhou.vote/v{number}/?m={category}", f"pages/{category}/index.html", "html", f"{category} index")
                simple_probe = legacy_probe_path(
                    f".tmp_cn_v{number}_{category}_simple.html"
                )
                if simple_probe.exists():
                    add(simple_probe.name, number, f"https://touhou.vote/v{number}/?m={category}&type=simple", f"pages/{category}/m_{category}__type_simple.html", "html", f"{category} simple")
            paper_probe = legacy_probe_path(f".tmp_cn_v{number}_paper.html")
            if paper_probe.exists():
                add(paper_probe.name, number, f"https://touhou.vote/v{number}/?m=paper", "pages/paper/index.html", "html", "paper index")
        for number, category, item_id, filename in (
            (5, "chara", "1", ".tmp_cn_v5_info_chara1.html"),
            (5, "music", "1", ".tmp_cn_v5_info_music1.html"),
            (5, "work", "1", ".tmp_cn_v5_info_work1.html"),
            (5, "cp", "001002000", ".tmp_cn_v5_info_cp.html"),
            (9, "chara", "1", ".tmp_cn_v9_info_chara1.html"),
            (9, "music", "1", ".tmp_cn_v9_info_music1.html"),
            (9, "work", "1", ".tmp_cn_v9_info_work1.html"),
            (9, "cp", "001002000", ".tmp_cn_v9_info_cp.html"),
        ):
            add(
                filename,
                number,
                f"https://touhou.vote/v{number}/?m=info&type={category}&id={item_id}",
                f"details/{category}/{item_id}.html",
                "html",
                f"{category} detail",
            )

        imported = 0
        for filename, number, url, relative, expect, label in specs:
            source = legacy_probe_path(filename)
            target = DATA_ROOT / f"round_{number:02d}" / "raw" / relative
            if not source.is_file() or target.is_file():
                continue
            data = source.read_bytes()
            job = FetchJob(number, url, target, expect=expect, label=label)
            valid, error = self._validate(job, data, "text/html; charset=utf-8" if expect == "html" else "")
            if not valid:
                continue
            write_bytes_atomic(target, data)
            record = {
                "record_key": self.record_key(job),
                "round": number,
                "url": url,
                "method": "GET",
                "request_body_sha256": sha256_bytes(b""),
                "request_form_keys": [],
                "status": 200,
                "success": True,
                "content_type": "text/html; charset=utf-8" if expect == "html" else "application/javascript",
                "bytes": len(data),
                "sha256": sha256_bytes(data),
                "local_path": rel_workspace(target),
                "expect": expect,
                "label": label,
                "retrieved_at": utc_now(),
                "elapsed_seconds": 0,
                "attempt": 0,
                "error": "",
                "imported_from": filename,
            }
            self._append_record(record)
            imported += 1
        print(f"Imported {imported} already-downloaded official temporary artifacts.", flush=True)

    @staticmethod
    def record_key(job: FetchJob) -> str:
        body = urllib.parse.urlencode(list(job.form), doseq=True).encode("utf-8") if job.form else b""
        return "|".join([job.method.upper(), job.url, sha256_bytes(body)])

    @staticmethod
    def source_index_key(job: FetchJob) -> str:
        if job.method.upper() == "GET" and not job.form:
            return job.url
        body = urllib.parse.urlencode(list(job.form), doseq=True).encode("utf-8")
        return (
            f"{job.method.upper()} {job.url} "
            f"body_sha256={sha256_bytes(body)}"
        )

    @staticmethod
    def request_provenance(job: FetchJob) -> dict[str, Any]:
        """Return the complete public request parameters used for a resource.

        The questionnaire POST bodies contain only public question tokens copied
        from the official result page.  Keeping both their ordered key/value pairs
        and the encoded-body hash makes a cached response reproducible; storing
        only the form keys would not be enough to recreate the request.
        """
        parsed = urllib.parse.urlsplit(job.url)
        return {
            "request_query": [
                [key, value]
                for key, value in urllib.parse.parse_qsl(
                    parsed.query, keep_blank_values=True
                )
            ],
            "request_form": [[key, value] for key, value in job.form],
            "request_form_keys": sorted({key for key, _ in job.form}),
        }

    def _load_manifest_records(self) -> None:
        for path in (MANIFEST_PATH, JOURNAL_PATH):
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    key = record.get("record_key")
                    if key:
                        self.records[key] = record

    def _append_record(self, record: Mapping[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
            with JOURNAL_PATH.open("a", encoding="utf-8", newline="") as handle:
                handle.write(line)
            self.records[str(record["record_key"])] = dict(record)

    def _register_source(self, job: FetchJob) -> None:
        state = self.states[job.round_no]
        with self._lock:
            state.sources[self.source_index_key(job)] = rel_workspace(job.target)

    def _existing_is_valid(self, job: FetchJob, record: Mapping[str, Any] | None) -> bool:
        if self.refresh or not job.target.is_file() or job.target.stat().st_size <= 0:
            return False
        if (
            not record
            or record.get("status") != 200
            or record.get("error")
            or record.get("success") is False
        ):
            return False
        if record.get("local_path") != rel_workspace(job.target):
            return False
        if record.get("bytes") != job.target.stat().st_size:
            return False
        try:
            stored = job.target.read_bytes()
            if record.get("sha256") and sha256_bytes(stored) != record.get("sha256"):
                return False
            storage_encoding = (
                record.get("storage_encoding")
                or job.storage_encoding
                or ("gzip" if job.target.suffix == ".gz" else "identity")
            )
            if storage_encoding == "gzip":
                response = gzip.decompress(stored)
            elif storage_encoding == "identity":
                response = stored
            else:
                return False
            if record.get("response_bytes") not in (None, len(response)):
                return False
            if record.get("response_sha256") and sha256_bytes(response) != record.get("response_sha256"):
                return False
            # Revalidate identity files as well as gzip checkpoints.  A 200
            # challenge/error page must never become a permanent valid cache.
            valid, _ = self._validate(
                job, response, str(record.get("content_type", ""))
            )
            if not valid:
                return False
        except (OSError, EOFError, gzip.BadGzipFile):
            return False
        return True

    def _enrich_cached_record(
        self, job: FetchJob, record: Mapping[str, Any] | None
    ) -> None:
        """Backfill reproducible request/raw-response provenance on old cache rows."""
        if record is None:
            return
        provenance = self.request_provenance(job)
        expected_storage = job.storage_encoding or "identity"
        if (
            all(record.get(name) == value for name, value in provenance.items())
            and record.get("storage_encoding") == expected_storage
            and record.get("response_bytes") is not None
            and bool(record.get("response_sha256"))
        ):
            return
        if job.storage_encoding == "gzip":
            try:
                response = gzip.decompress(job.target.read_bytes())
            except (OSError, EOFError, gzip.BadGzipFile):
                return
            provenance.update(
                {
                    "storage_encoding": "gzip",
                    "response_bytes": len(response),
                    "response_sha256": sha256_bytes(response),
                }
            )
        else:
            provenance.update(
                {
                    "storage_encoding": "identity",
                    "response_bytes": job.target.stat().st_size,
                    "response_sha256": sha256_file(job.target),
                }
            )
        if any(record.get(name) != value for name, value in provenance.items()):
            enriched = dict(record)
            enriched.update(provenance)
            enriched["provenance_enriched_at"] = utc_now()
            self._append_record(enriched)

    def _validate(self, job: FetchJob, data: bytes, content_type: str) -> tuple[bool, str]:
        if not data:
            return False, "empty response"
        text = ""
        if job.expect in {"html", "json", "js"}:
            text = decode_body(data, content_type)
        if job.expect == "json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                return False, f"invalid JSON: {exc}"
            if job.label.startswith("advanced questionnaire advice"):
                if not isinstance(payload, dict) or not payload:
                    return False, "advanced catalogue is not a nonempty object"
                if any(
                    not str(key).isdigit()
                    or not isinstance(value, str)
                    or not clean_text(value)
                    for key, value in payload.items()
                ):
                    return False, "advanced catalogue contains an invalid id/name entry"
            elif job.label.startswith("advanced entity catalogue"):
                if not isinstance(payload, dict) or not payload:
                    return False, "advanced catalogue is not a nonempty object"
                if any(
                    not str(key).strip()
                    or not isinstance(value, str)
                    or not clean_text(value)
                    for key, value in payload.items()
                ):
                    return False, "advanced catalogue contains an invalid id/name entry"
            elif job.label.startswith("advanced questionnaire pair"):
                if not isinstance(payload, dict):
                    return False, "advanced questionnaire pair is not an object"
                if payload.get("cross") is True:
                    return True, ""
                pair = payload.get("data")
                if not isinstance(pair, dict):
                    return False, "advanced questionnaire pair lacks its data object"
                item1 = pair.get("item1")
                item2 = pair.get("item2")
                matrix = pair.get("data")
                percent = pair.get("percent")
                percentall = pair.get("percentall")
                if (
                    not isinstance(item1, list)
                    or not item1
                    or not isinstance(item2, list)
                    or not item2
                    or not isinstance(matrix, dict)
                    or not isinstance(percent, dict)
                    or not isinstance(percentall, list)
                    or len(percentall) != len(item2)
                ):
                    return False, "advanced questionnaire pair has an incomplete matrix schema"
                for index in range(len(item2)):
                    matrix_row = matrix.get(str(index))
                    percent_row = percent.get(str(index))
                    reverse_row = percentall[index]
                    if (
                        not isinstance(matrix_row, list)
                        or len(matrix_row) != len(item1)
                        or any(integer_value(value) is None for value in matrix_row)
                        or not isinstance(percent_row, list)
                        or len(percent_row) != len(item1)
                        or not isinstance(reverse_row, list)
                        or len(reverse_row) != len(item1)
                    ):
                        return False, "advanced questionnaire pair matrix dimensions do not match its options"
        elif job.expect == "html":
            lower = text.lower()
            if "<html" not in lower and "<!doctype" not in lower:
                return False, "response is not HTML"
            if "<title>404 not found" in lower or "调用了不存在的内部方法" in text or "<title>载入失败" in text:
                return False, "official page reports unavailable/404"
            challenge_markers = (
                "cf-chl-",
                "challenge-platform",
                "cf-turnstile",
                "checking your browser",
                "just a moment",
                "verify you are human",
                "attention required! | cloudflare",
                "人机验证",
                "安全验证",
                "访问验证",
                "验证码",
            )
            if any(marker in lower for marker in challenge_markers):
                return False, "possible anti-bot challenge page"
            ranking_arrays = extract_all_json_after(text, '"rows":')
            if job.label.startswith((
                "advanced questionnaire condition",
                "advanced entity ",
            )) and not any(isinstance(value, list) for value in ranking_arrays):
                return False, "advanced ranking page lacks a parseable embedded rows array"
            if job.label in {
                "advanced entry chara simple",
                "advanced entry music simple",
            } and not any(
                isinstance(value, list) and bool(value) for value in ranking_arrays
            ):
                return False, "advanced ranking entry page lacks a nonempty rows array"
            if job.label == "advanced entry paper":
                questlist_result = extract_json_after(text, "var questlist =")
                if (
                    questlist_result is None
                    or not isinstance(questlist_result[0], list)
                    or not questlist_result[0]
                ):
                    return False, "advanced questionnaire entry page lacks a nonempty questlist"
        elif job.expect == "js":
            lower = text.lower()
            if (
                "<title>404 not found" in lower
                or lower.lstrip().startswith(("<html", "<!doctype html"))
                or any(
                    marker in lower
                    for marker in (
                        "cf-chl-",
                        "challenge-platform",
                        "cf-turnstile",
                        "checking your browser",
                        "just a moment",
                        "verify you are human",
                        "人机验证",
                        "安全验证",
                        "访问验证",
                        "验证码",
                    )
                )
            ):
                return False, "JavaScript resource is unavailable/404"
        return True, ""

    def _adaptive_request_start_interval(
        self,
        *,
        transient_retry: bool = False,
    ) -> float:
        """Return the live per-request interval for singleton recovery.

        Normal operation remains count-batched.  Once adaptive recovery has
        proven that only one worker is safe, waiting after thirty logical jobs
        is ineffective; every real HTTP attempt must honor the displayed
        cooldown.  ``transient_retry`` also protects the retries of the first
        singleton request, before its final FetchResult reaches the controller.
        """

        if not bool(getattr(self, "adaptive_tuning", True)):
            return 0.0
        configured_ceiling = max(
            1,
            int(
                getattr(
                    self,
                    "adaptive_worker_ceiling",
                    getattr(
                        self,
                        "worker_ceiling",
                        getattr(self, "workers", MAX_WORKERS),
                    ),
                )
            ),
        )
        safe_ceiling = max(
            1,
            min(
                configured_ceiling,
                int(
                    getattr(
                        self,
                        "adaptive_safe_worker_ceiling",
                        configured_ceiling,
                    )
                ),
            ),
        )
        active_workers = max(
            1,
            min(
                safe_ceiling,
                int(getattr(self, "adaptive_workers", getattr(self, "workers", 1))),
            ),
        )
        if active_workers != 1:
            return 0.0
        base_pause_floor = float(
            getattr(self, "adaptive_pause_floor", MIN_ADAPTIVE_BATCH_PAUSE_SECONDS)
        )
        safe_pause_floor = float(
            getattr(self, "adaptive_safe_pause_floor", base_pause_floor)
        )
        degraded = bool(
            transient_retry
            or safe_ceiling < configured_ceiling
            or getattr(self, "adaptive_failure_wave_active", False)
            or getattr(self, "adaptive_restart_probation", False)
            or safe_pause_floor > base_pause_floor + 1e-9
        )
        if not degraded:
            return 0.0
        return max(
            0.0,
            min(
                ABSOLUTE_MAX_BATCH_PAUSE_SECONDS,
                float(
                    getattr(
                        self,
                        "adaptive_batch_pause",
                        getattr(self, "batch_pause", 0.0),
                    )
                ),
            ),
        )

    def _wait_for_adaptive_request_start(
        self,
        *,
        transient_retry: bool = False,
    ) -> None:
        """Space singleton recovery attempts using one process-wide gate."""

        gate_lock = getattr(self, "_adaptive_request_gate_lock", None)
        if gate_lock is None:
            gate_lock = threading.Lock()
            self._adaptive_request_gate_lock = gate_lock
        while True:
            with gate_lock:
                interval = self._adaptive_request_start_interval(
                    transient_retry=transient_retry
                )
                now = time.monotonic()
                previous_value = getattr(
                    self, "_adaptive_last_request_start_at", None
                )
                previous_start = (
                    float(previous_value) if previous_value is not None else None
                )
                previous_target = (
                    previous_start + interval
                    if interval > 0.0 and previous_start is not None
                    else now
                )
                recovery_target = float(
                    getattr(
                        self,
                        "adaptive_transient_recovery_gate_until",
                        0.0,
                    )
                )
                target = max(previous_target, recovery_target)
                wait_seconds = max(0.0, target - now)
                if wait_seconds <= 0.0:
                    self._adaptive_last_request_start_at = now
                    return
                # Reserve this start slot before releasing the lock.  A peer
                # that arrives concurrently will schedule after it instead of
                # issuing a synchronized retry burst.
                self._adaptive_last_request_start_at = target
            time.sleep(wait_seconds)
            after_sleep = time.monotonic()
            with gate_lock:
                current_gate = float(
                    getattr(
                        self,
                        "adaptive_transient_recovery_gate_until",
                        0.0,
                    )
                )
                if after_sleep < target and after_sleep <= now:
                    # Test doubles may make sleep a no-op.  Treat the reserved
                    # slot as elapsed so the direct call cannot spin forever.
                    after_sleep = target
                if after_sleep >= target and after_sleep >= current_gate:
                    self._adaptive_last_request_start_at = after_sleep
                    return

    def fetch_one(self, job: FetchJob) -> FetchResult:
        self._register_source(job)
        key = self.record_key(job)
        with self._lock:
            existing_record = self.records.get(key)
        if self._existing_is_valid(job, existing_record):
            self._enrich_cached_record(job, existing_record)
            with self._lock:
                self.skipped += 1
            return FetchResult(job=job, ok=True, skipped=True, status=200, bytes_count=job.target.stat().st_size)

        body = urllib.parse.urlencode(list(job.form), doseq=True).encode("utf-8") if job.form else None
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/html,application/javascript,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Referer": BASE.format(round_no=job.round_no),
        }
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        last_error = ""
        status: int | None = None
        transient_error = False
        transient_retry_seen = False
        last_attempt = 0
        retry_after_transient = False
        for attempt in range(1, self.retries + 1):
            last_attempt = attempt
            self._wait_for_adaptive_request_start(
                transient_retry=retry_after_transient
            )
            status = None
            transient_error = False
            started = time.monotonic()
            try:
                request = urllib.request.Request(job.url, data=body, method=job.method.upper(), headers=headers)
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    status = response.status
                    content_type = response.headers.get("Content-Type", "")
                    content_encoding = response.headers.get("Content-Encoding", "").lower()
                    data = response.read()
                    if content_encoding == "gzip":
                        data = gzip.decompress(data)
                    elif content_encoding == "deflate":
                        data = zlib.decompress(data)
                valid, validation_error = self._validate(job, data, content_type)
                if status != 200:
                    raise RuntimeError(f"HTTP {status}")
                if not valid:
                    raise RuntimeError(validation_error)
                response_bytes = len(data)
                response_sha256 = sha256_bytes(data)
                if job.storage_encoding == "gzip":
                    stored_data = gzip.compress(data, compresslevel=9, mtime=0)
                else:
                    stored_data = data
                write_bytes_atomic(job.target, stored_data)
                record = {
                    "record_key": key,
                    "round": job.round_no,
                    "url": job.url,
                    "method": job.method.upper(),
                    "request_body_sha256": sha256_bytes(body or b""),
                    **self.request_provenance(job),
                    "status": status,
                    "success": True,
                    "content_type": content_type,
                    "bytes": len(stored_data),
                    "sha256": sha256_bytes(stored_data),
                    "storage_encoding": job.storage_encoding or "identity",
                    "response_bytes": response_bytes,
                    "response_sha256": response_sha256,
                    "local_path": rel_workspace(job.target),
                    "expect": job.expect,
                    "label": job.label,
                    "retrieved_at": utc_now(),
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "attempt": attempt,
                    "error": "",
                }
                self._append_record(record)
                with self._lock:
                    self.downloaded += 1
                return FetchResult(
                    job=job,
                    ok=True,
                    status=status,
                    bytes_count=len(stored_data),
                    transient_recovered=transient_retry_seen,
                )
            except urllib.error.HTTPError as exc:
                status = exc.code
                transient_error = status in TRANSIENT_HTTP_STATUSES or status == 403
                last_error = f"HTTPError {exc.code}: {exc.reason}"
                # urlopen raises HTTPError as a response-like object.  We do
                # not consume its body, so close it explicitly before retrying.
                exc.close()
            except Exception as exc:
                transient_error = bool(
                    is_transient_network_exception(exc)
                    or status in TRANSIENT_HTTP_STATUSES
                    or status == 403
                )
                last_error = f"{type(exc).__name__}: {exc}"
            retry_after_transient = bool(
                transient_error
                or status in TRANSIENT_HTTP_STATUSES
                or status == 403
            )
            if retry_after_transient:
                transient_retry_seen = True
                self._note_transient_recovery_gate()
            if attempt < self.retries:
                # Archived PHP endpoints commonly return 502/503/504 while
                # temporarily saturated; allow the host time to recover.  A
                # 403 is treated as a possible WAF block and is deliberately
                # retried much more slowly instead of being mistaken for a
                # missing official resource.
                if status == 403:
                    if attempt >= min(self.retries, 2):
                        break
                    time.sleep(min(30 * attempt, 180))
                elif transient_error or status in TRANSIENT_HTTP_STATUSES:
                    # Absorb sporadic gateway resets in the request itself.
                    # The old two-attempt cap promoted ordinary blips into a
                    # queue-level circuit break too readily.
                    time.sleep(min(2 ** (attempt - 1), 30))
                else:
                    time.sleep(min(2 ** (attempt - 1), 12))

        failure_record = {
            "record_key": key,
            "round": job.round_no,
            "url": job.url,
            "method": job.method.upper(),
            "request_body_sha256": sha256_bytes(body or b""),
            **self.request_provenance(job),
            "status": status,
            "success": False,
            "content_type": "",
            "bytes": 0,
            "sha256": "",
            "local_path": rel_workspace(job.target),
            "expect": job.expect,
            "storage_encoding": job.storage_encoding or "identity",
            "label": job.label,
            "retrieved_at": utc_now(),
            "attempt": last_attempt or self.retries,
            "error": last_error,
            "transient": transient_error,
            "optional": job.optional,
        }
        self._append_record(failure_record)
        with self._lock:
            self.failed += 1
        if not job.optional:
            print(f"ERROR {job.url}: {last_error}", file=sys.stderr, flush=True)
        return FetchResult(
            job=job,
            ok=False,
            status=status,
            error=last_error,
            transient=transient_error,
        )

    def _begin_network_phase(self, phase: str) -> bool:
        """Reset learned speed when actual network work changes content."""

        if str(getattr(self, "adaptive_phase", "")) == str(phase):
            return False
        self.adaptive_phase = str(phase)
        self.adaptive_replay_active = False
        configured_content_ceiling = int(
            getattr(
                self,
                "adaptive_worker_ceiling",
                getattr(
                    self,
                    "worker_ceiling",
                    getattr(self, "workers", MAX_WORKERS),
                ),
            )
        )
        self.adaptive_safe_worker_ceiling = configured_content_ceiling
        self.adaptive_workers = (
            configured_content_ceiling
            if bool(getattr(self, "adaptive_tuning", True))
            else self.workers
        )
        self.adaptive_batch_pause = self.batch_pause
        self.adaptive_safe_pause_floor = float(
            getattr(
                self,
                "adaptive_pause_floor",
                min(
                    MIN_ADAPTIVE_BATCH_PAUSE_SECONDS,
                    float(
                        getattr(
                            self,
                            "batch_pause_ceiling",
                            MAX_BATCH_PAUSE_SECONDS,
                        )
                    ),
                ),
            )
        )
        self.adaptive_failure_wave_active = False
        self.adaptive_success_streak = 0
        self.adaptive_pause_success_streak = 0
        self.adaptive_pause_rollback = 0.0
        self._reset_adaptive_health()
        self.adaptive_transient_recovery_gate_until = 0.0
        self.adaptive_restart_probation = False
        self.adaptive_last_failure_workers = None
        # A content reset is a new operating point too.  Advancing instead of
        # reusing epoch zero keeps any future cross-boundary drain result
        # harmless even if phase orchestration later becomes asynchronous.
        self.adaptive_controller_epoch = int(
            getattr(self, "adaptive_controller_epoch", 0)
        ) + 1
        self.adaptive_failure_wave_epoch = None
        self.adaptive_recovery_at = 0.0
        self.adaptive_next_decrease_at = 0.0
        self.adaptive_next_pause_probe_at = (
            time.monotonic() + ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS
        )
        self._adaptive_last_request_start_at = None
        self.adaptive_last_increase_at = time.monotonic()
        self.adaptive_next_increase_at = (
            self.adaptive_last_increase_at
            + ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS
        )
        print(
            f"[adaptive throttle] new content={phase!r}; reset workers="
            f"{self.adaptive_workers}; safe ceiling="
            f"{self.adaptive_safe_worker_ceiling}; cooldown="
            f"{self.adaptive_batch_pause:.2f}s",
            flush=True,
        )
        return True

    def _prepare_adaptive_phase(self, phase: str) -> bool:
        """Apply content/replay boundaries and return whether this is a prefix.

        Queue retries can call ``fetch_many`` for cache-only or even empty
        phases.  Keeping this transition independent from the eventual number
        of HTTP jobs prevents a stale replay marker from leaking its safety
        point into the next real content family.
        """

        replay_prefix = False
        replay_active = bool(getattr(self, "adaptive_replay_active", False))
        adaptive_phase = str(getattr(self, "adaptive_phase", "") or "").strip()
        current_phase = str(phase or "").strip()
        if replay_active and not adaptive_phase:
            # Defensive migration for a malformed checkpoint: without a
            # target phase there is no safe way to decide which prefix ends.
            self.adaptive_replay_active = False
            replay_active = False
        if replay_active:
            if current_phase == adaptive_phase:
                # The target has been reached even when every item is already
                # cached.  Clear only gates created by the prefix; preserve the
                # learned worker/pause point and restart probation.
                self.adaptive_replay_active = False
                self.adaptive_failure_wave_active = False
                self.adaptive_last_failure_workers = None
                self.adaptive_failure_wave_epoch = None
                self.adaptive_recovery_at = 0.0
                self.adaptive_next_decrease_at = 0.0
                self.adaptive_success_streak = 0
                self.adaptive_pause_success_streak = 0
                self._reset_adaptive_health()
                self._adaptive_last_request_start_at = None
                self.adaptive_transient_recovery_gate_until = 0.0
                boundary_now = time.monotonic()
                self.adaptive_last_increase_at = boundary_now
                self.adaptive_next_increase_at = (
                    boundary_now + ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS
                )
                self.adaptive_next_pause_probe_at = (
                    boundary_now + ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS
                )
                # Fence late completions from the replayed prefix before the
                # target phase starts earning fresh health evidence.
                self.adaptive_controller_epoch = int(
                    getattr(self, "adaptive_controller_epoch", 0)
                ) + 1
                replay_active = False
            else:
                replay_prefix = True
        if not replay_prefix and not replay_active and adaptive_phase != current_phase:
            # A fully cached/empty phase is still a genuine content boundary
            # after replay has ended.  Reset now so the following network phase
            # starts from the configured ceiling.
            self._begin_network_phase(phase)
        return replay_prefix

    def fetch_many(self, jobs: Sequence[FetchJob], phase: str) -> list[FetchResult]:
        unique: dict[str, FetchJob] = {}
        for job in jobs:
            unique[self.record_key(job)] = job
        jobs = list(unique.values())
        replay_prefix = self._prepare_adaptive_phase(phase)
        if not jobs:
            return []
        if self.circuit_open and not self.rebuild_only:
            print(f"[{phase}] skipped because transient circuit is open: {self.circuit_reason}", file=sys.stderr, flush=True)
            return []
        if self.rebuild_only:
            return [
                FetchResult(job=job, ok=job.target.is_file(), skipped=job.target.is_file(), status=200 if job.target.is_file() else None)
                for job in jobs
            ]

        # Remove validated local substitutions and valid cached resources before
        # batching.  Previously a resume
        # run still created thread pools and slept after batches containing
        # only skips, which made large interrupted crawls unnecessarily slow.
        all_jobs = jobs
        local_results: list[FetchResult] = []
        network_jobs: list[FetchJob] = []
        for job in all_jobs:
            info = self._local_substitution_info(job)
            # Do not hide a pre-existing official file.  If it is present but
            # fails its HTTP manifest check, normal retry/repair remains the
            # safer choice; local reuse is for genuinely omitted requests.
            if info is not None and not job.target.exists():
                self._record_local_substitution(job, info)
                local_results.append(
                    FetchResult(
                        job=job,
                        ok=True,
                        skipped=True,
                        local_substitute=True,
                        status=None,
                    )
                )
            else:
                network_jobs.append(job)
        jobs = network_jobs
        cached_results: list[FetchResult] = []
        pending_jobs: list[FetchJob] = []
        retry_priority: dict[str, int] = {}
        for job in jobs:
            self._register_source(job)
            record_key = self.record_key(job)
            with self._lock:
                existing_record = self.records.get(record_key)
            if self._existing_is_valid(job, existing_record):
                self._enrich_cached_record(job, existing_record)
                cached_results.append(
                    FetchResult(
                        job=job,
                        ok=True,
                        skipped=True,
                        status=200,
                        bytes_count=job.target.stat().st_size,
                    )
                )
            else:
                pending_jobs.append(job)
                # A prior failure, a missing/corrupt previously recorded file,
                # or an untracked partial file is unfinished checkpoint work.
                # Keep those retries stably ahead of never-attempted resources
                # so a resume repairs known gaps before expanding its frontier.
                retry_priority[record_key] = int(
                    existing_record is None and not job.target.exists()
                )
        pending_jobs.sort(
            key=lambda job: retry_priority[self.record_key(job)]
        )
        if cached_results:
            with self._lock:
                self.skipped += len(cached_results)
        print(
            f"[{phase}] {len(all_jobs)} resources; cached={len(cached_results)}, "
            f"local={len(local_results)}, network={len(pending_jobs)}, "
            f"workers={int(getattr(self, 'adaptive_workers', self.workers))}",
            flush=True,
        )
        if not pending_jobs:
            write_json_atomic(
                RUN_STATE_JSON,
                {
                    "updated_at": utc_now(),
                    "pid": os.getpid(),
                    "queue_stage_id": os.environ.get("DATA_CRAWL_QUEUE_STAGE_ID"),
                    "queue_stage_attempt": os.environ.get("DATA_CRAWL_QUEUE_STAGE_ATTEMPT"),
                    "queue_stage_started_at": os.environ.get("DATA_CRAWL_QUEUE_STAGE_STARTED_AT"),
                    "phase": phase,
                    "adaptive_phase": str(getattr(self, "adaptive_phase", "")),
                    "adaptive_replay_active": bool(
                        getattr(self, "adaptive_replay_active", False)
                    ),
                    "phase_total": len(all_jobs),
                    "phase_completed_this_run": len(all_jobs),
                    "phase_remaining": 0,
                    "successful_or_skipped": len(cached_results) + len(local_results),
                    "satisfied_by_local_source": len(local_results),
                    "failed": 0,
                    "stopped_reason": "",
                    "resumable": False,
                    "workers": self.workers,
                    "configured_workers": self.workers,
                    "adaptive_tuning": bool(getattr(self, "adaptive_tuning", True)),
                    "adaptive_worker_ceiling": int(getattr(self, "adaptive_worker_ceiling", MAX_WORKERS)),
                    "adaptive_safe_worker_ceiling": int(getattr(self, "adaptive_safe_worker_ceiling", getattr(self, "adaptive_worker_ceiling", MAX_WORKERS))),
                    "adaptive_workers": int(getattr(self, "adaptive_workers", self.workers)),
                    "request_limit_ceiling": int(getattr(self, "request_limit_ceiling", MAX_BATCH_REQUESTS)),
                    "adaptive_batch_pause_ceiling_seconds": float(getattr(self, "adaptive_pause_ceiling", MAX_BATCH_PAUSE_SECONDS)),
                    "adaptive_pause_floor_seconds": float(getattr(self, "adaptive_pause_floor", MIN_ADAPTIVE_BATCH_PAUSE_SECONDS)),
                    "adaptive_safe_pause_floor_seconds": float(max(getattr(self, "adaptive_safe_pause_floor", getattr(self, "adaptive_pause_floor", MIN_ADAPTIVE_BATCH_PAUSE_SECONDS)), self._adaptive_persisted_pause() if getattr(self, "adaptive_pause_rollback", 0.0) > getattr(self, "adaptive_batch_pause", self.batch_pause) else getattr(self, "adaptive_pause_floor", MIN_ADAPTIVE_BATCH_PAUSE_SECONDS))),
                    "adaptive_batch_pause_seconds": self._adaptive_persisted_pause(),
                     # Health/candidate evidence is intentionally not durable;
                     # a restarted process must earn it again from zero.
                     "adaptive_success_streak": 0,
                     "adaptive_pause_success_streak": 0,
                     "adaptive_pause_rollback": 0.0,
                     "adaptive_next_pause_probe_at": float(getattr(self, "adaptive_next_pause_probe_at", 0.0)),
                     "adaptive_recovery_at": float(getattr(self, "adaptive_recovery_at", 0.0)),
                    "adaptive_last_decrease_at": float(getattr(self, "adaptive_last_decrease_at", 0.0)),
                    "adaptive_next_decrease_at": float(getattr(self, "adaptive_next_decrease_at", 0.0)),
                    "adaptive_last_increase_at": float(getattr(self, "adaptive_last_increase_at", 0.0)),
                    "adaptive_next_increase_at": float(getattr(self, "adaptive_next_increase_at", 0.0)),
                    "adaptive_failure_wave_active": bool(getattr(self, "adaptive_failure_wave_active", False)),
                    "adaptive_decrease_min_interval_seconds": ADAPTIVE_DECREASE_MIN_INTERVAL_SECONDS,
                    "adaptive_increase_min_interval_seconds": ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS,
                    "adaptive_success_window_results": ADAPTIVE_SUCCESS_WINDOW_RESULTS,
                    "adaptive_pause_increase_step_seconds": ADAPTIVE_PAUSE_INCREASE_STEP_SECONDS,
                    "adaptive_pause_decrease_step_seconds": ADAPTIVE_PAUSE_DECREASE_STEP_SECONDS,
                    "minimum_seconds_between_request_starts": self._adaptive_request_start_interval(),
                    "request_limit": self.batch_size,
                    "batch_size": self.batch_size,
                    "batch_pause_seconds": self.batch_pause,
                },
            )
            self._persist_adaptive_profile()
            return local_results + cached_results

        results: list[FetchResult] = list(local_results) + list(cached_results)
        completed = len(results)
        network_completed = 0
        ok_count = sum(result.ok for result in results)
        failed_count = sum(not result.ok for result in results)
        next_index = 0
        # Every future keeps the controller operating point at which it was
        # admitted.  Completion time alone can never promote an old 504 into a
        # fresh failure probe.
        inflight: dict[Any, tuple[FetchJob, int]] = {}
        # Failure detection and cooldown scheduling intentionally use separate
        # counters.  In degraded mode the cooldown window can shrink to one
        # worker wave; clearing the failure evidence at that boundary would
        # otherwise make a three-failure circuit impossible to confirm.
        failure_window_results: list[FetchResult] = []
        cooldown_completed = 0
        stopped_reason = ""
        accepting = True
        last_persisted_completed = -1
        last_persisted_monotonic: float | None = None
        last_persisted_adaptive_version = -1
        next_submit_at = float(getattr(self, "adaptive_recovery_at", 0.0))

        def refill(pool: ThreadPoolExecutor) -> None:
            nonlocal next_index
            if next_submit_at > 0 and time.monotonic() < next_submit_at:
                return
            while (
                accepting
                and next_index < len(pending_jobs)
                and len(inflight) < max(
                    1,
                    min(
                        int(
                            getattr(
                                self,
                                "adaptive_worker_ceiling",
                                getattr(self, "worker_ceiling", MAX_WORKERS),
                            )
                        ),
                        int(
                            getattr(
                                self,
                                "adaptive_safe_worker_ceiling",
                                getattr(self, "adaptive_worker_ceiling", MAX_WORKERS),
                            )
                        ),
                        int(getattr(self, "adaptive_workers", self.workers)),
                    ),
                )
            ):
                job = pending_jobs[next_index]
                next_index += 1
                submission_epoch = max(
                    0,
                    int(getattr(self, "adaptive_controller_epoch", 0)),
                )
                inflight[pool.submit(self.fetch_one, job)] = (
                    job,
                    submission_epoch,
                )

        def persist_checkpoint(*, force: bool = False) -> None:
            nonlocal last_persisted_completed, last_persisted_monotonic, last_persisted_adaptive_version
            now = time.monotonic()
            if last_persisted_completed == completed and not force:
                return
            if (
                not force
                and last_persisted_monotonic is not None
                and now - last_persisted_monotonic
                < RUN_STATE_UPDATE_INTERVAL_SECONDS
            ):
                return
            write_json_atomic(
                RUN_STATE_JSON,
                {
                    "updated_at": utc_now(),
                    "pid": os.getpid(),
                    "queue_stage_id": os.environ.get("DATA_CRAWL_QUEUE_STAGE_ID"),
                    "queue_stage_attempt": os.environ.get("DATA_CRAWL_QUEUE_STAGE_ATTEMPT"),
                    "queue_stage_started_at": os.environ.get("DATA_CRAWL_QUEUE_STAGE_STARTED_AT"),
                    "phase": phase,
                    "adaptive_phase": str(getattr(self, "adaptive_phase", "")),
                    "adaptive_replay_active": bool(
                        getattr(self, "adaptive_replay_active", False)
                    ),
                    "phase_total": len(all_jobs),
                    "phase_completed_this_run": completed,
                    "phase_remaining": len(all_jobs) - completed,
                    "successful_or_skipped": ok_count,
                    "failed": failed_count,
                    "stopped_reason": stopped_reason,
                    "resumable": bool(stopped_reason or completed < len(all_jobs)),
                    "satisfied_by_local_source": len(local_results),
                    "workers": int(getattr(self, "adaptive_workers", self.workers)),
                    "configured_workers": self.workers,
                    "adaptive_tuning": bool(getattr(self, "adaptive_tuning", True)),
                    "adaptive_worker_ceiling": int(
                        getattr(
                            self,
                            "adaptive_worker_ceiling",
                            getattr(self, "worker_ceiling", MAX_WORKERS),
                        )
                    ),
                    "adaptive_safe_worker_ceiling": int(
                        getattr(
                            self,
                            "adaptive_safe_worker_ceiling",
                            getattr(self, "adaptive_worker_ceiling", MAX_WORKERS),
                        )
                    ),
                    "adaptive_workers": int(getattr(self, "adaptive_workers", self.workers)),
                    "request_limit_ceiling": int(getattr(self, "request_limit_ceiling", MAX_BATCH_REQUESTS)),
                    "adaptive_batch_pause_ceiling_seconds": float(getattr(self, "adaptive_pause_ceiling", MAX_BATCH_PAUSE_SECONDS)),
                    "adaptive_pause_floor_seconds": float(getattr(self, "adaptive_pause_floor", MIN_ADAPTIVE_BATCH_PAUSE_SECONDS)),
                    "adaptive_safe_pause_floor_seconds": float(max(getattr(self, "adaptive_safe_pause_floor", getattr(self, "adaptive_pause_floor", MIN_ADAPTIVE_BATCH_PAUSE_SECONDS)), self._adaptive_persisted_pause() if getattr(self, "adaptive_pause_rollback", 0.0) > getattr(self, "adaptive_batch_pause", self.batch_pause) else getattr(self, "adaptive_pause_floor", MIN_ADAPTIVE_BATCH_PAUSE_SECONDS))),
                    "adaptive_batch_pause_seconds": self._adaptive_persisted_pause(),
                     # Health/candidate evidence is intentionally not durable;
                     # a restarted process must earn it again from zero.
                     "adaptive_success_streak": 0,
                     "adaptive_pause_success_streak": 0,
                     "adaptive_pause_rollback": 0.0,
                     "adaptive_next_pause_probe_at": float(getattr(self, "adaptive_next_pause_probe_at", 0.0)),
                     "adaptive_recovery_at": float(getattr(self, "adaptive_recovery_at", 0.0)),
                    "minimum_seconds_between_request_starts": self._adaptive_request_start_interval(),
                    "request_limit": self.batch_size,
                    "batch_size": self.batch_size,
                    "batch_pause_seconds": self.batch_pause,
                },
            )
            # Save at the same cadence as the durable checkpoint (and after a
            # speed adjustment), so a later queue start can reuse the latest
            # learned safe point without rewriting JSON for every response.
            self._persist_adaptive_profile()
            last_persisted_completed = completed
            last_persisted_monotonic = now
            last_persisted_adaptive_version = int(
                getattr(self, "adaptive_adjustments", 0)
            )

        # Make the selected phase and cached-prefix progress visible
        # immediately; subsequent writes are throttled to roughly once a
        # second and the final/circuit state is forced below.
        persist_checkpoint(force=True)

        # The configured worker count is the controller's starting point.  The
        # pool itself is created at the guarded ceiling so stable runs can add
        # slots without rebuilding the executor; ``refill`` still controls how
        # many requests are actually in flight.
        with ThreadPoolExecutor(
            max_workers=int(
                getattr(
                    self,
                    "adaptive_worker_ceiling",
                    getattr(self, "worker_ceiling", MAX_WORKERS),
                )
            ),
            thread_name_prefix="cnvote",
        ) as pool:
            refill(pool)
            while inflight or (accepting and next_index < len(pending_jobs)):
                if not inflight:
                    wait_seconds = (
                        max(0.0, next_submit_at - time.monotonic())
                        if next_submit_at > 0
                        else 0.0
                    )
                    if wait_seconds > 0:
                        # Wake periodically so a stop signal can still be
                        # observed by the surrounding runner between probes.
                        time.sleep(min(wait_seconds, 5.0))
                    refill(pool)
                    if not inflight:
                        continue
                # Harvest one completion at a time and immediately refill its
                # slot.  Unlike fixed submission batches, a single slow PHP
                # response no longer leaves the other workers idle.
                future = next(as_completed(tuple(inflight)))
                job, request_epoch = inflight.pop(future)
                try:
                    result = future.result()
                except Exception as exc:  # defensive; fetch_one absorbs normal failures
                    result = FetchResult(
                        job=job, ok=False, error=f"worker crash: {exc}"
                    )
                    traceback.print_exc()
                results.append(result)
                # Prefix results still participate in the circuit breaker so
                # an actually unavailable upstream is protected, but their
                # adaptive speed observations are suppressed below.
                failure_window_results.append(result)
                completed += 1
                network_completed += 1
                cooldown_completed += 1
                ok_count += int(result.ok)
                failed_count += int(not result.ok)
                persist_checkpoint()
                if completed % 100 == 0 or completed == len(all_jobs):
                    print(
                        f"[{phase}] {completed}/{len(all_jobs)} complete; ok={ok_count}",
                        flush=True,
                    )

                transient_failures = [
                    item
                    for item in failure_window_results
                    if not item.ok
                    and (
                        item.transient
                        or item.status in TRANSIENT_HTTP_STATUSES
                    )
                ]
                if (
                    not stopped_reason
                    and len(transient_failures)
                    >= self.transient_failure_threshold
                ):
                    # The threshold confirms that the failed operating point
                    # must remain above the learned safe ceiling across the
                    # automatic restart.  Observe this completion normally
                    # first so a threshold of one still gets exactly one
                    # throttle decision; epoch rejection makes this a no-op
                    # when an earlier peer already made that decision.
                    self._adaptive_observe(
                        result,
                        allow_adjustment=not replay_prefix,
                        request_epoch=request_epoch,
                    )
                    # Confirmation itself only opens/extends the quiet gate;
                    # it never applies a second worker or pause reduction.
                    self._adaptive_observe(
                        result,
                        allow_adjustment=not replay_prefix,
                        confirmed_failure_wave=True,
                        request_epoch=request_epoch,
                    )
                    statuses = sorted(
                        {
                            str(item.status)
                            if item.status is not None
                            else "transport"
                            for item in transient_failures
                        }
                    )
                    stopped_reason = (
                        "transient circuit breaker: "
                        f"{len(transient_failures)} failures in a "
                        f"{len(failure_window_results)}-completion window; "
                        f"transport/status {statuses}"
                    )
                    self.circuit_open = True
                    self.circuit_reason = stopped_reason
                    accepting = False
                    print(
                        f"[{phase}] STOPPED — {stopped_reason}. Rerun will resume.",
                        file=sys.stderr,
                        flush=True,
                    )
                    persist_checkpoint(force=True)

                # Apply the speed change before refilling this completion's
                # slot.  A failure must gate the next submission at the new
                # conservative point; refilling first would briefly submit at
                # the old speed and can turn one outage into a larger wave.
                adjustment_version_before = int(
                    getattr(self, "adaptive_adjustments", 0)
                )
                self._adaptive_observe(
                    result,
                    allow_adjustment=(
                        not bool(stopped_reason) and not replay_prefix
                    ),
                    request_epoch=request_epoch,
                )
                if (
                    not stopped_reason
                    and int(getattr(self, "adaptive_adjustments", 0))
                    != adjustment_version_before
                ):
                    # Make a newly learned speed visible immediately, including
                    # while the recovery gate is waiting for its next probe.
                    persist_checkpoint(force=True)
                next_submit_at = max(
                    next_submit_at,
                    float(getattr(self, "adaptive_recovery_at", 0.0)),
                )

                if len(failure_window_results) >= self.batch_size:
                    failure_window_results.clear()

                configured_ceiling = max(
                    1,
                    int(
                        getattr(
                            self,
                            "adaptive_worker_ceiling",
                            getattr(self, "worker_ceiling", self.workers),
                        )
                    ),
                )
                safe_ceiling = max(
                    1,
                    min(
                        configured_ceiling,
                        int(
                            getattr(
                                self,
                                "adaptive_safe_worker_ceiling",
                                configured_ceiling,
                            )
                        ),
                    ),
                )
                active_workers = max(
                    1,
                    min(
                        safe_ceiling,
                        int(getattr(self, "adaptive_workers", self.workers)),
                    ),
                )
                degraded = bool(
                    getattr(self, "adaptive_tuning", True)
                    and (
                        safe_ceiling < configured_ceiling
                        or getattr(self, "adaptive_failure_wave_active", False)
                        or getattr(self, "adaptive_restart_probation", False)
                    )
                )
                cooldown_window = max(1, self.batch_size)
                if degraded and active_workers > 1:
                    # Pause after each complete in-flight wave while degraded,
                    # rather than allowing another thirty-result burst.  This
                    # is intentional safety behavior; the request-start gate
                    # below only waits for whatever portion of the same quiet
                    # interval remains, so adaptive pacing is not added twice.
                    cooldown_window = min(cooldown_window, active_workers)
                if cooldown_completed >= cooldown_window:
                    cooldown_completed = 0
                    persist_checkpoint(force=bool(stopped_reason))
                    current_pause = float(
                        getattr(self, "adaptive_batch_pause", self.batch_pause)
                    )
                    singleton_interval = self._adaptive_request_start_interval()
                    if (
                        accepting
                        and next_index < len(pending_jobs)
                        and current_pause > 0
                        and singleton_interval <= 0
                    ):
                        time.sleep(current_pause)
                # A circuit break stops new submissions, but already-running
                # requests are drained so their atomic files/journal entries
                # and the final checkpoint are not lost.  Drain completions
                # were passed allow_adjustment=False above, so they cannot
                # repeatedly lower the controller.
                if accepting:
                    refill(pool)

        if (
            last_persisted_completed != completed
            or last_persisted_adaptive_version
            != int(getattr(self, "adaptive_adjustments", 0))
        ):
            persist_checkpoint(force=True)
        return results

    def page_job(self, round_no: int, url: str, relative: str, *, optional: bool = False, label: str = "") -> FetchJob:
        return FetchJob(
            round_no=round_no,
            url=url,
            target=DATA_ROOT / f"round_{round_no:02d}" / "raw" / relative,
            expect="html",
            optional=optional,
            label=label,
        )

    def compressed_page_job(
        self,
        round_no: int,
        url: str,
        relative: str,
        *,
        optional: bool = False,
        label: str = "",
    ) -> FetchJob:
        """Store a byte-for-byte HTTP HTML response inside deterministic gzip.

        Advanced-filter result pages repeat a large amount of static interface
        markup.  Lossless gzip keeps the complete response auditable while the
        manifest records hashes and byte counts for both the HTTP body and the
        compressed file stored on disk.
        """
        if not relative.endswith(".gz"):
            raise ValueError("compressed HTML targets must end with .gz")
        return FetchJob(
            round_no=round_no,
            url=url,
            target=DATA_ROOT / f"round_{round_no:02d}" / "raw" / relative,
            expect="html",
            storage_encoding="gzip",
            optional=optional,
            label=label,
        )

    def script_job(self, round_no: int, url: str, relative: str, *, optional: bool = False, label: str = "") -> FetchJob:
        return FetchJob(
            round_no=round_no,
            url=url,
            target=DATA_ROOT / f"round_{round_no:02d}" / "raw" / relative,
            expect="js",
            optional=optional,
            label=label,
        )

    def json_job(
        self,
        round_no: int,
        url: str,
        relative: str,
        *,
        method: str = "GET",
        form: Sequence[tuple[str, str]] = (),
        optional: bool = False,
        label: str = "",
    ) -> FetchJob:
        return FetchJob(
            round_no=round_no,
            url=url,
            target=DATA_ROOT / f"round_{round_no:02d}" / "raw" / relative,
            method=method,
            form=tuple(form),
            expect="json",
            optional=optional,
            label=label,
        )

    def compressed_json_job(
        self,
        round_no: int,
        url: str,
        relative: str,
        *,
        method: str = "GET",
        form: Sequence[tuple[str, str]] = (),
        optional: bool = False,
        label: str = "",
    ) -> FetchJob:
        if not relative.endswith(".json.gz"):
            raise ValueError("compressed JSON targets must end with .json.gz")
        return FetchJob(
            round_no=round_no,
            url=url,
            target=DATA_ROOT / f"round_{round_no:02d}" / "raw" / relative,
            method=method,
            form=tuple(form),
            expect="json",
            storage_encoding="gzip",
            optional=optional,
            label=label,
        )

    @staticmethod
    def read_text(path: Path) -> str:
        data = path.read_bytes()
        if path.suffix == ".gz":
            data = gzip.decompress(data)
        return decode_body(data, "text/html; charset=utf-8")

    def crawl_round_1(self, round_no: int) -> None:
        state = self.states[round_no]
        base = BASE.format(round_no=round_no)
        root_job = self.page_job(round_no, base, "pages/root.html", label="round root")
        category_urls = {
            "chara": urllib.parse.urljoin(base, "index.php?mod=chara"),
            "music": urllib.parse.urljoin(base, "index.php?mod=music"),
            "work": urllib.parse.urljoin(base, "index.php?mod=work"),
            "paper": urllib.parse.urljoin(base, "index.php?mod=paper"),
        }
        jobs = [root_job]
        for category, url in category_urls.items():
            jobs.append(self.page_job(round_no, url, f"pages/{category}/index.html", label=f"{category} index"))
        results = self.fetch_many(jobs, f"v{round_no} indexes")
        for result in results:
            if result.ok and not getattr(result, "local_substitute", False):
                state.page_files.add(result.job.target)
        state.questionnaire_file = jobs[-1].target

        variant_jobs: list[FetchJob] = []
        for category in ("chara", "music", "work"):
            index_path = DATA_ROOT / f"round_{round_no:02d}" / "raw" / "pages" / category / "index.html"
            if not index_path.exists():
                continue
            for url in extract_links(self.read_text(index_path), category_urls[category]):
                query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                if query.get("mod", [""])[0] == category and "step" in query and same_round_url(url, round_no):
                    variant_jobs.append(
                        self.page_job(round_no, url, f"pages/{category}/{query_slug(url)}.html", label=f"{category} result variant")
                    )
        variant_results = self.fetch_many(variant_jobs, f"v{round_no} result variants")
        local_count = sum(
            1 for result in variant_results if getattr(result, "local_substitute", False)
        )
        if local_count:
            state.notes.append(
                f"{local_count} redundant v1 ranking views were satisfied by validated local workbooks; "
                "step=1/detail discovery was retained."
            )
        for result in variant_results:
            if result.ok and not getattr(result, "local_substitute", False):
                query = urllib.parse.parse_qs(urllib.parse.urlparse(result.job.url).query)
                category = query.get("mod", ["unknown"])[0]
                state.add_summary(category, result.job.target)
        if state.questionnaire_file and state.questionnaire_file.exists():
            state.add_summary("paper", state.questionnaire_file)
        self._discover_and_fetch_legacy_details(state, version=1)
        state.notes.extend([
            "The official round-1 navigation has no CP or game department.",
            "The work result is a static table and exposes no numeric detail page links.",
        ])

    def crawl_round_2_or_3(self, round_no: int) -> None:
        state = self.states[round_no]
        base = BASE.format(round_no=round_no)
        category_by_m = {"1": "chara", "2": "music", "3": "work", "4": "cp", "5": "paper"}
        jobs = [self.page_job(round_no, base, "pages/root.html", label="round root")]
        for number, category in category_by_m.items():
            url = urllib.parse.urljoin(base, f"?m={number}")
            jobs.append(self.page_job(round_no, url, f"pages/{category}/index.html", label=f"{category} index"))
        results = self.fetch_many(jobs, f"v{round_no} indexes")
        for result in results:
            if result.ok and not getattr(result, "local_substitute", False):
                state.page_files.add(result.job.target)
        state.questionnaire_file = DATA_ROOT / f"round_{round_no:02d}" / "raw" / "pages" / "paper" / "index.html"

        variant_jobs: list[FetchJob] = []
        for number, category in category_by_m.items():
            index_path = DATA_ROOT / f"round_{round_no:02d}" / "raw" / "pages" / category / "index.html"
            if not index_path.exists() or category == "paper":
                continue
            index_url = urllib.parse.urljoin(base, f"?m={number}")
            for url in extract_links(self.read_text(index_path), index_url):
                query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                if query.get("m", [""])[0] == number and any(key in query for key in ("s", "t")) and same_round_url(url, round_no):
                    variant_jobs.append(
                        self.page_job(round_no, url, f"pages/{category}/{query_slug(url)}.html", label=f"{category} result variant")
                    )
        variant_results = self.fetch_many(variant_jobs, f"v{round_no} result variants")
        for result in variant_results:
            if result.ok and not getattr(result, "local_substitute", False):
                query = urllib.parse.parse_qs(urllib.parse.urlparse(result.job.url).query)
                category = category_by_m.get(query.get("m", [""])[0], "unknown")
                state.add_summary(category, result.job.target)
        for number, category in category_by_m.items():
            path = DATA_ROOT / f"round_{round_no:02d}" / "raw" / "pages" / category / "index.html"
            if path.exists():
                state.add_summary(category, path)
        self._discover_and_fetch_legacy_details(state, version=round_no)
        state.notes.append(
            "Detail type 4 is the work-with-character breakdown, not an item-level CP detail page."
        )

    def crawl_round_4(self, round_no: int) -> None:
        state = self.states[round_no]
        base = BASE.format(round_no=round_no)
        categories = ("chara", "music", "work", "cp", "paper")
        jobs = [self.page_job(round_no, base, "pages/root.html", label="round root")]
        for category in categories:
            url = urllib.parse.urljoin(base, f"?m={category}")
            jobs.append(self.page_job(round_no, url, f"pages/{category}/index.html", label=f"{category} index"))
        results = self.fetch_many(jobs, "v4 indexes")
        for result in results:
            if result.ok and not getattr(result, "local_substitute", False):
                state.page_files.add(result.job.target)
        state.questionnaire_file = DATA_ROOT / "round_04" / "raw" / "pages" / "paper" / "index.html"

        variant_jobs: list[FetchJob] = []
        for category in categories:
            index_path = DATA_ROOT / "round_04" / "raw" / "pages" / category / "index.html"
            if not index_path.exists() or category == "paper":
                continue
            index_url = urllib.parse.urljoin(base, f"?m={category}")
            for url in extract_links(self.read_text(index_path), index_url):
                query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                if query.get("m", [""])[0] == category and any(key in query for key in ("t", "s")) and same_round_url(url, round_no):
                    variant_jobs.append(
                        self.page_job(round_no, url, f"pages/{category}/{query_slug(url)}.html", label=f"{category} result variant")
                    )
        # The round-4 default CP table is truncated (446 groups).  The
        # official ``s=1`` view contains the complete 1,118-group table and is
        # required both for the ranking archive and CP detail discovery.
        complete_cp_url = urllib.parse.urljoin(base, "?m=cp&s=1")
        variant_jobs.append(
            self.page_job(
                round_no,
                complete_cp_url,
                "pages/cp/m_cp__s_1.html",
                label="cp complete result variant",
            )
        )
        variant_results = self.fetch_many(variant_jobs, "v4 result variants")
        for result in variant_results:
            if result.ok and not getattr(result, "local_substitute", False):
                query = urllib.parse.parse_qs(urllib.parse.urlparse(result.job.url).query)
                state.add_summary(query.get("m", ["unknown"])[0], result.job.target)
        for category in categories:
            path = DATA_ROOT / "round_04" / "raw" / "pages" / category / "index.html"
            if path.exists():
                state.add_summary(category, path)
        self._discover_and_fetch_legacy_details(state, version=4)
        state.notes.append("The game questionnaire is published as the work&t=game result subpage.")

    def _discover_and_fetch_legacy_details(self, state: RoundState, version: int) -> None:
        round_no = state.round_no
        patterns: list[tuple[re.Pattern[str], Callable[[re.Match[str]], tuple[str, str, str]]]]
        if version == 1:
            patterns = [(
                re.compile(r"(?:\./)?index\.php\?mod=json&type=(chara|music|work)&id=([0-9]+)"),
                lambda match: (match.group(1), match.group(2), urllib.parse.urljoin(BASE.format(round_no=round_no), match.group(0))),
            )]
        elif version in (2, 3):
            type_map = {"1": "chara", "2": "music", "3": "work", "4": "work_characters"}
            patterns = [(
                re.compile(r"(?:\./)?\?m=j&t=([1-4])&i=([0-9]+)"),
                lambda match: (
                    type_map[match.group(1)],
                    match.group(2),
                    urllib.parse.urljoin(BASE.format(round_no=round_no), match.group(0)),
                ),
            )]
        else:
            patterns = [(
                re.compile(r"(?:\./)?\?v=json&m=(chara|music|work|cp)&i=([0-9]+)"),
                lambda match: (match.group(1), match.group(2), urllib.parse.urljoin(BASE.format(round_no=round_no), match.group(0))),
            )]

        discoveries: dict[tuple[str, str], str] = {}
        for path in sorted(state.page_files | {item for files in state.summary_files.values() for item in files}):
            if not path.exists():
                continue
            text = self.read_text(path)
            for pattern, mapper in patterns:
                for match in pattern.finditer(text):
                    category, item_id, url = mapper(match)
                    discoveries[(category, item_id)] = url
        if version == 4:
            base = BASE.format(round_no=round_no)
            for category in ("chara", "music", "work", "cp"):
                for path in state.summary_files.get(category, set()):
                    if not path.exists():
                        continue
                    result = extract_json_after(self.read_text(path), "var vote =")
                    if not result or not isinstance(result[0], list):
                        continue
                    for item in result[0]:
                        if not isinstance(item, dict) or "id" not in item:
                            continue
                        item_id = str(item["id"])
                        url = urllib.parse.urljoin(base, f"?v=json&m={category}&i={item_id}")
                        discoveries[(category, item_id)] = url
        jobs: list[FetchJob] = []
        per_category_count: dict[str, int] = {}
        for (category, item_id), url in sorted(discoveries.items(), key=lambda item: (item[0][0], int(item[0][1]))):
            if self.max_items is not None:
                count = per_category_count.get(category, 0)
                if count >= self.max_items:
                    continue
                per_category_count[category] = count + 1
            target_relative = f"details/{category}/{item_id}.html"
            job = self.page_job(round_no, url, target_relative, label=f"{category} detail")
            jobs.append(job)
            state.add_detail(category, item_id, job.target)
        results = self.fetch_many(jobs, f"v{round_no} details")
        failed_keys = {(result.job.label, result.job.target.stem) for result in results if not result.ok}
        if failed_keys:
            state.notes.append(f"{len(failed_keys)} legacy detail downloads failed; rerun resumes them.")

    def crawl_round_modern(self, round_no: int) -> None:
        state = self.states[round_no]
        base = BASE.format(round_no=round_no)
        categories = ("chara", "music", "work", "cp", "game", "paper")
        jobs = [self.page_job(round_no, base, "pages/root.html", label="round root")]
        for category in categories:
            url = urllib.parse.urljoin(base, f"?m={category}")
            jobs.append(self.page_job(round_no, url, f"pages/{category}/index.html", label=f"{category} index"))
        index_results = self.fetch_many(jobs, f"v{round_no} indexes")
        for result in index_results:
            if result.ok:
                state.page_files.add(result.job.target)
        state.questionnaire_file = DATA_ROOT / f"round_{round_no:02d}" / "raw" / "pages" / "paper" / "index.html"

        variant_jobs: list[FetchJob] = []
        for category in categories:
            index_path = DATA_ROOT / f"round_{round_no:02d}" / "raw" / "pages" / category / "index.html"
            index_url = urllib.parse.urljoin(base, f"?m={category}")
            if index_path.exists():
                for url in extract_links(self.read_text(index_path), index_url):
                    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                    page_category = query.get("m", [""])[0]
                    if page_category in categories and same_round_url(url, round_no):
                        if "type" in query or page_category == "game":
                            variant_jobs.append(
                                self.page_job(
                                    round_no,
                                    url,
                                    f"pages/{page_category}/{query_slug(url)}.html",
                                    label=f"{page_category} result variant",
                                )
                            )
        # The game page accepts type=simple although some rounds do not link it explicitly.
        game_simple_url = urllib.parse.urljoin(base, "?m=game&type=simple")
        variant_jobs.append(self.page_job(round_no, game_simple_url, "pages/game/m_game__type_simple.html", label="game simple"))
        # Simple pages are the authoritative complete item lists used for detail discovery.
        for category in ("chara", "music", "work", "cp"):
            url = urllib.parse.urljoin(base, f"?m={category}&type=simple")
            variant_jobs.append(
                self.page_job(round_no, url, f"pages/{category}/m_{category}__type_simple.html", label=f"{category} simple")
            )
        variant_results = self.fetch_many(variant_jobs, f"v{round_no} result variants")
        for result in variant_results:
            if not result.ok:
                continue
            query = urllib.parse.parse_qs(urllib.parse.urlparse(result.job.url).query)
            category = query.get("m", ["unknown"])[0]
            state.add_summary(category, result.job.target)
            if query.get("type", [""])[0] == "simple" and category in ("chara", "music", "work", "cp"):
                state.modern_simple_files[category] = result.job.target
        if state.questionnaire_file and state.questionnaire_file.exists():
            state.add_summary("paper", state.questionnaire_file)

        script_jobs = [
            self.script_job(round_no, urllib.parse.urljoin(base, "js/info.js"), "scripts/info.js", label="detail API client"),
            self.script_job(round_no, urllib.parse.urljoin(base, "js/paperinfo.js"), "scripts/paperinfo.js", label="questionnaire API client"),
            self.script_job(
                round_no,
                urllib.parse.urljoin(base, "js/crossvote.js"),
                "scripts/crossvote.js",
                optional=True,
                label="crossvote API client",
            ),
        ]
        self.fetch_many(script_jobs, f"v{round_no} interface scripts")
        self._parse_modern_questionnaire_definitions(state)
        self._discover_modern_details(state)
        self._fetch_modern_details(state)
        self._fetch_modern_aggregate_questionnaire(state)
        self._fetch_modern_crossvote(state)
        if not self.no_item_apis:
            self._fetch_modern_item_apis(state)
        else:
            state.notes.append("Item-level APIs were skipped by --no-item-apis.")

    def crawl_round_supplemental(self, round_no: int) -> None:
        """Fetch questionnaires/default co-vote data before large detail batches.

        The old PHP detail endpoint can become saturated after dozens of item
        requests.  Aggregate questionnaire APIs are independent, high-value
        resources, so a resume run must be able to collect them without first
        traversing every character/music/work/CP detail page.
        """
        state = self.states[round_no]
        self.reconstruct_state(round_no)
        base = BASE.format(round_no=round_no)

        if round_no <= 4:
            # Rounds 1--4 publish questionnaire results directly in HTML and
            # do not expose the later aggregate JSON API/default co-vote UI.
            if round_no == 4:
                jobs = [
                    self.page_job(round_no, base, "pages/root.html", label="round root"),
                    self.page_job(
                        round_no,
                        urllib.parse.urljoin(base, "?m=paper"),
                        "pages/paper/index.html",
                        label="paper index",
                    ),
                ]
                self.fetch_many(jobs, f"v{round_no} supplemental questionnaire HTML")
                state.questionnaire_file = (
                    DATA_ROOT
                    / f"round_{round_no:02d}"
                    / "raw"
                    / "pages"
                    / "paper"
                    / "index.html"
                )
                if state.questionnaire_file.exists():
                    state.add_summary("paper", state.questionnaire_file)
            state.notes.append(
                "Supplemental-only mode: this round has no later aggregate questionnaire/default crossvote API."
            )
            return

        questionnaire_path = (
            DATA_ROOT
            / f"round_{round_no:02d}"
            / "raw"
            / "pages"
            / "paper"
            / "index.html"
        )
        jobs = [
            self.page_job(round_no, base, "pages/root.html", label="round root"),
            self.page_job(
                round_no,
                urllib.parse.urljoin(base, "?m=paper"),
                "pages/paper/index.html",
                label="paper index",
            ),
            self.script_job(
                round_no,
                urllib.parse.urljoin(base, "js/paperinfo.js"),
                "scripts/paperinfo.js",
                label="questionnaire API client",
            ),
        ]
        if round_no in {8, 9}:
            jobs.append(
                self.script_job(
                    round_no,
                    urllib.parse.urljoin(base, "js/crossvote.js"),
                    "scripts/crossvote.js",
                    label="crossvote API client",
                )
            )
        results = self.fetch_many(jobs, f"v{round_no} supplemental entry resources")
        for result in results:
            if result.ok and result.job.expect == "html":
                state.page_files.add(result.job.target)

        state.questionnaire_file = questionnaire_path
        if questionnaire_path.exists():
            state.add_summary("paper", questionnaire_path)
        self._parse_modern_questionnaire_definitions(state)
        self._fetch_modern_aggregate_questionnaire(state)
        if round_no in {8, 9}:
            self._fetch_modern_crossvote(state)
        else:
            state.notes.append(
                "The official default crossvote visualization/API is not offered before round 8."
            )
        state.notes.append(
            "Supplemental-only mode: aggregate questionnaire/default crossvote fetched before item details."
        )

    def _parse_modern_questionnaire_definitions(self, state: RoundState) -> None:
        round_dir = DATA_ROOT / f"round_{state.round_no:02d}"
        paper_path = state.questionnaire_file
        if paper_path is None or not paper_path.exists():
            state.notes.append("Questionnaire HTML unavailable; definitions could not be parsed.")
            return
        text = self.read_text(paper_path)
        paperall_result = extract_json_after(text, "paperall =")
        if paperall_result:
            value = paperall_result[0]
            if isinstance(value, list) and value and isinstance(value[0], dict):
                state.questionnaire_groups = {str(key): [str(item) for item in items] for key, items in value[0].items()}
        questlist_result = extract_json_after(text, "var questlist =")
        if questlist_result and isinstance(questlist_result[0], list):
            state.questionnaire_defs = [dict(item) for item in questlist_result[0] if isinstance(item, dict)]
        info_path = round_dir / "raw" / "scripts" / "info.js"
        if info_path.exists():
            info_text = self.read_text(info_path)
            block_match = re.search(r"var\s+hobAry\s*=\s*\[(.*?)\]\s*;", info_text, re.S)
            if block_match:
                state.hob_tokens = re.findall(r"['\"]([^'\"]+)['\"]", block_match.group(1))

        processed = round_dir / "processed" / "questionnaire"
        definitions_payload = {
            "round": state.round_no,
            "groups": state.questionnaire_groups,
            "questions": state.questionnaire_defs,
            "item_detail_question_tokens": state.hob_tokens,
            "source": rel_workspace(paper_path),
        }
        write_json_atomic(processed / "definitions.json", definitions_payload)
        definition_rows = [
            {
                "round": state.round_no,
                "group": item.get("group"),
                "question": item.get("name", ""),
                "public_token": item.get("value", ""),
                "included_in_item_detail": item.get("value") in state.hob_tokens,
            }
            for item in state.questionnaire_defs
        ]
        write_csv(
            processed / "definitions.csv",
            definition_rows,
            ["round", "group", "question", "public_token", "included_in_item_detail"],
        )

    def _discover_modern_details(self, state: RoundState) -> None:
        pattern = re.compile(r"(?:\./)?\?m=info&type=(chara|music|work|cp)&id=([0-9]+)")
        for category, path in state.modern_simple_files.items():
            if not path.exists():
                continue
            for match in pattern.finditer(self.read_text(path)):
                if match.group(1) == category:
                    state.detail_ids.setdefault(category, set()).add(match.group(2))

    def _fetch_modern_details(self, state: RoundState) -> None:
        base = BASE.format(round_no=state.round_no)
        jobs: list[FetchJob] = []
        for category, ids in sorted(state.detail_ids.items()):
            selected_ids = sorted(ids, key=lambda value: (len(value), value))
            if self.max_items is not None:
                selected_ids = selected_ids[: self.max_items]
            for item_id in selected_ids:
                url = urllib.parse.urljoin(base, f"?m=info&type={category}&id={item_id}")
                job = self.page_job(state.round_no, url, f"details/{category}/{item_id}.html", label=f"{category} detail")
                jobs.append(job)
                state.add_detail(category, item_id, job.target)
        self.fetch_many(jobs, f"v{state.round_no} detail HTML")

    def _fetch_modern_aggregate_questionnaire(self, state: RoundState) -> None:
        round_no = state.round_no
        base = BASE.format(round_no=round_no)
        api_base = urllib.parse.urljoin(base, "api.php?action=make")
        jobs = [
            self.json_job(round_no, api_base + "&object=votedate&text=paper", "api/questionnaire/votedate.json", label="aggregate questionnaire date"),
            self.json_job(round_no, api_base + "&object=votesex&text=paper", "api/questionnaire/votesex.json", label="aggregate questionnaire sex/age"),
            self.json_job(round_no, api_base + "&object=votegeo&text=all", "api/questionnaire/votegeo.json", label="aggregate questionnaire geography"),
        ]
        for group_id, tokens in sorted(state.questionnaire_groups.items(), key=lambda item: int(item[0])):
            form = [("paper[]", token) for token in tokens]
            url = api_base + f"&object=votepaper&text=paper&index={group_id}"
            jobs.append(
                self.json_job(
                    round_no,
                    url,
                    f"api/questionnaire/groups/{group_id}.json",
                    method="POST",
                    form=form,
                    label=f"aggregate questionnaire group {group_id}",
                )
            )
        self.fetch_many(jobs, f"v{round_no} aggregate questionnaire APIs")

    def _fetch_modern_crossvote(self, state: RoundState) -> None:
        round_no = state.round_no
        base = BASE.format(round_no=round_no)
        page_jobs: list[FetchJob] = []
        for category in ("chara", "music"):
            url = urllib.parse.urljoin(base, f"?m={category}&type=crossvote")
            page_jobs.append(
                self.page_job(
                    round_no,
                    url,
                    f"pages/{category}/m_{category}__type_crossvote.html",
                    optional=True,
                    label=f"{category} crossvote page",
                )
            )
        results = self.fetch_many(page_jobs, f"v{round_no} crossvote pages")
        api_jobs: list[FetchJob] = []
        for result in results:
            if not result.ok or not result.job.target.exists():
                continue
            text = self.read_text(result.job.target)
            type_match = re.search(r"var\s+type\s*=\s*[\"']([^\"']+)", text)
            number_match = re.search(r"var\s+number\s*=\s*[\"']([^\"']+)", text)
            filter_match = re.search(r"var\s+filter\s*=\s*[\"']([^\"']+)", text)
            if not (type_match and number_match and filter_match):
                continue
            category = type_match.group(1)
            number = number_match.group(1)
            rate = filter_match.group(1)
            state.expected_crossvote[category] = {"filter": number, "rate": rate}
            url = urllib.parse.urljoin(
                base,
                f"api.php?action=make&object=votecrossvote&text={category}&filter={number}&rate={rate}",
            )
            api_jobs.append(
                self.json_job(
                    round_no,
                    url,
                    f"api/crossvote/{category}_filter_{number}_rate_{rate}.json",
                    method="POST",
                    label=f"{category} official-default crossvote",
                )
            )
            # The published page deliberately shows only a filtered graph
            # (normally the top 30/50 entries at rate 5).  The API rejects a
            # zero threshold (``filter=0&rate=0`` returns the literal
            # ``错误make``), but accepts the wider top-100 scope and its
            # lowest positive rate.  Preserve both scopes instead of treating
            # the official-default visualization as a complete matrix.
            # Character data accepts a top-100 request.  The music endpoint
            # rejects top-100 with ``错误make`` in both rounds, so retain its
            # published top-N node scope and lower only the rate threshold.
            expanded_filter = "100" if category == "chara" else number
            expanded_rate = "1"
            expanded_scope = (
                "official_api_expanded_top100_lowest_accepted_rate_not_complete_matrix"
                if category == "chara"
                else "official_api_default_topn_lowest_accepted_rate_not_complete_matrix"
            )
            state.expected_crossvote[category].update({
                "expanded_filter": expanded_filter,
                "expanded_rate": expanded_rate,
                "expanded_scope": expanded_scope,
            })
            expanded_url = urllib.parse.urljoin(
                base,
                (
                    "api.php?action=make&object=votecrossvote"
                    f"&text={category}&filter={expanded_filter}&rate={expanded_rate}"
                ),
            )
            api_jobs.append(
                self.json_job(
                    round_no,
                    expanded_url,
                    f"api/crossvote/{category}_filter_{expanded_filter}_rate_{expanded_rate}.json",
                    method="POST",
                    label=(
                        f"{category} official API top-{expanded_filter} "
                        "lowest-accepted-rate crossvote (not complete matrix)"
                    ),
                )
            )
        self.fetch_many(api_jobs, f"v{round_no} crossvote APIs")
        if not state.expected_crossvote:
            state.notes.append("The official crossvote visualization/API is unavailable for this round.")

    def _fetch_modern_item_apis(self, state: RoundState) -> None:
        round_no = state.round_no
        base = BASE.format(round_no=round_no)
        api_base = urllib.parse.urljoin(base, "api.php?action=make")
        jobs: list[FetchJob] = []
        for category, id_paths in sorted(state.details.items()):
            for item_id in sorted(id_paths, key=lambda value: (len(value), value)):
                for object_name in ("votedate", "votesex", "votegeo"):
                    url = api_base + f"&object={object_name}&text={category}&id={item_id}"
                    jobs.append(
                        self.json_job(
                            round_no,
                            url,
                            f"api/items/{category}/{item_id}/{object_name}.json",
                            label=f"{category} {item_id} {object_name}",
                        )
                    )
                if state.hob_tokens:
                    form = [("paper[]", token) for token in state.hob_tokens]
                    url = api_base + f"&object=votepaper&text={category}&id={item_id}"
                    jobs.append(
                        self.json_job(
                            round_no,
                            url,
                            f"api/items/{category}/{item_id}/votepaper.json",
                            method="POST",
                            form=form,
                            label=f"{category} {item_id} votepaper",
                        )
                    )
        self.fetch_many(jobs, f"v{round_no} item APIs")

    # ------------------------------------------------------------------
    # Bounded advanced-search archive (rounds 5--9)

    @staticmethod
    def _advanced_marker_support(text: str) -> dict[str, bool]:
        return {
            "questionnaire_filter": (
                "action=advice&object=item" in text
                and "&quest=" in text
                and "&item=" in text
            ),
            "entity_filter": (
                "action=advice&object=list" in text
                and "votetype" in text
                and "voteid" in text
                and "votetrue" in text
            ),
        }

    def _advanced_entry_resources(self, state: RoundState) -> dict[str, Any]:
        round_no = state.round_no
        base = BASE.format(round_no=round_no)
        jobs = [
            self.page_job(
                round_no,
                urllib.parse.urljoin(base, "?m=paper"),
                "pages/paper/index.html",
                label="advanced entry paper",
            ),
            self.page_job(
                round_no,
                urllib.parse.urljoin(base, "?m=chara&type=simple"),
                "pages/chara/m_chara__type_simple.html",
                label="advanced entry chara simple",
            ),
            self.page_job(
                round_no,
                urllib.parse.urljoin(base, "?m=music&type=simple"),
                "pages/music/m_music__type_simple.html",
                label="advanced entry music simple",
            ),
            self.script_job(
                round_no,
                urllib.parse.urljoin(base, "js/paperinfo.js"),
                "scripts/paperinfo.js",
                label="advanced questionnaire client",
            ),
            self.script_job(
                round_no,
                urllib.parse.urljoin(base, "js/info.js"),
                "scripts/info.js",
                label="advanced detail client",
            ),
        ]
        self.fetch_many(jobs, f"v{round_no} advanced-search entry resources")
        round_dir = DATA_ROOT / f"round_{round_no:02d}"
        paper = round_dir / "raw" / "pages" / "paper" / "index.html"
        state.questionnaire_file = paper
        if paper.exists():
            state.add_summary("paper", paper)
        supports: dict[str, dict[str, bool]] = {}
        for category in ("chara", "music"):
            path = (
                round_dir
                / "raw"
                / "pages"
                / category
                / f"m_{category}__type_simple.html"
            )
            if path.exists():
                state.modern_simple_files[category] = path
                state.add_summary(category, path)
                supports[category] = self._advanced_marker_support(self.read_text(path))
            else:
                supports[category] = {
                    "questionnaire_filter": False,
                    "entity_filter": False,
                }
        paper_available = paper.exists()
        paper_text = self.read_text(paper) if paper_available else ""
        paper_client = round_dir / "raw" / "scripts" / "paperinfo.js"
        paper_client_text = self.read_text(paper_client) if paper_client.exists() else ""
        cross_questionnaire: bool | None
        if not paper_available or not paper_client.exists():
            cross_questionnaire = None
            aggregate_questionnaire = None
        else:
            aggregate_questionnaire = (
                "paperall" in paper_text
                and "object=votepaper&text=paper" in paper_client_text
            )
            cross_questionnaire = (
                "object=votepaper&text=paper" in paper_client_text
                and "quest1" in paper_text
                and "quest2" in paper_text
            )
        self._parse_modern_questionnaire_definitions(state)
        return {
            "entry_resources": [
                {
                    "url": job.url,
                    "path": rel_workspace(job.target),
                    "available": job.target.exists(),
                }
                for job in jobs
            ],
            "ranking_support": supports,
            "questionnaire_cross": cross_questionnaire,
            "aggregate_questionnaire": aggregate_questionnaire,
            "paper_available": paper_available,
            "paper_client_available": paper_client.exists(),
        }

    def _advanced_question_specs(self, state: RoundState) -> list[dict[str, Any]]:
        definitions: list[dict[str, Any]] = []
        seen_tokens: set[str] = set()
        for item in state.questionnaire_defs:
            copied = dict(item)
            copied["source_surfaces"] = ["paper_cross"]
            definitions.append(copied)
            seen_tokens.add(str(item.get("value", "")))
        for category, path in sorted(state.modern_simple_files.items()):
            if not path.exists():
                continue
            result = extract_json_after(self.read_text(path), "var questlist =")
            if not result or not isinstance(result[0], list):
                continue
            for item in result[0]:
                if not isinstance(item, dict):
                    continue
                token = str(item.get("value", ""))
                if token in seen_tokens:
                    for existing in definitions:
                        if str(existing.get("value", "")) == token:
                            surfaces = existing.setdefault("source_surfaces", [])
                            surface = f"{category}_ranking_filter"
                            if surface not in surfaces:
                                surfaces.append(surface)
                            break
                    continue
                copied = dict(item)
                copied["source_surfaces"] = [f"{category}_ranking_filter"]
                definitions.append(copied)
                seen_tokens.add(token)
        specs: list[dict[str, Any]] = []
        for index, item in enumerate(definitions, start=1):
            token = str(item.get("value", ""))
            name = clean_text(str(item.get("name", "")))
            surfaces = [str(value) for value in item.get("source_surfaces", [])]
            open_answer = any(
                marker in name
                for marker in (
                    "详细描述",
                    "詳細描述",
                    "请描述",
                    "請描述",
                    "请填写",
                    "請填寫",
                    "请输入",
                    "請輸入",
                    "自由回答",
                    "意见或建议",
                    "意見或建議",
                )
            )
            analytical = bool(token) and not open_answer
            specs.append(
                {
                    "question_index": index,
                    "group": str(item.get("group", "")),
                    "question": name,
                    "token": token,
                    "source_surfaces": ";".join(surfaces),
                    "cross_eligible": "paper_cross" in surfaces,
                    "analytical": analytical,
                    "status": (
                        "pending"
                        if analytical
                        else "intentionally_excluded"
                    ),
                    "exclusion_reason": (
                        ""
                        if analytical
                        else (
                            "open/non-categorical answer offered on a ranking filter surface; "
                            "answer prose is intentionally not enumerated"
                        )
                    ),
                }
            )
        return specs

    def _advanced_question_option_counts(
        self, state: RoundState
    ) -> dict[tuple[str, str], int]:
        """Map official question/answer labels to aggregate respondent counts."""
        round_dir = DATA_ROOT / f"round_{state.round_no:02d}"
        api_dir = round_dir / "raw" / "api" / "questionnaire"
        counts: dict[tuple[str, str], int] = {}
        group_dir = api_dir / "groups"
        if group_dir.exists():
            for path in sorted(group_dir.glob("*.json")):
                try:
                    payload = read_json_path(path)
                except (OSError, EOFError, gzip.BadGzipFile, json.JSONDecodeError):
                    continue
                for row in self._question_answer_rows(
                    payload, round_no=state.round_no, group=path.stem
                ):
                    count = integer_value(row.get("all_count"))
                    if count is not None:
                        counts[(clean_text(str(row.get("question", ""))), clean_text(str(row.get("option", ""))))] = count

        votesex = api_dir / "votesex.json"
        if votesex.exists():
            try:
                payload = read_json_path(votesex)
            except (OSError, EOFError, gzip.BadGzipFile, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
                data = payload["data"]
                quest = payload.get("quest") if isinstance(payload.get("quest"), dict) else {}
                age_title = clean_text(str(quest.get("title", "")))
                age_options = quest.get("value") if isinstance(quest.get("value"), list) else []
                age_counts = data.get("all") if isinstance(data.get("all"), list) else []
                for option_index, option in enumerate(age_options):
                    if option_index < len(age_counts):
                        count = integer_value(age_counts[option_index])
                        if count is not None:
                            counts[(age_title, clean_text(str(option)))] = count
                male = sum(integer_value(value) or 0 for value in data.get("male", []))
                female = sum(integer_value(value) or 0 for value in data.get("female", []))
                for spec in self._advanced_question_specs(state):
                    if "性别" in spec["question"] or "性別" in spec["question"]:
                        counts[(spec["question"], "男性")] = male
                        counts[(spec["question"], "女性")] = female

        votegeo = api_dir / "votegeo.json"
        if votegeo.exists():
            try:
                payload = read_json_path(votegeo)
            except (OSError, EOFError, gzip.BadGzipFile, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
                geo: dict[str, int] = {}
                for entry in payload["data"].get("all", []):
                    if isinstance(entry, dict):
                        count = integer_value(entry.get("value"))
                        if count is not None:
                            geo[clean_text(str(entry.get("name", "")))] = count
                text_counts = payload["data"].get("text", {})
                if isinstance(text_counts, dict):
                    items = payload.get("item", [])
                    for key, entry in text_counts.items():
                        if not isinstance(entry, dict):
                            continue
                        try:
                            item_index = int(str(key)) - 1
                        except ValueError:
                            continue
                        if isinstance(items, list) and 0 <= item_index < len(items):
                            count = integer_value(entry.get("all"))
                            if count is not None:
                                geo[clean_text(str(items[item_index]))] = count
                for spec in self._advanced_question_specs(state):
                    if "居住地" in spec["question"]:
                        for option, count in geo.items():
                            counts[(spec["question"], option)] = count
        return counts

    @staticmethod
    def _advanced_overview(text: str, category: str) -> dict[str, Any]:
        def number(pattern: str) -> int | None:
            match = re.search(pattern, text)
            return int(match.group(1).replace(",", "")) if match else None

        overview = {
            "total_effective_votes": number(r"总有效票数\s*([\d,]+)"),
            "total_first_votes": number(r"总本命票数\s*([\d,]+)"),
            "filtered_entity_count": number(r"过滤后(?:角色|音乐)总数\s*([\d,]+)"),
            "actual_entity_count": number(r"实际总数\s*([\d,]+)"),
            "mean_votes": number(r"平均得票数\s*([\d,]+)"),
            "median_votes": number(r"中位(?:角色|音乐)得票数\s*([\d,]+)"),
        }
        filter_match = re.search(r"当前过滤条件为：\s*(.*?)\s*[。.]", text, re.S)
        overview["official_filter_description"] = (
            clean_text(filter_match.group(1)) if filter_match else ""
        )
        overview["target_category"] = category
        return overview

    def _process_advanced_ranking(
        self,
        job: FetchJob,
        *,
        processed_path: Path,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        record = self.records.get(self.record_key(job))
        index_row = {
            **dict(context),
            "url": job.url,
            "raw_path": rel_workspace(job.target),
            "processed_path": rel_workspace(processed_path),
            "status": "fetch_failed",
            "row_count": 0,
            "error": "",
        }
        if not job.target.exists() or not self._existing_is_valid(job, record):
            if record:
                index_row["error"] = str(record.get("error", "missing/invalid file"))
            else:
                index_row["error"] = "missing official response"
            return index_row
        text = self.read_text(job.target)
        arrays = [
            value
            for value in extract_all_json_after(text, '"rows":')
            if isinstance(value, list)
        ]
        if not arrays:
            index_row["error"] = "official page contains no embedded ranking rows"
            return index_row
        flattened = [
            flatten_summary_record(item)
            for item in arrays[0]
            if isinstance(item, dict)
        ]
        previous_vote: int | None = None
        competition_rank = 0
        rows: list[dict[str, Any]] = []
        for order, row in enumerate(flattened, start=1):
            normalized = dict(row)
            for field_name in ("vote", "first", "weight", "male", "female"):
                number = integer_value(normalized.get(field_name))
                if number is not None:
                    normalized[field_name] = number
            for field_name, value in list(normalized.items()):
                if isinstance(value, str):
                    percentage = percent_number(value)
                    if percentage is not None:
                        normalized[f"{field_name}_percentage_points"] = percentage
            vote = integer_value(normalized.get("vote"))
            if vote != previous_vote:
                competition_rank = order
                previous_vote = vote
            rows.append(
                {
                    "server_order": order,
                    "rank_by_vote": competition_rank,
                    **normalized,
                }
            )
        target_category = str(context.get("target_category", ""))
        payload = {
            "schema_version": 1,
            "round": job.round_no,
            "context": dict(context),
            "overview": self._advanced_overview(text, target_category),
            "rows": rows,
            "source": {
                "url": job.url,
                "method": job.method,
                "request_query": self.request_provenance(job)["request_query"],
                "request_form": self.request_provenance(job)["request_form"],
                "raw_path": rel_workspace(job.target),
                "stored_sha256": sha256_file(job.target),
                "response_sha256": record.get("response_sha256") if record else None,
                "retrieved_at": record.get("retrieved_at") if record else None,
            },
            "derivation": (
                "Rows are losslessly unwrapped from the official embedded FooTable JSON; "
                "count fields are converted to integers and percentage strings receive parallel "
                "*_percentage_points fields; rank_by_vote is computed locally with competition "
                "ranking from official vote counts."
            ),
        }
        write_gzip_json_atomic(processed_path, payload)
        index_row.update(
            {
                "status": "available_crawled",
                "row_count": len(rows),
                "error": "",
                **payload["overview"],
            }
        )
        return index_row

    @staticmethod
    def _pair_cells(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict) or payload.get("cross") is True:
            return []
        data = payload.get("data")
        if not isinstance(data, dict):
            return []
        quest1 = data.get("quest1") if isinstance(data.get("quest1"), dict) else {}
        quest2 = data.get("quest2") if isinstance(data.get("quest2"), dict) else {}
        item1 = quest1.get("value") if isinstance(quest1.get("value"), list) else data.get("item1", [])
        item2 = quest2.get("value") if isinstance(quest2.get("value"), list) else data.get("item2", [])
        matrix = data.get("data") if isinstance(data.get("data"), dict) else {}
        percent = data.get("percent") if isinstance(data.get("percent"), dict) else {}
        percentall = data.get("percentall") if isinstance(data.get("percentall"), list) else []
        rows: list[dict[str, Any]] = []
        for second_index, second_option in enumerate(item2 if isinstance(item2, list) else []):
            values = matrix.get(str(second_index), [])
            within_first = percent.get(str(second_index), [])
            reverse = percentall[second_index] if second_index < len(percentall) else []
            for first_index, first_option in enumerate(item1 if isinstance(item1, list) else []):
                rows.append(
                    {
                        "question1": str(payload.get("title1", quest1.get("title", ""))),
                        "question2": str(payload.get("title2", quest2.get("title", ""))),
                        "question1_option_index": first_index,
                        "question1_option": first_option,
                        "question2_option_index": second_index,
                        "question2_option": second_option,
                        "count": (
                            integer_value(values[first_index])
                            if isinstance(values, list) and first_index < len(values)
                            else None
                        ),
                        "percent_within_question1_option": (
                            within_first[first_index]
                            if isinstance(within_first, list) and first_index < len(within_first)
                            else None
                        ),
                        "percent_within_question2_option": (
                            reverse[first_index]
                            if isinstance(reverse, list) and first_index < len(reverse)
                            else None
                        ),
                        "question1_multi": data.get("multi1"),
                        "question2_multi": data.get("multi2"),
                    }
                )
        return rows

    def _fetch_advanced_questionnaire(
        self, state: RoundState, support: Mapping[str, Any]
    ) -> dict[str, Any]:
        round_no = state.round_no
        round_dir = DATA_ROOT / f"round_{round_no:02d}"
        processed_dir = round_dir / "processed" / "advanced" / "questionnaire"
        base = BASE.format(round_no=round_no)

        # These compact aggregate endpoints provide authoritative cohort sizes
        # for the categorical answer conditions and are reused by the ordinary
        # questionnaire layer.
        self._fetch_modern_aggregate_questionnaire(state)
        self._process_questionnaire_api(state)
        aggregate_paths = [
            round_dir / "raw" / "api" / "questionnaire" / f"{name}.json"
            for name in ("votedate", "votesex", "votegeo")
        ] + [
            round_dir
            / "raw"
            / "api"
            / "questionnaire"
            / "groups"
            / f"{group_id}.json"
            for group_id in sorted(
                state.questionnaire_groups,
                key=lambda value: int(value),
            )
        ]
        specs = self._advanced_question_specs(state)
        analytical_specs = [item for item in specs if item["analytical"]]
        if self.max_items is not None:
            analytical_specs = analytical_specs[: self.max_items]
        write_csv(
            processed_dir / "questions.csv",
            specs,
            [
                "question_index",
                "group",
                "question",
                "token",
                "source_surfaces",
                "cross_eligible",
                "analytical",
                "status",
                "exclusion_reason",
            ],
        )

        ranking_support = support.get("ranking_support", {})
        filter_targets = [
            category
            for category in ("chara", "music")
            if ranking_support.get(category, {}).get("questionnaire_filter")
        ]
        advice_jobs: list[FetchJob] = []
        advice_by_index: dict[int, FetchJob] = {}
        if filter_targets:
            for spec in analytical_specs:
                q_index = int(spec["question_index"])
                url = urllib.parse.urljoin(
                    base,
                    "api.php?"
                    + urllib.parse.urlencode(
                        {
                            "action": "advice",
                            "object": "item",
                            "text": spec["token"],
                        }
                    ),
                )
                job = self.json_job(
                    round_no,
                    url,
                    f"advanced/questionnaire/advice/q_{q_index:03d}.json",
                    label=f"advanced questionnaire advice q{q_index:03d}",
                )
                advice_jobs.append(job)
                advice_by_index[q_index] = job
        self.fetch_many(advice_jobs, f"v{round_no} advanced questionnaire answer catalogues")

        count_lookup = self._advanced_question_option_counts(state)
        option_rows: list[dict[str, Any]] = []
        condition_specs: list[tuple[FetchJob, dict[str, Any], Path]] = []
        for spec in analytical_specs:
            q_index = int(spec["question_index"])
            advice_job = advice_by_index.get(q_index)
            if advice_job is None or not advice_job.target.exists():
                option_rows.append(
                    {
                        **spec,
                        "answer_index": "",
                        "answer_id": "",
                        "answer": "",
                        "expected_cohort": "",
                        "status": (
                            "official_not_offered" if not filter_targets else "fetch_failed"
                        ),
                        "advice_path": (
                            rel_workspace(advice_job.target) if advice_job else ""
                        ),
                    }
                )
                continue
            try:
                options = read_json_path(advice_job.target)
            except (OSError, EOFError, gzip.BadGzipFile, json.JSONDecodeError):
                options = None
            if not isinstance(options, dict):
                option_rows.append(
                    {
                        **spec,
                        "answer_index": "",
                        "answer_id": "",
                        "answer": "",
                        "expected_cohort": "",
                        "status": "fetch_failed",
                        "advice_path": rel_workspace(advice_job.target),
                    }
                )
                continue
            for answer_index, (answer_id, answer) in enumerate(options.items(), start=1):
                answer_text = clean_text(str(answer))
                expected = count_lookup.get((spec["question"], answer_text))
                option_rows.append(
                    {
                        **spec,
                        "answer_index": answer_index,
                        "answer_id": str(answer_id),
                        "answer": answer_text,
                        "expected_cohort": expected,
                        "status": "available_crawled",
                        "advice_path": rel_workspace(advice_job.target),
                    }
                )
                for target_category in filter_targets:
                    query = urllib.parse.urlencode(
                        [
                            ("m", target_category),
                            ("type", "simple"),
                            ("quest", str(spec["token"])),
                            ("item", str(answer_id)),
                        ]
                    )
                    url = urllib.parse.urljoin(base, "?" + query)
                    relative = (
                        "advanced/questionnaire/conditions/"
                        f"q_{q_index:03d}/a_{answer_index:03d}/"
                        f"target_{target_category}.html.gz"
                    )
                    job = self.compressed_page_job(
                        round_no,
                        url,
                        relative,
                        label=(
                            f"advanced questionnaire condition q{q_index:03d} "
                            f"a{answer_index:03d} target {target_category}"
                        ),
                    )
                    processed_path = (
                        processed_dir
                        / "conditions"
                        / f"q_{q_index:03d}"
                        / f"a_{answer_index:03d}"
                        / f"target_{target_category}.json.gz"
                    )
                    context = {
                        "condition_family": "questionnaire_answer",
                        "question_index": q_index,
                        "question_group": spec["group"],
                        "question": spec["question"],
                        "question_token": spec["token"],
                        "answer_index": answer_index,
                        "answer_id": str(answer_id),
                        "answer": answer_text,
                        "expected_cohort": expected,
                        "expected_cohort_source": (
                            "official aggregate questionnaire APIs"
                            if expected is not None
                            else "unavailable"
                        ),
                        "target_category": target_category,
                    }
                    condition_specs.append((job, context, processed_path))

        write_csv(
            processed_dir / "options.csv",
            option_rows,
            [
                "question_index",
                "group",
                "question",
                "token",
                "source_surfaces",
                "cross_eligible",
                "analytical",
                "answer_index",
                "answer_id",
                "answer",
                "expected_cohort",
                "status",
                "advice_path",
                "exclusion_reason",
            ],
        )
        self.fetch_many(
            [job for job, _, _ in condition_specs],
            f"v{round_no} advanced questionnaire-conditioned rankings",
        )
        condition_rows = [
            self._process_advanced_ranking(
                job, processed_path=processed_path, context=context
            )
            for job, context, processed_path in condition_specs
        ]
        condition_fields = union_fieldnames(
            condition_rows,
            preferred=(
                "condition_family",
                "question_index",
                "question_group",
                "question",
                "question_token",
                "answer_index",
                "answer_id",
                "answer",
                "expected_cohort",
                "target_category",
                "status",
                "row_count",
                "url",
                "raw_path",
                "processed_path",
                "error",
            ),
        )
        write_csv(
            processed_dir / "condition_index.csv",
            condition_rows,
            condition_fields,
        )

        pair_specs: list[tuple[FetchJob, dict[str, Any]]] = []
        pair_question_specs = [
            spec for spec in analytical_specs if spec.get("cross_eligible")
        ]
        if support.get("questionnaire_cross"):
            api_url = urllib.parse.urljoin(
                base, "api.php?action=make&object=votepaper&text=paper"
            )
            for left_offset, left in enumerate(pair_question_specs):
                for right in pair_question_specs[left_offset + 1 :]:
                    left_index = int(left["question_index"])
                    right_index = int(right["question_index"])
                    job = self.compressed_json_job(
                        round_no,
                        api_url,
                        (
                            "advanced/questionnaire/pairs/"
                            f"q_{left_index:03d}__q_{right_index:03d}.json.gz"
                        ),
                        method="POST",
                        form=(
                            ("quest1", str(left["token"])),
                            ("quest2", str(right["token"])),
                        ),
                        label=(
                            f"advanced questionnaire pair q{left_index:03d} "
                            f"q{right_index:03d}"
                        ),
                    )
                    pair_specs.append(
                        (
                            job,
                            {
                                "question1_index": left_index,
                                "question1": left["question"],
                                "question1_token": left["token"],
                                "question2_index": right_index,
                                "question2": right["question"],
                                "question2_token": right["token"],
                            },
                        )
                    )
        self.fetch_many(
            [job for job, _ in pair_specs],
            f"v{round_no} advanced questionnaire unordered pairs",
        )
        pair_rows: list[dict[str, Any]] = []
        pair_cells: list[dict[str, Any]] = []
        for job, context in pair_specs:
            record = self.records.get(self.record_key(job))
            row = {
                **context,
                "url": job.url,
                "request_form": json.dumps(list(job.form), ensure_ascii=False),
                "raw_path": rel_workspace(job.target),
                "status": "fetch_failed",
                "cross_conflict": "",
                "cell_count": 0,
                "error": "",
            }
            if job.target.exists() and self._existing_is_valid(job, record):
                try:
                    payload = read_json_path(job.target)
                except (OSError, EOFError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
                    row["error"] = f"{type(exc).__name__}: {exc}"
                else:
                    cells = self._pair_cells(payload)
                    for cell in cells:
                        pair_cells.append(
                            {
                                "round": round_no,
                                **context,
                                **cell,
                                "source": rel_workspace(job.target),
                            }
                        )
                    row.update(
                        {
                            "status": "available_crawled",
                            "cross_conflict": bool(
                                isinstance(payload, dict) and payload.get("cross") is True
                            ),
                            "cell_count": len(cells),
                        }
                    )
            elif record:
                row["error"] = str(record.get("error", "missing/invalid file"))
            else:
                row["error"] = "missing official response"
            pair_rows.append(row)
        write_csv(
            processed_dir / "pair_index.csv",
            pair_rows,
            [
                "question1_index",
                "question1",
                "question1_token",
                "question2_index",
                "question2",
                "question2_token",
                "status",
                "cross_conflict",
                "cell_count",
                "url",
                "request_form",
                "raw_path",
                "error",
            ],
        )
        write_gzip_csv_atomic(
            processed_dir / "pair_cells.csv.gz",
            pair_cells,
            [
                "round",
                "question1_index",
                "question1",
                "question1_token",
                "question1_option_index",
                "question1_option",
                "question2_index",
                "question2",
                "question2_token",
                "question2_option_index",
                "question2_option",
                "count",
                "percent_within_question1_option",
                "percent_within_question2_option",
                "question1_multi",
                "question2_multi",
                "source",
            ],
        )
        return {
            "analytical_questions": sum(item["analytical"] for item in specs),
            "questions_selected_this_run": len(analytical_specs),
            "cross_questions_selected_this_run": len(pair_question_specs),
            "intentionally_excluded_questions": sum(
                not item["analytical"] for item in specs
            ),
            "aggregate_expected": len(aggregate_paths),
            "aggregate_available": sum(
                self._manifest_file_available(path) for path in aggregate_paths
            ),
            "advice_expected": len(advice_jobs),
            "advice_available": sum(
                self._existing_is_valid(job, self.records.get(self.record_key(job)))
                for job in advice_jobs
            ),
            "answer_options": sum(bool(row.get("answer_id")) for row in option_rows),
            "condition_expected": len(condition_specs),
            "condition_available": sum(
                row.get("status") == "available_crawled" for row in condition_rows
            ),
            "pair_expected": len(pair_specs),
            "pair_available": sum(
                row.get("status") == "available_crawled" for row in pair_rows
            ),
            "pair_cells": len(pair_cells),
            "filter_targets": filter_targets,
            "cross_offered": bool(support.get("questionnaire_cross")),
        }

    def _advanced_entity_base_counts(
        self, state: RoundState, category: str
    ) -> dict[str, dict[str, Any]]:
        path = state.modern_simple_files.get(category)
        if path is None or not path.exists():
            return {}
        arrays = [
            value
            for value in extract_all_json_after(self.read_text(path), '"rows":')
            if isinstance(value, list)
        ]
        if not arrays:
            return {}
        counts: dict[str, dict[str, Any]] = {}
        for row in arrays[0]:
            if not isinstance(row, dict) or "id" not in row:
                continue
            item_id = str(row["id"])
            counts[item_id] = {
                "name": clean_text(str(unwrap_footable(row.get("name", "")))),
                "vote": integer_value(row.get("vote")),
                "first": integer_value(row.get("first")),
            }
        return counts

    def _fetch_advanced_entity(
        self, state: RoundState, support: Mapping[str, Any]
    ) -> dict[str, Any]:
        round_no = state.round_no
        round_dir = DATA_ROOT / f"round_{round_no:02d}"
        processed_dir = round_dir / "processed" / "advanced" / "entity"
        base = BASE.format(round_no=round_no)
        ranking_support = support.get("ranking_support", {})
        targets = [
            category
            for category in ("chara", "music")
            if ranking_support.get(category, {}).get("entity_filter")
        ]
        catalog_jobs: dict[str, FetchJob] = {}
        if targets:
            for source_category in ("chara", "music"):
                url = urllib.parse.urljoin(
                    base,
                    "api.php?"
                    + urllib.parse.urlencode(
                        {
                            "action": "advice",
                            "object": "list",
                            "text": source_category,
                        }
                    ),
                )
                catalog_jobs[source_category] = self.json_job(
                    round_no,
                    url,
                    f"advanced/entity/catalog/{source_category}.json",
                    label=f"advanced entity catalogue {source_category}",
                )
        self.fetch_many(
            list(catalog_jobs.values()), f"v{round_no} advanced entity catalogues"
        )

        catalog_rows: list[dict[str, Any]] = []
        condition_specs: list[tuple[FetchJob, dict[str, Any], Path]] = []
        excluded_rows: list[dict[str, Any]] = []
        for source_category in ("chara", "music"):
            job = catalog_jobs.get(source_category)
            catalog: Any = None
            if job and job.target.exists():
                try:
                    catalog = read_json_path(job.target)
                except (OSError, EOFError, gzip.BadGzipFile, json.JSONDecodeError):
                    catalog = None
            if not isinstance(catalog, dict):
                catalog_rows.append(
                    {
                        "source_category": source_category,
                        "source_index": "",
                        "source_id": "",
                        "source_name": "",
                        "base_vote_count": "",
                        "base_first_count": "",
                        "status": (
                            "official_not_offered" if not targets else "fetch_failed"
                        ),
                        "source": rel_workspace(job.target) if job else "",
                    }
                )
                continue
            base_counts = self._advanced_entity_base_counts(state, source_category)
            items = list(catalog.items())
            if self.max_items is not None:
                items = items[: self.max_items]
            for source_index, (source_id, source_name) in enumerate(items, start=1):
                counts = base_counts.get(str(source_id), {})
                source_name_text = clean_text(str(source_name))
                catalog_rows.append(
                    {
                        "source_category": source_category,
                        "source_index": source_index,
                        "source_id": str(source_id),
                        "source_name": source_name_text,
                        "base_name": counts.get("name", ""),
                        "base_vote_count": counts.get("vote"),
                        "base_first_count": counts.get("first"),
                        "status": "available_crawled",
                        "source": rel_workspace(job.target),
                    }
                )
                for condition_kind, votetrue, count_key in (
                    ("any", "0", "vote"),
                    ("first", "1", "first"),
                ):
                    expected = counts.get(count_key)
                    for target_category in targets:
                        context = {
                            "condition_family": "entity_vote",
                            "source_category": source_category,
                            "condition_kind": condition_kind,
                            "source_index": source_index,
                            "source_id": str(source_id),
                            "source_name": source_name_text,
                            "expected_cohort": expected,
                            "expected_cohort_source": (
                                "official unfiltered simple ranking"
                                if expected is not None
                                else "unavailable"
                            ),
                            "target_category": target_category,
                        }
                        if expected == 0:
                            excluded_rows.append(
                                {
                                    **context,
                                    "url": "",
                                    "raw_path": "",
                                    "processed_path": "",
                                    "status": "intentionally_excluded",
                                    "row_count": 0,
                                    "error": (
                                        "zero-sized cohort proven by official base ranking"
                                    ),
                                }
                            )
                            continue
                        query = urllib.parse.urlencode(
                            [
                                ("m", target_category),
                                ("type", "simple"),
                                ("votetype", source_category),
                                ("voteid", str(source_id)),
                                ("votetrue", votetrue),
                            ]
                        )
                        url = urllib.parse.urljoin(base, "?" + query)
                        relative = (
                            "advanced/entity/conditions/"
                            f"{source_category}/{condition_kind}/"
                            f"source_{source_index:04d}/target_{target_category}.html.gz"
                        )
                        condition_job = self.compressed_page_job(
                            round_no,
                            url,
                            relative,
                            label=(
                                f"advanced entity {source_category} {condition_kind} "
                                f"source {source_index:04d} target {target_category}"
                            ),
                        )
                        processed_path = (
                            processed_dir
                            / "conditions"
                            / source_category
                            / condition_kind
                            / f"source_{source_index:04d}"
                            / f"target_{target_category}.json.gz"
                        )
                        condition_specs.append(
                            (condition_job, context, processed_path)
                        )
        write_csv(
            processed_dir / "catalog.csv",
            catalog_rows,
            [
                "source_category",
                "source_index",
                "source_id",
                "source_name",
                "base_name",
                "base_vote_count",
                "base_first_count",
                "status",
                "source",
            ],
        )
        self.fetch_many(
            [job for job, _, _ in condition_specs],
            f"v{round_no} advanced entity-conditioned rankings",
        )
        condition_rows = [
            self._process_advanced_ranking(
                job, processed_path=processed_path, context=context
            )
            for job, context, processed_path in condition_specs
        ]
        condition_rows.extend(excluded_rows)
        condition_fields = union_fieldnames(
            condition_rows,
            preferred=(
                "condition_family",
                "source_category",
                "condition_kind",
                "source_index",
                "source_id",
                "source_name",
                "expected_cohort",
                "target_category",
                "status",
                "row_count",
                "url",
                "raw_path",
                "processed_path",
                "error",
            ),
        )
        write_csv(
            processed_dir / "condition_index.csv",
            condition_rows,
            condition_fields,
        )
        return {
            "targets": targets,
            "catalogue_sources_expected": len(catalog_jobs),
            "catalogue_sources_available": sum(
                self._existing_is_valid(job, self.records.get(self.record_key(job)))
                for job in catalog_jobs.values()
            ),
            "catalog_items": sum(
                row.get("status") == "available_crawled" for row in catalog_rows
            ),
            "condition_expected": len(condition_specs),
            "condition_available": sum(
                row.get("status") == "available_crawled" for row in condition_rows
            ),
            "zero_cohort_conditions_excluded": len(excluded_rows),
        }

    @staticmethod
    def _read_csv_index(path: Path) -> list[dict[str, str]]:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    def crawl_round_advanced(self, round_no: int, *, stage: str | None = None) -> None:
        stage = stage or self.advanced_stage
        state = self.states[round_no]
        self.reconstruct_state(round_no)
        round_dir = DATA_ROOT / f"round_{round_no:02d}"
        summary_path = round_dir / "processed" / "advanced" / "summary.json"
        if summary_path.exists():
            try:
                summary = read_json_path(summary_path)
            except (OSError, json.JSONDecodeError):
                summary = {}
        else:
            summary = {}
        summary.update(
            {
                "schema_version": 1,
                "round": round_no,
                "official_base": BASE.format(round_no=round_no),
                "updated_at": utc_now(),
                "scope": (
                    "bounded analytical advanced-search data: categorical questionnaire "
                    "answers, unordered distinct categorical-question pairs, and nonempty "
                    "character/music any/first-vote atomic cohorts, each against the "
                    "official character/music ranking pages"
                ),
                "intentionally_not_enumerated": [
                    "min/max result display ranges",
                    "client-side keyword search",
                    "open-answer/recommendation-reason prose",
                    "images and fonts",
                    "composite AND/OR condition products beyond the official two-question cross table",
                ],
            }
        )
        if round_no < 5:
            summary["status"] = "official_not_offered"
            summary["reason"] = (
                "The round predates the official advanced-search interface used in rounds 5-9."
            )
            write_json_atomic(summary_path, summary)
            return

        support = self._advanced_entry_resources(state)
        summary["interface_support"] = support
        stages = set(summary.get("stages_completed", []))
        attempted = set(summary.get("stages_attempted", []))
        if stage == "questionnaire":
            questionnaire_result = self._fetch_advanced_questionnaire(
                state, support
            )
            summary["questionnaire"] = questionnaire_result
            attempted.add("questionnaire")
            if (
                questionnaire_result["aggregate_available"]
                == questionnaire_result["aggregate_expected"]
                and questionnaire_result["advice_available"]
                == questionnaire_result["advice_expected"]
                and questionnaire_result["condition_available"]
                == questionnaire_result["condition_expected"]
                and questionnaire_result["pair_available"]
                == questionnaire_result["pair_expected"]
            ):
                stages.add("questionnaire")
            else:
                stages.discard("questionnaire")
        if stage == "entity":
            entity_result = self._fetch_advanced_entity(state, support)
            summary["entity"] = entity_result
            attempted.add("entity")
            if (
                entity_result["catalogue_sources_available"]
                == entity_result["catalogue_sources_expected"]
                and entity_result["condition_available"]
                == entity_result["condition_expected"]
            ):
                stages.add("entity")
            else:
                stages.discard("entity")
        summary["stages_attempted"] = sorted(attempted)
        summary["stages_completed"] = sorted(stages)
        summary["status"] = (
            "available_crawled"
            if not self.circuit_open and attempted.issubset(stages)
            else "fetch_failed"
        )
        if self.circuit_open:
            summary["error"] = self.circuit_reason
        write_json_atomic(summary_path, summary)

    @staticmethod
    def _advanced_status(
        *, offered: bool | None, expected: int, available: int
    ) -> str:
        if offered is False:
            return "official_not_offered"
        if offered is None:
            return "fetch_failed"
        return "available_crawled" if available == expected else "fetch_failed"

    def _manifest_file_available(self, path: Path) -> bool:
        record = self._record_for_path(path)
        if record is None or not path.exists():
            return False
        if path.stat().st_size != record.get("bytes"):
            return False
        return not record.get("sha256") or sha256_file(path) == record.get("sha256")

    def _advanced_integrity_errors(self) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        for record in self.records.values():
            path_text = str(record.get("local_path", ""))
            if "/raw/advanced/" not in path_text:
                continue
            if (
                record.get("status") != 200
                or record.get("error")
                or record.get("success") is False
            ):
                continue
            path = WORKSPACE / path_text
            if not path.exists():
                errors.append({"type": "missing_file", "path": path_text})
                continue
            stored = path.read_bytes()
            if len(stored) != record.get("bytes"):
                errors.append({"type": "stored_byte_count_mismatch", "path": path_text})
            if sha256_bytes(stored) != record.get("sha256"):
                errors.append({"type": "stored_sha256_mismatch", "path": path_text})
            if record.get("storage_encoding") == "gzip":
                try:
                    response = gzip.decompress(stored)
                except (OSError, EOFError, gzip.BadGzipFile) as exc:
                    errors.append(
                        {
                            "type": "invalid_gzip",
                            "path": path_text,
                            "error": str(exc),
                        }
                    )
                    continue
                if len(response) != record.get("response_bytes"):
                    errors.append({"type": "response_byte_count_mismatch", "path": path_text})
                if sha256_bytes(response) != record.get("response_sha256"):
                    errors.append({"type": "response_sha256_mismatch", "path": path_text})
                job = FetchJob(
                    round_no=int(record.get("round", 0)),
                    url=str(record.get("url", "")),
                    target=path,
                    method=str(record.get("method", "GET")),
                    form=tuple(
                        (str(item[0]), str(item[1]))
                        for item in record.get("request_form", [])
                        if isinstance(item, list) and len(item) == 2
                    ),
                    expect=str(record.get("expect", "bytes")),
                    storage_encoding="gzip",
                    label=str(record.get("label", "")),
                )
                valid, reason = self._validate(
                    job, response, str(record.get("content_type", ""))
                )
                if not valid:
                    errors.append(
                        {
                            "type": "decompressed_response_invalid",
                            "path": path_text,
                            "error": reason,
                        }
                    )
        return errors

    def write_advanced_coverage(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for round_no in range(5, 10):
            round_dir = DATA_ROOT / f"round_{round_no:02d}"
            processed = round_dir / "processed" / "advanced"
            summary_path = processed / "summary.json"
            try:
                summary = read_json_path(summary_path) if summary_path.exists() else {}
            except (OSError, json.JSONDecodeError):
                summary = {}
            support = summary.get("interface_support", {}) if isinstance(summary, dict) else {}
            ranking_support = support.get("ranking_support", {}) if isinstance(support, dict) else {}

            entry_paths = {
                "paper": round_dir / "raw" / "pages" / "paper" / "index.html",
                "chara_simple": round_dir / "raw" / "pages" / "chara" / "m_chara__type_simple.html",
                "music_simple": round_dir / "raw" / "pages" / "music" / "m_music__type_simple.html",
                "paper_client": round_dir / "raw" / "scripts" / "paperinfo.js",
                "info_client": round_dir / "raw" / "scripts" / "info.js",
            }
            for name, path in entry_paths.items():
                available = int(self._manifest_file_available(path))
                rows.append(
                    {
                        "round": round_no,
                        "component": f"entry_{name}",
                        "target": "",
                        "expected": 1,
                        "available_crawled": available,
                        "intentionally_excluded": 0,
                        "status": self._advanced_status(
                            offered=True, expected=1, available=available
                        ),
                        "evidence": rel_workspace(path),
                    }
                )

            question_rows = self._read_csv_index(
                processed / "questionnaire" / "questions.csv"
            )
            analytical_questions = sum(
                str(row.get("analytical", "")).lower() == "true"
                for row in question_rows
            )
            cross_questions = sum(
                str(row.get("analytical", "")).lower() == "true"
                and str(row.get("cross_eligible", "")).lower() == "true"
                for row in question_rows
            )
            excluded_questions = sum(
                row.get("status") == "intentionally_excluded" for row in question_rows
            )
            advice_available = sum(
                (
                    round_dir
                    / "raw"
                    / "advanced"
                    / "questionnaire"
                    / "advice"
                    / f"q_{int(row['question_index']):03d}.json"
                ).exists()
                and self._manifest_file_available(
                    round_dir
                    / "raw"
                    / "advanced"
                    / "questionnaire"
                    / "advice"
                    / f"q_{int(row['question_index']):03d}.json"
                )
                for row in question_rows
                if str(row.get("analytical", "")).lower() == "true"
                and str(row.get("question_index", "")).isdigit()
            )
            paper_known = entry_paths["paper"].exists()
            q_offered = (
                any(
                    ranking_support.get(category, {}).get("questionnaire_filter")
                    for category in ("chara", "music")
                )
                if paper_known and ranking_support
                else None
            )
            questionnaire_summary = (
                summary.get("questionnaire", {}) if isinstance(summary, dict) else {}
            )
            aggregate_expected = int(
                questionnaire_summary.get("aggregate_expected", 0) or 0
            )
            aggregate_available = int(
                questionnaire_summary.get("aggregate_available", 0) or 0
            )
            aggregate_value = support.get("aggregate_questionnaire") if support else None
            aggregate_offered = (
                aggregate_value
                if isinstance(aggregate_value, bool) and paper_known
                else None
            )
            rows.append(
                {
                    "round": round_no,
                    "component": "questionnaire_aggregate_apis",
                    "target": "",
                    "expected": aggregate_expected,
                    "available_crawled": aggregate_available,
                    "intentionally_excluded": 0,
                    "status": (
                        "fetch_failed"
                        if aggregate_offered is True and aggregate_expected == 0
                        else self._advanced_status(
                            offered=aggregate_offered,
                            expected=aggregate_expected,
                            available=aggregate_available,
                        )
                    ),
                    "evidence": rel_workspace(
                        round_dir / "raw" / "api" / "questionnaire"
                    ),
                }
            )
            rows.append(
                {
                    "round": round_no,
                    "component": "questionnaire_answer_catalogues",
                    "target": "",
                    "expected": analytical_questions,
                    "available_crawled": advice_available,
                    "intentionally_excluded": excluded_questions,
                    "status": (
                        "fetch_failed"
                        if q_offered is True and analytical_questions == 0
                        else self._advanced_status(
                            offered=q_offered,
                            expected=analytical_questions,
                            available=advice_available,
                        )
                    ),
                    "evidence": rel_workspace(
                        processed / "questionnaire" / "questions.csv"
                    ),
                }
            )

            condition_rows = self._read_csv_index(
                processed / "questionnaire" / "condition_index.csv"
            )
            option_rows = self._read_csv_index(
                processed / "questionnaire" / "options.csv"
            )
            option_count = sum(bool(row.get("answer_id")) for row in option_rows)
            for category in ("chara", "music"):
                page_path = entry_paths[f"{category}_simple"]
                offered: bool | None
                if not page_path.exists():
                    offered = None
                else:
                    offered = bool(
                        ranking_support.get(category, {}).get("questionnaire_filter")
                    )
                selected = [
                    row
                    for row in condition_rows
                    if row.get("target_category") == category
                ]
                available = sum(
                    row.get("status") == "available_crawled" for row in selected
                )
                expected = option_count if offered is not False else 0
                rows.append(
                    {
                        "round": round_no,
                        "component": "questionnaire_atomic_rankings",
                        "target": category,
                        "expected": expected,
                        "available_crawled": available,
                        "intentionally_excluded": excluded_questions,
                        "status": self._advanced_status(
                            offered=offered, expected=expected, available=available
                        ),
                        "evidence": rel_workspace(
                            processed / "questionnaire" / "condition_index.csv"
                        ),
                    }
                )

            pair_rows = self._read_csv_index(
                processed / "questionnaire" / "pair_index.csv"
            )
            pair_expected = cross_questions * (cross_questions - 1) // 2
            pair_available = sum(
                row.get("status") == "available_crawled" for row in pair_rows
            )
            cross_value = support.get("questionnaire_cross") if support else None
            cross_offered = (
                cross_value if isinstance(cross_value, bool) and paper_known else None
            )
            rows.append(
                {
                    "round": round_no,
                    "component": "questionnaire_unordered_pairs",
                    "target": "",
                    "expected": pair_expected if cross_offered is not False else 0,
                    "available_crawled": pair_available,
                    "intentionally_excluded": excluded_questions,
                    "status": self._advanced_status(
                        offered=cross_offered,
                        expected=pair_expected if cross_offered is not False else 0,
                        available=pair_available,
                    ),
                    "evidence": rel_workspace(
                        processed / "questionnaire" / "pair_index.csv"
                    ),
                }
            )

            catalog_rows = self._read_csv_index(processed / "entity" / "catalog.csv")
            entity_condition_rows = self._read_csv_index(
                processed / "entity" / "condition_index.csv"
            )
            entity_ui_known = all(
                entry_paths[f"{category}_simple"].exists()
                for category in ("chara", "music")
            )
            entity_offered = (
                any(
                    ranking_support.get(category, {}).get("entity_filter")
                    for category in ("chara", "music")
                )
                if entity_ui_known and ranking_support
                else None
            )
            for source_category in ("chara", "music"):
                catalogue_file = (
                    round_dir
                    / "raw"
                    / "advanced"
                    / "entity"
                    / "catalog"
                    / f"{source_category}.json"
                )
                available = int(self._manifest_file_available(catalogue_file))
                rows.append(
                    {
                        "round": round_no,
                        "component": "entity_catalogue",
                        "target": source_category,
                        "expected": 1 if entity_offered is not False else 0,
                        "available_crawled": available,
                        "intentionally_excluded": 0,
                        "status": self._advanced_status(
                            offered=entity_offered,
                            expected=1 if entity_offered is not False else 0,
                            available=available,
                        ),
                        "evidence": rel_workspace(catalogue_file),
                    }
                )
            for target_category in ("chara", "music"):
                page_path = entry_paths[f"{target_category}_simple"]
                offered = (
                    bool(ranking_support.get(target_category, {}).get("entity_filter"))
                    if page_path.exists() and ranking_support
                    else None
                )
                selected = [
                    row
                    for row in entity_condition_rows
                    if row.get("target_category") == target_category
                ]
                expected = 0
                catalogue_zero = 0
                for row in catalog_rows:
                    if row.get("status") != "available_crawled" or not row.get("source_id"):
                        continue
                    for field in ("base_vote_count", "base_first_count"):
                        value = row.get(field, "")
                        try:
                            cohort = int(value) if value != "" else None
                        except ValueError:
                            cohort = None
                        if cohort == 0:
                            catalogue_zero += 1
                        else:
                            # Unknown base counts are not treated as zero; the
                            # official condition page remains required.
                            expected += 1
                available = sum(
                    row.get("status") == "available_crawled" for row in selected
                )
                excluded_from_index = sum(
                    row.get("status") == "intentionally_excluded" for row in selected
                )
                excluded = max(excluded_from_index, catalogue_zero)
                rows.append(
                    {
                        "round": round_no,
                        "component": "entity_atomic_rankings",
                        "target": target_category,
                        "expected": expected,
                        "available_crawled": available,
                        "intentionally_excluded": excluded,
                        "status": self._advanced_status(
                            offered=offered, expected=expected, available=available
                        ),
                        "evidence": rel_workspace(
                            processed / "entity" / "condition_index.csv"
                        ),
                    }
                )
            total_excluded = excluded_questions + sum(
                row.get("status") == "intentionally_excluded"
                for row in entity_condition_rows
            )
            rows.append(
                {
                    "round": round_no,
                    "component": "analytical_exclusions",
                    "target": "",
                    "expected": total_excluded,
                    "available_crawled": 0,
                    "intentionally_excluded": total_excluded,
                    "status": "intentionally_excluded",
                    "evidence": (
                        "open/non-categorical questions and zero-sized entity cohorts only"
                    ),
                }
            )

        integrity_errors = self._advanced_integrity_errors()
        all_complete = self.max_items is None and not integrity_errors and all(
            row["status"] in {
                "available_crawled",
                "official_not_offered",
                "intentionally_excluded",
            }
            for row in rows
        )
        relevant_components = {
            "entry_paper",
            "entry_chara_simple",
            "entry_music_simple",
            "entry_paper_client",
            "entry_info_client",
        }
        if self.advanced_stage in {"questionnaire", "all"}:
            relevant_components.update(
                {
                    "questionnaire_answer_catalogues",
                    "questionnaire_aggregate_apis",
                    "questionnaire_atomic_rankings",
                    "questionnaire_unordered_pairs",
                }
            )
        if self.advanced_stage in {"entity", "all"}:
            relevant_components.update(
                {"entity_catalogue", "entity_atomic_rankings"}
            )
        current_rows = [
            row
            for row in rows
            if row["round"] in self.rounds
            and row["component"] in relevant_components
        ]
        current_run_ok = (
            self.max_items is None
            and
            not self.circuit_open
            and not integrity_errors
            and all(row["status"] != "fetch_failed" for row in current_rows)
        )
        payload = {
            "schema_version": 1,
            "generated_at": utc_now(),
            "official_host": "https://touhou.vote/",
            "scope": "Chinese official legacy advanced-search basis, rounds 5-9",
            "requested_rounds_this_run": self.rounds,
            "advanced_stage_this_run": self.advanced_stage,
            "allRequiredChecksPassed": all_complete,
            "all_required_checks_passed": all_complete,
            "current_run_ok": current_run_ok,
            "status_definitions": {
                "available_crawled": "Officially offered and every expected response represented by this row is present and valid.",
                "fetch_failed": "Officially offered/expected, or interface evidence is missing, but one or more files are absent or invalid; never interpreted as official absence.",
                "official_not_offered": "A successfully archived official interface page lacks this component.",
                "intentionally_excluded": "Analytically empty or non-categorical/open content excluded under the documented bounded policy.",
            },
            "bounded_policy": {
                "included": [
                    "all categorical questionnaire-answer atomic filters on character and music rankings",
                    "all unordered pairs of distinct categorical questionnaire questions from the official cross API",
                    "all statistically nonempty character/music any-vote and first-vote atomic filters on character and music rankings",
                ],
                "excluded": [
                    "open-answer and recommendation-reason prose",
                    "min/max and client keyword display filters reproducible locally",
                    "zero-sized entity cohorts proven by the official base ranking",
                    "images and fonts",
                ],
            },
            # Keep the family/combination vocabulary identical to the modern
            # crawler.  Unlike CN10/11, CN5/9 really do expose the official
            # all-answer questionnaire cross-tab, so its parity status is
            # available_crawled here.
            "coverage_contract": advanced_coverage_contract(
                questionnaire_pair_status="available_crawled",
                questionnaire_pair_reason=(
                    "legacy PHP votepaper endpoint returned every unordered "
                    "eligible-question pair matrix"
                ),
            ),
            "integrity_errors": integrity_errors,
            "rows": rows,
        }
        write_json_atomic(ADVANCED_COVERAGE_JSON, payload)
        write_csv(ADVANCED_COVERAGE_CSV, rows, list(rows[0]) if rows else [])
        write_json_atomic(
            ADVANCED_VALIDATION_JSON,
            {
                "generated_at": utc_now(),
                "ok": current_run_ok,
                "all_rounds_complete": all_complete,
                "integrity_errors": integrity_errors,
                "circuit_open": self.circuit_open,
                "circuit_reason": self.circuit_reason,
            },
        )
        report_lines = [
            "# 国区第5—9届高级搜索抓取覆盖",
            "",
            f"生成时间：{payload['generated_at']}",
            "",
            "状态严格区分 `available_crawled`、`fetch_failed`、`official_not_offered`、`intentionally_excluded`。",
            "",
            "| 届 | 组件 | 目标 | 应抓 | 已抓 | 主动排除 | 状态 |",
            "|---:|---|---|---:|---:|---:|---|",
        ]
        for row in rows:
            report_lines.append(
                f"| {row['round']} | {row['component']} | {row['target']} | "
                f"{row['expected']} | {row['available_crawled']} | "
                f"{row['intentionally_excluded']} | {row['status']} |"
            )
        report_lines.extend(
            [
                "",
                "原始高级榜页面以无损 `.html.gz` 保存；清单同时记录压缩文件与解压后 HTTP 响应的字节数和 SHA-256。",
                "问卷交叉 API 以 `.json.gz` 保存，规范化的数值矩阵见各届 `processed/advanced/questionnaire/pair_cells.csv.gz`。",
                "",
            ]
        )
        write_text_atomic(ADVANCED_REPORT_MD, "\n".join(report_lines))
        self.exit_ok = current_run_ok
        return payload

    def crawl_advanced(self) -> None:
        stages = (
            ("questionnaire", "entity")
            if self.advanced_stage == "all"
            else (self.advanced_stage,)
        )
        for stage in stages:
            for round_no in self.rounds:
                print(
                    f"\n=== Chinese official round {round_no} advanced ({stage}) ===",
                    flush=True,
                )
                self.crawl_round_advanced(round_no, stage=stage)
                self.write_source_index(self.states[round_no])
                self.compact_manifest()
                self.write_advanced_coverage()
                if self.circuit_open:
                    print(
                        f"Advanced crawl paused in resumable state: {self.circuit_reason}",
                        file=sys.stderr,
                        flush=True,
                    )
                    break
            if self.circuit_open:
                break
        self.compact_manifest()
        self.write_advanced_coverage()

    def crawl(self) -> None:
        if self.advanced_only:
            self.crawl_advanced()
            return
        for round_no in range(1, 10):
            if round_no not in self.rounds:
                self.reconstruct_state(round_no)
        for round_no in self.rounds:
            print(f"\n=== Chinese official round {round_no} ===", flush=True)
            if self.rebuild_only:
                self.reconstruct_state(round_no)
            elif self.supplemental_only:
                self.crawl_round_supplemental(round_no)
            elif round_no == 1:
                self.crawl_round_1(round_no)
            elif round_no in (2, 3):
                self.crawl_round_2_or_3(round_no)
            elif round_no == 4:
                self.crawl_round_4(round_no)
            else:
                self.crawl_round_modern(round_no)
            self.write_source_index(self.states[round_no])
            self.process_round(self.states[round_no])
            self.compact_manifest()
            self.write_coverage()
            if self.circuit_open:
                print(f"Crawl paused in resumable state: {self.circuit_reason}", file=sys.stderr, flush=True)
                break
        self.compact_manifest()
        self.write_coverage()
        self.validate()

    def reconstruct_state(self, round_no: int) -> None:
        state = self.states[round_no]
        state.local_substitutions = [
            dict(record)
            for record in getattr(self, "local_substitution_records", {}).values()
            if int(record.get("round", 0) or 0) == round_no
        ]
        round_dir = DATA_ROOT / f"round_{round_no:02d}"
        if not round_dir.exists():
            return
        for path in (round_dir / "raw" / "pages").rglob("*.html"):
            state.page_files.add(path)
            relative = path.relative_to(round_dir / "raw" / "pages")
            category = relative.parts[0] if len(relative.parts) > 1 else "root"
            state.summary_files.setdefault(category, set()).add(path)
        paper = round_dir / "raw" / "pages" / "paper" / "index.html"
        if paper.exists():
            state.questionnaire_file = paper
        for path in (round_dir / "raw" / "details").rglob("*.html") if (round_dir / "raw" / "details").exists() else []:
            category = path.parent.name
            state.add_detail(category, path.stem, path)
        source_index = round_dir / "source_index.json"
        if source_index.exists():
            try:
                value = json.loads(source_index.read_text(encoding="utf-8"))
                state.sources = dict(value.get("sources", {}))
            except json.JSONDecodeError:
                pass
        for record in self.records.values():
            if (
                record.get("round") == round_no
                and record.get("status") == 200
                and not record.get("error")
                and record.get("success") is not False
            ):
                url = str(record.get("url", ""))
                method = str(record.get("method", "GET")).upper()
                body_hash = str(record.get("request_body_sha256", sha256_bytes(b"")))
                source_key = (
                    url
                    if method == "GET" and body_hash == sha256_bytes(b"")
                    else f"{method} {url} body_sha256={body_hash}"
                )
                state.sources[source_key] = str(record.get("local_path", ""))
        # Reconstruct the full expected legacy detail set from the already saved
        # result pages, not merely from files that happened to finish downloading.
        # This keeps a partial/504-interrupted run classified as fetch_failed.
        legacy_texts = [self.read_text(path) for path in state.page_files if path.exists()]
        if round_no == 1:
            pattern = re.compile(r"(?:\./)?index\.php\?mod=json&type=(chara|music|work)&id=([0-9]+)")
            for text in legacy_texts:
                for match in pattern.finditer(text):
                    category, item_id = match.groups()
                    state.add_detail(category, item_id, round_dir / "raw" / "details" / category / f"{item_id}.html")
        elif round_no in (2, 3):
            type_map = {"1": "chara", "2": "music", "3": "work", "4": "work_characters"}
            pattern = re.compile(r"(?:\./)?\?m=j&t=([1-4])&i=([0-9]+)")
            for text in legacy_texts:
                for match in pattern.finditer(text):
                    category, item_id = type_map[match.group(1)], match.group(2)
                    state.add_detail(category, item_id, round_dir / "raw" / "details" / category / f"{item_id}.html")
        elif round_no == 4:
            pattern = re.compile(r"(?:\./)?\?v=json&m=(chara|music|work|cp)&i=([0-9]+)")
            for text in legacy_texts:
                for match in pattern.finditer(text):
                    category, item_id = match.groups()
                    state.add_detail(category, item_id, round_dir / "raw" / "details" / category / f"{item_id}.html")
            for category in ("chara", "music", "work", "cp"):
                for path in state.summary_files.get(category, set()):
                    if not path.exists():
                        continue
                    result = extract_json_after(self.read_text(path), "var vote =")
                    if not result or not isinstance(result[0], list):
                        continue
                    for item in result[0]:
                        if isinstance(item, dict) and "id" in item:
                            item_id = str(item["id"])
                            state.add_detail(
                                category,
                                item_id,
                                round_dir / "raw" / "details" / category / f"{item_id}.html",
                            )
        if round_no >= 5:
            for category in ("chara", "music", "work", "cp"):
                simple = round_dir / "raw" / "pages" / category / f"m_{category}__type_simple.html"
                if simple.exists():
                    state.modern_simple_files[category] = simple
            if round_no in {8, 9}:
                for category in ("chara", "music"):
                    crossvote_page = (
                        round_dir
                        / "raw"
                        / "pages"
                        / category
                        / f"m_{category}__type_crossvote.html"
                    )
                    if not crossvote_page.exists():
                        continue
                    text = self.read_text(crossvote_page)
                    type_match = re.search(r"var\s+type\s*=\s*[\"']([^\"']+)", text)
                    number_match = re.search(r"var\s+number\s*=\s*[\"']([^\"']+)", text)
                    filter_match = re.search(r"var\s+filter\s*=\s*[\"']([^\"']+)", text)
                    if type_match and number_match and filter_match:
                        state.expected_crossvote[type_match.group(1)] = {
                            "filter": number_match.group(1),
                            "rate": filter_match.group(1),
                    "expanded_filter": "100" if category == "chara" else number_match.group(1),
                    "expanded_rate": "1",
                    "expanded_scope": (
                                "official_api_expanded_top100_lowest_accepted_rate_not_complete_matrix"
                                if category == "chara"
                                else "official_api_default_topn_lowest_accepted_rate_not_complete_matrix"
                            ),
                        }
            self._parse_modern_questionnaire_definitions(state)
            self._discover_modern_details(state)

    def write_source_index(self, state: RoundState) -> None:
        round_dir = DATA_ROOT / f"round_{state.round_no:02d}"
        local_substitutions = [
            dict(record)
            for record in getattr(self, "local_substitution_records", {}).values()
            if int(record.get("round", 0) or 0) == state.round_no
        ]
        state.local_substitutions = sorted(
            local_substitutions,
            key=lambda value: (str(value.get("category", "")), str(value.get("url", ""))),
        )
        write_json_atomic(
            round_dir / "source_index.json",
            {
                "round": state.round_no,
                "official_base": BASE.format(round_no=state.round_no),
                "generated_at": utc_now(),
                "sources": dict(sorted(state.sources.items())),
                "local_substitutions": state.local_substitutions,
                "reason_pages_followed": 0,
                "note": "Raw official records remain unmerged; same-title aggregation is a later processed step.",
            },
        )

    def process_round(self, state: RoundState) -> None:
        round_dir = DATA_ROOT / f"round_{state.round_no:02d}"
        processed = round_dir / "processed"
        processed.mkdir(parents=True, exist_ok=True)
        self._process_summary_pages(state)
        self._process_questionnaire_html(state)
        self._process_detail_html(state)
        if state.round_no >= 4:
            self._process_modern_embedded_data(state)
        if state.round_no >= 5:
            self._process_questionnaire_api(state)
            self._process_item_api_indexes(state)

    def _process_summary_pages(self, state: RoundState) -> None:
        output_dir = DATA_ROOT / f"round_{state.round_no:02d}" / "processed" / "summary_tables"
        long_rows: list[dict[str, Any]] = []
        summary_index: list[dict[str, Any]] = []
        all_paths = sorted({path for paths in state.summary_files.values() for path in paths})
        for path in all_paths:
            if not path.exists():
                continue
            text = self.read_text(path)
            parsed = parse_html_tables(text)
            relative = path.relative_to(DATA_ROOT / f"round_{state.round_no:02d}" / "raw").as_posix()
            target = output_dir / (relative.replace("/", "__") + ".tables.json")
            write_json_atomic(target, {"source": rel_workspace(path), **parsed})
            page_rows = list(tables_to_long_rows(parsed, rel_workspace(path)))
            long_rows.extend(page_rows)
            summary_index.append(
                {
                    "source": rel_workspace(path),
                    "parsed": rel_workspace(target),
                    "table_count": len(parsed.get("tables", [])),
                    "cell_count": len(page_rows),
                }
            )
        write_csv(
            output_dir / "cells.csv",
            long_rows,
            [
                "source", "table_index", "table_heading", "table_id", "row_index",
                "cell_index", "cell_type", "text", "number", "percent", "numeric_tokens",
            ],
        )
        write_csv(output_dir / "index.csv", summary_index, ["source", "parsed", "table_count", "cell_count"])

    def _process_questionnaire_html(self, state: RoundState) -> None:
        path = state.questionnaire_file
        if path is None or not path.exists():
            return
        output_dir = DATA_ROOT / f"round_{state.round_no:02d}" / "processed" / "questionnaire"
        parsed = parse_html_tables(self.read_text(path))
        write_json_atomic(output_dir / "html_tables.json", {"source": rel_workspace(path), **parsed})
        write_csv(
            output_dir / "html_table_cells.csv",
            tables_to_long_rows(parsed, rel_workspace(path)),
            [
                "source", "table_index", "table_heading", "table_id", "row_index",
                "cell_index", "cell_type", "text", "number", "percent", "numeric_tokens",
            ],
        )

    def _process_detail_html(self, state: RoundState) -> None:
        round_dir = DATA_ROOT / f"round_{state.round_no:02d}"
        output_dir = round_dir / "processed" / "details"
        index_rows: list[dict[str, Any]] = []
        for category, items in sorted(state.details.items()):
            for item_id, path in sorted(items.items(), key=lambda item: (len(item[0]), item[0])):
                if not path.exists():
                    index_rows.append({
                        "round": state.round_no,
                        "category": category,
                        "id": item_id,
                        "entity_key": entity_key(state.round_no, category, item_id),
                        "html_path": rel_workspace(path),
                        "status": "missing",
                    })
                    continue
                text = self.read_text(path)
                parsed = parse_html_tables(text)
                headings = [entry["text"] for entry in parsed.get("headings", [])]
                title_match = re.search(r"<title>(.*?)</title>", text, re.I | re.S)
                title = clean_text(title_match.group(1)) if title_match else ""
                payload = {
                    "round": state.round_no,
                    "category": category,
                    "id": item_id,
                    "title": title,
                    "headings": headings,
                    "source": rel_workspace(path),
                    "reason_body_included": False,
                    "tables": parsed.get("tables", []),
                    "parse_error": parsed.get("parse_error", ""),
                }
                target = output_dir / category / f"{item_id}.json"
                write_json_atomic(target, payload)
                index_rows.append({
                    "round": state.round_no,
                    "category": category,
                    "id": item_id,
                    # This is the same stable key emitted by the portable
                    # vote dataset.  Keeping it in the crawl-side index lets
                    # detail/questionnaire files join the CN1–9 ranking rows
                    # without relying on translated display names.
                    "entity_key": entity_key(state.round_no, category, item_id),
                    "title": title,
                    "primary_heading": headings[0] if headings else "",
                    "html_path": rel_workspace(path),
                    "parsed_path": rel_workspace(target),
                    "table_count": len(parsed.get("tables", [])),
                    "status": "ok",
                })
        write_csv(
            output_dir / "index.csv",
            index_rows,
            ["round", "category", "id", "entity_key", "title", "primary_heading", "html_path", "parsed_path", "table_count", "status"],
        )

    def _process_modern_embedded_data(self, state: RoundState) -> None:
        round_dir = DATA_ROOT / f"round_{state.round_no:02d}"
        output_dir = round_dir / "processed" / "rankings"
        for category, paths in sorted(state.summary_files.items()):
            for path in sorted(paths):
                if not path.exists():
                    continue
                text = self.read_text(path)
                arrays: list[Any] = []
                if state.round_no == 4:
                    result = extract_json_after(text, "var vote =")
                    if result:
                        arrays = [result[0]]
                elif state.round_no >= 5:
                    arrays = extract_all_json_after(text, '"rows":')
                    if category == "paper":
                        vote_result = extract_json_after(text, "vote =")
                        if vote_result:
                            arrays.insert(0, vote_result[0])
                arrays = [value for value in arrays if isinstance(value, list)]
                if not arrays:
                    continue
                slug = path.stem
                payload = {
                    "round": state.round_no,
                    "category": category,
                    "source": rel_workspace(path),
                    "datasets": arrays,
                    "raw_records_are_unmerged": True,
                }
                target = output_dir / category / f"{slug}.json"
                write_json_atomic(target, payload)
                for dataset_index, records in enumerate(arrays):
                    dict_rows = [record for record in records if isinstance(record, dict)]
                    if not dict_rows:
                        continue
                    flattened = [flatten_summary_record(record) for record in dict_rows]
                    fields = union_fieldnames(flattened, preferred=("id", "list", "index", "name", "jpname", "group", "vote", "first", "weight"))
                    write_csv(output_dir / category / f"{slug}.dataset_{dataset_index}.csv", flattened, fields)

    @staticmethod
    def _question_answer_rows(payload: Any, *, round_no: int, category: str = "", item_id: str = "", group: str = "") -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        questions = payload.get("data")
        if isinstance(questions, dict):
            questions = [questions]
        if not isinstance(questions, list):
            return []
        rows: list[dict[str, Any]] = []
        payload_titles = payload.get("title") if isinstance(payload.get("title"), list) else []
        for question_index, question in enumerate(questions):
            if not isinstance(question, dict):
                continue
            quest = question.get("quest") if isinstance(question.get("quest"), dict) else {}
            title = str(quest.get("title") or (payload_titles[question_index] if question_index < len(payload_titles) else ""))
            options = quest.get("value") if isinstance(quest.get("value"), list) else question.get("item")
            if not isinstance(options, list):
                options = []
            data = question.get("data") if isinstance(question.get("data"), dict) else {}
            percent = question.get("percent") if isinstance(question.get("percent"), dict) else {}
            for option_index, option in enumerate(options):
                row: dict[str, Any] = {
                    "round": round_no,
                    "category": category,
                    "id": item_id,
                    "entity_key": (
                        entity_key(round_no, category, item_id)
                        if category and item_id
                        else ""
                    ),
                    "group": group,
                    "question_index": question_index,
                    "question_id": quest.get("index", ""),
                    "question": title,
                    "multi": quest.get("multi", question.get("multi", "")),
                    "option_index": option_index,
                    "option": option,
                }
                for sex in ("all", "male", "female", "sum"):
                    values = data.get(sex)
                    if isinstance(values, list) and option_index < len(values):
                        row[f"{sex}_count"] = values[option_index]
                    percentages = percent.get(sex)
                    if isinstance(percentages, list) and option_index < len(percentages):
                        row[f"{sex}_percent"] = percentages[option_index]
                totals = question.get("total") if isinstance(question.get("total"), dict) else {}
                for sex in ("all", "male", "female", "diff"):
                    if sex in totals:
                        row[f"total_{sex}"] = totals[sex]
                rows.append(row)
        return rows

    def _process_questionnaire_api(self, state: RoundState) -> None:
        round_dir = DATA_ROOT / f"round_{state.round_no:02d}"
        api_dir = round_dir / "raw" / "api" / "questionnaire"
        output_dir = round_dir / "processed" / "questionnaire"
        answer_rows: list[dict[str, Any]] = []
        group_dir = api_dir / "groups"
        if group_dir.exists():
            for path in sorted(group_dir.glob("*.json"), key=lambda p: (len(p.stem), p.stem)):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                answer_rows.extend(self._question_answer_rows(payload, round_no=state.round_no, group=path.stem))
        fields = [
            "round", "group", "question_index", "question_id", "question", "multi", "option_index", "option",
            "all_count", "male_count", "female_count", "sum_count", "all_percent", "male_percent", "female_percent",
            "total_all", "total_male", "total_female", "total_diff",
        ]
        write_csv(output_dir / "answers.csv", answer_rows, fields)
        write_json_atomic(
            output_dir / "api_index.json",
            {
                "round": state.round_no,
                "votedate": rel_workspace(api_dir / "votedate.json") if (api_dir / "votedate.json").exists() else None,
                "votesex": rel_workspace(api_dir / "votesex.json") if (api_dir / "votesex.json").exists() else None,
                "votegeo": rel_workspace(api_dir / "votegeo.json") if (api_dir / "votegeo.json").exists() else None,
                "group_files": [rel_workspace(path) for path in sorted(group_dir.glob("*.json"))] if group_dir.exists() else [],
                "answer_rows": len(answer_rows),
            },
        )

    def _process_item_api_indexes(self, state: RoundState) -> None:
        round_dir = DATA_ROOT / f"round_{state.round_no:02d}"
        api_root = round_dir / "raw" / "api" / "items"
        output_dir = round_dir / "processed" / "item_apis"
        index_rows: list[dict[str, Any]] = []
        answer_rows: list[dict[str, Any]] = []
        sex_age_rows: list[dict[str, Any]] = []
        geo_rows: list[dict[str, Any]] = []
        if not api_root.exists():
            write_csv(output_dir / "index.csv", [], ["round", "category", "id", "entity_key", "votedate", "votesex", "votegeo", "votepaper", "complete"])
            return
        for category_dir in sorted(path for path in api_root.iterdir() if path.is_dir()):
            for item_dir in sorted((path for path in category_dir.iterdir() if path.is_dir()), key=lambda p: (len(p.name), p.name)):
                paths = {name: item_dir / f"{name}.json" for name in ("votedate", "votesex", "votegeo", "votepaper")}
                index_rows.append({
                    "round": state.round_no,
                    "category": category_dir.name,
                    "id": item_dir.name,
                    # Keep the item-level API index joinable to the detail
                    # index and the portable CN ranking/advanced tables.  The
                    # key is deliberately based on the official item id, not
                    # on a translated display name which can change between
                    # old vote pages.
                    "entity_key": entity_key(state.round_no, category_dir.name, item_dir.name),
                    **{name: rel_workspace(path) if path.exists() else "" for name, path in paths.items()},
                    "complete": all(path.exists() for path in paths.values()),
                })
                paper_path = paths["votepaper"]
                if paper_path.exists():
                    try:
                        payload = json.loads(paper_path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        pass
                    else:
                        answer_rows.extend(
                            self._question_answer_rows(
                                payload,
                                round_no=state.round_no,
                                category=category_dir.name,
                                item_id=item_dir.name,
                            )
                        )
                sex_path = paths["votesex"]
                if sex_path.exists():
                    try:
                        payload = json.loads(sex_path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        payload = None
                    if isinstance(payload, dict):
                        quest = payload.get("quest") if isinstance(payload.get("quest"), dict) else {}
                        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                        options = quest.get("value") if isinstance(quest.get("value"), list) else []
                        for option_index, option in enumerate(options):
                            row = {
                                "round": state.round_no,
                                "category": category_dir.name,
                                "id": item_dir.name,
                                "entity_key": entity_key(state.round_no, category_dir.name, item_dir.name),
                                "question": quest.get("title", ""),
                                "option_index": option_index,
                                "option": option,
                            }
                            for sex in ("all", "male", "female"):
                                values = data.get(sex)
                                if isinstance(values, list) and option_index < len(values):
                                    row[sex] = values[option_index]
                            sex_age_rows.append(row)
                geo_path = paths["votegeo"]
                if geo_path.exists():
                    try:
                        payload = json.loads(geo_path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        payload = None
                    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
                        data = payload["data"]
                        series_maps: dict[str, dict[str, Any]] = {}
                        for series in ("all", "sum", "male", "female", "per", "maleper", "femaleper"):
                            entries = data.get(series)
                            if isinstance(entries, list):
                                series_maps[series] = {
                                    str(entry.get("key", entry.get("name", ""))): entry
                                    for entry in entries if isinstance(entry, dict)
                                }
                        keys = sorted({key for mapping in series_maps.values() for key in mapping})
                        for key in keys:
                            first = next((mapping[key] for mapping in series_maps.values() if key in mapping), {})
                            row = {
                                "round": state.round_no,
                                "category": category_dir.name,
                                "id": item_dir.name,
                                "entity_key": entity_key(state.round_no, category_dir.name, item_dir.name),
                                "geo_key": key,
                                "geo_name": first.get("name", ""),
                            }
                            for series, mapping in series_maps.items():
                                if key in mapping:
                                    row[series] = mapping[key].get("value")
                            geo_rows.append(row)
        write_csv(
            output_dir / "index.csv",
            index_rows,
            ["round", "category", "id", "entity_key", "votedate", "votesex", "votegeo", "votepaper", "complete"],
        )
        write_csv(
            output_dir / "questionnaire_answers.csv",
            answer_rows,
                [
                    "round", "category", "id", "entity_key", "group", "question_index", "question_id", "question", "multi",
                    "option_index", "option", "all_count", "male_count", "female_count", "sum_count",
                    "all_percent", "male_percent", "female_percent", "total_all", "total_male", "total_female", "total_diff",
                ],
        )
        write_csv(
            output_dir / "sex_age.csv",
            sex_age_rows,
            ["round", "category", "id", "entity_key", "question", "option_index", "option", "all", "male", "female"],
        )
        write_csv(
            output_dir / "geography.csv",
            geo_rows,
            ["round", "category", "id", "entity_key", "geo_key", "geo_name", "all", "sum", "male", "female", "per", "maleper", "femaleper"],
        )

    def compact_manifest(self) -> None:
        with self._lock:
            records = [dict(record) for record in self.records.values()]
        records.sort(key=lambda item: (item.get("round", 0), item.get("local_path", ""), item.get("method", ""), item.get("url", "")))
        part = MANIFEST_PATH.with_name(f".{MANIFEST_PATH.name}.part")
        with part.open("w", encoding="utf-8", newline="") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        os.replace(part, MANIFEST_PATH)

    def _record_for_path(self, path: Path) -> dict[str, Any] | None:
        relative = rel_workspace(path)
        successes = [
            record
            for record in self.records.values()
            if record.get("local_path") == relative
            and record.get("status") == 200
            and not record.get("error")
            and record.get("success") is not False
        ]
        return successes[-1] if successes else None

    def coverage_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        local_records = list(
            getattr(self, "local_substitution_records", {}).values()
            if isinstance(getattr(self, "local_substitution_records", {}), Mapping)
            else []
        )
        all_categories = ("chara", "music", "work", "work_characters", "cp", "game", "paper")
        summary_offered: dict[int, set[str]] = {
            1: {"chara", "music", "work", "paper"},
            2: {"chara", "music", "work", "work_characters", "cp", "game", "paper"},
            3: {"chara", "music", "work", "work_characters", "cp", "game", "paper"},
            4: {"chara", "music", "work", "cp", "game", "paper"},
            **{
                number: {"chara", "music", "work", "cp", "game", "paper"}
                for number in range(5, 10)
            },
        }
        detail_offered: dict[int, set[str]] = {
            1: {"chara", "music"},
            2: {"chara", "music", "work", "work_characters"},
            3: {"chara", "music", "work", "work_characters"},
            4: {"chara", "music", "work", "cp"},
            **{
                number: {"chara", "music", "work", "cp"}
                for number in range(5, 10)
            },
        }

        for round_no in range(1, 10):
            state = self.states[round_no]
            round_dir = DATA_ROOT / f"round_{round_no:02d}"
            for category in all_categories:
                summary_paths = state.summary_files.get(category, set())
                summary_downloaded = sum(path.exists() for path in summary_paths)
                detail_map = state.details.get(category, {})
                detail_expected = len(state.detail_ids.get(category, set())) or len(detail_map)
                details_downloaded = sum(path.exists() for path in detail_map.values())

                available = bool(summary_downloaded or details_downloaded)
                if category == "game":
                    if round_no in (2, 3):
                        available = any("s_4" in path.stem for path in state.summary_files.get("work", set()))
                    elif round_no == 4:
                        available = any("t_game" in path.stem for path in state.summary_files.get("work", set()))
                elif category == "work_characters" and round_no in (2, 3):
                    available = details_downloaded > 0

                main_summary_available = available
                if round_no == 1 and category in {"chara", "music"}:
                    # Local workbooks may replace only alternate sort views;
                    # the canonical step=1 page is still required for official
                    # ids and detail discovery.
                    main_summary_available = any(
                        "step_1" in path.stem
                        for path in summary_paths
                        if path.exists()
                    )
                elif round_no >= 5 and category in {"chara", "music", "work", "cp"}:
                    main_summary_available = (
                        round_dir / "raw" / "pages" / category / f"m_{category}__type_simple.html"
                    ).exists()
                elif round_no >= 5 and category == "game":
                    game_dir = round_dir / "raw" / "pages" / "game"
                    main_summary_available = any(
                        path.exists()
                        for path in (game_dir / "m_game__type_simple.html", game_dir / "index.html")
                    )
                elif round_no >= 5 and category == "paper":
                    main_summary_available = (round_dir / "raw" / "pages" / "paper" / "index.html").exists()
                elif round_no == 4 and category == "cp":
                    # The default CP page omits one-vote combinations; s=1 is the
                    # official complete list required for full coverage.
                    main_summary_available = any("s_1" in path.stem for path in summary_paths if path.exists())

                if category not in summary_offered[round_no]:
                    summary_status = "official_not_offered"
                elif main_summary_available:
                    summary_status = "available_crawled"
                else:
                    summary_status = "fetch_failed"

                if category not in detail_offered[round_no]:
                    detail_status = "official_not_offered"
                elif detail_expected > 0 and details_downloaded == detail_expected:
                    detail_status = "available_crawled"
                else:
                    detail_status = "fetch_failed"

                api_counts: dict[str, int] = {}
                item_api_offered = round_no >= 5 and category in {"chara", "music", "work", "cp"}
                if item_api_offered:
                    for api_name in ("votedate", "votesex", "votegeo", "votepaper"):
                        api_counts[api_name] = sum(
                            (round_dir / "raw" / "api" / "items" / category / item_id / f"{api_name}.json").exists()
                            for item_id in state.detail_ids.get(category, set())
                        )
                    if (
                        detail_expected > 0
                        and all(api_counts.get(name, 0) == detail_expected for name in ("votedate", "votesex", "votegeo", "votepaper"))
                    ):
                        item_api_status = "available_crawled"
                    else:
                        item_api_status = "fetch_failed"
                else:
                    item_api_status = "official_not_offered"

                questionnaire_groups_expected = len(state.questionnaire_groups) if category == "paper" else 0
                questionnaire_groups_downloaded = 0
                if category == "paper" and round_no >= 5:
                    group_dir = round_dir / "raw" / "api" / "questionnaire" / "groups"
                    questionnaire_groups_downloaded = len(list(group_dir.glob("*.json"))) if group_dir.exists() else 0
                if category != "paper":
                    questionnaire_status = "official_not_offered"
                elif round_no <= 4:
                    questionnaire_status = (
                        "available_crawled"
                        if state.questionnaire_file and state.questionnaire_file.exists()
                        else "fetch_failed"
                    )
                elif (
                    questionnaire_groups_expected > 0
                    and questionnaire_groups_downloaded == questionnaire_groups_expected
                    and all(
                        (round_dir / "raw" / "api" / "questionnaire" / f"{name}.json").exists()
                        for name in ("votedate", "votesex", "votegeo")
                    )
                ):
                    questionnaire_status = "available_crawled"
                else:
                    questionnaire_status = "fetch_failed"

                crossvote_offered = round_no in {8, 9} and category in {"chara", "music"}
                crossvote_dir = round_dir / "raw" / "api" / "crossvote"
                default_parameters = state.expected_crossvote.get(category, {})
                default_filter = str(default_parameters.get("filter", ""))
                default_rate = str(default_parameters.get("rate", ""))
                default_path = (
                    crossvote_dir / f"{category}_filter_{default_filter}_rate_{default_rate}.json"
                    if default_filter and default_rate
                    else None
                )
                expanded_filter = str(
                    default_parameters.get(
                        "expanded_filter",
                        "100" if category == "chara" else default_filter,
                    )
                )
                expanded_rate = str(default_parameters.get("expanded_rate", "1"))
                expanded_path = crossvote_dir / f"{category}_filter_{expanded_filter}_rate_{expanded_rate}.json"
                crossvote_default_available = bool(default_path and default_path.exists())
                crossvote_expanded_available = expanded_path.exists()
                if not crossvote_offered:
                    crossvote_status = "official_not_offered"
                elif crossvote_default_available and crossvote_expanded_available:
                    crossvote_status = "available_crawled"
                else:
                    crossvote_status = "fetch_failed"

                offered_component_statuses = [summary_status]
                if category in detail_offered[round_no]:
                    offered_component_statuses.append(detail_status)
                if item_api_offered:
                    offered_component_statuses.append(item_api_status)
                if category == "paper":
                    offered_component_statuses.append(questionnaire_status)
                if crossvote_offered:
                    offered_component_statuses.append(crossvote_status)
                if all(status == "official_not_offered" for status in offered_component_statuses):
                    overall_status = "official_not_offered"
                elif "fetch_failed" in offered_component_statuses:
                    overall_status = "fetch_failed"
                else:
                    overall_status = "available_crawled"

                failures = [
                    record
                    for record in self.records.values()
                    if record.get("round") == round_no
                    and record.get("success") is False
                    and (
                        f"/{category}/" in str(record.get("local_path", ""))
                        or str(record.get("label", "")).startswith(category)
                    )
                ]
                local_for_component = [
                    record
                    for record in local_records
                    if int(record.get("round", 0) or 0) == round_no
                    and str(record.get("category", "")) == category
                ]
                local_source_status = (
                    "available_local_substitute"
                    if local_for_component
                    else "not_used"
                )
                rows.append({
                    "round": round_no,
                    "category": category,
                    "overall_status": overall_status,
                    "summary_status": summary_status,
                    "detail_status": detail_status,
                    "item_api_status": item_api_status,
                    "questionnaire_status": questionnaire_status,
                    "crossvote_status": crossvote_status,
                    "available": available,
                    "summary_pages_expected_or_discovered": len(summary_paths),
                    "summary_pages_downloaded": summary_downloaded,
                    "summary_pages_omitted_by_policy": len(local_for_component),
                    "local_source_status": local_source_status,
                    "local_source_evidence": display_path(LOCAL_SOURCE_MANIFEST_PATH)
                    if local_for_component
                    else "",
                    "local_source_workbooks": json.dumps(
                        sorted({str(record.get("workbook", "")) for record in local_for_component}),
                        ensure_ascii=False,
                    ),
                    "local_source_hashes": json.dumps(
                        sorted({str(record.get("workbook_sha256", "")) for record in local_for_component}),
                        ensure_ascii=False,
                    ),
                    "detail_ids_discovered": len(state.detail_ids.get(category, set())),
                    "detail_pages_expected": detail_expected,
                    "detail_pages_downloaded": details_downloaded,
                    "votedate_json": api_counts.get("votedate", 0),
                    "votesex_json": api_counts.get("votesex", 0),
                    "votegeo_json": api_counts.get("votegeo", 0),
                    "votepaper_json": api_counts.get("votepaper", 0),
                    "questionnaire_groups_expected": questionnaire_groups_expected,
                    "questionnaire_groups_downloaded": questionnaire_groups_downloaded,
                    "crossvote_default_available": crossvote_default_available,
                    "crossvote_default_parameters": json.dumps(
                        {"filter": default_filter, "rate": default_rate} if default_filter and default_rate else {},
                        ensure_ascii=False,
                    ),
                    "crossvote_expanded_available": crossvote_expanded_available if crossvote_offered else False,
                    "crossvote_expanded_parameters": json.dumps(
                        {
                            "filter": expanded_filter,
                            "rate": expanded_rate,
                            "scope": default_parameters.get(
                                "expanded_scope",
                                (
                                    "official_api_expanded_top100_lowest_accepted_rate_not_complete_matrix"
                                    if category == "chara"
                                    else "official_api_default_topn_lowest_accepted_rate_not_complete_matrix"
                                ),
                            ),
                        }
                        if crossvote_offered
                        else {},
                        ensure_ascii=False,
                    ),
                    "fetch_failure_count": len(failures),
                    "fetch_failure_http_statuses": json.dumps(sorted({item.get("status") for item in failures if item.get("status") is not None})),
                    "reason_pages_followed": 0,
                    "notes": " | ".join(state.notes),
                })
        return rows

    def write_coverage(self) -> None:
        rows = self.coverage_rows()
        payload = {
            "generated_at": utc_now(),
            "official_host": "https://touhou.vote/",
            "scope": "Chinese official popularity-poll rounds 1-9",
            "raw_layer_policy": "No same-title or cross-work merging in raw data; every round/entry remains traceable.",
            "reason_body_policy": "Vote-reason endpoints were not requested.",
            "local_source_manifest": display_path(LOCAL_SOURCE_MANIFEST_PATH),
            "local_source_validation": getattr(self, "local_source_validation", {}),
            "status_definitions": {
                "available_crawled": "The official component is offered and all currently expected files for it are present.",
                "available_local_substitute": "Only a deliberately redundant ranking view is satisfied by a hash/header/row-validated local workbook; it is not an official HTTP response.",
                "official_not_offered": "The official navigation/interface for this round does not offer this component.",
                "fetch_failed": "The official component is offered but one or more expected files are missing or a transient fetch failed; rerun is safe.",
            },
            "transient_failures_are_not_official_absence": True,
            "rows": rows,
        }
        write_json_atomic(COVERAGE_JSON, payload)
        fields = list(rows[0]) if rows else []
        write_csv(COVERAGE_CSV, rows, fields)

    def validate(self) -> None:
        errors: list[dict[str, Any]] = []
        checked_files = 0
        json_files = 0
        success_records = [
            record
            for record in self.records.values()
            if record.get("status") == 200
            and not record.get("error")
            and record.get("success") is not False
        ]
        for record in success_records:
            path = WORKSPACE / str(record.get("local_path", ""))
            if not path.exists():
                errors.append({"type": "missing_file", "path": record.get("local_path"), "url": record.get("url")})
                continue
            checked_files += 1
            try:
                stored = path.read_bytes()
            except OSError as exc:
                errors.append(
                    {
                        "type": "read_error",
                        "path": record.get("local_path"),
                        "error": str(exc),
                    }
                )
                continue
            if len(stored) != record.get("bytes"):
                errors.append({"type": "byte_count_mismatch", "path": record.get("local_path")})
            actual_hash = sha256_bytes(stored)
            if actual_hash != record.get("sha256"):
                errors.append({"type": "sha256_mismatch", "path": record.get("local_path")})
            storage_encoding = record.get("storage_encoding") or (
                "gzip" if path.suffix == ".gz" else "identity"
            )
            if storage_encoding == "gzip":
                try:
                    response = gzip.decompress(stored)
                except (EOFError, gzip.BadGzipFile, OSError) as exc:
                    errors.append(
                        {
                            "type": "invalid_gzip",
                            "path": record.get("local_path"),
                            "error": str(exc),
                        }
                    )
                    continue
            elif storage_encoding == "identity":
                response = stored
            else:
                errors.append(
                    {
                        "type": "unknown_storage_encoding",
                        "path": record.get("local_path"),
                        "storage_encoding": storage_encoding,
                    }
                )
                continue
            if record.get("response_bytes") not in (None, len(response)):
                errors.append(
                    {
                        "type": "response_byte_count_mismatch",
                        "path": record.get("local_path"),
                    }
                )
            if (
                record.get("response_sha256")
                and sha256_bytes(response) != record.get("response_sha256")
            ):
                errors.append(
                    {
                        "type": "response_sha256_mismatch",
                        "path": record.get("local_path"),
                    }
                )
            job = FetchJob(
                round_no=int(record.get("round", 0)),
                url=str(record.get("url", "")),
                target=path,
                method=str(record.get("method", "GET")),
                form=tuple(
                    (str(item[0]), str(item[1]))
                    for item in record.get("request_form", [])
                    if isinstance(item, list) and len(item) == 2
                ),
                expect=str(record.get("expect", "bytes")),
                storage_encoding=("gzip" if storage_encoding == "gzip" else ""),
                label=str(record.get("label", "")),
            )
            valid, reason = self._validate(
                job, response, str(record.get("content_type", ""))
            )
            if not valid:
                errors.append(
                    {
                        "type": "invalid_response",
                        "path": record.get("local_path"),
                        "error": reason,
                    }
                )
            elif job.expect == "json":
                json_files += 1
        coverage = self.coverage_rows()
        incomplete_rows = [
            {"round": row["round"], "category": row["category"]}
            for row in coverage
            if row.get("overall_status") == "fetch_failed"
        ]
        manifest_errors = list(errors)
        manifest_integrity_ok = not manifest_errors
        local_records = list(
            getattr(self, "local_substitution_records", {}).values()
            if isinstance(getattr(self, "local_substitution_records", {}), Mapping)
            else []
        )
        local_source_used = bool(local_records)
        local_validation = getattr(self, "local_source_validation", {})
        if local_source_used:
            # Recheck the file hash at final validation time in case an editor
            # changed a workbook while the long crawl was running.
            local_validation = validate_local_workbooks()
            self.local_source_validation = local_validation
        local_source_integrity_ok = (
            bool(local_validation.get("valid", False)) if local_source_used else True
        )
        if local_source_used and not local_source_integrity_ok:
            errors.append({
                "type": "local_source_invalidated",
                "path": display_path(LOCAL_SOURCE_MANIFEST_PATH),
                "error": "workbook hash/sheet/header validation failed after substitution",
            })
        # ``raw_crawl_complete`` is intentionally false when a local workbook
        # substituted an HTTP view.  ``required_data_complete`` is the queue
        # gate: it remains true because only redundant views are substituted and
        # all detail/questionnaire/API requirements still have to pass.
        raw_crawl_complete = not incomplete_rows and not local_source_used
        required_data_complete = not incomplete_rows and local_source_integrity_ok
        # Keep the historical key as the required-data alias for older queue/UI
        # readers; new consumers should use the explicit pair above.
        crawl_complete = required_data_complete
        payload = {
            "generated_at": utc_now(),
            "ok": manifest_integrity_ok and local_source_integrity_ok and required_data_complete,
            "manifest_integrity_ok": manifest_integrity_ok,
            "local_source_integrity_ok": local_source_integrity_ok,
            "local_source_used": local_source_used,
            "local_source_manifest": display_path(LOCAL_SOURCE_MANIFEST_PATH),
            "raw_crawl_complete": raw_crawl_complete,
            "required_data_complete": required_data_complete,
            "crawl_complete": crawl_complete,
            "manifest_records": len(self.records),
            "successful_records": len(success_records),
            "checked_files": checked_files,
            "valid_json_files": json_files,
            "errors": errors,
            "incomplete_coverage_rows": incomplete_rows,
            "coverage_rows": len(coverage),
            "workers_configured": self.workers,
            # Keep ``workers_hard_cap`` as a compatibility key, but make its
            # meaning explicit: it is this run's configurable adaptive rail.
            "workers_hard_cap": int(
                getattr(self, "worker_ceiling", MAX_WORKERS)
            ),
            "workers_absolute_hard_cap": ABSOLUTE_MAX_WORKERS,
            "request_limit_ceiling": int(
                getattr(self, "request_limit_ceiling", MAX_BATCH_REQUESTS)
            ),
            "batch_pause_ceiling_seconds": float(
                getattr(self, "batch_pause_ceiling", MAX_BATCH_PAUSE_SECONDS)
            ),
            "minimum_seconds_between_request_starts": 0.0,
            "request_limit": int(getattr(self, "batch_size", 0)),
            "downloaded_this_run": self.downloaded,
            "skipped_this_run": self.skipped,
            "satisfied_by_local_source_this_run": int(getattr(self, "local_substituted", 0)),
            "failed_this_run": self.failed,
        }
        write_json_atomic(VALIDATION_JSON, payload)
        print(
            f"Validation: ok={payload['ok']} integrity={manifest_integrity_ok} "
            f"crawl_complete={crawl_complete} raw_crawl_complete={raw_crawl_complete} "
            f"local={len(local_records)} checked={checked_files} json={json_files} errors={len(errors)}",
            flush=True,
        )


def parse_rounds(value: str) -> list[int]:
    selected: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text), int(end_text)
            selected.update(range(start, end + 1))
        else:
            selected.add(int(part))
    invalid = sorted(number for number in selected if number < 1 or number > 9)
    if invalid:
        raise argparse.ArgumentTypeError(f"rounds must be within 1-9; got {invalid}")
    return sorted(selected)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rounds", type=parse_rounds, default=list(range(1, 10)), help="Rounds such as 1-9 or 1,4,8-9 (default: 1-9)")
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Starting concurrent HTTP workers (default: 5; must not exceed --worker-ceiling)",
    )
    parser.add_argument(
        "--worker-ceiling",
        type=int,
        default=None,
        help=(
            "Configurable adaptive concurrency ceiling (default: 10; "
            f"absolute maximum: {ABSOLUTE_MAX_WORKERS})"
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Explicitly resume from hash-validated manifest checkpoints "
            "(resuming is also the default when --refresh is absent)"
        ),
    )
    parser.add_argument("--refresh", action="store_true", help="Redownload existing successful resources")
    parser.add_argument(
        "--reuse-local-workbooks",
        "--reuse-workbooks",
        "--skip-redundant-views",
        dest="reuse_local_workbooks",
        action="store_true",
        help=(
            "Use hash/header/row-validated TouhouVote_cn.xlsx and "
            "TouhouVote_music_cn.xlsx only for redundant v1 step=2/3/4 "
            "ranking views; retain step=1, details, questionnaires, APIs, "
            "cross-votes, and advanced-search resources."
        ),
    )
    parser.add_argument("--no-item-apis", action="store_true", help="Skip the four per-entry APIs in rounds 5-9")
    parser.add_argument(
        "--supplemental-only",
        action="store_true",
        help=(
            "Fetch/process only aggregate questionnaire and official-default crossvote resources; "
            "skip large ranking/detail/item-API batches"
        ),
    )
    parser.add_argument(
        "--advanced-only",
        action="store_true",
        help=(
            "Fetch/process only the bounded advanced-search basis for rounds 5-9: "
            "categorical questionnaire conditions and pairs, then nonempty "
            "character/music any/first-vote atomic conditions"
        ),
    )
    parser.add_argument(
        "--advanced-stage",
        choices=("questionnaire", "entity", "all"),
        default="all",
        help=(
            "Advanced-only substage (default: all). 'all' runs questionnaire "
            "answer catalogues/conditional rankings/unordered pairs before entity conditions."
        ),
    )
    parser.add_argument(
        "--max-items",
        type=int,
        help=(
            "Testing only: cap each ordinary detail category and each advanced "
            "question/entity catalogue; capped runs are never marked complete"
        ),
    )
    parser.add_argument("--retries", type=int, default=4, help="Attempts per resource (default: 4)")
    parser.add_argument("--timeout", type=int, default=90, help="HTTP timeout seconds (default: 90)")
    parser.add_argument(
        "--request-limit",
        type=int,
        default=None,
        help="Maximum network requests completed in one checkpoint/cooldown window (default: configured ceiling)",
    )
    parser.add_argument(
        "--request-limit-ceiling",
        type=int,
        default=None,
        help=(
            "Configurable request-budget ceiling (default: 30; "
            f"absolute maximum: {ABSOLUTE_MAX_BATCH_REQUESTS})"
        ),
    )
    parser.add_argument(
        "--batch-size",
        dest="legacy_batch_size",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--batch-pause",
        type=float,
        default=None,
        help="Normal cooldown seconds between batches (default: configured ceiling)",
    )
    parser.add_argument(
        "--batch-pause-ceiling",
        type=float,
        default=None,
        help=(
            "Configurable normal cooldown ceiling (default: 3 seconds; "
            f"absolute maximum: {ABSOLUTE_MAX_BATCH_PAUSE_SECONDS:g} seconds)"
        ),
    )
    parser.add_argument(
        "--transient-failure-threshold",
        type=int,
        default=None,
        help="Stop a phase after this many transient failures (default: min(6, request limit))",
    )
    parser.add_argument(
        "--import-existing-temp",
        action="store_true",
        help="Promote already downloaded .tmp_cn_* official probes before crawling/rebuilding",
    )
    parser.add_argument("--rebuild-only", action="store_true", help="Do not use network; rebuild processed files/coverage from local raw data")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        worker_ceiling = int(
            _requested_ceiling(
                args.worker_ceiling,
                env_name=ENV_WORKER_CEILING,
                default=DEFAULT_WORKER_CEILING,
                absolute=ABSOLUTE_MAX_WORKERS,
                integer=True,
            )
        )
        request_limit_ceiling = int(
            _requested_ceiling(
                args.request_limit_ceiling,
                env_name=ENV_REQUEST_LIMIT_CEILING,
                default=DEFAULT_REQUEST_LIMIT_CEILING,
                absolute=ABSOLUTE_MAX_BATCH_REQUESTS,
                integer=True,
            )
        )
        batch_pause_ceiling = float(
            _requested_ceiling(
                args.batch_pause_ceiling,
                env_name=ENV_BATCH_PAUSE_CEILING,
                default=DEFAULT_BATCH_PAUSE_CEILING,
                absolute=ABSOLUTE_MAX_BATCH_PAUSE_SECONDS,
                integer=False,
            )
        )
    except ValueError as exc:
        parser.error(str(exc))
    workers = 5 if args.workers is None else args.workers
    batch_pause = (
        batch_pause_ceiling if args.batch_pause is None else args.batch_pause
    )
    if args.resume and args.refresh:
        parser.error("--resume and --refresh are mutually exclusive")
    if args.advanced_only and args.supplemental_only:
        parser.error("--advanced-only and --supplemental-only are mutually exclusive")
    if args.advanced_only and any(number < 5 for number in args.rounds):
        parser.error("--advanced-only supports official legacy advanced-search rounds 5-9")
    if args.max_items is not None and args.max_items < 1:
        parser.error("--max-items must be at least 1")
    if workers < 1 or workers > worker_ceiling:
        parser.error(
            f"--workers must be between 1 and configured worker ceiling "
            f"{worker_ceiling}"
        )
    if args.request_limit is not None and args.legacy_batch_size is not None:
        parser.error("--request-limit and deprecated --batch-size are mutually exclusive")
    request_limit = (
        args.request_limit
        if args.request_limit is not None
        else args.legacy_batch_size
        if args.legacy_batch_size is not None
        else request_limit_ceiling
    )
    if request_limit < 1:
        parser.error("--request-limit must be at least 1")
    if request_limit > request_limit_ceiling:
        parser.error(
            f"--request-limit must be at most configured request-limit ceiling "
            f"{request_limit_ceiling}"
        )
    if batch_pause < 0 or batch_pause > batch_pause_ceiling:
        parser.error(
            f"--batch-pause must be between 0 and configured batch-pause ceiling "
            f"{batch_pause_ceiling:g} seconds"
        )
    transient_failure_threshold = (
        min(6, request_limit)
        if args.transient_failure_threshold is None
        else args.transient_failure_threshold
    )
    if transient_failure_threshold < 1 or transient_failure_threshold > request_limit:
        parser.error(
            f"--transient-failure-threshold must be between 1 and "
            f"the request limit ({request_limit})"
        )
    try:
        crawler = Crawler(
            rounds=args.rounds,
            workers=workers,
            refresh=args.refresh,
            no_item_apis=args.no_item_apis,
            max_items=args.max_items,
            retries=max(1, args.retries),
            timeout=max(10, args.timeout),
            delay=0.0,
            batch_size=request_limit,
            batch_pause=max(0.0, batch_pause),
            transient_failure_threshold=max(1, transient_failure_threshold),
            import_existing_temp=args.import_existing_temp,
            supplemental_only=args.supplemental_only,
            advanced_only=args.advanced_only,
            advanced_stage=args.advanced_stage,
            rebuild_only=args.rebuild_only,
            reuse_local_workbooks=args.reuse_local_workbooks,
            worker_ceiling=worker_ceiling,
            request_limit_ceiling=request_limit_ceiling,
            batch_pause_ceiling=batch_pause_ceiling,
        )
        crawler.crawl()
    except KeyboardInterrupt:
        print("Interrupted. Existing files and the manifest journal are resumable.", file=sys.stderr)
        return 130
    return 0 if crawler.exit_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
