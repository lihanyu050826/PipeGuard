const state = {
  overview: null,
  pipelines: [],
  alerts: [],
  workOrders: [],
  devices: [],
  inspections: [],
  analytics: null,
  database: null,
  auditLogs: [],
  selectedPipeline: "PL-001",
  alertFilter: "all",
  workFilter: "all",
  deviceStatusFilter: "all",
  deviceTypeFilter: "all",
  deviceSearch: "",
  inspectionStatusFilter: "all",
  inspectionPipelineFilter: "all",
  inspectionSearch: "",
  refreshTimer: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const levelText = { normal: "运行正常", warning: "注意观察", critical: "高风险" };
const alertStatusText = { open: "待确认", acknowledged: "已确认", resolved: "已恢复" };
const componentText = { pressure: "压力异常", flow: "流量平衡", gas: "气体浓度", vibration: "振动信号" };
const workStatusText = { pending: "待处理", in_progress: "处理中", completed: "已完成" };
const priorityText = { urgent: "紧急", high: "高", medium: "中", low: "低" };
const inspectionStatusText = { planned: "待执行", in_progress: "执行中", completed: "已完成" };
const inspectionResultText = { normal: "现场正常", abnormal: "发现异常" };

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) throw new Error(`API ${response.status}`);
  return response.json();
}

function formatTime(value) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).format(new Date(value));
}

function formatDateTime(value) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(new Date(value));
}

function formatDate(value) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date(value));
}

function notify(message) {
  const toast = $("#toast");
  $("p", toast).textContent = message;
  toast.classList.add("show");
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => toast.classList.remove("show"), 3000);
}

async function refreshAll({ quiet = false } = {}) {
  try {
    const [overview, pipelines, alerts, workOrders, devices, inspections, analytics, database, auditLogs] = await Promise.all([
      api("/api/overview"), api("/api/pipelines"), api("/api/alerts"),
      api("/api/work-orders"), api("/api/devices"), api("/api/inspections"), api("/api/analytics"),
      api("/api/database"), api("/api/audit-logs"),
    ]);
    state.overview = overview;
    state.pipelines = pipelines.items;
    state.alerts = alerts.items;
    state.workOrders = workOrders.items;
    state.devices = devices.items;
    state.inspections = inspections.items;
    state.analytics = analytics;
    state.database = database;
    state.auditLogs = auditLogs.items;
    $("#error-banner").classList.add("hidden");
    render();
    if (!quiet) notify("监测数据已同步");
  } catch (error) {
    $("#error-banner").classList.remove("hidden");
    console.error(error);
  }
}

function render() {
  renderMetrics();
  renderPipelineList();
  renderRecentAlerts();
  renderSelectors();
  renderAlerts();
  renderWorkOrders();
  renderDevices();
  renderInspections();
  renderAnalytics();
  renderDatabase();
  loadPipelineDetail(state.selectedPipeline);
}

function renderMetrics() {
  const { metrics, updated_at: updatedAt } = state.overview;
  $("#metric-pipelines").textContent = metrics.pipeline_count;
  $("#metric-length").textContent = metrics.monitored_length;
  $("#metric-devices").textContent = metrics.online_devices;
  $("#device-ratio").textContent = `/ ${metrics.device_total} 台`;
  $("#metric-alerts").textContent = metrics.open_alerts;
  $("#nav-alert-count").textContent = metrics.open_alerts;
  $("#nav-work-count").textContent = state.workOrders.filter((item) => item.status !== "completed").length;
  $("#nav-inspection-count").textContent = state.inspections.filter((item) => item.status !== "completed").length;
  $("#last-updated").textContent = `${formatTime(updatedAt)} 更新`;
  const offlineDevices = metrics.device_total - metrics.online_devices;
  $("#health-device-value").textContent = offlineDevices ? `${offlineDevices} 台离线` : "正常";
  $("#health-device-value").classList.toggle("health-warning", offlineDevices > 0);

  const mostRisky = [...state.pipelines].sort(
    (a, b) => b.telemetry.risk.score - a.telemetry.risk.score,
  )[0];
  const normal = mostRisky.telemetry.risk.level === "normal";
  $("#insight-title").textContent = normal ? "全网未发现显著泄漏特征" : `${mostRisky.name}存在异常特征`;
  $("#insight-copy").textContent = normal
    ? "压力与流量保持稳定，多源信号相关性处于正常范围。"
    : mostRisky.telemetry.risk.factors.join("；");
  $("#confidence-stat").textContent = `${Math.round(mostRisky.telemetry.risk.confidence * 100)}%`;
}

