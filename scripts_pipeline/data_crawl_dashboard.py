#!/usr/bin/env python3
"""Loopback-only web dashboard for the durable data-crawl queue.

The service deliberately uses only Python's standard library.  It serves a
small, fixed set of static files and delegates queue operations to
``data_crawl_control``.  Mutating requests require an unguessable per-process
token as well as an exact loopback Host and Origin, so a page opened elsewhere
cannot drive the local crawler.
"""

from __future__ import annotations

import argparse
import html
from http import HTTPStatus
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
from pathlib import Path
import secrets
import sys
import threading
import time
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit
import webbrowser

try:  # Package import in tests; direct import from a command file.
    from . import data_crawl_control as default_control
except ImportError:  # pragma: no cover - exercised when launched directly
    import data_crawl_control as default_control


STATIC_ROOT = Path(__file__).resolve().parent / "dashboard"
MAX_REQUEST_BYTES = 64 * 1024
DASHBOARD_API_VERSION = 2
STATIC_ROUTES: dict[str, tuple[str, str]] = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/eta.js": ("eta.js", "text/javascript; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
API_ROUTES = {
    "/api/status",
    "/api/start",
    "/api/stop",
    "/api/restart",
    "/api/rebenchmark",
    "/api/settings",
    "/api/save-and-restart",
}
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "connect-src 'self'",
        "img-src 'self' data:",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "form-action 'self'",
    )
)


