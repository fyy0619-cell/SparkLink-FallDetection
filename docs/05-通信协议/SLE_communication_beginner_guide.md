# 跌倒检测项目 SLE 通信小白指南

本文面向第一次接触 WS63、星闪 SLE、BLE/蓝牙和嵌入式通信的同学。目标是把“它到底怎么通信、工程里从哪里开始看、拿到开发板后怎么一步步跑起来”讲清楚。

本项目的核心链路很简单：

```text
板 A（Server，传感器 + AI）
  MPU6050 采集人体姿态 -> AI 判断跌倒 -> 通过 SLE 发 0x05
        |
        | 2.4 GHz 近距离无线链路（SLE / SSAP / Notify）
        v
板 B（Client，接收端 + 报警/网关）
  收到 0x05 -> 蜂鸣器响、LED/灯带变红 -> 可选 Wi-Fi 上传 HTTP 告警
```

一句话理解：板 A 像“报警器发射端”，板 B 像“随身接收器”。板 A 一旦判断跌倒，就把一个很短的消息 `0x05` 通过 SLE 推给板 B；板 B 收到后立刻响铃、亮灯，并回写 `0x06` 表示“我收到了”。

## 1. 先建立几个直觉

### 1.1 SLE 是什么

SLE 在这里指星闪（NearLink）里的低功耗短距通信能力。你可以先把它理解成“和 BLE 很像的一种近距离无线通信方式”：

- 不需要路由器，两个开发板可以直接通信。
- 适合低功耗、低时延的小数据包，例如告警、遥控、传感器数据。
- 需要经历广播、扫描、连接、配对、服务发现、数据收发这些步骤。
- 本项目使用 SLE 承担“板 A 到板 B 的告警链路”。

### 1.2 SSAP 是什么

SSAP 是 SLE 上层的“服务访问协议”。如果 SLE 是快递车和道路，SSAP 就是快递柜规则：

- `Service`：服务，像一个大柜子。本项目的跌倒检测服务 UUID 是 `0xABCD`。
- `Property`：属性/特征值，像柜子里的一个格子。本项目用于通知的属性 UUID 是 `0xABCE`。
- `Handle`：句柄，像格子的编号。真正收发数据时通常靠 handle 找到具体通道。
- `Notify`：通知，Server 主动把数据推给 Client。本项目用 Notify 发跌倒告警。
- `Write`：写入，Client 主动写数据给 Server。本项目用 Write 回 `0x06` ACK。

一句话：SLE 负责“连上线”，SSAP 负责“连上后按哪个服务、哪个属性收发数据”。

### 1.3 本项目为什么只发一个字节

因为告警场景不需要复杂数据。当前协议约定如下：

| 数据 | 方向 | 含义 |
| --- | --- | --- |
| `0x01` | Server -> Client，或 Client -> Server | 握手/激活链路，用于确认通知通道可用 |
| `0x05` | Server -> Client | 跌倒告警，Client 收到后报警 |
| `0x06` | Client -> Server | ACK，表示 Client 已收到告警 |

你可以把它理解为三句话：

- `0x01`：你好，我在线。
- `0x05`：有人跌倒了，快报警。
- `0x06`：收到，我已经开始报警。

## 2. 工程里从哪里开始看

建议按下面顺序看，不要一开始就钻协议栈源码。

| 顺序 | 文件 | 你要看什么 |
| --- | --- | --- |
| 1 | `application/samples/my_demo/fall_detect/src/main_task.c` | 程序入口，选择 Server/Client，跌倒后调用发送函数 |
| 2 | `application/samples/my_demo/fall_detect/Kconfig` | 编译配置，选择板 A 还是板 B，是否使用 SLE |
| 3 | `application/samples/my_demo/fall_detect/src/sle_server_task.c` | 板 A 的 SLE Server 实现：建服务、广播、连接后发通知 |
| 4 | `application/samples/my_demo/fall_detect/src/sle_client_task.c` | 板 B 的 SLE Client 实现：扫描、连接、服务发现、接收通知、报警 |
| 5 | `application/samples/my_demo/fall_detect/src/fall_alert_gateway.c` | 可选 Wi-Fi 网关：收到跌倒后再上传 HTTP |
| 6 | `docs/fall-detect-sle-debug-summary-2026-04-29.md` | 之前联调踩坑记录，适合排查问题 |

主线入口在 `main_task.c`：

