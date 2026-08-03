import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from pipeguard.store import MonitoringStore


class DatabasePersistenceTests(unittest.TestCase):
    def test_existing_v1_database_is_upgraded_without_losing_alerts(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(Path(directory) / "legacy.db")
            with closing(sqlite3.connect(database_path)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    INSERT INTO metadata(key, value) VALUES ('schema_version', '1');
                    CREATE TABLE alerts (
                        id TEXT PRIMARY KEY,
                        pipeline_id TEXT NOT NULL,
                        pipeline_name TEXT NOT NULL,
                        level TEXT NOT NULL,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        acknowledged_at TEXT,
                        work_order_id TEXT
                    );
                    INSERT INTO alerts VALUES (
                        'ALT-0099', 'PL-001', '北区输油干线', 'warning',
                        '历史告警', '升级前已存在的记录', 'acknowledged',
                        '2026-08-01T08:00:00+00:00', '2026-08-01T08:05:00+00:00', NULL
                    );
                    """
                )
            store = MonitoringStore(seed=5, database_path=database_path)
            try:
                alert_ids = {item["id"] for item in store.alerts()}
                self.assertIn("ALT-0099", alert_ids)
                self.assertGreaterEqual(len(alert_ids), 9)
                self.assertEqual(len(store.devices()), 15)
                self.assertEqual(len(store.inspections()), 9)
                self.assertEqual(store.database_summary()["schema_version"], "3")
            finally:
                store.close()

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
            device, error = store.update_device_status("GT-002", "offline")
            self.assertIsNone(error)
            self.assertEqual(device["status"], "offline")
            inspection, error = store.create_inspection(
                "PL-002", "持久化巡检测试", "数据库测试员",
                "2026-08-05T08:00:00+00:00", priority="high",
                checklist=["检查阀门", "核对仪表"],
            )
            self.assertIsNone(error)
            started, error = store.update_inspection(
                inspection["id"], "in_progress"
            )
            self.assertIsNone(error)
            self.assertEqual(started["status"], "in_progress")
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
                persisted_device = next(
                    item for item in reopened.devices() if item["id"] == "GT-002"
                )
                self.assertEqual(persisted_device["status"], "offline")
                persisted_inspection = next(
                    item for item in reopened.inspections()
                    if item["id"] == inspection["id"]
                )
                self.assertEqual(persisted_inspection["status"], "in_progress")
                self.assertEqual(persisted_inspection["checklist"], ["检查阀门", "核对仪表"])
                self.assertGreaterEqual(
                    reopened.database_summary()["tables"][0]["rows"], 96
                )
                actions = {item["action"] for item in reopened.audit_logs()}
                self.assertIn("alert_created", actions)
                self.assertIn("work_order_created", actions)
                self.assertIn("device_status_changed", actions)
                self.assertIn("inspection_created", actions)
                self.assertIn("inspection_started", actions)
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
