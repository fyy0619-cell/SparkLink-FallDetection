# 跌倒检测项目 WiFi 推送网关完整流程

本文把项目里 **WiFi 推送报警** 这条链路从头到尾讲一遍：触发条件是什么、板上代码怎么走、配置项要怎么填、后端怎么收、短信/微信/语音怎么发。

适合"第一次看这块、想完整跑通一遍"的人。

---

## 一、整体数据流

```text
板 A (Server)           板 B (Client)                  后端服务器              家属手机
─────────────          ─────────────                  ───────────            ─────────
MPU6050 + AI                                                                    │
      │                                                                          │
      └─ SLE 发 0x05 ──► 收到 0x05                                                │
                              │                                                  │
                              ├─ 蜂鸣器/灯带报警 (本地)                          │
                              │                                                  │
                              ├─ 4G 拨号 (银尔达 DTU, 走 UART1)                  │
                              │                                                  │
                              └─ WiFi HTTP POST ──► /api/fall-alert              │
                                                          │                      │
                                                          ├─ dry-run: 仅打印     │
                                                          ├─ pushplus ─────────► 微信
                                                          └─ tencent ──────────► 短信
                                                                                 └─► 语音
```

**关键设计**：

- 板 A 只管检测，**不上网**；板 B 既是 SLE Client，又是 WiFi 网关。
- 板 B 上 **WiFi 任务和 SLE 回调解耦** —— SLE 回调里只丢一个标志位，HTTP 真正发送在后台任务里跑，避免阻塞 SLE 栈。
- **云厂商密钥永远不进固件**。板 B 只持有"自家后端的 token"；后端再用 AccessKey 调腾讯云/PushPlus。

---

## 二、涉及的文件清单

| 角色 | 文件 | 作用 |
|---|---|---|
| 板 B 触发点 | `application/samples/my_demo/fall_detect/src/sle_client_task.c` | 收到 SLE `0x05` 后调用 gateway |
| WiFi 网关头 | `application/samples/my_demo/fall_detect/inc/fall_alert_gateway.h` | 仅两个对外 API |
| WiFi 网关实现 | `application/samples/my_demo/fall_detect/src/fall_alert_gateway.c` | WiFi 状态机 + HTTP POST + 防抖 |
| WiFi 网关配置 | `application/samples/my_demo/fall_detect/inc/fall_alert_gateway_config.h` | SSID/密码/服务器/Token |
| 后端 Demo | `tools/fall_alert_backend_demo.py` | HTTP 服务 + 三种通知器 |
| 后端环境变量模板 | `tools/fall_alert_backend.env.example` | 给后端配密钥/联系人/通道 |

> 模块名叫 `fall_alert_gateway`，不要和后面 4G DTU 那条线（`fall_alert_4g_dtu`）混了——它们俩**是并联的**，跌倒时同时触发，互不依赖。

---

## 三、板 B 端：触发位置

打开 `sle_client_task.c:94`，看 SLE 通知回调：

```c
static void my_sle_speed_notification_cb(...)
{
    if (data->data[0] == 0x05) {
        fall_alert_set(true, 0);                       // 本地蜂鸣器 + 红灯
        fall_alert_gateway_post_fall(data->data[0]);   // ← WiFi 上报入口
        fall_alert_4g_dtu_post_fall(data->data[0]);    // ← 4G 拨号入口（并联）
        ...
        ssapc_write_req(client_id, conn_id, &wr);      // 回 0x06 ACK 给板 A
    }
}
```

`fall_alert_gateway_post_fall()` 内部只做三件事（`fall_alert_gateway.c:379`）：

```c
g_last_payload = source_payload;
g_event_count++;
g_alert_pending = true;
```

**就这三行**。它**不发包、不连网络、不阻塞**，纯粹是给后台任务放一个"有活干"的标志位。SLE 回调瞬间返回，星闪栈不会被卡。

初始化在 `sle_client_task.c:337` —— 整个 SLE Client 启动时调用 `fall_alert_gateway_init()`，它创建一个名为 `fall_alert_gw` 的内核线程跑 `fall_alert_gateway_task()`。

---

## 四、板 B 端：后台任务做什么

`fall_alert_gateway.c:323` 这个任务的逻辑是：

