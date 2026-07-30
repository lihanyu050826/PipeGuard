"""Explainable multi-sensor leak risk assessment."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RiskResult:
    """Result produced by the fusion algorithm."""

    score: float
    level: str
    confidence: float
    factors: list[str]
    components: dict[str, float]

    def to_dict(self) -> dict:
        return asdict(self)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def assess_leak_risk(
    *,
    pressure: float,
    baseline_pressure: float,
    inlet_flow: float,
    outlet_flow: float,
    gas_ppm: float,
    vibration: float,
) -> RiskResult:
    """Fuse four independent signals into a 0-100 explainable risk score.

    The implementation is intentionally transparent for teaching purposes.
    A production system would learn weights and thresholds from site data.
    """

    safe_pressure = max(baseline_pressure, 0.01)
    safe_inlet = max(inlet_flow, 0.01)

    pressure_drop = _clamp((baseline_pressure - pressure) / safe_pressure / 0.25)
    flow_imbalance = _clamp((inlet_flow - outlet_flow) / safe_inlet / 0.20)
    gas_anomaly = _clamp((gas_ppm - 20.0) / 100.0)
    vibration_anomaly = _clamp((vibration - 1.5) / 5.0)

    components = {
        "pressure": round(pressure_drop * 100, 1),
        "flow": round(flow_imbalance * 100, 1),
        "gas": round(gas_anomaly * 100, 1),
        "vibration": round(vibration_anomaly * 100, 1),
    }

    weighted = (
        pressure_drop * 0.34
        + flow_imbalance * 0.36
        + gas_anomaly * 0.20
        + vibration_anomaly * 0.10
    )

    # Correlated pressure and mass-balance anomalies are more convincing
    # than either signal alone.
    correlation_boost = 0.0
    if pressure_drop > 0.45 and flow_imbalance > 0.45:
        correlation_boost = 0.13
    elif pressure_drop > 0.25 and flow_imbalance > 0.25:
        correlation_boost = 0.06

    score = round(_clamp(weighted + correlation_boost) * 100, 1)
    if score >= 65:
        level = "critical"
    elif score >= 35:
        level = "warning"
    else:
        level = "normal"

    factors: list[str] = []
    if pressure_drop >= 0.25:
        factors.append("管内压力较基线明显下降")
    if flow_imbalance >= 0.25:
        factors.append("进出口流量出现不平衡")
    if gas_anomaly >= 0.25:
        factors.append("可燃气体浓度升高")
    if vibration_anomaly >= 0.25:
        factors.append("管道振动偏离正常范围")
    if not factors:
        factors.append("各项监测指标处于正常波动范围")

    active_signals = sum(
        value >= 0.25
        for value in (pressure_drop, flow_imbalance, gas_anomaly, vibration_anomaly)
    )
    # Agreement among signals is high both when all signals are normal and
    # when several signals are anomalous. A lone abnormal signal is less
    # conclusive and therefore receives lower confidence.
    confidence_by_signal_count = {
        0: 0.94,
        1: 0.72,
        2: 0.82,
        3: 0.90,
        4: 0.97,
    }
    confidence = confidence_by_signal_count[active_signals]

    return RiskResult(score, level, confidence, factors, components)