```text
Server 模式：
Fall_Detect_Task_Body
  -> AI_Model_Init / MPU6050_Init
  -> sle_server_task_init
  -> 循环采集 MPU6050
  -> AI_Feed_And_Predict_6Axis 返回 status == 1
  -> sle_send_fall_alert(0x05)

Client 模式：
Fall_Detect_Task_Body
  -> sle_client_task_init
  -> 等待 SLE 通知
  -> 收到 0x05 后由回调触发蜂鸣器和灯带
```

## 3. 它分成哪几层

不要把所有函数混在一起看。可以分成 5 层：

```text
第 5 层：业务层
  跌倒检测、报警、蜂鸣器、LED、Wi-Fi 上传

第 4 层：应用协议层
  约定 0x01/0x05/0x06 分别代表什么

第 3 层：SSAP 服务层
  Service UUID 0xABCD、Property UUID 0xABCE、Notify、Write、Handle

第 2 层：SLE 连接层
  enable_sle、广播 announce、扫描 seek、连接 connect、配对 pair、MTU 交换

第 1 层：硬件/系统层
  WS63 射频、GPIO、MPU6050、蜂鸣器、WS2812B、LiteOS 任务调度
```

调试时也按层排查：先看硬件供电和烧录，再看是否广播/扫描，再看是否连接/配对，再看服务发现，再看 `0x05` 业务包。

## 4. Server 端是如何实现的

Server 是板 A：负责采集传感器、跑 AI、发现跌倒后发告警。

### 4.1 初始化流程

代码入口：`application/samples/my_demo/fall_detect/src/sle_server_task.c` 的 `sle_server_task_init()`。

它主要做 4 件事：

1. 注册连接回调：有人连上或断开时，SDK 会回调 `sle_connect_state_changed_cbk()`。
2. 注册 SSAP 回调：Client 写数据过来时，SDK 会回调 `ssaps_write_request_cbk()`。
3. 注册 SLE 使能回调：`enable_sle()` 成功后，进入 `sle_server_on_stack_ready()`。
4. 调用 `enable_sle()` 唤醒 SLE 协议栈。

简化流程：

```text
sle_server_task_init
  -> sle_connection_register_callbacks
  -> ssaps_register_callbacks
  -> sle_announce_seek_register_callbacks
  -> enable_sle
      -> sle_server_on_stack_ready
          -> sle_uuid_server_add
          -> sle_set_local_addr_init
          -> sle_uuid_server_adv_init
```

### 4.2 建服务：告诉 Client “我能提供什么”

`sle_uuid_server_add()` 做的是“开店并摆货”：

- 注册一个 SSAP Server，得到 `g_server_id`。
- 添加一个主服务 `0xABCD`，得到 `g_service_handle`。
- 在服务下添加一个属性 `0xABCE`，得到 `g_property_handle`。
- 给属性打开 READ、WRITE、NOTIFY 能力。
- 启动服务。

这些变量很关键：

| 变量 | 含义 |
| --- | --- |
| `g_server_id` | 本地 SSAP Server 的编号 |
| `g_service_handle` | 跌倒服务的句柄 |
| `g_property_handle` | 真正用于 Notify 的属性句柄 |
| `g_sle_conn_hdl` | 当前连接的 Client 句柄，`0xFFFF` 表示没人连接 |

### 4.3 广播：让 Client 能找到板 A

`sle_set_local_addr_init()` 把板 A 地址固定为：

```text
11:22:33:44:55:66
```

Client 扫描时会专门找这个地址。这样做的好处是：现场有多个设备时，板 B 不会误连别人。

然后 `sle_uuid_server_adv_init()` 开始广播。广播可以理解为板 A 不断喊：“我是 `11:22:33:44:55:66`，我在这里，可以连接。”

### 4.4 连接成功：保存连接句柄并发握手

连接成功后会进入：

```c
sle_connect_state_changed_cbk(...)
```

里面最重要的是：

```text
g_sle_conn_hdl = conn_id
```

这一步相当于记住“当前快递要发给谁”。如果没有这个连接句柄，`sle_send_fall_alert()` 不知道往哪里发，只能打印 `No client connected`。

连接成功后 Server 会主动发 `0x01` 握手通知，帮助确认通知通道可用。

### 4.5 跌倒后发送 0x05

真正发告警的函数是：

```c
errcode_t sle_send_fall_alert(uint8_t *data, uint16_t len)
```

`main_task.c` 里 AI 判断跌倒后调用它：

```text
status == 1
  -> alert_data = 0x05
  -> sle_send_fall_alert(&alert_data, 1)
```

`sle_send_fall_alert()` 内部构造 `ssaps_ntf_ind_t`，然后调用：

