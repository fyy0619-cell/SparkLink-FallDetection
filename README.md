# 星闪跌倒检测系统 | SparkLink Fall Detection

> 基于海思WS63开发板 + LiteOS + TinyML + SLE星闪协议的智能跌倒检测系统  
> 研究方向：嵌入式AI · 星闪通信 · 边缘推理

---

## 🎯 演示快速开始

现场演示/答辩/路演的人,先看这三份速查,**不用读项目其它任何文档**:

| 我要做的事 | 看这份 |
| --- | --- |
| 改电话号 / WiFi / 后端 IP / PushPlus token | [📄 现场配置速查](docs/06-系统集成/现场配置速查.md) |
| 看引脚 / 接线 / 灯带 / 蜂鸣器 / V100C 怎么接 | [📄 硬件接线速查](docs/06-系统集成/硬件接线速查.md) |
| 演示前自检 + 讲者脚本 + 现场故障回退预案 | [📄 演示手册](docs/06-系统集成/演示手册.md) |

设计原理(更深层的解释)在 [`远程报警链路与户外化方案-2026-05-10.md`](docs/06-系统集成/远程报警链路与户外化方案-2026-05-10.md)。

---

## 项目简介

本项目是一套运行在**海思WS63开发板（LiteOS）** 上的跌倒检测系统，通过MPU6050采集三轴加速度与陀螺仪数据，利用 **Edge Impulse** 训练TinyML模型并部署到端侧进行实时推理，同时集成**SLE（星闪）与BLE双协议**实现无线数据传输。

### 系统架构

```
┌─────────────────────────────────────────────────┐
│               星闪开发板 (HiSilicon WS63)         │
│                   LiteOS RTOS                    │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ MPU6050  │  │ TinyML   │  │  SLE / BLE    │  │
│  │ I2C采集  │→ │ 端侧推理 │→ │  无线传输     │  │
│  │ X,Y,Z轴  │  │ 跌倒判断 │  │  双协议支持   │  │
│  └──────────┘  └──────────┘  └───────────────┘  │
└─────────────────────────────────────────────────┘
         ↕ SLE星闪协议
┌──────────────────┐      ┌──────────────────────┐
│  手机/华为设备    │      │   另一块开发板（主控）  │
│  BLE接收端       │      │   SLE中继/处理节点     │
└──────────────────┘      └──────────────────────┘
```

### 核心技术栈

| 层次 | 技术 |
|------|------|
| 硬件 | HiSilicon WS63、MPU6050、MH-CD42锂电管理 |
| 系统 | LiteOS（华为轻量级RTOS） |
| 驱动 | I2C（GPIO15/16）、C/C++混合编译 |
| 外设 | WS2812B RGB灯带（单总线时序驱动） |
| AI推理 | Edge Impulse → TinyML模型 → LiteOS部署 |
| 通信 | SLE（星闪）、BLE（蓝牙低功耗） |
| 工程规范 | UTF-8（无BOM）源码编码、Git文本管理、PowerShell编码修复脚本 |
| 数据集 | SisFall Enhanced + 自采数据（normal/fall） |

---

## 快速导航

| 阶段 | 内容 | 文档 |
|------|------|------|
| 阶段一 | 环境搭建与SDK配置 | [📄 查看](docs/01-环境搭建/) |
| 阶段二 | MPU6050硬件驱动 | [📄 查看](docs/02-硬件驱动/) |
| 阶段三 | 数据采集与处理 | [📄 查看](datasets/README.md) |
| 阶段四 | TinyML模型训练与部署 | [📄 查看](docs/04-TinyML模型/) |
| 阶段五 | SLE/BLE通信协议 | [📄 查看](docs/05-通信协议/) |
| 阶段六 | 系统集成与优化 | [📄 查看](docs/06-系统集成/) |
| 日志 | 开发日志（按日期） | [📄 查看](docs/日志/) |

---

## 学习路线

详见 👉 [ROADMAP.md](ROADMAP.md)

---

## 仓库结构

```
SparkLink-FallDetection/
├── README.md                   # 项目总览（本文件）
├── ROADMAP.md                  # 完整学习路线图
├── .gitignore
├── docs/
│   ├── 01-环境搭建/             # SDK编译、LiteOS、C++移植
│   ├── 02-硬件驱动/             # MPU6050驱动、WS2812B灯光报警驱动
│   ├── 04-TinyML模型/           # Edge Impulse训练与部署
│   ├── 05-通信协议/             # SLE与BLE原理
│   ├── 06-系统集成/             # 通知链路、功耗、远程报警
│   ├── 日志/                   # 按日期整理的开发日志
│   └── fall-detect-sle-debug-summary-2026-04-29(.md / -en.md)
├── datasets/
│   └── README.md               # 数据集格式与采集规范说明
└── tools/                       # 远程报警 / 4G拨号脚本
    ├── fall_alert_backend_demo.py     # Python 告警后端 Demo
    ├── fall_alert_backend.env.example # 后端环境变量模板
    ├── V100C_PASTE_THIS_TO_TASK1.lua  # V100C 任务1可直接粘贴脚本
    ├── v100c_uart_call_task.lua
    └── v100c_min_call_test.lua
```

> 说明：本仓库为**学习与文档仓库**，WS63 工程源码在独立的 SDK 工程中维护，未纳入本仓库。

---

## 开发记录摘要