function pipelineRow(pipeline) {
  const t = pipeline.telemetry;
  return `
    <div class="pipeline-row" data-pipeline="${pipeline.id}">
      <div class="pipeline-name"><span class="pipe-symbol">⌁</span><span><b>${pipeline.name}</b><small>${pipeline.id} · ${pipeline.medium}</small></span></div>
      <div class="pipeline-value"><span>管内压力</span><b>${t.pressure} MPa</b></div>
      <div class="pipeline-value"><span>出口流量</span><b>${t.outlet_flow} m³/h</b></div>
      <em class="state-badge ${pipeline.status}"><i></i>${levelText[pipeline.status]}</em>
    </div>`;
}

function renderPipelineList() {
  const list = $("#pipeline-list");
  list.classList.remove("skeleton-block");
  list.innerHTML = state.pipelines.map(pipelineRow).join("");
  $$("[data-pipeline]", list).forEach((row) => {
    row.addEventListener("click", () => {
      state.selectedPipeline = row.dataset.pipeline;
      navigate("pipelines");
    });
  });
}

function renderRecentAlerts() {
  $("#recent-alerts").innerHTML = state.alerts.slice(0, 3).map((alert) => `
    <div class="recent-alert">
      <span class="alert-icon ${alert.level}">${alert.level === "critical" ? "!" : "△"}</span>
      <span><b>${alert.title}</b><small>${alert.pipeline_name} · ${formatDateTime(alert.created_at)}</small></span>
    </div>`).join("");
}

function renderSelectors() {
  $("#pipe-count").textContent = `${state.pipelines.length} 条`;
  $("#pipe-selector").innerHTML = state.pipelines.map((pipeline) => `
    <button class="pipe-option ${pipeline.id === state.selectedPipeline ? "active" : ""}" data-select-pipe="${pipeline.id}">
      <span class="option-status ${pipeline.status}"></span>
      <b>${pipeline.name}</b><small>${pipeline.id} · ${pipeline.length} km</small>
    </button>`).join("");
  $$("[data-select-pipe]").forEach((button) => button.addEventListener("click", () => {
    state.selectedPipeline = button.dataset.selectPipe;
    renderSelectors();
    loadPipelineDetail(state.selectedPipeline);
  }));
}

async function loadPipelineDetail(id) {
  if (!$("#pipelines-view").classList.contains("active")) return;
  try {
    const pipeline = await api(`/api/pipelines/${id}`);
    renderPipelineDetail(pipeline);
  } catch (error) {
    console.error(error);
  }
}

function renderPipelineDetail(pipeline) {
  const t = pipeline.telemetry;
  $("#detail-id").textContent = pipeline.id;
  $("#detail-name").textContent = pipeline.name;
  $("#detail-meta").textContent = `${pipeline.location} · ${pipeline.medium} · 全长 ${pipeline.length} km`;
  const status = $("#detail-status");
  status.className = `large-status ${pipeline.status}`;
  $("span", status).textContent = levelText[pipeline.status];
  $("#sensor-pressure").textContent = t.pressure;
  $("#sensor-inlet").textContent = t.inlet_flow;
  $("#sensor-outlet").textContent = t.outlet_flow;
  $("#sensor-gas").textContent = t.gas_ppm;
  $("#delta-pressure").textContent = `基线 ${pipeline.baseline_pressure} MPa`;
  $("#flow-diff").textContent = `差值 ${(t.inlet_flow - t.outlet_flow).toFixed(1)} m³/h`;

  const risk = t.risk;
  $("#risk-score").textContent = Math.round(risk.score);
  $("#risk-ring").style.setProperty("--score", risk.score);
  $("#risk-ring").style.setProperty("--teal", risk.level === "critical" ? "#df5360" : risk.level === "warning" ? "#df8b24" : "#0b8b80");
  $("#risk-label").textContent = risk.level === "critical" ? "疑似泄漏，请立即核查" : risk.level === "warning" ? "存在异常，建议关注" : "当前风险较低";
  $("#risk-confidence").textContent = `模型置信度 ${Math.round(risk.confidence * 100)}%`;
  $("#risk-components").innerHTML = Object.entries(risk.components).map(([key, value]) => `
    <div><div class="risk-component-head"><span>${componentText[key]}</span><b>${value}%</b></div><div class="component-bar"><i style="width:${value}%"></i></div></div>
  `).join("");
  $("#risk-factors").innerHTML = risk.factors.map((factor) => `<li>${factor}</li>`).join("");
  drawChart(pipeline.history);
}

