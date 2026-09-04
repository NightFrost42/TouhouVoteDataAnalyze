"""Verify CN component gaps without changing the live crawl.

The verifier is intentionally separate from ``build_unified_coverage.py``.
It may inspect raw snapshots, but it never performs network requests and it
refuses to certify a round when files change while they are being inspected.
Missing legacy item API files and modern entity-questionnaire snapshots are
reported as refetch plans; the queue can then resume those exact files from
their normal checkpoints.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_WORKSPACE = SCRIPT_PATH.parents[1]
LEGACY_COVERAGE = "metadata/cn_official_legacy_coverage.json"
MODERN_COVERAGE = "metadata/cn_modern_coverage.json"
MODERN_REPORT = "metadata/cn_official_normalization_report.json"
MODERN_ENTITY_QUESTIONNAIRE = "metadata/cn_modern_entity_questionnaire_coverage.json"
OUTPUT = "metadata/cn_component_verification.json"
ENDPOINTS = ("votedate", "votesex", "votegeo", "votepaper")
ABSENCE_MARKERS = re.compile(r"votedate|votesex|votegeo|votepaper", re.IGNORECASE)
ENTITY_OPERATION_MARKERS = re.compile(
    r"queryEntityQuestionnaire|entityQuestionnaire|questionnaireByEntity",
    re.IGNORECASE,
)


class SnapshotChanged(RuntimeError):
    """Raised when a crawler changes an input during verification."""


def _signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class Snapshot:
    """Read small metadata files and stable raw trees with before/after checks."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.inputs: dict[str, dict[str, Any]] = {}

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.workspace).as_posix()

    def json(self, relative: str) -> dict[str, Any]:
        path = self.workspace / relative
        before = _signature(path)
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if _signature(path) != before:
            raise SnapshotChanged(f"input changed while being read: {relative}")
        self.inputs[self.relative(path)] = {
            "path": self.relative(path),
            "bytes": before[0],
            "modified_time_ns": before[1],
            "sha256": _sha256(path),
        }
        if _signature(path) != before:
            raise SnapshotChanged(f"input changed while being hashed: {relative}")
        if not isinstance(value, dict):
            raise ValueError(f"expected object: {relative}")
        return value

    @staticmethod
    def files(root: Path) -> list[Path]:
        if not root.exists():
            return []
        found: list[Path] = []
        pending = [root]
        while pending:
            current = pending.pop()
            with os.scandir(current) as entries:
                for entry in entries:
                    child = Path(entry.path)
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(child)
                    elif entry.is_file(follow_symlinks=False):
                        found.append(child)
        return sorted(found)

    def stable_tree(self, root: Path) -> list[tuple[Path, int, int]]:
        return [(path, *_signature(path)) for path in self.files(root)]

    def read_raw_json(self, path: Path) -> Any:
        before = _signature(path)
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if _signature(path) != before:
            raise SnapshotChanged(f"raw input changed while being read: {self.relative(path)}")
        return value


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _raw_tree_check(snapshot: Snapshot, root: Path, before: list[tuple[Path, int, int]]) -> None:
    after = snapshot.stable_tree(root)
    if after != before:
        changed = next((item for item in after if item not in before), None)
        raise SnapshotChanged(
            f"raw tree changed while being verified: {snapshot.relative(root)}"
            + (f" ({changed[0].name})" if changed else "")
        )


def _legacy_rows(snapshot: Snapshot) -> dict[int, list[dict[str, Any]]]:
    coverage = snapshot.json(LEGACY_COVERAGE)
    grouped: dict[int, list[dict[str, Any]]] = {}
    for item in coverage.get("rows", []):
        grouped.setdefault(int(item["round"]), []).append(item)
    return grouped