```c
ssaps_notify_indicate(g_server_id, g_sle_conn_hdl, &param)
```

这就是 Server 主动 Notify 给 Client 的关键 API。

## 5. Client 端是如何实现的

Client 是板 B：负责找到板 A、连接、接收告警、触发蜂鸣器/灯带，并可选上传 Wi-Fi。

### 5.1 初始化流程

代码入口：`application/samples/my_demo/fall_detect/src/sle_client_task.c` 的 `sle_client_task_init()`。

它主要做 5 件事：

1. 初始化 LED、蜂鸣器、WS2812B。
2. 启动报警守护任务，用于需要定时关闭报警的场景。
3. 初始化可选 Wi-Fi 网关。
4. 注册扫描、连接、配对、SSAP 数据回调。
5. 调用 `enable_sle()` 启动 SLE。

简化流程：

```text
sle_client_task_init
  -> fall_alert_led_init
  -> ws2812b_init
  -> fall_alert_gateway_init
  -> 注册 seek/connect/ssapc 回调
  -> enable_sle
      -> my_sle_sample_sle_enable_cbk
          -> ssapc_register_client
          -> 设置本机地址 AA:BB:CC:DD:EE:FF
          -> 设置扫描参数
          -> sle_start_seek
```

### 5.2 扫描：找到板 A

Client 扫描回调是：

```c
my_sle_sample_seek_result_info_cbk(...)
```

每扫到一个设备就打印它的 MAC，然后比较是不是目标地址：

```text
目标 Server MAC = 11:22:33:44:55:66
```

如果匹配，就停止扫描：

```text
g_need_connect = true
sle_stop_seek()
```

为什么不是扫到后立刻连接？因为很多协议栈要求“先完全停止扫描，再发起连接”。本项目在 `seek_disable_cb` 里等扫描真的停掉后再连接。

### 5.3 连接和配对

扫描停止后进入：

```c
my_sle_sample_seek_disable_cbk(...)
```

如果 `g_need_connect == true`，就调用：

```c
sle_connect_remote_device(&g_remote_addr)
```

连接成功后进入：

```c
my_sle_sample_connect_state_changed_cbk(...)
```

此处会：

- 保存 `g_conn_id`。
- 设置 `g_sle_connected = true`，主任务开始打印心跳。
- 调用 `sle_pair_remote_device(&g_remote_addr)` 发起配对。

配对成功后进入：

```c
my_sle_sample_pair_complete_cbk(...)
```

然后发起 MTU 协商：

```c
ssapc_exchange_info_req(g_client_id, conn_id, &info)
```

MTU 可以理解为“双方商量一次最多能搬多大的包”。本项目只发 1 字节，但按照标准流程仍然做 MTU 交换，后续服务发现也依赖这个时序。

### 5.4 服务发现：找到 0xABCD

MTU 协商完成后进入：

```c
my_sle_exchange_info_cbk(...)
```

然后发起服务发现：

```c
ssapc_find_structure(client_id, conn_id, &find_param)
```

发现到服务时进入：

```c
my_sle_find_structure_cbk(...)
```

Client 会检查服务 UUID 是否为 `0xABCD`。匹配后保存：

```text
g_found_service_start_hdl = service->start_hdl
g_fall_service_found = true
```

服务发现完成后，Client 写一次 `0x01` 激活通道。这一步类似“我已经找到你的跌倒服务了，后面通知可以往这里发”。

### 5.5 收到 0x05 后报警并回 ACK

最核心的接收回调是：

```c
my_sle_speed_notification_cb(...)
```

只要 Server Notify 到来，SDK 就会调用它。当前逻辑是：

```text
收到 data[0]
  如果 data[0] == 0x05：
    -> 蜂鸣器打开
    -> LED 打开
    -> WS2812B 变红
    -> fall_alert_gateway_post_fall，可选上传 Wi-Fi 告警
    -> 通过 ssapc_write_req 回写 0x06 ACK
```

回写 ACK 后，Server 的 `ssaps_write_request_cbk()` 会看到 `0x06`，打印“Fall alert confirmed”。这样形成完整闭环：

```text
Server 发送 0x05
  -> Client 收到并报警
  -> Client 回写 0x06
  -> Server 确认 Client 已收到
```

## 6. 拿到开发板后如何上手

下面按“两块板”的实际流程写。建议先只跑 SLE 告警，不要一开始就加 Wi-Fi、云短信、语音电话。

### 6.1 准备硬件

你需要：

