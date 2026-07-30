# PipeGuard 油气管道智能监测与泄漏预警系统

> 工业互联网概论课程小组项目：利用多源传感、边缘计算与云端可视化，实现油气管道运行状态监测、泄漏风险研判和告警处置闭环。

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-zero-0b8b80)](#快速开始)
[![License](https://img.shields.io/badge/license-MIT-2ea44f)](LICENSE)

## 项目简介

油气管道通常跨区域、环境复杂，单一传感器容易受到工况波动或设备噪声干扰。PipeGuard 构建了一个“端—边—云”工业互联网原型：

- **端侧感知**：模拟压力、进出口流量、可燃气体和振动等工业传感器；
- **边缘分析**：通过质量守恒与多信号关联，在数据源附近实时计算风险；
- **平台服务**：提供统一 HTTP API、设备状态与告警生命周期管理；
- **应用展示**：以 Web 监控大屏展示管网状态、趋势、研判依据和处置结果。

项目只使用 Python 标准库和原生 HTML/CSS/JavaScript，无需安装第三方依赖，适合课堂演示和原理讲解。

## 功能亮点

- 三条在役管线与 12 台感知设备的实时数据模拟
- 压力、流量、气体、振动四信号加权融合
- 0–100 风险评分、三级风险分级及可解释研判依据
- 监控总览、管线趋势、设备管理、告警中心四个功能页面
- 泄漏场景一键注入，便于现场答辩演示
- 告警产生、确认、恢复状态的闭环管理
- 响应式页面，适配桌面、平板和手机
- 标准库单元测试与 API 集成测试

## 快速开始

环境要求：Python 3.10 或更高版本。

```bash
git clone https://github.com/lihanyu050826/PipeGuard.git
cd PipeGuard
python run.py
```

浏览器访问 [http://127.0.0.1:8000](http://127.0.0.1:8000)。

也可指定监听地址和端口：

```bash
python run.py --host 0.0.0.0 --port 8080
```

### 演示泄漏预警

1. 打开“管线监测”；
2. 选择任意管线；
3. 点击右上角“注入泄漏演示”并确认；
4. 观察压力下降、进出口流量差增大和风险分上升；
5. 进入“告警中心”，点击“确认告警”完成处置闭环。

> “注入泄漏演示”仅修改内存中的模拟数据，重启服务即可复位。

## 系统架构

```mermaid
flowchart LR
    subgraph Device["端侧：现场感知层"]
        P["压力传感器"]
        F["超声波流量计"]
        G["气体探测器"]
        V["振动传感器"]
    end
    subgraph Edge["边缘层"]
        GW["工业边缘网关"]
        ALG["多源融合与风险评分"]
    end
    subgraph Platform["平台层"]
        API["HTTP 数据服务"]
        EVENT["告警与设备管理"]
    end
    subgraph App["应用层"]
        DASH["可视化监控大屏"]
        USER["运维人员"]
    end
    P & F & G & V -->|MQTT / 工业协议| GW
    GW --> ALG
    ALG -->|风险结果| API
    API <--> EVENT
    API --> DASH --> USER
    USER -->|告警确认| EVENT
```

详细设计见 [系统架构文档](docs/architecture.md)。

## 泄漏风险算法

系统使用可解释的规则融合模型：

```text
基础风险 = 0.34 × 压降异常
         + 0.36 × 流量不平衡
         + 0.20 × 气体浓度异常
         + 0.10 × 振动异常
```

当压降与流量不平衡同时显著出现时增加相关性权重，以降低单传感器误报。最终分级如下：

| 风险分 | 级别 | 系统动作 |
| --- | --- | --- |
| 0–34 | 正常 | 持续采样 |
| 35–64 | 警告 | 提示关注、加密采样 |
| 65–100 | 严重 | 产生泄漏告警并进入处置流程 |

该算法强调课程演示中的透明性。实际生产系统需利用真实工况数据校准阈值，并与负压波、声学检测或机器学习模型交叉验证。

## 项目结构

```text
PipeGuard/
├─ pipeguard/
│  ├─ risk.py          # 多源融合风险算法
│  ├─ store.py         # 实时数据、告警与模拟器
│  └─ server.py        # HTTP API 与静态资源服务
├─ web/
│  ├─ index.html       # 监控平台页面
│  ├─ styles.css       # 响应式视觉样式
│  └─ app.js           # API 调用、图表与交互
├─ tests/              # 单元测试与 API 测试
├─ docs/               # 课程报告、架构、API 和答辩资料
├─ run.py              # 启动入口
├─ Dockerfile
└─ README.md
```

## 测试

```bash
python -m unittest discover -s tests -v
```

测试覆盖正常、警告、严重风险识别，相关信号增强、接口健康检查、管线查询、404 处理、泄漏注入和告警确认。

## 文档

- [课程项目报告](docs/course-report.md)
- [系统架构设计](docs/architecture.md)
- [HTTP API 文档](docs/api.md)
- [答辩演示提纲](docs/presentation.md)
- [小组协作建议](docs/teamwork.md)

## 安全与适用范围

本仓库是用于教学和原型验证的模拟系统，不应直接用于真实油气管道生产控制。生产落地还需要工业防火墙、TLS 双向认证、设备身份管理、时序数据库、冗余部署、安全仪表系统联锁，以及符合行业规范的现场验证。

## 许可证

[MIT License](LICENSE) © 2026 PipeGuard Team
