from __future__ import annotations

import copy
from pathlib import Path
import threading
import tempfile
import time
import unittest
from unittest import mock

from scripts_pipeline import crawl_cn_legacy as legacy


class LegacyProbePathTests(unittest.TestCase):
    def test_staging_is_preferred_and_root_remains_a_compatibility_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging" / "cn_legacy_probes"
            staging.mkdir(parents=True)
            (root / ".tmp_cn_root_only.html").write_text("root", encoding="utf-8")
            (root / ".tmp_cn_both.html").write_text("old", encoding="utf-8")
            (staging / ".tmp_cn_both.html").write_text("staged", encoding="utf-8")
            with (
                mock.patch.object(legacy, "WORKSPACE", root),
                mock.patch.object(legacy, "LEGACY_PROBE_ROOT", staging),
            ):
                self.assertEqual(
                    legacy.legacy_probe_path(".tmp_cn_both.html"),
                    staging / ".tmp_cn_both.html",
                )
                self.assertEqual(
                    legacy.legacy_probe_path(".tmp_cn_root_only.html"),
                    root / ".tmp_cn_root_only.html",
                )


class LegacySlidingWindowTests(unittest.TestCase):
    @staticmethod
    def crawler(*, workers: int, batch_size: int, threshold: int = 6) -> legacy.Crawler:
        crawler = object.__new__(legacy.Crawler)
        crawler.workers = workers
        crawler.batch_size = batch_size
        crawler.batch_pause = 0.0
        crawler.delay = 0.0
        crawler.transient_failure_threshold = threshold
        crawler.circuit_open = False
        crawler.circuit_reason = ""
        crawler.rebuild_only = False
        crawler.refresh = False
        crawler.adaptive_controller_epoch = 0
        crawler.records = {}
        crawler.skipped = 0
        crawler._lock = threading.RLock()
        crawler._register_source = lambda job: None
        crawler._existing_is_valid = lambda job, record: False
        return crawler

    @staticmethod
    def jobs(count: int) -> list[legacy.FetchJob]:
        return [
            legacy.FetchJob(
                round_no=5,
                url=f"https://touhou.vote/v5/test/{index}",
                target=Path(f"test_{index}.json"),
                expect="json",
                label=f"test {index}",
            )
            for index in range(count)
        ]

    def test_fast_completion_refills_before_slow_peer_finishes(self) -> None:
        crawler = self.crawler(workers=2, batch_size=10)
        jobs = self.jobs(3)
        slow_started = threading.Event()
        slow_finished = threading.Event()
        third_started_before_slow_finished = threading.Event()

        def fetch(job: legacy.FetchJob) -> legacy.FetchResult:
            index = int(job.url.rsplit("/", 1)[1])
            if index == 0:
                slow_started.set()
                time.sleep(0.2)
                slow_finished.set()
            elif index == 1:
                self.assertTrue(slow_started.wait(timeout=1))
            elif not slow_finished.is_set():
                third_started_before_slow_finished.set()
            return legacy.FetchResult(job=job, ok=True, status=200)

        crawler.fetch_one = fetch
        with mock.patch.object(legacy, "write_json_atomic"):
            results = crawler.fetch_many(jobs, "sliding-test")

        self.assertEqual(len(results), 3)
        self.assertTrue(third_started_before_slow_finished.is_set())

    def test_checkpoints_follow_network_completion_windows(self) -> None:
        crawler = self.crawler(workers=1, batch_size=2)
        crawler.batch_pause = 0.25
        jobs = self.jobs(5)
        crawler.fetch_one = lambda job: legacy.FetchResult(
            job=job, ok=True, status=200
        )
        checkpoints: list[dict[str, object]] = []
        clock = [0.0]

        def monotonic() -> float:
            value = clock[0]
            clock[0] += 0.2
            return value

        with (
            mock.patch.object(
                legacy,
                "write_json_atomic",
                side_effect=lambda path, value: checkpoints.append(copy.deepcopy(value)),
            ),
            mock.patch.object(
                legacy.time,
                "monotonic",
                side_effect=monotonic,
            ),
            mock.patch.object(legacy.time, "sleep") as sleep,
        ):
            crawler.fetch_many(jobs, "checkpoint-test")

        completed = [item["phase_completed_this_run"] for item in checkpoints]
        self.assertEqual(completed[0], 0)
        self.assertEqual(completed[-1], 5)
        self.assertEqual(completed, sorted(set(completed)))
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(checkpoints[-1]["phase_remaining"], 0)

    def test_singleton_recovery_spaces_every_real_http_retry(self) -> None:
        crawler = self.crawler(workers=1, batch_size=30)
        crawler.retries = 3
        crawler.timeout = 10
        crawler.failed = 0
        crawler.skipped = 0
        crawler.adaptive_tuning = True
        crawler.worker_ceiling = 8
        crawler.adaptive_worker_ceiling = 8
        crawler.adaptive_safe_worker_ceiling = 1
        crawler.adaptive_workers = 1
        crawler.adaptive_pause_floor = 0.25
        crawler.adaptive_safe_pause_floor = 3.0
        crawler.adaptive_batch_pause = 3.0
        crawler.adaptive_failure_wave_active = True
        crawler.adaptive_restart_probation = True
        crawler._adaptive_request_gate_lock = threading.Lock()
        crawler._adaptive_last_request_start_at = None
        crawler._append_record = lambda record: None

        job = self.jobs(1)[0]
        clock = [100.0]
        request_starts: list[float] = []

        def monotonic() -> float:
            return clock[0]

        def sleep(seconds: float) -> None:
            clock[0] += seconds

        def fail_with_504(*args: object, **kwargs: object) -> object:
            request_starts.append(clock[0])
            raise legacy.urllib.error.HTTPError(
                job.url,
                504,
                "Gateway Timeout",
                hdrs=None,
                fp=None,
            )

        with (
            mock.patch.object(legacy.time, "monotonic", side_effect=monotonic),
            mock.patch.object(legacy.time, "sleep", side_effect=sleep),
            mock.patch.object(
                legacy.urllib.request,
                "urlopen",
                side_effect=fail_with_504,
            ),
        ):
            result = crawler.fetch_one(job)

        self.assertFalse(result.ok)
        self.assertEqual(len(request_starts), 3)
        self.assertTrue(
            all(
                later - earlier >= crawler.adaptive_batch_pause
                for earlier, later in zip(request_starts, request_starts[1:])
            )
        )

    def test_transient_retry_success_resets_health_without_downshift(self) -> None:
        crawler = self.crawler(workers=3, batch_size=30)
        crawler.retries = 2
        crawler.timeout = 1
        crawler.failed = 0
        crawler.downloaded = 0
        crawler.adaptive_tuning = True
        crawler.worker_ceiling = 8
        crawler.adaptive_worker_ceiling = 8
        crawler.adaptive_safe_worker_ceiling = 8
        crawler.adaptive_workers = 3
        crawler.adaptive_batch_pause = 1.0
        crawler.adaptive_healthy_since = 100.0
        crawler.adaptive_healthy_epoch = 0
        crawler.adaptive_epoch_successes = 30
        crawler.adaptive_success_streak = 30
        crawler._append_record = lambda record: None

        with tempfile.TemporaryDirectory() as directory:
            job = legacy.FetchJob(
                round_no=5,
                url="https://touhou.vote/v5/retry-success",
                target=Path(directory) / "retry.json",
                expect="json",
            )
            response = mock.MagicMock()
            response.status = 200
            response.headers = {
                "Content-Type": "application/json",
                "Content-Encoding": "",
            }
            response.read.return_value = b"{}"
            response.__enter__.return_value = response
            first = legacy.urllib.error.HTTPError(
                job.url, 504, "Gateway Timeout", hdrs=None, fp=None
            )
            with (
                mock.patch.object(legacy, "WORKSPACE", Path(directory)),
                mock.patch.object(
                    legacy.urllib.request,
                    "urlopen",
                    side_effect=[first, response],
                ),
                mock.patch.object(legacy.time, "sleep"),
            ):
                result = crawler.fetch_one(job)

        self.assertTrue(result.ok)
        self.assertTrue(result.transient_recovered)
        self.assertEqual(crawler.adaptive_workers, 3)
        self.assertEqual(crawler.adaptive_batch_pause, 1.0)
        crawler._adaptive_observe(result, request_epoch=0)
        self.assertIsNone(crawler.adaptive_healthy_since)
        self.assertEqual(crawler.adaptive_epoch_successes, 0)

    def test_nontransient_errors_clear_health_but_do_not_change_speed(self) -> None:
        crawler = self.crawler(workers=3, batch_size=30)
        crawler.adaptive_worker_ceiling = 8
        crawler.adaptive_safe_worker_ceiling = 8
        crawler.adaptive_workers = 3
        crawler.adaptive_batch_pause = 1.0
        crawler.adaptive_healthy_since = 100.0
        crawler.adaptive_healthy_epoch = 0
        crawler.adaptive_epoch_successes = 30
        crawler.adaptive_success_streak = 30
        for status, error in (
            (404, "HTTP 404"),
            (None, "semantic validation failed"),
            (None, "OSError: disk full"),
        ):
            with self.subTest(status=status, error=error):
                crawler.adaptive_healthy_since = 100.0
                crawler.adaptive_healthy_epoch = crawler.adaptive_controller_epoch
                crawler.adaptive_epoch_successes = 30
                crawler.adaptive_success_streak = 30
                result = legacy.FetchResult(
                    job=self.jobs(1)[0],
                    ok=False,
                    status=status,
                    error=error,
                    transient=False,
                )
                crawler._adaptive_observe(result)
                self.assertEqual(crawler.adaptive_workers, 3)
                self.assertEqual(crawler.adaptive_batch_pause, 1.0)
                self.assertIsNone(crawler.adaptive_healthy_since)

    def test_403_and_429_are_retried_before_success(self) -> None:
        crawler = self.crawler(workers=2, batch_size=30)
        crawler.retries = 2
        crawler.timeout = 1
        crawler.downloaded = 0
        crawler.failed = 0
        crawler._append_record = lambda record: None
        for status in (403, 429):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                job = legacy.FetchJob(
                    round_no=5,
                    url=f"https://touhou.vote/v5/retry-{status}",
                    target=Path(directory) / "retry.json",
                    expect="json",
                )
                response = mock.MagicMock()
                response.status = 200
                response.headers = {
                    "Content-Type": "application/json",
                    "Content-Encoding": "",
                }
                response.read.return_value = b"{}"
                response.__enter__.return_value = response
                first = legacy.urllib.error.HTTPError(
                    job.url, status, "blocked", hdrs=None, fp=None
                )
                with (
                    mock.patch.object(legacy, "WORKSPACE", Path(directory)),
                    mock.patch.object(
                        legacy.urllib.request,
                        "urlopen",
                        side_effect=[first, response],
                    ),
                    mock.patch.object(legacy.time, "sleep"),
                ):
                    result = crawler.fetch_one(job)
                self.assertTrue(result.ok)
                self.assertTrue(result.transient_recovered)

    def test_timeout_retry_success_is_not_a_permanent_slowdown(self) -> None:
        crawler = self.crawler(workers=2, batch_size=30)
        crawler.retries = 2
        crawler.timeout = 1
        crawler.downloaded = 0
        crawler.failed = 0
        crawler._append_record = lambda record: None
        with tempfile.TemporaryDirectory() as directory:
            job = legacy.FetchJob(
                round_no=5,
                url="https://touhou.vote/v5/timeout-success",
                target=Path(directory) / "retry.json",
                expect="json",
            )
            response = mock.MagicMock()
            response.status = 200
            response.headers = {
                "Content-Type": "application/json",
                "Content-Encoding": "",
            }
            response.read.return_value = b"{}"
            response.__enter__.return_value = response
            with (
                mock.patch.object(legacy, "WORKSPACE", Path(directory)),
                mock.patch.object(
                    legacy.urllib.request,
                    "urlopen",
                    side_effect=[TimeoutError("timed out"), response],
                ),
                mock.patch.object(legacy.time, "sleep"),
            ):
                result = crawler.fetch_one(job)
        self.assertTrue(result.ok)
        self.assertTrue(result.transient_recovered)

    def test_global_transient_gate_spaces_other_workers(self) -> None:
        crawler = self.crawler(workers=3, batch_size=30)
        crawler.adaptive_tuning = True
        crawler.adaptive_batch_pause = 1.0
        crawler.adaptive_workers = 3
        crawler.adaptive_safe_worker_ceiling = 3
        with (
            mock.patch.object(
                legacy.time, "monotonic", side_effect=[100.0, 100.0, 100.0]
            ),
            mock.patch.object(legacy.time, "sleep") as sleep,
        ):
            crawler._note_transient_recovery_gate()
            crawler._wait_for_adaptive_request_start()
        self.assertTrue(sleep.called)
        self.assertGreaterEqual(sleep.call_args.args[0], legacy.RECOVERY_MIN_PAUSE_SECONDS)

    def test_degraded_cooldown_does_not_clear_circuit_evidence(self) -> None:
        crawler = self.crawler(workers=3, batch_size=30, threshold=3)
        crawler.batch_pause = 1.0
        crawler.adaptive_batch_pause = 1.0
        crawler.adaptive_tuning = True
        crawler.worker_ceiling = 3
        crawler.adaptive_worker_ceiling = 3
        crawler.adaptive_safe_worker_ceiling = 2
        crawler.adaptive_workers = 2
        crawler.adaptive_pause_floor = 0.25
        crawler.adaptive_safe_pause_floor = 1.0
        crawler.adaptive_phase = "degraded-window-test"
        jobs = self.jobs(4)
        crawler.fetch_one = lambda job: legacy.FetchResult(
            job=job,
            ok=False,
            status=504,
            transient=True,
        )

        with (
            mock.patch.object(legacy, "write_json_atomic"),
            mock.patch.object(crawler, "_persist_adaptive_profile"),
            mock.patch.object(crawler, "_adaptive_observe"),
            mock.patch.object(legacy.time, "sleep") as sleep,
        ):
            results = crawler.fetch_many(jobs, "degraded-window-test")

        self.assertGreaterEqual(len(results), 3)
        self.assertTrue(crawler.circuit_open)
        self.assertIn("3 failures", crawler.circuit_reason)
        sleep.assert_any_call(1.0)

    def test_failed_and_corrupt_checkpoints_precede_new_missing_jobs(self) -> None:
        crawler = self.crawler(workers=1, batch_size=20)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jobs = [
                legacy.FetchJob(
                    round_no=5,
                    url=f"https://touhou.vote/v5/priority/{index}",
                    target=root / f"item_{index}.json",
                    expect="json",
                    label=f"priority {index}",
                )
                for index in range(3)
            ]
            # Input order is new, known failure, corrupt partial file.  Both
            # kinds of unfinished checkpoint work must move ahead of the new
            # frontier while retaining their relative order.
            failed_key = crawler.record_key(jobs[1])
            crawler.records[failed_key] = {
                "record_key": failed_key,
                "success": False,
                "error": "HTTP 503",
            }
            jobs[2].target.write_text("corrupt", encoding="utf-8")
            fetched: list[int] = []

            def fetch(job: legacy.FetchJob) -> legacy.FetchResult:
                fetched.append(int(job.url.rsplit("/", 1)[1]))
                return legacy.FetchResult(job=job, ok=True, status=200)

            crawler.fetch_one = fetch
            with mock.patch.object(legacy, "write_json_atomic"):
                crawler.fetch_many(jobs, "priority-test")

        self.assertEqual(fetched, [1, 2, 0])

    def test_circuit_stops_refill_but_drains_inflight_request(self) -> None:
        crawler = self.crawler(workers=3, batch_size=2, threshold=2)
        jobs = self.jobs(5)
        release_third = threading.Event()
        started: list[int] = []
        started_lock = threading.Lock()

        def fetch(job: legacy.FetchJob) -> legacy.FetchResult:
            index = int(job.url.rsplit("/", 1)[1])
            with started_lock:
                started.append(index)
            if index in {0, 1}:
                return legacy.FetchResult(job=job, ok=False, status=503)
            if index >= 2:
                release_third.wait(timeout=1)
            return legacy.FetchResult(job=job, ok=True, status=200)

        crawler.fetch_one = fetch
        checkpoints: list[dict[str, object]] = []
        timer = threading.Timer(0.2, release_third.set)
        timer.start()
        try:
            with mock.patch.object(
                legacy,
                "write_json_atomic",
                side_effect=lambda path, value: checkpoints.append(copy.deepcopy(value)),
            ):
                results = crawler.fetch_many(jobs, "circuit-test")
        finally:
            timer.cancel()

        # The first failure lowers and gates the active limit before any slot is
        # refilled; only the already-running third request is drained.
        self.assertEqual(set(started), {0, 1, 2})
        self.assertEqual(len(results), 3)
        self.assertTrue(crawler.circuit_open)
        self.assertEqual(checkpoints[-1]["phase_completed_this_run"], 3)
        self.assertEqual(checkpoints[-1]["phase_remaining"], 2)

    def test_failure_wave_is_observed_before_refill_and_not_during_circuit_drain(self) -> None:
        crawler = self.crawler(workers=3, batch_size=20, threshold=2)
        crawler.worker_ceiling = 3
        crawler.adaptive_worker_ceiling = 3
        crawler.adaptive_workers = 3
        crawler.batch_pause = 3.0
        crawler.adaptive_batch_pause = 3.0
        crawler.adaptive_pause_floor = 0.25
        crawler.adaptive_tuning = True
        crawler.adaptive_recovery_at = 0.0
        crawler.adaptive_adjustments = 0
        jobs = self.jobs(4)
        started: list[int] = []
        initial_wave = threading.Barrier(3)

        def fetch(job: legacy.FetchJob) -> legacy.FetchResult:
            started.append(int(job.url.rsplit("/", 1)[1]))
            # Hold the first three submissions together so the assertion
            # observes the controller's refill decision, not executor timing.
            if len(started) <= 3:
                initial_wave.wait(timeout=2)
            return legacy.FetchResult(
                job=job,
                ok=False,
                status=504,
                transient=True,
            )

        crawler.fetch_one = fetch
        with mock.patch.object(legacy, "write_json_atomic"):
            results = crawler.fetch_many(jobs, "adaptive-circuit-drain-test")

        # The first result lowers the active limit before refill.  The second
        # opens the circuit; it and the remaining in-flight failure are drain
        # results from the same outage and must not cause more reductions.
        self.assertEqual(set(started), {0, 1, 2})
        self.assertEqual(len(results), 3)
        self.assertTrue(crawler.circuit_open)
        self.assertEqual(crawler.adaptive_workers, 2)
        # The first 504 changes both dimensions once (3 -> 2 workers and
        # 3.0 -> 3.5 seconds).  Threshold confirmation and the other two
        # already-submitted failures may drain, but cannot raise pause again.
        self.assertEqual(crawler.adaptive_batch_pause, 3.5)
        self.assertEqual(
            crawler.adaptive_controller_epoch,
            crawler.adaptive_failure_wave_epoch + 1,
        )

    def test_transport_failures_without_http_status_trip_circuit(self) -> None:
        crawler = self.crawler(workers=1, batch_size=2, threshold=2)
        jobs = self.jobs(3)
        def fetch(job: legacy.FetchJob) -> legacy.FetchResult:
            index = int(job.url.rsplit("/", 1)[1])
            return legacy.FetchResult(
                job=job,
                ok=False,
                status=None if index == 0 else 503,
                error=(
                    "TimeoutError: timed out"
                    if index == 0
                    else "HTTPError 503"
                ),
                transient=True,
            )

        crawler.fetch_one = fetch
        clock = [100.0]

        with (
            mock.patch.object(legacy, "write_json_atomic"),
            mock.patch.object(
                legacy.time,
                "monotonic",
                side_effect=lambda: clock[0],
            ),
            mock.patch.object(
                legacy.time,
                "sleep",
                side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
            ),
        ):
            results = crawler.fetch_many(jobs, "transport-circuit-test")

        self.assertEqual(len(results), 2)
        self.assertTrue(crawler.circuit_open)
        self.assertIn("transient circuit breaker", crawler.circuit_reason)
        self.assertIn("transport", crawler.circuit_reason)
        self.assertIn("503", crawler.circuit_reason)

    def test_threshold_trips_immediately_without_waiting_for_full_batch(self) -> None:
        crawler = self.crawler(workers=2, batch_size=50, threshold=3)
        jobs = self.jobs(20)
        started: list[int] = []

        def fetch(job: legacy.FetchJob) -> legacy.FetchResult:
            started.append(int(job.url.rsplit("/", 1)[1]))
            return legacy.FetchResult(
                job=job,
                ok=False,
                status=None,
                error="URLError: WinError 10013",
                transient=True,
            )

        crawler.fetch_one = fetch
        clock = [100.0]
        with (
            mock.patch.object(legacy, "write_json_atomic"),
            mock.patch.object(
                legacy.time,
                "monotonic",
                side_effect=lambda: clock[0],
            ),
            mock.patch.object(
                legacy.time,
                "sleep",
                side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
            ),
        ):
            results = crawler.fetch_many(jobs, "early-circuit-test")

        self.assertTrue(crawler.circuit_open)
        self.assertLess(len(results), crawler.batch_size)
        self.assertLessEqual(len(started), crawler.transient_failure_threshold + crawler.workers)
        self.assertIn("3 failures", crawler.circuit_reason)

    def test_transport_exception_classifier_excludes_semantic_and_disk_errors(self) -> None:
        self.assertTrue(
            legacy.is_transient_network_exception(
                legacy.urllib.error.URLError(TimeoutError("timed out"))
            )
        )
        self.assertTrue(
            legacy.is_transient_network_exception(ConnectionResetError())
        )
        self.assertFalse(
            legacy.is_transient_network_exception(
                RuntimeError("invalid response schema")
            )
        )
        self.assertFalse(
            legacy.is_transient_network_exception(OSError("disk full"))
        )


if __name__ == "__main__":
    unittest.main()
