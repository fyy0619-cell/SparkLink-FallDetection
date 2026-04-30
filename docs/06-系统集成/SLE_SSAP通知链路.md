# 跌倒检测系统 — SLE SSAP 通知链路全解析

> 记录双板通信系统从传感器采集到跌倒告警的完整数据流，以及 2026.04.26 调试过程中定位并修复的所有问题。

---

## 系统架构

```
[板A - Server]                        [板B - Client]
  MPU6050 (I²C)
  GPIO15=SCL, GPIO16=SDA
  ↓ 100Hz 采样
  循环缓冲区 (100帧 × 3轴)
  ↓ 每30帧（0.3s）触发一次推理
  Edge Impulse DSP (~3045ms)
  TFLite 神经网络 (~2798ms)
  ↓ 跌倒概率 > 80%
  ssaps_notify_indicate(0x05)
        ─────── SLE SSAP ──────────→  notification_cb
                                        GPIO_09 LED 亮
                                        串口打印 "FALL"
                                        ssapc_write_req(0x06)
        ←─── ssaps_write_request_cbk ──
  打印 "ACK received from client!"
```

---

## 各阶段耗时分析

| 阶段 | 耗时 | 备注 |
|------|------|------|
| MPU6050 采样周期 | 10ms/帧 | 100Hz |
| 推理触发间隔 | 300ms | 每30帧 |
| Edge Impulse DSP | ~3045ms | RISC-V 无硬件 DSP 加速 |
| TFLite 推理 | ~2798ms | |
| **单次推理合计** | **~5.8s** | 主线程同步执行，期间停止采样 |
| SLE 通知传输 | <100ms | 无线链路本身延迟极低 |
| **最坏端到端延迟** | **~12s** | 跌倒恰好发生在推理刚开始时 |

**结论**：延迟主要来自 AI 推理管道，而非无线通信。端侧 TinyML 是本系统核心亮点，延迟属于 RISC-V 平台性能特性。

---

## 关键源文件

| 文件 | 角色 |
|------|------|
| `src/main_task.c` | 主循环：采样→推理→发送警报 |
| `src/ai_model.cpp` | Edge Impulse + TFLite 推理封装 |
| `src/sle_server_task.c` | 板A：SLE Server，注册服务/属性/CCCD，发送 Notify |
| `src/sle_client_task.c` | 板B：SLE Client，扫描/连接/服务发现/接收通知/点灯 |
| `src/sle_speed_server_adv.c` | 官方广播参数配置（直接复用） |

---

## 服务端核心初始化序列

```c
// sle_server_task.c → sle_uuid_server_add()

// 1. 注册 Server
ssaps_register_server(&app_uuid, &g_server_id);

// 2. 添加主服务
ssaps_add_service_sync(g_server_id, &service_uuid, 1, &g_service_handle);

// 3. 添加属性（需同时声明 NOTIFY + WRITE 权限）
ssaps_property_info_t property = {0};
property.operate_indication = SSAP_OPERATE_INDICATION_BIT_READ  |
                              SSAP_OPERATE_INDICATION_BIT_NOTIFY |
                              SSAP_OPERATE_INDICATION_BIT_WRITE; // WRITE 必须！客户端才能回 ACK
property.permissions        = SSAP_PERMISSION_READ | SSAP_PERMISSION_WRITE;
property.value              = property_value;
property.value_len          = sizeof(property_value);
ssaps_add_property_sync(g_server_id, g_service_handle, &property, &g_property_handle);

// 4. 添加 CCCD 描述符（缺少此步则 Notify 被协议栈静默丢弃）
ssaps_desc_info_t descriptor = {0};
static uint8_t cccd_val[2]   = {0x01, 0x00};
descriptor.type               = SSAP_DESCRIPTOR_CLIENT_CONFIGURATION;
descriptor.permissions        = SSAP_PERMISSION_READ | SSAP_PERMISSION_WRITE;
descriptor.operate_indication = SSAP_OPERATE_INDICATION_BIT_READ |
                                SSAP_OPERATE_INDICATION_BIT_WRITE;
descriptor.value              = cccd_val;
descriptor.value_len          = 2;
ssaps_add_descriptor_sync(g_server_id, g_service_handle, g_property_handle, &descriptor);

// 5. 启动服务
ssaps_start_service(g_server_id, g_service_handle);
```

---

## 客户端核心初始化序列