```text
任务启动
  │
  ├─[阶段 1] 连 WiFi (阻塞，直到拿到 IP)
  │      ↓
  │   状态机：INIT → SCANNING → SCAN_DONE → FOUND_TARGET
  │              → CONNECTING → CONNECT_DONE → GET_IP → READY
  │
  └─[阶段 2] 主循环 (每 200ms 一轮)
         ↓
       g_alert_pending 为 false  → 睡 200ms
       g_alert_pending 为 true   → 检查冷却
                                  │
                       未到 60s ─→ 丢弃这次，清标志（防 AI 连击）
                       已到 ─────→ HTTP POST
                                  │
                              发送成功 → 记录时间戳，清标志
                              发送失败 → 留着标志，3 秒后重试
```

**冷却机制**：`FALL_GATEWAY_CLOUD_COOLDOWN_MS = 60000` —— 一次跌倒可能让 AI 在 1~2 秒里反复触发，后台一分钟只准上报一次。这条机制和板 A 自己的 `FALL_DETECT_COOLDOWN_MS` **是双重保险**，串联工作。

**HTTP 请求长这样**（`fall_alert_gateway.c:261`）：

```http
POST /api/fall-alert HTTP/1.1
Host: 10.189.231.184:8080
Content-Type: application/json
Authorization: Bearer change-me-demo-token
Connection: close
Content-Length: 86

{"device_id":"ws63-fall-client-001","event":"fall","payload":5,"event_count":3}
```

**纯 HTTP，没用 HTTPS**。原因：WS63 SDK 镜像里没把 TLS 库编进去会更省 flash；后端在内网或者代理后面就够安全。要走 HTTPS 的话需要前面挂 Nginx 反代。

---

## 五、固件配置（最容易踩坑的地方）

打开 `application/samples/my_demo/fall_detect/inc/fall_alert_gateway_config.h`：

```c
#define FALL_GATEWAY_WIFI_ENABLED       1               // 0 = 整个模块禁用，纯演示用
#define FALL_GATEWAY_WIFI_SSID          "OPPO Find X9s Pro"
#define FALL_GATEWAY_WIFI_PASSWORD      "yyfu0619"
#define FALL_GATEWAY_SERVER_HOST        "10.189.231.184"   // 后端 IP，不要写 DNS 名
#define FALL_GATEWAY_SERVER_PORT        8080
#define FALL_GATEWAY_SERVER_PATH        "/api/fall-alert"
#define FALL_GATEWAY_DEVICE_ID          "ws63-fall-client-001"
#define FALL_GATEWAY_AUTH_TOKEN         "change-me-demo-token"
#define FALL_GATEWAY_CLOUD_COOLDOWN_MS  60000U
```

| 配置项 | 注意点 |
|---|---|
| `WIFI_SSID` | **必须是 2.4 GHz**。WS63 不支持 5G；手机热点要去手机设置里强制改成 2.4G。 |
| `WIFI_PASSWORD` | 不能为空（开放网络要改代码改 security_type）。 |
| `SERVER_HOST` | 优先 IP，DNS 在 SDK 默认配置下不一定可用。手机热点开了之后，电脑插这个热点会拿到一个 `192.168.x.x` 或 `10.x.x.x` IP，**那个就是写这里的值**。 |
| `SERVER_PORT` | 后端启动时 `--port` 要一致；防火墙要放行。 |
| `DEVICE_ID` | 多块板子时区分用，会进 JSON。 |
| `AUTH_TOKEN` | 必须**和后端 `FALL_BACKEND_TOKEN` 完全一致**，否则后端返回 401。 |
| `CLOUD_COOLDOWN_MS` | 单次跌倒后这段时间内的重复触发会被网关合并丢弃。 |

**改完一定要重新编译烧录板 B**。WiFi 信息编进了固件，**不像 Lua 脚本可以热下发**。

---

## 六、后端：怎么收、怎么发

后端在 `tools/fall_alert_backend_demo.py`，是个纯标准库 Python（无依赖即可运行 dry-run 模式）。

### 6.1 收报警端

只有一个 endpoint：`POST /api/fall-alert`，逻辑：

```text
1. 检查 Authorization: Bearer <token> 是否匹配 FALL_BACKEND_TOKEN
   → 不匹配返 401
2. 解析 JSON
   → 失败返 400
3. 走 60 秒去重 (FALL_RATE_LIMIT_SECONDS)
   → 命中返 200 {ok: true, notified: false, reason: "rate_limited"}
4. 调用通知器 .send(alert)
   → 成功返 200 {ok: true, notified: true}
```

### 6.2 通知器三选一

后端通过环境变量 `FALL_NOTIFY_PROVIDER` 切换：

