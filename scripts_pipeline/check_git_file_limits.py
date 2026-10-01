"""Check staged and unpublished Git blobs against GitHub's 100 MiB limit.

The repository stores large logical datasets as ordinary Git partitions.  This
check intentionally does not inspect ignored local reconstructions, because
those files are never part of a clone or push.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


LIMIT_BYTES = 100 * 1024 * 1024
def git(root: Path, *args: str, input_text: str | None = None) -> str:
    command = ["git", "-c", f"safe.directory={root}", *args]
    result = subprocess.run(
        command,
        cwd=root,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
    )
    return result.stdout


def blob_sizes(root: Path, oids: list[str]) -> dict[str, int]:
    if not oids:
        return {}
    request = "".join(f"{oid}\n" for oid in oids)
    output = git(root, "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)", input_text=request)
    result = {}
    for line in output.splitlines():
        oid, object_type, size = line.split()
        if object_type == "blob":
            result[oid] = int(size)
    return result


def staged_blobs(root: Path) -> list[tuple[str, str, int]]:
    entries = git(root, "ls-files", "--stage", "-z").split("\0")
    parsed = []
    for entry in entries:
        if not entry:
            continue
        metadata, path = entry.split("\t", 1)
        _mode, oid, _stage = metadata.split()
        parsed.append((path, oid))
    sizes = blob_sizes(root, [oid for _path, oid in parsed])
    return [(path, oid, sizes[oid]) for path, oid in parsed if oid in sizes]


def unpublished_blobs(root: Path) -> list[tuple[str, str, int]]:
    try:
        upstream = git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").strip()
    except subprocess.CalledProcessError:
        upstream = ""
    revision_range = f"{upstream}..HEAD" if upstream else "--not --remotes"
    revision_args = ["rev-list", "--objects", *revision_range.split()]
    lines = git(root, *revision_args).splitlines()
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in lines:
        parts = line.split(" ", 1)
        if len(parts) != 2 or parts[0] in seen:
            continue
        seen.add(parts[0])
        candidates.append((parts[0], parts[1]))
    if not candidates:
        return []
    sizes = blob_sizes(root, [oid for oid, _path in candidates])
    return [(path, oid, sizes[oid]) for oid, path in candidates if oid in sizes]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    violations: list[tuple[str, str, int]] = []

    for path, oid, size in staged_blobs(root):
        if size > LIMIT_BYTES:
            violations.append((f"staged:{path}", oid, size))

    for path, oid, size in unpublished_blobs(root):
        if size > LIMIT_BYTES:
            violations.append((f"unpublished:{path}", oid, size))

    attributes = root / ".gitattributes"
    if attributes.exists() and re.search(r"(^|\s)filter=lfs(\s|$)", attributes.read_text(encoding="utf-8")):
        print("ERROR: .gitattributes contains a Git LFS filter", file=sys.stderr)
        return 1

    for path, oid, size in violations:
        print(f"ERROR: {path} is {size / 1024 / 1024:.2f} MiB ({oid})", file=sys.stderr)
    if violations:
        return 1

    print(f"OK: staged and unpublished Git blobs are <= {LIMIT_BYTES / 1024 / 1024:.0f} MiB; Git LFS filter absent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
