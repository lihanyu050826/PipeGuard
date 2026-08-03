"""Thread-safe monitoring state backed by SQLite persistence."""

import math
import random
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

from .database import Database
from .risk import assess_leak_risk


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


PIPELINES = [  # type: List[Dict[str, Any]]
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

DEVICE_TYPES = [  # type: List[Dict[str, str]]
    {
        "type_code": "PT",
        "type_name": "压力变送器",
        "metric_key": "pressure",
        "unit": "MPa",
        "range_text": "0–10 MPa",
        "accuracy": "±0.25% FS",
        "protocol": "HART",
    },
    {
        "type_code": "FT",
        "type_name": "超声波流量计",
        "metric_key": "outlet_flow",
        "unit": "m³/h",
        "range_text": "0–200 m³/h",
        "accuracy": "±0.5%",
        "protocol": "Modbus RTU",
    },
    {
        "type_code": "GT",
        "type_name": "可燃气体探测器",
        "metric_key": "gas_ppm",
        "unit": "ppm",
        "range_text": "0–1000 ppm",
        "accuracy": "±3% FS",
        "protocol": "MQTT",
    },
    {
        "type_code": "VT",
        "type_name": "振动传感器",
        "metric_key": "vibration",
        "unit": "mm/s",
        "range_text": "0–20 mm/s",
        "accuracy": "±0.1 mm/s",
        "protocol": "MQTT",
    },
    {
        "type_code": "TT",
        "type_name": "温度变送器",
        "metric_key": "temperature",
        "unit": "℃",
        "range_text": "-20–120 ℃",
        "accuracy": "±0.3 ℃",
        "protocol": "Modbus RTU",
    },
]


class MonitoringStore:
    """Owns live snapshots and coordinates persistent business state."""

    def __init__(
        self, *, seed: Optional[int] = None, database_path: Optional[str] = None
    ) -> None:
        self._lock = threading.RLock()
        self._random = random.Random(seed)
        self._database = Database(database_path or ":memory:")
        self._tick = 0
        self._leak_ticks = {}  # type: Dict[str, int]
        self._snapshots = {}  # type: Dict[str, Dict[str, Any]]
        self._history = {  # type: Dict[str, Deque[Dict[str, Any]]]
            pipeline["id"]: deque(maxlen=60) for pipeline in PIPELINES
        }
        now = datetime.now(timezone.utc)
        initial_alerts = [  # type: List[Dict[str, Any]]
            {
                "id": "ALT-0002",
                "pipeline_id": "PL-002",
                "pipeline_name": "东区天然气支线",
                "level": "warning",
                "title": "振动传感器短时波动",
                "description": "边缘节点检测到 3.2 mm/s 瞬时振动，现已恢复。",
                "status": "resolved",
                "created_at": (now - timedelta(days=3)).isoformat(timespec="seconds"),
                "acknowledged_at": (now - timedelta(days=3, minutes=-8)).isoformat(timespec="seconds"),
                "work_order_id": "WO-0002",
            },
            {
                "id": "ALT-0001",
                "pipeline_id": "PL-003",
                "pipeline_name": "南区成品油管线",
                "level": "warning",
                "title": "出口流量轻微偏低",
                "description": "质量守恒偏差持续 45 秒，建议例行检查流量计。",
                "status": "acknowledged",
                "created_at": (now - timedelta(days=2)).isoformat(timespec="seconds"),
                "acknowledged_at": (now - timedelta(days=2, minutes=-12)).isoformat(timespec="seconds"),
                "work_order_id": "WO-0001",
            },
            {
                "id": "ALT-DEMO-0003",
                "pipeline_id": "PL-003",
                "pipeline_name": "南区成品油管线",
                "level": "warning",
                "title": "南区阀室后备电池电量偏低",
                "description": "边缘节点上报后备电池剩余 18%，建议在本周巡检中完成更换。",
                "status": "acknowledged",
                "created_at": (now - timedelta(days=1, hours=4)).isoformat(timespec="seconds"),
                "acknowledged_at": (now - timedelta(days=1, hours=3, minutes=45)).isoformat(timespec="seconds"),
                "work_order_id": "WO-DEMO-0003",
            },
            {
                "id": "ALT-DEMO-0004",
                "pipeline_id": "PL-002",
                "pipeline_name": "东区天然气支线",
                "level": "warning",
                "title": "东区入口压力短时波动",
                "description": "入口压力在五分钟内出现两次轻微波动，现场复核后确认由调压作业引起。",
                "status": "resolved",
                "created_at": (now - timedelta(days=1)).isoformat(timespec="seconds"),
                "acknowledged_at": (now - timedelta(days=1, minutes=-6)).isoformat(timespec="seconds"),
                "work_order_id": "WO-DEMO-0004",
            },
            {
                "id": "ALT-DEMO-0005",
                "pipeline_id": "PL-001",
                "pipeline_name": "北区输油干线",
                "level": "critical",
                "title": "北区进出口流量差异常",
                "description": "连续三个采样周期质量守恒偏差超过 8%，需要检查河西阀室和流量计。",
                "status": "acknowledged",
                "created_at": (now - timedelta(hours=6)).isoformat(timespec="seconds"),
                "acknowledged_at": (now - timedelta(hours=5, minutes=48)).isoformat(timespec="seconds"),
                "work_order_id": "WO-DEMO-0005",
            },
            {
                "id": "ALT-DEMO-0006",
                "pipeline_id": "PL-003",
                "pipeline_name": "南区成品油管线",
                "level": "warning",
                "title": "南区温度变送器数据漂移",
                "description": "温度读数与相邻测点偏差 3.1 ℃，建议检查接线并进行现场校准。",
                "status": "open",
                "created_at": (now - timedelta(hours=3)).isoformat(timespec="seconds"),
                "acknowledged_at": None,
            },
            {
                "id": "ALT-DEMO-0007",
                "pipeline_id": "PL-002",
                "pipeline_name": "东区天然气支线",
                "level": "critical",
                "title": "东区气体浓度短时升高",
                "description": "阀室周边可燃气体浓度最高达到 86 ppm，已安排人员携带便携仪表复核。",
                "status": "acknowledged",
                "created_at": (now - timedelta(hours=1, minutes=20)).isoformat(timespec="seconds"),
                "acknowledged_at": (now - timedelta(hours=1, minutes=12)).isoformat(timespec="seconds"),
                "work_order_id": "WO-DEMO-0006",
            },
            {
                "id": "ALT-DEMO-0008",
                "pipeline_id": "PL-001",
                "pipeline_name": "北区输油干线",
                "level": "warning",
                "title": "北区阀室通信延迟升高",
                "description": "边缘网关通信时延由 23 ms 升至 168 ms，数据仍在连续上报。",
                "status": "open",
                "created_at": (now - timedelta(minutes=22)).isoformat(timespec="seconds"),
                "acknowledged_at": None,
            },
            {
                "id": "ALT-DEMO-0009",
                "pipeline_id": "PL-001",
                "pipeline_name": "北区输油干线",
                "level": "warning",
                "title": "北区压力变送器零点漂移",
                "description": "压力变送器零点偏差 0.08 MPa，完成远程校准后读数已恢复稳定。",
                "status": "resolved",
                "created_at": (now - timedelta(days=2, hours=9)).isoformat(timespec="seconds"),
                "acknowledged_at": (now - timedelta(days=2, hours=8, minutes=48)).isoformat(timespec="seconds"),
                "work_order_id": "WO-DEMO-0007",
            },
            {
                "id": "ALT-DEMO-0010",
                "pipeline_id": "PL-003",
                "pipeline_name": "南区成品油管线",
                "level": "critical",
                "title": "南区泵房振动趋势上升",
                "description": "泵组振动由 2.1 mm/s 升至 4.8 mm/s，已通知机泵专业人员现场诊断。",
                "status": "acknowledged",
                "created_at": (now - timedelta(hours=2, minutes=25)).isoformat(timespec="seconds"),
                "acknowledged_at": (now - timedelta(hours=2, minutes=16)).isoformat(timespec="seconds"),
                "work_order_id": "WO-DEMO-0008",
            },
            {
                "id": "ALT-DEMO-0011",
                "pipeline_id": "PL-002",
                "pipeline_name": "东区天然气支线",
                "level": "warning",
                "title": "东区阴极保护电位偏离",
                "description": "两处测试桩保护电位接近预警下限，需要复测接地与恒电位仪输出。",
                "status": "acknowledged",
                "created_at": (now - timedelta(hours=5, minutes=10)).isoformat(timespec="seconds"),
                "acknowledged_at": (now - timedelta(hours=4, minutes=58)).isoformat(timespec="seconds"),
                "work_order_id": "WO-DEMO-0009",
            },
            {
                "id": "ALT-DEMO-0012",
                "pipeline_id": "PL-003",
                "pipeline_name": "南区成品油管线",
                "level": "critical",
                "title": "南区流量计通信中断",
                "description": "储备库入口流量计连续五分钟未上报，边缘网关已切换到估算值模式。",
                "status": "acknowledged",
                "created_at": (now - timedelta(minutes=55)).isoformat(timespec="seconds"),
                "acknowledged_at": (now - timedelta(minutes=49)).isoformat(timespec="seconds"),
                "work_order_id": "WO-DEMO-0010",
            },
            {
                "id": "ALT-DEMO-0013",
                "pipeline_id": "PL-001",
                "pipeline_name": "北区输油干线",
                "level": "warning",
                "title": "北区温度测点升高速率异常",
                "description": "十分钟内温度上升 2.6 ℃，尚未超过高限，需持续观察趋势。",
                "status": "open",
                "created_at": (now - timedelta(minutes=12)).isoformat(timespec="seconds"),
                "acknowledged_at": None,
            },
        ]
        initial_work_orders = [  # type: List[Dict[str, Any]]
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
                "created_at": (now - timedelta(days=3)).isoformat(timespec="seconds"),
                "due_at": (now - timedelta(days=2, hours=16)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(days=2, hours=20)).isoformat(timespec="seconds"),
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
                "created_at": (now - timedelta(days=2)).isoformat(timespec="seconds"),
                "due_at": (now - timedelta(days=1, hours=20)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(days=1, hours=22)).isoformat(timespec="seconds"),
            },
            {
                "id": "WO-DEMO-0003",
                "title": "南区阀室后备电池更换",
                "pipeline_id": "PL-003",
                "pipeline_name": "南区成品油管线",
                "alert_id": "ALT-DEMO-0003",
                "priority": "high",
                "status": "pending",
                "assignee": "赵工",
                "description": "携带同规格电池，在巡检窗口完成更换并测试断电切换。",
                "created_at": (now - timedelta(days=1, hours=3, minutes=40)).isoformat(timespec="seconds"),
                "due_at": (now + timedelta(days=1)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(days=1, hours=3, minutes=40)).isoformat(timespec="seconds"),
            },
            {
                "id": "WO-DEMO-0004",
                "title": "东区入口压力波动复核",
                "pipeline_id": "PL-002",
                "pipeline_name": "东区天然气支线",
                "alert_id": "ALT-DEMO-0004",
                "priority": "medium",
                "status": "completed",
                "assignee": "陈工",
                "description": "核对调压作业记录，复测入口压力并确认仪表工作正常。",
                "created_at": (now - timedelta(hours=23, minutes=45)).isoformat(timespec="seconds"),
                "due_at": (now - timedelta(hours=15)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(hours=20)).isoformat(timespec="seconds"),
            },
            {
                "id": "WO-DEMO-0005",
                "title": "北区流量平衡异常排查",
                "pipeline_id": "PL-001",
                "pipeline_name": "北区输油干线",
                "alert_id": "ALT-DEMO-0005",
                "priority": "urgent",
                "status": "pending",
                "assignee": "北区应急组",
                "description": "检查河西阀室阀位、流量计零点及沿线是否存在异常迹象。",
                "created_at": (now - timedelta(hours=5, minutes=45)).isoformat(timespec="seconds"),
                "due_at": (now - timedelta(hours=3, minutes=45)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(hours=5, minutes=45)).isoformat(timespec="seconds"),
            },
            {
                "id": "WO-DEMO-0006",
                "title": "东区气体浓度现场复测",
                "pipeline_id": "PL-002",
                "pipeline_name": "东区天然气支线",
                "alert_id": "ALT-DEMO-0007",
                "priority": "urgent",
                "status": "in_progress",
                "assignee": "周工",
                "description": "携带便携式气体检测仪复测阀室周边浓度，排查法兰和放散管。",
                "created_at": (now - timedelta(hours=1, minutes=10)).isoformat(timespec="seconds"),
                "due_at": (now + timedelta(minutes=50)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(minutes=35)).isoformat(timespec="seconds"),
            },
            {
                "id": "WO-DEMO-0007",
                "title": "北区压力变送器零点校准",
                "pipeline_id": "PL-001",
                "pipeline_name": "北区输油干线",
                "alert_id": "ALT-DEMO-0009",
                "priority": "medium",
                "status": "completed",
                "assignee": "钱工",
                "description": "远程校准压力变送器零点，并与站控标准表进行比对。",
                "created_at": (now - timedelta(days=2, hours=8, minutes=45)).isoformat(timespec="seconds"),
                "due_at": (now - timedelta(days=2, hours=4)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(days=2, hours=7, minutes=30)).isoformat(timespec="seconds"),
            },
            {
                "id": "WO-DEMO-0008",
                "title": "南区泵组振动现场诊断",
                "pipeline_id": "PL-003",
                "pipeline_name": "南区成品油管线",
                "alert_id": "ALT-DEMO-0010",
                "priority": "urgent",
                "status": "in_progress",
                "assignee": "机泵检修组",
                "description": "采集泵组轴承振动频谱，检查联轴器对中和轴承温度。",
                "created_at": (now - timedelta(hours=2, minutes=12)).isoformat(timespec="seconds"),
                "due_at": (now + timedelta(hours=1, minutes=48)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(hours=1, minutes=35)).isoformat(timespec="seconds"),
            },
            {
                "id": "WO-DEMO-0009",
                "title": "东区阴极保护系统复测",
                "pipeline_id": "PL-002",
                "pipeline_name": "东区天然气支线",
                "alert_id": "ALT-DEMO-0011",
                "priority": "high",
                "status": "in_progress",
                "assignee": "防腐检测组",
                "description": "复测沿线测试桩保护电位，检查恒电位仪及接地连接状态。",
                "created_at": (now - timedelta(hours=4, minutes=52)).isoformat(timespec="seconds"),
                "due_at": (now + timedelta(hours=3)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(hours=3, minutes=40)).isoformat(timespec="seconds"),
            },
            {
                "id": "WO-DEMO-0010",
                "title": "南区入口流量计通信恢复",
                "pipeline_id": "PL-003",
                "pipeline_name": "南区成品油管线",
                "alert_id": "ALT-DEMO-0012",
                "priority": "urgent",
                "status": "pending",
                "assignee": "仪表值班组",
                "description": "检查流量计供电、通信线缆和网关通道，恢复实时数据上报。",
                "created_at": (now - timedelta(minutes=46)).isoformat(timespec="seconds"),
                "due_at": (now + timedelta(hours=2)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(minutes=46)).isoformat(timespec="seconds"),
            },
        ]
        registered_at = datetime.now(timezone.utc)
        initial_devices = []  # type: List[Dict[str, Any]]
        for pipeline_index, pipeline in enumerate(PIPELINES):
            for type_index, device_type in enumerate(DEVICE_TYPES):
                sequence = pipeline_index * len(DEVICE_TYPES) + type_index + 1
                calibrated_at = registered_at - timedelta(days=24 + sequence * 3)
                initial_devices.append(
                    {
                        "id": "{}-{:03d}".format(
                            device_type["type_code"], pipeline_index + 1
                        ),
                        "name": device_type["type_name"],
                        "type_code": device_type["type_code"],
                        "type_name": device_type["type_name"],
                        "pipeline_id": pipeline["id"],
                        "pipeline_name": pipeline["name"],
                        "metric_key": device_type["metric_key"],
                        "unit": device_type["unit"],
                        "range_text": device_type["range_text"],
                        "accuracy": device_type["accuracy"],
                        "protocol": device_type["protocol"],
                        "status": "online",
                        "battery": max(72, 98 - sequence * 2),
                        "signal": max(68, 96 - sequence),
                        "last_seen": registered_at.isoformat(timespec="seconds"),
                        "calibrated_at": calibrated_at.isoformat(
                            timespec="seconds"
                        ),
                        "maintenance_due": (
                            calibrated_at + timedelta(days=180)
                        ).isoformat(timespec="seconds"),
                    }
                )
        default_checklist = [
            "检查阀门与法兰是否渗漏",
            "核对压力与流量仪表读数",
            "检查管线沿线环境与第三方施工",
            "拍照并填写巡检记录",
        ]
        initial_inspections = [  # type: List[Dict[str, Any]]
            {
                "id": "INS-0001",
                "pipeline_id": "PL-001",
                "pipeline_name": "北区输油干线",
                "title": "北区干线日常巡检",
                "inspector": "张工",
                "priority": "high",
                "status": "planned",
                "scheduled_at": (now + timedelta(hours=2)).isoformat(timespec="seconds"),
                "started_at": None,
                "completed_at": None,
                "result": None,
                "notes": "重点检查河西阀室附近管段。",
                "checklist": list(default_checklist),
                "created_at": now.isoformat(timespec="seconds"),
                "updated_at": now.isoformat(timespec="seconds"),
            },
            {
                "id": "INS-0002",
                "pipeline_id": "PL-002",
                "pipeline_name": "东区天然气支线",
                "title": "东区支线仪表专项巡检",
                "inspector": "王工",
                "priority": "medium",
                "status": "in_progress",
                "scheduled_at": (now - timedelta(hours=1)).isoformat(timespec="seconds"),
                "started_at": (now - timedelta(minutes=45)).isoformat(timespec="seconds"),
                "completed_at": None,
                "result": None,
                "notes": "复核气体探测器与振动传感器。",
                "checklist": list(default_checklist),
                "created_at": (now - timedelta(hours=3)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(minutes=45)).isoformat(timespec="seconds"),
            },
            {
                "id": "INS-0003",
                "pipeline_id": "PL-003",
                "pipeline_name": "南区成品油管线",
                "title": "南区储备库交接巡检",
                "inspector": "李工",
                "priority": "medium",
                "status": "completed",
                "scheduled_at": (now - timedelta(days=1)).isoformat(timespec="seconds"),
                "started_at": (now - timedelta(days=1, minutes=-10)).isoformat(timespec="seconds"),
                "completed_at": (now - timedelta(days=1, minutes=-55)).isoformat(timespec="seconds"),
                "result": "normal",
                "notes": "现场管线、阀室及仪表状态正常。",
                "checklist": list(default_checklist),
                "created_at": (now - timedelta(days=2)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(days=1, minutes=-55)).isoformat(timespec="seconds"),
            },
            {
                "id": "INS-DEMO-0004",
                "pipeline_id": "PL-003",
                "pipeline_name": "南区成品油管线",
                "title": "南区储备库夜间巡检",
                "inspector": "刘工",
                "priority": "low",
                "status": "planned",
                "scheduled_at": (now + timedelta(hours=6)).isoformat(timespec="seconds"),
                "started_at": None,
                "completed_at": None,
                "result": None,
                "notes": "检查库区照明、围栏和入口阀组。",
                "checklist": list(default_checklist),
                "created_at": (now - timedelta(hours=2)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(hours=2)).isoformat(timespec="seconds"),
            },
            {
                "id": "INS-DEMO-0005",
                "pipeline_id": "PL-002",
                "pipeline_name": "东区天然气支线",
                "title": "东区工业园沿线徒步巡检",
                "inspector": "孙工",
                "priority": "high",
                "status": "planned",
                "scheduled_at": (now - timedelta(hours=4)).isoformat(timespec="seconds"),
                "started_at": None,
                "completed_at": None,
                "result": None,
                "notes": "任务已逾期，重点排查工业园施工区域。",
                "checklist": list(default_checklist),
                "created_at": (now - timedelta(days=1)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(days=1)).isoformat(timespec="seconds"),
            },
            {
                "id": "INS-DEMO-0006",
                "pipeline_id": "PL-001",
                "pipeline_name": "北区输油干线",
                "title": "河西阀室密封专项检查",
                "inspector": "赵工",
                "priority": "high",
                "status": "in_progress",
                "scheduled_at": (now - timedelta(minutes=40)).isoformat(timespec="seconds"),
                "started_at": (now - timedelta(minutes=25)).isoformat(timespec="seconds"),
                "completed_at": None,
                "result": None,
                "notes": "检查阀杆、法兰和排污口密封情况。",
                "checklist": list(default_checklist),
                "created_at": (now - timedelta(hours=5)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(minutes=25)).isoformat(timespec="seconds"),
            },
            {
                "id": "INS-DEMO-0007",
                "pipeline_id": "PL-001",
                "pipeline_name": "北区输油干线",
                "title": "北区站交接班巡检",
                "inspector": "钱工",
                "priority": "medium",
                "status": "completed",
                "scheduled_at": (now - timedelta(days=2)).isoformat(timespec="seconds"),
                "started_at": (now - timedelta(days=2, minutes=-5)).isoformat(timespec="seconds"),
                "completed_at": (now - timedelta(days=2, minutes=-38)).isoformat(timespec="seconds"),
                "result": "normal",
                "notes": "站内设备、消防设施和数据采集状态均正常。",
                "checklist": list(default_checklist),
                "created_at": (now - timedelta(days=3)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(days=2, minutes=-38)).isoformat(timespec="seconds"),
            },
            {
                "id": "INS-DEMO-0008",
                "pipeline_id": "PL-002",
                "pipeline_name": "东区天然气支线",
                "title": "东区阀室可燃气体专项巡检",
                "inspector": "周工",
                "priority": "high",
                "status": "completed",
                "scheduled_at": (now - timedelta(days=1, hours=6)).isoformat(timespec="seconds"),
                "started_at": (now - timedelta(days=1, hours=5, minutes=50)).isoformat(timespec="seconds"),
                "completed_at": (now - timedelta(days=1, hours=5, minutes=12)).isoformat(timespec="seconds"),
                "result": "abnormal",
                "notes": "放散管附近存在轻微异味，已提交复测工单。",
                "checklist": list(default_checklist),
                "created_at": (now - timedelta(days=2)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(days=1, hours=5, minutes=12)).isoformat(timespec="seconds"),
            },
            {
                "id": "INS-DEMO-0009",
                "pipeline_id": "PL-003",
                "pipeline_name": "南区成品油管线",
                "title": "南区管廊第三方施工巡查",
                "inspector": "吴工",
                "priority": "medium",
                "status": "completed",
                "scheduled_at": (now - timedelta(days=4)).isoformat(timespec="seconds"),
                "started_at": (now - timedelta(days=4, minutes=-8)).isoformat(timespec="seconds"),
                "completed_at": (now - timedelta(days=4, minutes=-52)).isoformat(timespec="seconds"),
                "result": "normal",
                "notes": "施工围挡与管线保护距离符合要求，已完成现场拍照。",
                "checklist": list(default_checklist),
                "created_at": (now - timedelta(days=5)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(days=4, minutes=-52)).isoformat(timespec="seconds"),
            },
            {
                "id": "INS-DEMO-0010",
                "pipeline_id": "PL-001",
                "pipeline_name": "北区输油干线",
                "title": "北区河道穿越段汛期巡检",
                "inspector": "郑工",
                "priority": "high",
                "status": "planned",
                "scheduled_at": (now + timedelta(hours=9)).isoformat(timespec="seconds"),
                "started_at": None,
                "completed_at": None,
                "result": None,
                "notes": "检查河岸冲刷、标志桩和穿越段上方施工活动。",
                "checklist": list(default_checklist),
                "created_at": (now - timedelta(hours=6)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(hours=6)).isoformat(timespec="seconds"),
            },
            {
                "id": "INS-DEMO-0011",
                "pipeline_id": "PL-003",
                "pipeline_name": "南区成品油管线",
                "title": "南区泵房机电联合巡检",
                "inspector": "许工",
                "priority": "high",
                "status": "in_progress",
                "scheduled_at": (now - timedelta(hours=2)).isoformat(timespec="seconds"),
                "started_at": (now - timedelta(hours=1, minutes=42)).isoformat(timespec="seconds"),
                "completed_at": None,
                "result": None,
                "notes": "联合检查泵组振动、轴承温度和电机电流。",
                "checklist": list(default_checklist),
                "created_at": (now - timedelta(days=1)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(hours=1, minutes=42)).isoformat(timespec="seconds"),
            },
            {
                "id": "INS-DEMO-0012",
                "pipeline_id": "PL-002",
                "pipeline_name": "东区天然气支线",
                "title": "东区高后果区周界巡检",
                "inspector": "何工",
                "priority": "medium",
                "status": "completed",
                "scheduled_at": (now - timedelta(days=3, hours=4)).isoformat(timespec="seconds"),
                "started_at": (now - timedelta(days=3, hours=3, minutes=50)).isoformat(timespec="seconds"),
                "completed_at": (now - timedelta(days=3, hours=3, minutes=5)).isoformat(timespec="seconds"),
                "result": "normal",
                "notes": "周界围栏、警示标识及沿线占压情况均正常。",
                "checklist": list(default_checklist),
                "created_at": (now - timedelta(days=4)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(days=3, hours=3, minutes=5)).isoformat(timespec="seconds"),
            },
        ]
        self._database.initialize(
            initial_alerts, initial_work_orders, initial_devices,
            initial_inspections,
        )
        self._alerts = self._database.load_alerts()
        self._work_orders = self._database.load_work_orders()
        self._devices = self._database.load_devices()
        self._inspections = self._database.load_inspections()
        self._alert_seq = self._maximum_sequence(self._alerts)
        self._work_order_seq = self._maximum_sequence(self._work_orders)
        self._inspection_seq = self._maximum_sequence(self._inspections)

        history_available = True
        for pipeline in PIPELINES:
            pipe_id = pipeline["id"]
            samples = self._database.load_recent_telemetry(pipe_id, 60)
            self._history[pipe_id].extend(samples)
            if samples:
                self._snapshots[pipe_id] = samples[-1]
            else:
                history_available = False
        if history_available:
            self.advance()
        else:
            for _ in range(32):
                self.advance()

    @staticmethod
    def _maximum_sequence(items: List[Dict[str, Any]]) -> int:
        values = []
        for item in items:
            try:
                values.append(int(str(item["id"]).split("-")[-1]))
            except (KeyError, TypeError, ValueError):
                continue
        return max(values or [0])

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
                self._database.save_telemetry(pipe_id, sample)

                if (
                    risk.level == "critical"
                    and (not previous or previous["risk"]["level"] != "critical")
                ):
                    self._create_alert(pipeline, risk, sample)
            if self._tick % 30 == 0:
                self._database.prune_telemetry(
                    [pipeline["id"] for pipeline in PIPELINES]
                )

    def _create_alert(self, pipeline: dict, risk: Any, sample: dict) -> None:
        self._alert_seq += 1
        alert = {
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
        }
        self._alerts.insert(
            0,
            alert,
        )
        self._database.save_alert(alert)
        self._database.add_audit(
            "alert_created",
            "alert",
            alert["id"],
            "{}产生严重告警，风险评分为{}。".format(
                pipeline["name"], round(risk.score)
            ),
        )

    def overview(self) -> Dict[str, Any]:
        with self._lock:
            pipelines = self.pipelines()
            open_alerts = sum(
                alert["status"] == "open" for alert in self._alerts
            )
            online = sum(device["status"] == "online" for device in self._devices)
            return {
                "system_name": "PipeGuard",
                "updated_at": utc_now(),
                "metrics": {
                    "pipeline_count": len(pipelines),
                    "monitored_length": round(sum(p["length"] for p in pipelines), 1),
                    "online_devices": online,
                    "device_total": len(self._devices),
                    "open_alerts": open_alerts,
                    "availability": 99.8,
                },
                "pipelines": pipelines,
            }

    def pipelines(self) -> List[Dict[str, Any]]:
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

    def pipeline(self, pipe_id: str) -> Optional[Dict[str, Any]]:
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

    def alerts(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(alert) for alert in self._alerts]

    def work_orders(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(work_order) for work_order in self._work_orders]

    def inspections(self) -> List[Dict[str, Any]]:
        """Return inspection plans with a calculated overdue flag."""

        with self._lock:
            now = utc_now()
            result = []
            for inspection in self._inspections:
                item = dict(inspection)
                item["checklist"] = list(inspection.get("checklist", []))
                item["is_overdue"] = (
                    inspection["status"] != "completed"
                    and inspection["scheduled_at"] < now
                )
                result.append(item)
            return sorted(result, key=lambda item: (item["status"] == "completed", item["scheduled_at"]))

    def create_inspection(
        self,
        pipeline_id: str,
        title: str,
        inspector: str,
        scheduled_at: str,
        priority: str = "medium",
        notes: str = "",
        checklist: Optional[List[str]] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        if priority not in ("low", "medium", "high"):
            return None, "invalid_priority"
        pipeline = next((item for item in PIPELINES if item["id"] == pipeline_id), None)
        if not pipeline:
            return None, "pipeline_not_found"
        if not title.strip() or not inspector.strip() or not scheduled_at.strip():
            return None, "required_fields"
        with self._lock:
            self._inspection_seq += 1
            now = utc_now()
            task = {
                "id": "INS-{:04d}".format(self._inspection_seq),
                "pipeline_id": pipeline["id"],
                "pipeline_name": pipeline["name"],
                "title": title.strip(),
                "inspector": inspector.strip(),
                "priority": priority,
                "status": "planned",
                "scheduled_at": scheduled_at.strip(),
                "started_at": None,
                "completed_at": None,
                "result": None,
                "notes": notes.strip(),
                "checklist": [
                    str(item).strip() for item in (checklist or []) if str(item).strip()
                ],
                "created_at": now,
                "updated_at": now,
            }
            self._inspections.append(task)
            self._database.save_inspection(task)
            self._database.add_audit(
                "inspection_created", "inspection", task["id"],
                "为{}创建巡检计划，负责人为{}。".format(
                    pipeline["name"], task["inspector"]
                ),
            )
            return dict(task), None

    def update_inspection(
        self, inspection_id: str, status: str, result: str = "", notes: str = ""
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        allowed = {"planned": {"in_progress"}, "in_progress": {"completed"}, "completed": set()}
        if status not in allowed:
            return None, "invalid_status"
        with self._lock:
            task = next((item for item in self._inspections if item["id"] == inspection_id), None)
            if not task:
                return None, "inspection_not_found"
            current = task["status"]
            if status == current:
                return dict(task), None
            if status not in allowed[current]:
                return None, "invalid_transition"
            if status == "completed" and result not in ("normal", "abnormal"):
                return None, "invalid_result"
            now = utc_now()
            task["status"] = status
            task["updated_at"] = now
            action = "inspection_started"
            detail = "{}巡检已开始，负责人为{}。".format(task["pipeline_name"], task["inspector"])
            if status == "in_progress":
                task["started_at"] = now
            else:
                task["result"] = result
                task["notes"] = notes.strip() or task["notes"]
                task["completed_at"] = now
                action = "inspection_completed"
                detail = "巡检结论：{}。".format("正常" if result == "normal" else "发现异常")
                if result == "abnormal":
                    self._alert_seq += 1
                    alert = {
                        "id": "ALT-{:04d}".format(self._alert_seq),
                        "pipeline_id": task["pipeline_id"],
                        "pipeline_name": task["pipeline_name"],
                        "level": "warning",
                        "title": "{}巡检发现异常".format(task["pipeline_name"]),
                        "description": task["notes"] or "现场巡检发现异常，请安排进一步排查。",
                        "status": "open",
                        "created_at": now,
                        "acknowledged_at": None,
                    }
                    self._alerts.insert(0, alert)
                    self._database.save_alert(alert)
                    action = "inspection_abnormal"
                    detail += " 系统已自动生成告警{}。".format(alert["id"])
            self._database.save_inspection(task)
            self._database.add_audit(action, "inspection", task["id"], detail)
            return dict(task), None

    def devices(self) -> List[Dict[str, Any]]:
        """Return persistent device assets enriched with live readings."""

        with self._lock:
            result = []
            now = utc_now()
            for device in self._devices:
                item = dict(device)
                snapshot = self._snapshots.get(device["pipeline_id"], {})
                if device["status"] == "online":
                    item["reading"] = snapshot.get(device["metric_key"])
                    item["last_seen"] = snapshot.get("timestamp", device["last_seen"])
                else:
                    item["reading"] = None
                item["calibration_due"] = device["maintenance_due"] <= now
                result.append(item)
            return result

    def calibrate_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            device = next(
                (item for item in self._devices if item["id"] == device_id), None
            )
            if not device:
                return None
            now = datetime.now(timezone.utc)
            device["calibrated_at"] = now.isoformat(timespec="seconds")
            device["maintenance_due"] = (
                now + timedelta(days=180)
            ).isoformat(timespec="seconds")
            device["last_seen"] = now.isoformat(timespec="seconds")
            self._database.save_device(device)
            self._database.add_audit(
                "device_calibrated",
                "device",
                device_id,
                "{} {} 已完成远程零点校准。".format(
                    device["pipeline_name"], device["type_name"]
                ),
            )
            return next(
                item for item in self.devices() if item["id"] == device_id
            )

    def update_device_status(
        self, device_id: str, status: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        if status not in ("online", "offline"):
            return None, "invalid_status"
        with self._lock:
            device = next(
                (item for item in self._devices if item["id"] == device_id), None
            )
            if not device:
                return None, "device_not_found"
            if device["status"] == status:
                return next(
                    item for item in self.devices() if item["id"] == device_id
                ), None

            device["status"] = status
            device["last_seen"] = utc_now()
            self._database.save_device(device)
            alert_title = "设备 {} 通信中断".format(device_id)
            if status == "offline":
                self._alert_seq += 1
                alert = {
                    "id": "ALT-{:04d}".format(self._alert_seq),
                    "pipeline_id": device["pipeline_id"],
                    "pipeline_name": device["pipeline_name"],
                    "level": "warning",
                    "title": alert_title,
                    "description": "{} 已离线，请检查供电、通信链路与边缘网关。".format(
                        device["type_name"]
                    ),
                    "status": "open",
                    "created_at": utc_now(),
                    "acknowledged_at": None,
                }
                self._alerts.insert(0, alert)
                self._database.save_alert(alert)
            else:
                for alert in self._alerts:
                    if alert["title"] == alert_title and alert["status"] != "resolved":
                        alert["status"] = "resolved"
                        alert["acknowledged_at"] = alert.get(
                            "acknowledged_at"
                        ) or utc_now()
                        self._database.save_alert(alert)
            self._database.add_audit(
                "device_status_changed",
                "device",
                device_id,
                "{} 已{}。".format(
                    device["type_name"], "恢复在线" if status == "online" else "模拟离线"
                ),
            )
            return next(
                item for item in self.devices() if item["id"] == device_id
            ), None

    def create_work_order(
        self,
        alert_id: str,
        *,
        assignee: str = "值班运维组",
        description: str = "",
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
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
            self._database.save_alert(alert)
            self._database.save_work_order(work_order)
            self._database.add_audit(
                "work_order_created",
                "work_order",
                work_order["id"],
                "由告警{}创建，负责人为{}。".format(
                    alert["id"], work_order["assignee"]
                ),
            )
            return dict(work_order), None

    def update_work_order(
        self, work_order_id: str, status: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
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
                    self._database.save_alert(alert)
            self._database.save_work_order(work_order)
            self._database.add_audit(
                "work_order_status_changed",
                "work_order",
                work_order["id"],
                "工单状态由{}更新为{}。".format(current, status),
            )
            return dict(work_order), None

    def analytics(self) -> Dict[str, Any]:
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
            online_devices = sum(
                device["status"] == "online" for device in self._devices
            )
            calibration_due = sum(
                device["maintenance_due"] <= utc_now() for device in self._devices
            )
            inspection_status = {
                status: sum(item["status"] == status for item in self._inspections)
                for status in ("planned", "in_progress", "completed")
            }
            overdue = sum(
                item["status"] != "completed" and item["scheduled_at"] < utc_now()
                for item in self._inspections
            )
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
                "devices": {
                    "total": len(self._devices),
                    "online": online_devices,
                    "offline": len(self._devices) - online_devices,
                    "online_rate": round(
                        online_devices / max(1, len(self._devices)) * 100, 1
                    ),
                    "calibration_due": calibration_due,
                },
                "inspections": {
                    "total": len(self._inspections),
                    "by_status": inspection_status,
                    "overdue": overdue,
                    "completion_rate": round(
                        inspection_status["completed"]
                        / max(1, len(self._inspections)) * 100, 1
                    ),
                },
            }

    def acknowledge(self, alert_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for alert in self._alerts:
                if alert["id"] == alert_id:
                    if alert["status"] == "open":
                        alert["status"] = "acknowledged"
                        alert["acknowledged_at"] = utc_now()
                        self._database.save_alert(alert)
                        self._database.add_audit(
                            "alert_acknowledged",
                            "alert",
                            alert["id"],
                            "值班人员确认告警，等待现场处置。",
                        )
                    return dict(alert)
        return None

    def simulate_leak(self, pipe_id: str) -> bool:
        with self._lock:
            if not any(p["id"] == pipe_id for p in PIPELINES):
                return False
            self._leak_ticks[pipe_id] = 120
            self._database.add_audit(
                "scenario_injected",
                "pipeline",
                pipe_id,
                "课程演示注入模拟泄漏场景。",
            )
            # Advance enough to make the effect immediately visible.
            for _ in range(16):
                self.advance()
            return True

    def database_summary(self) -> Dict[str, Any]:
        return self._database.summary()

    def audit_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._database.audit_logs(limit)

    def close(self) -> None:
        self._database.close()


class Simulator:
    """Runs the store at a fixed sampling interval."""

    def __init__(self, store: MonitoringStore, interval: float = 2.0) -> None:
        self.store = store
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None  # type: Optional[threading.Thread]

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
