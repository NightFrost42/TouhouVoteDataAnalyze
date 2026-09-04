"""分卷数据文件的读取与合并工具。

大于 GitHub 单文件限制的 CSV 会被保存为 ``文件名.part-001``、
``文件名.part-002`` 等分卷。读取时优先使用完整文件；完整文件不存在时，
按编号依次读取分卷，并跳过后续分卷重复的表头。这样源码运行、目录版和
单文件版都可以使用同一套数据布局。
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
from pathlib import Path
from typing import Iterator, TextIO


PART_RE = re.compile(r"\.part-(\d+)$")


def part_paths(path: Path) -> list[Path]:
    """返回逻辑文件对应的实际文件列表，并检查分卷编号是否连续。"""
    if path.is_file():
        return [path]
    candidates: list[tuple[int, Path]] = []
    for item in path.parent.glob(path.name + ".part-*"):
        match = PART_RE.search(item.name)
        if match:
            candidates.append((int(match.group(1)), item))
    candidates.sort(key=lambda pair: pair[0])
    if not candidates:
        return []
    expected = list(range(1, len(candidates) + 1))
    actual = [number for number, _ in candidates]
    if actual != expected:
        raise ValueError(f"分卷编号不连续：{path}，实际为 {actual}")
    return [item for _, item in candidates]


def logical_file_exists(path: Path) -> bool:
    """判断完整文件或其分卷是否存在。"""
    return bool(part_paths(path))


def part_manifest_path(path: Path) -> Path:
    return path.with_name(path.name + ".parts.json")


def _open_text(path: Path, compressed: bool) -> TextIO:
    opener = gzip.open if compressed else open
    return opener(path, "rt", encoding="utf-8-sig", newline="")


def iter_csv_rows(path: Path, compressed: bool = False) -> Iterator[dict[str, str]]:
    """逐行读取完整 CSV 或分卷 CSV。

    每个分卷都包含表头，因而分卷可以单独用 Excel 或 pandas 打开；这里
    只保留第一卷的表头，后续卷的表头由 ``DictReader`` 自然跳过。
    """
    paths = part_paths(path)
    if not paths:
        raise FileNotFoundError(path)
    for part in paths:
        with _open_text(part, compressed=compressed) as handle:
            yield from csv.DictReader(handle)


def read_csv_rows(path: Path, compressed: bool = False) -> list[dict[str, str]]:
    return list(iter_csv_rows(path, compressed=compressed))


def merge_parts(path: Path, destination: Path | None = None) -> Path:
    """把分卷合并为完整文件，并按清单校验大小和 SHA-256。

    默认目标是逻辑文件本身；如果目标已存在则直接返回。合并过程先写
    临时文件，校验通过后再替换目标，避免留下半个文件。
    """
    if path.is_file():
        return path
    paths = part_paths(path)
    if not paths:
        raise FileNotFoundError(path)
    target = destination or path
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".merge.tmp")
    digest = hashlib.sha256()
    total = 0
    with temporary.open("wb") as output:
        for index, part in enumerate(paths):
            with part.open("rb") as source:
                if index:
                    source.readline()  # 每卷第一行都是重复表头
                while block := source.read(1024 * 1024):
                    output.write(block)
                    digest.update(block)
                    total += len(block)
    manifest = load_part_manifest(path)
    if manifest:
        expected_bytes = manifest.get("original_bytes")
        expected_sha = manifest.get("original_sha256")
        if expected_bytes is not None and int(expected_bytes) != total:
            temporary.unlink(missing_ok=True)
            raise ValueError(f"合并后大小不符：{path}，{total} != {expected_bytes}")
        if expected_sha and str(expected_sha) != digest.hexdigest():
            temporary.unlink(missing_ok=True)
            raise ValueError(f"合并后 SHA-256 不符：{path}")
    temporary.replace(target)
    return target


def load_part_manifest(path: Path) -> dict | None:
    manifest = part_manifest_path(path)
    if not manifest.is_file():
        return None
    with manifest.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    return value if isinstance(value, dict) else None