function drawChart(history) {
  const canvas = $("#trend-chart");
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(500, rect.width * ratio);
  canvas.height = 260 * ratio;
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  const width = canvas.width / ratio;
  const height = 260;
  const padding = { left: 34, right: 18, top: 18, bottom: 25 };
  const plotW = width - padding.left - padding.right;
  const plotH = height - padding.top - padding.bottom;

  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = "#e8eeee";
  ctx.lineWidth = 1;
  ctx.font = "8px Inter";
  ctx.fillStyle = "#91a0a4";
  for (let i = 0; i <= 4; i += 1) {
    const y = padding.top + (plotH / 4) * i;
    ctx.beginPath(); ctx.moveTo(padding.left, y); ctx.lineTo(width - padding.right, y); ctx.stroke();
  }

  const series = [
    { key: "pressure", color: "#0b8b80", normalize: (v) => v / 8 },
    { key: "outlet_flow", color: "#7c64df", normalize: (v) => v / 160 },
  ];
  series.forEach(({ key, color, normalize }) => {
    const gradient = ctx.createLinearGradient(0, padding.top, 0, height - padding.bottom);
    gradient.addColorStop(0, `${color}30`); gradient.addColorStop(1, `${color}00`);
    ctx.beginPath();
    history.forEach((point, i) => {
      const x = padding.left + (i / Math.max(1, history.length - 1)) * plotW;
      const y = padding.top + (1 - normalize(point[key])) * plotH;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();
    if (key === "pressure") {
      ctx.lineTo(width - padding.right, height - padding.bottom);
      ctx.lineTo(padding.left, height - padding.bottom);
      ctx.closePath(); ctx.fillStyle = gradient; ctx.fill();
    }
  });
  ctx.fillStyle = "#91a0a4";
  ctx.fillText("60 个采样点前", padding.left, height - 7);
  ctx.textAlign = "right";
  ctx.fillText("现在", width - padding.right, height - 7);
  ctx.textAlign = "left";
}

function renderAlerts() {
  const counts = state.alerts.reduce((acc, a) => ({ ...acc, [a.status]: (acc[a.status] || 0) + 1 }), {});
  $("#summary-open").textContent = counts.open || 0;
  $("#summary-ack").textContent = counts.acknowledged || 0;
  $("#summary-resolved").textContent = counts.resolved || 0;
  const filtered = state.alertFilter === "all" ? state.alerts : state.alerts.filter((a) => a.status === state.alertFilter);
  $("#alert-table").innerHTML = filtered.length ? filtered.map((alert) => `
    <tr>
      <td><span class="level-cell"><i class="level-dot ${alert.level}"></i>${alert.level === "critical" ? "严重" : "警告"}</span></td>
      <td><b>${alert.title}</b><br><small>${alert.description}</small></td>
      <td>${alert.pipeline_name}<br><small>${alert.pipeline_id}</small></td>
      <td>${formatDateTime(alert.created_at)}</td>
      <td><span class="status-tag ${alert.status}">${alertStatusText[alert.status]}</span></td>
      <td>
        <div class="table-actions">
          <button class="ack-button" data-ack="${alert.id}" ${alert.status !== "open" ? "disabled" : ""}>${alert.status === "open" ? "确认" : "已确认"}</button>
          <button class="ack-button order" data-create-order="${alert.id}" ${alert.work_order_id ? "disabled" : ""}>${alert.work_order_id || "转工单"}</button>
        </div>
      </td>
    </tr>`).join("") : `<tr><td colspan="6" style="text-align:center;padding:30px;color:#89979c">当前筛选条件下暂无告警</td></tr>`;
  $$("[data-ack]").forEach((button) => button.addEventListener("click", () => acknowledgeAlert(button.dataset.ack)));
  $$("[data-create-order]").forEach((button) => button.addEventListener("click", () => createWorkOrder(button.dataset.createOrder)));
}

async function acknowledgeAlert(id) {
  try {
    await api(`/api/alerts/${id}/ack`, { method: "POST" });
    notify(`告警 ${id} 已确认`);
    await refreshAll({ quiet: true });
  } catch { notify("操作失败，请稍后重试"); }
}

async function createWorkOrder(alertId) {
  const alert = state.alerts.find((item) => item.id === alertId);
  if (!confirm(`将“${alert?.title}”转为运维工单？`)) return;
  try {
    const order = await api("/api/work-orders", {
      method: "POST",
      body: JSON.stringify({ alert_id: alertId, assignee: "值班运维组" }),
    });
    notify(`工单 ${order.id} 已创建`);
    await refreshAll({ quiet: true });
    navigate("workorders");
  } catch {
    notify("创建工单失败，请检查该告警是否已转工单");
  }
}

function renderWorkOrders() {
  const counts = state.workOrders.reduce(
    (acc, order) => ({ ...acc, [order.status]: (acc[order.status] || 0) + 1 }),
    {},
  );
  $("#work-total").textContent = state.workOrders.length;
  $("#work-pending").textContent = counts.pending || 0;
  $("#work-progress").textContent = counts.in_progress || 0;
  const completionRate = state.workOrders.length
    ? Math.round(((counts.completed || 0) / state.workOrders.length) * 100)
    : 0;
  $("#work-rate").textContent = `${completionRate}%`;

  const filtered = state.workFilter === "all"
    ? state.workOrders
    : state.workOrders.filter((order) => order.status === state.workFilter);
  $("#work-order-list").innerHTML = filtered.length ? filtered.map((order) => {
    const nextStatus = order.status === "pending"
      ? "in_progress"
      : order.status === "in_progress" ? "completed" : null;
    const actionText = order.status === "pending"
      ? "开始处理"
      : order.status === "in_progress" ? "完成工单" : "处置完成";
    return `
      <article class="panel work-order-card">
        <div class="work-order-head"><span class="work-order-code">${order.id}</span><span class="work-priority ${order.priority}">${priorityText[order.priority]}优先级</span></div>
        <h3>${order.title}</h3>
        <p>${order.description}</p>
        <div class="work-meta">
          <div><span>负责人员</span><b>${order.assignee}</b></div>
          <div><span>关联管线</span><b>${order.pipeline_id}</b></div>
          <div><span>要求完成</span><b>${formatDateTime(order.due_at)}</b></div>
        </div>
        <div class="work-footer">
          <span class="work-status ${order.status}">${workStatusText[order.status]}</span>
          <button class="work-action" data-work-id="${order.id}" data-work-status="${nextStatus || ""}" ${nextStatus ? "" : "disabled"}>${actionText}</button>
        </div>
      </article>`;
  }).join("") : `<article class="panel empty-state">当前筛选条件下暂无工单</article>`;

  $$("[data-work-id]").forEach((button) => button.addEventListener("click", () => {
    updateWorkOrder(button.dataset.workId, button.dataset.workStatus);
  }));
}

async function updateWorkOrder(id, status) {
  if (!status) return;
  try {
    const order = await api(`/api/work-orders/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    });
    notify(`${order.id} 已更新为“${workStatusText[order.status]}”`);
    await refreshAll({ quiet: true });
  } catch {
    notify("工单状态更新失败");
  }
}

function renderInspections() {
  if ($("#inspection-pipeline").options.length === 0) {
    const options = state.pipelines.map((pipeline) => `<option value="${pipeline.id}">${pipeline.name}</option>`).join("");
    $("#inspection-pipeline").innerHTML = options;
    $("#inspection-pipeline-filter").insertAdjacentHTML("beforeend", options);
  }
  const total = state.inspections.length;
  const planned = state.inspections.filter((item) => item.status === "planned").length;
  const inProgress = state.inspections.filter((item) => item.status === "in_progress").length;
  const overdue = state.inspections.filter((item) => item.is_overdue).length;
  $("#inspection-total").textContent = total;
  $("#inspection-planned").textContent = planned;
  $("#inspection-progress").textContent = inProgress;
  $("#inspection-overdue").textContent = overdue;

  const keyword = state.inspectionSearch.trim().toLowerCase();
  const filtered = state.inspections.filter((task) => {
    const matchesPipeline = state.inspectionPipelineFilter === "all"
      || task.pipeline_id === state.inspectionPipelineFilter;
    const matchesStatus = state.inspectionStatusFilter === "all"
      || (state.inspectionStatusFilter === "overdue" ? task.is_overdue : task.status === state.inspectionStatusFilter);
    const searchable = `${task.id} ${task.title} ${task.inspector} ${task.pipeline_name}`.toLowerCase();
    return matchesPipeline && matchesStatus && (!keyword || searchable.includes(keyword));
  });
  $("#inspection-result-count").textContent = `${filtered.length} 项任务`;
  $("#inspection-grid").innerHTML = filtered.length ? filtered.map((task) => {
    const visualStatus = task.is_overdue ? "overdue" : task.status;
    const statusLabel = task.is_overdue ? "已逾期" : inspectionStatusText[task.status];
    const action = task.status === "planned"
      ? `<button class="primary" data-inspection-start="${task.id}">开始巡检</button>`
      : task.status === "in_progress"
        ? `<button class="primary" data-inspection-complete="${task.id}">提交结论</button>`
        : `<button disabled>${inspectionResultText[task.result] || "已结项"}</button>`;
    const progressCopy = task.status === "planned" ? "等待现场人员开始"
      : task.status === "in_progress" ? `已于 ${formatDateTime(task.started_at)} 开始`
        : `已于 ${formatDateTime(task.completed_at)} 完成`;
    return `
      <article class="panel inspection-card ${task.status} ${task.is_overdue ? "overdue" : ""}">
        <div class="inspection-head">
          <div><span class="inspection-code">${task.id}</span><h3>${task.title}</h3><p>${task.pipeline_name} · ${task.pipeline_id}</p></div>
          <div class="inspection-badges"><span class="inspection-priority ${task.priority}">${priorityText[task.priority]}优先级</span><span class="inspection-status ${visualStatus}">${statusLabel}</span></div>
        </div>
        <div class="inspection-meta">
          <div><span>负责人</span><b>${task.inspector}</b></div>
          <div><span>计划时间</span><b>${formatDateTime(task.scheduled_at)}</b></div>
          <div><span>巡检结论</span><b>${inspectionResultText[task.result] || "待提交"}</b></div>
        </div>
        <div class="inspection-progress-line"><i></i><span>${progressCopy}</span></div>
        <p class="inspection-note">${task.notes || "暂无补充说明，按标准巡检清单执行。"}</p>
        <div class="inspection-checks">${task.checklist.map((item) => `<span>✓ ${item}</span>`).join("")}</div>
        <div class="inspection-actions">${action}</div>
      </article>`;
  }).join("") : `<article class="panel empty-state">没有找到符合筛选条件的巡检任务</article>`;

  $$('[data-inspection-start]').forEach((button) => button.addEventListener("click", () => {
    updateInspection(button.dataset.inspectionStart, "in_progress");
  }));
  $$('[data-inspection-complete]').forEach((button) => button.addEventListener("click", () => {
    $("#inspection-result-id").value = button.dataset.inspectionComplete;
    $("#inspection-result-notes").value = "";
    openModal("inspection-result-modal");
  }));
}

function openModal(id) {
  $("#" + id).classList.remove("hidden");
  document.body.style.overflow = "hidden";
}

function closeModal(id) {
  $("#" + id).classList.add("hidden");
  if (!$(".modal-backdrop:not(.hidden)")) document.body.style.overflow = "";
}

async function updateInspection(id, status, result = "", notes = "") {
  try {
    const task = await api(`/api/inspections/${id}/status`, {
      method: "POST", body: JSON.stringify({ status, result, notes }),
    });
    notify(status === "in_progress" ? `${task.id} 已开始巡检` : `${task.id} 已完成，结论已入库`);
    await refreshAll({ quiet: true });
  } catch {
    notify("巡检状态更新失败，请检查任务当前状态");
  }
}

function renderAnalytics() {
  if (!state.analytics) return;
  const {
    risk, alerts, work_orders: workOrders, devices: deviceStats, inspections,
    generated_at: generatedAt,
  } = state.analytics;
  const operationScore = Math.max(
    0,
    Math.round(
      100 - risk.average * 0.65 - (100 - alerts.closure_rate) * 0.12
      - deviceStats.offline * 4,
    ),
  );
  $("#operation-score").textContent = operationScore;
  $("#analytics-time").textContent = `${formatDateTime(generatedAt)} 生成 · 实时数据`;
  $("#analytics-conclusion").textContent = operationScore >= 90
    ? "管网总体运行平稳，风险处于可控范围"
    : operationScore >= 75 ? "管网运行基本稳定，需跟进未闭环事件" : "存在较高运行风险，请优先组织现场处置";
  $("#healthy-pipes").textContent = `${risk.healthy_pipelines} / ${state.pipelines.length} 条健康`;
  $("#pipeline-risk-bars").innerHTML = state.pipelines.map((pipeline) => {
    const score = pipeline.telemetry.risk.score;
    const level = pipeline.telemetry.risk.level;
    return `<div><div class="analytics-bar-head"><span>${pipeline.name}</span><b>${score} 分</b></div><div class="analytics-bar-track"><i class="${level}" style="width:${Math.max(2, score)}%"></i></div></div>`;
  }).join("");
  $("#closure-rate").textContent = `闭环率 ${alerts.closure_rate}%`;
  $("#closure-donut").style.setProperty("--closure", alerts.closure_rate);
  $("#closure-donut strong").textContent = `${Math.round(alerts.closure_rate)}%`;
  $("#analytics-alert-total").textContent = alerts.total;
  $("#analytics-work-total").textContent = workOrders.total;
  $("#analytics-work-rate").textContent = `${workOrders.completion_rate}%`;
  $("#analytics-device-rate").textContent = `在线率 ${deviceStats.online_rate}%`;
  $("#analytics-device-online").textContent = `${deviceStats.online} / ${deviceStats.total}`;
  $("#analytics-device-offline").textContent = deviceStats.offline;
  $("#analytics-device-due").textContent = deviceStats.calibration_due;
  $("#analytics-inspection-rate").textContent = `完成率 ${inspections.completion_rate}%`;
  $("#analytics-inspection-total").textContent = inspections.total;
  $("#analytics-inspection-progress").textContent = inspections.by_status.in_progress;
  $("#analytics-inspection-overdue").textContent = inspections.overdue;
  $("#operation-advice").textContent = deviceStats.offline > 0
    ? `当前有 ${deviceStats.offline} 台设备离线，建议优先检查设备供电、现场总线和边缘网关连接。`
    : inspections.overdue > 0
    ? `当前有 ${inspections.overdue} 项巡检任务逾期，建议优先联系负责人完成现场检查并回填结论。`
    : risk.maximum >= 65
    ? "检测到高风险管线，建议立即创建紧急工单，复核压力、流量与现场气体信号，并按预案隔离相关管段。"
    : workOrders.by_status.pending > 0
      ? `当前有 ${workOrders.by_status.pending} 条工单等待处理，建议完成责任分派并在要求时限内反馈现场结果。`
      : "当前风险与运维任务均处于受控状态，建议保持巡检频次并定期导出告警记录归档。";
}

function formatBytes(value) {
  if (!value) return "0 KB";
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / 1024 / 1024).toFixed(2)} MB`;
}

function renderDatabase() {
  if (!state.database) return;
  const database = state.database;
  const tableMap = Object.fromEntries(database.tables.map((table) => [table.name, table]));
  $("#db-engine").textContent = database.engine;
  $("#db-version").textContent = database.sqlite_version;
  $("#db-location").textContent = database.location;
  $("#db-last-write").textContent = database.last_telemetry_at
    ? formatDateTime(database.last_telemetry_at)
    : "等待首个采样";
  $("#db-size").textContent = `${formatBytes(database.size_bytes)} · Schema v${database.schema_version}`;
  $("#db-telemetry-count").textContent = tableMap.telemetry?.rows || 0;
  $("#db-alert-count").textContent = tableMap.alerts?.rows || 0;
  $("#db-work-count").textContent = tableMap.work_orders?.rows || 0;
  $("#db-device-count").textContent = tableMap.devices?.rows || 0;
  $("#db-inspection-count").textContent = tableMap.inspection_tasks?.rows || 0;
  $("#db-audit-count").textContent = tableMap.audit_logs?.rows || 0;
  $("#database-table-list").innerHTML = database.tables.map((table) => `
    <div class="database-table-row">
      <span class="table-symbol">▦</span>
      <div><b>${table.name}</b><small>${table.description}</small></div>
      <strong>${table.rows}<small>ROWS</small></strong>
    </div>`).join("");

  const actionText = {
    database_initialized: "数据库初始化",
    scenario_injected: "演示场景注入",
    alert_created: "系统生成告警",
    alert_acknowledged: "人工确认告警",
    work_order_created: "创建运维工单",
    work_order_status_changed: "更新工单状态",
    devices_registered: "设备资产入库",
    device_calibrated: "设备远程校准",
    device_status_changed: "设备状态变更",
    inspection_plans_registered: "巡检计划初始化",
    inspection_created: "创建巡检计划",
    inspection_started: "开始现场巡检",
    inspection_completed: "巡检正常结项",
    inspection_abnormal: "巡检异常上报",
  };
  $("#audit-log-list").innerHTML = state.auditLogs.length
    ? state.auditLogs.slice(0, 8).map((log) => `
      <div class="audit-log-row">
        <span class="audit-node"></span>
        <div><b>${actionText[log.action] || log.action}</b><p>${log.detail}</p><small>${formatDateTime(log.created_at)} · ${log.entity_id}</small></div>
      </div>`).join("")
    : `<div class="audit-empty">暂无操作审计记录</div>`;
}

function renderDevices() {
  const total = state.devices.length;
  const online = state.devices.filter((device) => device.status === "online").length;
  const averageSignal = total
    ? Math.round(state.devices.reduce((sum, device) => sum + device.signal, 0) / total)
    : 0;
  $("#device-total").textContent = total;
  $("#device-online").textContent = online;
  $("#device-offline").textContent = total - online;
  $("#device-online-rate").textContent = `在线率 ${Math.round(online / Math.max(1, total) * 100)}%`;
  $("#device-signal").textContent = `${averageSignal}%`;

  const keyword = state.deviceSearch.trim().toLowerCase();
  const filtered = state.devices.filter((device) => {
    const matchesStatus = state.deviceStatusFilter === "all"
      || device.status === state.deviceStatusFilter;
    const matchesType = state.deviceTypeFilter === "all"
      || device.type_code === state.deviceTypeFilter;
    const searchable = `${device.id} ${device.name} ${device.pipeline_name}`.toLowerCase();
    return matchesStatus && matchesType && (!keyword || searchable.includes(keyword));
  });
  $("#device-result-count").textContent = `${filtered.length} 台设备`;
  $("#device-grid").innerHTML = filtered.length ? filtered.map((device) => {
    const reading = device.reading === null || device.reading === undefined
      ? "—" : device.reading;
    const nextStatus = device.status === "online" ? "offline" : "online";
    return `
      <article class="panel device-card ${device.status}">
        <div class="device-card-head">
          <div class="device-identity"><span class="device-symbol">${device.type_code}</span><div><span>${device.id}</span><h3>${device.type_name}</h3></div></div>
          <span class="online-tag ${device.status}"><i></i>${device.status === "online" ? "在线" : "离线"}</span>
        </div>
        <div class="device-reading ${device.status}"><span>实时读数</span><strong>${reading}</strong><small>${device.unit}</small><em>${device.pipeline_name}</em></div>
        <div class="device-data">
          <div><span>量程 / 精度</span><b>${device.range_text}</b><small>${device.accuracy}</small></div>
          <div><span>通信协议</span><b>${device.protocol}</b><small>最后在线 ${formatTime(device.last_seen)}</small></div>
          <div><span>供电状态</span><b>${device.battery}%</b><div class="mini-progress"><i style="width:${device.battery}%"></i></div></div>
          <div><span>信号质量</span><b>${device.signal}%</b><div class="mini-progress signal"><i style="width:${device.signal}%"></i></div></div>
        </div>
        <div class="calibration-row"><span>上次校准 ${formatDate(device.calibrated_at)}</span><b class="${device.calibration_due ? "due" : ""}">${device.calibration_due ? "已到期" : `下次 ${formatDate(device.maintenance_due)}`}</b></div>
        <div class="device-actions">
          <button data-device-calibrate="${device.id}" ${device.status === "offline" ? "disabled" : ""}>⌖ 远程校准</button>
          <button class="${nextStatus === "offline" ? "offline" : "recover"}" data-device-toggle="${device.id}" data-device-next="${nextStatus}">${nextStatus === "offline" ? "模拟离线" : "恢复在线"}</button>
        </div>
      </article>`;
  }).join("") : `<article class="panel empty-state">没有找到符合筛选条件的设备</article>`;

  $$('[data-device-calibrate]').forEach((button) => button.addEventListener("click", () => {
    calibrateDevice(button.dataset.deviceCalibrate);
  }));
  $$('[data-device-toggle]').forEach((button) => button.addEventListener("click", () => {
    updateDeviceStatus(button.dataset.deviceToggle, button.dataset.deviceNext);
  }));
}

async function calibrateDevice(id) {
  try {
    await api(`/api/devices/${id}/calibrate`, { method: "POST", body: "{}" });
    notify(`${id} 远程校准完成，下次周期已更新`);
    await refreshAll({ quiet: true });
  } catch {
    notify("设备校准失败，请检查设备连接");
  }
}

async function updateDeviceStatus(id, status) {
  const action = status === "offline" ? "模拟设备离线" : "恢复设备在线";
  if (!confirm(`确认${action}“${id}”？`)) return;
  try {
    await api(`/api/devices/${id}/status`, {
      method: "POST", body: JSON.stringify({ status }),
    });
    notify(`${id} 已${status === "offline" ? "离线，系统已生成告警" : "恢复在线"}`);
    await refreshAll({ quiet: true });
  } catch {
    notify("设备状态更新失败");
  }
}

function navigate(target) {
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.target === target));
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === `${target}-view`));
  const titles = {
    overview: "管网运行总览",
    pipelines: "管线实时监测",
    alerts: "告警处置中心",
    workorders: "运维工单中心",
    devices: "感知设备管理",
    inspections: "管线巡检计划",
    analytics: "运行分析报告",
    database: "持久化数据中心",
  };
  $("#page-title").textContent = titles[target];
  if (target === "pipelines") {
    renderSelectors();
    loadPipelineDetail(state.selectedPipeline);
  }
  if (target === "workorders") renderWorkOrders();
  if (target === "inspections") renderInspections();
  if (target === "analytics") renderAnalytics();
  if (target === "database") renderDatabase();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

$$(".nav-item").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.target)));
$$("[data-jump]").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.jump)));
$("#refresh-btn").addEventListener("click", () => refreshAll());
$("#simulate-btn").addEventListener("click", async () => {
  const pipeline = state.pipelines.find((p) => p.id === state.selectedPipeline);
  if (!confirm(`确认向“${pipeline?.name}”注入模拟泄漏数据？\n该操作仅影响演示数据。`)) return;
  try {
    await api("/api/simulate/leak", { method: "POST", body: JSON.stringify({ pipeline_id: state.selectedPipeline }) });
    notify("泄漏场景已注入，风险曲线正在变化");
    await refreshAll({ quiet: true });
  } catch { notify("场景注入失败"); }
});
$$("[data-filter]").forEach((button) => button.addEventListener("click", () => {
  state.alertFilter = button.dataset.filter;
  $$("[data-filter]").forEach((b) => b.classList.toggle("active", b === button));
  renderAlerts();
}));
$$("[data-work-filter]").forEach((button) => button.addEventListener("click", () => {
  state.workFilter = button.dataset.workFilter;
  $$("[data-work-filter]").forEach((item) => item.classList.toggle("active", item === button));
  renderWorkOrders();
}));
$$("[data-device-status]").forEach((button) => button.addEventListener("click", () => {
  state.deviceStatusFilter = button.dataset.deviceStatus;
  $$("[data-device-status]").forEach((item) => item.classList.toggle("active", item === button));
  renderDevices();
}));
$("#device-type-filter").addEventListener("change", (event) => {
  state.deviceTypeFilter = event.target.value;
  renderDevices();
});
$("#device-search").addEventListener("input", (event) => {
  state.deviceSearch = event.target.value;
  renderDevices();
});
$$('[data-inspection-status]').forEach((button) => button.addEventListener("click", () => {
  state.inspectionStatusFilter = button.dataset.inspectionStatus;
  $$('[data-inspection-status]').forEach((item) => item.classList.toggle("active", item === button));
  renderInspections();
}));
$("#inspection-pipeline-filter").addEventListener("change", (event) => {
  state.inspectionPipelineFilter = event.target.value;
  renderInspections();
});
$("#inspection-search").addEventListener("input", (event) => {
  state.inspectionSearch = event.target.value;
  renderInspections();
});
$("#new-inspection-btn").addEventListener("click", () => {
  const scheduled = new Date(Date.now() + 2 * 60 * 60 * 1000);
  const local = new Date(scheduled.getTime() - scheduled.getTimezoneOffset() * 60000);
  $("#inspection-scheduled").value = local.toISOString().slice(0, 16);
  openModal("inspection-modal");
});
$$('[data-close-modal]').forEach((button) => button.addEventListener("click", () => closeModal(button.dataset.closeModal)));
$$('.modal-backdrop').forEach((modal) => modal.addEventListener("click", (event) => {
  if (event.target === modal) closeModal(modal.id);
}));
$("#inspection-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const checklist = $$('.inspection-checklist input:checked').map((item) => item.value);
  try {
    const task = await api("/api/inspections", {
      method: "POST",
      body: JSON.stringify({
        pipeline_id: $("#inspection-pipeline").value,
        title: $("#inspection-title").value,
        inspector: $("#inspection-inspector").value,
        scheduled_at: new Date($("#inspection-scheduled").value).toISOString(),
        priority: $("#inspection-priority").value,
        notes: $("#inspection-notes").value,
        checklist,
      }),
    });
    closeModal("inspection-modal");
    event.target.reset();
    notify(`${task.id} 巡检计划已创建`);
    await refreshAll({ quiet: true });
  } catch {
    notify("巡检计划创建失败，请完整填写必填项");
  }
});
$("#inspection-result-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const result = $('input[name="inspection-result"]:checked').value;
  const notes = $("#inspection-result-notes").value;
  if (result === "abnormal" && !notes.trim()) {
    notify("发现异常时，请填写具体位置和现象");
    return;
  }
  const id = $("#inspection-result-id").value;
  closeModal("inspection-result-modal");
  await updateInspection(id, "completed", result, notes);
});
window.addEventListener("resize", () => loadPipelineDetail(state.selectedPipeline));

refreshAll({ quiet: true });
state.refreshTimer = setInterval(() => refreshAll({ quiet: true }), 5000);
