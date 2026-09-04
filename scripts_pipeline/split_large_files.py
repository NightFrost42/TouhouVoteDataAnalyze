#!/usr/bin/env python3
"""把超过 GitHub 单文件限制的 CSV 分卷，并生成可校验的清单。

分卷按完整 CSV 记录切开，每卷都保留表头，因此可以单独检查。查询器的
``vote_explorer.data_chunks`` 会在完整文件不存在时自动按编号读取这些分卷。
默认只处理数据集目录和查询器便携数据目录中的未压缩 CSV，不会改动原始抓取树。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from vote_explorer.data_chunks import merge_parts, PART_RE, part_manifest_path, part_paths


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIRS = (ROOT / "datasets", ROOT / "vote_explorer" / "data")
PART_BYTES = 80 * 1024 * 1024
GITHUB_LIMIT_BYTES = 100 * 1024 * 1024


def _record_quote_state(data: bytes, in_quotes: bool) -> bool:
    """更新 CSV 双引号状态，避免在带换行的字段中间切分。"""
    index = 0
    while index < len(data):
        if data[index] == 34:  # b'"'
            if index + 1 < len(data) and data[index + 1] == 34:
                index += 2
                continue
            in_quotes = not in_quotes
        index += 1
    return in_quotes


def _records(handle):
    buffer = bytearray()
    in_quotes = False
    for line in handle:
        buffer.extend(line)
        in_quotes = _record_quote_state(line, in_quotes)
        if not in_quotes:
            yield bytes(buffer)
            buffer.clear()
    if buffer:
        yield bytes(buffer)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_manifest(path: Path, original_bytes: int, original_sha256: str, parts: list[dict], part_bytes: int) -> None:
    payload = {
        "schema_version": 1,
        "base_name": path.name,
        "original_bytes": original_bytes,
        "original_sha256": original_sha256,
        "part_bytes_target": part_bytes,
        "parts": parts,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    target = part_manifest_path(path)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False, suffix=".tmp") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(target)


def _record_in_manifests(path: Path, original_bytes: int, original_sha256: str, parts: list[dict]) -> None:
    """在相邻的数据清单中记录分卷布局，保留原始文件的校验值。"""
    for manifest_path in sorted(path.parent.glob("*manifest*.json")):
        if manifest_path.name.endswith(".parts.json"):
            continue
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        storage = payload.setdefault("storage", {})
        split_files = storage.setdefault("split_files", {})
        split_files[path.name] = {
            "parts_manifest": part_manifest_path(path).name,
            "original_bytes": original_bytes,
            "original_sha256": original_sha256,
            "parts": [item["name"] for item in parts],
        }
        temporary = manifest_path.with_name(manifest_path.name + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(manifest_path)


def split_file(path: Path, part_bytes: int = PART_BYTES, remove_original: bool = False) -> dict:
    if not path.is_file():
        existing = part_paths(path)
        if existing:
            manifest = part_manifest_path(path)
            if manifest.is_file():
                try:
                    payload = json.loads(manifest.read_text(encoding="utf-8"))
                    _record_in_manifests(
                        path,
                        int(payload.get("original_bytes", 0)),
                        str(payload.get("original_sha256", "")),
                        list(payload.get("parts", [])),
                    )
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    pass
            return {"path": path.as_posix(), "status": "already_split", "parts": len(existing)}
        return {"path": path.as_posix(), "status": "missing"}
    if path.suffix.lower() != ".csv":
        return {"path": path.as_posix(), "status": "skipped_non_csv"}

    original_bytes = path.stat().st_size
    original_sha256 = _sha256(path)
    temporary_paths: list[Path] = []
    part_records: list[dict] = []
    with tempfile.TemporaryDirectory(prefix=f"{path.stem}.split-", dir=path.parent) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        with path.open("rb") as source:
            records = _records(source)
            try:
                header = next(records)
            except StopIteration:
                return {"path": path.as_posix(), "status": "empty"}
            part_number = 0
            output = None
            output_path = None
            output_size = 0
            output_hash = None

            def start_part() -> None:
                nonlocal part_number, output, output_path, output_size, output_hash
                if output is not None:
                    output.close()
                part_number += 1
                output_path = temp_dir / f"{path.name}.part-{part_number:03d}"
                output = output_path.open("wb")
                output.write(header)
                output_size = len(header)
                output_hash = hashlib.sha256()
                output_hash.update(header)
                temporary_paths.append(output_path)

            start_part()
            for record in records:
                if output_size > len(header) and output_size + len(record) > part_bytes:
                    start_part()
                assert output is not None and output_hash is not None
                output.write(record)
                output_hash.update(record)
                output_size += len(record)
            assert output is not None and output_path is not None and output_hash is not None
            output.close()

        combined_size = 0
        for temporary in temporary_paths:
            size = temporary.stat().st_size
            combined_size += size - (len(header) if temporary != temporary_paths[0] else 0)
            part_records.append(
                {
                    "name": temporary.name,
                    "bytes": size,
                    "sha256": _sha256(temporary),
                }
            )
        if combined_size != original_bytes:
            raise RuntimeError(f"分卷大小校验失败：{path}，{combined_size} != {original_bytes}")

        # 只有全部分卷写完并通过大小校验后才替换旧分卷。
        for old in part_paths(path):
            if old != path:
                old.unlink()
        for temporary in temporary_paths:
            temporary.replace(path.parent / temporary.name)

    _write_manifest(path, original_bytes, original_sha256, part_records, part_bytes)
    _record_in_manifests(path, original_bytes, original_sha256, part_records)
    if remove_original:
        path.unlink()
    return {
        "path": path.as_posix(),
        "status": "split",
        "parts": len(part_records),
        "original_bytes": original_bytes,
        "original_sha256": original_sha256,
        "removed_original": remove_original,
    }


def discover_targets(threshold_bytes: int) -> list[Path]:
    targets: list[Path] = []
    for directory in DEFAULT_DIRS:
        if not directory.is_dir():
            continue
        for path in directory.rglob("*.csv"):
            if path.is_file() and path.stat().st_size > threshold_bytes:
                targets.append(path)
    return sorted(set(targets), key=lambda item: item.as_posix().casefold())


def discover_split_bases() -> list[Path]:
    targets: list[Path] = []
    suffix = ".parts.json"
    for directory in DEFAULT_DIRS:
        if not directory.is_dir():
            continue
        for manifest in directory.rglob("*.parts.json"):
            if manifest.name.endswith(suffix):
                targets.append(manifest.with_name(manifest.name[: -len(suffix)]))
    return sorted(set(targets), key=lambda item: item.as_posix().casefold())


def main() -> int:
    parser = argparse.ArgumentParser(description="分卷超过 GitHub 单文件限制的 CSV")
    parser.add_argument("paths", nargs="*", type=Path, help="要处理的 CSV；不填时使用 --all")
    parser.add_argument("--all", action="store_true", help="扫描 datasets/ 和 vote_explorer/data/")
    parser.add_argument("--merge", action="store_true", help="将分卷恢复为完整 CSV，而不是继续分卷")
    parser.add_argument("--threshold-mb", type=float, default=100, help="只处理大于此大小的文件，默认 100 MB")
    parser.add_argument("--part-mb", type=float, default=80, help="每卷目标大小，默认 80 MB")
    parser.add_argument("--replace", action="store_true", help="分卷成功后删除完整原文件")
    args = parser.parse_args()
    threshold = int(args.threshold_mb * 1024 * 1024)
    part_bytes = int(args.part_mb * 1024 * 1024)
    if part_bytes <= 0 or part_bytes >= GITHUB_LIMIT_BYTES:
        parser.error("--part-mb 必须为正数且小于 100 MB")
    if args.paths:
        targets = [(ROOT / path).resolve() if not path.is_absolute() else path.resolve() for path in args.paths]
    elif args.all:
        targets = discover_split_bases() if args.merge else discover_targets(threshold)
    else:
        parser.error("请提供文件路径，或使用 --all")
    if args.merge:
        results = []
        for path in targets:
            merged = merge_parts(path)
            results.append({"path": path.as_posix(), "status": "merged", "destination": merged.as_posix()})
    else:
        results = [split_file(path, part_bytes=part_bytes, remove_original=args.replace) for path in targets]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(item["status"] not in {"missing", "skipped_non_csv"} for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
