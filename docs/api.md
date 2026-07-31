# PipeGuard HTTP API

默认服务地址：`http://127.0.0.1:8000`。所有响应均为 UTF-8 JSON。

## 健康检查

```http
GET /api/health
```

```json
{"status":"ok","service":"pipeguard-api","version":"1.1.1"}
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

返回正常、警告、严重管线数量，告警闭环率，工单完成率及各状态数量。

## 导出告警

```http
GET /api/export/alerts.csv
```

返回带 UTF-8 BOM 的 CSV 文件，可直接使用 Excel 打开并用于课程报告留档。

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
