"""Small standard-library HTTP API and static file server."""

import argparse
import csv
import io
import json
import mimetypes
import re
import signal
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .store import MonitoringStore, Simulator

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
DEFAULT_DATABASE = Path(__file__).resolve().parent.parent / "data" / "pipeguard.db"


class PipeGuardServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: Tuple[str, int], store: MonitoringStore):
        super().__init__(address, RequestHandler)
        self.store = store

    def server_close(self) -> None:
        super().server_close()
        self.store.close()


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

    def _csv(self, rows: List[Dict[str, object]], filename: str) -> None:
        output = io.StringIO()
        columns = [
            "告警编号",
            "级别",
            "告警事件",
            "管线编号",
            "管线名称",
            "状态",
            "工单编号",
            "发生时间",
        ]
        writer = csv.writer(output)
        writer.writerow(columns)
        for alert in rows:
            writer.writerow(
                [
                    alert["id"],
                    alert["level"],
                    alert["title"],
                    alert["pipeline_id"],
                    alert["pipeline_name"],
                    alert["status"],
                    alert.get("work_order_id", ""),
                    alert["created_at"],
                ]
            )
        body = ("\ufeff" + output.getvalue()).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header(
            "Content-Disposition", f'attachment; filename="{filename}"'
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _work_order_csv(
        self, rows: List[Dict[str, object]], filename: str
    ) -> None:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "工单编号", "工单标题", "关联告警", "管线编号", "管线名称",
                "优先级", "状态", "负责人", "创建时间", "要求完成时间",
            ]
        )
        for order in rows:
            writer.writerow(
                [
                    order["id"], order["title"], order["alert_id"],
                    order["pipeline_id"], order["pipeline_name"],
                    order["priority"], order["status"], order["assignee"],
                    order["created_at"], order["due_at"],
                ]
            )
        body = ("\ufeff" + output.getvalue()).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header(
            "Content-Disposition", f'attachment; filename="{filename}"'
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _device_csv(
        self, rows: List[Dict[str, object]], filename: str
    ) -> None:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "设备编号", "设备名称", "类型", "关联管线", "状态",
                "实时读数", "单位", "电量", "信号质量", "通信协议",
                "最后在线", "上次校准", "下次维护",
            ]
        )
        for device in rows:
            writer.writerow(
                [
                    device["id"], device["name"], device["type_name"],
                    device["pipeline_name"], device["status"],
                    device.get("reading", ""), device["unit"],
                    device["battery"], device["signal"], device["protocol"],
                    device["last_seen"], device["calibrated_at"],
                    device["maintenance_due"],
                ]
            )
        body = ("\ufeff" + output.getvalue()).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header(
            "Content-Disposition", f'attachment; filename="{filename}"'
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _inspection_csv(
        self, rows: List[Dict[str, object]], filename: str
    ) -> None:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "巡检编号", "巡检任务", "管线编号", "管线名称", "负责人",
                "优先级", "状态", "计划时间", "开始时间", "完成时间",
                "巡检结论", "巡检记录",
            ]
        )
        for task in rows:
            writer.writerow(
                [
                    task["id"], task["title"], task["pipeline_id"],
                    task["pipeline_name"], task["inspector"], task["priority"],
                    task["status"], task["scheduled_at"],
                    task.get("started_at", ""), task.get("completed_at", ""),
                    task.get("result", ""), task.get("notes", ""),
                ]
            )
        body = ("\ufeff" + output.getvalue()).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header(
            "Content-Disposition", f'attachment; filename="{filename}"'
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        pipeline_match = re.fullmatch(r"/api/pipelines/([A-Za-z0-9-]+)", path)
        if path == "/api/health":
            self._json(
                {
                    "status": "ok",
                    "service": "pipeguard-api",
                    "version": "1.4.0",
                    "database": "connected",
                }
            )
        elif path == "/api/overview":
            self._json(self.server.store.overview())
        elif path == "/api/pipelines":
            self._json({"items": self.server.store.pipelines()})
        elif path == "/api/alerts":
            self._json({"items": self.server.store.alerts()})
        elif path == "/api/work-orders":
            self._json({"items": self.server.store.work_orders()})
        elif path == "/api/devices":
            self._json({"items": self.server.store.devices()})
        elif path == "/api/inspections":
            self._json({"items": self.server.store.inspections()})
        elif path == "/api/analytics":
            self._json(self.server.store.analytics())
        elif path == "/api/database":
            self._json(self.server.store.database_summary())
        elif path == "/api/audit-logs":
            self._json({"items": self.server.store.audit_logs()})
        elif path == "/api/export/alerts.csv":
            self._csv(self.server.store.alerts(), "pipeguard-alerts.csv")
        elif path == "/api/export/work-orders.csv":
            self._work_order_csv(
                self.server.store.work_orders(), "pipeguard-work-orders.csv"
            )
        elif path == "/api/export/devices.csv":
            self._device_csv(
                self.server.store.devices(), "pipeguard-devices.csv"
            )
        elif path == "/api/export/inspections.csv":
            self._inspection_csv(
                self.server.store.inspections(), "pipeguard-inspections.csv"
            )
        elif pipeline_match:
            pipeline = self.server.store.pipeline(pipeline_match.group(1))
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
        alert_match = re.fullmatch(r"/api/alerts/([A-Za-z0-9-]+)/ack", path)
        work_order_match = re.fullmatch(
            r"/api/work-orders/([A-Za-z0-9-]+)/status", path
        )
        device_calibrate_match = re.fullmatch(
            r"/api/devices/([A-Za-z0-9-]+)/calibrate", path
        )
        device_status_match = re.fullmatch(
            r"/api/devices/([A-Za-z0-9-]+)/status", path
        )
        inspection_status_match = re.fullmatch(
            r"/api/inspections/([A-Za-z0-9-]+)/status", path
        )
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
        elif alert_match:
            alert = self.server.store.acknowledge(alert_match.group(1))
            if alert:
                self._json(alert)
            else:
                self._json({"error": "alert_not_found"}, HTTPStatus.NOT_FOUND)
        elif path == "/api/work-orders":
            body = self._body()
            work_order, error = self.server.store.create_work_order(
                str(body.get("alert_id", "")),
                assignee=str(body.get("assignee", "")),
                description=str(body.get("description", "")),
            )
            if error == "alert_not_found":
                self._json({"error": error}, HTTPStatus.NOT_FOUND)
            elif error == "work_order_exists":
                self._json(
                    {"error": error, "work_order": work_order},
                    HTTPStatus.CONFLICT,
                )
            else:
                self._json(work_order, HTTPStatus.CREATED)
        elif work_order_match:
            work_order, error = self.server.store.update_work_order(
                work_order_match.group(1), str(self._body().get("status", ""))
            )
            if error == "work_order_not_found":
                self._json({"error": error}, HTTPStatus.NOT_FOUND)
            elif error:
                self._json({"error": error}, HTTPStatus.CONFLICT)
            else:
                self._json(work_order)
        elif device_calibrate_match:
            device = self.server.store.calibrate_device(
                device_calibrate_match.group(1)
            )
            if device:
                self._json(device)
            else:
                self._json({"error": "device_not_found"}, HTTPStatus.NOT_FOUND)
        elif device_status_match:
            device, error = self.server.store.update_device_status(
                device_status_match.group(1),
                str(self._body().get("status", "")),
            )
            if error == "device_not_found":
                self._json({"error": error}, HTTPStatus.NOT_FOUND)
            elif error:
                self._json({"error": error}, HTTPStatus.BAD_REQUEST)
            else:
                self._json(device)
        elif path == "/api/inspections":
            body = self._body()
            task, error = self.server.store.create_inspection(
                str(body.get("pipeline_id", "")),
                str(body.get("title", "")),
                str(body.get("inspector", "")),
                str(body.get("scheduled_at", "")),
                priority=str(body.get("priority", "medium")),
                notes=str(body.get("notes", "")),
                checklist=body.get("checklist", []),
            )
            if error == "pipeline_not_found":
                self._json({"error": error}, HTTPStatus.NOT_FOUND)
            elif error:
                self._json({"error": error}, HTTPStatus.BAD_REQUEST)
            else:
                self._json(task, HTTPStatus.CREATED)
        elif inspection_status_match:
            body = self._body()
            task, error = self.server.store.update_inspection(
                inspection_status_match.group(1),
                str(body.get("status", "")),
                result=str(body.get("result", "")),
                notes=str(body.get("notes", "")),
            )
            if error == "inspection_not_found":
                self._json({"error": error}, HTTPStatus.NOT_FOUND)
            elif error:
                self._json({"error": error}, HTTPStatus.CONFLICT)
            else:
                self._json(task)
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
    store: Optional[MonitoringStore] = None,
) -> PipeGuardServer:
    return PipeGuardServer((host, port), store or MonitoringStore())


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 PipeGuard 监测平台")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument(
        "--database",
        default=str(DEFAULT_DATABASE),
        help="SQLite 数据库文件路径",
    )
    args = parser.parse_args()

    store = MonitoringStore(database_path=args.database)
    simulator = Simulator(store)
    server = create_server(args.host, args.port, store=store)
    simulator.start()

    def shutdown_handler(_signum: int, _frame: object) -> None:
        # shutdown() cannot be called safely on the serve_forever thread.
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, shutdown_handler)
    print(f"PipeGuard 已启动：http://{args.host}:{args.port}")
    print(f"SQLite 数据库：{args.database}")
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
