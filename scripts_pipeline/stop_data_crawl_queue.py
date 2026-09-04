"""Safely stop this workspace's durable data-crawl queue.

Only the runner and active child PIDs recorded in ``metadata`` are inspected.
The runner exits after seeing the stop sentinel; this helper may terminate the
recorded active child so a long request batch does not delay shutdown.  New
metadata records include a process identity (PID, creation time and executable)
which is verified on the *same process handle* used for termination. Older
records without that identity may receive the stop sentinel, but are never
terminated from a bare PID.
No process-name enumeration is ever performed.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


WORKSPACE = Path(__file__).resolve().parents[1]
METADATA = WORKSPACE / "metadata"
STOP_PATH = METADATA / "data_crawl_queue.stop"
STATE_PATH = METADATA / "data_crawl_queue_state.json"
PID_PATH = METADATA / "data_crawl_queue_pid.json"
REPORT_PATH = METADATA / "data_crawl_queue_stop_report.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


if sys.platform == "win32":
    from ctypes import wintypes

    class _FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _STILL_ACTIVE = 259
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.GetExitCodeProcess.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
    ]
    _kernel32.GetProcessTimes.restype = wintypes.BOOL
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateProcess.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL


def _positive_pid(value: Any) -> int | None:
    return value if type(value) is int and 0 < value <= 0xFFFFFFFF else None


def _normalize_executable(value: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(value)))


def _windows_identity_from_handle(handle: int, pid: int) -> dict[str, Any] | None:
    creation = _FILETIME()
    exit_time = _FILETIME()
    kernel = _FILETIME()
    user = _FILETIME()
    if not _kernel32.GetProcessTimes(
        handle,
        ctypes.byref(creation),
        ctypes.byref(exit_time),
        ctypes.byref(kernel),
        ctypes.byref(user),
    ):
        return None
    # 32768 comfortably exceeds ordinary Windows paths and avoids relying on
    # MAX_PATH, which Python installations may legitimately exceed.
    capacity = wintypes.DWORD(32768)
    buffer = ctypes.create_unicode_buffer(capacity.value)
    if not _kernel32.QueryFullProcessImageNameW(
        handle, 0, buffer, ctypes.byref(capacity)
    ):
        return None
    creation_time = (
        int(creation.dwHighDateTime) << 32
    ) | int(creation.dwLowDateTime)
    return {
        "pid": int(pid),
        "creation_time_100ns": creation_time,
        "executable_path": buffer.value,
    }


def process_alive(pid: int) -> bool:
    """Return whether the exact numeric PID currently exists."""

    if _positive_pid(pid) is None:
        return False
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == _STILL_ACTIVE
    finally:
        _kernel32.CloseHandle(handle)


def process_identity(pid: int) -> dict[str, Any] | None:
    """Return stable ``pid``/creation-time/executable identity metadata."""

    if _positive_pid(pid) is None:
        return None
    if sys.platform == "win32":
        handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            return _windows_identity_from_handle(handle, pid)
        finally:
            _kernel32.CloseHandle(handle)

    # Linux fallback for development/tests.  /proc start ticks are stable for
    # PID-reuse detection though the key retains its Windows-oriented name.
    try:
        stat_parts = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
        executable = os.readlink(f"/proc/{pid}/exe")
        start_ticks = int(stat_parts[21])
    except (OSError, ValueError, IndexError):
        return None
    return {
        "pid": int(pid),
        "creation_time_100ns": start_ticks,
        "executable_path": executable,
    }


def verified_process_exit_code(
    pid: int, expected_identity: Mapping[str, Any] | None
) -> tuple[bool, int | None, str]:
    """Read liveness/exit code only for the recorded process identity.

    On Windows, identity and exit code are read from the same process handle,
    so PID reuse cannot turn an unrelated process into a recovered crawler
    child. ``None`` means the verified process is still active.
    """

    canonical, identity_error = _canonical_expected_identity(expected_identity)
    if canonical is None:
        return False, None, f"identity_refused: {identity_error}"
    if canonical["pid"] != pid:
        return False, None, "identity_refused: pid mismatch"

    if sys.platform == "win32":
        handle = _kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:  # ERROR_INVALID_PARAMETER: PID no longer exists.
                return True, -1, "verified_process_no_longer_exists"
            return False, None, f"OpenProcess failed with WinError {error}"
        try:
            actual = _windows_identity_from_handle(handle, pid)
            matched, detail = identities_match(canonical, actual)
            if not matched:
                return False, None, f"identity_refused: {detail}"
            exit_code = wintypes.DWORD()
            if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False, None, (
                    "GetExitCodeProcess failed with WinError "
                    f"{ctypes.get_last_error()}"
                )
            if exit_code.value == _STILL_ACTIVE:
                return True, None, "identity_verified:still_active"
            return True, int(exit_code.value), "identity_verified:exited"
        finally:
            _kernel32.CloseHandle(handle)

    # Development fallback: verify on both sides of the liveness check. This
    # is conservative and never reports a mismatched PID as the recorded one.
    before = process_identity(pid)
    matched, detail = identities_match(canonical, before)
    if not matched:
        if before is None and not process_alive(pid):
            return True, -1, "verified_process_no_longer_exists"
        return False, None, f"identity_refused: {detail}"
    if process_alive(pid):
        after = process_identity(pid)
        matched, detail = identities_match(canonical, after)
        if not matched:
            return False, None, f"identity_refused: {detail}"
        return True, None, "identity_verified:still_active"
    return True, -1, "identity_verified:exited_without_code"


def _canonical_expected_identity(
    expected: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(expected, Mapping):
        return None, "missing process identity"
    pid = _positive_pid(expected.get("pid"))
    creation = expected.get("creation_time_100ns")
    executable = expected.get("executable_path")
    if pid is None:
        return None, "identity has no valid pid"
    if type(creation) is not int or creation < 0:
        return None, "identity has no valid creation_time_100ns"
    if not isinstance(executable, str) or not executable.strip():
        return None, "identity has no valid executable_path"
    return {
        "pid": pid,
        "creation_time_100ns": creation,
        "executable_path": executable,
    }, None


def identities_match(
    expected: Mapping[str, Any] | None, actual: Mapping[str, Any] | None
) -> tuple[bool, str]:
    canonical, error = _canonical_expected_identity(expected)
    if canonical is None:
        return False, error or "invalid expected identity"
    if not isinstance(actual, Mapping):
        return False, "cannot inspect actual process identity"
    if actual.get("pid") != canonical["pid"]:
        return False, "pid mismatch"
    if actual.get("creation_time_100ns") != canonical["creation_time_100ns"]:
        return False, "creation time mismatch (possible PID reuse)"
    actual_executable = actual.get("executable_path")
    if not isinstance(actual_executable, str) or (
        _normalize_executable(actual_executable)
        != _normalize_executable(canonical["executable_path"])
    ):
        return False, "executable path mismatch"
    return True, "identity_verified"


def inspect_recorded_process(
    pid: int | None, expected_identity: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Inspect a recorded PID and report whether its identity is trustworthy."""

    if pid is None or not process_alive(pid):
        return {
            "alive": False,
            "identityVerified": False,
            "identityStatus": "not_running",
            "actualIdentity": None,
        }
    actual = process_identity(pid)
    if expected_identity is None:
        return {
            "alive": True,
            "identityVerified": False,
            "identityStatus": "legacy_unverified",
            "actualIdentity": actual,
        }
    matched, detail = identities_match(expected_identity, actual)
    return {
        "alive": bool(matched),
        "identityVerified": bool(matched),
        "identityStatus": detail,
        "actualIdentity": actual,
        "pidOccupiedByDifferentProcess": not matched,
    }