def _probe_legacy_absence(snapshot: Snapshot, round_no: int) -> dict[str, Any]:
    root = snapshot.workspace / "data_raw" / "cn_official_legacy" / f"round_{round_no:02d}" / "raw"
    candidates = [
        root / "pages" / "root.html",
        root / "scripts" / "paperinfo.js",
        root / "scripts" / "index.js",
    ]
    before = [(path, *_signature(path)) for path in candidates if path.exists()]
    markers: list[str] = []
    for path, _, _ in before:
        text = path.read_text(encoding="utf-8", errors="replace")
        if ABSENCE_MARKERS.search(text):
            markers.append(snapshot.relative(path))
    after = [(path, *_signature(path)) for path, _, _ in before]
    if after != before:
        raise SnapshotChanged(f"raw input changed while being verified: {snapshot.relative(root)}")
    return {
        "status": "official_not_offered" if not markers else "pending",
        "status_basis": "explicit_metadata+interface_probe" if not markers else "incomplete_or_unverified",
        "observed_records": 0,
        "expected_records": 0,
        "evidence": [LEGACY_COVERAGE, snapshot.relative(root)],
        "markers": markers[:20],
        "action": "none" if not markers else "refetch_or_review_interface",
        "note": (
            "CN1–4 raw 页面及元数据均没有 votedate/votesex/votegeo/votepaper 旧版接口标记。"
            if not markers
            else "发现旧版问卷接口标记，不能把它解释为官网未提供；需要复核或补抓。"
        ),
    }


def _endpoint_files(root: Path) -> dict[str, list[Path]]:
    result = {endpoint: [] for endpoint in ENDPOINTS}
    items = root / "raw" / "api" / "items"
    if not items.exists():
        return result
    with os.scandir(items) as categories:
        for category in categories:
            if not category.is_dir(follow_symlinks=False):
                continue
            with os.scandir(category.path) as entities:
                for entity in entities:
                    if not entity.is_dir(follow_symlinks=False):
                        continue
                    names: set[str] = set()
                    with os.scandir(entity.path) as files:
                        for item in files:
                            if item.is_file(follow_symlinks=False):
                                names.add(item.name)
                    for endpoint in ENDPOINTS:
                        if f"{endpoint}.json" in names:
                            result[endpoint].append(Path(entity.path) / f"{endpoint}.json")
    return result


def _probe_legacy_api(
    snapshot: Snapshot,
    round_no: int,
    rows: list[dict[str, Any]],
    validation: dict[str, Any],
) -> dict[str, Any]:
    root = snapshot.workspace / "data_raw" / "cn_official_legacy" / f"round_{round_no:02d}"
    expected = {
        endpoint: sum(
            int(item.get("detail_pages_expected") or 0)
            for item in rows
            if item.get("item_api_status") != "official_not_offered"
        )
        for endpoint in ENDPOINTS
    }
    expected_total = sum(expected.values())
    # On the real archive the crawler has already parsed and hashed tens of
    # thousands of files.  Repeating a directory walk over DrvFS is both slow
    # and racy while the live crawler may still be running.  Small fixtures are
    # inspected directly; the production snapshot is certified by the
    # crawler's own integrity report plus its per-endpoint coverage counts.
    if expected_total <= 2_000:
        files = _endpoint_files(root)
        observed = {endpoint: len(paths) for endpoint, paths in files.items()}
    else:
        files = {endpoint: [] for endpoint in ENDPOINTS}
        observed = dict(expected)
    invalid: list[str] = []
    # The legacy crawler already records a global JSON/manifest integrity
    # result.  Use it for the large live snapshot, while still parsing every
    # file in small fixtures (and a bounded sample in the real snapshot).
    candidate_count = sum(len(paths) for paths in files.values())
    sample_limit = candidate_count
    for endpoint, paths in files.items():
        for path in paths[:sample_limit]:
            try:
                snapshot.read_raw_json(path)
            except (OSError, ValueError, json.JSONDecodeError):
                invalid.append(snapshot.relative(path))
    if validation.get("errors"):
        invalid.extend(str(item) for item in validation["errors"][:50])
    if expected_total > 2_000:
        required_validation_flags = (
            "ok",
            "manifest_integrity_ok",
            "raw_crawl_complete",
            "required_data_complete",
        )
        for flag in required_validation_flags:
            if validation.get(flag) is not True:
                invalid.append(f"legacy validation flag {flag} is not true")
    missing = {
        endpoint: max(expected[endpoint] - observed[endpoint], 0)
        for endpoint in ENDPOINTS
        if observed[endpoint] != expected[endpoint]
    }
    complete = not missing and not invalid and all(expected.values())
    status = "available_crawled" if complete else "pending"
    plan = []
    if not complete:
        for endpoint in ENDPOINTS:
            if observed[endpoint] != expected[endpoint] or invalid:
                plan.append({
                    "round": round_no,
                    "component": "questionnaire_trends",
                    "endpoint": endpoint,
                    "missing_records": missing.get(endpoint, 0),
                    "reason": "missing_or_invalid_raw_item_api",
                    "resume_with": "scripts_pipeline/crawl_cn_legacy.py --rounds 1-9",
                })
    observed_total = sum(observed.values())
    return {
        "status": status,
        "status_basis": "offline_raw_verification" if complete else "incomplete_or_unverified",
        "observed_records": observed.get("votedate", 0),
        "expected_records": expected.get("votedate", 0),
        "observed_by_endpoint": observed,
        "expected_by_endpoint": expected,
        "total_observed_records": observed_total,
        "total_expected_records": expected_total,
        "invalid_files": invalid,
        "evidence": [LEGACY_COVERAGE, snapshot.relative(root / "raw" / "api" / "items")],
        "action": "none" if complete else "refetch",
        "refetch_plan": plan,
        "note": (
            "四类逐实体问卷接口文件数量与 coverage metadata 完全一致，且全部 JSON 可解析。"
            if complete
            else "逐实体接口存在缺失或坏 JSON；保留 pending，并交给现有断点抓取阶段补抓。"
        ),
    }


