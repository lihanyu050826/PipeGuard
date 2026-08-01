import tempfile
import unittest
from pathlib import Path

from pipeguard.store import MonitoringStore


class DatabasePersistenceTests(unittest.TestCase):
    def test_alerts_work_orders_and_audit_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(Path(directory) / "pipeguard-test.db")
            store = MonitoringStore(seed=17, database_path=database_path)
            self.assertTrue(store.simulate_leak("PL-001"))
            alert = next(
                item
                for item in store.alerts()
                if item["pipeline_id"] == "PL-001" and item["status"] == "open"
            )
            order, error = store.create_work_order(
                alert["id"], assignee="数据库测试员"
            )
            self.assertIsNone(error)
            store.close()

            reopened = MonitoringStore(seed=17, database_path=database_path)
            try:
                persisted_alert = next(
                    item for item in reopened.alerts() if item["id"] == alert["id"]
                )
                persisted_order = next(
                    item for item in reopened.work_orders() if item["id"] == order["id"]
                )
                self.assertEqual(persisted_alert["work_order_id"], order["id"])
                self.assertEqual(persisted_alert["status"], "acknowledged")
                self.assertEqual(persisted_order["assignee"], "数据库测试员")
                self.assertGreaterEqual(
                    reopened.database_summary()["tables"][0]["rows"], 96
                )
                actions = {item["action"] for item in reopened.audit_logs()}
                self.assertIn("alert_created", actions)
                self.assertIn("work_order_created", actions)
            finally:
                reopened.close()

    def test_database_summary_reports_persistent_file(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(Path(directory) / "summary.db")
            store = MonitoringStore(seed=3, database_path=database_path)
            try:
                summary = store.database_summary()
                self.assertTrue(summary["persistent"])
                self.assertEqual(summary["engine"], "SQLite")
                self.assertTrue(Path(database_path).exists())
                self.assertGreater(summary["size_bytes"], 0)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