- 两块 WS63/WS63E 开发板。
- 板 A：接 MPU6050，用于跌倒检测。
- 板 B：接蜂鸣器、普通 LED、WS2812B 灯带，作为接收报警端。
- 两根 USB 线，分别用于供电、烧录、串口日志。
- 稳定供电。SLE 扫描和发射时对电源瞬态比较敏感，供电不稳会导致扫描不到或连接不稳定。

### 6.2 配置板 A 为 Server

在配置菜单或对应配置文件中选择：

```text
ENABLE_FALL_DETECT_APP = y
FALL_DETECT_USE_SLE = y
FALL_DETECT_ROLE_SERVER = y
```

板 A 烧录后，你希望看到类似日志：

```text
[System] Running in SERVER mode (Board A).
[SLE Server] sle_server_task_init completed.
[SLE Server] SLE Stack Enabled and Adv Started.
```

如果没有看到 `Adv Started`，优先检查：

- 是否真的启用了 SLE。
- `sle_server_on_stack_ready()` 是否进入。
- 是否有编译宏把 `sle_server_task.c` 排除了。

### 6.3 配置板 B 为 Client

另一块板选择：

```text
ENABLE_FALL_DETECT_APP = y
FALL_DETECT_USE_SLE = y
FALL_DETECT_ROLE_CLIENT = y
```

板 B 烧录后，你希望看到类似日志：

```text
[System] Running in CLIENT mode (Board B).
[CLIENT] SLE Client Component Initialized.
[CLIENT] SSAP client registered, id=...
[CLIENT] SLE Scanner Started (PHY=1). Listening for Server...
```

如果扫描到板 A，会看到：

```text
[CLIENT SCAN] Saw MAC: 11:22:33:44:55:66
[CLIENT] Target Server Found! Stopping scan and connecting...
[CLIENT] Connected to Server! conn_id: ...
[CLIENT] Pair complete. Exchanging MTU...
[CLIENT] Matched fall service UUID=0xabcd
```

### 6.4 验证通信是否成功

先不要真的摔板子，可以用以下现象判断链路成功：

1. 板 A 显示 Client Connected。
2. 板 B 显示 Connected、Pair complete、MTU exchange done、Service discovery complete。
3. 板 B 主循环每秒打印 `[CLIENT] 1`，说明连接保持中。
4. 板 A 发送握手后，板 B 能看到 `Notification: data[0]=0x01`。
5. 触发跌倒后，板 B 能看到 `Notification: data[0]=0x05`，蜂鸣器响、灯变红。
6. 板 A 收到 `0x06` ACK，说明告警闭环完成。

### 6.5 触发跌倒告警

正常路径是：

```text
MPU6050 数据
  -> AI_Feed_And_Predict_6Axis
  -> 返回 status == 1
  -> main_task.c 调用 sle_send_fall_alert(0x05)
```

如果你只是想先验证通信，可以临时在 Server 连接成功后发 `0x05`，或在 AI 判断处强制 `status == 1`。验证完成后务必删除临时代码，避免误报警。

### 6.6 再打开 Wi-Fi 网关

SLE 本身只负责板 A 到板 B。若需要短信/电话/后台推送，需要板 B 再通过 Wi-Fi 上传。

配置文件：

```text
application/samples/my_demo/fall_detect/inc/fall_alert_gateway_config.h
```

流程变成：

```text
板 A --SLE 0x05--> 板 B --Wi-Fi HTTP POST--> 后端服务 --短信/电话--> 家属手机
```

详细 Wi-Fi 网关说明见：`docs/fall-detect-wifi-alert-gateway.md`。

## 7. SLE 和蓝牙/BLE 的关系

### 7.1 它们是什么关系

SLE 和 BLE 都属于 2.4 GHz 近距离无线通信技术，使用体验上有很多相似点：都要广播、扫描、连接、配对，都有服务/属性/通知这类抽象。

但它们不是同一个协议。BLE 属于 Bluetooth 蓝牙技术体系；SLE 属于星闪 NearLink 技术体系。本项目使用的是 WS63 SDK 提供的 SLE API，不是手机常见蓝牙 App 直接扫描的 BLE GATT 服务。

### 7.2 相同点

| 方面 | SLE | BLE |
| --- | --- | --- |
| 工作场景 | 短距离无线 | 短距离无线 |
| 常见流程 | 广播、扫描、连接、配对 | 广播、扫描、连接、配对 |
| 数据模型 | SSAP 的 Service/Property | GATT 的 Service/Characteristic |
| 推送方式 | Notify/Indicate | Notify/Indicate |
| 适合数据 | 小包、控制、传感器、告警 | 小包、控制、传感器、告警 |

