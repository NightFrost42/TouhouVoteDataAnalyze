from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock
import urllib.error
from pathlib import Path

from scripts_pipeline import crawl_cn_modern_entity_questionnaire as entity
from scripts_pipeline import crawl_cn_modern_advanced as advanced
from scripts_pipeline import crawl_cn_modern as core


class EntityQuestionnaireTests(unittest.TestCase):
    def test_content_list_switch_keeps_one_continuous_speed_probe(self) -> None:
        speed = core.AdaptiveSpeed(
            workers=3,
            request_limit=10,
            pause=0.5,
            worker_ceiling=8,
            request_limit_ceiling=30,
            pause_ceiling=3.0,
            profile_path=None,
        )
        speed.set_phase("content-a")
        speed.workers = 6
        speed.pause = 1.25
        speed.safe_worker_ceiling = 6
        speed.safe_pause_floor = 1.25
        speed.pause_rollback = 1.5
        speed.pause_probe_blocked_until = 12345.0

        speed.set_phase("content-b")
        self.assertEqual((speed.workers, speed.pause), (6, 1.25))
        self.assertEqual(speed.pause_rollback, 1.5)
        self.assertEqual(speed.pause_probe_blocked_until, 12345.0)

        speed.workers = 2
        speed.pause = 2.0
        speed.set_phase("content-a")
        self.assertEqual((speed.workers, speed.pause), (2, 2.0))

    def spec(self) -> advanced.ConditionSpec:
        return advanced.ConditionSpec(
            source_category="character",
            kind="any",
            source_index=1,
            source_rank=1,
            source_display_rank="1",
            source_name="灵梦",
            normalized_probe_name="灵梦",
            expected_cohort=12,
            query_filter='chars: ["灵梦"]',
        )

    def value(self, *, answers_str: bool = False) -> dict:
        data = {
            "queryGlobalStats": {"numVote": 12},
            "queryQuestionnaire": {
                "entries": [
                    {
                        "questionId": "q11011",
                        "answersCat": [{"aid": "1101101", "totalVotes": 5, "maleVotes": 4, "femaleVotes": 1}],
                        "totalAnswers": 12,
                        "totalMale": 10,
                        "totalFemale": 2,
                    }
                ]
            },
            "queryCompletionRates": {"items": []},
        }
        if answers_str:
            data["queryQuestionnaire"]["answersStr"] = []
        return {
            "provenance": {
                "status": 200,
                "operation": "EntityQuestionnaire",
                "variables": {
                    "voteStart": "start",
                    "voteYear": 10,
                    "query": 'chars: ["灵梦"]',
                    "questionsOfInterest": ["q11011"],
                },
            },
            "context": {
                "sourceCategory": "character",
                "conditionKind": "any",
                "query": 'chars: ["灵梦"]',
            },
            "data": data,
        }

    def test_checkpoint_shape_is_verified(self) -> None:
        spec = self.spec()
        variables = {
            "voteStart": "start",
            "voteYear": 10,
            "query": spec.query_filter,
            "questionsOfInterest": ["q11011"],
        }
        ok, reason = entity.response_valid(self.value(), spec, variables)
        self.assertTrue(ok, reason)

    def test_open_text_field_is_rejected(self) -> None:
        spec = self.spec()
        variables = {
            "voteStart": "start",
            "voteYear": 10,
            "query": spec.query_filter,
            "questionsOfInterest": ["q11011"],
        }
        ok, reason = entity.response_valid(self.value(answers_str=True), spec, variables)
        self.assertFalse(ok)
        self.assertIn("forbidden", reason or "")

    def test_queue_does_not_schedule_unavailable_entity_stage(self) -> None:
        config = json.loads(
            Path("metadata/data_crawl_queue.json").read_text(encoding="utf-8")
        )
        self.assertTrue(
            any(item["id"] == "cn_modern_entity_questionnaire" for item in config["stages"])
        )
        self.assertIn("queryQuestionnaire", entity.ENTITY_QUESTIONNAIRE_QUERY)
        self.assertEqual(entity.core.ENDPOINT, "https://touhou.vote/res-be/graphql")

    def test_queue_status_is_small_and_attempt_owned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            status_path = Path(temporary) / "queue-status.json"
            old_path = entity.STATUS_PATH
            old_stage = os.environ.get("DATA_CRAWL_QUEUE_STAGE_ID")
            try:
                entity.STATUS_PATH = status_path
                os.environ["DATA_CRAWL_QUEUE_STAGE_ID"] = "cn_modern_entity_questionnaire"
                entity.write_queue_status(
                    state="running",
                    stage="entity_questionnaire",
                    round=10,
                    completed=2,
                    total=4,
                    remaining=2,
                    currentDimension="character_any",
                    currentSourceIndex=3,
                    currentSourceName="古明地恋",
                    currentQuery='chars: ["古明地恋"]',
                )
                value = json.loads(status_path.read_text(encoding="utf-8"))
            finally:
                entity.STATUS_PATH = old_path
                if old_stage is None:
                    os.environ.pop("DATA_CRAWL_QUEUE_STAGE_ID", None)
                else:
                    os.environ["DATA_CRAWL_QUEUE_STAGE_ID"] = old_stage
        self.assertEqual(value["queue_stage_id"], "cn_modern_entity_questionnaire")
        self.assertEqual((value["completed"], value["total"], value["remaining"]), (2, 4, 2))
        self.assertEqual(value["currentQuery"], 'chars: ["古明地恋"]')

    def test_only_modern_site_availability_errors_open_recovery_circuit(self) -> None:
        def http_error(status: int) -> urllib.error.HTTPError:
            return urllib.error.HTTPError("https://touhou.vote/", status, "", {}, None)

        for status in (403, 429, 504, 521):
            self.assertIsNotNone(entity.transient_failure_reason(http_error(status)))
        self.assertIsNone(entity.transient_failure_reason(http_error(404)))
        self.assertIsNone(entity.transient_failure_reason(ValueError("semantic")))
        gateway_decode = RuntimeError(
            'QuestionnairePairCell: [{"extensions":{"service":"gateway",'
            '"url":"http://result-query/v1/global-stats/",'
            '"error_kind":"JSON_DECODE_ERROR",'
            '"error_message":"EOF while parsing a value"}}]'
        )
        self.assertEqual(
            entity.transient_failure_reason(gateway_decode),
            "graphql: upstream decode",
        )

    def test_repeated_521_stops_round_and_leaves_unattempted_items_pending(self) -> None:
        specs = [
            advanced.ConditionSpec(
                source_category="character",
                kind="any",
                source_index=index,
                source_rank=index,
                source_display_rank=str(index),
                source_name=f"角色{index}",
                normalized_probe_name=f"角色{index}",
                expected_cohort=10,
                query_filter=f'chars: ["角色{index}"]',
            )
            for index in range(1, 6)
        ]
        failure = urllib.error.HTTPError(
            "https://touhou.vote/res-be/graphql",
            521,
            "origin down",
            {},
            None,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_root = root / "data_raw" / "cn_official"
            base_path = data_root / "round_10" / "graphql" / "base.json"
            base_path.parent.mkdir(parents=True)
            base_path.write_text("{}", encoding="utf-8")
            output = root / "metadata" / "coverage.json"
            status = root / "metadata" / "status.json"
            with (
                mock.patch.object(entity.core, "WORKSPACE", root),
                mock.patch.object(entity.core, "DATA_ROOT", data_root),
                mock.patch.object(entity, "OUTPUT", output),
                mock.patch.object(entity, "STATUS_PATH", status),
                mock.patch.object(entity.advanced, "build_specs", return_value=specs),
                mock.patch.object(entity, "question_ids", return_value=["q1"]),
                mock.patch.object(entity, "fetch_one", side_effect=failure) as fetch,
            ):
                result = entity.crawl_round(
                    entity.core.ROUNDS[10],
                    object(),
                    resume=True,
                    max_requests=None,
                    transient_failure_threshold=3,
                )
            status_value = json.loads(status.read_text(encoding="utf-8"))

        self.assertEqual(fetch.call_count, 3)
        self.assertTrue(result["transientCircuitOpen"])
        self.assertTrue(result["resumable"])
        self.assertEqual(result["fetchFailed"], 3)
        self.assertEqual(result["pending"], 2)
        self.assertEqual(
            [item["status"] for item in result["records"]],
            ["fetch_failed", "fetch_failed", "fetch_failed", "pending", "pending"],
        )
        self.assertEqual(status_value["state"], "recovery_wait")
        self.assertEqual(status_value["processed"], 3)
        self.assertEqual(status_value["successful"], 0)

    def test_main_does_not_probe_next_modern_round_while_circuit_is_open(self) -> None:
        round_payload = {
            "round": 10,
            "complete": False,
            "expectedResponses": 5,
            "availableCrawled": 0,
            "fetchFailed": 3,
            "pending": 2,
            "transientCircuitOpen": True,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "metadata" / "coverage.json"
            status = root / "metadata" / "status.json"
            data_root = root / "data_raw" / "cn_official"
            with (
                mock.patch.object(entity.core, "WORKSPACE", root),
                mock.patch.object(entity.core, "DATA_ROOT", data_root),
                mock.patch.object(entity, "OUTPUT", output),
                mock.patch.object(entity, "STATUS_PATH", status),
                mock.patch.object(
                    entity,
                    "parse_rounds",
                    return_value=[entity.core.ROUNDS[10], entity.core.ROUNDS[11]],
                ),
                mock.patch.object(entity.core, "PublicClient", return_value=object()),
                mock.patch.object(
                    entity,
                    "crawl_round",
                    return_value=round_payload,
                ) as crawl,
            ):
                result = entity.main(["--rounds", "10,11", "--resume"])
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result, 1)
        self.assertEqual(crawl.call_count, 1)
        self.assertEqual([item["round"] for item in payload["rounds"]], [10])
        self.assertTrue(payload["transientCircuitOpen"])


class ModernAdaptiveSpeedTests(unittest.TestCase):
    def controller(self) -> core.AdaptiveSpeed:
        return core.AdaptiveSpeed(
            workers=3,
            request_limit=30,
            pause=0.5,
            worker_ceiling=8,
            request_limit_ceiling=30,
            pause_ceiling=3.0,
            profile_path=None,
        )

    def test_transient_failures_are_tolerated_then_slow_one_dimension(self) -> None:
        speed = core.AdaptiveSpeed(
            workers=3,
            request_limit=30,
            pause=2.0,
            worker_ceiling=8,
            request_limit_ceiling=30,
            pause_ceiling=3.0,
            profile_path=None,
        )
        speed.workers = 5
        speed.safe_worker_ceiling = 8
        speed.pause = 0.25
        speed.safe_pause_floor = 0.25
        speed.observe(ok=False, transient=True, request_epoch=0)
        first = speed.status()
        speed.observe(ok=False, transient=True, request_epoch=0)
        second = speed.status()
        self.assertEqual((first["adaptiveWorkers"], first["adaptiveBatchPause"]), (5, 0.25))
        self.assertEqual((second["adaptiveWorkers"], second["adaptiveBatchPause"]), (5, 0.25))
        self.assertEqual(second["adaptiveTransientFailures"], 2)

        speed.observe(ok=False, transient=True, request_epoch=0)
        cooldown_step = speed.status()
        self.assertEqual(
            (cooldown_step["adaptiveWorkers"], cooldown_step["adaptiveBatchPause"]),
            (5, 0.75),
        )
        self.assertEqual(cooldown_step["adaptiveTransientFailures"], 0)
        self.assertGreaterEqual(
            cooldown_step["adaptivePauseProbeBlockedSeconds"],
            core.ADAPTIVE_FAILED_PAUSE_PROBE_LOCK_SECONDS - 1.0,
        )

        # Late failures from the operating point that was just replaced are
        # drain evidence and cannot count toward the next slowdown.
        for _ in range(5):
            speed.observe(ok=False, transient=True, request_epoch=0)
        self.assertEqual(speed.status()["adaptiveTransientFailures"], 0)

        def next_failure_group() -> dict:
            epoch = speed.status()["adaptiveControllerEpoch"]
            for _ in range(3):
                speed.observe(ok=False, transient=True, request_epoch=epoch)
            return speed.status()

        self.assertEqual(next_failure_group()["adaptiveBatchPause"], 1.25)
        self.assertEqual(next_failure_group()["adaptiveBatchPause"], 1.75)
        default_cooldown_step = next_failure_group()
        self.assertEqual(
            (default_cooldown_step["adaptiveWorkers"], default_cooldown_step["adaptiveBatchPause"]),
            (5, 2.0),
        )
        worker_step = next_failure_group()
        self.assertEqual(
            (worker_step["adaptiveWorkers"], worker_step["adaptiveBatchPause"]),
            (4, 2.0),
        )
        configured_worker_step = next_failure_group()
        self.assertEqual(
            (configured_worker_step["adaptiveWorkers"], configured_worker_step["adaptiveBatchPause"]),
            (3, 2.0),
        )
        deep_cooldown_step = next_failure_group()
        self.assertEqual(
            (deep_cooldown_step["adaptiveWorkers"], deep_cooldown_step["adaptiveBatchPause"]),
            (3, 2.5),
        )

    def test_recovery_reverses_deep_pause_workers_then_fast_pause(self) -> None:
        speed = core.AdaptiveSpeed(
            workers=3,
            request_limit=30,
            pause=2.0,
            worker_ceiling=5,
            request_limit_ceiling=30,
            pause_ceiling=3.0,
            profile_path=None,
        )
        speed.workers = 3
        speed.safe_worker_ceiling = 3
        speed.pause = 2.5
        speed.safe_pause_floor = 2.5
        clock = mock.Mock(return_value=1000.0)

        def healthy_window() -> dict:
            speed.next_increase_at = clock.return_value
            with mock.patch.object(core.time, "monotonic", clock):
                for _ in range(core.ADAPTIVE_SUCCESS_WINDOW):
                    speed.observe(
                        ok=True,
                        request_epoch=speed.status()["adaptiveControllerEpoch"],
                    )
            clock.return_value += core.ADAPTIVE_HEALTHY_DWELL_SECONDS + 1
            return speed.status()

        self.assertEqual(healthy_window()["adaptiveBatchPause"], 2.25)
        at_default_pause = healthy_window()
        self.assertEqual(
            (at_default_pause["adaptiveWorkers"], at_default_pause["adaptiveBatchPause"]),
            (3, 2.0),
        )
        self.assertEqual(healthy_window()["adaptiveWorkers"], 4)
        at_worker_ceiling = healthy_window()
        self.assertEqual(
            (at_worker_ceiling["adaptiveWorkers"], at_worker_ceiling["adaptiveBatchPause"]),
            (5, 2.0),
        )
        self.assertEqual(healthy_window()["adaptiveBatchPause"], 1.75)

    def test_failed_fast_pause_probe_rolls_back_and_is_temporarily_locked(self) -> None:
        speed = core.AdaptiveSpeed(
            workers=3,
            request_limit=30,
            pause=0.75,
            worker_ceiling=3,
            request_limit_ceiling=30,
            pause_ceiling=3.0,
            profile_path=None,
        )
        monotonic_clock = mock.Mock(return_value=1000.0)
        wall_clock = mock.Mock(return_value=2000.0)
        speed.next_increase_at = monotonic_clock.return_value

        with (
            mock.patch.object(core.time, "monotonic", monotonic_clock),
            mock.patch.object(core.time, "time", wall_clock),
        ):
            for _ in range(core.ADAPTIVE_SUCCESS_WINDOW):
                speed.observe(
                    ok=True,
                    request_epoch=speed.status()["adaptiveControllerEpoch"],
                )
            probe = speed.status()
            self.assertEqual(probe["adaptiveBatchPause"], 0.5)
            self.assertEqual(probe["adaptivePauseRollback"], 0.75)

            probe_epoch = probe["adaptiveControllerEpoch"]
            for _ in range(speed.failure_threshold):
                speed.observe(ok=False, transient=True, request_epoch=probe_epoch)
            rollback = speed.status()
            self.assertEqual(rollback["adaptiveBatchPause"], 0.75)
            self.assertEqual(rollback["adaptivePauseRollback"], 0.0)
            self.assertEqual(
                rollback["adaptivePauseProbeBlockedSeconds"],
                core.ADAPTIVE_FAILED_PAUSE_PROBE_LOCK_SECONDS,
            )

            monotonic_clock.return_value += core.ADAPTIVE_HEALTHY_DWELL_SECONDS + 1
            wall_clock.return_value += core.ADAPTIVE_HEALTHY_DWELL_SECONDS + 1
            rollback_epoch = rollback["adaptiveControllerEpoch"]
            for _ in range(core.ADAPTIVE_SUCCESS_WINDOW):
                speed.observe(ok=True, request_epoch=rollback_epoch)
            locked = speed.status()
            self.assertEqual(locked["adaptiveBatchPause"], 0.75)
            self.assertEqual(locked["adaptiveSuccessStreak"], core.ADAPTIVE_SUCCESS_WINDOW)

            elapsed = core.ADAPTIVE_FAILED_PAUSE_PROBE_LOCK_SECONDS + 1
            monotonic_clock.return_value = 1000.0 + elapsed
            wall_clock.return_value = 2000.0 + elapsed
            speed.observe(ok=True, request_epoch=rollback_epoch)
            retried = speed.status()
            self.assertEqual(retried["adaptiveBatchPause"], 0.5)
            self.assertEqual(retried["adaptivePauseRollback"], 0.75)

    def test_pause_probe_lock_persists_and_restart_uses_stable_pause(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary) / "profiles.json"
            with mock.patch.object(core.time, "time", return_value=2000.0):
                speed = core.AdaptiveSpeed(
                    workers=3,
                    request_limit=30,
                    pause=0.75,
                    worker_ceiling=3,
                    request_limit_ceiling=30,
                    pause_ceiling=3.0,
                    stage_id="stage",
                    profile_path=profile,
                )
                speed.pause = 0.5
                speed.safe_pause_floor = 0.75
                speed.pause_rollback = 0.75
                speed.pause_probe_blocked_until = 2300.0
                speed._persist_profile()

            with mock.patch.object(core.time, "time", return_value=2010.0):
                restored = core.AdaptiveSpeed(
                    workers=3,
                    request_limit=30,
                    pause=0.75,
                    worker_ceiling=3,
                    request_limit_ceiling=30,
                    pause_ceiling=3.0,
                    stage_id="stage",
                    profile_path=profile,
                )
                status = restored.status()

        self.assertEqual(status["adaptiveBatchPause"], 0.75)
        self.assertEqual(status["adaptivePauseRollback"], 0.0)
        self.assertEqual(status["adaptivePauseProbeBlockedSeconds"], 290.0)

    def test_healthy_window_increases_one_worker(self) -> None:
        speed = self.controller()
        clock = mock.Mock(return_value=1000.0)
        speed.next_increase_at = 1000.0
        with mock.patch.object(core.time, "monotonic", clock):
            for _ in range(core.ADAPTIVE_SUCCESS_WINDOW):
                speed.observe(ok=True, request_epoch=0)
        self.assertEqual(speed.status()["adaptiveWorkers"], 4)

    def test_graphql_gateway_decode_retries_count_as_one_tolerated_failure(self) -> None:
        speed = self.controller()
        client = core.PublicClient(
            delay=0,
            retries=3,
            timeout=1,
            adaptive_speed=speed,
        )
        gateway_error = json.dumps(
            {
                "errors": [
                    {
                        "message": "Error",
                        "extensions": {
                            "service": "gateway",
                            "url": "http://result-query/v1/global-stats/",
                            "error_kind": "JSON_DECODE_ERROR",
                            "error_message": "EOF while parsing a value",
                        },
                    }
                ]
            }
        ).encode("utf-8")
        success = json.dumps(
            {"data": {"queryGlobalStats": {"numVote": 12}}}
        ).encode("utf-8")
        response_meta = {"status": 200, "retrievedAt": "now"}
        with mock.patch.object(
            client,
            "_request",
            side_effect=[
                (gateway_error, response_meta),
                (gateway_error, response_meta),
                (success, response_meta),
            ],
        ) as request:
            value = client.graphql(
                "QuestionnairePairCell",
                "query QuestionnairePairCell { value }",
                {"query": "q1=1 AND q2=2"},
            )

        self.assertEqual(request.call_count, 3)
        self.assertEqual(value["data"]["queryGlobalStats"]["numVote"], 12)
        self.assertEqual(speed.status()["adaptiveWorkers"], 3)
        self.assertEqual(speed.status()["adaptiveBatchPause"], 0.5)
        self.assertEqual(speed.status()["adaptiveTransientFailures"], 1)

    def test_clean_success_window_clears_tolerated_failure_evidence(self) -> None:
        speed = self.controller()
        speed.observe(ok=False, transient=True, request_epoch=0)
        for _ in range(core.ADAPTIVE_FAILURE_EVIDENCE_CLEAR_SUCCESSES):
            speed.observe(ok=True, request_epoch=0)
        self.assertEqual(speed.status()["adaptiveTransientFailures"], 0)

    def test_old_profile_is_normalized_to_staged_ladder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary) / "profiles.json"
            profile.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "stages": {
                            "stage": {
                                "adaptive_workers": 7,
                                "adaptive_pause_seconds": 3.5,
                                "adaptive_safe_worker_ceiling": 7,
                                "adaptive_safe_pause_floor": 3.5,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            speed = core.AdaptiveSpeed(
                workers=6,
                request_limit=30,
                pause=2.0,
                worker_ceiling=10,
                request_limit_ceiling=30,
                pause_ceiling=3.0,
                stage_id="stage",
                profile_path=profile,
            )

        self.assertEqual(speed.status()["adaptiveWorkers"], 7)
        self.assertEqual(speed.status()["adaptiveBatchPause"], 2.0)
        self.assertEqual(speed.status()["adaptiveSafePauseFloor"], 2.0)


if __name__ == "__main__":
    unittest.main()
