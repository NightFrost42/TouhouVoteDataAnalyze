#!/usr/bin/env python3
"""Safe local controls and status aggregation for the data-crawl queue.

The module is shared by the local dashboard and the one-click command files.
It never enumerates or kills processes by name: only the runner/child recorded
in this workspace's metadata can be acted upon.  Queue data remain resumable;
starting after a failure-limit stop resets only the new consecutive-failure
budget, not successful checkpoints or historical failure totals.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import json
import math
import msvcrt
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Any, BinaryIO, Iterator, Mapping, Sequence

try:  # Package import in tests; direct import when executed as a script.
    from . import stop_data_crawl_queue as stop_helper
except ImportError:  # pragma: no cover - exercised by the command files
    import stop_data_crawl_queue as stop_helper


WORKSPACE = Path(__file__).resolve().parents[1]
METADATA = WORKSPACE / "metadata"
CONFIG_PATH = METADATA / "data_crawl_queue.json"
STATE_PATH = METADATA / "data_crawl_queue_state.json"
PID_PATH = METADATA / "data_crawl_queue_pid.json"
STOP_PATH = METADATA / "data_crawl_queue.stop"
RUNNER_LOCK_PATH = METADATA / ".data_crawl_queue.lock"
CONTROL_LOCK_PATH = METADATA / ".data_crawl_control.lock"
RUNNER_SCRIPT = WORKSPACE / "scripts_pipeline" / "run_data_crawl_queue.py"
LOG_ROOT = METADATA / "logs" / "data_crawl_queue"
RUNNER_STDOUT = LOG_ROOT / "runner.stdout.log"
RUNNER_STDERR = LOG_ROOT / "runner.stderr.log"
LEGACY_RUN_STATE = METADATA / "cn_official_legacy_run_state.json"
# Learned adaptive points are keyed by queue stage.  The dashboard's
# rebenchmark action removes only the selected stage's entry so another stage
# can continue from its own proven speed.
LEGACY_ADAPTIVE_PROFILE = METADATA / "cn_official_legacy_adaptive_profiles.json"
MODERN_ADAPTIVE_PROFILE = METADATA / "cn_modern_adaptive_profiles.json"
MODERN_RUN_STATE = METADATA / "cn_modern_advanced_queue_status.json"
MODERN_ENTITY_QUESTIONNAIRE_RUN_STATE = (
    METADATA / "cn_modern_entity_questionnaire_queue_status.json"
)
MODERN_ENTITY_QUESTIONNAIRE_COVERAGE = (
    METADATA / "cn_modern_entity_questionnaire_coverage.json"
)
THWIKI_ARRANGEMENT_COUNTS_RUN_STATE = (
    METADATA / "thwiki_arrangement_counts_queue_status.json"
)

FAILURE_STOP_STATUSES = {
    "stopped_after_failures",
    "stopped_failure_limit",
    "paused_after_failures",
    "failed_paused",
}
IDENTITY_CONFLICT_STATUS = "stopped_child_identity_mismatch"
IDLE_TERMINAL_STATUSES = {
    "complete",
    "completed",
    "stopped_by_signal",
    IDENTITY_CONFLICT_STATUS,
    *FAILURE_STOP_STATUSES,
}
TUNABLE_STAGE_IDS = ("cn_legacy_advanced", "cn_legacy_remaining")
# Modern CN10/11 crawlers now expose the same adaptive speed controls.  Keep
# the original tuple for compatibility with callers that only know the legacy
# stages, while including modern stages whenever they are present in a queue
# configuration.
ALL_TUNABLE_STAGE_IDS = TUNABLE_STAGE_IDS + (
    "cn_modern_advanced",
    "cn_modern_entity_questionnaire",
)


def present_tunable_stage_ids(value: Mapping[str, Any]) -> tuple[str, ...]:
    stages = value.get("stages")
    if not isinstance(stages, list):
        return TUNABLE_STAGE_IDS
    present = {
        str(item.get("id"))
        for item in stages
        if isinstance(item, Mapping)
    }
    return tuple(stage_id for stage_id in ALL_TUNABLE_STAGE_IDS if stage_id in present)
DEFAULT_STAGE_LABELS = {
    "jp_modern_round22": "日区第22届完整结果抓取",
    "jp_modern_normalize_22": "日区第17–22届现代站数据整理",
    "jp_unified_build_22": "日区第3–22届统一数据重建",
    "jp_unified_validate_22": "日区第3–22届独立完整性验证",
    "cn_modern_advanced": "国区第10–11届高级搜索与问卷",
    "cn_legacy_advanced": "国区第5–9届高级搜索与关联问卷",
    "cn_legacy_remaining": "国区第1–9届排名、详情与问卷补全",
    "cn_modern_normalize": "国区第10–11届数据整理",
    "cn_modern_validate": "国区第10–11届高级搜索校验",
    "cn_legacy_rebuild_validate": "国区第1–9届离线重建与校验",
    "cn_modern_entity_questionnaire": "国区第10–11届实体问卷明细补抓",
    "cn_component_verification": "国区1–11届问卷组件离线验证",
    "unified_coverage": "日区3–22届与国区1–11届覆盖检查",
    "thwiki_arrangement_counts": "THBWiki 原曲同人曲计数、半年与日区结束区间",
}
DEFAULT_STAGE_KINDS = {
    "jp_modern_round22": "crawl",
    "jp_modern_normalize_22": "transform",
    "jp_unified_build_22": "transform",
    "jp_unified_validate_22": "validation",
    "cn_modern_advanced": "crawl",
    "cn_legacy_advanced": "crawl",
    "cn_legacy_remaining": "crawl",
    "cn_modern_normalize": "transform",
    "cn_modern_validate": "validation",
    "cn_legacy_rebuild_validate": "validation",
    "cn_modern_entity_questionnaire": "crawl",
    "cn_component_verification": "validation",
    "unified_coverage": "coverage",
    "thwiki_arrangement_counts": "crawl",
}
LEGACY_PHASE_LABELS = {
    "indexes": "入口与排行页",
    "result variants": "排名筛选视图",
    "details": "项目详情页",
    "detail HTML": "项目详情页",
    "interface scripts": "接口脚本",
    "supplemental questionnaire HTML": "附加问卷页面",
    "supplemental entry resources": "附加数据入口",
    "aggregate questionnaire APIs": "汇总问卷接口",
    "crossvote pages": "关联投票页面",
    "crossvote APIs": "关联投票接口",
    "item APIs": "角色、音乐等项目的详细统计接口",
    "advanced-search entry resources": "高级搜索入口",
    "advanced questionnaire answer catalogues": "高级搜索问卷答案目录",
    "advanced questionnaire-conditioned rankings": "问卷答案条件排行",
    "advanced questionnaire unordered pairs": "问卷答案两两关联表",
    "advanced entity catalogues": "角色与音乐高级搜索对象目录",
    "advanced entity-conditioned rankings": "角色与音乐投票条件排行",
}
# The bracketed summaries emitted by ``crawl_cn_legacy.fetch_many`` are the
# useful unit of work for the dashboard.  Keep a deterministic plan even before
# a phase has printed its first summary so a fresh stage does not look empty.
LEGACY_ADVANCED_CONTENT_PHASES = (
    "advanced-search entry resources",
    "aggregate questionnaire APIs",
    "advanced questionnaire answer catalogues",
    "advanced questionnaire-conditioned rankings",
    "advanced questionnaire unordered pairs",
    "advanced entity catalogues",
    "advanced entity-conditioned rankings",
)
LEGACY_REMAINING_CONTENT_PHASES = (
    "indexes",
    "result variants",
    "details",
    "detail HTML",
    "interface scripts",
    "supplemental questionnaire HTML",
    "supplemental entry resources",
    "aggregate questionnaire APIs",
    "crossvote pages",
    "crossvote APIs",
    "item APIs",
)
MODERN_PHASE_LABELS = {
    "lock_acquired": "获取高级搜索单实例锁",
    "advanced_conditions_start": "准备高级搜索条件",
    "advanced_conditions": "抓取高级搜索条件结果",
    "advanced_questionnaire_pairs": "抓取问卷两两交叉单元格",
    "covote_rebuild": "重建关联投票数值表",
    "validation_and_manifest": "校验完整性并生成清单",
    "finished": "高级搜索数据处理完成",
}
FIELD_SPECS: dict[str, tuple[str, type, float, float]] = {
    # The values below are the absolute process-level safety limits.  A
    # stage's editable ``*Ceiling`` settings normally remain much lower (the
    # queue defaults are 10/30/3), but allowing the actual starting value to
    # follow a deliberately raised ceiling is useful when an upstream is
    # healthy.  The crawler enforces the same absolute limits independently.
    "workers": ("--workers", int, 1, 32),
    # This used to be exposed as ``batchSize``/``--batch-size``.  Keep the
    # JSON key for compatibility with saved UI settings, but the command-line
    # flag now describes the actual policy: a bounded number of requests per
    # checkpoint/cooldown window, not a time interval between starts.
    "batchSize": ("--request-limit", int, 1, 300),
    "batchPause": ("--batch-pause", float, 0, 60),
    "retries": ("--retries", int, 1, 20),
    "timeout": ("--timeout", int, 10, 3600),
    "transientFailureThreshold": (
        "--transient-failure-threshold",
        int,
        1,
        30,
    ),
}
# User-configurable adaptive exploration guardrails.  These are intentionally
# separate from FIELD_SPECS: old queue files do not have these flags, so they
# must remain readable and editable.  The values are exposed in camelCase by
# the dashboard/API while the queue stage metadata also accepts snake_case.
GUARDRAIL_SPECS: dict[str, tuple[str, type, float, float]] = {
    "workerCeiling": ("--worker-ceiling", int, 1, 32),
    "requestLimitCeiling": ("--request-limit-ceiling", int, 1, 300),
    "batchPauseCeiling": ("--batch-pause-ceiling", float, 0, 60),
}
GUARDRAIL_DEFAULTS: dict[str, int | float] = {
    "workerCeiling": 10,
    "requestLimitCeiling": 30,
    "batchPauseCeiling": 3.0,
}
GUARDRAIL_SNAKE_KEYS = {
    "workerCeiling": "worker_ceiling",
    "requestLimitCeiling": "request_limit_ceiling",
    "batchPauseCeiling": "batch_pause_ceiling",
}
GUARDRAIL_PAYLOAD_ALIASES = {
    field: (field, snake)
    for field, snake in GUARDRAIL_SNAKE_KEYS.items()
}
# Values in queue files created before the request-budget migration can be
# larger than the current safety rails (for example ``--batch-size 144`` or
# ``--batch-pause 12.5``).  Keep accepting those historical values at the
# control/API boundary, but normalize them down to the active hard caps before
# writing a command.  This lets an old saved configuration be opened and
# repaired instead of making the dashboard unusable.
COMPAT_CLAMP_FIELDS = {"batchSize", "batchPause"}
LEGACY_SETTING_FIELDS = {"delay", "requestLimit"}
LEGACY_ARGUMENT_ALIASES = {"batchSize": ("--request-limit", "--batch-size")}


class SettingsValidationError(ValueError):
    def __init__(self, errors: Mapping[str, str]) -> None:
        super().__init__("invalid crawl settings")
        self.errors = dict(errors)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _lock_file(path: Path) -> BinaryIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    return handle


@contextmanager
def control_lock() -> Iterator[None]:
    try:
        handle = _lock_file(CONTROL_LOCK_PATH)
    except OSError as exc:
        raise RuntimeError("another queue-control action is still running") from exc
    try:
        yield
    finally:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            handle.close()


def runner_lock_held() -> bool:
    try:
        handle = _lock_file(RUNNER_LOCK_PATH)
    except OSError:
        return True
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        handle.close()
    return False


def _positive_pid(value: Any) -> int | None:
    return value if type(value) is int and 0 < value <= 0xFFFFFFFF else None


def process_snapshot() -> dict[str, Any]:
    state = load_object(STATE_PATH)
    pid_record = load_object(PID_PATH)
    runner_pid = _positive_pid(pid_record.get("pid"))
    current = state.get("current_stage")
    current = current if isinstance(current, dict) else {}
    child_pid = _positive_pid(current.get("child_pid"))
    runner_expected = pid_record.get("process_identity")
    runner_expected = runner_expected if isinstance(runner_expected, dict) else None
    child_expected = current.get("child_identity")
    child_expected = child_expected if isinstance(child_expected, dict) else None
    runner_inspection = stop_helper.inspect_recorded_process(
        runner_pid, runner_expected
    )
    child_inspection = stop_helper.inspect_recorded_process(child_pid, child_expected)
    lock_held = runner_lock_held()
    return {
        "state": state,
        "pidRecord": pid_record,
        "runnerPid": runner_pid,
        "childPid": child_pid,
        "runnerAlive": bool(runner_inspection["alive"]),
        "childAlive": bool(child_inspection["alive"]),
        "runnerIdentityVerified": bool(runner_inspection["identityVerified"]),
        "childIdentityVerified": bool(child_inspection["identityVerified"]),
        "runnerIdentityStatus": runner_inspection["identityStatus"],
        "childIdentityStatus": child_inspection["identityStatus"],
        "runnerLockHeld": lock_held,
        "stopRequested": STOP_PATH.exists(),
    }


def _console_python() -> Path:
    executable = Path(sys.executable).resolve()
    if executable.name.lower() == "pythonw.exe":
        console = executable.with_name("python.exe")
        if console.is_file():
            return console
    return executable


def _prepare_resume_after_failure_stop() -> None:
    state = load_object(STATE_PATH)
    if state.get("status") not in FAILURE_STOP_STATUSES:
        return
    current = state.get("current_stage")
    stage_id = current.get("id") if isinstance(current, dict) else None
    if not isinstance(stage_id, str) or not stage_id:
        error = state.get("last_error")
        stage_id = error.get("stage") if isinstance(error, dict) else None
    if isinstance(stage_id, str) and stage_id:
        consecutive = state.setdefault("consecutive_stage_failures", {})
        if isinstance(consecutive, dict):
            consecutive[stage_id] = 0
        markers = state.get("notification_markers")
        if isinstance(markers, dict):
            retry_markers = markers.get("retry_threshold")
            if isinstance(retry_markers, dict):
                retry_markers.pop(stage_id, None)
    state["last_failure_stop"] = state.get("last_error")
    state["last_error"] = None
    state["status"] = "queued"
    state["resumed_after_failure_stop_at"] = utc_now()
    atomic_write_json(STATE_PATH, state)


def _read_json_path(value: Any, keys: Sequence[str | int]) -> Any:
    """Read one queue success-check path without importing the runner.

    The dashboard intentionally has its own small implementation of the
    success contract.  This lets it distinguish a genuinely completed queue
    from a stale ``status=complete`` marker even when the runner exits before
    its PID record can be observed.
    """

    current = value
    for key in keys:
        if isinstance(key, int):
            if not isinstance(current, list):
                raise TypeError("expected a list while reading success path")
            current = current[key]
        else:
            if not isinstance(current, Mapping):
                raise TypeError("expected an object while reading success path")
            current = current[key]
    return current


def _stage_success_contract(stage: Mapping[str, Any]) -> tuple[bool, str]:
    """Return whether one configured stage currently satisfies its checks."""

    stage_id = str(stage.get("id", "")) or "<unknown>"
    checks = stage.get("success_checks", [])
    if not isinstance(checks, list):
        return False, f"stage {stage_id} has invalid success checks"
    for check in checks:
        if not isinstance(check, Mapping):
            return False, f"stage {stage_id} has an invalid success check"
        kind = check.get("type")
        raw_path = check.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            return False, f"stage {stage_id} has a check without a path"
        path = WORKSPACE / raw_path
        if kind == "file_exists":
            if not path.is_file():
                return False, f"stage {stage_id}: missing success artifact {path}"
            continue
        if kind != "json_path_equals":
            return False, f"stage {stage_id}: unknown success check type {kind!r}"
        if not path.is_file():
            return False, f"stage {stage_id}: missing success artifact {path}"
        try:
            actual = _read_json_path(
                json.loads(path.read_text(encoding="utf-8")),
                check.get("json_path", []),
            )
        except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
            return False, f"stage {stage_id}: cannot read {path}: {exc}"
        if actual != check.get("equals"):
            return (
                False,
                f"stage {stage_id}: {path} success check is "
                f"{actual!r}, expected {check.get('equals')!r}",
            )
    return True, "ok"


def _queue_success_contract() -> tuple[bool, str]:
    """Return whether every configured stage currently satisfies its checks.

    This is deliberately read-only.  A failed check is left for the queue
    runner to repair; the controller only uses the result to avoid reporting a
    stale clean no-op when a previous run recorded all stages as complete.
    """

    try:
        config = load_object(CONFIG_PATH)
        if config.get("schema_version") != 1:
            return False, "unsupported or missing queue config"
        stages = config.get("stages")
        if not isinstance(stages, list):
            return False, "queue config has no stages list"
        for stage in stages:
            if not isinstance(stage, Mapping):
                return False, "queue config contains an invalid stage"
            ok, reason = _stage_success_contract(stage)
            if not ok:
                return False, reason
        return True, "ok"
    except (OSError, ValueError, TypeError) as exc:
        return False, f"cannot inspect queue success contract: {type(exc).__name__}: {exc}"


def _reopen_stale_completion() -> tuple[bool, str]:
    """Clear only stale completion markers before launching a new runner.

    Older queue runners trusted ``completed_stages`` and could therefore exit
    immediately after a new success check was added.  Reopening the first
    invalidated stage here is safe: it changes only orchestration metadata and
    leaves raw files, caches, hashes, and crawler checkpoints untouched.
    """

    config = load_object(CONFIG_PATH)
    state = load_object(STATE_PATH)
    stages = config.get("stages")
    completed = state.get("completed_stages")
    if config.get("schema_version") != 1 or not isinstance(stages, list):
        return False, "queue config has no usable stages list"
    if not isinstance(completed, list):
        return True, "no completion markers"
    completed_ids = {str(item) for item in completed}
    for index, stage in enumerate(stages):
        if not isinstance(stage, Mapping):
            return False, "queue config contains an invalid stage"
        stage_id = str(stage.get("id", ""))
        if stage_id not in completed_ids:
            break
        ok, reason = _stage_success_contract(stage)
        if ok:
            continue
        prior_ids = {
            str(item.get("id", ""))
            for item in stages[:index]
            if isinstance(item, Mapping)
        }
        state["completed_stages"] = [
            item for item in completed if str(item) in prior_ids
        ]
        state["status"] = "queued"
        state["current_stage"] = None
        state.pop("completed_at", None)
        state["reopened_stale_completion"] = {
            "stage": stage_id,
            "reason": reason,
            "recorded_at": utc_now(),
        }
        atomic_write_json(STATE_PATH, state)
        return False, reason
    return True, "ok"


def start_queue(*, wait_seconds: float = 3.0) -> dict[str, Any]:
    with control_lock():
        before = process_snapshot()
        before_state = before.get("state")
        before_status = (
            before_state.get("status") if isinstance(before_state, dict) else None
        )
        if before_status == IDENTITY_CONFLICT_STATUS:
            return {
                "ok": False,
                "action": "child_identity_conflict",
                "error": (
                    "recorded child identity conflicts with the current PID; "
                    "automatic restart is disabled to avoid a duplicate crawler"
                ),
                **before,
            }
        if before["runnerAlive"]:
            return {"ok": True, "action": "already_running", **before}
        if before["stopRequested"] and (
            before["childAlive"] or before["runnerLockHeld"]
        ):
            return {
                "ok": False,
                "action": "stopping",
                "error": "the previous queue is still stopping",
                **before,
            }
        if before["runnerLockHeld"]:
            return {
                "ok": False,
                "action": "runner_lock_held",
                "error": "runner lock is held but its PID metadata is unavailable",
                **before,
            }

        STOP_PATH.unlink(missing_ok=True)
        _prepare_resume_after_failure_stop()
        # Repair stale completion metadata before spawning.  This makes the
        # start button effective even when the dashboard/runner was opened
        # before the success contract was tightened.
        try:
            _reopen_stale_completion()
        except (OSError, ValueError, TypeError):
            # Preflight is a guard against stale completion metadata, not a
            # second startup gate.  If an artifact is temporarily unreadable,
            # let the runner produce its normal diagnostics instead of making
            # the start button unusable.
            pass
        LOG_ROOT.mkdir(parents=True, exist_ok=True)
        command = [
            str(_console_python()),
            str(RUNNER_SCRIPT),
            "--resume",
        ]
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        )
        with (
            RUNNER_STDOUT.open("ab") as stdout,
            RUNNER_STDERR.open("ab") as stderr,
        ):
            process = subprocess.Popen(
                command,
                cwd=WORKSPACE,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                close_fds=True,
                creationflags=creationflags,
            )

        deadline = time.monotonic() + max(0.0, wait_seconds)
        after = process_snapshot()
        while time.monotonic() < deadline:
            if after["runnerAlive"]:
                break
            if process.poll() is not None:
                break
            time.sleep(0.1)
            after = process_snapshot()
        process_exit_code = process.poll()
        state_after = after.get("state")
        # A queued runner is allowed to start, observe that every configured
        # stage is already complete, and exit cleanly before the controller's
        # short liveness window elapses.  That is a successful no-op resume,
        # not a launch failure.  Previously this path reported
        # ``start_failed`` with exit code 0 and empty PID metadata, which made
        # an already-finished queue look broken in the console.
        contract_ok, contract_reason = _queue_success_contract()
        clean_complete = bool(
            process_exit_code == 0
            and not after["runnerAlive"]
            and isinstance(state_after, Mapping)
            and state_after.get("status") in {"complete", "completed"}
            and contract_ok
        )
        stale_clean_exit = bool(
            process_exit_code == 0
            and not after["runnerAlive"]
            and not clean_complete
            and not contract_ok
        )
        ok = bool(after["runnerAlive"] or process_exit_code is None or clean_complete)
        action = "already_complete" if clean_complete else ("started" if ok else "start_failed")
        error = None
        if stale_clean_exit:
            error = (
                "queue runner exited 0 but the configured success contract is "
                f"still incomplete: {contract_reason}; retry start to reopen the "
                "invalidated stage"
            )
        return {
            "ok": ok,
            "action": action,
            "spawnedPid": process.pid,
            "spawnExitCode": process_exit_code,
            **({"error": error} if error else {}),
            **after,
        }


def request_stop() -> dict[str, Any]:
    with control_lock():
        snapshot = process_snapshot()
        snapshot_state = snapshot.get("state")
        snapshot_status = (
            snapshot_state.get("status")
            if isinstance(snapshot_state, dict)
            else None
        )
        if (
            snapshot_status in IDLE_TERMINAL_STATUSES
            and not snapshot["runnerAlive"]
            and not snapshot["childAlive"]
            and not snapshot["runnerLockHeld"]
        ):
            return {
                "ok": True,
                "action": "already_stopped",
                **snapshot,
            }
        if snapshot["stopRequested"] and not (
            snapshot["runnerAlive"]
            or snapshot["childAlive"]
            or snapshot["runnerLockHeld"]
        ):
            return {"ok": True, "action": "already_stopped", **snapshot}

        atomic_write_text(STOP_PATH, "stop\n")
        event: dict[str, Any] = {
            "stopSignalWritten": True,
            "childTerminationRequested": False,
        }
        state = snapshot["state"]
        current = state.get("current_stage")
        current = current if isinstance(current, dict) else {}
        child_pid = snapshot["childPid"]
        if child_pid is not None and snapshot["childAlive"]:
            expected_identity = current.get("child_identity")
            ok, detail = stop_helper.terminate_process(
                child_pid,
                expected_identity=(
                    expected_identity if isinstance(expected_identity, dict) else None
                ),
            )
            event.update(
                {
                    "childTerminationRequested": True,
                    "childTerminationOk": ok,
                    "childTerminationDetail": detail,
                    "childTerminationIdentityMode": (
                        "verified"
                        if isinstance(expected_identity, dict)
                        else "legacy_unverified"
                    ),
                }
            )
        elif not snapshot["runnerAlive"] and not snapshot["runnerLockHeld"]:
            state["status"] = "stopped_by_signal"
            state["last_stop"] = {
                "stage": current.get("id"),
                "message": "stop requested while no runner was active",
                "recorded_at": utc_now(),
            }
            atomic_write_json(STATE_PATH, state)
        return {"ok": True, "action": "stop_requested", **event, **snapshot}


def wait_until_stopped(timeout: float = 120.0) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.1, timeout)
    latest = process_snapshot()
    while time.monotonic() < deadline:
        if (
            not latest["runnerAlive"]
            and not latest["childAlive"]
            and not latest["runnerLockHeld"]
        ):
            return {"ok": True, "action": "stopped", **latest}
        time.sleep(0.25)
        latest = process_snapshot()
    return {
        "ok": False,
        "action": "stop_timeout",
        "error": "timed out waiting for the recorded queue processes to stop",
        **latest,
    }


def stop_queue(*, timeout: float = 120.0) -> dict[str, Any]:
    requested = request_stop()
    if not requested.get("ok"):
        return requested
    return wait_until_stopped(timeout)


def restart_queue(*, timeout: float = 120.0) -> dict[str, Any]:
    stopped = stop_queue(timeout=timeout)
    if not stopped.get("ok"):
        return {"ok": False, "action": "restart_stop_failed", "stop": stopped}
    started = start_queue()
    return {
        "ok": bool(started.get("ok")),
        "action": "restarted" if started.get("ok") else "restart_start_failed",
        "stop": stopped,
        "start": started,
    }


def _reset_legacy_run_state_for_rebenchmark(
    value: Mapping[str, Any],
    *,
    stage_id: str,
    stage_settings: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep a legacy checkpoint but replace its learned speed fields.

    Progress, phase identity, and arbitrary provenance/checkpoint fields are
    deliberately copied through.  Only the adaptive controller's transient
    state is reset, allowing the next process to resume the same unfinished
    content from the configured ceiling.
    """

    reset = dict(value)
    worker_ceiling = int(stage_settings.get("workerCeiling", stage_settings.get("workers", 1)))
    request_ceiling = int(
        stage_settings.get("requestLimitCeiling", stage_settings.get("batchSize", 1))
    )
    batch_size = int(stage_settings.get("batchSize", request_ceiling))
    pause = float(stage_settings.get("batchPause", 0.0))
    pause_ceiling = float(
        stage_settings.get("batchPauseCeiling", max(pause, 0.0))
    )
    pause_floor = min(0.25, pause_ceiling)
    phase = str(reset.get("phase") or "")
    reset.update(
        {
            "queue_stage_id": stage_id,
            "workers": worker_ceiling,
            "configured_workers": int(stage_settings.get("workers", worker_ceiling)),
            "adaptive_tuning": bool(stage_settings.get("adaptiveTuning", True)),
            "adaptive_worker_ceiling": worker_ceiling,
            "adaptive_safe_worker_ceiling": worker_ceiling,
            "adaptive_workers": worker_ceiling,
            "request_limit_ceiling": request_ceiling,
            "request_limit": batch_size,
            "batch_size": batch_size,
            "adaptive_batch_pause_ceiling_seconds": pause_ceiling,
            "adaptive_pause_floor_seconds": pause_floor,
            "adaptive_safe_pause_floor_seconds": pause_floor,
            "adaptive_batch_pause_seconds": pause,
            "batch_pause_seconds": pause,
            "minimum_seconds_between_request_starts": 0.0,
            "adaptive_success_streak": 0,
            "adaptive_pause_success_streak": 0,
            "adaptive_pause_rollback": 0.0,
            "adaptive_recovery_at": 0.0,
            "adaptive_last_decrease_at": 0.0,
            "adaptive_next_decrease_at": 0.0,
            "adaptive_last_increase_at": 0.0,
            "adaptive_next_increase_at": 0.0,
            "adaptive_next_pause_probe_at": 0.0,
            "adaptive_adjustments": 0,
            "adaptive_failure_wave_active": False,
            "adaptive_restart_probation": False,
            "adaptive_replay_active": False,
            "adaptive_phase": phase,
            "stopped_reason": "",
            "updated_at": utc_now(),
        }
    )
    reset.pop("adaptive_last_failure_workers", None)
    # Health/candidate evidence is process-local and must never survive an
    # operator-triggered rebenchmark reset.
    for key in (
        "adaptive_healthy_since",
        "adaptive_healthy_epoch",
        "adaptive_epoch_successes",
        "adaptive_transient_recovery_gate_until",
    ):
        reset.pop(key, None)
    return reset


