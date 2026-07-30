"""Small standard-library HTTP API and static file server."""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import signal
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .store import MonitoringStore, Simulator

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"


class PipeGuardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], store: MonitoringStore):
        super().__init__(address, RequestHandler)
        self.store = store


class RequestHandler(BaseHTTPRequestHandler):
    server: PipeGuardServer

    def log_message(self, format: str, *args: object) -> None:
        sys.stdout.write(f"[PipeGuard] {self.address_string()} {format % args}\n")

    def _json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json({"status": "ok", "service": "pipeguard-api", "version": "1.0.0"})
        elif path == "/api/overview":
            self._json(self.server.store.overview())
        elif path == "/api/pipelines":
            self._json({"items": self.server.store.pipelines()})
        elif path == "/api/alerts":
            self._json({"items": self.server.store.alerts()})
        elif match := re.fullmatch(r"/api/pipelines/([A-Za-z0-9-]+)", path):
            pipeline = self.server.store.pipeline(match.group(1))
            if pipeline:
                self._json(pipeline)
            else:
                self._json({"error": "pipeline_not_found"}, HTTPStatus.NOT_FOUND)
        elif path.startswith("/api/"):
            self._json({"error": "endpoint_not_found"}, HTTPStatus.NOT_FOUND)
        else:
            self._static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/simulate/leak":
            pipe_id = self._body().get("pipeline_id", "PL-001")
            if self.server.store.simulate_leak(pipe_id):
                self._json(
                    {
                        "message": "泄漏场景已注入",
                        "pipeline_id": pipe_id,
                    },
                    HTTPStatus.ACCEPTED,
                )
            else:
                self._json({"error": "pipeline_not_found"}, HTTPStatus.NOT_FOUND)
        elif match := re.fullmatch(r"/api/alerts/([A-Za-z0-9-]+)/ack", path):
            alert = self.server.store.acknowledge(match.group(1))
            if alert:
                self._json(alert)
            else:
                self._json({"error": "alert_not_found"}, HTTPStatus.NOT_FOUND)
        else:
            self._json({"error": "endpoint_not_found"}, HTTPStatus.NOT_FOUND)

    def _static(self, path: str) -> None:
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        candidate = (WEB_ROOT / relative).resolve()
        if WEB_ROOT not in candidate.parents and candidate != WEB_ROOT:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not candidate.is_file():
            # SPA fallback supports refreshing future client-side routes.
            candidate = WEB_ROOT / "index.html"
        content = candidate.read_bytes()
        content_type, _ = mimetypes.guess_type(candidate.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)


def create_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    *,
    store: MonitoringStore | None = None,
) -> PipeGuardServer:
    return PipeGuardServer((host, port), store or MonitoringStore())


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 PipeGuard 监测平台")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    args = parser.parse_args()

    store = MonitoringStore()
    simulator = Simulator(store)
    server = create_server(args.host, args.port, store=store)
    simulator.start()

    def shutdown_handler(_signum: int, _frame: object) -> None:
        # shutdown() cannot be called safely on the serve_forever thread.
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, shutdown_handler)
    print(f"PipeGuard 已启动：http://{args.host}:{args.port}")
    print("按 Ctrl+C 停止服务")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止 PipeGuard…")
    finally:
        simulator.stop()
        server.server_close()


if __name__ == "__main__":
    main()
