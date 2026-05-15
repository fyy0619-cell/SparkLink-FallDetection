# 数据集说明

## 目录

```
datasets/
├── normal.csv      # 正常行为数据（行走、站立、坐下）
├── fall.csv        # 跌倒数据（模拟各方向跌倒）
└── README.md       # 本文件
```

> 注：`normal.csv` / `fall.csv` 为采集数据，未随仓库提交；本文件说明其格式与采集规范。

---

## 数据格式

```csv
timestamp_ms,accel_x,accel_y,accel_z,gyro_x,gyro_y,gyro_z,label
0,0.12,-0.05,0.98,1.2,-0.3,0.8,normal
5,0.15,-0.04,0.97,1.1,-0.2,0.9,normal
...
```

| 字段 | 单位 | 说明 |
|------|------|------|
| `timestamp_ms` | ms | 采样时间戳，间隔5ms（200Hz） |
| `accel_x/y/z` | g | 三轴加速度（±4g量程） |
| `gyro_x/y/z` | °/s | 三轴角速度（±500°/s量程） |
| `label` | - | `normal` 或 `fall` |

---

## 采集规范

- **采样率**：200Hz（每5ms一帧）
- **窗口大小**：256采样点（约1.28秒）
- **每类样本数**：至少200个窗口

---

## SisFall Enhanced数据集

**官网**：http://sistemic.udea.edu.co/en/research/projects/sisfall/

下载后需要预处理：
1. 原始采样率200Hz，与本项目模型一致，无需降采样
2. 将ADC原始值转换为物理量（g 和 °/s）
3. 按窗口大小（256采样点）切分并导出为上述CSV格式

SisFall 二分类归并与 CSV 整理的完整过程，见 [EdgeImpulse_训练数据全过程](../docs/04-TinyML模型/EdgeImpulse_训练数据全过程_2026-05-07.md)。
