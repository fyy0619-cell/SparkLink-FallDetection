# SLE（星闪）与BLE（蓝牙低功耗）对比

## 协议概览

| 对比项 | BLE（Bluetooth Low Energy） | SLE（SparkLink Low Energy，星闪） |
|--------|---------------------------|----------------------------------|
| 标准组织 | Bluetooth SIG（国际） | 星闪联盟（中国主导） |
| 频段 | 2.4GHz ISM | 2.4GHz ISM |
| 速率 | 最高2Mbps | 最高12Mbps（理论） |
| 时延 | ~6ms | <2ms（理论） |
| 设备支持 | 几乎所有手机/设备 | 部分华为手机 + 星闪开发板 |
| 定位精度 | 约1-3m | 厘米级（配合UWB） |
| API复杂度 | 成熟，文档丰富 | 新兴，文档有限 |

---

## 当前实际情况（2026年）

- SLE仅在**部分华为手机型号**与星闪开发板之间支持
- 普通Android/iOS手机**不支持SLE**，只能用BLE
- 因此推荐策略：**双协议方案**

```
手机端（Android）←── BLE ──→ WS63开发板A（主控）
                              ↕ SLE
                          WS63开发板B（传感节点）
```

这样SLE用于高速板间通信，BLE用于与手机交互，发挥各自优势。

---

## BLE连接状态机

```
[IDLE] → 广播(ADV) → [ADVERTISING]
    ←── 扫描发现 ───
[SCANNING] → 发起连接请求 → [CONNECTING]
    ←── 连接建立 ───
[CONNECTED] → 数据传输 → [DATA EXCHANGE]
```

### 常见问题：扫描到但无法连接

检查广播数据包：

```c
// 广播类型必须是 connectable undirected
adv_param.type = BLE_ADV_TYPE_IND;  // 可连接的非定向广播
// 不要用 BLE_ADV_TYPE_NONCONN_IND（不可连接）
```

### 常见问题：连接后立即断开

检查连接参数：

```c
conn_param.min_interval = 0x0010;   // 20ms
conn_param.max_interval = 0x0030;   // 60ms
conn_param.latency = 0;
conn_param.supervision_timeout = 0x00C8;  // 2000ms（不要太短）
```

---

## SLE板间通信基本流程

```c
// 节点A：作为SLE Server（发起广播）
sle_announce_param_t ann_param;
ann_param.announce_type = SLE_ANNOUNCE_TYPE_CONNECTABLE_UNDIRECTED;
sle_start_announce(0, &ann_param);

// 节点B：作为SLE Client（扫描并连接）
sle_start_scan(&scan_param);
// 扫描回调中发现目标设备后
sle_connect_remote_device(&connect_addr);
```

> **坑**：SLE的API与BLE完全不同，不要混用。SLE头文件在SDK的 `middleware/services/communication/sle/` 目录下。

---

## 驱动文件定位技巧

在SDK中找不到文件时：

```bash
# 找BLE相关头文件
grep -r "ble_gap" middleware/ --include="*.h" -l
grep -r "sle_connection" middleware/ --include="*.h" -l

# 找回调函数注册接口
grep -r "register_.*callback" middleware/services/communication/
```
