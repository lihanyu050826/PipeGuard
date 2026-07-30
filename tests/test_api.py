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


if __name__ == "__main__":
    unittest.main()
