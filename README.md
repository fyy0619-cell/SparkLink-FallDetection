# 星闪跌倒检测系统 | SparkLink Fall Detection

> 基于海思WS63开发板 + LiteOS + TinyML + SLE星闪协议的智能跌倒检测系统  
> 研究方向：嵌入式AI · 星闪通信 · 边缘推理

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
| 阶段三 | 数据采集与处理 | [📄 查看](docs/03-数据采集/) |
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
├── docs/
│   ├── 日志/                   # 按日期整理的开发日志
│   ├── 01-环境搭建/             # SDK编译、LiteOS、C++移植
│   ├── 02-硬件驱动/             # I2C、MPU6050、GPIO配置
│   ├── 03-数据采集/             # 传感器数据、滑动窗口
│   ├── 04-TinyML模型/           # Edge Impulse训练与部署
│   ├── 05-通信协议/             # SLE与BLE原理与实现
│   └── 06-系统集成/             # 电源管理、任务调度
├── src/
│   ├── drivers/mpu6050/         # MPU6050驱动代码
│   ├── tinyml/model/            # 部署用TinyML模型
│   ├── communication/
│   │   ├── sle/                 # 星闪SLE协议实现
│   │   └── ble/                 # BLE蓝牙实现
│   └── app/fall_detection/      # 跌倒检测主应用
├── datasets/                    # 训练数据集
│   ├── normal.csv
│   └── fall.csv
├── models/edge_impulse/         # Edge Impulse导出的模型文件
└── tools/data_collection/       # 数据采集工具脚本
```

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

---

## 参考资料

- [海思WS63官方SDK文档]
- [Edge Impulse官方文档](https://docs.edgeimpulse.com)
- [SisFall数据集](http://sistemic.udea.edu.co/en/research/projects/sisfall/)
- [LiteOS开源仓库](https://gitee.com/LiteOS/LiteOS)
- [星闪联盟官网](https://www.sparklink.org.cn)

---

## Latest Debug Reports

- CN: [fall-detect-sle-debug-summary-2026-04-29](docs/fall-detect-sle-debug-summary-2026-04-29.md)
- EN: [fall-detect-sle-debug-summary-2026-04-29-en](docs/fall-detect-sle-debug-summary-2026-04-29-en.md)

- CN: [EdgeImpulse_WS63_部署调试记录_2026-05-07](docs/04-TinyML模型/EdgeImpulse_WS63_部署调试记录_2026-05-07.md)
- CN: [EdgeImpulse_训练数据全过程_2026-05-07](docs/04-TinyML模型/EdgeImpulse_训练数据全过程_2026-05-07.md)

## 远程报警与户外化方案

- CN: [远程报警链路与户外化方案-2026-05-10](docs/06-系统集成/远程报警链路与户外化方案-2026-05-10.md)
- Tool: [fall_alert_backend_demo.py](tools/fall_alert_backend_demo.py) - 支持 dry-run、PushPlus 微信推送、腾讯云短信/语音预留。
- Env: [fall_alert_backend.env.example](tools/fall_alert_backend.env.example) - 后端环境变量模板，不包含真实密钥。

当前已验证链路：Board A 跌倒检测 -> SLE 0x05 -> Board B 本地声光报警 -> Wi-Fi HTTP -> Python 后端 -> PushPlus 微信通知。

户外产品化方向：将 Wi-Fi 网关替换为 4G Cat.1/DTU + GPS/北斗，实现脱离电脑和局域网的独立报警。