| Provider | 何时用 | 必备配置 | 收到形式 |
|---|---|---|---|
| `dryrun` | 第一次跑、调试 | 无 | 后端控制台打印 |
| `pushplus` | 没有短信签名资质、家属用微信 | `PUSHPLUS_TOKEN` | 微信收 markdown 卡片 |
| `tencent` | 走腾讯云 SMS + 语音 | `TENCENT_*` 一堆 | 家属收短信 + 语音呼叫 |

注意 `FALL_NOTIFY_DRY_RUN=1` 是**总开关**——只要它是 1，不管 provider 是谁都只打印不发。**比赛/演示前一定记得把这个置 0**。

### 6.3 启动命令

**最简（dry-run，本地测）**：

```powershell
python tools\fall_alert_backend_demo.py --host 0.0.0.0 --port 8080
```

**PushPlus 微信推送**（推荐：不用资质审核、家属手机微信扫码就能收）：

```powershell
$env:FALL_BACKEND_TOKEN="change-me-demo-token"
$env:FALL_NOTIFY_PROVIDER="pushplus"
$env:FALL_NOTIFY_DRY_RUN="0"
$env:PUSHPLUS_TOKEN="你的PushPlusToken"
$env:PUSHPLUS_CHANNEL="wechat"
python tools\fall_alert_backend_demo.py --host 0.0.0.0 --port 8080
```

**腾讯云 SMS + 语音呼叫**（要先在腾讯云控制台过签名/模板审核）：

```powershell
pip install tencentcloud-sdk-python

$env:FALL_BACKEND_TOKEN="change-me-demo-token"
$env:FALL_NOTIFY_PROVIDER="tencent"
$env:FALL_NOTIFY_DRY_RUN="0"
$env:FALL_NOTIFY_CHANNELS="sms,voice"
$env:FALL_CONTACTS="+8613800138000,+8613900139000"
$env:TENCENT_SECRET_ID="AKIDxxxxxxxx"
$env:TENCENT_SECRET_KEY="xxxxxxxx"
$env:TENCENT_SMS_REGION="ap-guangzhou"
$env:TENCENT_SMS_SDK_APP_ID="1400000000"
$env:TENCENT_SMS_SIGN_NAME="你的短信签名"
$env:TENCENT_SMS_TEMPLATE_ID="1234567"
$env:TENCENT_VMS_REGION="ap-guangzhou"
$env:TENCENT_VMS_SDK_APP_ID="1400000000"
$env:TENCENT_VMS_TEMPLATE_ID="1234567"
python tools\fall_alert_backend_demo.py --host 0.0.0.0 --port 8080
```

### 6.4 短信/语音模板

腾讯云后台建模板时占位符要这么写：

```text
{1} : 设备 ID  (例如 ws63-fall-client-001)
{2} : 报警时刻 (后端按本地时区拼)
{3} : 事件序号 (event_count，第几次报警)
```

短信示例：

```text
检测到跌倒报警，设备{1}，时间{2}，事件序号{3}，请立即查看。
```

语音示例：

```text
紧急提醒，检测到跌倒报警，设备{1}，时间{2}，请立即查看。
```

---

## 七、端到端联调步骤

照顺序做，**任何一步失败先解决再往下走**：

1. **后端先跑起来**

   ```powershell
   python tools\fall_alert_backend_demo.py --host 0.0.0.0 --port 8080
   ```

   看到 `Listening on http://0.0.0.0:8080/api/fall-alert` 即可。