def _remove_legacy_profile_entry(stage_id: str) -> bool:
    """Delete one stage's adaptive profile entry, preserving all others."""

    try:
        raw = LEGACY_ADAPTIVE_PROFILE.read_text(encoding="utf-8")
    except OSError:
        return False
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("自适应速度档案格式损坏，未执行重新测速") from exc
    if not isinstance(value, dict):
        raise RuntimeError("自适应速度档案格式损坏，未执行重新测速")
    direct = "stages" not in value
    stages = value if direct else value.get("stages")
    if not isinstance(stages, dict) or stage_id not in stages:
        return False
    stages = dict(stages)
    stages.pop(stage_id, None)
    updated = stages if direct else {**value, "stages": stages}
    atomic_write_json(LEGACY_ADAPTIVE_PROFILE, updated)
    return True


def _remove_modern_profile_entry(stage_id: str) -> bool:
    """Delete one modern-stage adaptive profile entry, if present."""

    try:
        raw = MODERN_ADAPTIVE_PROFILE.read_text(encoding="utf-8")
    except OSError:
        return False
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("现代自适应速度档案格式损坏，未执行重新测速") from exc
    if not isinstance(value, dict):
        raise RuntimeError("现代自适应速度档案格式损坏，未执行重新测速")
    direct = "stages" not in value
    stages = value if direct else value.get("stages")
    if not isinstance(stages, dict) or stage_id not in stages:
        return False
    stages = dict(stages)
    stages.pop(stage_id, None)
    atomic_write_json(MODERN_ADAPTIVE_PROFILE, stages if direct else {**value, "stages": stages})
    return True


