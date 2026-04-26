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

## SLE SSAP 通知机制（Notify）深度解析

> 本节记录 2026.04.26 调试 SLE Notify 全链路时踩过的两个关键坑，以及最终可运行的完整方案。

### SSAP 通知的完整握手流程

```
[Server - 板A]                           [Client - 板B]
  enable_sle()
  ssaps_register_server()
  ssaps_add_service_sync()
  ssaps_add_property_sync()
  ssaps_add_descriptor_sync(CCCD)  ← 必须！否则 Notify 在协议栈被静默丢弃
  ssaps_start_service()
  sle_uuid_server_adv_init()       广播 →
                                          sle_set_seek_param(seek_phys=1)
                                          sle_start_seek()
                                   ← 扫描发现 MAC=11:22:33:44:55:66
                                          sle_stop_seek()
                                          sle_connect_remote_device()
  connect_state_changed_cb ←── 连接建立 ──→ connect_state_changed_cb
  g_sle_conn_hdl = conn_id                 sle_pair_remote_device()
                                   ← 配对完成
                                          ssapc_exchange_info_req(MTU=512)
                                   ← MTU 协商完成
                                          ssapc_find_structure()  ← 必须！否则通知不路由到应用层
                                   ← 服务发现完成（start_hdl=0x10）
                                          ssapc_write_req(handle, 0x01)  激活通知
  ssaps_write_request_cbk 触发
  (通知通道激活)
  ...跌倒检测...
  ssaps_notify_indicate(data=0x05) ──────────────────────────────→ notification_cb 触发
                                          GPIO_09 LED 点亮
                                          osal_printk("FALL")
                                          ssapc_write_req(0x06) ACK
  ssaps_write_request_cbk(0x06) ←────────────────────────────────
  打印 "ACK received from client!"
```

---

### 坑1：客户端缺少服务发现（ssapc_find_structure）

**现象**：服务端 `ssaps_notify_indicate` 返回 SUCCESS，客户端 `notification_cb` 永不触发。

**根本原因**：WS63 SLE 协议栈要求客户端完成服务发现后，才会将 Notify 包路由到应用层。未调用则通知在协议栈内部静默丢弃。

**修复**：在 MTU 协商完成回调中立即调用服务发现：

```c
// my_sle_exchange_info_cbk 内
static void my_sle_exchange_info_cbk(uint8_t client_id, uint16_t conn_id,
    ssap_exchange_info_t *param, errcode_t status)
{
    osal_printk("[CLIENT] MTU exchange done: mtu=%d\r\n", param->mtu_size);

    ssapc_find_structure_param_t find_param = {0};
    find_param.type      = SSAP_FIND_TYPE_PRIMARY_SERVICE;
    find_param.start_hdl = 1;
    find_param.end_hdl   = 0xFFFF;
    ssapc_find_structure(client_id, conn_id, &find_param);
}
```

服务发现结果通过两个回调返回，**两个都必须注册**：

```c
ssapc_cbk.find_structure_cb     = my_sle_find_structure_cbk;     // 每发现一条服务触发
ssapc_cbk.find_structure_cmp_cb = my_sle_find_structure_cmp_cbk; // 所有服务发现完毕触发
```

---

### 坑2：服务端缺少 CCCD 描述符

**现象**：服务发现成功（`start_hdl=0x10 end_hdl=0x11`），但跌倒后客户端仍无反应。

**根本原因**：SLE SSAP 与 BLE 一样存在 CCCD（Client Configuration Descriptor）机制。服务端属性必须注册 `SSAP_DESCRIPTOR_CLIENT_CONFIGURATION` 描述符，协议栈才会为每条连接维护"通知订阅状态"。缺少时 `ssaps_notify_indicate` 虽返回成功，但数据在协议栈层面被丢弃。

**修复**：在 `ssaps_add_property_sync` 之后、`ssaps_start_service` 之前添加：

```c
ssaps_desc_info_t descriptor = {0};
static uint8_t cccd_val[2]   = {0x01, 0x00}; // 0x01 = 通知默认开启
descriptor.permissions        = SSAP_PERMISSION_READ | SSAP_PERMISSION_WRITE;
descriptor.operate_indication = SSAP_OPERATE_INDICATION_BIT_READ |
                                SSAP_OPERATE_INDICATION_BIT_WRITE;
descriptor.type               = SSAP_DESCRIPTOR_CLIENT_CONFIGURATION; // 0x02
descriptor.value              = cccd_val;
descriptor.value_len          = sizeof(cccd_val);
ssaps_add_descriptor_sync(server_id, service_handle, property_handle, &descriptor);
```

---

### 客户端激活写（Activation Write）

服务发现完成后，客户端需向服务端写入一次，激活协议栈的通知路由通道：

```c
// my_sle_find_structure_cmp_cbk 内
static void my_sle_find_structure_cmp_cbk(uint8_t client_id, uint16_t conn_id,
    ssapc_find_structure_result_t *result, errcode_t status)
{
    static uint8_t s_activate = 0x01;
    ssapc_write_param_t wr = {0};
    wr.handle   = g_found_service_start_hdl; // 服务发现回调中保存的 start_hdl
    wr.type     = SSAP_PROPERTY_TYPE_VALUE;
    wr.data_len = 1;
    wr.data     = &s_activate;
    ssapc_write_req(client_id, conn_id, &wr);
}
```

---

### 跌倒警报 ACK 回传

客户端收到 `0x05` 跌倒数据后，向服务端回写 `0x06` 作为应答，形成完整闭环：

```c
// notification_cb 内
if (data->data[0] == 0x05) {
    uapi_gpio_set_val(FALL_ALERT_LED_PIN, GPIO_LEVEL_HIGH); // GPIO_09 亮灯
    osal_printk("FALL\r\n");

    static uint8_t s_ack = 0x06;
    ssapc_write_param_t wr = {0};
    wr.handle   = data->handle; // 复用服务端属性句柄
    wr.type     = SSAP_PROPERTY_TYPE_VALUE;
    wr.data_len = 1;
    wr.data     = &s_ack;
    ssapc_write_req(client_id, conn_id, &wr);
}
```

服务端的 `ssaps_write_request_cbk` 检测 `value[0] == 0x06` 即可确认收到 ACK。

---

### 关键 API 速查

| 阶段 | 接口 | 说明 |
|------|------|------|
| 服务端初始化 | `ssaps_add_descriptor_sync` | 注册 CCCD，Notify 必要条件 |
| 服务端发送 | `ssaps_notify_indicate` | 主动推送通知 |
| 客户端 MTU 后 | `ssapc_find_structure` | 服务发现，Notify 路由必要条件 |
| 客户端激活 | `ssapc_write_req` (0x01) | 激活通知通道 |
| 客户端应答 | `ssapc_write_req` (0x06) | 跌倒 ACK 回传 |

---

## 扫描参数关键配置

```c
// 必须显式设置 seek_phys=1，否则射频无法工作
sle_seek_param_t param = {0};
param.seek_phys        = 1;   // 关键！默认值0会导致扫描不到任何设备
param.seek_interval[0] = 100;
param.seek_window[0]   = 100;
sle_set_seek_param(&param);
```

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
