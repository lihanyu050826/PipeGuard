# PipeGuard HTTP API

默认服务地址：`http://127.0.0.1:8000`。所有响应均为 UTF-8 JSON。

## 健康检查

```http
GET /api/health
```

```json
{"status":"ok","service":"pipeguard-api","version":"1.5.0","database":"connected"}
```

## 管网总览

```http
GET /api/overview
```

返回系统更新时间、监测里程、设备在线率、待处置告警和全部管线简要状态。

## 管线列表

```http
GET /api/pipelines
```

## 单条管线详情

```http
GET /api/pipelines/PL-001
```

返回管线资产信息、最新遥测、风险结果及最近 60 个采样点。

风险对象示例：

```json
{
  "score": 12.4,
  "level": "normal",
  "confidence": 0.58,
  "factors": ["各项监测指标处于正常波动范围"],
  "components": {
    "pressure": 0.0,
    "flow": 4.6,
    "gas": 0.0,
    "vibration": 0.0
  }
}
```

## 设备资产管理

查询 15 台传感设备台账与实时读数：

```http
GET /api/devices
```

返回设备类型、管线归属、量程、精度、协议、电量、信号、校准周期与在线状态。

执行远程校准：

```http
POST /api/devices/PT-001/calibrate
Content-Type: application/json

{}
```

更新设备状态：

```http
POST /api/devices/PT-001/status
Content-Type: application/json

{"status":"offline"}
```

状态可为 `online` 或 `offline`。设备离线时系统自动生成通信中断告警，恢复在线时自动闭环对应告警。

## 巡检计划

查询巡检任务：

```http
GET /api/inspections
```

新建计划：

```http
POST /api/inspections
Content-Type: application/json

{"pipeline_id":"PL-001","title":"北区干线日常巡检","inspector":"张工","scheduled_at":"2026-08-03T10:00:00+00:00","priority":"high","notes":"重点检查河西阀室","checklist":["检查阀门","核对仪表"]}
```

推进状态或提交结论：

```http
POST /api/inspections/INS-0004/status
Content-Type: application/json

{"status":"completed","result":"abnormal","notes":"法兰处发现轻微油渍"}
```

状态只能按 `planned` → `in_progress` → `completed` 流转。结论可为 `normal` 或 `abnormal`；异常结项会自动生成一条待确认告警。

## 告警列表

```http
GET /api/alerts
```

告警状态包括：

- `open`：待确认；
- `acknowledged`：已由运维人员确认；
- `resolved`：指标恢复正常。

## 确认告警

```http
POST /api/alerts/ALT-0003/ack
Content-Type: application/json
```

该接口具备幂等性；重复确认不会创建新事件。

## 运维工单

查询全部工单：

```http
GET /api/work-orders
```

由告警创建工单：

```http
POST /api/work-orders
Content-Type: application/json

{
  "alert_id": "ALT-0003",
  "assignee": "值班运维组",
  "description": "现场复核压力与阀室状态"
}
```

同一告警只能关联一个工单。工单创建后，相应告警会自动变为 `acknowledged`。

推进工单状态：

```http
POST /api/work-orders/WO-0003/status
Content-Type: application/json

{"status":"in_progress"}
```

状态只能按 `pending` → `in_progress` → `completed` 顺序流转；工单完成后，相应告警自动变为 `resolved`。

## 运营分析

```http
GET /api/analytics
```

返回正常、警告、严重管线数量，告警闭环率，工单完成率，巡检完成率与逾期数，以及设备在线率、离线数和待校准数量。

## 导出告警

```http
GET /api/export/alerts.csv
```

返回带 UTF-8 BOM 的 CSV 文件，可直接使用 Excel 打开并用于课程报告留档。

## 数据库状态

```http
GET /api/database
```

返回 SQLite 版本、数据库位置、文件大小、保留策略，以及 `telemetry`、`alerts`、`work_orders`、`devices`、`inspection_tasks`、`audit_logs` 六张表的记录数。

## 操作审计日志

```http
GET /api/audit-logs
```

返回最近 50 条关键操作，包括泄漏场景注入、告警生成、设备校准、设备状态变更、工单创建和状态更新。

## 导出工单

```http
GET /api/export/work-orders.csv
```

返回带 UTF-8 BOM 的工单 CSV 文件，包含负责人、优先级、状态和时限信息。

## 导出设备台账

```http
GET /api/export/devices.csv
```

返回带 UTF-8 BOM 的设备 CSV，包含设备归属、实时读数、信号质量、通信协议和校准周期。

## 导出巡检记录

```http
GET /api/export/inspections.csv
```

返回带 UTF-8 BOM 的巡检 CSV，包含负责人、计划时间、状态、结论和现场记录。

## 注入泄漏演示

```http
POST /api/simulate/leak
Content-Type: application/json

{"pipeline_id":"PL-001"}
```

成功返回 `202 Accepted`。该接口仅用于课程演示，生产系统必须移除或限制为测试环境。

## 错误格式

不存在的资源返回 `404`：

```json
{"error":"pipeline_not_found"}
```