def terminate_process(
    pid: int, *, expected_identity: Mapping[str, Any] | None = None
) -> tuple[bool, str]:
    """Terminate one recorded PID, verifying identity on the same handle.

    Legacy metadata without an identity is refused. The runner can still exit
    cooperatively after seeing the stop sentinel, but a bare PID is never
    sufficient authority to terminate a process because it may have been
    reused.
    """

    if not process_alive(pid):
        return True, "already_not_running"
    canonical, identity_error = _canonical_expected_identity(expected_identity)
    if canonical is None:
        return False, f"identity_refused: {identity_error}"
    if canonical is not None and canonical["pid"] != pid:
        return False, "identity_refused: pid mismatch"

    if sys.platform != "win32":
        matched, detail = identities_match(canonical, process_identity(pid))
        if not matched:
            return False, f"identity_refused: {detail}"
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            return False, f"{type(exc).__name__}: {exc}"
        return True, "identity_verified:SIGTERM_sent"

    access = _PROCESS_TERMINATE | _PROCESS_QUERY_LIMITED_INFORMATION
    handle = _kernel32.OpenProcess(access, False, pid)
    if not handle:
        return False, f"OpenProcess failed with WinError {ctypes.get_last_error()}"
    try:
        # Verification and termination share this kernel handle, closing the
        # PID-reuse race between the two operations.
        actual = _windows_identity_from_handle(handle, pid)
        matched, detail = identities_match(canonical, actual)
        if not matched:
            return False, f"identity_refused: {detail}"
        if not _kernel32.TerminateProcess(handle, 143):
            return False, (
                f"TerminateProcess failed with WinError {ctypes.get_last_error()}"
            )
        return True, "identity_verified:TerminateProcess_sent"
    finally:
        _kernel32.CloseHandle(handle)


