from __future__ import annotations

import http.client
import json
from pathlib import Path
import threading
import unittest
from unittest import mock

from scripts_pipeline import data_crawl_dashboard as dashboard


class FakeControl:
    def __init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0
        self.restart_calls = 0
        self.rebenchmark_calls: list[tuple[str, float]] = []
        self.restart_ok = True
        self.saved_payloads: list[object] = []

    @staticmethod
    def settings() -> dict[str, object]:
        stage = {
            "workers": 4,
            "delay": 0.5,
            "batchSize": 80,
            "batchPause": 5.0,
            "retries": 5,
            "timeout": 180,
            "transientFailureThreshold": 3,
        }
        return {
            "stages": {
                "cn_legacy_advanced": dict(stage),
                "cn_legacy_remaining": dict(stage),
            },
            "failurePolicy": {"maxConsecutiveStageFailures": 5},
        }

    def status_snapshot(self, *, include_logs: bool) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "generatedAt": "2026-08-19T00:00:00+00:00",
            "queue": {
                "name": "test-queue",
                "status": "running",
                "effectiveStatus": "running",
                "completedStages": ["one"],
                "stageCount": 2,
                "completedStageCount": 1,
                "lastError": None,
                "consecutiveStageFailures": {},
                "totalStageFailures": {},
            },
            "stage": {
                "id": "cn_legacy_advanced",
                "label": "国区第5–9届高级搜索与关联问卷",
                "kind": "crawl",
                "activity": "正在抓取：国区第5届 · 问卷答案两两关联表",
                "description": "test stage",
                "status": "running",
            },
            "processes": {
                "runnerPid": 101,
                "childPid": 202,
                "runnerAlive": True,
                "childAlive": True,
                "stopRequested": False,
            },
            "progress": {
                "status": "active",
                "activityLabel": "国区第5届 · 问卷答案两两关联表",
                "completed": 40,
                "total": 100,
                "remaining": 60,
                "percent": 40.0,
            },
            "tasks": [
                {
                    "index": 1,
                    "id": "one",
                    "label": "已完成任务",
                    "kind": "crawl",
                    "status": "completed",
                    "isCurrent": False,
                    "attempt": 1,
                    "failureCount": 0,
                },
                {
                    "index": 2,
                    "id": "cn_legacy_advanced",
                    "label": "国区第5–9届高级搜索与关联问卷",
                    "kind": "crawl",
                    "status": "running",
                    "isCurrent": True,
                    "attempt": 2,
                    "failureCount": 0,
                    "activity": "正在抓取：国区第5届 · 问卷答案两两关联表",
                },
            ],
            "logs": {"queue": "queue <script>", "stage": "stage log"}
            if include_logs
            else {},
            "settings": self.settings(),
            "controls": {
                "canStart": False,
                "canStop": True,
                "canRestart": True,
                "settingsApplyImmediately": False,
            },
        }

    def start_queue(self) -> dict[str, object]:
        self.start_calls += 1
        return {"ok": True, "action": "started"}

    def request_stop(self) -> dict[str, object]:
        self.stop_calls += 1
        return {"ok": True, "action": "stop_requested"}

    def restart_queue(self, *, timeout: float) -> dict[str, object]:
        self.restart_calls += 1
        return {
            "ok": self.restart_ok,
            "action": "restarted" if self.restart_ok else "restart_failed",
            "timeout": timeout,
        }

    def rebenchmark_stage(
        self, stage_id: str, *, timeout: float
    ) -> dict[str, object]:
        self.rebenchmark_calls.append((stage_id, timeout))
        return {
            "ok": True,
            "action": "rebenchmarked",
            "stageId": stage_id,
        }

    def save_settings(self, payload: object) -> object:
        self.saved_payloads.append(payload)
        return payload


class DashboardServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.control = FakeControl()
        self.token = "offline-test-token"
        self.server = dashboard.create_server(
            port=0,
            control_api=self.control,
            control_token=self.token,
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        supplied = {"Host": f"127.0.0.1:{self.port}", **(headers or {})}
        connection.request(method, path, body=body, headers=supplied)
        response = connection.getresponse()
        result = (
            response.status,
            {key.lower(): value for key, value in response.getheaders()},
            response.read(),
        )
        connection.close()
        return result

    def mutation_headers(self) -> dict[str, str]:
        return {
            "X-Control-Token": self.token,
            "Origin": f"http://127.0.0.1:{self.port}",
            "Content-Type": "application/json",
        }

    def test_index_injects_token_and_strict_security_headers(self) -> None:
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(self.token.encode("ascii"), body)
        self.assertNotIn(b"__CONTROL_TOKEN__", body)
        self.assertEqual(
            headers["content-security-policy"], dashboard.CONTENT_SECURITY_POLICY
        )
        self.assertEqual(headers["x-frame-options"], "DENY")
        self.assertEqual(headers["cache-control"], "no-store, max-age=0")

    def test_only_fixed_static_routes_are_served(self) -> None:
        status, _, body = self.request("GET", "/styles.css")
        self.assertEqual(status, 200)
        self.assertIn(b".page-shell", body)
        status, _, body = self.request("GET", "/eta.js")
        self.assertEqual(status, 200)
        self.assertIn(b"createEstimator", body)
        status, _, _ = self.request("GET", "/styles.css?v=1")
        self.assertEqual(status, 404)
        status, _, _ = self.request("GET", "/../metadata/data_crawl_queue.json")
        self.assertEqual(status, 404)

    def test_status_requires_token_and_returns_bounded_api_shape(self) -> None:
        status, _, _ = self.request("GET", "/api/status")
        self.assertEqual(status, 403)
        status, _, body = self.request(
            "GET",
            "/api/status",
            headers={"X-Control-Token": self.token},
        )
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(
            payload["dashboardApiVersion"], dashboard.DASHBOARD_API_VERSION
        )
        self.assertEqual(payload["data"]["processes"]["runnerPid"], 101)
        self.assertEqual(payload["data"]["logs"]["queue"], "queue <script>")
        self.assertEqual(payload["data"]["tasks"][1]["status"], "running")

    def test_invalid_host_is_rejected_before_static_or_api_access(self) -> None:
        status, _, body = self.request(
            "GET", "/", headers={"Host": "attacker.invalid"}
        )
        self.assertEqual(status, 421)
        self.assertEqual(json.loads(body)["code"], "invalid_host")

    def test_mutation_requires_exact_origin_and_csrf_token(self) -> None:
        body = b"{}"
        status, _, _ = self.request(
            "POST",
            "/api/start",
            body=body,
            headers={
                "Origin": "https://attacker.invalid",
                "X-Control-Token": self.token,
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(status, 403)
        status, _, _ = self.request(
            "POST",
            "/api/start",
            body=body,
            headers={
                "Origin": f"http://127.0.0.1:{self.port}",
                "X-Control-Token": "wrong-token",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(status, 403)
        self.assertEqual(self.control.start_calls, 0)

    def test_start_stop_and_restart_delegate_to_control_core(self) -> None:
        headers = self.mutation_headers()
        status, _, body = self.request(
            "POST", "/api/start", body=b"{}", headers=headers
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["action"], "started")
        status, _, _ = self.request(
            "POST", "/api/stop", body=b"{}", headers=headers
        )
        self.assertEqual(status, 202)
        status, _, _ = self.request(
            "POST", "/api/restart", body=b"{}", headers=headers
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.control.start_calls, 1)
        self.assertEqual(self.control.stop_calls, 1)
        self.assertEqual(self.control.restart_calls, 1)

    def test_rebenchmark_delegates_stage_id_and_returns_result(self) -> None:
        body = json.dumps({"stageId": "cn_legacy_remaining"}).encode("utf-8")

        status, _, response = self.request(
            "POST",
            "/api/rebenchmark",
            body=body,
            headers=self.mutation_headers(),
        )

        self.assertEqual(status, 200)
        self.assertEqual(
            json.loads(response),
            {
                "ok": True,
                "action": "rebenchmarked",
                "stageId": "cn_legacy_remaining",
            },
        )
        self.assertEqual(
            self.control.rebenchmark_calls,
            [("cn_legacy_remaining", 120.0)],
        )

    def test_rebenchmark_rejects_missing_or_blank_stage_without_delegating(self) -> None:
        for payload in ({}, {"stageId": "   "}, {"stageId": 123}):
            with self.subTest(payload=payload):
                status, _, response = self.request(
                    "POST",
                    "/api/rebenchmark",
                    body=json.dumps(payload).encode("utf-8"),
                    headers=self.mutation_headers(),
                )
                self.assertEqual(status, 400)
                self.assertEqual(json.loads(response)["code"], "invalid_stage")
        self.assertEqual(self.control.rebenchmark_calls, [])

    def test_save_and_save_restart_pass_numeric_settings_without_rewriting(self) -> None:
        payload = self.control.settings()
        body = json.dumps(payload).encode("utf-8")
        headers = self.mutation_headers()
        status, _, response = self.request(
            "POST", "/api/settings", body=body, headers=headers
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response)["settings"], payload)
        status, _, response = self.request(
            "POST", "/api/save-and-restart", body=body, headers=headers
        )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(response)["ok"])
        self.assertEqual(self.control.saved_payloads, [payload, payload])
        self.assertEqual(self.control.restart_calls, 1)

    def test_save_restart_failure_reports_that_settings_were_saved(self) -> None:
        self.control.restart_ok = False
        payload = self.control.settings()
        body = json.dumps(payload).encode("utf-8")
        status, _, response = self.request(
            "POST",
            "/api/save-and-restart",
            body=body,
            headers=self.mutation_headers(),
        )
        result = json.loads(response)
        self.assertEqual(status, 409)
        self.assertFalse(result["ok"])
        self.assertTrue(result["settingsSaved"])
        self.assertEqual(result["settings"], payload)
        self.assertIn("配置已保存", result["error"])

    def test_rejects_oversized_body_without_reading_it(self) -> None:
        headers = self.mutation_headers()
        headers["Content-Length"] = str(dashboard.MAX_REQUEST_BYTES + 1)
        status, _, body = self.request(
            "POST", "/api/settings", body=b"", headers=headers
        )
        self.assertEqual(status, 413)
        self.assertEqual(json.loads(body)["code"], "request_too_large")

    def test_running_dashboard_can_be_identified_for_one_click_reuse(self) -> None:
        self.assertTrue(dashboard.existing_dashboard_available(self.port))


class DashboardStaticSafetyTests(unittest.TestCase):
    def test_dynamic_content_uses_text_content_not_html_injection(self) -> None:
        script = (
            Path(dashboard.__file__).resolve().parent / "dashboard" / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn("textContent", script)
        self.assertIn("createElement", script)
        self.assertIn("replaceChildren", script)
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("outerHTML", script)
        self.assertNotIn("insertAdjacentHTML", script)

    def test_large_content_list_reuses_rows_and_reserves_scrollbar_width(self) -> None:
        static_root = Path(dashboard.__file__).resolve().parent / "dashboard"
        script = (static_root / "app.js").read_text(encoding="utf-8")
        styles = (static_root / "styles.css").read_text(encoding="utf-8")
        self.assertIn("function reconcileContentEntries(entries)", script)
        self.assertIn("document.createDocumentFragment()", script)
        self.assertIn("const previousScrollTop = list.scrollTop;", script)
        self.assertIn("list.scrollTop = previousScrollTop;", script)
        self.assertNotIn("elements.contentList.replaceChildren();", script)
        self.assertIn("scrollbar-gutter: stable;", styles)

    def test_rebenchmark_requires_compatible_dashboard_backend(self) -> None:
        script = (
            Path(dashboard.__file__).resolve().parent / "dashboard" / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn("dashboardApiVersion >= REBENCHMARK_API_VERSION", script)
        self.assertIn("控制台后台版本过旧，请重新打开控制台", script)
        self.assertIn('path === "/api/rebenchmark" && status === 404', script)

    def test_current_batch_pause_is_visible_for_configured_and_zero_values(self) -> None:
        script = (
            Path(dashboard.__file__).resolve().parent / "dashboard" / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "const currentPause = adaptivePause === null ? configuredPause : adaptivePause;",
            script,
        )
        self.assertIn("if (currentPause !== null) {", script)
        self.assertNotIn("adaptivePause !== null && adaptivePause > 0", script)
        self.assertIn('label: "当前批间冷却"', script)

    def test_current_batch_pause_labels_auto_and_manual_modes(self) -> None:
        script = (
            Path(dashboard.__file__).resolve().parent / "dashboard" / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn('? [`自动调节`, `起始 ${configuredPause', script)
        self.assertIn(': ["手动固定", "自动调节已关闭"]', script)
        self.assertIn("当前内容安全下限", script)
        self.assertIn("单并发恢复时每次请求均生效", script)

    def test_pythonw_without_stderr_does_not_break_request_logging(self) -> None:
        handler = object.__new__(dashboard.DashboardHandler)
        handler.path = "/"
        with mock.patch.object(dashboard.sys, "stderr", None):
            handler.log_message("ignored %s", "message")

if __name__ == "__main__":
    unittest.main()
