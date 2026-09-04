#!/usr/bin/env python3
"""Run the official-data crawl as a durable, sequential background queue.

The queue definition lives in ``metadata/data_crawl_queue.json``.  Each stage
is a normal argv array (no shell), is retried with bounded exponential backoff,
and must finish before the next stage starts.  State and logs are written after
every transition so the runner can be restarted safely with ``--resume``.

This program intentionally contains no article analysis or social-media work.
It only orchestrates crawlers, normalization, and coverage validation.
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import json
import msvcrt
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, BinaryIO, Mapping, Sequence


WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = WORKSPACE / "metadata" / "data_crawl_queue.json"
DEFAULT_STATE = WORKSPACE / "metadata" / "data_crawl_queue_state.json"
DEFAULT_LOCK = WORKSPACE / "metadata" / ".data_crawl_queue.lock"
DEFAULT_PID = WORKSPACE / "metadata" / "data_crawl_queue_pid.json"
DEFAULT_STOP = WORKSPACE / "metadata" / "data_crawl_queue.stop"
LOG_ROOT = WORKSPACE / "metadata" / "logs" / "data_crawl_queue"

# Guardrails are stored as stage metadata so older queue commands remain
# readable.  At launch the runner materializes them as ordinary argv options;
# a transitional command that already contains one is updated in place.
STAGE_GUARDRAIL_ARGUMENTS = {
    "worker_ceiling": "--worker-ceiling",
    "request_limit_ceiling": "--request-limit-ceiling",
    "batch_pause_ceiling": "--batch-pause-ceiling",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def append_event(message: str) -> None:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    line = f"{utc_now()} {message}\n"
    with (LOG_ROOT / "queue.log").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()


def run_notification_child(kind: str, title: str, message: str) -> int:
    """Display one Windows message box without acquiring the queue lock."""

    styles = {
        "retry_threshold": 0x00000030,  # MB_ICONWARNING
        "queue_complete": 0x00000040,  # MB_ICONINFORMATION
    }
    try:
        result = ctypes.windll.user32.MessageBoxW(
            None,
            message,
            title,
            styles.get(kind, 0x00000040) | 0x00040000,  # MB_TOPMOST
        )
    except BaseException as exc:
        append_event(
            f"notification child failed kind={kind}: {type(exc).__name__}: {exc}"
        )
        return 1
    if result == 0:
        append_event(f"notification child returned zero kind={kind}")
        return 1
    return 0


def launch_notification(kind: str, title: str, message: str) -> bool:
    """Start a detached popup process; notification failure never stops work."""

    executable = Path(sys.executable)
    pythonw = executable.with_name("pythonw.exe")
    if pythonw.is_file():
        executable = pythonw
    command = [
        str(executable),
        str(Path(__file__).resolve()),
        "--notification-child",
        kind,
        title,
        message,
    ]
    creationflags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    )
    try:
        process = subprocess.Popen(
            command,
            cwd=WORKSPACE,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
    except BaseException as exc:
        append_event(
            f"notification launch failed kind={kind}: {type(exc).__name__}: {exc}"
        )
        return False
    append_event(f"notification launched kind={kind} child_pid={process.pid}")
    return True


def notification_settings(config: Mapping[str, Any]) -> Mapping[str, Any]:
    value = config.get("notifications", {})
    return value if isinstance(value, Mapping) else {}


def notification_markers(state: dict[str, Any]) -> dict[str, Any]:
    markers = state.setdefault(
        "notification_markers",
        {"retry_threshold": {}, "queue_complete": None},
    )
    if not isinstance(markers, dict):
        markers = {"retry_threshold": {}, "queue_complete": None}
        state["notification_markers"] = markers
    if not isinstance(markers.get("retry_threshold"), dict):
        markers["retry_threshold"] = {}
    markers.setdefault("queue_complete", None)
    return markers


def record_stage_failure(state: dict[str, Any], stage_id: str) -> int:
    """Record exactly one observed stage failure and return its lifetime total.

    ``stage_attempts`` is deliberately not used here.  An attempt can be
    interrupted by an operator stop, and old runner versions could increment
    it before failing to launch a command.  Neither case is evidence of a real
    stage failure.
    """

    failures = state.setdefault("stage_failures", {})
    if not isinstance(failures, dict):
        failures = {}
        state["stage_failures"] = failures
    try:
        previous = max(0, int(failures.get(stage_id, 0)))
    except (TypeError, ValueError):
        previous = 0
    failures[stage_id] = previous + 1

    streaks = state.setdefault("consecutive_stage_failures", {})
    if not isinstance(streaks, dict):
        streaks = {}
        state["consecutive_stage_failures"] = streaks
    try:
        previous_streak = max(0, int(streaks.get(stage_id, 0)))
    except (TypeError, ValueError):
        previous_streak = 0
    streaks[stage_id] = previous_streak + 1
    return int(failures[stage_id])


def consecutive_stage_failures(state: Mapping[str, Any], stage_id: str) -> int:
    streaks = state.get("consecutive_stage_failures", {})
    if not isinstance(streaks, Mapping):
        return 0
    try:
        return max(0, int(streaks.get(stage_id, 0)))
    except (TypeError, ValueError):
        return 0


def clear_stage_failure_streak(state: dict[str, Any], stage_id: str) -> None:
    streaks = state.setdefault("consecutive_stage_failures", {})
    if not isinstance(streaks, dict):
        streaks = {}
        state["consecutive_stage_failures"] = streaks
    streaks[stage_id] = 0


def failure_limit(config: Mapping[str, Any]) -> int:
    policy = config.get("failure_policy", {})
    if not isinstance(policy, Mapping):
        policy = {}
    fallback = notification_settings(config).get("failed_attempt_threshold", 5)
    try:
        return max(1, int(policy.get("max_consecutive_stage_failures", fallback)))
    except (TypeError, ValueError):
        return 5


def reset_failure_run(state: dict[str, Any]) -> None:
    """Start a fresh retry budget while preserving lifetime failure totals."""

    state["consecutive_stage_failures"] = {}
    markers = notification_markers(state)
    markers["retry_threshold"] = {}
    if state.get("status") == "stopped_after_failures":
        state["last_failure_stop"] = state.get("last_error")
        state["last_error"] = None
        state["status"] = "queued"
    elif state.get("status") == "stopped_by_signal":
        # A neutral operator stop may leave a finished 130/143 child record in
        # current_stage. It has already been accounted for by last_stop and
        # must not be replayed as a real failure after the sentinel is removed.
        state["current_stage"] = None
        state["last_error"] = None
        state["status"] = "queued"
    state["failure_run_started_at"] = utc_now()


def maybe_notify_retry_threshold(
    config: Mapping[str, Any],
    state: dict[str, Any],
    state_path: Path,
    stage: Mapping[str, Any],
    failure_count: int,
    reason: str,
    *,
    stopped: bool = False,
) -> None:
    settings = notification_settings(config)
    if not bool(settings.get("enabled", True)):
        return
    try:
        threshold = max(1, int(settings.get("failed_attempt_threshold", 5)))
    except (TypeError, ValueError):
        threshold = 5
    if failure_count < threshold:
        return
    stage_id = str(stage["id"])
    markers = notification_markers(state)
    retry_markers = markers["retry_threshold"]
    previous_marker = retry_markers.get(stage_id)
    if isinstance(previous_marker, Mapping) and (
        not stopped or bool(previous_marker.get("stopped"))
    ):
        return

    # Persist the claim before spawning the popup.  This deliberately gives
    # at-most-once delivery across runner restarts.
    marker = {
        "attempted_at": utc_now(),
        "failed_attempts": failure_count,
        "threshold": threshold,
        "stopped": stopped,
        "launch_status": "claimed",
    }
    retry_markers[stage_id] = marker
    save_state(state, state_path)
    description = str(stage.get("description") or stage_id)
    outcome = (
        "已达到连续失败上限，队列已停机；修复问题后可从断点重新启动。"
        if stopped
        else "尚未达到停机上限，队列会按退避策略继续重试。"
    )
    message = (
        f"抓取阶段已连续失败 {failure_count} 次。{outcome}\n\n"
        f"阶段：{description}\n"
        f"最近错误：{reason}\n"
        f"日志：{(LOG_ROOT / (stage_id + '.log')).relative_to(WORKSPACE)}"
    )
    title = (
        "东方投票数据抓取队列：失败超限，已停机"
        if stopped
        else "东方投票数据抓取队列：需要检查"
    )
    launched = launch_notification("retry_threshold", title, message)
    marker["launch_status"] = "launched" if launched else "failed"
    marker["launch_recorded_at"] = utc_now()
    save_state(state, state_path)


def maybe_notify_queue_complete(
    config: Mapping[str, Any], state: dict[str, Any], state_path: Path
) -> None:
    settings = notification_settings(config)
    if not bool(settings.get("enabled", True)) or not bool(
        settings.get("notify_on_complete", True)
    ):
        return
    markers = notification_markers(state)
    if markers.get("queue_complete") is not None:
        return
    marker = {
        "attempted_at": utc_now(),
        "launch_status": "claimed",
    }
    markers["queue_complete"] = marker
    save_state(state, state_path)
    launched = launch_notification(
        "queue_complete",
        "东方投票数据抓取队列：已完成",
        "所有队列阶段及其配置的成功检查均已通过。\n"
        "日区 3–22 届、国区 1–11 届的本轮抓取队列已经结束。",
    )
    marker["launch_status"] = "launched" if launched else "failed"
    marker["launch_recorded_at"] = utc_now()
    save_state(state, state_path)


def acquire_lock(path: Path) -> BinaryIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        handle.close()
        raise RuntimeError("another data-crawl queue runner already holds the lock") from exc
    return handle


def process_exit_code(pid: int) -> int | None:
    """Return None while a Windows process is active, otherwise its exit code.

    A missing/inaccessible PID is represented as -1.  The runner is Windows-
    specific because this workspace is Windows and uses ``Start-Process``.
    """

    process_query_limited_information = 0x1000
    synchronize = 0x00100000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(
        process_query_limited_information | synchronize, False, int(pid)
    )
    if not handle:
        return -1
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return -1
        return None if code.value == still_active else int(code.value)
    finally:
        kernel32.CloseHandle(handle)


def process_identity(pid: int) -> dict[str, Any]:
    """Capture the stop helper's PID-reuse-resistant process identity.

    The helper is imported lazily so a partially deployed update still starts
    the queue.  A PID-only fallback is intentionally marked incomplete; the
    hardened stop helper can then refuse a destructive action instead of
    trusting stale metadata.
    """

    try:
        try:
            from scripts_pipeline import stop_data_crawl_queue as stop_helper
        except ModuleNotFoundError:
            # Direct ``python scripts_pipeline/run_data_crawl_queue.py`` puts
            # the script directory, rather than its parent, first on sys.path.
            import stop_data_crawl_queue as stop_helper

        capture = getattr(stop_helper, "process_identity", None)
        if callable(capture):
            value = capture(pid)
            if isinstance(value, Mapping):
                return dict(value)
    except Exception as exc:
        append_event(
            f"process identity capture failed pid={pid}: "
            f"{type(exc).__name__}: {exc}"
        )
    return {"pid": int(pid), "identity_complete": False}


class ChildIdentityError(RuntimeError):
    """A recorded running child cannot be proven to be the crawler child."""


def verified_child_exit_code(
    pid: int, expected_identity: Mapping[str, Any] | None
) -> int | None:
    """Return an exit code only after PID-reuse-resistant identity checks."""

    try:
        try:
            from scripts_pipeline import stop_data_crawl_queue as stop_helper
        except ModuleNotFoundError:
            import stop_data_crawl_queue as stop_helper
        verify = getattr(stop_helper, "verified_process_exit_code", None)
        if not callable(verify):
            raise ChildIdentityError("process identity verifier is unavailable")
        verified, code, detail = verify(pid, expected_identity)
    except ChildIdentityError:
        raise
    except Exception as exc:
        raise ChildIdentityError(
            f"cannot verify recorded child identity: {type(exc).__name__}: {exc}"
        ) from exc
    if not verified:
        raise ChildIdentityError(str(detail))
    return code


def resolve_command(command: Sequence[str]) -> list[str]:
    substitutions = {
        "{python}": sys.executable,
        "{node}": shutil.which("node") or "node",
        "{workspace}": str(WORKSPACE),
    }
    return [substitutions.get(part, part) for part in command]


def apply_stage_guardrails(
    command: list[str], stage: Mapping[str, Any]
) -> list[str]:
    """Inject configured stage guardrails into a resolved crawler command."""

    for stage_key, flag in STAGE_GUARDRAIL_ARGUMENTS.items():
        camel_key = "".join(
            part if index == 0 else part.capitalize()
            for index, part in enumerate(stage_key.split("_"))
        )
        value = stage.get(stage_key, stage.get(camel_key))
        if value is None:
            continue
        try:
            index = command.index(flag)
        except ValueError:
            command.extend((flag, str(value)))
        else:
            if index + 1 >= len(command):
                raise ValueError(f"stage command has no value for {flag}")
            command[index + 1] = str(value)
    return command


def read_path(value: Any, keys: Sequence[str | int]) -> Any:
    current = value
    for key in keys:
        if isinstance(key, int):
            current = current[key]
        else:
            current = current[key]
    return current


def checks_pass(stage: Mapping[str, Any]) -> tuple[bool, str]:
    checks = stage.get("success_checks", [])
    for check in checks:
        kind = check.get("type")
        path = WORKSPACE / check["path"]
        if kind == "file_exists":
            if not path.is_file():
                return False, f"missing success artifact: {path}"
        elif kind == "json_path_equals":
            if not path.is_file():
                return False, f"missing success artifact: {path}"
            try:
                actual = read_path(load_json(path), check.get("json_path", []))
            except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
                return False, f"cannot read success check {path}: {exc}"
            expected = check.get("equals")
            if actual != expected:
                return False, f"success check failed for {path}: {actual!r} != {expected!r}"
        else:
            return False, f"unknown success check type: {kind!r}"
    return True, "ok"


def initial_state(config: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "queue_name": config.get("queue_name", "official-data-crawl"),
        "status": "queued",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "current_stage": None,
        "completed_stages": [],
        "stage_attempts": {},
        "stage_failures": {},
        "consecutive_stage_failures": {},
        "last_error": None,
    }


def save_state(state: dict[str, Any], state_path: Path) -> None:
    state["updated_at"] = utc_now()
    atomic_write_json(state_path, state)


def load_state(config: Mapping[str, Any], state_path: Path) -> dict[str, Any]:
    if not state_path.is_file():
        return initial_state(config)
    state = load_json(state_path)
    if state.get("schema_version") != 1:
        raise RuntimeError(f"unsupported queue state schema: {state.get('schema_version')}")
    return state


def next_stage(config: Mapping[str, Any], state: Mapping[str, Any]) -> Mapping[str, Any] | None:
    completed = set(state.get("completed_stages", []))
    stages = list(config.get("stages", []))
    for index, stage in enumerate(stages):
        stage_id = str(stage["id"])
        if stage_id not in completed:
            return stage
        # A completed-stage marker is only a cache hint. Re-check the current
        # success contract before skipping it so tightened validation rules or
        # a changed output schema automatically reopen the stage on resume.
        if stage.get("success_checks"):
            ok, _ = checks_pass(stage)
            if not ok:
                # Downstream transforms/validations consume this artifact. If
                # an old completion marker is invalidated, discard completion
                # markers for this stage and everything after it so they are
                # rebuilt against the newly fetched data.
                prior_ids = {str(item["id"]) for item in stages[:index]}
                prior = state.get("completed_stages")
                if isinstance(prior, list):
                    state["completed_stages"] = [
                        item for item in prior if str(item) in prior_ids
                    ]
                state.pop("completed_at", None)
                return stage
    return None


def preparing_stage_record(
    stage: Mapping[str, Any], state: Mapping[str, Any]
) -> dict[str, Any]:
    """Describe the next stage before its child process has been launched."""

    stage_id = str(stage["id"])
    attempts = state.get("stage_attempts")
    attempts = attempts if isinstance(attempts, Mapping) else {}
    next_attempt = int(attempts.get(stage_id, 0)) + 1
    stage_log = LOG_ROOT / f"{stage_id}.log"
    return {
        "id": stage_id,
        "label": stage.get("label", ""),
        "kind": stage.get("kind", "task"),
        "description": stage.get("description", ""),
        "status": "preparing",
        "attempt": next_attempt,
        "child_pid": None,
        "parent_runner_pid": os.getpid(),
        "started_at": utc_now(),
        "log": stage_log.relative_to(WORKSPACE).as_posix(),
    }


def stage_result_from_current(
    stage: Mapping[str, Any], current: Mapping[str, Any]
) -> tuple[int, str]:
    try:
        exit_code = int(current.get("exit_code", -1))
    except (TypeError, ValueError):
        exit_code = -1
    ok, check_reason = checks_pass(stage)
    if exit_code == 0 and ok:
        return 0, "ok"
    if exit_code != 0:
        return exit_code, str(
            current.get("launch_error") or f"stage command exited {exit_code}"
        )
    return 1, check_reason


def wait_for_existing_child(
    stage: Mapping[str, Any], state: dict[str, Any], state_path: Path, poll_seconds: float
) -> tuple[int, str] | None:
    """Recover one unprocessed result from a child owned by an older runner.

    A finished failure stays in ``current_stage`` until its counter update is
    saved.  This closes the crash window between observing the child's exit and
    recording the failure, while ``failure_recorded`` prevents double counts.
    """

    current = state.get("current_stage") or {}
    if current.get("id") != stage["id"]:
        return None
    if current.get("status") == "finished":
        if current.get("failure_recorded"):
            return None
        return stage_result_from_current(stage, current)
    if current.get("status") != "running":
        return None
    child_pid = current.get("child_pid")
    if not isinstance(child_pid, int):
        return None
    child_identity = current.get("child_identity")
    if not isinstance(child_identity, Mapping):
        raise ChildIdentityError(
            "recorded running child has no reusable process identity"
        )
    append_event(f"reattaching to stage={stage['id']} child_pid={child_pid}")
    while True:
        code = verified_child_exit_code(child_pid, child_identity)
        if code is not None:
            current["exit_code"] = code
            current["finished_at"] = utc_now()
            current["status"] = "finished"
            state["current_stage"] = current
            save_state(state, state_path)
            return stage_result_from_current(stage, current)
        time.sleep(poll_seconds)


def run_stage(
    stage: Mapping[str, Any], state: dict[str, Any], state_path: Path, poll_seconds: float
) -> tuple[int, str]:
    stage_id = stage["id"]
    attempts = state.setdefault("stage_attempts", {})
    attempt = int(attempts.get(stage_id, 0)) + 1
    attempts[stage_id] = attempt
    command = apply_stage_guardrails(resolve_command(stage["command"]), stage)
    executable = Path(command[0])
    script_candidate = WORKSPACE / command[1] if len(command) > 1 else None
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    stage_log = LOG_ROOT / f"{stage_id}.log"
    started_at = utc_now()

    def persist_launch_failure(exit_code: int, reason: str) -> tuple[int, str]:
        state["status"] = "running"
        state["current_stage"] = {
            "id": stage_id,
            "description": stage.get("description", ""),
            "status": "finished",
            "attempt": attempt,
            "child_pid": None,
            "parent_runner_pid": os.getpid(),
            "started_at": started_at,
            "finished_at": utc_now(),
            "exit_code": exit_code,
            "launch_error": reason,
            "log": stage_log.relative_to(WORKSPACE).as_posix(),
        }
        save_state(state, state_path)
        append_event(
            f"stage={stage_id} attempt={attempt} could not start: {reason}"
        )
        return exit_code, reason

    if not executable.is_file():
        return persist_launch_failure(127, f"executable not found: {executable}")
    if script_candidate is not None and command[1].endswith(".py") and not script_candidate.is_file():
        return persist_launch_failure(
            127, f"stage script not ready: {script_candidate}"
        )

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["DATA_CRAWL_QUEUE_STAGE_ID"] = stage_id
    env["DATA_CRAWL_QUEUE_STAGE_ATTEMPT"] = str(attempt)
    env["DATA_CRAWL_QUEUE_STAGE_STARTED_AT"] = started_at
    for stage_key in STAGE_GUARDRAIL_ARGUMENTS:
        camel_key = "".join(
            part if index == 0 else part.capitalize()
            for index, part in enumerate(stage_key.split("_"))
        )
        guard_value = stage.get(stage_key, stage.get(camel_key))
        if guard_value is not None:
            env[f"DATA_CRAWL_{stage_key.upper()}"] = str(guard_value)
    # Automatic throttling has two separate behaviours: transient failures
    # always reduce load, while recovery after a success streak is optional.
    # Keep the switch in the queue JSON (rather than appending a CLI flag) so
    # old crawler commands remain launchable.
    adaptive_tuning = stage.get("adaptive_tuning", stage.get("adaptiveTuning", True))
    adaptive_disabled = adaptive_tuning is False or (
        isinstance(adaptive_tuning, str)
        and adaptive_tuning.strip().lower() in {"0", "false", "no", "off", "disabled"}
    )
    env["DATA_CRAWL_ADAPTIVE_TUNING"] = "0" if adaptive_disabled else "1"
    append_event(f"starting stage={stage_id} attempt={attempt} command={command!r}")
    with stage_log.open("a", encoding="utf-8", newline="\n") as output:
        output.write(f"\n{utc_now()} START attempt={attempt} command={command!r}\n")
        output.flush()
        try:
            process = subprocess.Popen(
                command,
                cwd=WORKSPACE,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, ValueError) as exc:
            reason = f"stage launch failed: {type(exc).__name__}: {exc}"
            output.write(f"{utc_now()} END attempt={attempt} launch_error={reason}\n")
            output.flush()
            return persist_launch_failure(126, reason)
        state["status"] = "running"
        state["current_stage"] = {
            "id": stage_id,
            "description": stage.get("description", ""),
            "status": "running",
            "attempt": attempt,
            "child_pid": process.pid,
            "child_identity": process_identity(process.pid),
            "parent_runner_pid": os.getpid(),
            "started_at": started_at,
            "log": stage_log.relative_to(WORKSPACE).as_posix(),
        }
        state["last_error"] = None
        try:
            save_state(state, state_path)
        except BaseException as exc:
            # Popen succeeded, so losing the child PID record here must never
            # leave an orphan crawler after the runner releases its lock. Use
            # this exact Popen handle rather than looking up a process by PID.
            try:
                process.terminate()
            except BaseException:
                pass
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                    process.wait()
                except BaseException:
                    pass
            except BaseException:
                try:
                    process.kill()
                    process.wait()
                except BaseException:
                    pass
            # Logging is deliberately best effort and happens only after the
            # child cleanup. A full or unavailable disk must not bypass it.
            try:
                output.write(
                    f"{utc_now()} CHILD_STATE_SAVE_FAILED "
                    f"{type(exc).__name__}: {exc}; child cleanup requested\n"
                )
                output.flush()
            except BaseException:
                pass
            raise exc.with_traceback(exc.__traceback__)
        exit_code = process.wait()
        output.write(f"{utc_now()} END attempt={attempt} exit_code={exit_code}\n")
        output.flush()

    ok, reason = checks_pass(stage)
    current = state["current_stage"]
    current["exit_code"] = exit_code
    current["finished_at"] = utc_now()
    current["success_checks_passed"] = ok
    current["success_check_message"] = reason
    current["status"] = "finished"
    save_state(state, state_path)
    if exit_code == 0 and ok:
        return 0, "ok"
    if exit_code != 0:
        return exit_code, f"stage command exited {exit_code}"
    return 1, reason


def run_queue(
    config_path: Path,
    state_path: Path,
    lock_path: Path,
    *,
    explicit_resume: bool = False,
) -> int:
    lock_handle = acquire_lock(lock_path)
    runner_pid = os.getpid()
    atomic_write_json(
        DEFAULT_PID,
        {
            "pid": runner_pid,
            "process_identity": process_identity(runner_pid),
            "started_at": utc_now(),
            "config": config_path.relative_to(WORKSPACE).as_posix(),
            "state": state_path.relative_to(WORKSPACE).as_posix(),
        },
    )
    append_event(f"queue runner started pid={runner_pid}")
    resume_prepared = False
    try:
        while True:
            config = load_json(config_path)
            if config.get("schema_version") != 1:
                raise RuntimeError("unsupported queue config schema")
            poll_seconds = max(1.0, float(config.get("poll_seconds", 30)))
            retry_initial = max(5.0, float(config.get("retry_initial_seconds", 60)))
            retry_max = max(retry_initial, float(config.get("retry_max_seconds", 3600)))
            state = load_state(config, state_path)

            if DEFAULT_STOP.exists():
                state["status"] = "stopped_by_signal"
                save_state(state, state_path)
                append_event(f"queue stopped because {DEFAULT_STOP} exists")
                return 2

            if explicit_resume and not resume_prepared:
                reset_failure_run(state)
                save_state(state, state_path)
                append_event(
                    "explicit resume started a fresh consecutive-failure budget"
                )
                resume_prepared = True

            stage = next_stage(config, state)
            if stage is None:
                state["status"] = "complete"
                state["current_stage"] = None
                state.setdefault("completed_at", utc_now())
                save_state(state, state_path)
                append_event("queue complete")
                maybe_notify_queue_complete(config, state, state_path)
                return 0

            current_record = state.get("current_stage")
            if (
                not isinstance(current_record, Mapping)
                or current_record.get("id") != stage["id"]
            ):
                state["status"] = "running"
                state["current_stage"] = preparing_stage_record(stage, state)
                save_state(state, state_path)

            try:
                recovered_result = wait_for_existing_child(
                    stage, state, state_path, poll_seconds
                )
            except ChildIdentityError as exc:
                state["status"] = "stopped_child_identity_mismatch"
                state["last_error"] = {
                    "stage": stage["id"],
                    "message": str(exc),
                    "type": "child_identity_mismatch",
                    "will_retry": False,
                    "recorded_at": utc_now(),
                }
                save_state(state, state_path)
                append_event(
                    f"queue halted before child reattach for stage={stage['id']}: {exc}"
                )
                return 4
            recovered = recovered_result is not None
            if recovered_result is None:
                exit_code, reason = run_stage(
                    stage, state, state_path, poll_seconds
                )
            else:
                exit_code, reason = recovered_result
            if exit_code == 0:
                completed = state.setdefault("completed_stages", [])
                if stage["id"] not in completed:
                    completed.append(stage["id"])
                clear_stage_failure_streak(state, str(stage["id"]))
                following = next_stage(config, state)
                state["current_stage"] = (
                    preparing_stage_record(following, state)
                    if following is not None
                    else None
                )
                state["last_error"] = None
                save_state(state, state_path)
                qualifier = "recovered " if recovered else ""
                append_event(f"completed {qualifier}stage={stage['id']}")
                continue

            # The stop helper writes the signal before terminating the exact
            # active child.  Treat the resulting 130/143-style exit as a
            # neutral, resumable stop: it must not inflate retry backoff or
            # trigger the failed-attempt popup.
            if DEFAULT_STOP.exists():
                state["status"] = "stopped_by_signal"
                state["last_error"] = None
                state["last_stop"] = {
                    "stage": stage["id"],
                    "exit_code": exit_code,
                    "message": reason,
                    "recorded_at": utc_now(),
                }
                save_state(state, state_path)
                append_event(
                    f"queue stopped during stage={stage['id']} because {DEFAULT_STOP} exists"
                )
                return 2

            stage_id = str(stage["id"])
            lifetime_failure_count = record_stage_failure(state, stage_id)
            streak = consecutive_stage_failures(state, stage_id)
            limit = failure_limit(config)
            current = state.get("current_stage")
            if isinstance(current, dict) and current.get("id") == stage["id"]:
                current["failure_recorded"] = True
                current["failure_recorded_at"] = utc_now()
                current["lifetime_failure_count"] = lifetime_failure_count
                current["consecutive_failure_count"] = streak

            error_record = {
                "stage": stage["id"],
                "exit_code": exit_code,
                "message": reason,
                "lifetime_failure_count": lifetime_failure_count,
                "consecutive_failure_count": streak,
                "max_consecutive_stage_failures": limit,
                "recorded_at": utc_now(),
            }

            if streak >= limit:
                state["status"] = "stopped_after_failures"
                error_record["will_retry"] = False
                state["last_error"] = error_record
                state["failure_stop"] = dict(error_record)
                save_state(state, state_path)
                append_event(
                    f"stage={stage_id} stopped queue after {streak} consecutive "
                    f"failures ({lifetime_failure_count} lifetime): {reason}"
                )
                maybe_notify_retry_threshold(
                    config,
                    state,
                    state_path,
                    stage,
                    streak,
                    reason,
                    stopped=True,
                )
                return 3

            delay = min(
                retry_max,
                retry_initial * (2 ** min(streak - 1, 6)),
            )
            state["status"] = "retry_wait"
            error_record["will_retry"] = True
            error_record["retry_after_seconds"] = delay
            state["last_error"] = error_record
            save_state(state, state_path)
            append_event(
                f"stage={stage_id} failed exit_code={exit_code}; consecutive={streak} "
                f"lifetime={lifetime_failure_count}; retry in {delay:.0f}s: {reason}"
            )
            maybe_notify_retry_threshold(
                config, state, state_path, stage, streak, reason, stopped=False
            )
            slept = 0.0
            while slept < delay:
                if DEFAULT_STOP.exists():
                    break
                interval = min(poll_seconds, delay - slept)
                time.sleep(interval)
                slept += interval
    finally:
        try:
            DEFAULT_PID.unlink(missing_ok=True)
        finally:
            lock_handle.seek(0)
            try:
                msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                lock_handle.close()


def print_status(state_path: Path) -> int:
    if not state_path.is_file():
        print(json.dumps({"status": "not_started", "state": str(state_path)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(load_json(state_path), ensure_ascii=False, indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "resume checkpoints with a fresh consecutive-failure budget; "
            "lifetime failure totals are preserved"
        ),
    )
    parser.add_argument("--status", action="store_true", help="print state without acquiring the runner lock")
    parser.add_argument(
        "--notification-child",
        nargs=3,
        metavar=("KIND", "TITLE", "MESSAGE"),
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    if args.notification_child is not None:
        return run_notification_child(*args.notification_child)
    config_path = args.config.resolve()
    state_path = args.state.resolve()
    lock_path = args.lock.resolve()
    if args.status:
        return print_status(state_path)
    if not config_path.is_file():
        parser.error(f"queue config not found: {config_path}")
    return run_queue(
        config_path,
        state_path,
        lock_path,
        explicit_resume=args.resume,
    )


if __name__ == "__main__":
    raise SystemExit(main())
