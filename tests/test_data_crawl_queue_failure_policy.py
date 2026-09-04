from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from scripts_pipeline import run_data_crawl_queue as queue


class DataCrawlQueueFailurePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        metadata_root = queue.WORKSPACE / "metadata"
        metadata_root.mkdir(parents=True, exist_ok=True)
        self._temporary = tempfile.TemporaryDirectory(
            prefix="queue_failure_policy_test_", dir=metadata_root
        )
        self.root = Path(self._temporary.name)
        self.config_path = self.root / "queue.json"
        self.state_path = self.root / "state.json"
        self.lock_path = self.root / "queue.lock"
        self.stop_path = self.root / "queue.stop"
        self.pid_path = self.root / "queue_pid.json"
        self.log_root = self.root / "logs"
        self.stage = {
            "id": "sample",
            "description": "sample stage",
            "command": [str(Path(__file__)), "unused.py"],
            "success_checks": [],
        }
        self._patches = [
            mock.patch.object(queue, "DEFAULT_STOP", self.stop_path),
            mock.patch.object(queue, "DEFAULT_PID", self.pid_path),
            mock.patch.object(queue, "LOG_ROOT", self.log_root),
            mock.patch.object(
                queue,
                "process_identity",
                side_effect=lambda pid: {"pid": pid, "identity_complete": True},
            ),
        ]
        for patcher in self._patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self._patches):
            patcher.stop()
        self._temporary.cleanup()

    def write_json(self, path: Path, value: object) -> None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def config(self, *, maximum: int = 2) -> dict[str, object]:
        return {
            "schema_version": 1,
            "queue_name": "failure-policy-test",
            "poll_seconds": 1,
            "retry_initial_seconds": 5,
            "retry_max_seconds": 5,
            "failure_policy": {
                "max_consecutive_stage_failures": maximum,
                "stop_when_reached": True,
            },
            "notifications": {"enabled": False},
            "stages": [self.stage],
        }

    def test_resolve_command_uses_discovered_node(self) -> None:
        node = self.root / "node.exe"
        with mock.patch.object(queue.shutil, "which", return_value=str(node)):
            resolved = queue.resolve_command(["{node}", "script.mjs"])
        self.assertEqual(resolved, [str(node), "script.mjs"])

    def test_completed_stage_with_now_failing_contract_is_reopened(self) -> None:
        config = self.config()
        config["stages"] = [
            {
                "id": "sample",
                "success_checks": [{"type": "file_exists", "path": "stale"}],
            }
        ]
        state = {"completed_stages": ["sample", "downstream"]}
        with mock.patch.object(
            queue, "checks_pass", return_value=(False, "missing success artifact")
        ):
            self.assertEqual(queue.next_stage(config, state)["id"], "sample")
        self.assertEqual(state["completed_stages"], [])

    def test_limit_stops_with_exit_three_and_explicit_resume_is_fresh(self) -> None:
        config = self.config(maximum=2)
        self.write_json(self.config_path, config)

        with (
            mock.patch.object(
                queue,
                "run_stage",
                side_effect=[(17, "first"), (17, "second")],
            ) as run_stage,
            mock.patch.object(queue.time, "sleep"),
        ):
            result = queue.run_queue(
                self.config_path, self.state_path, self.lock_path
            )

        self.assertEqual(result, 3)
        self.assertEqual(run_stage.call_count, 2)
        stopped = queue.load_json(self.state_path)
        self.assertEqual(stopped["status"], "stopped_after_failures")
        self.assertEqual(stopped["stage_failures"]["sample"], 2)
        self.assertEqual(stopped["consecutive_stage_failures"]["sample"], 2)
        self.assertFalse(stopped["last_error"]["will_retry"])

        stopped["notification_markers"] = {
            "retry_threshold": {"sample": {"launch_status": "launched"}},
            "queue_complete": None,
        }
        self.write_json(self.state_path, stopped)
        with mock.patch.object(queue, "run_stage", return_value=(0, "ok")):
            resumed_result = queue.run_queue(
                self.config_path,
                self.state_path,
                self.lock_path,
                explicit_resume=True,
            )

        resumed = queue.load_json(self.state_path)
        self.assertEqual(resumed_result, 0)
        self.assertEqual(resumed["status"], "complete")
        self.assertEqual(resumed["stage_failures"]["sample"], 2)
        self.assertEqual(resumed["consecutive_stage_failures"]["sample"], 0)
        self.assertEqual(
            resumed["notification_markers"]["retry_threshold"], {}
        )
        self.assertIn("last_failure_stop", resumed)

    def test_reattached_child_failure_is_counted_once(self) -> None:
        config = self.config(maximum=1)
        self.write_json(self.config_path, config)
        state = queue.initial_state(config)
        state["status"] = "running"
        state["current_stage"] = {
            "id": "sample",
            "status": "running",
            "attempt": 1,
            "child_pid": 4242,
            "child_identity": {
                "pid": 4242,
                "creation_time_100ns": 1,
                "executable_path": "python.exe",
            },
        }
        self.write_json(self.state_path, state)

        with (
            mock.patch.object(queue, "verified_child_exit_code", return_value=9),
            mock.patch.object(
                queue,
                "run_stage",
                side_effect=AssertionError("reattached result was discarded"),
            ),
        ):
            result = queue.run_queue(
                self.config_path, self.state_path, self.lock_path
            )

        persisted = queue.load_json(self.state_path)
        self.assertEqual(result, 3)
        self.assertEqual(persisted["stage_failures"]["sample"], 1)
        self.assertTrue(persisted["current_stage"]["failure_recorded"])
        self.assertIsNone(
            queue.wait_for_existing_child(
                self.stage, persisted, self.state_path, poll_seconds=1
            )
        )
        self.assertEqual(persisted["stage_failures"]["sample"], 1)

    def test_stop_signal_after_reattached_child_exit_is_neutral(self) -> None:
        config = self.config(maximum=1)
        self.write_json(self.config_path, config)
        state = queue.initial_state(config)
        state["status"] = "running"
        state["current_stage"] = {
            "id": "sample",
            "status": "running",
            "attempt": 1,
            "child_pid": 4242,
            "child_identity": {
                "pid": 4242,
                "creation_time_100ns": 1,
                "executable_path": "python.exe",
            },
        }
        self.write_json(self.state_path, state)

        def stopped_exit(pid: int, expected_identity: object) -> int:
            self.stop_path.write_text("stop\n", encoding="ascii")
            return 143

        with (
            mock.patch.object(
                queue, "verified_child_exit_code", side_effect=stopped_exit
            ),
            mock.patch.object(
                queue,
                "run_stage",
                side_effect=AssertionError("a new child must not start"),
            ),
        ):
            result = queue.run_queue(
                self.config_path, self.state_path, self.lock_path
            )

        persisted = queue.load_json(self.state_path)
        self.assertEqual(result, 2)
        self.assertEqual(persisted["status"], "stopped_by_signal")
        self.assertEqual(persisted["stage_failures"], {})
        self.assertEqual(persisted["consecutive_stage_failures"], {})

    def test_reattach_identity_mismatch_halts_without_starting_or_counting(self) -> None:
        config = self.config(maximum=1)
        self.write_json(self.config_path, config)
        state = queue.initial_state(config)
        state["status"] = "running"
        state["current_stage"] = {
            "id": "sample",
            "status": "running",
            "attempt": 1,
            "child_pid": 4242,
            "child_identity": {
                "pid": 4242,
                "creation_time_100ns": 1,
                "executable_path": "python.exe",
            },
        }
        self.write_json(self.state_path, state)

        with (
            mock.patch.object(
                queue,
                "verified_child_exit_code",
                side_effect=queue.ChildIdentityError("creation time mismatch"),
            ),
            mock.patch.object(
                queue,
                "run_stage",
                side_effect=AssertionError("identity mismatch started a child"),
            ),
        ):
            result = queue.run_queue(
                self.config_path, self.state_path, self.lock_path
            )

        persisted = queue.load_json(self.state_path)
        self.assertEqual(result, 4)
        self.assertEqual(persisted["status"], "stopped_child_identity_mismatch")
        self.assertEqual(persisted["stage_failures"], {})
        self.assertFalse(persisted["last_error"]["will_retry"])

    def test_explicit_resume_after_operator_stop_does_not_replay_exit_as_failure(self) -> None:
        config = self.config(maximum=1)
        self.write_json(self.config_path, config)
        state = queue.initial_state(config)
        state["status"] = "stopped_by_signal"
        state["current_stage"] = {
            "id": "sample",
            "status": "finished",
            "attempt": 1,
            "child_pid": 4242,
            "exit_code": 143,
        }
        state["last_stop"] = {
            "stage": "sample",
            "exit_code": 143,
            "message": "operator stop",
        }
        self.write_json(self.state_path, state)

        with mock.patch.object(queue, "run_stage", return_value=(0, "ok")) as run:
            result = queue.run_queue(
                self.config_path,
                self.state_path,
                self.lock_path,
                explicit_resume=True,
            )

        persisted = queue.load_json(self.state_path)
        self.assertEqual(result, 0)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(persisted["stage_failures"], {})
        self.assertEqual(persisted["status"], "complete")

    def test_success_clears_streak_without_erasing_lifetime_total(self) -> None:
        config = self.config(maximum=3)
        self.write_json(self.config_path, config)
        state = queue.initial_state(config)
        state["stage_failures"] = {"sample": 7}
        state["consecutive_stage_failures"] = {"sample": 2}
        self.write_json(self.state_path, state)

        with mock.patch.object(queue, "run_stage", return_value=(0, "ok")):
            result = queue.run_queue(
                self.config_path, self.state_path, self.lock_path
            )

        persisted = queue.load_json(self.state_path)
        self.assertEqual(result, 0)
        self.assertEqual(persisted["stage_failures"]["sample"], 7)
        self.assertEqual(persisted["consecutive_stage_failures"]["sample"], 0)

    def test_preflight_launch_failure_is_durable_and_counts(self) -> None:
        config = self.config(maximum=1)
        config["stages"][0]["command"] = [
            str(self.root / "missing-python.exe"),
            "unused.py",
        ]
        self.write_json(self.config_path, config)

        result = queue.run_queue(
            self.config_path, self.state_path, self.lock_path
        )

        persisted = queue.load_json(self.state_path)
        self.assertEqual(result, 3)
        self.assertEqual(persisted["stage_failures"]["sample"], 1)
        self.assertTrue(
            persisted["current_stage"]["launch_error"].startswith(
                "executable not found:"
            )
        )
        self.assertTrue(persisted["current_stage"]["failure_recorded"])

    def test_child_is_terminated_if_first_running_state_save_fails(self) -> None:
        stage = dict(self.stage)
        stage["command"] = [
            sys.executable,
            "scripts_pipeline/run_data_crawl_queue.py",
        ]
        state = queue.initial_state(self.config())
        process = mock.Mock(pid=8765)
        process.wait.return_value = 143
        output = mock.Mock()
        output.write.side_effect = [
            None,  # append_event before the stage log is opened
            None,  # stage START line
            OSError("simulated log disk failure"),
        ]
        stage_log_context = mock.MagicMock()
        stage_log_context.__enter__.return_value = output

        with (
            mock.patch.object(Path, "open", return_value=stage_log_context),
            mock.patch.object(queue.subprocess, "Popen", return_value=process),
            mock.patch.object(
                queue, "save_state", side_effect=OSError("simulated disk failure")
            ),
        ):
            with self.assertRaisesRegex(OSError, "simulated disk failure"):
                queue.run_stage(stage, state, self.state_path, poll_seconds=1)

        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=30)

    def test_success_atomically_publishes_the_following_stage_as_preparing(self) -> None:
        first = {**self.stage, "id": "first", "label": "first"}
        second = {**self.stage, "id": "second", "label": "second"}
        config = self.config(maximum=2)
        config["stages"] = [first, second]
        self.write_json(self.config_path, config)
        snapshots: list[dict[str, object]] = []
        original_save = queue.save_state

        def capture(state: dict[str, object], path: Path) -> None:
            snapshots.append(copy.deepcopy(state))
            original_save(state, path)

        with (
            mock.patch.object(queue, "save_state", side_effect=capture),
            mock.patch.object(
                queue,
                "run_stage",
                side_effect=[(0, "ok"), (0, "ok")],
            ),
        ):
            result = queue.run_queue(
                self.config_path, self.state_path, self.lock_path
            )

        self.assertEqual(result, 0)
        after_first = [
            item
            for item in snapshots
            if item.get("completed_stages") == ["first"]
        ]
        self.assertTrue(after_first)
        self.assertTrue(
            all(
                isinstance(item.get("current_stage"), dict)
                and item["current_stage"].get("id") == "second"
                and item["current_stage"].get("status") == "preparing"
                for item in after_first
            )
        )


if __name__ == "__main__":
    unittest.main()
