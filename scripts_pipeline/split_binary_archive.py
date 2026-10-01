"""Split/restore an archive byte-for-byte without loading it into memory."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path


def split(path: Path, part_bytes=40 * 1024 * 1024):
    if part_bytes <= 0:
        raise ValueError("part_bytes must be positive")
    digest = hashlib.sha256()
    parts = []
    total = 0
    with path.open("rb") as source:
        while chunk := source.read(part_bytes):
            checksum = hashlib.sha256(chunk).hexdigest()
            name = f"{path.name}.{checksum[:16]}.binpart"
            (path.parent / name).write_bytes(chunk)
            parts.append({"name": name, "bytes": len(chunk), "sha256": checksum})
            digest.update(chunk)
            total += len(chunk)
    manifest = {"schema_version": 1, "format": "binary-concatenation", "base_name": path.name,
                "original_bytes": total, "original_sha256": digest.hexdigest(), "parts": parts}
    target = path.with_name(path.name + ".binary-parts.json")
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    return manifest


def restore(manifest_path: Path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    def safe_name(name):
        if Path(name).name != name or name in (".", ".."):
            raise ValueError("Invalid archive member name")
        return manifest_path.parent / name
    target = safe_name(manifest["base_name"])
    fd, name = tempfile.mkstemp(dir=target.parent, suffix=".restore.tmp")
    total = 0
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as output:
            for part in manifest["parts"]:
                part_digest = hashlib.sha256()
                size = 0
                with safe_name(part["name"]).open("rb") as source:
                    while block := source.read(1024 * 1024):
                        output.write(block)
                        digest.update(block)
                        part_digest.update(block)
                        total += len(block)
                        size += len(block)
                if size != part["bytes"] or part_digest.hexdigest() != part["sha256"]:
                    raise ValueError("Archive part hash/size mismatch")
        if total != manifest["original_bytes"] or digest.hexdigest() != manifest["original_sha256"]:
            raise ValueError("Restored archive hash/size mismatch")
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("split", "restore"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    result = split(args.path) if args.action == "split" else restore(args.path)
    print(result)
