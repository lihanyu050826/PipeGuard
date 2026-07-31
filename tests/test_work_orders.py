import unittest

from pipeguard.store import MonitoringStore


class WorkOrderTests(unittest.TestCase):
    def setUp(self):
        self.store = MonitoringStore(seed=7)

    def test_alert_can_only_create_one_work_order(self):
        order, error = self.store.create_work_order("ALT-0001")
        self.assertEqual(error, "work_order_exists")
        self.assertEqual(order["id"], "WO-0001")

    def test_missing_alert_is_rejected(self):
        order, error = self.store.create_work_order("ALT-NOT-FOUND")
        self.assertIsNone(order)
        self.assertEqual(error, "alert_not_found")

    def test_work_order_cannot_skip_in_progress(self):
        self.store.simulate_leak("PL-001")
        alert = next(
            item
            for item in self.store.alerts()
            if item["pipeline_id"] == "PL-001" and item["status"] == "open"
        )
        order, error = self.store.create_work_order(alert["id"])
        self.assertIsNone(error)

        updated, transition_error = self.store.update_work_order(
            order["id"], "completed"
        )
        self.assertIsNone(updated)
        self.assertEqual(transition_error, "invalid_transition")


if __name__ == "__main__":
    unittest.main()
