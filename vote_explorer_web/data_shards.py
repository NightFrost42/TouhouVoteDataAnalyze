"""Stream large CSVs into lossless, bounded web shards; no statistics run here."""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
import sys
import tempfile
from itertools import islice
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vote_explorer.data_chunks import iter_csv_rows

SOURCES = {
    "covote_pairs": "analysis_covote_pairs_all.csv",
    "character_music_covote": "analysis_character_music_covote_all.csv",
    "entity_questionnaire": "analysis_entity_questionnaire_all.csv.gz",
}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def prune_unreferenced(output, names):
    """Only delete obsolete content-addressed files in this generated directory."""
    for path in output.iterdir():
        if re.fullmatch(r"[0-9a-f]{64}\.json(?:\.gz)?", path.name) and path.name not in names:
            path.unlink()


def write_content(output: Path, value, suffix=".json"):
    raw = encoded(value)
    if suffix.endswith(".gz"):
        raw = gzip.compress(raw, compresslevel=6, mtime=0)
    digest = hashlib.sha256(raw).hexdigest()
    name = digest + suffix
    (output / name).write_bytes(raw)
    return {"path": name, "bytes": len(raw), "sha256": digest}


def selection_key(kind, row):
    label = row.get("round_label") or row["region"].upper() + row["round"]
    if kind == "covote_pairs":
        scope = row.get("pair_category") or ("music" if "music" in row.get("source_type", "") else "character")
        return [kind, label, scope]
    if kind == "entity_questionnaire":
        return [kind, label, row["category"], row["question_key"]]
    return [kind, label]


def build_data_shards(data: Path, output: Path, rows_per_shard=2000):
    output.mkdir(parents=True, exist_ok=True)
    index = {"schema_version": 1, "client_statistics": False, "entries": {}, "sources": {}}
    for kind, filename in SOURCES.items():
        staging = tempfile.TemporaryDirectory(prefix=".tmp-shards-", dir=output)
        spool_paths = {}
        buffers = defaultdict(list)
        columns = None
        total = 0
        buffered_rows = 0

        def flush(key):
            nonlocal buffered_rows
            rows = buffers.pop(key)
            buffered_rows -= len(rows)
            path = Path(staging.name) / hashlib.sha256(key.encode()).hexdigest()
            spool_paths[key] = path
            with path.open("ab") as handle:
                for row in rows:
                    handle.write(encoded([row[c] for c in columns]) + b"\n")

        def emit(key, rows):
            # Factor repeated provenance and categorical strings without losing types.
            defaults = {k: rows[0][k] for k in columns if all(r[k] == rows[0][k] for r in rows)}
            varying = [k for k in columns if k not in defaults]
            payload = {"columns": varying, "defaults": defaults, "values": [[r[k] for k in varying] for r in rows]}
            entry = write_content(output, payload, ".json.gz")
            entry["rows"] = len(rows)
            index["entries"].setdefault(key, []).append(entry)

        for row in iter_csv_rows(data / filename, compressed=filename.endswith(".gz")):
            if columns is None:
                columns = list(row)
            key = json.dumps(selection_key(kind, row), ensure_ascii=False, separators=(",", ":"))
            buffers[key].append(row)
            buffered_rows += 1
            total += 1
            if len(buffers[key]) >= rows_per_shard:
                flush(key)
            elif buffered_rows >= 20000:
                flush(max(buffers, key=lambda k: len(buffers[k])))
        for key in list(buffers):
            flush(key)
        # Regroup spooled rows into full shards: bounded RAM must not multiply
        # HTTP requests when the input interleaves thousands of selection keys.
        try:
            for key, path in sorted(spool_paths.items()):
                with path.open("rb") as handle:
                    while lines := list(islice(handle, rows_per_shard)):
                        emit(key, [dict(zip(columns, json.loads(line))) for line in lines])
        finally:
            staging.cleanup()
        index["sources"][kind] = {"file": filename, "rows": total, "columns": columns or []}
    # Publish the new index only after all immutable content is available.
    with tempfile.NamedTemporaryFile(dir=output, suffix=".tmp", delete=False) as handle:
        handle.write(encoded(index))
        temporary = Path(handle.name)
    temporary.replace(output / "index.json")
    prune_unreferenced(output, {e["path"] for group in index["entries"].values() for e in group})
    return index


def snapshot_available(s):
    if not isinstance(s, dict):
        return False
    for field in ("points", "nodes", "row_labels", "categories"):
        if field in s:
            if field == "row_labels":
                return bool(s[field] and s.get("col_labels"))
            if field == "categories":
                return bool(s[field]) and any(v is not None and v != "" for series in s.get("series", []) for v in series.get("values", []))
            return bool(s[field])
    return bool(s.get("table_rows"))


def split_templates(payload, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    index = {k: v for k, v in payload.items() if k not in ("snapshots", "pair_snapshots")}
    index.update(schema_version=2, snapshots={}, pair_snapshots={}, template_shards={})
    for key, rounds in payload["snapshots"].items():
        pairs = payload.get("pair_snapshots", {}).get(key, {})
        entry = write_content(output, {"snapshots": {key: rounds}, "pair_snapshots": {key: pairs}})
        entry["path"] = "templates/" + entry["path"]
        index["template_shards"][key] = entry
        index["snapshots"][key] = {r: {"available": snapshot_available(s)} for r, s in rounds.items()}
        index["pair_snapshots"][key] = {r: {c: {"available": snapshot_available(s)} for c, s in comparisons.items()} for r, comparisons in pairs.items()}
    return index


if __name__ == "__main__":
    result = build_data_shards(ROOT / "vote_explorer/data", ROOT / "vote_explorer_web/web_data/tables")
    print(f"{len(result['entries'])} selections, {sum(s['rows'] for s in result['sources'].values())} rows")
