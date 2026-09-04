from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts_pipeline import crawl_cn_legacy as legacy


class LegacyConfigurableGuardrailTests(unittest.TestCase):
    @staticmethod
    def crawler_kwargs() -> dict[str, object]:
        return {
            "rounds": [5],
            "workers": 7,
            "refresh": False,
            "no_item_apis": False,
            "max_items": None,
            "retries": 1,
            "timeout": 10,
            "delay": 0.0,
            "batch_size": 40,
            "batch_pause": 4.0,
            "transient_failure_threshold": 3,
            "import_existing_temp": False,
            "supplemental_only": False,
            "advanced_only": True,
            "advanced_stage": "all",
            "rebuild_only": True,
            "worker_ceiling": 12,
            "request_limit_ceiling": 50,
            "batch_pause_ceiling": 5.0,
        }

    def make_crawler(
        self,
        root: Path,
        **overrides: object,
    ) -> legacy.Crawler:
        values = self.crawler_kwargs()
        values.update(overrides)
        metadata = root / "metadata"
        with (
            mock.patch.object(legacy, "DATA_ROOT", root / "data"),
            mock.patch.object(legacy, "METADATA_ROOT", metadata),
            mock.patch.object(legacy, "MANIFEST_PATH", metadata / "manifest.jsonl"),
            mock.patch.object(legacy, "JOURNAL_PATH", metadata / "journal.jsonl"),
            mock.patch.object(legacy, "RUN_STATE_JSON", metadata / "state.json"),
            mock.patch.object(legacy, "ADAPTIVE_PROFILE_JSON", metadata / "profiles.json"),
            mock.patch.dict(legacy.os.environ, {}, clear=False),
        ):
            legacy.os.environ.pop("DATA_CRAWL_QUEUE_STAGE_ID", None)
            return legacy.Crawler(**values)

    @staticmethod
    def fetch_result(*, ok: bool, status: int | None = None) -> legacy.FetchResult:
        return legacy.FetchResult(
            job=legacy.FetchJob(
                round_no=5,
                url="https://touhou.vote/v5/test",
                target=Path("test.json"),
            ),
            ok=ok,
            status=status,
            transient=not ok,
        )

    def test_configurable_ceilings_drive_runtime_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            crawler = self.make_crawler(Path(directory))
        self.assertEqual(crawler.worker_ceiling, 12)
        self.assertEqual(crawler.adaptive_worker_ceiling, 12)
        self.assertEqual(crawler.request_limit_ceiling, 50)
        self.assertEqual(crawler.batch_pause_ceiling, 5.0)
        self.assertEqual(crawler.batch_size, 40)
        self.assertEqual(crawler.batch_pause, 4.0)

    def test_starting_values_cannot_exceed_configured_ceilings(self) -> None:
        cases = (
            {"workers": 13},
            {"batch_size": 51},
            {"batch_pause": 5.1},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    self.make_crawler(Path(directory), **overrides)

    def test_transient_recovery_may_temporarily_exceed_normal_pause_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            crawler = self.make_crawler(
                Path(directory),
                workers=2,
                batch_size=8,
                batch_pause=1.0,
                batch_pause_ceiling=1.0,
            )
        result = legacy.FetchResult(
            job=legacy.FetchJob(
                round_no=5,
                url="https://touhou.vote/v5/test",
                target=Path("test.json"),
            ),
            ok=False,
            status=504,
            transient=True,
        )
        crawler._adaptive_observe(result)
        self.assertEqual(crawler.adaptive_workers, 1)
        self.assertGreater(crawler.adaptive_batch_pause, crawler.batch_pause_ceiling)
        self.assertLessEqual(
            crawler.adaptive_batch_pause,
            legacy.ABSOLUTE_MAX_BATCH_PAUSE_SECONDS,
        )

    def test_failure_wave_needs_a_new_submission_epoch_after_probe_gate(self) -> None:
        """Neither elapsed time nor a late peer can manufacture a new probe."""

        with tempfile.TemporaryDirectory() as directory:
            crawler = self.make_crawler(Path(directory), workers=5)
        crawler.adaptive_workers = 5
        crawler.adaptive_batch_pause = 4.0
        clock = mock.Mock(return_value=1_000.0)
        failure = self.fetch_result(ok=False, status=504)

        with mock.patch.object(legacy.time, "monotonic", clock):
            crawler._adaptive_observe(failure, request_epoch=0)
            self.assertEqual(crawler.adaptive_workers, 4)
            self.assertEqual(crawler.adaptive_batch_pause, 4.5)
            self.assertEqual(crawler.adaptive_controller_epoch, 1)
            self.assertEqual(crawler.adaptive_failure_wave_epoch, 0)

            # These are peers from the same failure wave.  They arrive after
            # the first decision but before the host has had time to recover.
            clock.return_value = 1_010.0
            crawler._adaptive_observe(failure, request_epoch=0)
            clock.return_value = (
                1_000.0 + legacy.ADAPTIVE_DECREASE_MIN_INTERVAL_SECONDS - 0.1
            )
            crawler._adaptive_observe(failure, request_epoch=0)
            self.assertEqual(crawler.adaptive_workers, 4)
            self.assertEqual(crawler.adaptive_batch_pause, 4.5)

            # The very same old request remains immutable even after the dwell
            # window.  Only a request actually submitted in epoch 1 can be new
            # evidence for one further deliberately small adjustment.
            clock.return_value = (
                1_000.0 + legacy.ADAPTIVE_DECREASE_MIN_INTERVAL_SECONDS + 0.1
            )
            crawler._adaptive_observe(failure, request_epoch=0)
            self.assertEqual(crawler.adaptive_workers, 4)
            self.assertEqual(crawler.adaptive_batch_pause, 4.5)

            crawler._adaptive_observe(failure, request_epoch=1)
        self.assertEqual(crawler.adaptive_workers, 3)
        self.assertEqual(crawler.adaptive_batch_pause, 5.0)
        self.assertEqual(crawler.adaptive_controller_epoch, 2)
        self.assertEqual(crawler.adaptive_failure_wave_epoch, 1)

    def test_old_epoch_success_cannot_undo_failure_downshift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            crawler = self.make_crawler(Path(directory), workers=5)
        crawler.adaptive_workers = 5
        crawler.adaptive_batch_pause = 4.0

        clock = mock.Mock(return_value=1_000.0)
        with mock.patch.object(legacy.time, "monotonic", clock):
            crawler._adaptive_observe(
                self.fetch_result(ok=False, status=504),
                request_epoch=0,
            )
            success_window = max(
                legacy.ADAPTIVE_SUCCESS_WINDOW_RESULTS,
                crawler.batch_size,
            )
            crawler.adaptive_success_streak = success_window - 1
            crawler.adaptive_next_increase_at = 0.0
            clock.return_value = 2_000.0
            crawler._adaptive_observe(
                self.fetch_result(ok=True, status=200),
                request_epoch=0,
            )

        self.assertEqual(crawler.adaptive_workers, 4)
        self.assertEqual(crawler.adaptive_batch_pause, 4.5)
        self.assertEqual(crawler.adaptive_success_streak, success_window - 1)
        self.assertEqual(crawler.adaptive_controller_epoch, 1)

    def test_late_same_epoch_failures_at_long_delays_adjust_only_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            crawler = self.make_crawler(Path(directory), workers=5)
        failure = self.fetch_result(ok=False, status=504)
        clock = mock.Mock(return_value=1_000.0)
        with mock.patch.object(legacy.time, "monotonic", clock):
            crawler._adaptive_observe(failure, request_epoch=0)
            first = (crawler.adaptive_workers, crawler.adaptive_batch_pause)
            for timestamp in (1_030.0, 1_090.0, 1_360.0):
                clock.return_value = timestamp
                crawler._adaptive_observe(failure, request_epoch=0)
        self.assertEqual(
            (crawler.adaptive_workers, crawler.adaptive_batch_pause),
            first,
        )

    def test_failure_pause_uses_fixed_half_second_step_with_three_second_floor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            crawler = self.make_crawler(
                Path(directory),
                workers=3,
                batch_size=8,
                batch_pause=1.0,
                batch_pause_ceiling=1.0,
            )

        with mock.patch.object(legacy.time, "monotonic", return_value=1_000.0):
            crawler._adaptive_observe(self.fetch_result(ok=False, status=503))
        self.assertEqual(crawler.adaptive_workers, 2)
        self.assertEqual(crawler.adaptive_batch_pause, 3.0)

        # Above the recovery floor the controller adds exactly 0.5 seconds,
        # instead of multiplying an already large cooldown.
        crawler.adaptive_recovery_at = 0.0
        if hasattr(crawler, "adaptive_last_decrease_at"):
            crawler.adaptive_last_decrease_at = 0.0
        if hasattr(crawler, "adaptive_next_decrease_at"):
            crawler.adaptive_next_decrease_at = 0.0
        crawler.adaptive_batch_pause = 4.0
        with mock.patch.object(legacy.time, "monotonic", return_value=2_000.0):
            crawler._adaptive_observe(self.fetch_result(ok=False, status=503))
        self.assertEqual(crawler.adaptive_workers, 1)
        self.assertEqual(crawler.adaptive_batch_pause, 4.5)

    def test_success_needs_full_window_and_increase_dwell(self) -> None:
        """A fast burst must not repeatedly raise concurrency."""

        with tempfile.TemporaryDirectory() as directory:
            crawler = self.make_crawler(Path(directory), workers=4)
        crawler.adaptive_workers = 4
        crawler.adaptive_batch_pause = crawler.adaptive_pause_floor
        # Start the fixture at the beginning of an eligible increase dwell;
        # production initialization uses the real monotonic clock.
        crawler.adaptive_next_increase_at = 1_000.0
        crawler.adaptive_last_increase_at = 0.0
        success = self.fetch_result(ok=True, status=200)
        clock = mock.Mock(return_value=1_000.0)
        success_window = crawler._required_healthy_results(4)

        with mock.patch.object(legacy.time, "monotonic", clock):
            for _ in range(success_window - 1):
                crawler._adaptive_observe(success)
            self.assertEqual(crawler.adaptive_workers, 4)

            clock.return_value = 1_120.0
            crawler._adaptive_observe(success)
            self.assertEqual(crawler.adaptive_workers, 5)
            self.assertEqual(
                crawler.adaptive_batch_pause,
                crawler.adaptive_pause_floor,
            )

            # Even another complete success window cannot immediately make a
            # second increase; the first decision needs time to settle.
            clock.return_value = (
                1_120.0 + legacy.ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS - 0.1
            )
            for _ in range(success_window):
                crawler._adaptive_observe(success)
            self.assertEqual(crawler.adaptive_workers, 5)

            clock.return_value = (
                1_240.0 + legacy.ADAPTIVE_INCREASE_MIN_INTERVAL_SECONDS + 0.1
            )
            for _ in range(success_window):
                crawler._adaptive_observe(success)
        self.assertEqual(crawler.adaptive_workers, 6)

    def test_success_window_accelerates_only_one_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            crawler = self.make_crawler(Path(directory), workers=4)
        crawler.adaptive_workers = 4
        crawler.adaptive_batch_pause = 4.5
        crawler.adaptive_next_increase_at = 1_000.0
        success = self.fetch_result(ok=True, status=200)

        with mock.patch.object(legacy.time, "monotonic", return_value=1_000.0):
            for _ in range(crawler._required_healthy_results(4) - 1):
                crawler._adaptive_observe(success)
        with mock.patch.object(legacy.time, "monotonic", return_value=1_120.0):
            crawler._adaptive_observe(success)

        # One healthy window may raise concurrency or lower pause, never both.
        # This prevents a single burst of cached/fast responses from making
        # two simultaneous load increases.
        self.assertEqual(crawler.adaptive_batch_pause, 4.5)
        self.assertEqual(crawler.adaptive_workers, 5)

    def test_pause_recovery_requires_same_health_window_and_uses_quarter_step(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            crawler = self.make_crawler(
                Path(directory),
                workers=3,
                worker_ceiling=3,
                batch_pause=4.0,
                batch_pause_ceiling=4.0,
            )
        crawler.adaptive_workers = 3
        crawler.adaptive_safe_worker_ceiling = 3
        crawler.adaptive_batch_pause = 4.0
        crawler.adaptive_safe_pause_floor = crawler.adaptive_pause_floor
        crawler.adaptive_next_increase_at = 0.0
        success = self.fetch_result(ok=True, status=200)
        with mock.patch.object(legacy.time, "monotonic", return_value=1_000.0):
            for _ in range(crawler._required_healthy_results(3) - 1):
                crawler._adaptive_observe(success)
        self.assertEqual(crawler.adaptive_batch_pause, 4.0)
        with mock.patch.object(legacy.time, "monotonic", return_value=1_120.0):
            crawler._adaptive_observe(success)
        self.assertEqual(crawler.adaptive_workers, 3)
        self.assertEqual(crawler.adaptive_batch_pause, 3.75)
        self.assertIsNone(crawler.adaptive_healthy_since)

    def test_saved_point_is_clamped_to_new_guardrails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = root / "metadata"
            metadata.mkdir()
            state = metadata / "state.json"
            state.write_text(
                json.dumps(
                    {
                        "queue_stage_id": "fixture-stage",
                        "adaptive_workers": 20,
                        "adaptive_batch_pause_seconds": 9,
                    }
                ),
                encoding="utf-8",
            )
            values = self.crawler_kwargs()
            values.update(
                worker_ceiling=12,
                batch_pause_ceiling=2.0,
                batch_pause=2.0,
            )
            with (
                mock.patch.object(legacy, "DATA_ROOT", root / "data"),
                mock.patch.object(legacy, "METADATA_ROOT", metadata),
                mock.patch.object(legacy, "MANIFEST_PATH", metadata / "manifest.jsonl"),
                mock.patch.object(legacy, "JOURNAL_PATH", metadata / "journal.jsonl"),
                mock.patch.object(legacy, "RUN_STATE_JSON", state),
                mock.patch.object(legacy, "ADAPTIVE_PROFILE_JSON", metadata / "profiles.json"),
                mock.patch.dict(
                    legacy.os.environ,
                    {"DATA_CRAWL_QUEUE_STAGE_ID": "fixture-stage"},
                ),
            ):
                crawler = legacy.Crawler(**values)
        self.assertEqual(crawler.adaptive_workers, 12)
        self.assertEqual(crawler.adaptive_batch_pause, 2.0)

    def test_lowered_worker_count_survives_stage_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = root / "metadata"
            metadata.mkdir()
            state = metadata / "state.json"
            state.write_text(
                json.dumps(
                    {
                        "queue_stage_id": "fixture-stage",
                        "adaptive_workers": 2,
                        "adaptive_batch_pause_seconds": 4.5,
                    }
                ),
                encoding="utf-8",
            )
            values = self.crawler_kwargs()
            with (
                mock.patch.object(legacy, "DATA_ROOT", root / "data"),
                mock.patch.object(legacy, "METADATA_ROOT", metadata),
                mock.patch.object(legacy, "MANIFEST_PATH", metadata / "manifest.jsonl"),
                mock.patch.object(legacy, "JOURNAL_PATH", metadata / "journal.jsonl"),
                mock.patch.object(legacy, "RUN_STATE_JSON", state),
                mock.patch.object(legacy, "ADAPTIVE_PROFILE_JSON", metadata / "profiles.json"),
                mock.patch.dict(
                    legacy.os.environ,
                    {"DATA_CRAWL_QUEUE_STAGE_ID": "fixture-stage"},
                ),
            ):
                crawler = legacy.Crawler(**values)

        self.assertEqual(crawler.adaptive_workers, 2)
        self.assertEqual(crawler.adaptive_batch_pause, 4.5)

    def test_restart_discards_health_and_unconfirmed_pause_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = root / "metadata"
            metadata.mkdir()
            state = metadata / "state.json"
            state.write_text(
                json.dumps(
                    {
                        "queue_stage_id": "fixture-stage",
                        "adaptive_workers": 1,
                        "adaptive_batch_pause_seconds": 2.75,
                        "adaptive_pause_rollback": 3.0,
                        "adaptive_success_streak": 30,
                        "adaptive_pause_success_streak": 30,
                        "adaptive_healthy_since": 10.0,
                        "adaptive_epoch_successes": 30,
                    }
                ),
                encoding="utf-8",
            )
            values = self.crawler_kwargs()
            values.update(workers=3, batch_pause=3.0, batch_pause_ceiling=3.0)
            with (
                mock.patch.object(legacy, "DATA_ROOT", root / "data"),
                mock.patch.object(legacy, "METADATA_ROOT", metadata),
                mock.patch.object(legacy, "MANIFEST_PATH", metadata / "manifest.jsonl"),
                mock.patch.object(legacy, "JOURNAL_PATH", metadata / "journal.jsonl"),
                mock.patch.object(legacy, "RUN_STATE_JSON", state),
                mock.patch.object(legacy, "ADAPTIVE_PROFILE_JSON", metadata / "profiles.json"),
                mock.patch.dict(
                    legacy.os.environ,
                    {"DATA_CRAWL_QUEUE_STAGE_ID": "fixture-stage"},
                ),
            ):
                crawler = legacy.Crawler(**values)

        self.assertEqual(crawler.adaptive_batch_pause, 3.0)
        self.assertEqual(crawler.adaptive_pause_success_streak, 0)
        self.assertEqual(crawler.adaptive_pause_rollback, 0.0)
        self.assertIsNone(crawler.adaptive_healthy_since)
        self.assertEqual(crawler.adaptive_epoch_successes, 0)

    def test_emergency_pause_and_safe_floor_survive_same_content_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = root / "metadata"
            metadata.mkdir()
            state = metadata / "state.json"
            state.write_text(
                json.dumps(
                    {
                        "queue_stage_id": "fixture-stage",
                        "phase": "unfinished-content",
                        "adaptive_phase": "unfinished-content",
                        "phase_remaining": 12,
                        "resumable": True,
                        "stopped_reason": (
                            "transient circuit breaker: 3 failures in a "
                            "3-completion window"
                        ),
                        "adaptive_workers": 1,
                        "adaptive_safe_worker_ceiling": 1,
                        "adaptive_batch_pause_seconds": 3.5,
                        "adaptive_batch_pause_ceiling_seconds": 3.0,
                        "adaptive_safe_pause_floor_seconds": 3.5,
                    }
                ),
                encoding="utf-8",
            )
            values = self.crawler_kwargs()
            values.update(
                workers=3,
                worker_ceiling=8,
                batch_pause=3.0,
                batch_pause_ceiling=3.0,
            )
            with (
                mock.patch.object(legacy, "DATA_ROOT", root / "data"),
                mock.patch.object(legacy, "METADATA_ROOT", metadata),
                mock.patch.object(legacy, "MANIFEST_PATH", metadata / "manifest.jsonl"),
                mock.patch.object(legacy, "JOURNAL_PATH", metadata / "journal.jsonl"),
                mock.patch.object(legacy, "RUN_STATE_JSON", state),
                mock.patch.object(legacy, "ADAPTIVE_PROFILE_JSON", metadata / "profiles.json"),
                mock.patch.dict(
                    legacy.os.environ,
                    {"DATA_CRAWL_QUEUE_STAGE_ID": "fixture-stage"},
                ),
            ):
                crawler = legacy.Crawler(**values)

        self.assertEqual(crawler.adaptive_workers, 1)
        self.assertEqual(crawler.adaptive_batch_pause, 3.5)
        self.assertEqual(crawler.adaptive_safe_pause_floor, 3.5)
        with mock.patch.object(legacy.time, "monotonic", return_value=2_000.0):
            crawler._adaptive_observe(self.fetch_result(ok=False, status=504))
        self.assertEqual(crawler.adaptive_batch_pause, 4.0)
        self.assertEqual(crawler.adaptive_safe_pause_floor, 4.0)

    def test_confirmed_circuit_extends_wait_without_second_pause_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            crawler = self.make_crawler(
                Path(directory),
                workers=1,
                worker_ceiling=8,
                batch_pause=3.0,
                batch_pause_ceiling=3.0,
            )
        crawler.adaptive_workers = 1
        crawler.adaptive_safe_worker_ceiling = 1
        crawler.adaptive_batch_pause = 3.0
        crawler.adaptive_safe_pause_floor = 3.0
        crawler.adaptive_last_failure_workers = 1

        failure = self.fetch_result(ok=False, status=504)
        clock = mock.Mock(return_value=1_000.0)
        with mock.patch.object(legacy.time, "monotonic", clock):
            crawler._adaptive_observe(failure, request_epoch=0)
            first_recovery_at = crawler.adaptive_recovery_at
            clock.return_value = 1_001.0
            crawler._adaptive_observe(
                failure,
                confirmed_failure_wave=True,
                request_epoch=0,
            )
        self.assertEqual(crawler.adaptive_workers, 1)
        self.assertEqual(crawler.adaptive_batch_pause, 3.5)
        self.assertEqual(crawler.adaptive_safe_pause_floor, 3.5)
        self.assertEqual(crawler.adaptive_controller_epoch, 1)
        self.assertGreater(crawler.adaptive_recovery_at, first_recovery_at)

        crawler.adaptive_success_streak = crawler.batch_size - 1
        crawler.adaptive_next_increase_at = 0.0
        success = self.fetch_result(ok=True, status=200)
        with mock.patch.object(legacy.time, "monotonic", return_value=2_000.0):
            crawler._adaptive_observe(success)
        self.assertEqual(crawler.adaptive_workers, 1)
        self.assertEqual(crawler.adaptive_batch_pause, 3.5)

    def test_confirmed_circuit_alone_never_changes_speed_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            crawler = self.make_crawler(
                Path(directory),
                workers=5,
                worker_ceiling=8,
                batch_pause=4.0,
                batch_pause_ceiling=4.0,
            )
        crawler.adaptive_workers = 5
        crawler.adaptive_safe_worker_ceiling = 8
        crawler.adaptive_batch_pause = 4.0
        crawler.adaptive_safe_pause_floor = crawler.adaptive_pause_floor

        with mock.patch.object(legacy.time, "monotonic", return_value=1_000.0):
            crawler._adaptive_observe(
                self.fetch_result(ok=False, status=504),
                confirmed_failure_wave=True,
                request_epoch=0,
            )

        self.assertEqual(crawler.adaptive_workers, 5)
        self.assertEqual(crawler.adaptive_safe_worker_ceiling, 8)
        self.assertEqual(crawler.adaptive_batch_pause, 4.0)
        self.assertEqual(crawler.adaptive_controller_epoch, 0)
        self.assertGreater(crawler.adaptive_recovery_at, 1_000.0)

    def test_sustained_singleton_success_lowers_emergency_pause_and_safe_floor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            crawler = self.make_crawler(
                Path(directory),
                workers=1,
                worker_ceiling=8,
                batch_size=40,
                batch_pause=3.0,
                batch_pause_ceiling=3.0,
            )
        crawler.adaptive_workers = 1
        crawler.adaptive_safe_worker_ceiling = 1
        crawler.adaptive_batch_pause = 15.0
        crawler.adaptive_safe_pause_floor = 15.0
        crawler.adaptive_next_increase_at = 0.0
        crawler.adaptive_next_pause_probe_at = 0.0
        success = self.fetch_result(ok=True, status=200)
        success_window = crawler._required_healthy_results(1)

        # Recovery requires both the result count and the full two-minute
        # continuous-health dwell, even at a singleton cooldown.
        self.assertEqual(success_window, 30)
        clock = mock.Mock(return_value=1_000.0)
        with mock.patch.object(legacy.time, "monotonic", clock):
            for completed in range(success_window - 1):
                clock.return_value = 1_000.0
                crawler._adaptive_observe(success)
            self.assertEqual(crawler.adaptive_batch_pause, 15.0)
            self.assertEqual(crawler.adaptive_safe_pause_floor, 15.0)

            clock.return_value = 1_120.0
            crawler._adaptive_observe(success)

        # Every pause recovery tier moves only one conservative quarter-second.
        self.assertEqual(crawler.adaptive_batch_pause, 14.75)
        self.assertEqual(crawler.adaptive_safe_pause_floor, 14.75)
        self.assertEqual(crawler.adaptive_pause_rollback, 15.0)
        self.assertGreaterEqual(
            crawler.adaptive_safe_pause_floor,
            crawler.adaptive_pause_floor,
        )

    def test_each_faster_pause_probe_updates_rollback_and_504_restores_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            crawler = self.make_crawler(
                Path(directory),
                workers=1,
                worker_ceiling=8,
                batch_size=40,
                batch_pause=3.0,
                batch_pause_ceiling=3.0,
            )
        crawler.adaptive_workers = 1
        crawler.adaptive_safe_worker_ceiling = 1
        crawler.adaptive_batch_pause = 8.0
        crawler.adaptive_safe_pause_floor = 8.0
        crawler.adaptive_next_increase_at = 0.0
        crawler.adaptive_next_pause_probe_at = 0.0
        success = self.fetch_result(ok=True, status=200)
        clock = mock.Mock(return_value=1_000.0)

        def complete_stable_pause_window() -> tuple[float, float]:
            previous_pause = crawler.adaptive_batch_pause
            success_window = crawler._required_healthy_results(1)
            for _ in range(success_window - 1):
                crawler._adaptive_observe(success)
            clock.return_value += 120.0
            crawler._adaptive_observe(success)
            return previous_pause, crawler.adaptive_batch_pause

        with mock.patch.object(legacy.time, "monotonic", clock):
            first_stable_pause, first_probe_pause = complete_stable_pause_window()
            self.assertEqual(first_probe_pause, 7.75)
            self.assertEqual(
                getattr(crawler, "adaptive_pause_rollback", None),
                first_stable_pause,
            )

            second_stable_pause, second_probe_pause = complete_stable_pause_window()
            self.assertEqual(second_probe_pause, 7.5)
            self.assertEqual(second_stable_pause, first_probe_pause)
            self.assertEqual(
                getattr(crawler, "adaptive_pause_rollback", None),
                second_stable_pause,
            )

            clock.return_value += second_probe_pause
            crawler._adaptive_observe(self.fetch_result(ok=False, status=504))

        self.assertGreaterEqual(
            crawler.adaptive_batch_pause,
            second_stable_pause,
        )
        self.assertGreaterEqual(
            crawler.adaptive_safe_pause_floor,
            second_stable_pause,
        )

    def test_manual_mode_keeps_dashboard_speed_after_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            crawler = self.make_crawler(
                Path(directory),
                workers=1,
                worker_ceiling=8,
                batch_pause=2.0,
                batch_pause_ceiling=3.0,
                adaptive_tuning=False,
            )
        failure = self.fetch_result(ok=False, status=504)
        crawler._adaptive_observe(failure, confirmed_failure_wave=True)
        self.assertEqual(crawler.adaptive_workers, 1)
        self.assertEqual(crawler.adaptive_batch_pause, 2.0)
        self.assertEqual(crawler._adaptive_request_start_interval(), 0.0)

    def test_manual_mode_does_not_probe_faster_pause_after_successes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            crawler = self.make_crawler(
                Path(directory),
                workers=1,
                worker_ceiling=8,
                batch_size=40,
                batch_pause=15.0,
                batch_pause_ceiling=15.0,
                adaptive_tuning=False,
            )
        crawler.adaptive_safe_pause_floor = crawler.batch_pause
        crawler.adaptive_next_pause_probe_at = 0.0
        success = self.fetch_result(ok=True, status=200)

        with mock.patch.object(legacy.time, "monotonic", return_value=10_000.0):
            for _ in range(crawler.batch_size * 2):
                crawler._adaptive_observe(success)

        self.assertEqual(crawler.adaptive_batch_pause, 15.0)
        self.assertEqual(crawler.adaptive_safe_pause_floor, 15.0)
        self.assertEqual(
            getattr(crawler, "adaptive_pause_rollback", None),
            0.0,
        )

    def test_failed_checkpoint_enters_replay_even_with_old_false_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = root / "metadata"
            metadata.mkdir()
            state = metadata / "state.json"
            state.write_text(
                json.dumps(
                    {
                        "queue_stage_id": "fixture-stage",
                        "phase": "v9 target",
                        "adaptive_phase": "v9 target",
                        "adaptive_replay_active": False,
                        "phase_remaining": 636,
                        "resumable": True,
                        "stopped_reason": (
                            "transient circuit breaker: 3 failures in a "
                            "3-completion window"
                        ),
                        "adaptive_workers": 7,
                        "adaptive_safe_worker_ceiling": 7,
                        "adaptive_batch_pause_seconds": 6.5,
                        "adaptive_batch_pause_ceiling_seconds": 6.0,
                    }
                ),
                encoding="utf-8",
            )
            values = self.crawler_kwargs()
            values.update(
                workers=3,
                worker_ceiling=8,
                batch_pause=6.0,
                batch_pause_ceiling=6.0,
            )
            with (
                mock.patch.object(legacy, "DATA_ROOT", root / "data"),
                mock.patch.object(legacy, "METADATA_ROOT", metadata),
                mock.patch.object(legacy, "MANIFEST_PATH", metadata / "manifest.jsonl"),
                mock.patch.object(legacy, "JOURNAL_PATH", metadata / "journal.jsonl"),
                mock.patch.object(legacy, "RUN_STATE_JSON", state),
                mock.patch.object(legacy, "ADAPTIVE_PROFILE_JSON", metadata / "profiles.json"),
                mock.patch.dict(
                    legacy.os.environ,
                    {"DATA_CRAWL_QUEUE_STAGE_ID": "fixture-stage"},
                ),
            ):
                crawler = legacy.Crawler(**values)

        self.assertTrue(crawler.adaptive_replay_active)
        self.assertEqual(crawler.adaptive_phase, "v9 target")
        self.assertEqual(crawler.adaptive_workers, 7)
        self.assertEqual(crawler.adaptive_safe_worker_ceiling, 7)

    def test_replayed_failed_content_continues_from_seven_and_lowers_to_six(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            crawler = self.make_crawler(
                root,
                workers=3,
                worker_ceiling=8,
                batch_size=30,
                transient_failure_threshold=3,
                rebuild_only=False,
            )
            target_phase = "v9 advanced questionnaire-conditioned rankings"
            crawler.adaptive_phase = target_phase
            crawler.adaptive_replay_active = True
            crawler.adaptive_workers = 7
            crawler.adaptive_safe_worker_ceiling = 7
            jobs = [
                legacy.FetchJob(
                    round_no=9,
                    url=f"https://touhou.vote/v9/replay-{index}",
                    target=root / f"missing-{index}.json",
                )
                for index in range(7)
            ]

            def fail(job: legacy.FetchJob) -> legacy.FetchResult:
                return legacy.FetchResult(
                    job=job,
                    ok=False,
                    status=502,
                    transient=True,
                )

            crawler.fetch_one = fail
            with (
                mock.patch.object(crawler, "_register_source"),
                mock.patch.object(crawler, "_existing_is_valid", return_value=False),
                mock.patch.object(legacy, "write_json_atomic"),
                mock.patch.object(crawler, "_persist_adaptive_profile"),
            ):
                results = crawler.fetch_many(jobs, target_phase)

        self.assertFalse(crawler.adaptive_replay_active)
        self.assertGreaterEqual(len(results), 3)
        self.assertTrue(crawler.circuit_open)
        self.assertEqual(crawler.adaptive_workers, 6)
        self.assertEqual(crawler.adaptive_safe_worker_ceiling, 6)

    def test_new_content_resets_current_speed_and_safe_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            crawler = self.make_crawler(
                root,
                workers=3,
                worker_ceiling=8,
                batch_pause=5.0,
                batch_pause_ceiling=5.0,
            )
            crawler.adaptive_phase = "content-a"
            crawler.adaptive_workers = 7
            crawler.adaptive_safe_worker_ceiling = 7
            crawler.adaptive_batch_pause = 1.0
            crawler.adaptive_safe_pause_floor = 1.0
            crawler.adaptive_pause_rollback = 4.0

            changed = crawler._begin_network_phase("content-b")

        self.assertTrue(changed)
        self.assertEqual(crawler.adaptive_phase, "content-b")
        self.assertEqual(crawler.adaptive_workers, 8)
        self.assertEqual(crawler.adaptive_safe_worker_ceiling, 8)
        self.assertEqual(crawler.adaptive_batch_pause, 5.0)
        self.assertEqual(
            crawler.adaptive_safe_pause_floor,
            crawler.adaptive_pause_floor,
        )
        self.assertEqual(
            getattr(crawler, "adaptive_pause_rollback", None),
            0.0,
        )

    def test_same_content_keeps_learned_safe_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            crawler = self.make_crawler(
                root,
                workers=3,
                worker_ceiling=8,
            )
            crawler.adaptive_phase = "content-a"
            crawler.adaptive_workers = 7
            crawler.adaptive_safe_worker_ceiling = 7

            changed = crawler._begin_network_phase("content-a")

        self.assertFalse(changed)
        self.assertEqual(crawler.adaptive_workers, 7)
        self.assertEqual(crawler.adaptive_safe_worker_ceiling, 7)

    def test_cached_prefix_does_not_consume_content_reset_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cached = root / "cached.json"
            cached.write_bytes(b"{}")
            crawler = self.make_crawler(
                root,
                workers=3,
                worker_ceiling=8,
                rebuild_only=False,
            )
            crawler.adaptive_phase = "unfinished-content"
            crawler.adaptive_replay_active = True
            crawler.adaptive_workers = 7
            crawler.adaptive_safe_worker_ceiling = 7

            with (
                mock.patch.object(crawler, "_register_source"),
                mock.patch.object(crawler, "_existing_is_valid", return_value=True),
                mock.patch.object(crawler, "_enrich_cached_record"),
                mock.patch.object(legacy, "write_json_atomic"),
                mock.patch.object(crawler, "_persist_adaptive_profile"),
            ):
                crawler.fetch_many(
                    [
                        legacy.FetchJob(
                            round_no=5,
                            url="https://touhou.vote/v5/cached-prefix",
                            target=cached,
                        )
                    ],
                    "already-finished-content",
                )
                crawler.adaptive_replay_active = False
                crawler.fetch_many(
                    [
                        legacy.FetchJob(
                            round_no=5,
                            url="https://touhou.vote/v5/next-cached-content",
                            target=cached,
                        )
                    ],
                    "next-content",
                )

        self.assertEqual(crawler.adaptive_phase, "next-content")
        self.assertEqual(crawler.adaptive_workers, 8)
        self.assertEqual(crawler.adaptive_safe_worker_ceiling, 8)

    def test_zero_normal_pause_floor_is_reachable_after_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            crawler = self.make_crawler(
                Path(directory),
                workers=1,
                batch_size=8,
                batch_pause=0.0,
                batch_pause_ceiling=0.0,
            )
        crawler.adaptive_batch_pause = 0.2
        crawler.adaptive_success_streak = 59
        crawler.adaptive_epoch_successes = 29
        crawler.adaptive_pause_success_streak = 29
        crawler.adaptive_healthy_epoch = crawler.adaptive_controller_epoch
        crawler.adaptive_healthy_since = 1_000.0
        crawler.adaptive_next_increase_at = 0.0
        crawler.adaptive_next_pause_probe_at = 0.0
        success = legacy.FetchResult(
            job=legacy.FetchJob(
                round_no=5,
                url="https://touhou.vote/v5/test",
                target=Path("test.json"),
            ),
            ok=True,
        )
        with mock.patch.object(legacy.time, "monotonic", return_value=1_120.0):
            crawler._adaptive_observe(success)
        self.assertEqual(crawler.adaptive_batch_pause, 0.0)

    def test_cli_rejects_values_above_configured_or_absolute_ceiling(self) -> None:
        cases = (
            ["--workers", "11", "--worker-ceiling", "10"],
            ["--request-limit", "31", "--request-limit-ceiling", "30"],
            ["--batch-pause", "4", "--batch-pause-ceiling", "3"],
            ["--worker-ceiling", str(legacy.ABSOLUTE_MAX_WORKERS + 1)],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(SystemExit):
                legacy.main(arguments)


if __name__ == "__main__":
    unittest.main()
