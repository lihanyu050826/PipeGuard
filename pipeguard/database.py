"""SQLite persistence for PipeGuard.

The module only uses Python's standard library and remains compatible with
Python 3.6. Each write is protected by a re-entrant lock because telemetry is
produced by a background thread while HTTP requests may update alerts and
work orders concurrently.
"""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


SCHEMA_VERSION = "1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """Small repository around one SQLite connection."""

    def __init__(self, path: str = ":memory:") -> None:
        self.path = str(path or ":memory:")
        self._lock = threading.RLock()
        self._closed = False
        if self.path != ":memory:":
            Path(self.path).expanduser().resolve().parent.mkdir(
                parents=True, exist_ok=True
            )
        self._connection = sqlite3.connect(
            self.path, timeout=10, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = NORMAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS alerts (
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

                CREATE TABLE IF NOT EXISTS work_orders (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    pipeline_id TEXT NOT NULL,
                    pipeline_name TEXT NOT NULL,
                    alert_id TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    status TEXT NOT NULL,
                    assignee TEXT NOT NULL,
                    description TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (alert_id) REFERENCES alerts(id)
                );

                CREATE TABLE IF NOT EXISTS telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pipeline_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    pressure REAL NOT NULL,
                    inlet_flow REAL NOT NULL,
                    outlet_flow REAL NOT NULL,
                    temperature REAL NOT NULL,
                    gas_ppm REAL NOT NULL,
                    vibration REAL NOT NULL,
                    risk_score REAL NOT NULL,
                    risk_level TEXT NOT NULL,
                    risk_confidence REAL NOT NULL,
                    risk_factors TEXT NOT NULL,
                    risk_components TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_telemetry_pipeline_time
                    ON telemetry(pipeline_id, id DESC);

                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_audit_created_at
                    ON audit_logs(id DESC);
                """
            )
            self._connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                ("schema_version", SCHEMA_VERSION),
            )

    def initialize(
        self,
        initial_alerts: List[Dict[str, Any]],
        initial_work_orders: List[Dict[str, Any]],
    ) -> None:
        """Seed a newly-created database without overwriting existing data."""

        with self._lock:
            alert_count = self._connection.execute(
                "SELECT COUNT(*) FROM alerts"
            ).fetchone()[0]
            if alert_count:
                return
            with self._connection:
                for alert in initial_alerts:
                    self._insert_alert(alert)
                for order in initial_work_orders:
                    self._insert_work_order(order)
                self._insert_audit(
                    "database_initialized",
                    "system",
                    "PipeGuard",
                    "SQLite 数据库初始化完成，已写入演示告警与工单。",
                )

    def _insert_alert(self, alert: Dict[str, Any]) -> None:
        self._connection.execute(
            """
            INSERT INTO alerts(
                id, pipeline_id, pipeline_name, level, title, description,
                status, created_at, acknowledged_at, work_order_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert["id"], alert["pipeline_id"], alert["pipeline_name"],
                alert["level"], alert["title"], alert["description"],
                alert["status"], alert["created_at"],
                alert.get("acknowledged_at"), alert.get("work_order_id"),
            ),
        )

    def _insert_work_order(self, order: Dict[str, Any]) -> None:
        self._connection.execute(
            """
            INSERT INTO work_orders(
                id, title, pipeline_id, pipeline_name, alert_id, priority,
                status, assignee, description, created_at, due_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order["id"], order["title"], order["pipeline_id"],
                order["pipeline_name"], order["alert_id"], order["priority"],
                order["status"], order["assignee"], order["description"],
                order["created_at"], order["due_at"], order["updated_at"],
            ),
        )

    def load_alerts(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM alerts ORDER BY created_at DESC, id DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def load_work_orders(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM work_orders ORDER BY created_at DESC, id DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def save_alert(self, alert: Dict[str, Any]) -> None:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE alerts SET pipeline_id=?, pipeline_name=?, level=?,
                    title=?, description=?, status=?, created_at=?,
                    acknowledged_at=?, work_order_id=? WHERE id=?
                """,
                (
                    alert["pipeline_id"], alert["pipeline_name"], alert["level"],
                    alert["title"], alert["description"], alert["status"],
                    alert["created_at"], alert.get("acknowledged_at"),
                    alert.get("work_order_id"), alert["id"],
                ),
            )
            if cursor.rowcount == 0:
                self._insert_alert(alert)

    def save_work_order(self, order: Dict[str, Any]) -> None:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE work_orders SET title=?, pipeline_id=?, pipeline_name=?,
                    alert_id=?, priority=?, status=?, assignee=?, description=?,
                    created_at=?, due_at=?, updated_at=? WHERE id=?
                """,
                (
                    order["title"], order["pipeline_id"], order["pipeline_name"],
                    order["alert_id"], order["priority"], order["status"],
                    order["assignee"], order["description"], order["created_at"],
                    order["due_at"], order["updated_at"], order["id"],
                ),
            )
            if cursor.rowcount == 0:
                self._insert_work_order(order)

    def save_telemetry(self, pipeline_id: str, sample: Dict[str, Any]) -> None:
        risk = sample["risk"]
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO telemetry(
                    pipeline_id, timestamp, pressure, inlet_flow, outlet_flow,
                    temperature, gas_ppm, vibration, risk_score, risk_level,
                    risk_confidence, risk_factors, risk_components
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pipeline_id, sample["timestamp"], sample["pressure"],
                    sample["inlet_flow"], sample["outlet_flow"],
                    sample["temperature"], sample["gas_ppm"],
                    sample["vibration"], risk["score"], risk["level"],
                    risk["confidence"],
                    json.dumps(risk["factors"], ensure_ascii=False),
                    json.dumps(risk["components"], ensure_ascii=False),
                ),
            )

    def load_recent_telemetry(
        self, pipeline_id: str, limit: int = 60
    ) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM telemetry WHERE pipeline_id=?
                ORDER BY id DESC LIMIT ?
                """,
                (pipeline_id, max(1, int(limit))),
            ).fetchall()
        samples = []
        for row in reversed(rows):
            samples.append(
                {
                    "timestamp": row["timestamp"],
                    "pressure": row["pressure"],
                    "inlet_flow": row["inlet_flow"],
                    "outlet_flow": row["outlet_flow"],
                    "temperature": row["temperature"],
                    "gas_ppm": row["gas_ppm"],
                    "vibration": row["vibration"],
                    "risk": {
                        "score": row["risk_score"],
                        "level": row["risk_level"],
                        "confidence": row["risk_confidence"],
                        "factors": json.loads(row["risk_factors"]),
                        "components": json.loads(row["risk_components"]),
                    },
                }
            )
        return samples

    def prune_telemetry(self, pipeline_ids: List[str], keep: int = 720) -> None:
        with self._lock, self._connection:
            for pipeline_id in pipeline_ids:
                self._connection.execute(
                    """
                    DELETE FROM telemetry
                    WHERE pipeline_id=? AND id NOT IN (
                        SELECT id FROM telemetry WHERE pipeline_id=?
                        ORDER BY id DESC LIMIT ?
                    )
                    """,
                    (pipeline_id, pipeline_id, max(60, int(keep))),
                )

    def _insert_audit(
        self, action: str, entity_type: str, entity_id: str, detail: str
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO audit_logs(action, entity_type, entity_id, detail, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (action, entity_type, entity_id, detail, utc_now()),
        )

    def add_audit(
        self, action: str, entity_type: str, entity_id: str, detail: str
    ) -> None:
        with self._lock, self._connection:
            self._insert_audit(action, entity_type, entity_id, detail)

    def audit_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def summary(self) -> Dict[str, Any]:
        descriptions = {
            "telemetry": "历史遥测采样",
            "alerts": "风险告警事件",
            "work_orders": "运维处置工单",
            "audit_logs": "系统操作审计",
        }
        tables = []
        with self._lock:
            for name in ("telemetry", "alerts", "work_orders", "audit_logs"):
                count = self._connection.execute(
                    "SELECT COUNT(*) FROM " + name
                ).fetchone()[0]
                tables.append(
                    {"name": name, "rows": count, "description": descriptions[name]}
                )
            last_row = self._connection.execute(
                "SELECT MAX(timestamp) FROM telemetry"
            ).fetchone()[0]
            sqlite_version = self._connection.execute(
                "SELECT sqlite_version()"
            ).fetchone()[0]
        size_bytes = 0
        if self.path != ":memory:":
            file_path = Path(self.path)
            if file_path.exists():
                size_bytes = file_path.stat().st_size
        return {
            "engine": "SQLite",
            "sqlite_version": sqlite_version,
            "schema_version": SCHEMA_VERSION,
            "persistent": self.path != ":memory:",
            "location": "内存测试数据库" if self.path == ":memory:" else self.path,
            "size_bytes": size_bytes,
            "retention_per_pipeline": 720,
            "last_telemetry_at": last_row,
            "tables": tables,
        }

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True
