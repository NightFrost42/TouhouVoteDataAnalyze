"""Audit every generated selection against all source CSV cells and hashes."""
from __future__ import annotations
import gzip
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vote_explorer.data_chunks import iter_csv_rows
from vote_explorer_web.data_shards import SOURCES, encoded, selection_key


def audit():
    directory = ROOT / "vote_explorer_web/web_data/tables"
    index = json.loads((directory / "index.json").read_bytes())
    expected, actual = defaultdict(hashlib.sha256), defaultdict(hashlib.sha256)
    counts = defaultdict(int)
    for kind, filename in SOURCES.items():
        columns = index["sources"][kind]["columns"]
        for row in iter_csv_rows(ROOT / "vote_explorer/data" / filename, compressed=filename.endswith(".gz")):
            key = encoded(selection_key(kind, row)).decode()
            expected[key].update(encoded([row[c] for c in columns]) + b"\n")
            counts[kind] += 1
        assert counts[kind] == index["sources"][kind]["rows"], kind
    sizes = []
    for key, entries in index["entries"].items():
        kind = json.loads(key)[0]
        columns = index["sources"][kind]["columns"]
        for entry in entries:
            raw = (directory / entry["path"]).read_bytes()
            assert len(raw) == entry["bytes"] and hashlib.sha256(raw).hexdigest() == entry["sha256"], entry["path"]
            sizes.append(len(raw))
            payload = json.loads(gzip.decompress(raw))
            assert len(payload["values"]) == entry["rows"]
            for values in payload["values"]:
                row = dict(payload["defaults"], **dict(zip(payload["columns"], values)))
                actual[key].update(encoded([row[c] for c in columns]) + b"\n")
    assert set(expected) == set(actual)
    assert all(expected[k].digest() == actual[k].digest() for k in expected), "Source cell/order mismatch"
    result = dict(status="PASS", selections=len(expected), source_rows=dict(counts), shards=len(sizes), max_shard_bytes=max(sizes), shard_bytes=sum(sizes))
    print(json.dumps(result))
    return result


if __name__ == "__main__":
    audit()