- **2026.03.25** — 首次将星闪开发板蓝牙与手机端成功连接
- **2026.03.29** — 解决MPU6050 I2C接口配置（GPIO15/16），修复地址兼容性
- **2026.03.30** — 引入TinyML解决姿态误判，准备 normal/fall 数据集
- **2026.04.02** — 攻克C++编译链在LiteOS上的移植难题
- **2026.04.11** — 跌倒检测推理流程全链路跑通
- **2026.04.21** — 系统学习星闪SLE与BLE原理
- **2026.04.24** — 解决SLE+雷达并行时的供电不足问题
- **2026.04.26** — 修复SLE SSAP通知链路（服务发现 + CCCD + 激活写）
- **2026.04.30** — 修复中文注释乱码，统一UTF-8（无BOM）编码规范
- **2026.05.01** — 完成WS2812B灯带告警集成（时序调参 + 告警闪烁任务）
- **2026.05.07** — 完成Edge Impulse模型部署调试，梳理训练数据全过程
- **2026.05.09** — 打通Board B Wi-Fi网关、HTTP后端与PushPlus微信远程报警闭环
- **2026.05.10** — 形成户外化4G Cat.1/DTU方案，补充V100C/Air780EHV串口JSON触发电话的接入设计
- **2026.05.11** — 结合银尔达V100C与Air780 API文档，确认外部RXD/TXD使用`UartGetRecChAndDel(1)`并补充小白版DTU原理说明
- **2026.05.11** — 在WS63工程侧准备`fall_alert_4g_dtu.*`，Board B收到`0x05`后可通过UART1向V100C发送跌倒JSON
- **2026.05.13** — 完成银尔达V100C/Air780EHV串口拨号联调，跑通「跌倒JSON → UART → 4G电话告警」链路
- **2026.05.15** — 修复WS2812B灯带数据时序失真（颜色错乱/灯珠不亮），改用RISC-V周期计数器+TCXO主频自标定，并将报警闪烁降到2.5Hz
- **2026.05.18** — 集成腰部自采数据训练的Edge Impulse卷积网络模型，构建「路径B触发+NN复核否决」混合判定；解决移植层缺口、posix链接冲突、C++全局构造不可靠等6个集成问题，并新增`[Monitor]`状态监控日志；补充采样时序专题（Tick原理与硬件定时器200Hz采样管线、端到端时延预算）

---

## 参考资料

- 海思 WS63 官方 SDK 文档（随开发板 SDK 发布）
- [Edge Impulse官方文档](https://docs.edgeimpulse.com)
- [SisFall数据集](http://sistemic.udea.edu.co/en/research/projects/sisfall/)
- [LiteOS开源仓库](https://gitee.com/LiteOS/LiteOS)
- [星闪联盟官网](https://www.sparklink.org.cn)

---

## Latest Debug Reports

- CN: [fall-detect-sle-debug-summary-2026-04-29](docs/fall-detect-sle-debug-summary-2026-04-29.md)
- EN: [fall-detect-sle-debug-summary-2026-04-29-en](docs/fall-detect-sle-debug-summary-2026-04-29-en.md)

- CN: [EdgeImpulse_模型部署全流程_小白指南](docs/04-TinyML模型/EdgeImpulse_模型部署全流程_小白指南.md) — 模型如何一步步部署进 WS63 工程
- CN: [EdgeImpulse_WS63_部署调试记录_2026-05-07](docs/04-TinyML模型/EdgeImpulse_WS63_部署调试记录_2026-05-07.md)
- CN: [EdgeImpulse_训练数据全过程_2026-05-07](docs/04-TinyML模型/EdgeImpulse_训练数据全过程_2026-05-07.md)
- CN: [实时性·可靠性·星闪优势量化分析](docs/06-系统集成/实时性_可靠性_星闪优势量化分析.md) — 系统级实时性 / 可靠性 / SLE 优势量化
- CN: [性能测试与SLE延迟验证方法](docs/06-系统集成/性能测试与SLE延迟验证方法.md) — 如何实测 SLE 延迟 / 推理耗时（可复现操作手册）

## 远程报警与户外化方案

- CN: [V100C_Air780EHV_UART_call_debug_2026-05-13](docs/06-系统集成/V100C_Air780EHV_UART_call_debug_2026-05-13.md)
- CN: [V100C 短信告警实现](docs/06-系统集成/V100C_短信告警实现.md) - 跌倒时除拨号外，给指定号码发短信
- Tool: [V100C_PASTE_THIS_TO_TASK1.lua](tools/V100C_PASTE_THIS_TO_TASK1.lua) - 银尔达 V100C 后台任务1可直接粘贴脚本，读取 WS63 UART JSON 后拨号 + 发短信。
- CN: [远程报警链路与户外化方案-2026-05-10](docs/06-系统集成/远程报警链路与户外化方案-2026-05-10.md)
- Tool: [fall_alert_backend_demo.py](tools/fall_alert_backend_demo.py) - 支持 dry-run、PushPlus 微信推送、腾讯云短信/语音预留。
- Env: [fall_alert_backend.env.example](tools/fall_alert_backend.env.example) - 后端环境变量模板，不包含真实密钥。

当前已验证链路：Board A 跌倒检测 -> SLE 0x05 -> Board B 本地声光报警 -> Wi-Fi HTTP -> Python 后端 -> PushPlus 微信通知。

户外产品化方向：将 Wi-Fi 网关替换为 4G Cat.1/DTU + GPS/北斗，实现脱离电脑和局域网的独立报警。
