import json
import threading
import unittest
import urllib.error
import urllib.request

from pipeguard.server import create_server
from pipeguard.store import MonitoringStore


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = MonitoringStore(seed=42)
        cls.server = create_server("127.0.0.1", 0, store=cls.store)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, path, *, method="GET", payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            method=method,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read())

    def test_health(self):
        status, body = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["version"], "1.3.0")
        self.assertEqual(body["database"], "connected")

    def test_overview_contains_three_pipelines(self):
        _, body = self.request("/api/overview")
        self.assertEqual(body["metrics"]["pipeline_count"], 3)
        self.assertEqual(len(body["pipelines"]), 3)

    def test_pipeline_detail_has_history(self):
        _, body = self.request("/api/pipelines/PL-001")
        self.assertEqual(body["id"], "PL-001")
        self.assertGreaterEqual(len(body["history"]), 30)
        self.assertIn("risk", body["telemetry"])

    def test_missing_pipeline_returns_404(self):
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request("/api/pipelines/DOES-NOT-EXIST")
        self.assertEqual(context.exception.code, 404)

    def test_simulated_leak_creates_alert_and_can_be_acknowledged(self):
        status, body = self.request(
            "/api/simulate/leak",
            method="POST",
            payload={"pipeline_id": "PL-001"},
        )
        self.assertEqual(status, 202)
        self.assertEqual(body["pipeline_id"], "PL-001")

        _, detail = self.request("/api/pipelines/PL-001")
        self.assertEqual(detail["telemetry"]["risk"]["level"], "critical")

        _, alerts = self.request("/api/alerts")
        alert = next(
            item for item in alerts["items"]
            if item["pipeline_id"] == "PL-001" and item["status"] == "open"
        )
        _, acknowledged = self.request(
            f"/api/alerts/{alert['id']}/ack",
            method="POST",
            payload={},
        )
        self.assertEqual(acknowledged["status"], "acknowledged")
        self.assertIsNotNone(acknowledged["acknowledged_at"])

        status, order = self.request(
            "/api/work-orders",
            method="POST",
            payload={"alert_id": alert["id"], "assignee": "测试运维员"},
        )
        self.assertEqual(status, 201)
        self.assertEqual(order["status"], "pending")
        self.assertEqual(order["alert_id"], alert["id"])
        self.assertEqual(order["assignee"], "测试运维员")

        _, in_progress = self.request(
            f"/api/work-orders/{order['id']}/status",
            method="POST",
            payload={"status": "in_progress"},
        )
        self.assertEqual(in_progress["status"], "in_progress")

        _, completed = self.request(
            f"/api/work-orders/{order['id']}/status",
            method="POST",
            payload={"status": "completed"},
        )
        self.assertEqual(completed["status"], "completed")

        _, alerts_after = self.request("/api/alerts")
        resolved = next(item for item in alerts_after["items"] if item["id"] == alert["id"])
        self.assertEqual(resolved["status"], "resolved")

    def test_analytics_summarizes_operations(self):
        _, body = self.request("/api/analytics")
        self.assertIn("risk", body)
        self.assertIn("alerts", body)
        self.assertIn("work_orders", body)
        self.assertGreaterEqual(body["work_orders"]["total"], 2)
        self.assertGreaterEqual(body["alerts"]["closure_rate"], 0)

    def test_database_and_audit_endpoints(self):
        _, database = self.request("/api/database")
        self.assertEqual(database["engine"], "SQLite")
        self.assertEqual(database["schema_version"], "2")
        table_names = {table["name"] for table in database["tables"]}
        self.assertEqual(
            table_names,
            {"telemetry", "alerts", "work_orders", "devices", "audit_logs"},
        )

        _, audit_logs = self.request("/api/audit-logs")
        self.assertGreaterEqual(len(audit_logs["items"]), 1)

    def test_device_management_updates_metrics_alerts_and_audit(self):
        _, devices = self.request("/api/devices")
        self.assertEqual(len(devices["items"]), 12)
        device = next(item for item in devices["items"] if item["id"] == "PT-001")
        self.assertEqual(device["status"], "online")
        self.assertIsNotNone(device["reading"])

        _, offline = self.request(
            "/api/devices/PT-001/status",
            method="POST",
            payload={"status": "offline"},
        )
        self.assertEqual(offline["status"], "offline")
        self.assertIsNone(offline["reading"])
        _, overview = self.request("/api/overview")
        self.assertEqual(overview["metrics"]["online_devices"], 11)
        _, alerts = self.request("/api/alerts")
        self.assertTrue(
            any(item["title"] == "设备 PT-001 通信中断" for item in alerts["items"])
        )

        _, online = self.request(
            "/api/devices/PT-001/status",
            method="POST",
            payload={"status": "online"},
        )
        self.assertEqual(online["status"], "online")
        _, calibrated = self.request(
            "/api/devices/PT-001/calibrate", method="POST", payload={}
        )
        self.assertFalse(calibrated["calibration_due"])
        _, audit_logs = self.request("/api/audit-logs")
        actions = {item["action"] for item in audit_logs["items"]}
        self.assertIn("device_status_changed", actions)
        self.assertIn("device_calibrated", actions)

    def test_alert_export_is_utf8_csv(self):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/export/alerts.csv"
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            body = response.read()
            self.assertEqual(response.status, 200)
            self.assertTrue(response.headers["Content-Type"].startswith("text/csv"))
            self.assertTrue(body.startswith(b"\xef\xbb\xbf"))
            self.assertIn("告警编号", body.decode("utf-8-sig"))

    def test_work_order_export_is_utf8_csv(self):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/export/work-orders.csv"
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            body = response.read()
            self.assertEqual(response.status, 200)
            self.assertTrue(response.headers["Content-Type"].startswith("text/csv"))
            self.assertTrue(body.startswith(b"\xef\xbb\xbf"))
            self.assertIn("工单编号", body.decode("utf-8-sig"))

    def test_device_export_is_utf8_csv(self):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/export/devices.csv"
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            body = response.read()
            self.assertEqual(response.status, 200)
            self.assertTrue(body.startswith(b"\xef\xbb\xbf"))
            self.assertIn("设备编号", body.decode("utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
