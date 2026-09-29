#!/usr/bin/env python3
"""Process the downloaded character comments without inventing semantics.

The crawler keeps one JSON document per entity and a compressed flat file per
round.  This module turns those documents into stable, analysis-friendly
tables, while retaining the original text and an explicit provenance link for
every row.  Derived fields describe text shape only; no sentiment or topic
label is inferred.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import statistics
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "metadata" / "character_comments_manifest.json"
DEFAULT_OUTPUT = ROOT / "data_processed" / "character_comments"
DEFAULT_REPORT = ROOT / "analysis_results" / "character_comments"
SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    value = str(value).replace("\r", "").replace("\x00", "")
    return "\n".join(re.sub(r"[ \t　]+", " ", line).strip() for line in value.split("\n") if line.strip())


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def script_class(value: str) -> str:
    if not value:
        return "empty"
    counts = Counter()
    for char in value:
        code = ord(char)
        if 0x3040 <= code <= 0x30FF:
            counts["ja"] += 1
        elif 0x4E00 <= code <= 0x9FFF:
            counts["han"] += 1
        elif char.isascii() and char.isalpha():
            counts["latin"] += 1
        elif not char.isspace() and not char.isdigit() and not re.match(r"[\W_]", char, re.UNICODE):
            counts["other"] += 1
    present = [key for key in ("han", "ja", "latin", "other") if counts[key]]
    return present[0] if len(present) == 1 else ("mixed" if present else "symbols_or_numbers")


def atomic_write(path: Path, writer) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with open(fd, "w", encoding="utf-8-sig", newline="") as handle:
            writer(handle)
        Path(name).replace(path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fields: list[str]) -> None:
    rows = list(rows)
    def emit(handle):
        out = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        out.writeheader()
        out.writerows(rows)
    atomic_write(path, emit)


def write_csv_gz(path: Path, rows: Iterable[Mapping[str, Any]], fields: list[str]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp.gz", dir=path.parent)
    try:
        with open(fd, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
            import io
            with io.TextIOWrapper(compressed, encoding="utf-8-sig", newline="", write_through=True) as text:
                out = csv.DictWriter(text, fieldnames=fields, extrasaction="ignore")
                out.writeheader()
                out.writerows(rows)
        Path(name).replace(path)
    finally:
        Path(name).unlink(missing_ok=True)


COMMENT_FIELDS = [
    "region", "round", "category", "entity_id", "entity_name", "rank", "comment_index",
    "text", "raw_text", "author", "is_primary", "submitted_at", "text_normalized",
    "text_sha256", "char_count", "line_count", "script_class", "has_url", "has_html_marker",
    "is_blank", "is_exact_duplicate", "duplicate_of_index", "source_kind", "source_url", "source_sha256",
]
ENTITY_FIELDS = [
    "region", "round", "entity_id", "entity_name", "rank", "status", "error", "comments_raw",
    "comments_nonempty", "comments_unique", "exact_duplicates", "avg_char_count", "median_char_count",
    "source_kind", "source_url", "source_sha256", "entity_path",
]
ROUND_FIELDS = [
    "region", "round", "entities_expected", "entities_ok", "entities_error", "entities_with_comments",
    "comments_raw", "comments_nonempty", "comments_unique", "exact_duplicates", "blank_comments",
]


def process(manifest_path: Path = DEFAULT_INPUT, output_dir: Path = DEFAULT_OUTPUT, report_dir: Path = DEFAULT_REPORT) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest.get("records", [])
    if not isinstance(records, list):
        raise ValueError("character comments manifest records must be a list")
    comments: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    rounds: dict[tuple[str, int], dict[str, Any]] = {}
    input_errors: list[dict[str, Any]] = []
    seen_entities: set[tuple[str, int, str]] = set()
    for record in records:
        if not isinstance(record, Mapping):
            input_errors.append({"error": "non-object manifest record"})
            continue
        region, round_no = str(record.get("region", "")), int(record.get("round", 0))
        entity_key = (region, round_no, str(record.get("entity_id", "")))
        if entity_key in seen_entities:
            input_errors.append({"entity": entity_key, "error": "duplicate entity in source manifest"})
        seen_entities.add(entity_key)
        key = (region, round_no)
        aggregate = rounds.setdefault(key, {"region": region, "round": round_no, "entities_expected": 0, "entities_ok": 0, "entities_error": 0, "entities_with_comments": 0, "comments_raw": 0, "comments_nonempty": 0, "comments_unique": 0, "exact_duplicates": 0, "blank_comments": 0})
        aggregate["entities_expected"] += 1
        entity_path = ROOT / str(record.get("entity_path", ""))
        try:
            entity = json.loads(entity_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            input_errors.append({"entity_path": str(entity_path), "error": f"cannot read entity: {exc}"})
            aggregate["entities_error"] += 1
            continue
        status = "error" if entity.get("error") else "ok"
        for field, expected in (("region", region), ("round", round_no), ("entity_id", str(record.get("entity_id", "")))):
            actual = str(entity.get(field, ""))
            if actual != str(expected):
                input_errors.append({"entity_path": str(entity_path), "error": f"{field} mismatch: manifest={expected!r}, entity={actual!r}"})
        aggregate["entities_ok" if status == "ok" else "entities_error"] += 1
        raw_comments = entity.get("comments") if isinstance(entity.get("comments"), list) else []
        if int(record.get("comment_count") or 0) != len(raw_comments):
            input_errors.append({"entity_path": str(entity_path), "error": f"comment_count mismatch: manifest={record.get('comment_count')}, entity={len(raw_comments)}"})
        seen: dict[str, int] = {}
        nonempty = unique = duplicates = blank = 0
        lengths: list[int] = []
        for index, item in enumerate(raw_comments, 1):
            item = item if isinstance(item, Mapping) else {}
            raw_text = clean_text(item.get("raw_text", item.get("text", "")))
            text = clean_text(item.get("text", raw_text))
            normalized = text.casefold()
            digest = text_sha256(normalized)
            duplicate_of = seen.get(digest, "") if normalized else ""
            is_blank = not bool(text)
            if is_blank:
                blank += 1
            else:
                nonempty += 1
                lengths.append(len(text))
            if duplicate_of:
                duplicates += 1
            elif normalized:
                seen[digest] = index
                unique += 1
            comments.append({
                "region": region, "round": round_no, "category": "character", "entity_id": entity.get("entity_id", record.get("entity_id", "")),
                "entity_name": entity.get("entity_name", record.get("entity_name", "")), "rank": entity.get("rank", record.get("rank", "")), "comment_index": index,
                "text": text, "raw_text": raw_text, "author": item.get("author", ""), "is_primary": item.get("is_primary", ""), "submitted_at": item.get("submitted_at", ""),
                "text_normalized": normalized, "text_sha256": digest if normalized else "", "char_count": len(text), "line_count": text.count("\n") + (1 if text else 0),
                "script_class": script_class(text), "has_url": bool(re.search(r"(?:https?://|www\\.)", text, re.I)), "has_html_marker": bool(re.search(r"<[^>]+>|&(?:lt|gt|amp);", text, re.I)),
                "is_blank": is_blank, "is_exact_duplicate": bool(duplicate_of), "duplicate_of_index": duplicate_of,
                "source_kind": entity.get("source_kind", record.get("source_kind", "")), "source_url": (entity.get("source") or {}).get("url", ""),
                "source_sha256": (entity.get("source") or {}).get("sha256", ""),
            })
        if nonempty:
            aggregate["entities_with_comments"] += 1
        aggregate["comments_raw"] += len(raw_comments)
        aggregate["comments_nonempty"] += nonempty
        aggregate["comments_unique"] += unique
        aggregate["exact_duplicates"] += duplicates
        aggregate["blank_comments"] += blank
        source = entity.get("source") if isinstance(entity.get("source"), Mapping) else {}
        entities.append({
            "region": region, "round": round_no, "entity_id": entity.get("entity_id", record.get("entity_id", "")), "entity_name": entity.get("entity_name", record.get("entity_name", "")),
            "rank": entity.get("rank", record.get("rank", "")), "status": status, "error": entity.get("error", ""), "comments_raw": len(raw_comments), "comments_nonempty": nonempty,
            "comments_unique": unique, "exact_duplicates": duplicates, "avg_char_count": round(statistics.mean(lengths), 3) if lengths else "", "median_char_count": statistics.median(lengths) if lengths else "",
            "source_kind": entity.get("source_kind", record.get("source_kind", "")), "source_url": source.get("url", ""), "source_sha256": source.get("sha256", ""), "entity_path": record.get("entity_path", ""),
        })
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv_gz(output_dir / "comments.csv.gz", comments, COMMENT_FIELDS)
    write_csv(output_dir / "entity_summary.csv", sorted(entities, key=lambda r: (r["region"], r["round"], str(r["entity_id"]))), ENTITY_FIELDS)
    round_rows = [rounds[key] for key in sorted(rounds)]
    write_csv(output_dir / "round_summary.csv", round_rows, ROUND_FIELDS)
    outputs = {
        "comments": output_dir / "comments.csv.gz",
        "entity_summary": output_dir / "entity_summary.csv",
        "round_summary": output_dir / "round_summary.csv",
    }
    try:
        input_manifest_label = manifest_path.relative_to(ROOT).as_posix()
    except ValueError:
        input_manifest_label = manifest_path.as_posix()
    summary = {
        "schema_version": SCHEMA_VERSION, "generated_at": utc_now(), "input_manifest": input_manifest_label,
        "source_manifest_schema_version": manifest.get("schema_version"), "content_policy": "text-shape processing only; no sentiment/topic inference",
        "records": len(records), "entities": len(entities), "comments_raw": len(comments), "comments_nonempty": sum(not row["is_blank"] for row in comments),
        "comments_unique": sum(not row["is_exact_duplicate"] and not row["is_blank"] for row in comments), "exact_duplicates": sum(row["is_exact_duplicate"] for row in comments),
        "blank_comments": sum(row["is_blank"] for row in comments), "input_errors": input_errors,
        "outputs": {name: {"path": display_path(path), "sha256": file_sha256(path), "bytes": path.stat().st_size} for name, path in outputs.items()},
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "processing_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (report_dir / "processing_summary.md").write_text("# Character comment processing\n\n" + "\n".join(f"- {key}: {value}" for key, value in summary.items() if key not in {"outputs", "input_errors"}) + "\n\nText is preserved as source data; derived fields describe shape, duplicates, and provenance only.\n", encoding="utf-8")
    run_manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": summary["generated_at"],
        "input": {"path": display_path(manifest_path), "sha256": file_sha256(manifest_path), "records": len(records)},
        "outputs": summary["outputs"],
        "counts": {key: summary[key] for key in ("entities", "comments_raw", "comments_nonempty", "comments_unique", "exact_duplicates", "blank_comments")},
        "input_error_count": len(input_errors),
    }
    (report_dir / "processing_run_manifest.json").write_text(json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    summary = process(args.manifest.resolve(), args.output_dir.resolve(), args.report_dir.resolve())
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["input_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