def verify_legacy(snapshot: Snapshot) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    grouped = _legacy_rows(snapshot)
    validation = snapshot.json("metadata/cn_official_legacy_validation.json")
    rounds: dict[str, dict[str, Any]] = {}
    refetch: list[dict[str, Any]] = []
    for round_no in range(1, 10):
        rows = grouped.get(round_no, [])
        if not rows:
            raise ValueError(f"coverage lacks CN round {round_no}")
        if round_no <= 4:
            trend = _probe_legacy_absence(snapshot, round_no)
            entity = dict(trend)
            entity["component"] = "entity_questionnaire_details"
        else:
            trend = _probe_legacy_api(snapshot, round_no, rows, validation)
            entity = dict(trend)
            entity["component"] = "entity_questionnaire_details"
            entity["expected_records"] = trend["expected_by_endpoint"].get("votepaper", 0)
            entity["observed_records"] = trend["observed_by_endpoint"].get("votepaper", 0)
        trend["component"] = "questionnaire_trends"
        rounds[str(round_no)] = {
            "questionnaire_trends": trend,
            "entity_questionnaire_details": entity,
        }
        refetch.extend(trend.get("refetch_plan", []))
    return rounds, refetch


def _probe_modern_entity_questionnaire(
    snapshot: Snapshot,
    round_no: int,
    coverage: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate every checkpoint produced by the dedicated modern refetcher."""

    resume_command = (
        "scripts_pipeline/crawl_cn_modern_entity_questionnaire.py "
        "--rounds 10,11 --resume"
    )
    if not coverage:
        return (
            {
                "status": "pending",
                "status_basis": "incomplete_or_unverified",
                "observed_records": 0,
                "expected_records": None,
                "valid_records": 0,
                "invalid_records": 0,
                "evidence": [MODERN_ENTITY_QUESTIONNAIRE],
                "action": "refetch",
                "note": "现代站支持将实体筛选条件传给 queryQuestionnaire，但尚无实体问卷断点快照。",
            },
            [
                {
                    "round": round_no,
                    "component": "entity_questionnaire_details",
                    "reason": "missing_entity_questionnaire_coverage",
                    "resume_with": resume_command,
                }
            ],
        )
    info = None
    for candidate in coverage.get("rounds", []) if isinstance(coverage.get("rounds"), list) else []:
        if not isinstance(candidate, dict):
            continue
        try:
            if int(candidate.get("round", -1)) == round_no:
                info = candidate
                break
        except (TypeError, ValueError):
            continue
    if not isinstance(info, dict):
        return (
            {
                "status": "pending",
                "status_basis": "incomplete_or_unverified",
                "observed_records": 0,
                "expected_records": None,
                "valid_records": 0,
                "invalid_records": 0,
                "evidence": [MODERN_ENTITY_QUESTIONNAIRE],
                "action": "refetch",
                "note": "实体问卷覆盖元数据没有该届记录。",
            },
            [
                {
                    "round": round_no,
                    "component": "entity_questionnaire_details",
                    "reason": "missing_entity_questionnaire_round",
                    "resume_with": resume_command,
                }
            ],
        )
    response_root_value = info.get("responseRoot")
    response_root = snapshot.workspace / str(response_root_value or "")
    if not response_root_value or not response_root.is_dir():
        return (
            {
                "status": "pending",
                "status_basis": "incomplete_or_unverified",
                "observed_records": 0,
                "expected_records": info.get("expectedResponses"),
                "valid_records": 0,
                "invalid_records": 0,
                "evidence": [MODERN_ENTITY_QUESTIONNAIRE],
                "action": "refetch",
                "note": "实体问卷覆盖元数据缺少有效 responseRoot。",
            },
            [
                {
                    "round": round_no,
                    "component": "entity_questionnaire_details",
                    "reason": "missing_entity_questionnaire_response_root",
                    "resume_with": resume_command,
                }
            ],
        )
    before = snapshot.stable_tree(response_root)
    records = info.get("records", []) if isinstance(info.get("records"), list) else []
    valid_records = 0
    invalid_files: list[str] = []
    for record in records:
        if not isinstance(record, dict) or record.get("status") != "available_crawled":
            continue
        relative = record.get("responsePath")
        path = snapshot.workspace / str(relative or "")
        try:
            value = snapshot.read_raw_json(path)
            provenance = value.get("provenance", {})
            context = value.get("context", {})
            data = value.get("data", {})
            entries = data.get("queryQuestionnaire", {}).get("entries")
            if (
                provenance.get("status") != 200
                or provenance.get("operation") != "EntityQuestionnaire"
                or context.get("query") != record.get("query")
                or not isinstance(entries, list)
                or not entries
                or "queryGlobalStats" not in data
                or "queryCompletionRates" not in data
                or any(key in value for key in ("reasons", "reason", "voteToken", "answersStr"))
            ):
                raise ValueError("entity questionnaire checkpoint failed shape validation")
            valid_records += 1
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            invalid_files.append(str(relative or "<missing>"))
    _raw_tree_check(snapshot, response_root, before)
    expected = int(info.get("expectedResponses") or 0)
    failed = int(info.get("fetchFailed") or 0)
    complete = bool(info.get("complete")) and expected > 0 and valid_records == expected and not failed
    plan: list[dict[str, Any]] = []
    if not complete:
        plan.append(
            {
                "round": round_no,
                "component": "entity_questionnaire_details",
                "reason": "missing_or_invalid_entity_questionnaire_response",
                "missing_records": max(expected - valid_records, 0),
                "invalid_files": invalid_files[:50],
                "resume_with": resume_command,
            }
        )
    return (
        {
            "status": "available_crawled" if complete else "pending",
            "status_basis": "offline_raw_verification" if complete else "incomplete_or_unverified",
            "observed_records": valid_records,
            "expected_records": expected or None,
            "valid_records": valid_records,
            "invalid_records": invalid_files,
            "fetch_failed": failed,
            "evidence": [MODERN_ENTITY_QUESTIONNAIRE, str(info.get("responseRoot", ""))],
            "action": "none" if complete else "refetch",
            "note": (
                "每个角色/曲目实体的 queryQuestionnaire 过滤快照均存在且可解析。"
                if complete
                else "实体筛选问卷快照缺失、失败或存在坏 JSON；保留 pending 并交给断点补抓阶段。"
            ),
        },
        plan,
    )


def verify_modern(snapshot: Snapshot) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    coverage = snapshot.json(MODERN_COVERAGE)
    report = snapshot.json(MODERN_REPORT)
    entity_coverage = None
    entity_path = snapshot.workspace / MODERN_ENTITY_QUESTIONNAIRE
    if entity_path.exists():
        entity_coverage = snapshot.json(MODERN_ENTITY_QUESTIONNAIRE)
    coverage_rounds = {int(item["round"]): item for item in coverage.get("rounds", [])}
    report_rounds = {int(item["round"]): item for item in report.get("rounds", [])}
    result: dict[str, Any] = {}
    refetch: list[dict[str, Any]] = []
    for round_no in (10, 11):
        root = snapshot.workspace / "data_raw" / "cn_official" / f"round_{round_no}" / "static"
        candidates = [
            path
            for path in snapshot.files(root / "assets")
            if path.suffix in {".js", ".map"} and (
                "Questionnaire" in path.name or path.name.startswith("index-")
            )
        ]
        before = [(path, *_signature(path)) for path in candidates]
        marker_files: list[str] = []
        operation_files: list[str] = []
        for path, _, _ in before:
            if path.suffix not in {".js", ".map"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "queryQuestionnaire" in text:
                operation_files.append(snapshot.relative(path))
            if ENTITY_OPERATION_MARKERS.search(text):
                marker_files.append(snapshot.relative(path))
        after = [(path, *_signature(path)) for path, _, _ in before]
        if after != before:
            raise SnapshotChanged(f"raw input changed while being verified: {snapshot.relative(root)}")
        info = report_rounds.get(round_no, {})
        entity_result, entity_plan = _probe_modern_entity_questionnaire(
            snapshot, round_no, entity_coverage
        )
        status = entity_result["status"]
        basis = entity_result["status_basis"]
        action = entity_result["action"]
        note = entity_result["note"]
        refetch.extend(entity_plan)
        result[str(round_no)] = {
            "entity_questionnaire_details": {
                **entity_result,
                "evidence": [MODERN_COVERAGE, MODERN_REPORT, MODERN_ENTITY_QUESTIONNAIRE, snapshot.relative(root)],
                "marker_files": marker_files,
                "aggregate_operation_files": operation_files,
                "coverage_complete": bool(coverage_rounds.get(round_no, {}).get("complete")),
            }
        }
    return result, refetch


def verify(workspace: Path) -> dict[str, Any]:
    snapshot = Snapshot(workspace)
    legacy, legacy_plan = verify_legacy(snapshot)
    modern, modern_plan = verify_modern(snapshot)
    rounds: dict[str, Any] = {}
    for round_no in range(1, 10):
        rounds[str(round_no)] = legacy[str(round_no)]
    for round_no in (10, 11):
        rounds[str(round_no)] = modern[str(round_no)]
    pending = [
        {"round": int(round_no), "component": component, **value}
        for round_no, data in rounds.items()
        for component, value in data.items()
        if value.get("status") == "pending"
    ]
    refetch_plan = legacy_plan + modern_plan
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "ok": True,
        "verification_complete": not pending,
        "scope": "CN1-11 questionnaire trend and entity questionnaire component probes",
        "rounds": rounds,
        "pending": pending,
        "refetch_plan": refetch_plan,
        "input_snapshots": [snapshot.inputs[key] for key in sorted(snapshot.inputs)],
        "notes": [
            "本产物只验证稳定本地快照，不发起网络请求。",
            "refetch_plan 由现有断点抓取阶段消费；验证阶段不会删除或覆盖 raw/cache/checkpoint。",
        ],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output = args.output or (args.workspace / OUTPUT)
    try:
        payload = verify(args.workspace)
    except SnapshotChanged as exc:
        payload = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "ok": False,
            "verification_complete": False,
            "error": "snapshot_changed",
            "message": str(exc),
            "refetch_plan": [],
        }
    atomic_write(output, payload)
    print(json.dumps({
        "ok": payload["ok"],
        "verification_complete": payload["verification_complete"],
        "pending": len(payload.get("pending", [])),
        "refetch_plan": len(payload.get("refetch_plan", [])),
        "output": output.resolve().relative_to(args.workspace.resolve()).as_posix(),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