```c
// sle_client_task.c → sle_client_task_init()

// 注册全部回调（服务发现回调缺一不可）
ssapc_callbacks_t ssapc_cbk = {0};
ssapc_cbk.exchange_info_cb      = my_sle_exchange_info_cbk;      // MTU 协商完成
ssapc_cbk.find_structure_cb     = my_sle_find_structure_cbk;     // 发现一条服务
ssapc_cbk.find_structure_cmp_cb = my_sle_find_structure_cmp_cbk; // 所有服务发现完毕
ssapc_cbk.write_cfm_cb          = my_sle_write_cfm_cbk;          // 写操作链路确认
ssapc_cbk.notification_cb       = my_sle_speed_notification_cb;  // 接收跌倒通知
ssapc_register_callbacks(&ssapc_cbk);
```

客户端连接握手顺序：

```
SLE 使能 → 配置扫描参数(seek_phys=1) → 扫描 → 发现目标MAC → 停扫 → 连接 → 配对
→ MTU 协商(512) → 服务发现(ssapc_find_structure) → 激活写(0x01) → 等待 Notify
```

---

## 发送跌倒警报（Server 调用）

```c
// main_task.c 中，AI 推理返回 status==1 时调用
uint8_t alert_data = 0x05;
sle_send_fall_alert(&alert_data, 1);

// sle_server_task.c 中的实现
errcode_t sle_send_fall_alert(uint8_t *data, uint16_t len)
{
    if (g_sle_conn_hdl == 0xFFFF) return ERRCODE_SLE_FAIL; // 未连接则丢弃

    ssaps_ntf_ind_t param = {0};
    param.handle    = g_property_handle;
    param.type      = SSAP_PROPERTY_TYPE_VALUE;
    param.value     = data;
    param.value_len = len;
    return ssaps_notify_indicate(g_server_id, g_sle_conn_hdl, &param);
}
```

---

## 客户端 LED 告警与 ACK 回传

```c
// sle_client_task.c → my_sle_speed_notification_cb()
if (data->data[0] == 0x05) {
    uapi_gpio_set_val(FALL_ALERT_LED_PIN, GPIO_LEVEL_HIGH); // GPIO_09 点亮

    osal_printk("FALL\r\n");
    osal_printk("[CLIENT ALERT] SOS RECEIVED!\r\n");

    // 回传 ACK，服务端 ssaps_write_request_cbk 接收并打印确认
    static uint8_t s_ack = 0x06;
    ssapc_write_param_t wr = {0};
    wr.handle   = data->handle;
    wr.type     = SSAP_PROPERTY_TYPE_VALUE;
    wr.data_len = 1;
    wr.data     = &s_ack;
    ssapc_write_req(client_id, conn_id, &wr);
}
```

---

## CMakeLists.txt 双板编译配置

通过 `MANUAL_SLE_SWITCH` 和 `CONFIG_FALL_DETECT_ROLE_CLIENT` 控制编译目标：

```cmake
set(MANUAL_SLE_SWITCH ON)

if(MANUAL_SLE_SWITCH)
    if(CONFIG_FALL_DETECT_ROLE_CLIENT)
        # 板B (Client)：移除 sle_server_task.c 和 ble_server_task.c
        list(REMOVE_ITEM APP_SRCS ".../sle_server_task.c")
        list(REMOVE_ITEM APP_SRCS ".../ble_server_task.c")
    else()
        # 板A (Server)：移除 sle_client_task.c 和 ble_server_task.c
        # 只编译 sle_speed_server_adv.c（广播配置），不编译 sle_speed_server.c
        # 原因：sle_speed_server.c 的 app_run() 会覆盖自定义连接回调
        list(REMOVE_ITEM APP_SRCS ".../sle_client_task.c")
        list(APPEND APP_SRCS ".../sle_speed_server_adv.c")
    endif()
endif()
```

---

## 技术栈

| 层次 | 技术 / 组件 |
|------|------------|
| 芯片 | HiSilicon WS63（RISC-V 32位） |
| 操作系统 | LiteOS v208.5.0 |
| 通信协议 | SLE SSAP（星闪服务访问协议） |
| 服务端关键 API | `ssaps_add_property_sync`、`ssaps_add_descriptor_sync`、`ssaps_notify_indicate` |
| 客户端关键 API | `ssapc_find_structure`、`ssapc_write_req`、`ssapc_register_callbacks` |
| AI 推理框架 | Edge Impulse SDK + TensorFlow Lite Micro |
| 传感器 | MPU6050（I²C，GPIO15=SCL，GPIO16=SDA） |
| 告警输出 | GPIO_09 LED + UART 串口打印 |
| 灯带告警 | WS2812B（红灯闪烁，400ms亮/400ms灭，超时自动关闭） |
| 工程质量 | UTF-8（无BOM）编码规范、`rg` 乱码扫描、PowerShell 编码修复脚本 |