def recorded_processes() -> dict[str, Any]:
    state = load_object(STATE_PATH)
    current = state.get("current_stage")
    current = current if isinstance(current, dict) else {}
    pid_record = load_object(PID_PATH)
    return {
        "runnerPid": _positive_pid(pid_record.get("pid")),
        "runnerIdentity": (
            pid_record.get("process_identity")
            if isinstance(pid_record.get("process_identity"), dict)
            else None
        ),
        "childPid": _positive_pid(current.get("child_pid")),
        "childIdentity": (
            current.get("child_identity")
            if isinstance(current.get("child_identity"), dict)
            else None
        ),
        "state": state,
    }


def recorded_pids() -> tuple[int | None, int | None]:
    """Compatibility helper for older maintenance/tests."""

    records = recorded_processes()
    return records["runnerPid"], records["childPid"]


def _record_status(pid: int | None, identity: Mapping[str, Any] | None) -> dict[str, Any]:
    return inspect_recorded_process(pid, identity)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    records = recorded_processes()
    runner_pid = records["runnerPid"]
    child_pid = records["childPid"]
    runner_identity = records["runnerIdentity"]
    child_identity = records["childIdentity"]
    report: dict[str, Any] = {
        "schemaVersion": 2,
        "requestedAt": utc_now(),
        "workspace": str(WORKSPACE),
        "runnerPid": runner_pid,
        "childPid": child_pid,
        "runnerIdentityRecorded": runner_identity is not None,
        "childIdentityRecorded": child_identity is not None,
        "dryRun": bool(args.dry_run),
        "events": [],
    }
    if args.dry_run:
        report.update(
            {
                "runner": _record_status(runner_pid, runner_identity),
                "child": _record_status(child_pid, child_identity),
                "wouldWriteStop": str(STOP_PATH),
            }
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    atomic_write(STOP_PATH, "stop\n")
    report["events"].append({"at": utc_now(), "event": "stop_signal_written"})

    if child_pid is not None:
        ok, detail = terminate_process(child_pid, expected_identity=child_identity)
        report["events"].append(
            {
                "at": utc_now(),
                "event": "active_stage_termination_requested",
                "pid": child_pid,
                "identityMode": (
                    "verified" if child_identity is not None else "legacy_unverified"
                ),
                "ok": ok,
                "detail": detail,
            }
        )

    deadline = time.monotonic() + max(1.0, args.timeout)
    while time.monotonic() < deadline:
        state = load_object(STATE_PATH)
        runner_status = _record_status(runner_pid, runner_identity)
        child_status = _record_status(child_pid, child_identity)
        # Identity mismatch means the recorded process ended and its PID was
        # reused.  Never terminate or wait for the unrelated replacement.
        runner_alive = bool(runner_status["alive"])
        child_alive = bool(child_status["alive"])
        if not runner_alive and not child_alive:
            report.update(
                {
                    "completedAt": utc_now(),
                    "queueStatus": state.get("status"),
                    "runnerAlive": False,
                    "childAlive": False,
                    "runnerIdentityStatus": runner_status["identityStatus"],
                    "childIdentityStatus": child_status["identityStatus"],
                    "success": state.get("status") == "stopped_by_signal",
                }
            )
            atomic_write_json(REPORT_PATH, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["success"] else 1
        time.sleep(0.25)

    state = load_object(STATE_PATH)
    runner_status = _record_status(runner_pid, runner_identity)
    child_status = _record_status(child_pid, child_identity)
    report.update(
        {
            "completedAt": utc_now(),
            "queueStatus": state.get("status"),
            "runnerAlive": bool(runner_status["alive"]),
            "childAlive": bool(child_status["alive"]),
            "runnerIdentityStatus": runner_status["identityStatus"],
            "childIdentityStatus": child_status["identityStatus"],
            "success": False,
            "error": "timed out waiting for queue shutdown",
        }
    )
    atomic_write_json(REPORT_PATH, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
