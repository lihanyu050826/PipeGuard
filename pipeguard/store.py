"""Thread-safe in-memory data store and telemetry simulator."""

from __future__ import annotations

import math
import random
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from .risk import assess_leak_risk


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


PIPELINES: list[dict[str, Any]] = [
    {
        "id": "PL-001",
        "name": "北区输油干线",
        "medium": "原油",
        "length": 36.8,
        "location": "北区站—河西阀室",
        "baseline_pressure": 6.40,
        "baseline_flow": 128.0,
        "temperature": 28.6,
    },
    {
        "id": "PL-002",
        "name": "东区天然气支线",
        "medium": "天然气",
        "length": 24.5,
        "location": "东区站—工业园",
        "baseline_pressure": 5.80,
        "baseline_flow": 102.0,
        "temperature": 24.2,
    },
    {
        "id": "PL-003",
        "name": "南区成品油管线",
        "medium": "成品油",
        "length": 18.2,
        "location": "南区站—储备库",
        "baseline_pressure": 6.10,
        "baseline_flow": 116.0,
        "temperature": 26.4,
    },
]


class MonitoringStore:
    """Owns live snapshots, histories and alert lifecycle."""

    def __init__(self, *, seed: int | None = None) -> None:
        self._lock = threading.RLock()
        self._random = random.Random(seed)
        self._tick = 0
        self._alert_seq = 2
        self._work_order_seq = 2
        self._leak_ticks: dict[str, int] = {}
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._history: dict[str, deque[dict[str, Any]]] = {
            pipeline["id"]: deque(maxlen=60) for pipeline in PIPELINES
        }
        self._alerts: list[dict[str, Any]] = [
            {
                "id": "ALT-0002",
                "pipeline_id": "PL-002",
                "pipeline_name": "东区天然气支线",
                "level": "warning",
                "title": "振动传感器短时波动",
                "description": "边缘节点检测到 3.2 mm/s 瞬时振动，现已恢复。",
                "status": "resolved",
                "created_at": utc_now(),
                "acknowledged_at": utc_now(),
            },
            {
                "id": "ALT-0001",
                "pipeline_id": "PL-003",
                "pipeline_name": "南区成品油管线",
                "level": "warning",
                "title": "出口流量轻微偏低",
                "description": "质量守恒偏差持续 45 秒，建议例行检查流量计。",
                "status": "acknowledged",
                "created_at": utc_now(),
                "acknowledged_at": utc_now(),
            },
        ]
        self._work_orders: list[dict[str, Any]] = [
            {
                "id": "WO-0002",
                "title": "东区振动传感器复核",
                "pipeline_id": "PL-002",
                "pipeline_name": "东区天然气支线",
                "alert_id": "ALT-0002",
                "priority": "medium",
                "status": "completed",
                "assignee": "王工",
                "description": "复核振动传感器安装状态并检查历史波形。",
                "created_at": utc_now(),
                "due_at": (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat(
                    timespec="seconds"
                ),
                "updated_at": utc_now(),
            },
            {
                "id": "WO-0001",
                "title": "南区流量计现场校验",
                "pipeline_id": "PL-003",
                "pipeline_name": "南区成品油管线",
                "alert_id": "ALT-0001",
                "priority": "high",
                "status": "in_progress",
                "assignee": "李工",
                "description": "校验出口流量计零点，检查阀门与管段是否存在异常。",
                "created_at": utc_now(),
                "due_at": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(
                    timespec="seconds"
                ),
                "updated_at": utc_now(),
            },
        ]
        self._alerts[0]["work_order_id"] = "WO-0002"
        self._alerts[1]["work_order_id"] = "WO-0001"
        for _ in range(32):
            self.advance()

    def advance(self) -> None:
        """Generate one sample for every pipeline."""

        with self._lock:
            self._tick += 1
            for index, pipeline in enumerate(PIPELINES):
                pipe_id = pipeline["id"]
                phase = self._tick / 7.0 + index * 1.7
                leak_strength = 0.0
                if self._leak_ticks.get(pipe_id, 0) > 0:
                    remaining = self._leak_ticks[pipe_id]
                    leak_strength = min(1.0, (121 - remaining) / 22.0 + 0.22)
                    self._leak_ticks[pipe_id] = remaining - 1
                    if remaining <= 1:
                        del self._leak_ticks[pipe_id]

                jitter = self._random.uniform(-0.012, 0.012)
                pressure = pipeline["baseline_pressure"] * (
                    1.0 + math.sin(phase) * 0.008 + jitter - leak_strength * 0.22
                )
                inlet = pipeline["baseline_flow"] * (
                    1.0 + math.cos(phase * 0.8) * 0.012
                    + self._random.uniform(-0.006, 0.006)
                )
                outlet = inlet * (
                    0.992
                    + self._random.uniform(-0.004, 0.004)
                    - leak_strength * 0.18
                )
                temperature = pipeline["temperature"] + math.sin(phase * 0.25) * 0.8
                gas_ppm = 16 + self._random.uniform(-3, 4) + leak_strength * 108
                vibration = 1.1 + self._random.uniform(-0.18, 0.25) + leak_strength * 4.8

                risk = assess_leak_risk(
                    pressure=pressure,
                    baseline_pressure=pipeline["baseline_pressure"],
                    inlet_flow=inlet,
                    outlet_flow=outlet,
                    gas_ppm=gas_ppm,
                    vibration=vibration,
                )
                sample = {
                    "timestamp": utc_now(),
                    "pressure": round(pressure, 2),
                    "inlet_flow": round(inlet, 1),
                    "outlet_flow": round(outlet, 1),
                    "temperature": round(temperature, 1),
                    "gas_ppm": round(gas_ppm, 1),
                    "vibration": round(vibration, 2),
                    "risk": risk.to_dict(),
                }
                previous = self._snapshots.get(pipe_id)
                self._snapshots[pipe_id] = sample
                self._history[pipe_id].append(sample)

                if (
                    risk.level == "critical"
                    and (not previous or previous["risk"]["level"] != "critical")
                ):
                    self._create_alert(pipeline, risk, sample)

    def _create_alert(self, pipeline: dict, risk: Any, sample: dict) -> None:
        self._alert_seq += 1
        self._alerts.insert(
            0,
            {
                "id": f"ALT-{self._alert_seq:04d}",
                "pipeline_id": pipeline["id"],
                "pipeline_name": pipeline["name"],
                "level": "critical",
                "title": "疑似管道泄漏",
                "description": (
                    f"融合风险 {risk.score:.0f} 分；压力 {sample['pressure']} MPa，"
                    f"进出口流量差 {sample['inlet_flow'] - sample['outlet_flow']:.1f} m³/h。"
                ),
                "status": "open",
                "created_at": utc_now(),
                "acknowledged_at": None,
            },
        )

    def overview(self) -> dict[str, Any]:
        with self._lock:
            pipelines = self.pipelines()
            open_alerts = sum(
                alert["status"] == "open" for alert in self._alerts
            )
            online = len(pipelines) * 4
            return {
                "system_name": "PipeGuard",
                "updated_at": utc_now(),
                "metrics": {
                    "pipeline_count": len(pipelines),
                    "monitored_length": round(sum(p["length"] for p in pipelines), 1),
                    "online_devices": online,
                    "device_total": online,
                    "open_alerts": open_alerts,
                    "availability": 99.8,
                },
                "pipelines": pipelines,
            }

    def pipelines(self) -> list[dict[str, Any]]:
        with self._lock:
            result = []
            for pipeline in PIPELINES:
                live = self._snapshots[pipeline["id"]]
                result.append(
                    {
                        **pipeline,
                        "status": live["risk"]["level"],
                        "telemetry": live,
                    }
                )
            return result

    def pipeline(self, pipe_id: str) -> dict[str, Any] | None:
        with self._lock:
            pipeline = next((p for p in PIPELINES if p["id"] == pipe_id), None)
            if not pipeline:
                return None
            return {
                **pipeline,
                "status": self._snapshots[pipe_id]["risk"]["level"],
                "telemetry": self._snapshots[pipe_id],
                "history": list(self._history[pipe_id]),
            }

    def alerts(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(alert) for alert in self._alerts]

    def work_orders(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(work_order) for work_order in self._work_orders]

    def create_work_order(
        self,
        alert_id: str,
        *,
        assignee: str = "值班运维组",
        description: str = "",
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Create one work order from an alert.

        The tuple contains the order and an optional conflict reason.
        """

        with self._lock:
            alert = next((item for item in self._alerts if item["id"] == alert_id), None)
            if not alert:
                return None, "alert_not_found"
            if alert.get("work_order_id"):
                existing = next(
                    (
                        item
                        for item in self._work_orders
                        if item["id"] == alert["work_order_id"]
                    ),
                    None,
                )
                return (dict(existing) if existing else None), "work_order_exists"

            self._work_order_seq += 1
            priority = "urgent" if alert["level"] == "critical" else "high"
            due_hours = 2 if priority == "urgent" else 8
            now = datetime.now(timezone.utc)
            work_order = {
                "id": f"WO-{self._work_order_seq:04d}",
                "title": f"{alert['pipeline_name']}异常处置",
                "pipeline_id": alert["pipeline_id"],
                "pipeline_name": alert["pipeline_name"],
                "alert_id": alert["id"],
                "priority": priority,
                "status": "pending",
                "assignee": assignee.strip() or "值班运维组",
                "description": description.strip() or alert["description"],
                "created_at": now.isoformat(timespec="seconds"),
                "due_at": (now + timedelta(hours=due_hours)).isoformat(
                    timespec="seconds"
                ),
                "updated_at": now.isoformat(timespec="seconds"),
            }
            self._work_orders.insert(0, work_order)
            alert["work_order_id"] = work_order["id"]
            if alert["status"] == "open":
                alert["status"] = "acknowledged"
                alert["acknowledged_at"] = utc_now()
            return dict(work_order), None

    def update_work_order(
        self, work_order_id: str, status: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        allowed = {
            "pending": {"in_progress"},
            "in_progress": {"completed"},
            "completed": set(),
        }
        if status not in allowed:
            return None, "invalid_status"
        with self._lock:
            work_order = next(
                (item for item in self._work_orders if item["id"] == work_order_id),
                None,
            )
            if not work_order:
                return None, "work_order_not_found"
            current = work_order["status"]
            if status == current:
                return dict(work_order), None
            if status not in allowed[current]:
                return None, "invalid_transition"
            work_order["status"] = status
            work_order["updated_at"] = utc_now()
            if status == "completed":
                alert = next(
                    (
                        item
                        for item in self._alerts
                        if item["id"] == work_order["alert_id"]
                    ),
                    None,
                )
                if alert:
                    alert["status"] = "resolved"
            return dict(work_order), None

    def analytics(self) -> dict[str, Any]:
        with self._lock:
            risk_scores = [
                self._snapshots[pipeline["id"]]["risk"]["score"]
                for pipeline in PIPELINES
            ]
            status_counts = {
                status: sum(order["status"] == status for order in self._work_orders)
                for status in ("pending", "in_progress", "completed")
            }
            alert_counts = {
                level: sum(alert["level"] == level for alert in self._alerts)
                for level in ("warning", "critical")
            }
            completed = status_counts["completed"]
            return {
                "generated_at": utc_now(),
                "risk": {
                    "average": round(sum(risk_scores) / len(risk_scores), 1),
                    "maximum": round(max(risk_scores), 1),
                    "healthy_pipelines": sum(score < 35 for score in risk_scores),
                },
                "alerts": {
                    "total": len(self._alerts),
                    "by_level": alert_counts,
                    "closure_rate": round(
                        sum(alert["status"] == "resolved" for alert in self._alerts)
                        / max(1, len(self._alerts))
                        * 100,
                        1,
                    ),
                },
                "work_orders": {
                    "total": len(self._work_orders),
                    "by_status": status_counts,
                    "completion_rate": round(
                        completed / max(1, len(self._work_orders)) * 100, 1
                    ),
                },
            }

    def acknowledge(self, alert_id: str) -> dict[str, Any] | None:
        with self._lock:
            for alert in self._alerts:
                if alert["id"] == alert_id:
                    if alert["status"] == "open":
                        alert["status"] = "acknowledged"
                        alert["acknowledged_at"] = utc_now()
                    return dict(alert)
        return None

    def simulate_leak(self, pipe_id: str) -> bool:
        with self._lock:
            if not any(p["id"] == pipe_id for p in PIPELINES):
                return False
            self._leak_ticks[pipe_id] = 120
            # Advance enough to make the effect immediately visible.
            for _ in range(16):
                self.advance()
            return True


class Simulator:
    """Runs the store at a fixed sampling interval."""

    def __init__(self, store: MonitoringStore, interval: float = 2.0) -> None:
        self.store = store
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self.store.advance()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval + 0.5)