2. **本机 curl 自测后端**

   ```powershell
   curl -X POST http://127.0.0.1:8080/api/fall-alert `
     -H "Content-Type: application/json" `
     -H "Authorization: Bearer change-me-demo-token" `
     -d "{\"device_id\":\"test\",\"event\":\"fall\",\"payload\":5,\"event_count\":1}"
   ```

   后端应该打印 `FALL ALERT` + JSON。这一步过了证明后端没问题，剩下出错就只可能在 WiFi/板子那边。

3. **确认 IP**

   电脑/服务器连上和板 B **同一个 WiFi**（手机热点 ok），命令行 `ipconfig` 看到的本机 IP 就是 `FALL_GATEWAY_SERVER_HOST` 要填的。

4. **改 `fall_alert_gateway_config.h`，编译，烧录板 B**

5. **板 B 上电**，串口应见到：

   ```text
   [FALL_GW] gateway task started.
   [FALL_GW] Wi-Fi scan start: <SSID>.
   [FALL_GW] Wi-Fi scan done.
   [FALL_GW] Wi-Fi connect start.
   [FALL_GW] Wi-Fi connected.
   [FALL_GW] DHCP success, ip=192.168.x.x.
   ```

   有 IP 就说明 WiFi 完全 OK。

6. **板 A 上电，触发跌倒**（甩一下/真摔），串口应见到：

   ```text
   [CLIENT] Notification: data[0]=0x05
   [FALL_GW] fall event queued, payload=0x05, count=1.
   [FALL_GW] HTTP response: HTTP/1.1 200 OK...
   [FALL_GW] fall alert uploaded.
   ```

   后端那边同时打印 `FALL ALERT` + 通知器输出（dry-run 时是 `[NOTIFY] dry-run enabled...`）。

7. **接真通知**：切到 `pushplus` 或 `tencent`，重新启动后端，再触发一次。

---

## 八、常见故障与对策

| 现象 | 原因 | 处理 |
|---|---|---|
| 板 B 一直 `Wi-Fi scan done` 后 `AP not found, retry` | SSID 拼错 / 路由器是 5G / SSID 含中文 | 改 2.4G、纯英数 SSID |
| 连上后 `DHCP timeout, retry Wi-Fi` | 路由器 DHCP 没分配 | 重启路由器；或在手机热点限制连接数里放开 |
| `connect server failed` | IP 错、端口防火墙拦、电脑没在同一网段 | 用 `ping <SERVER_HOST>` 从手机/另一台机器验证；Windows 防火墙放行 8080 |
| 后端返 `401` | Token 不一致 | `FALL_BACKEND_TOKEN` 和 `FALL_GATEWAY_AUTH_TOKEN` 必须一字不差 |
| 后端没反应、日志也没 | `--host 127.0.0.1` 启的 | 必须 `--host 0.0.0.0` 才能让局域网访问 |
| 报警进了但没收到短信 | `FALL_NOTIFY_DRY_RUN=1` 没关 / 腾讯云模板审核没过 / 联系人手机号没加国家码 | 总开关置 0；腾讯云控制台看模板状态；号码用 `+8613...` 格式 |
| 一次跌倒收到很多条 | AI 连击触发 | 检查板 A 的 `FALL_DETECT_COOLDOWN_MS` 和板 B 的 `FALL_GATEWAY_CLOUD_COOLDOWN_MS` 都生效；后端 `FALL_RATE_LIMIT_SECONDS` 是第三道闸 |
| 板 B 重启后连不上 WiFi | 路由器有 MAC 黑名单 / 静态 ARP 残留 | 重启路由器；或在路由器面板里删该 MAC |
| 串口看到 `HTTP send failed` 但 ping 没问题 | 后端 crash / 端口被占 | 后端那边 `netstat -ano | findstr 8080` 看进程；重启后端 |

---

## 九、和 4G DTU 那条线的关系

板 B 上跌倒触发时**同时调用了 2 个上报**：

```c
fall_alert_gateway_post_fall(data->data[0]);   // WiFi → 后端 → 微信/短信/语音
fall_alert_4g_dtu_post_fall(data->data[0]);    // UART1 → 银尔达 V100C → 真打电话 + 短信
```

它们是**互相独立**的两条通路：

- WiFi 这条：**需要现场有 WiFi 网络**，但通知形式丰富（微信卡片好读、语音可呼叫）。
- 4G 这条：**不依赖现场网络**，靠 V100C 模块上的 SIM 卡走运营商，覆盖更鲁棒，但只能发短信/打电话。

**两条都通**就是冗余高可用：WiFi 挂了 4G 上，4G 挂了 WiFi 上。比赛演示时建议两条都开着展示。

---

## 十、给后续维护人的话

- **不要把腾讯云 AccessKey/Secret 写到 `fall_alert_gateway_config.h`**。任何要发 SMS/语音的密钥都只能在后端。
- **任何新的"上报通道"（如钉钉机器人/飞书）**，加在后端 `make_notifier()` 里加一个新的 `Notifier` 子类，板子端**完全不用动**。这就是为什么固件只发到自家后端、不直接发到云厂商。
- WiFi 网关的状态机比较朴素（线性 INIT→SCAN→...→READY），失败一律退回 INIT。**不要在主循环里加 `osal_msleep > 1s`**，会让重连恢复变慢。
- `g_alert_pending` 是 `volatile bool`，单一生产者（SLE 回调）单一消费者（gateway 任务），没加锁。要加多消费者前先想清楚再动。