class DashboardServer(ThreadingHTTPServer):
    """HTTP server carrying the private token and queue-control facade."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        control_api: Any,
        control_token: str,
    ) -> None:
        self.control_api = control_api
        self.control_token = control_token
        self.action_lock = threading.Lock()
        self.control_reload_lock = threading.Lock()
        self.control_mtime_ns = self._control_mtime_ns()
        super().__init__(server_address, handler_class)

    def _control_mtime_ns(self) -> int | None:
        if self.control_api is not default_control:
            return None
        module_file = getattr(self.control_api, "__file__", None)
        if not module_file:
            return None
        try:
            return Path(module_file).stat().st_mtime_ns
        except OSError:
            return None

    def refresh_control_module(self) -> None:
        """Reload the local control facade when its source changed.

        A dashboard process can remain open for days while the crawler code is
        updated.  Without this check the page would serve new static assets
        but continue calling an old in-memory ``read_settings`` implementation
        (for example one that still required ``--delay``).
        """

        current_mtime = self._control_mtime_ns()
        if current_mtime is None or current_mtime == self.control_mtime_ns:
            return
        with self.control_reload_lock:
            current_mtime = self._control_mtime_ns()
            if current_mtime is None or current_mtime == self.control_mtime_ns:
                return
            importlib.invalidate_caches()
            importlib.reload(default_control)
            self.control_mtime_ns = self._control_mtime_ns()

    @property
    def allowed_hosts(self) -> frozenset[str]:
        port = self.server_address[1]
        return frozenset((f"127.0.0.1:{port}", f"localhost:{port}"))

    @property
    def allowed_origins(self) -> frozenset[str]:
        port = self.server_address[1]
        return frozenset(
            (f"http://127.0.0.1:{port}", f"http://localhost:{port}")
        )


class DashboardHandler(BaseHTTPRequestHandler):
    """Serve fixed assets and a small authenticated JSON API."""

    protocol_version = "HTTP/1.1"
    server_version = "TouhouCrawlDashboard/1"
    sys_version = ""

    @property
    def dashboard_server(self) -> DashboardServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, format: str, *args: Any) -> None:
        # Keep the console useful: routine one-second status polling is quiet.
        # pythonw deliberately has no stderr; BaseHTTPRequestHandler would
        # otherwise raise before sending every response.
        if self.path != "/api/status" and sys.stderr is not None:
            super().log_message(format, *args)

    def _send_security_headers(self) -> None:
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")

    def _write_response(
        self,
        status: HTTPStatus | int,
        body: bytes,
        content_type: str,
        *,
        head_only: bool = False,
    ) -> None:
        self.send_response(int(status))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        if self.close_connection:
            self.send_header("Connection", "close")
        self._send_security_headers()
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _json_response(
        self,
        status: HTTPStatus | int,
        value: Any,
        *,
        head_only: bool = False,
    ) -> None:
        body = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        self._write_response(
            status,
            body,
            "application/json; charset=utf-8",
            head_only=head_only,
        )

    def _error(
        self,
        status: HTTPStatus | int,
        message: str,
        *,
        code: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        value: dict[str, Any] = {"ok": False, "code": code, "error": message}
        if details:
            value["details"] = dict(details)
        self._json_response(status, value)

    def _path(self) -> str | None:
        parsed = urlsplit(self.path)
        if parsed.query or parsed.fragment:
            return None
        return parsed.path

    def _valid_host(self) -> bool:
        host = self.headers.get("Host", "").strip().lower()
        return host in self.dashboard_server.allowed_hosts

    def _valid_token(self) -> bool:
        supplied = self.headers.get("X-Control-Token", "")
        return bool(supplied) and secrets.compare_digest(
            supplied, self.dashboard_server.control_token
        )

    def _authorize_api(self, *, mutation: bool) -> bool:
        if not self._valid_host():
            if mutation:
                self.close_connection = True
            self._error(
                HTTPStatus.MISDIRECTED_REQUEST,
                "Host 不是本机控制台地址",
                code="invalid_host",
            )
            return False
        if mutation:
            origin = self.headers.get("Origin", "").strip().lower()
            if origin not in self.dashboard_server.allowed_origins:
                self.close_connection = True
                self._error(
                    HTTPStatus.FORBIDDEN,
                    "Origin 校验失败；请从本机控制台操作",
                    code="invalid_origin",
                )
                return False
        if not self._valid_token():
            if mutation:
                self.close_connection = True
            self._error(
                HTTPStatus.FORBIDDEN,
                "控制令牌无效，请刷新控制台",
                code="invalid_token",
            )
            return False
        return True

    def _read_json(self, *, allow_empty: bool = False) -> Any:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            if allow_empty:
                return {}
            raise ValueError("缺少 Content-Length")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Content-Length 无效") from exc
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise OverflowError("请求体超过 64 KiB 限制")
        if length == 0 and allow_empty:
            return {}
        media_type = self.headers.get("Content-Type", "").split(";", 1)[0]
        if media_type.strip().lower() != "application/json":
            raise TypeError("Content-Type 必须是 application/json")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求体不是有效的 UTF-8 JSON") from exc

    def _serve_static(self, path: str, *, head_only: bool) -> None:
        route = STATIC_ROUTES.get(path)
        if route is None:
            self._error(HTTPStatus.NOT_FOUND, "页面不存在", code="not_found")
            return
        filename, content_type = route
        try:
            body = (STATIC_ROOT / filename).read_bytes()
        except OSError:
            self._error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "控制台静态资源缺失",
                code="static_resource_missing",
            )
            return
        if filename == "index.html":
            token = html.escape(self.dashboard_server.control_token, quote=True)
            body = body.replace(b"__CONTROL_TOKEN__", token.encode("ascii"))
        self._write_response(
            HTTPStatus.OK, body, content_type, head_only=head_only
        )

    def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = self._path()
        if path is None or not self._valid_host():
            self._error(
                HTTPStatus.MISDIRECTED_REQUEST,
                "Host 或 URL 无效",
                code="invalid_request_target",
            )
            return
        if path in STATIC_ROUTES:
            self._serve_static(path, head_only=True)
            return
        self._error(HTTPStatus.NOT_FOUND, "页面不存在", code="not_found")

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = self._path()
        if path is None:
            self._error(
                HTTPStatus.NOT_FOUND,
                "不支持带参数的路由",
                code="unknown_route",
            )
            return
        if path in STATIC_ROUTES:
            if not self._valid_host():
                self._error(
                    HTTPStatus.MISDIRECTED_REQUEST,
                    "Host 不是本机控制台地址",
                    code="invalid_host",
                )
                return
            self._serve_static(path, head_only=False)
            return
        if path == "/api/status":
            if not self._authorize_api(mutation=False):
                return
            try:
                self.dashboard_server.refresh_control_module()
                value = self.dashboard_server.control_api.status_snapshot(
                    include_logs=True
                )
            except BaseException as exc:
                self.log_error("status failed: %s: %s", type(exc).__name__, exc)
                self._error(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    f"读取状态失败：{type(exc).__name__}: {exc}",
                    code="status_failed",
                )
                return
            self._json_response(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "dashboardApiVersion": DASHBOARD_API_VERSION,
                    "data": value,
                },
            )
            return
        self._error(HTTPStatus.NOT_FOUND, "接口或页面不存在", code="not_found")

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = self._path()
        if path not in API_ROUTES or path == "/api/status":
            self.close_connection = True
            self._error(HTTPStatus.NOT_FOUND, "接口不存在", code="not_found")
            return
        if not self._authorize_api(mutation=True):
            return
        try:
            payload = self._read_json(
                allow_empty=path in {"/api/start", "/api/stop", "/api/restart"}
            )
        except OverflowError as exc:
            self.close_connection = True
            self._error(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                str(exc),
                code="request_too_large",
            )
            return
        except TypeError as exc:
            self.close_connection = True
            self._error(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                str(exc),
                code="unsupported_media_type",
            )
            return
        except ValueError as exc:
            self.close_connection = True
            self._error(HTTPStatus.BAD_REQUEST, str(exc), code="invalid_json")
            return

        if not self.dashboard_server.action_lock.acquire(blocking=False):
            self._error(
                HTTPStatus.CONFLICT,
                "另一个启停或配置操作仍在执行",
                code="action_in_progress",
            )
            return
        try:
            self._run_action(path, payload)
        finally:
            self.dashboard_server.action_lock.release()

    def _run_action(self, path: str, payload: Any) -> None:
        control = self.dashboard_server.control_api
        try:
            self.dashboard_server.refresh_control_module()
            if path == "/api/start":
                result = control.start_queue()
                status = HTTPStatus.OK if result.get("ok", False) else HTTPStatus.CONFLICT
            elif path == "/api/stop":
                # Signal and return immediately; one-second polling shows shutdown.
                result = control.request_stop()
                status = (
                    HTTPStatus.ACCEPTED
                    if result.get("ok", False)
                    else HTTPStatus.CONFLICT
                )
            elif path == "/api/restart":
                result = control.restart_queue(timeout=120.0)
                status = HTTPStatus.OK if result.get("ok", False) else HTTPStatus.CONFLICT
            elif path == "/api/rebenchmark":
                if not isinstance(payload, Mapping):
                    self._error(
                        HTTPStatus.BAD_REQUEST,
                        "重新测速请求缺少 stageId",
                        code="invalid_stage",
                    )
                    return
                stage_id = payload.get("stageId")
                if not isinstance(stage_id, str) or not stage_id.strip():
                    self._error(
                        HTTPStatus.BAD_REQUEST,
                        "重新测速请求缺少 stageId",
                        code="invalid_stage",
                    )
                    return
                result = control.rebenchmark_stage(stage_id.strip(), timeout=120.0)
                status = HTTPStatus.OK if result.get("ok", False) else HTTPStatus.CONFLICT
            elif path == "/api/settings":
                saved = control.save_settings(payload)
                result = {"ok": True, "action": "settings_saved", "settings": saved}
                status = HTTPStatus.OK
            else:
                saved = control.save_settings(payload)
                restarted = control.restart_queue(timeout=120.0)
                result = {
                    "ok": bool(restarted.get("ok", False)),
                    "action": "settings_saved_and_restarted",
                    "settingsSaved": True,
                    "settings": saved,
                    "restart": restarted,
                }
                if not result["ok"]:
                    result["error"] = (
                        "配置已保存到磁盘，但安全重启失败；请按页面中的错误检查后重试"
                    )
                status = (
                    HTTPStatus.OK
                    if result["ok"]
                    else HTTPStatus.CONFLICT
                )
        except default_control.SettingsValidationError as exc:
            self._error(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "配置校验失败",
                code="settings_validation_failed",
                details=exc.errors,
            )
            return
        except BaseException as exc:
            self.log_error("action failed: %s: %s", type(exc).__name__, exc)
            self._error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"操作失败：{type(exc).__name__}: {exc}",
                code="action_failed",
            )
            return
        self._json_response(status, result)


def create_server(
    *,
    port: int = 8765,
    control_api: Any = default_control,
    control_token: str | None = None,
) -> DashboardServer:
    """Create, but do not start, a loopback dashboard server."""

    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    token = control_token or secrets.token_urlsafe(32)
    if not token or any(character.isspace() for character in token):
        raise ValueError("control token must be non-empty and contain no whitespace")
    return DashboardServer(
        ("127.0.0.1", port),
        DashboardHandler,
        control_api=control_api,
        control_token=token,
    )


def existing_dashboard_available(port: int) -> bool:
    """Return true only when the occupied loopback port is this dashboard."""

    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1.25)
    try:
        connection.request("GET", "/", headers={"Host": f"127.0.0.1:{port}"})
        response = connection.getresponse()
        body = response.read(64 * 1024)
        server_header = response.getheader("Server", "")
        csp = response.getheader("Content-Security-Policy", "")
        return (
            response.status == HTTPStatus.OK
            and "TouhouCrawlDashboard/1" in server_header
            and csp == CONTENT_SECURITY_POLICY
            and b'<meta name="csrf-token"' in body
            and b"__CONTROL_TOKEN__" not in body
        )
    except OSError:
        return False
    finally:
        connection.close()


def _start_queue_for_cli() -> bool:
    try:
        result = default_control.start_queue()
    except BaseException as exc:
        print(
            f"队列自动启动失败：{type(exc).__name__}: {exc}；可在控制台重试。",
            flush=True,
        )
        return False
    action = result.get("action", "unknown")
    if result.get("ok", False):
        print(f"队列启动状态：{action}", flush=True)
        return True
    print(
        f"队列未启动：{action}：{result.get('error', '未知错误')}；"
        "可在控制台检查后重试。",
        flush=True,
    )
    return False


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="open the dashboard in the default browser after binding",
    )
    parser.add_argument(
        "--start-queue",
        action="store_true",
        help="start or resume the queue from its saved settings after binding",
    )
    parser.add_argument(
        "--health-check",
        action="store_true",
        help="wait for an existing dashboard and exit without starting a server",
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=10.0,
        help="maximum wait used by --health-check (default: 10)",
    )
    args = parser.parse_args(argv)
    url = f"http://127.0.0.1:{args.port}/"
    if args.health_check:
        deadline = time.monotonic() + max(0.1, args.wait_seconds)
        while time.monotonic() < deadline:
            if existing_dashboard_available(args.port):
                print(f"爬取控制台健康检查通过：{url}", flush=True)
                return 0
            time.sleep(0.1)
        print(f"爬取控制台健康检查超时：{url}", flush=True)
        return 1
    # Check before binding.  Windows permits two ``SO_REUSEADDR`` listeners
    # on the same loopback port in some configurations; binding first would
    # therefore create a second dashboard instead of reusing the existing one.
    if existing_dashboard_available(args.port):
        print(f"检测到已打开的爬取控制台，复用：{url}", flush=True)
        started = _start_queue_for_cli() if args.start_queue else True
        if args.open_browser:
            webbrowser.open(url, new=2)
        return 0 if started else 1
    try:
        server = create_server(port=args.port)
    except OSError as exc:
        if existing_dashboard_available(args.port):
            print(f"检测到已打开的爬取控制台，复用：{url}", flush=True)
            started = _start_queue_for_cli() if args.start_queue else True
            if args.open_browser:
                webbrowser.open(url, new=2)
            return 0 if started else 1
        parser.error(f"无法绑定 127.0.0.1:{args.port}：{exc}")
    except ValueError as exc:
        parser.error(str(exc))
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    print(f"爬取控制台已启动：{url}", flush=True)
    print("关闭此窗口只会关闭控制台，不会终止正在运行的爬取队列。", flush=True)
    if args.start_queue and not _start_queue_for_cli():
        server.server_close()
        return 1
    if args.open_browser:
        webbrowser.open(url, new=2)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\n控制台已关闭。", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
