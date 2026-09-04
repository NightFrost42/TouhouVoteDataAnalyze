from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts_pipeline import run_data_crawl_queue as queue


class DataCrawlQueueNotificationTests(unittest.TestCase):
    def setUp(self) -> None:
        metadata_root = queue.WORKSPACE / "metadata"
        metadata_root.mkdir(parents=True, exist_ok=True)
        self._temporary = tempfile.TemporaryDirectory(
            prefix="queue_notification_test_", dir=metadata_root
        )
        self.root = Path(self._temporary.name)
        self.config_path = self.root / "queue.json"
        self.state_path = self.root / "state.json"
        self.lock_path = self.root / "queue.lock"
        self.stop_path = self.root / "queue.stop"
        self.pid_path = self.root / "queue_pid.json"
        self.log_root = self.root / "logs"

        self._patches = [
            mock.patch.object(queue, "DEFAULT_STOP", self.stop_path),
            mock.patch.object(queue, "DEFAULT_PID", self.pid_path),
            mock.patch.object(queue, "LOG_ROOT", self.log_root),
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

    @staticmethod
    def notification_config(*, stages: list[dict[str, object]] | None = None) -> dict[str, object]:
        return {
            "schema_version": 1,
            "queue_name": "notification-test",
            "poll_seconds": 1,
            "retry_initial_seconds": 5,
            "retry_max_seconds": 5,
            "notifications": {
                "enabled": True,
                "failed_attempt_threshold": 5,
                "notify_on_complete": True,
            },
            "stages": stages or [],
        }

    def test_retry_threshold_claim_is_persisted_before_launch_and_is_at_most_once(self) -> None:
        config = self.notification_config()
        state = queue.initial_state(config)
        stage = {"id": "sample", "description": "示例阶段"}
        launches: list[tuple[str, str, str]] = []

        def fake_launch(kind: str, title: str, message: str) -> bool:
            persisted = queue.load_json(self.state_path)
            marker = persisted["notification_markers"]["retry_threshold"]["sample"]
            self.assertEqual(marker["launch_status"], "claimed")
            launches.append((kind, title, message))
            return True

        with mock.patch.object(queue, "launch_notification", side_effect=fake_launch):
            queue.maybe_notify_retry_threshold(
                config, state, self.state_path, stage, 4, "not yet"
            )
            self.assertEqual(launches, [])

            queue.maybe_notify_retry_threshold(
                config, state, self.state_path, stage, 5, "threshold reached"
            )
            self.assertEqual(len(launches), 1)

            # Reloading the state models a runner restart.  Later failures must
            # not produce a second popup for the same stage.
            reloaded = queue.load_state(config, self.state_path)
            queue.maybe_notify_retry_threshold(
                config, reloaded, self.state_path, stage, 6, "still failing"
            )

        self.assertEqual(len(launches), 1)
        marker = queue.load_json(self.state_path)["notification_markers"][
            "retry_threshold"
        ]["sample"]
        self.assertEqual(marker["failed_attempts"], 5)
        self.assertEqual(marker["launch_status"], "launched")

    def test_attempts_are_not_inferred_as_real_failures(self) -> None:
        state = {"stage_attempts": {"sample": 5}}
        self.assertEqual(queue.record_stage_failure(state, "sample"), 1)
        self.assertEqual(queue.record_stage_failure(state, "sample"), 2)
        self.assertEqual(state["consecutive_stage_failures"]["sample"], 2)

    def test_complete_notification_is_once_and_completed_at_is_not_rewritten(self) -> None:
        config = self.notification_config()
        self.write_json(self.config_path, config)
        original_completed_at = "2000-01-02T03:04:05+00:00"
        state = queue.initial_state(config)
        state["status"] = "complete"
        state["completed_at"] = original_completed_at
        self.write_json(self.state_path, state)

        with mock.patch.object(queue, "launch_notification", return_value=True) as launch:
            self.assertEqual(
                queue.run_queue(self.config_path, self.state_path, self.lock_path), 0
            )
            self.assertEqual(
                queue.run_queue(self.config_path, self.state_path, self.lock_path), 0
            )

        persisted = queue.load_json(self.state_path)
        self.assertEqual(persisted["completed_at"], original_completed_at)
        self.assertEqual(persisted["status"], "complete")
        self.assertEqual(launch.call_count, 1)

    def test_stop_signal_wins_over_empty_queue_and_never_notifies_completion(self) -> None:
        config = self.notification_config()
        self.write_json(self.config_path, config)
        self.stop_path.write_text("stop\n", encoding="ascii")

        with mock.patch.object(queue, "launch_notification", return_value=True) as launch:
            result = queue.run_queue(
                self.config_path, self.state_path, self.lock_path
            )

        persisted = queue.load_json(self.state_path)
        self.assertEqual(result, 2)
        self.assertEqual(persisted["status"], "stopped_by_signal")
        self.assertNotIn("completed_at", persisted)
        launch.assert_not_called()

    def test_stop_during_stage_is_neutral_and_does_not_count_as_failure(self) -> None:
        stage = {
            "id": "sample",
            "description": "示例阶段",
            "command": [str(Path(__file__)), "unused.py"],
            "success_checks": [],
        }
        config = self.notification_config(stages=[stage])
        self.write_json(self.config_path, config)

        def interrupted_stage(*args: object, **kwargs: object) -> tuple[int, str]:
            self.stop_path.write_text("stop\n", encoding="ascii")
            return 143, "stage command exited 143"

        with (
            mock.patch.object(queue, "run_stage", side_effect=interrupted_stage),
            mock.patch.object(queue, "launch_notification") as launch,
        ):
            result = queue.run_queue(
                self.config_path, self.state_path, self.lock_path
            )

        persisted = queue.load_json(self.state_path)
        self.assertEqual(result, 2)
        self.assertEqual(persisted["status"], "stopped_by_signal")
        self.assertIsNone(persisted["last_error"])
        self.assertEqual(persisted["stage_failures"], {})
        self.assertEqual(persisted["consecutive_stage_failures"], {})
        self.assertEqual(persisted["last_stop"]["exit_code"], 143)
        launch.assert_not_called()

    def test_notification_child_mode_returns_before_acquiring_runner_lock(self) -> None:
        with (
            mock.patch.object(queue, "run_notification_child", return_value=17) as child,
            mock.patch.object(
                queue,
                "acquire_lock",
                side_effect=AssertionError("notification child tried to acquire queue lock"),
            ),
        ):
            result = queue.main(
                ["--notification-child", "queue_complete", "标题", "内容"]
            )

        self.assertEqual(result, 17)
        child.assert_called_once_with("queue_complete", "标题", "内容")

    def test_notification_launch_is_fire_and_forget(self) -> None:
        process = mock.Mock(pid=43210)
        with mock.patch.object(queue.subprocess, "Popen", return_value=process) as popen:
            self.assertTrue(queue.launch_notification("queue_complete", "标题", "内容"))

        process.wait.assert_not_called()
        kwargs = popen.call_args.kwargs
        self.assertIs(kwargs["stdin"], queue.subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], queue.subprocess.DEVNULL)
        self.assertIs(kwargs["stderr"], queue.subprocess.DEVNULL)
        self.assertTrue(kwargs["creationflags"] & queue.subprocess.CREATE_NO_WINDOW)
        self.assertTrue(
            kwargs["creationflags"] & queue.subprocess.CREATE_NEW_PROCESS_GROUP
        )

    def test_notification_launch_failure_is_logged_and_does_not_raise(self) -> None:
        with mock.patch.object(
            queue.subprocess, "Popen", side_effect=OSError("simulated launch failure")
        ):
            self.assertFalse(
                queue.launch_notification("retry_threshold", "标题", "内容")
            )

        log_text = (self.log_root / "queue.log").read_text(encoding="utf-8")
        self.assertIn("notification launch failed kind=retry_threshold", log_text)
        self.assertIn("simulated launch failure", log_text)


if __name__ == "__main__":
    unittest.main()