def rebenchmark_stage(stage_id: str, *, timeout: float = 120.0) -> dict[str, Any]:
    """Stop, clear one crawler stage's learned speed, and resume it.

    The operation intentionally does not touch raw files, manifests, or
    successful hashes.  A failed safe stop returns before either state file is
    changed, and a start failure reports ``adaptiveReset`` so the operator can
    distinguish it from a normal restart failure.
    """

    stage_id = str(stage_id or "").strip()
    if stage_id not in ALL_TUNABLE_STAGE_IDS:
        return {
            "ok": False,
            "action": "rebenchmark_invalid_stage",
            "error": "只能对当前支持自适应调速的国区抓取阶段重新测速",
            "stageId": stage_id,
        }

    before_config = load_object(CONFIG_PATH)
    _find_stage(before_config, stage_id)
    # Parse once before stopping so a malformed queue configuration cannot
    # leave the operator with a stopped queue and no clear action to take.
    before_settings = read_settings(before_config)
    del before_settings  # the post-stop read is authoritative below
    profile_path = (
        LEGACY_ADAPTIVE_PROFILE
        if stage_id in TUNABLE_STAGE_IDS
        else MODERN_ADAPTIVE_PROFILE
    )
    if profile_path.exists():
        try:
            profile_probe = json.loads(
                profile_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {
                "ok": False,
                "action": "rebenchmark_profile_invalid",
                "stageId": stage_id,
                "error": f"自适应速度档案格式损坏：{type(exc).__name__}",
            }
        if not isinstance(profile_probe, dict):
            return {
                "ok": False,
                "action": "rebenchmark_profile_invalid",
                "stageId": stage_id,
                "error": "自适应速度档案格式损坏",
            }

    stopped = stop_queue(timeout=timeout)
    if not stopped.get("ok"):
        return {
            "ok": False,
            "action": "rebenchmark_stop_failed",
            "stageId": stage_id,
            "stop": stopped,
        }

    # Re-read both files after the stop.  A queue transition during shutdown
    # must not cause us to clear a different stage's checkpoint.
    profile_before_bytes: bytes | None = None
    run_state_before_bytes: bytes | None = None
    profile_existed = profile_path.exists()
    run_state_path = LEGACY_RUN_STATE if stage_id in TUNABLE_STAGE_IDS else None
    run_state_existed = bool(run_state_path and run_state_path.exists())
    if profile_existed:
        profile_before_bytes = profile_path.read_bytes()
    if run_state_existed and run_state_path is not None:
        run_state_before_bytes = run_state_path.read_bytes()
    try:
        after_config = load_object(CONFIG_PATH)
        _find_stage(after_config, stage_id)
        settings = read_settings(after_config)
        stage_settings = settings["stages"][stage_id]

        profile_changed = (
            _remove_legacy_profile_entry(stage_id)
            if stage_id in TUNABLE_STAGE_IDS
            else _remove_modern_profile_entry(stage_id)
        )
        run_state = load_object(run_state_path) if run_state_path is not None else {}
        run_state_changed = False
        run_state_stage = run_state.get("queue_stage_id")
        if run_state and run_state_stage in (None, "", stage_id):
            reset = _reset_legacy_run_state_for_rebenchmark(
                run_state,
                stage_id=stage_id,
                stage_settings=stage_settings,
            )
            assert run_state_path is not None
            atomic_write_json(run_state_path, reset)
            run_state_changed = True
    except Exception as exc:
        # Roll back either file if the second atomic write failed.  This keeps
        # the reset all-or-nothing from the operator's perspective.
        try:
            if profile_existed and profile_before_bytes is not None:
                profile_path.write_bytes(profile_before_bytes)
            elif not profile_existed:
                profile_path.unlink(missing_ok=True)
            if run_state_existed and run_state_before_bytes is not None and run_state_path is not None:
                run_state_path.write_bytes(run_state_before_bytes)
            elif not run_state_existed and run_state_path is not None:
                run_state_path.unlink(missing_ok=True)
        except OSError:
            pass
        # Do not leave the queue stopped if a concurrent config/profile change
        # invalidated the post-stop reset.  The recovery start is best effort
        # and is included in the diagnostic payload.
        recovery_start = start_queue()
        return {
            "ok": False,
            "action": "rebenchmark_reset_failed",
            "stageId": stage_id,
            "adaptiveReset": False,
            "error": f"重新测速状态清理失败：{type(exc).__name__}: {exc}",
            "stop": stopped,
            "start": recovery_start,
        }

    started = start_queue()
    result = {
        "ok": bool(started.get("ok")),
        "action": "rebenchmarked" if started.get("ok") else "rebenchmark_start_failed",
        "stageId": stage_id,
        "adaptiveReset": True,
        "profileReset": profile_changed,
        "runStateReset": run_state_changed,
        "stop": stopped,
        "start": started,
    }
    if not result["ok"]:
        result["error"] = "速度学习状态已清除，但从断点启动失败；请检查队列状态后重试"
    return result


def _find_stage(config: Mapping[str, Any], stage_id: str) -> dict[str, Any]:
    stages = config.get("stages")
    if not isinstance(stages, list):
        raise RuntimeError("queue config has no stages array")
    for stage in stages:
        if isinstance(stage, dict) and stage.get("id") == stage_id:
            return stage
    raise RuntimeError(f"queue config has no stage {stage_id!r}")


def _argument_value(command: Sequence[Any], flag: str) -> str:
    try:
        index = list(command).index(flag)
    except ValueError as exc:
        raise RuntimeError(f"stage command is missing {flag}") from exc
    if index + 1 >= len(command):
        raise RuntimeError(f"stage command has no value for {flag}")
    return str(command[index + 1])


def _argument_value_any(command: Sequence[Any], flags: Sequence[str], *, default: str | None = None) -> str:
    for flag in flags:
        try:
            return _argument_value(command, flag)
        except RuntimeError:
            continue
    if default is not None:
        return default
    raise RuntimeError(f"stage command is missing one of {', '.join(flags)}")


def _set_argument(command: list[Any], flag: str, value: int | float) -> None:
    try:
        index = command.index(flag)
    except ValueError as exc:
        raise RuntimeError(f"stage command is missing {flag}") from exc
    if index + 1 >= len(command):
        raise RuntimeError(f"stage command has no value for {flag}")
    command[index + 1] = str(value)


def _set_argument_any(
    command: list[Any], flags: Sequence[str], value: int | float, *, canonical: str
) -> None:
    for flag in flags:
        try:
            index = command.index(flag)
        except ValueError:
            continue
        if index + 1 >= len(command):
            raise RuntimeError(f"stage command has no value for {flag}")
        command[index] = canonical
        command[index + 1] = str(value)
        return
    raise RuntimeError(f"stage command is missing one of {', '.join(flags)}")


def _set_or_append_argument(
    command: list[Any], flag: str, value: int | float
) -> None:
    """Set a command option, appending it for pre-guardrail queue files."""

    for index, item in enumerate(command):
        if item == flag:
            if index + 1 >= len(command):
                raise RuntimeError(f"stage command has no value for {flag}")
            command[index + 1] = str(value)
            return
    command.extend((flag, str(value)))


def read_settings(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    value = dict(config) if config is not None else load_object(CONFIG_PATH)
    stages: dict[str, dict[str, int | float | bool]] = {}
    for stage_id in present_tunable_stage_ids(value):
        stage = _find_stage(value, stage_id)
        command = stage.get("command")
        if not isinstance(command, list):
            raise RuntimeError(f"stage {stage_id!r} has no command array")
        fields: dict[str, int | float | bool] = {}
        for field, (flag, kind, _, _) in FIELD_SPECS.items():
            aliases = LEGACY_ARGUMENT_ALIASES.get(field, (flag,))
            raw = _argument_value_any(command, aliases)
            numeric = int(raw) if kind is int else float(raw)
            if field in COMPAT_CLAMP_FIELDS:
                # The command may still contain a pre-migration value.  The
                # crawler itself also clamps it, but exposing the normalized
                # value here keeps the UI/API consistent with what will run.
                numeric = min(numeric, FIELD_SPECS[field][3])
            fields[field] = numeric
        # Guardrails were added after the first queue schema was published.
        # Read them from either the command, explicit stage metadata, or the
        # safe defaults.  A legacy starting value above the new default is
        # retained as its effective ceiling so simply opening/saving an old
        # queue cannot make it invalid.
        for field, (flag, kind, minimum, maximum) in GUARDRAIL_SPECS.items():
            snake_key = GUARDRAIL_SNAKE_KEYS[field]
            # Runner launch semantics give explicit stage metadata priority
            # over a transitional argv flag.  Mirror that order in the UI so
            # a manually edited queue cannot display one rail and run another.
            raw = stage.get(field)
            if raw is None:
                raw = stage.get(snake_key)
            if raw is None:
                raw = _argument_value_any(command, (flag,), default="")
            if raw == "":
                raw = GUARDRAIL_DEFAULTS[field]
            try:
                numeric = int(raw) if kind is int else float(raw)
            except (TypeError, ValueError):
                numeric = GUARDRAIL_DEFAULTS[field]
            if not math.isfinite(float(numeric)):
                numeric = GUARDRAIL_DEFAULTS[field]
            numeric = max(minimum, min(maximum, numeric))
            actual_field = {
                "workerCeiling": "workers",
                "requestLimitCeiling": "batchSize",
                "batchPauseCeiling": "batchPause",
            }[field]
            actual = fields.get(actual_field)
            if isinstance(actual, (int, float)) and not isinstance(actual, bool):
                numeric = max(float(numeric), float(actual))
            numeric = min(maximum, numeric)
            fields[field] = int(numeric) if kind is int else float(numeric)
        fields["requestLimit"] = fields["batchSize"]
        fields["delay"] = float(_argument_value_any(command, ("--delay",), default="0"))
        # Adaptive throttling is deliberately a policy setting rather than a
        # command-line flag.  Older queue files do not have this key; in that
        # case retain the historical behaviour (automatic recovery enabled).
        adaptive_value = stage.get("adaptive_tuning", stage.get("adaptiveTuning", True))
        fields["adaptiveTuning"] = adaptive_value if isinstance(adaptive_value, bool) else True
        stages[stage_id] = fields
    policy = value.get("failure_policy")
    policy = policy if isinstance(policy, dict) else {}
    fallback_config = load_object(CONFIG_PATH)
    notifications = fallback_config.get("notifications")
    notifications = notifications if isinstance(notifications, dict) else {}
    maximum = policy.get(
        "max_consecutive_stage_failures",
        notifications.get("failed_attempt_threshold", 5),
    )
    try:
        maximum = int(maximum)
    except (TypeError, ValueError):
        maximum = 5
    return {
        "stages": stages,
        "failurePolicy": {"maxConsecutiveStageFailures": max(1, maximum)},
    }


def _validate_number(
    value: Any, *, kind: type, minimum: float, maximum: float, field: str
) -> int | float:
    if isinstance(value, bool) or type(value) not in (int, float):
        raise SettingsValidationError({field: "必须是数字"})
    numeric = float(value)
    if not math.isfinite(numeric):
        raise SettingsValidationError({field: "必须是有限数字"})
    if kind is int and not numeric.is_integer():
        raise SettingsValidationError({field: "必须是整数"})
    if numeric < minimum or numeric > maximum:
        raise SettingsValidationError(
            {field: f"允许范围为 {minimum:g}–{maximum:g}"}
        )
    return int(numeric) if kind is int else numeric


def validate_settings(payload: Any) -> dict[str, Any]:
    errors: dict[str, str] = {}
    if not isinstance(payload, dict):
        raise SettingsValidationError({"body": "请求必须是 JSON 对象"})
    for field in sorted(set(payload) - {"stages", "failurePolicy"}):
        errors[field] = "未知字段"
    stages_value = payload.get("stages")
    if not isinstance(stages_value, dict):
        raise SettingsValidationError({"stages": "缺少阶段配置"})
    for stage_id in sorted(set(stages_value) - set(ALL_TUNABLE_STAGE_IDS)):
        errors[f"stages.{stage_id}"] = "未知阶段"
    normalized_stages: dict[str, dict[str, int | float | bool]] = {}
    # A payload read from an older queue may not include the optional modern
    # stages.  Validate every stage that is present, while retaining the
    # legacy stages' historical required-field behaviour.
    stage_ids = tuple(
        stage_id for stage_id in ALL_TUNABLE_STAGE_IDS if stage_id in stages_value
    )
    for stage_id in stage_ids:
        stage_value = stages_value.get(stage_id)
        if not isinstance(stage_value, dict):
            errors[stage_id] = "缺少阶段配置"
            continue
        unknown = (
            set(stage_value)
            - set(FIELD_SPECS)
            - set(GUARDRAIL_SPECS)
            - set(GUARDRAIL_SNAKE_KEYS.values())
            - LEGACY_SETTING_FIELDS
            - {"adaptiveTuning", "adaptive_tuning"}
        )
        for field in sorted(unknown):
            errors[f"{stage_id}.{field}"] = "未知字段"
        normalized: dict[str, int | float | bool] = {}
        for field, (_, kind, minimum, maximum) in FIELD_SPECS.items():
            path = f"{stage_id}.{field}"
            source_field = field
            if field == "batchSize" and field not in stage_value:
                source_field = "requestLimit"
            if source_field not in stage_value:
                errors[path] = "缺少字段"
                continue
            try:
                normalized[field] = _validate_number(
                    stage_value[source_field],
                    kind=kind,
                    minimum=minimum,
                    maximum=maximum,
                    field=path,
                )
            except SettingsValidationError as exc:
                # Keep old queue files editable after lowering the safety
                # rails.  Only finite numeric values above the new maximum
                # are clamped; malformed values and values below the minimum
                # remain validation errors.
                value = stage_value.get(source_field)
                if (
                    field in COMPAT_CLAMP_FIELDS
                    and not isinstance(value, bool)
                    and isinstance(value, (int, float))
                    and math.isfinite(float(value))
                    and float(value) > maximum
                ):
                    normalized[field] = int(maximum) if kind is int else float(maximum)
                else:
                    errors.update(exc.errors)
        # Guardrails are optional in API payloads for backwards compatibility.
        # If omitted, use the historical safe defaults (or the actual value
        # when an older queue started above that default).  Explicit values
        # are still bounded by the absolute limits in GUARDRAIL_SPECS.
        for field, (_, kind, minimum, maximum) in GUARDRAIL_SPECS.items():
            path = f"{stage_id}.{field}"
            source_field = field
            if source_field not in stage_value:
                snake_key = GUARDRAIL_SNAKE_KEYS[field]
                source_field = snake_key if snake_key in stage_value else ""
            actual_field = {
                "workerCeiling": "workers",
                "requestLimitCeiling": "batchSize",
                "batchPauseCeiling": "batchPause",
            }[field]
            actual = normalized.get(actual_field)
            if not source_field:
                default_value = GUARDRAIL_DEFAULTS[field]
                if isinstance(actual, (int, float)) and not isinstance(actual, bool):
                    default_value = max(float(default_value), float(actual))
                normalized[field] = (
                    int(default_value) if kind is int else float(default_value)
                )
                continue
            try:
                normalized[field] = _validate_number(
                    stage_value[source_field],
                    kind=kind,
                    minimum=minimum,
                    maximum=maximum,
                    field=path,
                )
            except SettingsValidationError as exc:
                errors.update(exc.errors)
        for actual_field, ceiling_field in (
            ("workers", "workerCeiling"),
            ("batchSize", "requestLimitCeiling"),
            ("batchPause", "batchPauseCeiling"),
        ):
            actual = normalized.get(actual_field)
            ceiling = normalized.get(ceiling_field)
            if (
                isinstance(actual, (int, float))
                and not isinstance(actual, bool)
                and isinstance(ceiling, (int, float))
                and not isinstance(ceiling, bool)
                and float(actual) > float(ceiling)
            ):
                if actual_field in COMPAT_CLAMP_FIELDS:
                    # Historical dashboard clients submitted a high batch
                    # value without knowing about guardrails.  Clamp those
                    # two bounded throughput fields so an old saved payload
                    # remains repairable; worker mismatches stay explicit
                    # errors because silently changing concurrency is riskier.
                    normalized[actual_field] = (
                        int(ceiling)
                        if actual_field == "batchSize"
                        else float(ceiling)
                    )
                else:
                    errors[f"{stage_id}.{ceiling_field}"] = (
                        f"不能低于当前{actual_field}值 {actual:g}，请先降低起始值"
                    )
        adaptive = stage_value.get("adaptiveTuning", stage_value.get("adaptive_tuning", True))
        if not isinstance(adaptive, bool):
            errors[f"{stage_id}.adaptiveTuning"] = "必须是布尔值"
            adaptive = True
        normalized["adaptiveTuning"] = adaptive
        batch_size = normalized.get("batchSize")
        transient_limit = normalized.get("transientFailureThreshold")
        if (
            type(batch_size) is int
            and type(transient_limit) is int
            and transient_limit > batch_size
        ):
            errors[f"{stage_id}.transientFailureThreshold"] = (
                "不能大于每批请求数上限，否则该熔断阈值永远不会触发"
            )
        normalized_stages[stage_id] = normalized
    failure_value = payload.get("failurePolicy")
    if not isinstance(failure_value, dict):
        errors["failurePolicy"] = "缺少失败停机配置"
        maximum_failures: int | float = 5
    else:
        for field in sorted(
            set(failure_value) - {"maxConsecutiveStageFailures"}
        ):
            errors[f"failurePolicy.{field}"] = "未知字段"
        try:
            maximum_failures = _validate_number(
                failure_value.get("maxConsecutiveStageFailures"),
                kind=int,
                minimum=1,
                maximum=100,
                field="failurePolicy.maxConsecutiveStageFailures",
            )
        except SettingsValidationError as exc:
            errors.update(exc.errors)
            maximum_failures = 5
    if errors:
        raise SettingsValidationError(errors)
    return {
        "stages": normalized_stages,
        "failurePolicy": {
            "maxConsecutiveStageFailures": int(maximum_failures)
        },
    }


def save_settings(payload: Any) -> dict[str, Any]:
    normalized = validate_settings(payload)
    with control_lock():
        config = load_object(CONFIG_PATH)
        if config.get("schema_version") != 1:
            raise RuntimeError("unsupported or missing queue config")
        for stage_id, values in normalized["stages"].items():
            stage = _find_stage(config, stage_id)
            command = stage.get("command")
            if not isinstance(command, list):
                raise RuntimeError(f"stage {stage_id!r} has no command array")
            for field, value in values.items():
                if field == "adaptiveTuning":
                    # Keep this policy out of the stage command so old
                    # crawlers and direct invocations remain compatible.
                    stage["adaptive_tuning"] = bool(value)
                    continue
                if field in GUARDRAIL_SPECS:
                    # Keep the canonical source in stage metadata and make
                    # the argv explicit.  ``_set_or_append_argument`` upgrades
                    # old commands that predate configurable guardrails.
                    _set_or_append_argument(command, GUARDRAIL_SPECS[field][0], value)
                    stage[GUARDRAIL_SNAKE_KEYS[field]] = value
                    continue
                aliases = LEGACY_ARGUMENT_ALIASES.get(field, (FIELD_SPECS[field][0],))
                _set_argument_any(command, aliases, value, canonical=FIELD_SPECS[field][0])
        maximum = normalized["failurePolicy"]["maxConsecutiveStageFailures"]
        policy = config.setdefault("failure_policy", {})
        if not isinstance(policy, dict):
            policy = {}
            config["failure_policy"] = policy
        policy["max_consecutive_stage_failures"] = maximum
        policy["stop_when_reached"] = True
        notifications = config.setdefault("notifications", {})
        if isinstance(notifications, dict):
            notifications["failed_attempt_threshold"] = maximum
        atomic_write_json(CONFIG_PATH, config)
    return read_settings(config)


def tail_text(path: Path, *, max_bytes: int = 65536, max_lines: int = 200) -> str:
    try:
        size = path.stat().st_size
        start = max(0, size - max(1, max_bytes))
        with path.open("rb") as handle:
            handle.seek(start)
            data = handle.read(max_bytes)
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace")
    if start > 0 and "\n" in text:
        text = text.split("\n", 1)[1]
    lines = text.splitlines()
    return "\n".join(lines[-max_lines:])


def tail_stage_attempt(
    path: Path,
    attempt: Any,
    *,
    max_bytes: int = 1024 * 1024,
    max_lines: int = 200,
) -> str:
    """Return a bounded log tail without leaking errors from older attempts.

    Stage logs are deliberately append-only so prior failures remain available
    for diagnosis.  The live dashboard, however, must not present those lines
    as current activity after a safe restart.  If the current attempt marker is
    inside the bounded scan window, keep only that marker and the lines after
    it.  When an attempt has already produced more than the scan window, the
    ordinary tail is necessarily part of that current attempt and is safe to
    show as-is.
    """

    scan = tail_text(path, max_bytes=max_bytes, max_lines=10000)
    lines = scan.splitlines()
    if type(attempt) is int and attempt > 0:
        marker = re.compile(rf"\bSTART attempt={attempt}(?:\s|$)")
        for index in range(len(lines) - 1, -1, -1):
            if marker.search(lines[index]):
                lines = lines[index:]
                break
    return "\n".join(lines[-max_lines:])


def _safe_stage_log(state: Mapping[str, Any]) -> Path | None:
    current = state.get("current_stage")
    relative = current.get("log") if isinstance(current, dict) else None
    if not isinstance(relative, str) or not relative:
        return None
    candidate = (WORKSPACE / relative).resolve()
    root = LOG_ROOT.resolve()
    return candidate if candidate.is_relative_to(root) else None


def _first_present(value: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in value:
            return value[key]
    return None


def _parse_timestamp(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _progress_belongs_to_attempt(
    value: Mapping[str, Any],
    *,
    stage_id: str | None,
    stage_started_at: Any,
    child_pid: int | None,
) -> tuple[bool, str]:
    source_pid = _positive_pid(value.get("pid"))
    current_pid = _positive_pid(child_pid)
    source_stage = value.get("queue_stage_id")
    if isinstance(source_stage, str) and stage_id and source_stage != stage_id:
        return False, "previous_stage"
    if source_pid is not None and current_pid is not None:
        if source_pid != current_pid:
            return False, "previous_process"
        return True, "pid_match"

    started = _parse_timestamp(stage_started_at)
    updated = _parse_timestamp(
        _first_present(value, "updated_at", "updatedAt")
    )
    if started is not None:
        if updated is None:
            return False, "missing_progress_time"
        # Legacy state written before process identity was added is accepted
        # only after the new attempt's start instant. Equality is deliberately
        # rejected because safe stop/restart can occur within the same second.
        if updated <= started:
            return False, "previous_attempt"
    return True, "time_match"


def _legacy_activity_label(phase: Any) -> tuple[int | None, str | None]:
    if not isinstance(phase, str) or not phase.strip():
        return None, None
    match = re.fullmatch(r"v(\d+)\s+(.+)", phase.strip())
    if match is None:
        return None, phase.strip()
    round_number = int(match.group(1))
    detail = match.group(2)
    return round_number, LEGACY_PHASE_LABELS.get(detail, detail)


def _modern_activity_label(value: Mapping[str, Any], phase: Any) -> str | None:
    label = MODERN_PHASE_LABELS.get(str(phase), str(phase) if phase else "")
    round_number = value.get("round")
    prefix = f"国区第{round_number}届" if type(round_number) is int else "国区高级搜索"
    parts = [prefix, label] if label else [prefix]
    dimension = value.get("currentDimension")
    if isinstance(dimension, str) and dimension:
        dimension_label = {
            "character_any": "角色入选条件",
            "character_first": "角色一票条件",
            "music_any": "音乐入选条件",
            "music_first": "音乐一票条件",
            "questionnaire_pair": "问卷两两交叉",
        }.get(dimension, dimension)
        parts.append(dimension_label)
    source_name = value.get("currentSourceName")
    if isinstance(source_name, str) and source_name.strip():
        parts.append(source_name.strip())
    return " · ".join(parts)


def _entity_questionnaire_activity_label(
    value: Mapping[str, Any], phase: Any
) -> str | None:
    stage = str(phase or "")
    labels = {
        "lock_acquired": "获取实体问卷补抓状态",
        "entity_questionnaire_start": "准备实体问卷明细",
        "entity_questionnaire": "抓取实体问卷明细",
        "entity_questionnaire_finished": "实体问卷明细处理完成",
        "entity_questionnaire_error": "实体问卷明细处理异常",
        "entity_questionnaire_recovered": "从断点恢复实体问卷明细",
        "entity_questionnaire_recovery_wait": "官网暂不可用，已保留断点等待重试",
        "finished": "实体问卷明细处理完成",
    }
    label = labels.get(stage, stage)
    round_number = value.get("round")
    prefix = f"国区第{round_number}届" if type(round_number) is int else "国区实体问卷"
    parts = [prefix, label] if label else [prefix]
    dimension = value.get("currentDimension")
    if isinstance(dimension, str) and dimension:
        parts.append(
            {
                "character_any": "角色入选条件",
                "music_any": "音乐入选条件",
            }.get(dimension, dimension)
        )
    source_name = value.get("currentSourceName")
    if isinstance(source_name, str) and source_name.strip():
        parts.append(source_name.strip())
    return " · ".join(parts)


def _entity_questionnaire_content_items(
    status_value: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Convert durable entity records into dashboard content rows.

    Coverage records are resumable checkpoints, not a second progress source.
    A malformed/in-progress coverage file is simply treated as empty; the
    queue status file still supplies the current item and numeric counters.
    """

    coverage = load_object(MODERN_ENTITY_QUESTIONNAIRE_COVERAGE)
    rounds = coverage.get("rounds")
    if not isinstance(rounds, list):
        rounds = []
    current_round = status_value.get("round") if isinstance(status_value, Mapping) else None
    current_dimension = (
        status_value.get("currentDimension")
        if isinstance(status_value, Mapping)
        else None
    )
    current_index = (
        status_value.get("currentSourceIndex")
        if isinstance(status_value, Mapping)
        else None
    )
    # ``currentSource*`` remains in the final status file for auditability,
    # but a finished attempt must not make that last row look in-progress.
    # Only an active/recovery stage may designate a row as current; completed
    # rows should retain their green state in the dashboard content list.
    status_name = (
        str(
            status_value.get("state")
            or status_value.get("status")
            or ""
        ).strip().lower()
        if isinstance(status_value, Mapping)
        else ""
    )
    stage_name = (
        str(status_value.get("stage") or "").strip().lower()
        if isinstance(status_value, Mapping)
        else ""
    )
    current_allowed = not (
        status_name in {"complete", "completed", "incomplete", "error"}
        or stage_name in {
            "finished",
            "entity_questionnaire_finished",
            "entity_questionnaire_error",
        }
    )
    if type(current_round) is int and not any(
        isinstance(item, Mapping) and item.get("round") == current_round
        for item in rounds
    ):
        rounds = [*rounds, {"round": current_round, "records": []}]
    recent_items: dict[tuple[str, int], dict[str, Any]] = {}
    supplied_recent = (
        status_value.get("recentItems")
        if isinstance(status_value, Mapping)
        else None
    )
    if isinstance(supplied_recent, list):
        for item in supplied_recent:
            if not isinstance(item, Mapping):
                continue
            category = item.get("sourceCategory")
            try:
                index = int(item.get("sourceIndex"))
            except (TypeError, ValueError):
                continue
            if isinstance(category, str) and category:
                recent_items[(category, index)] = dict(item)
    rows: list[dict[str, Any]] = []
    for round_value in rounds:
        if not isinstance(round_value, Mapping):
            continue
        try:
            round_number = int(round_value.get("round"))
        except (TypeError, ValueError):
            continue
        records = round_value.get("records")
        if not isinstance(records, list):
            continue
        catalogue: list[dict[str, Any]] = []
        base = load_object(
            WORKSPACE
            / "data_raw"
            / "cn_official"
            / f"round_{round_number}"
            / "graphql"
            / "base.json"
        )
        data = base.get("data") if isinstance(base.get("data"), Mapping) else {}
        for category, key, filter_key in (
            ("character", "queryCharacterRanking", "chars"),
            ("music", "queryMusicRanking", "musics"),
        ):
            ranking = data.get(key) if isinstance(data, Mapping) else None
            entries = ranking.get("entries") if isinstance(ranking, Mapping) else None
            if not isinstance(entries, list):
                continue
            for index, entry in enumerate(entries, start=1):
                if not isinstance(entry, Mapping):
                    continue
                name = str(entry.get("name") or "")
                catalogue.append(
                    {
                        "sourceCategory": category,
                        "conditionKind": "any",
                        "sourceIndex": index,
                        "sourceName": name,
                        "query": f"{filter_key}: " + json.dumps([name], ensure_ascii=False),
                    }
                )
        item_count = max(len(records), len(catalogue))
        for position in range(item_count):
            raw_record = records[position] if position < len(records) else {}
            record = dict(raw_record) if isinstance(raw_record, Mapping) else {}
            # Early interrupted versions recorded pending rows with only an
            # index.  Rebuild their labels from the already archived unfiltered
            # catalogue; no network request or checkpoint rewrite is needed.
            if position < len(catalogue):
                record = {**catalogue[position], **record}
            if not raw_record:
                record.setdefault("status", "pending")
            try:
                recent_index = int(record.get("sourceIndex") or 0)
            except (TypeError, ValueError):
                recent_index = 0
            recent_key = (str(record.get("sourceCategory") or ""), recent_index)
            if recent_key in recent_items:
                record = {**record, **recent_items[recent_key]}
            if not isinstance(record, Mapping):
                continue
            category = str(record.get("sourceCategory") or "")
            condition = str(record.get("conditionKind") or "any")
            source_index = record.get("sourceIndex")
            try:
                source_index = int(source_index)
            except (TypeError, ValueError):
                source_index = None
            dimension = f"{category}_{condition}" if category else None
            raw_status = str(record.get("status") or "pending")
            status = {
                "available_crawled": "completed",
                "official_query_defect": "completed",
                "fetch_failed": "failed",
                "pending": "pending",
            }.get(raw_status, raw_status)
            category_label = {"character": "角色", "music": "音乐"}.get(
                category, category or "实体"
            )
            source_name = str(record.get("sourceName") or "未命名实体")
            row: dict[str, Any] = {
                "id": f"cn{round_number}:{dimension or 'entity'}:{source_index}",
                "round": round_number,
                "sourceCategory": category,
                "conditionKind": condition,
                "sourceIndex": source_index,
                "dimension": dimension,
                "label": f"国区第{round_number}届 · {category_label} · {source_name}",
                "rawLabel": f"CN{round_number} {category_label} #{source_index if source_index is not None else '—'}",
                "name": source_name,
                "sourceName": source_name,
                "query": record.get("query"),
                "responsePath": record.get("responsePath"),
                "status": status,
                "completed": 1 if status == "completed" else 0,
                "total": 1,
            }
            row["current"] = (
                current_allowed
                and status not in {"completed", "failed"}
                and type(current_round) is int
                and round_number == current_round
                and dimension == current_dimension
                and source_index == current_index
            )
            rows.append(row)
    if rows:
        return rows
    fallback = status_value.get("contentItems") if isinstance(status_value, Mapping) else None
    return [dict(item) for item in fallback if isinstance(item, Mapping)] if isinstance(fallback, list) else []


def _entity_questionnaire_coverage_progress() -> dict[str, Any]:
    """Recover numeric progress from an older attempt without a status file."""

    coverage = load_object(MODERN_ENTITY_QUESTIONNAIRE_COVERAGE)
    rounds = coverage.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        return {}
    latest = rounds[-1] if isinstance(rounds[-1], Mapping) else {}
    if not latest:
        return {}
    expected = latest.get("expectedResponses")
    available = latest.get("availableCrawled")
    failed = latest.get("fetchFailed")
    pending = latest.get("pending")
    if not all(type(item) is int and item >= 0 for item in (expected, available, failed, pending)):
        return {}
    records = latest.get("records")
    current: Mapping[str, Any] = {}
    if isinstance(records, list):
        pending_record = next(
            (
                record
                for record in records
                if isinstance(record, Mapping) and record.get("status") == "pending"
            ),
            None,
        )
        failed_record = next(
            (
                record
                for record in reversed(records)
                if isinstance(record, Mapping) and record.get("status") == "fetch_failed"
            ),
            None,
        )
        current = failed_record or pending_record or {}
    enriched = _entity_questionnaire_content_items()
    next_pending = next(
        (item for item in enriched if item.get("status") == "pending"),
        None,
    )
    if next_pending is not None:
        current = next_pending
    elif current and not current.get("sourceCategory"):
        target_index = current.get("sourceIndex")
        current = next(
            (
                item
                for item in enriched
                if item.get("sourceIndex") == target_index
            ),
            current,
        )
    category = current.get("sourceCategory")
    condition = current.get("conditionKind")
    dimension = f"{category}_{condition}" if category and condition else None
    round_number = latest.get("round")
    return {
        "updatedAt": coverage.get("generatedAt"),
        "stage": "entity_questionnaire_recovered",
        "round": round_number,
        "completed": available,
        "successful": available,
        "processed": available + failed,
        "total": expected,
        "remaining": expected - available,
        "recordedFailures": failed,
        "currentDimension": dimension,
        "currentSourceIndex": current.get("sourceIndex"),
        "currentSourceName": current.get("sourceName"),
        "currentQuery": current.get("query"),
    }


# ``crawl_cn_legacy.fetch_many`` emits one bounded resource summary for every
# round/phase.  Keep this parser tied to that stable, human-readable contract
# so the dashboard can show the actual work list rather than only the current
# aggregate counter.  It intentionally ignores ordinary progress/error lines.
_CONTENT_SUMMARY_RE = re.compile(
    r"^\[v(?P<round>\d+)\s+(?P<phase>[^\]]+)\]\s+"
    r"(?P<resources>[\d,]+)\s+resources;\s*"
    r"cached=(?P<cached>[\d,]+),\s*"
    r"(?:local=(?P<local>[\d,]+),\s*)?"
    r"network=(?P<network>[\d,]+),\s*"
    r"workers=(?P<workers>\d+)\s*$",
    re.IGNORECASE,
)


def _parse_content_summary_lines(log_text: str) -> list[dict[str, Any]]:
    """Parse current-attempt ``[vN phase] ...`` resource summaries.

    Retries can repeat a summary for the same round/phase.  The dashboard
    should present one row per logical resource group, using the newest
    observation, while retaining the order in which groups first appeared.
    """

    if not isinstance(log_text, str) or not log_text:
        return []
    rows: dict[tuple[int, str], dict[str, Any]] = {}
    order: list[tuple[int, str]] = []
    for raw_line in log_text.splitlines():
        match = _CONTENT_SUMMARY_RE.match(raw_line.strip())
        if match is None:
            continue
        round_number = int(match.group("round"))
        phase = match.group("phase").strip()
        key = (round_number, phase)
        if key not in rows:
            order.append(key)
        phase_label = LEGACY_PHASE_LABELS.get(phase, phase)
        rows[key] = {
            "id": f"v{round_number} {phase}",
            "round": round_number,
            "phase": phase,
            "rawLabel": f"[v{round_number} {phase}]",
            "label": f"国区第{round_number}届 · {phase_label}",
            "resources": int(match.group("resources").replace(",", "")),
            "cached": int(match.group("cached").replace(",", "")),
            "local": int((match.group("local") or "0").replace(",", "")),
            "network": int(match.group("network").replace(",", "")),
            "workers": int(match.group("workers")),
        }
    return [rows[key] for key in order]


def _planned_content_items(
    stage_id: str | None,
    observed_items: Sequence[Mapping[str, Any]] | None = None,
    current_phase: Any = None,
) -> list[dict[str, Any]]:
    """Return every planned bracket-summary task for a legacy stage.

    A log only contains phases reached by the current attempt.  The UI needs a
    stable overview of the whole stage, including rounds that have not started
    yet, so merge the observed counters onto a static round/phase plan.  An
    observed phase before the current one is treated as completed; the current
    phase is marked ``current`` and later phases remain ``pending``.
    """

    if stage_id == "cn_legacy_advanced":
        rounds = range(5, 10)
        phases = LEGACY_ADVANCED_CONTENT_PHASES
    elif stage_id == "cn_legacy_remaining":
        rounds = range(1, 10)
        phases = LEGACY_REMAINING_CONTENT_PHASES
    else:
        return [dict(item) for item in (observed_items or []) if isinstance(item, Mapping)]

    observed: dict[tuple[int, str], dict[str, Any]] = {}
    observed_order: list[tuple[int, str]] = []
    for item in observed_items or ():
        if not isinstance(item, Mapping):
            continue
        try:
            round_number = int(item.get("round"))
        except (TypeError, ValueError):
            continue
        phase = item.get("phase")
        if not isinstance(phase, str) or not phase.strip():
            continue
        key = (round_number, phase.strip())
        if key not in observed:
            observed_order.append(key)
        observed[key] = dict(item)

    planned_keys = [(round_number, phase) for round_number in rounds for phase in phases]
    current_key: tuple[int, str] | None = None
    if isinstance(current_phase, str):
        match = re.fullmatch(r"v(\d+)\s+(.+)", current_phase.strip())
        if match:
            current_key = (int(match.group(1)), match.group(2).strip())

    positions = {key: index for index, key in enumerate(planned_keys)}
    current_position = positions.get(current_key) if current_key else None
    rows: list[dict[str, Any]] = []
    for key in planned_keys:
        round_number, phase = key
        row = dict(observed.get(key, {}))
        row.update(
            {
                "id": f"v{round_number} {phase}",
                "round": round_number,
                "phase": phase,
                "rawLabel": f"[v{round_number} {phase}]",
                "label": f"国区第{round_number}届 · {LEGACY_PHASE_LABELS.get(phase, phase)}",
            }
        )
        if key not in observed:
            row.setdefault("resources", None)
            row.setdefault("cached", None)
            row.setdefault("network", None)
            row.setdefault("workers", None)
        position = positions[key]
        if current_key == key:
            row["status"] = "current"
            row["current"] = True
        elif current_position is not None and position < current_position:
            row["status"] = "completed"
            row["current"] = False
        elif key in observed and current_position is None:
            row["status"] = "completed"
            row["current"] = False
        else:
            row["status"] = "pending"
            row["current"] = False
        rows.append(row)

    # Preserve a newly introduced/unknown bracket phase rather than silently
    # hiding it.  It is appended after the known plan and never affects order
    # or completion semantics of the stable rows above.
    for key in observed_order:
        if key in positions:
            continue
        row = dict(observed[key])
        round_number, phase = key
        row.setdefault("id", f"v{round_number} {phase}")
        row.setdefault("round", round_number)
        row.setdefault("phase", phase)
        row.setdefault("rawLabel", f"[v{round_number} {phase}]")
        row.setdefault(
            "label",
            f"国区第{round_number}届 · {LEGACY_PHASE_LABELS.get(phase, phase)}",
        )
        row["status"] = "current" if current_key == key else "completed"
        row["current"] = current_key == key
        rows.append(row)
    return rows


def _progress_for_stage(
    stage_id: str | None,
    *,
    stage_started_at: Any = None,
    child_pid: int | None = None,
    content_items: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if stage_id in ("cn_legacy_advanced", "cn_legacy_remaining"):
        value = load_object(LEGACY_RUN_STATE)
        phase = value.get("phase")
        completed = value.get("phase_completed_this_run")
        total = value.get("phase_total")
        remaining = value.get("phase_remaining")
        round_number, phase_label = _legacy_activity_label(phase)
        activity_label = (
            f"国区第{round_number}届 · {phase_label}"
            if round_number is not None and phase_label
            else phase_label
        )
    elif stage_id == "cn_modern_advanced":
        value = load_object(MODERN_RUN_STATE)
        status_content_items = value.get("contentItems")
        if isinstance(status_content_items, list):
            content_items = [
                dict(item)
                for item in status_content_items
                if isinstance(item, Mapping)
            ]
        phase = _first_present(value, "phase", "stage")
        completed = _first_present(value, "completed", "completedRequests")
        total = _first_present(value, "total", "totalRequests")
        remaining = _first_present(value, "remaining", "remainingRequests")
        round_number = value.get("round")
        activity_label = _modern_activity_label(value, phase)
    elif stage_id == "cn_modern_entity_questionnaire":
        value = load_object(MODERN_ENTITY_QUESTIONNAIRE_RUN_STATE)
        if not value:
            value = _entity_questionnaire_coverage_progress()
        phase = _first_present(value, "phase", "stage")
        completed = _first_present(value, "completed", "completedRequests")
        total = _first_present(value, "total", "totalRequests")
        remaining = _first_present(value, "remaining", "remainingRequests")
        round_number = value.get("round")
        activity_label = _entity_questionnaire_activity_label(value, phase)
    elif stage_id == "thwiki_arrangement_counts":
        value = load_object(THWIKI_ARRANGEMENT_COUNTS_RUN_STATE)
        status_content_items = value.get("contentItems")
        if isinstance(status_content_items, list):
            content_items = [
                dict(item)
                for item in status_content_items
                if isinstance(item, Mapping)
            ]
        phase = _first_present(value, "phase", "stage")
        completed = _first_present(value, "completed", "completedRequests")
        total = _first_present(value, "total", "totalRequests")
        remaining = _first_present(value, "remaining", "remainingRequests")
        round_number = None
        activity_label = value.get("activityLabel") or str(phase or "") or None
    else:
        value = {}
        phase = None
        completed = total = remaining = None
        round_number = None
        activity_label = None

    has_source = bool(value)
    belongs, ownership = _progress_belongs_to_attempt(
        value,
        stage_id=stage_id,
        stage_started_at=stage_started_at,
        child_pid=child_pid,
    ) if has_source else (False, "missing_progress")
    if not belongs:
        progress_capable = stage_id in (
            "cn_modern_advanced",
            "cn_modern_entity_questionnaire",
            "cn_legacy_advanced",
            "cn_legacy_remaining",
            "thwiki_arrangement_counts",
        )
        entity_items = (
            _entity_questionnaire_content_items(value)
            if stage_id == "cn_modern_entity_questionnaire"
            else []
        )
        planned_items = _planned_content_items(
            stage_id,
            entity_items or content_items,
            current_phase=None,
        )
        return {
            "status": (
                "initializing"
                if progress_capable
                else "non_quantified" if stage_id else "unavailable"
            ),
            "ownership": ownership,
            "phase": None,
            "activityLabel": None,
            "round": None,
            "currentDimension": None,
            "currentSourceIndex": None,
            "currentSourceName": None,
            "currentQuery": None,
            "interfaceFamily": None,
            "transientCircuitOpen": None,
            "stoppedReason": None,
            "resumable": None,
            "completed": None,
            "successful": None,
            "processed": None,
            "total": None,
            "remaining": None,
            "failed": None,
            "workers": None,
            "delay": None,
            "requestLimit": None,
            "batchSize": None,
            "batchPause": None,
            "adaptiveTuning": None,
            "adaptiveWorkerCeiling": None,
            "adaptiveSafeWorkerCeiling": None,
            "workerCeiling": None,
            "requestLimitCeiling": None,
            "batchPauseCeiling": None,
            "adaptivePauseFloor": None,
            "adaptivePauseRollback": None,
            "adaptivePauseProbeBlockedSeconds": None,
            "adaptivePauseSuccessStreak": None,
            "updatedAt": None,
            "sourcePid": _positive_pid(value.get("pid")),
            "percent": None,
            "phaseComplete": False,
            "contentItems": planned_items,
        }

    valid_numbers = (
        type(completed) in (int, float)
        and type(total) in (int, float)
        and math.isfinite(float(completed))
        and math.isfinite(float(total))
        and float(total) > 0
        and float(completed) >= 0
    )
    percent = (
        max(0.0, min(100.0, 100.0 * float(completed) / float(total)))
        if valid_numbers
        else None
    )
    phase_complete = bool(valid_numbers and float(completed) >= float(total))
    return {
        "status": "phase_complete" if phase_complete else "active",
        "ownership": ownership,
        "phase": phase,
        "activityLabel": activity_label,
        "round": round_number,
        "currentDimension": value.get("currentDimension"),
        "currentSourceIndex": value.get("currentSourceIndex"),
        "currentSourceName": value.get("currentSourceName"),
        "currentQuery": value.get("currentQuery"),
        "interfaceFamily": (
            value.get("interfaceFamily", "国区第10–11届现代 GraphQL 问卷搜索接口")
            if stage_id == "cn_modern_entity_questionnaire"
            else value.get(
                "interfaceFamily", "THBWiki Semantic MediaWiki 聚合计数接口"
            )
            if stage_id == "thwiki_arrangement_counts"
            else None
        ),
        "transientCircuitOpen": value.get("transientCircuitOpen"),
        "stoppedReason": value.get("stoppedReason"),
        "resumable": value.get("resumable"),
        "completed": completed,
        "successful": value.get("successful"),
        "processed": value.get("processed"),
        "total": total,
        "remaining": remaining,
        "failed": _first_present(value, "failed", "recordedFailures"),
        "workers": _first_present(value, "workers", "adaptive_workers", "adaptiveWorkers"),
        "configuredWorkers": _first_present(
            value, "configured_workers", "configuredWorkers", "workers", "adaptiveWorkers"
        ),
        "adaptiveWorkers": _first_present(
            value, "adaptive_workers", "adaptiveWorkers", "workers"
        ),
        "adaptiveWorkerCeiling": _first_present(
            value, "adaptive_worker_ceiling", "adaptiveWorkerCeiling"
        ),
        "adaptiveSafeWorkerCeiling": _first_present(
            value,
            "adaptive_safe_worker_ceiling",
            "adaptiveSafeWorkerCeiling",
            "adaptive_worker_ceiling",
            "adaptiveWorkerCeiling",
        ),
        "workerCeiling": _first_present(
            value,
            "worker_ceiling",
            "workerCeiling",
            "adaptive_worker_ceiling",
            "adaptiveWorkerCeiling",
            "worker_ceiling_limit",
        ),
        "requestLimitCeiling": _first_present(
            value,
            "request_limit_ceiling",
            "requestLimitCeiling",
            "request_limit_ceiling_limit",
        ),
        "batchPauseCeiling": _first_present(
            value,
            "batch_pause_ceiling",
            "batchPauseCeiling",
            "adaptive_batch_pause_ceiling_seconds",
            "adaptiveBatchPauseCeiling",
            "batch_pause_ceiling_limit",
        ),
        "adaptiveTuning": (
            value.get("adaptive_tuning", value.get("adaptiveTuning", True))
        ),
        "adaptiveBatchPause": _first_present(
            value, "adaptive_batch_pause_seconds", "batch_pause_seconds", "adaptiveBatchPause"
        ),
        "adaptivePauseFloor": _first_present(
            value, "adaptive_pause_floor_seconds", "adaptivePauseFloor"
        ),
        "adaptiveSafePauseFloor": _first_present(
            value,
            "adaptive_safe_pause_floor_seconds",
            "adaptive_pause_floor_seconds",
            "adaptiveSafePauseFloor",
        ),
        "adaptivePauseRollback": _first_present(
            value, "adaptive_pause_rollback", "adaptivePauseRollback"
        ),
        "adaptivePauseProbeBlockedSeconds": _first_present(
            value,
            "adaptive_pause_probe_blocked_seconds",
            "adaptivePauseProbeBlockedSeconds",
        ),
        "adaptivePauseSuccessStreak": (
            _first_present(value, "adaptive_pause_success_streak", "adaptiveSuccessStreak")
            or 0
        ),
        "adaptiveRecoveryAt": _first_present(
            value, "adaptive_recovery_at", "adaptiveRecoveryAt"
        ),
        "delay": value.get("minimum_seconds_between_request_starts", 0.0),
        "requestLimit": _first_present(value, "request_limit", "batch_size", "requestLimit"),
        "batchSize": _first_present(value, "batch_size", "request_limit", "requestLimit"),
        "batchPause": _first_present(
            value, "batch_pause_seconds", "adaptive_batch_pause_seconds", "batchPause"
        ),
        "updatedAt": _first_present(value, "updated_at", "updatedAt"),
        "sourcePid": _positive_pid(value.get("pid")),
        "percent": percent,
        "phaseComplete": phase_complete,
        "contentItems": _planned_content_items(
            stage_id,
            (
                _entity_questionnaire_content_items(value)
                if stage_id == "cn_modern_entity_questionnaire"
                else content_items
            ),
            current_phase=None if phase_complete else phase,
        ),
    }


def _stage_label(stage: Mapping[str, Any]) -> str:
    stage_id = str(stage.get("id") or "")
    supplied = stage.get("label")
    return (
        supplied.strip()
        if isinstance(supplied, str) and supplied.strip()
        else DEFAULT_STAGE_LABELS.get(stage_id, stage_id)
    )


def _stage_kind(stage: Mapping[str, Any]) -> str:
    stage_id = str(stage.get("id") or "")
    supplied = stage.get("kind")
    return (
        supplied.strip()
        if isinstance(supplied, str) and supplied.strip()
        else DEFAULT_STAGE_KINDS.get(stage_id, "task")
    )


def _activity_text(
    label: str,
    progress: Mapping[str, Any],
    *,
    current_status: Any,
    task_status: str,
) -> str:
    progress_status = progress.get("status")
    activity_label = progress.get("activityLabel")
    target = activity_label if isinstance(activity_label, str) and activity_label else label
    if task_status == "stopped":
        return f"已安全停止于：{target}"
    if task_status == "stopping":
        return f"正在安全停止：{target}"
    if task_status == "retry_wait":
        return f"等待重试：{target}"
    if task_status in ("failed", "stale"):
        return f"执行异常：{target}"
    if current_status == "preparing" or progress_status == "initializing":
        return f"正在启动并恢复断点：{label}"
    if progress_status == "phase_complete" and activity_label:
        return f"已完成：{activity_label}；正在准备下一项"
    if isinstance(activity_label, str) and activity_label:
        return f"正在抓取：{activity_label}"
    return f"正在执行：{label}"


def _queue_tasks(
    stages: Sequence[Mapping[str, Any]],
    state: Mapping[str, Any],
    *,
    effective_status: str,
    runner_alive: bool,
    progress: Mapping[str, Any],
) -> list[dict[str, Any]]:
    completed = set(state.get("completed_stages", []))
    attempts = state.get("stage_attempts")
    attempts = attempts if isinstance(attempts, Mapping) else {}
    failures = state.get("stage_failures")
    failures = failures if isinstance(failures, Mapping) else {}
    streaks = state.get("consecutive_stage_failures")
    streaks = streaks if isinstance(streaks, Mapping) else {}
    current = state.get("current_stage")
    current = current if isinstance(current, Mapping) else {}
    current_id = current.get("id")

    if (
        (not current_id or current_id in completed)
        and runner_alive
        and effective_status == "running"
    ):
        next_pending = next(
            (stage for stage in stages if stage.get("id") not in completed),
            None,
        )
        if next_pending is not None:
            current_id = next_pending.get("id")

    tasks: list[dict[str, Any]] = []
    for index, stage in enumerate(stages, start=1):
        stage_id = str(stage.get("id") or "")
        is_current = stage_id == current_id
        if stage_id in completed:
            task_status = "completed"
            is_current = False
        elif not is_current:
            task_status = "pending"
        elif effective_status == "retry_wait":
            task_status = "retry_wait"
        elif effective_status == "stopping":
            task_status = "stopping"
        elif effective_status == "stale":
            task_status = "stale"
        elif effective_status in FAILURE_STOP_STATUSES or effective_status == IDENTITY_CONFLICT_STATUS:
            task_status = "failed"
        elif effective_status == "stopped_by_signal":
            task_status = "stopped"
        elif current.get("status") == "preparing" or not current:
            task_status = "preparing"
        elif current.get("status") == "finished":
            task_status = "transitioning"
        else:
            task_status = "running"
        label = _stage_label(stage)
        task = {
            "index": index,
            "id": stage_id,
            "label": label,
            "description": stage.get("description"),
            "kind": _stage_kind(stage),
            "status": task_status,
            "isCurrent": is_current,
            "attempt": (
                current.get("attempt")
                if is_current and current.get("attempt") is not None
                else attempts.get(stage_id, 0)
            ),
            "failureCount": failures.get(stage_id, 0),
            "consecutiveFailures": streaks.get(stage_id, 0),
        }
        if is_current:
            task["activity"] = _activity_text(
                label,
                progress,
                current_status=current.get("status"),
                task_status=task_status,
            )
            task["progress"] = {
                key: progress.get(key)
                for key in (
                    "status",
                    "completed",
                    "successful",
                    "processed",
                    "total",
                    "remaining",
                    "percent",
                    "round",
                    "activityLabel",
                    "currentDimension",
                    "currentSourceIndex",
                    "currentSourceName",
                    "currentQuery",
                    "transientCircuitOpen",
                    "stoppedReason",
                    "resumable",
                    "contentItems",
                )
            }
        tasks.append(task)
    return tasks


def status_snapshot(*, include_logs: bool = True) -> dict[str, Any]:
    processes = process_snapshot()
    state = processes.pop("state")
    pid_record = processes.pop("pidRecord")
    current = state.get("current_stage")
    current = current if isinstance(current, dict) else {}
    status = str(state.get("status") or "not_started")
    if processes["stopRequested"] and (
        processes["runnerAlive"] or processes["childAlive"]
    ):
        effective_status = "stopping"
    elif processes["runnerAlive"]:
        effective_status = "running" if status != "retry_wait" else "retry_wait"
    elif status == "running" or current.get("status") == "running":
        effective_status = "stale"
    else:
        effective_status = status
    config = load_object(CONFIG_PATH)
    stages = config.get("stages") if isinstance(config.get("stages"), list) else []
    completed_stages = state.get("completed_stages")
    completed_stages = completed_stages if isinstance(completed_stages, list) else []
    configured_stage_ids = {
        str(stage.get("id"))
        for stage in stages
        if isinstance(stage, Mapping) and stage.get("id")
    }
    # A queue may be upgraded in place.  Keep historical stage ids in the
    # durable state for auditability, but do not count removed stages in the
    # operator-facing totals or task list.
    visible_completed_stages = [
        stage_id
        for stage_id in completed_stages
        if str(stage_id) in configured_stage_ids
    ]
    progress_stage_id = current.get("id")
    progress_started_at = current.get("started_at")
    progress_child_pid = current.get("child_pid")
    if (
        progress_stage_id in set(completed_stages)
        and processes["runnerAlive"]
        and effective_status == "running"
    ):
        following = next(
            (stage for stage in stages if stage.get("id") not in completed_stages),
            None,
        )
        progress_stage_id = following.get("id") if isinstance(following, Mapping) else None
        progress_started_at = utc_now()
        progress_child_pid = None
    stage_log = _safe_stage_log(state)
    stage_log_text = (
        tail_stage_attempt(
            stage_log,
            current.get("attempt"),
            max_bytes=4 * 1024 * 1024,
            max_lines=10000,
        )
        if stage_log and progress_stage_id == current.get("id")
        else ""
    )
    content_items = _parse_content_summary_lines(stage_log_text)
    progress = _progress_for_stage(
        progress_stage_id,
        stage_started_at=progress_started_at,
        child_pid=progress_child_pid,
        content_items=content_items,
    )
    tasks = _queue_tasks(
        stages,
        state,
        effective_status=effective_status,
        runner_alive=bool(processes["runnerAlive"]),
        progress=progress,
    )
    active_task = next((task for task in tasks if task.get("isCurrent")), None)
    active_task = active_task if isinstance(active_task, dict) else {}
    active_matches_current = bool(
        active_task.get("id") and active_task.get("id") == current.get("id")
    )
    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "generatedAt": utc_now(),
        "queue": {
            "name": config.get("queue_name") or state.get("queue_name"),
            "status": status,
            "effectiveStatus": effective_status,
            "updatedAt": state.get("updated_at"),
            "completedStages": visible_completed_stages,
            "stageCount": len(stages),
            "completedStageCount": len(visible_completed_stages),
            "currentTaskId": active_task.get("id"),
            "lastError": state.get("last_error"),
            "lastStop": state.get("last_stop"),
            "lastFailureStop": state.get("last_failure_stop"),
            "consecutiveStageFailures": state.get(
                "consecutive_stage_failures", {}
            ),
            "totalStageFailures": state.get("stage_failures", {}),
        },
        "stage": {
            "id": current.get("id") or active_task.get("id"),
            "label": active_task.get("label"),
            "kind": active_task.get("kind"),
            "description": (
                current.get("description")
                if active_matches_current
                else active_task.get("description")
            ),
            "activity": active_task.get("activity"),
            "status": (
                current.get("status")
                if active_matches_current
                else active_task.get("status")
            ),
            "attempt": (
                current.get("attempt")
                if active_matches_current
                else active_task.get("attempt")
            ),
            "startedAt": current.get("started_at") if active_matches_current else None,
            "finishedAt": current.get("finished_at") if active_matches_current else None,
            "exitCode": current.get("exit_code") if active_matches_current else None,
        },
        "processes": {
            **processes,
            "runnerStartedAt": pid_record.get("started_at"),
        },
        "progress": progress,
        "tasks": tasks,
        "settings": read_settings(config),
    }
    if include_logs:
        payload["logs"] = {
            "queue": tail_text(LOG_ROOT / "queue.log", max_lines=80),
            "stage": "\n".join(stage_log_text.splitlines()[-120:]),
        }
    payload["controls"] = {
        "identityConflict": status == IDENTITY_CONFLICT_STATUS,
        "canStart": not processes["runnerAlive"]
        and not processes["runnerLockHeld"]
        and status != IDENTITY_CONFLICT_STATUS,
        "canStop": processes["runnerAlive"]
        or processes["childAlive"]
        or processes["runnerLockHeld"],
        "canRestart": status != IDENTITY_CONFLICT_STATUS,
        "canRebenchmark": status != IDENTITY_CONFLICT_STATUS
        and payload["stage"].get("id") in ALL_TUNABLE_STAGE_IDS,
        "settingsApplyImmediately": not processes["runnerAlive"],
    }
    return payload


def _json_safe_result(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe_result(item) for key, item in value.items() if key != "state"}
    if isinstance(value, list):
        return [_json_safe_result(item) for item in value]
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("status", "start", "stop", "restart", "rebenchmark", "settings"),
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--stage-id", default="")
    parser.add_argument("--no-logs", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "status":
            result = status_snapshot(include_logs=not args.no_logs)
        elif args.action == "start":
            result = start_queue()
        elif args.action == "stop":
            result = stop_queue(timeout=args.timeout)
        elif args.action == "restart":
            result = restart_queue(timeout=args.timeout)
        elif args.action == "rebenchmark":
            result = rebenchmark_stage(args.stage_id, timeout=args.timeout)
        else:
            result = read_settings()
    except BaseException as exc:
        result = {
            "ok": False,
            "action": args.action,
            "error": f"{type(exc).__name__}: {exc}",
        }
    print(json.dumps(_json_safe_result(result), ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) is not False else 1


if __name__ == "__main__":
    raise SystemExit(main())
