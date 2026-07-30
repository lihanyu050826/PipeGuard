import unittest

from pipeguard.risk import assess_leak_risk


class RiskEngineTests(unittest.TestCase):
    def test_normal_operation_is_low_risk(self):
        result = assess_leak_risk(
            pressure=6.38,
            baseline_pressure=6.4,
            inlet_flow=128,
            outlet_flow=127.3,
            gas_ppm=17,
            vibration=1.2,
        )
        self.assertEqual(result.level, "normal")
        self.assertLess(result.score, 10)
        self.assertIn("正常波动", result.factors[0])

    def test_moderate_anomaly_is_warning(self):
        result = assess_leak_risk(
            pressure=5.75,
            baseline_pressure=6.4,
            inlet_flow=128,
            outlet_flow=112,
            gas_ppm=48,
            vibration=2.2,
        )
        self.assertEqual(result.level, "warning")
        self.assertGreaterEqual(result.score, 35)
        self.assertLess(result.score, 65)

    def test_correlated_anomalies_are_critical(self):
        result = assess_leak_risk(
            pressure=4.9,
            baseline_pressure=6.4,
            inlet_flow=128,
            outlet_flow=101,
            gas_ppm=115,
            vibration=5.8,
        )
        self.assertEqual(result.level, "critical")
        self.assertGreaterEqual(result.score, 65)
        self.assertGreaterEqual(len(result.factors), 3)
        self.assertGreaterEqual(result.confidence, 0.88)

    def test_input_is_safely_clamped(self):
        result = assess_leak_risk(
            pressure=-100,
            baseline_pressure=0,
            inlet_flow=0,
            outlet_flow=-100,
            gas_ppm=10000,
            vibration=100,
        )
        self.assertLessEqual(result.score, 100)
        self.assertGreaterEqual(result.score, 0)


if __name__ == "__main__":
    unittest.main()