### 7.3 不同点

| 方面 | SLE | BLE |
| --- | --- | --- |
| 技术体系 | 星闪 NearLink | Bluetooth SIG 蓝牙 |
| 本项目 API | `sle_*`、`ssaps_*`、`ssapc_*` | `ble_*`、`gatts_*`、`gattc_*` 等 |
| 服务模型名称 | SSAP | GATT |
| 手机兼容性 | 取决于手机/系统是否支持星闪 | 普通手机普遍支持 BLE |
| 本项目定位 | 两块 WS63 板之间低时延告警 | 仓库里有旧 BLE 代码，可作为对比或兼容方案 |

### 7.4 为什么本项目选 SLE

这个跌倒检测演示的关键是“板 A 发现危险后，板 B 尽快收到”。SLE 很适合这种板到板、低时延、小数据告警链路。另外 WS63 本身就是 Wi-Fi 6 + 星闪多模芯片，使用 SLE 能更好展示芯片特色。

如果目标是“直接让普通手机 App 收到告警”，BLE 可能更容易，因为手机 BLE 生态更成熟。如果目标是“两块开发板稳定低时延通信”，SLE 更贴近本项目。

## 8. 常见问题和排查顺序

### 8.1 Client 扫不到 Server

按顺序检查：

1. 板 A 是否已经打印 `Adv Started`。
2. 板 B 是否已经打印 `SLE Scanner Started (PHY=1)`。
3. 板 A MAC 是否仍是 `11:22:33:44:55:66`。
4. 板 B 目标 MAC 是否也是 `11:22:33:44:55:66`。
5. 两块板距离是否太远，供电是否不稳。
6. 是否两块板都配置成了 Server，或都配置成了 Client。

### 8.2 能连接但收不到 0x05

按顺序检查：

1. Client 是否完成 `Pair complete`。
2. Client 是否完成 `MTU exchange done`。
3. Client 是否发现 `UUID=0xABCD`。
4. Server 的 `g_sle_conn_hdl` 是否不是 `0xFFFF`。
5. Server 的 `g_property_handle` 是否正确创建。
6. `sle_send_fall_alert()` 是否真的被调用。
7. 发送数据是否为 `0x05` 而不是 `0x01`。

### 8.3 Server 打印 No client connected

说明 Server 认为当前没有 Client 连接。重点看：

- `sle_connect_state_changed_cbk()` 有没有进入 CONNECTED 分支。
- 是否有其他示例代码重复注册连接回调，覆盖了本项目回调。
- Client 是否连接后又马上断开。
- 板 A 和板 B 是否烧录了相同角色，导致没有真正建立连接。

### 8.4 Client 收到 0x05 但蜂鸣器不响

重点看硬件层：

- 蜂鸣器是否接在 `GPIO_08`。
- 本项目按“低电平触发”蜂鸣器写的，空闲时输出高电平，报警时输出低电平。
- 蜂鸣器电源和 GND 是否正确。
- 如果你换了开发板或引脚，需要同步修改 `FALL_ALERT_BUZZER_PIN`。

### 8.5 SSAP Client 注册失败

如果看到类似：

```text
ssapc_register_client failed: 0x80006011
```

通常是注册时机太早。应确保在 `enable_sle()` 成功回调之后再调用 `ssapc_register_client()`。本项目已经按这个时序放在 `my_sle_sample_sle_enable_cbk()` 中。

## 9. 最小成功标准

如果你是第一次上手，不要一开始追求所有功能都通。先达到这 4 个目标：

1. 板 A 能广播，板 B 能扫描到 `11:22:33:44:55:66`。
2. 板 B 能连接、配对、完成 MTU 交换和服务发现。
3. 板 A 能发 `0x05`，板 B 能打印 `Notification: data[0]=0x05`。
4. 板 B 能蜂鸣器报警，并回写 `0x06`，板 A 能确认 ACK。

做到这 4 点，SLE 通信主链路就已经打通。后续再叠加 AI 参数优化、Wi-Fi 上传、短信/电话通知，都会更容易定位问题。

## 10. 记忆口诀

```text
Server：建服务 -> 开广播 -> 等连接 -> 跌倒发 0x05
Client：开扫描 -> 找 MAC -> 连上配对 -> 找服务 -> 收 0x05 -> 响铃回 0x06
分层排查：硬件 -> SLE 连接 -> SSAP 服务 -> 业务字节 -> 报警动作
```
