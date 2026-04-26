# 数据集说明

## 目录

```
datasets/
├── normal.csv      # 正常行为数据（行走、站立、坐下）
├── fall.csv        # 跌倒数据（模拟各方向跌倒）
└── README.md       # 本文件
```

---

## 数据格式

```csv
timestamp_ms,accel_x,accel_y,accel_z,gyro_x,gyro_y,gyro_z,label
0,0.12,-0.05,0.98,1.2,-0.3,0.8,normal
20,0.15,-0.04,0.97,1.1,-0.2,0.9,normal
...
```

| 字段 | 单位 | 说明 |
|------|------|------|
| `timestamp_ms` | ms | 采样时间戳，间隔20ms（50Hz） |
| `accel_x/y/z` | g | 三轴加速度（±2g量程） |
| `gyro_x/y/z` | °/s | 三轴角速度（±250°/s量程） |
| `label` | - | `normal` 或 `fall` |

---

## 采集规范

- **采样率**：50Hz（每20ms一帧）
- **窗口大小**：100帧（2秒）
- **每类样本数**：至少200个窗口

---

## SisFall Enhanced数据集

**官网**：http://sistemic.udea.edu.co/en/research/projects/sisfall/

下载后需要预处理：
1. 原始采样率200Hz，需要降采样到50Hz
2. 将ADC原始值转换为物理量（g 和 °/s）
3. 按窗口大小切分并导出为上述CSV格式

预处理脚本见：`tools/data_collection/preprocess_sisfall.py`
