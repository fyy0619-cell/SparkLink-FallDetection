# 跌倒报警 4G 通知（拨号 + 短信）实现与调试复盘

本文记录「板 B（WS63）收到跌倒报警后，经 4G DTU 自动拨打电话 + 发短信到指定号码」这条
通知链路的完整实现方案，以及联调过程中遇到的**全部问题与解决路径**，方便以后复盘。

---

## 1. 目标

板 A 检测到跌倒后，板 B（WS63 客户端）收到星闪 SLE 通知 `0x05`，需要**立刻**：

- 拨打电话到家属/监护人号码；
- 发送一条短信到同一号码。

WS63 本身不带 4G，拨号和发短信由外接的 **V100C / Air780EHV 4G DTU** 完成。

---

## 2. 整体架构

```text
板A(雷达/MPU6050 + AI)
  检测到跌倒
        |  星闪 SLE / SSAP Notify  发 0x05
        v
板B(WS63 客户端)
  sle_client_task.c 收到 0x05 -> fall_alert_4g_dtu_post_fall()
  fall_alert_4g_dtu.c 经 UART1 发两行 JSON:
     {"cmd":"sms" ,"phone":"...","text":"...","device":"...","event_count":N}\r\n
     {"cmd":"call","phone":"...","device":"...","payload":N,"event":"fall_alert"}\r\n
        |  UART  115200 8N1
        v
4G DTU(V100C / Air780EHV, 银尔达 DTU 固件 + LuatOS Lua5.3)
  「任务」脚本收 UART -> 拆 JSON -> cc.dial() 拨号 + SmsSend() 发短信
        |  4G 移动网络
        v
家属手机：来电响铃 + 收到短信
```

**职责划分**：WS63 只是“指令发起方”，真正拨号/发短信的动作在 DTU 上的 LuatOS「任务」脚本里。

---

## 3. 硬件接线

| WS63 | 方向 | DTU(V100C) |
|---|---|---|
| GPIO15 (UART1_TX) | ──► | 数据串口 RXD |
| GPIO16 (UART1_RX) | ◄── | 数据串口 TXD |
| GND | ─── | GND（必须共地） |

- TX/RX 必须**交叉**（一端 TX 接另一端 RX）。
- 两块板各自供电时，**中间一定要补一根 GND 线**。
- WS63 串口参数：`UART_BUS_1` / `GPIO15` / `GPIO16` / `PIN_MODE_1` / 115200 / 8N1。
  已对照 SDK `middleware/.../ws63_w33_evb/tiot_board_uart_port_config.h` 确认该 pinmux 正确。
- DTU 侧串口参数（银尔达平台「串口参数」页）：115200 / 8 / 无校验 / 1 位 / 打包超时 80ms。

> **关键结论**：WS63 这根线实测接在 DTU 的 **串口 id = 2**（不是 id 1）。
> DTU「任务」里 `UartGetRecChAndDel()` 必须用 `2`。详见第 7 节问题复盘 #9。

---

## 4. 前提条件（任一不满足都打不出电话/发不出短信）

1. **SIM 卡**：必须是移动/联通的**普通手机卡**。电信卡不行，物联网卡不支持。
2. **VoLTE**：Air780E 是纯 4G Cat.1 模块，不开 VoLTE 打不了电话。
   用 AT 口发 `AT+SETVOLTE?`，返回 `1` 才行；固件名带 `NOVOLTE` 的不支持。
3. **DTU 固件版本** ≥ V1.1.13（`SmsSend` 要求）。
4. DTU 已正常注册上 4G 网络。

---

## 5. 银尔达 DTU 任务 API 速查

| API | 说明 |
|---|---|
| `UartStopProRecCh(on)` | 参数 **0/1**（1=停止 DTU 内部处理所有串口通道）。**不是串口号**。任务要自己收串口，必须先调 `UartStopProRecCh(1)`。 |
| `UartGetRecChAndDel(id)` | 读串口 `id`（范围 1/2/3）的缓存数据并清除。无数据返回 `nil`。循环读到 nil 为止。 |
| `UartSetSendCh(id, s)` | 向串口 `id` 发送字符串。 |
| `SmsSend(num, msg)` | 发短信。返回 `1` 成功 / `0` 失败。需固件 ≥ V1.1.13、移动/联通卡。 |
| `cc.init(0)` | 初始化电话系统。需在收到 `CC_IND` 的 `READY` 后调用。 |
| `cc.dial(0, num)` | 拨号。第一个参数 `0`，第二个是号码字符串。 |
| `cc.hangUp()` / `cc.accept(0)` / `cc.lastNum()` | 挂断 / 接听 / 最后通话号码。 |
| `CC_IND` 消息 | 通话状态：`READY` / `CONNECTED` / `SPEECH_START` / `INCOMINGCALL` / `DISCONNECTED` / `MAKE_CALL_FAILED` / `HANGUP_CALL_DONE`。用 `sys.subscribe("CC_IND", fn)` 订阅。 |
| `json.decode(str)` / `log.info(...)` | JSON 解析 / 打印日志。任务环境可用。 |
| `sys.wait/subscribe/publish/waitUntil/timerLoopStart/timerStop` | LuatOS 系统接口。 |

---

## 6. 银尔达「任务」脚本格式约定

- 脚本必须以 **`function` 开头、`end` 结尾**（裸 `function`，不带函数名、不带 `()`，平台自己包装）。
- **脚本第一行必须就是 `function`**，前面不能有空格、空行或 `--[[ ]]` 块注释，否则上传报
  `function arguments expected near '...'`。
- 函数体内可以用 `--` 单行注释；整个配置文件上限 50K。
- 在 Luatools 里离线验证时，临时把 `function` 改成 `function test()` 并加
  `sys.taskInit(test)` / `sys.run()`，验证完再删掉、改回裸 `function`。

---

## 7. 问题复盘（完整调试路径）

| # | 现象 / 问题 | 根因 | 解决方案 |
|---|---|---|---|
| 1 | 语雀 API 手册在线打不开 | 网络策略拦截 `yinerda.yuque.com` | 改用截图把文档内容贴出来 |
| 2 | 任务上传报错 `function arguments expected near 'tname'` | 脚本开头加了 `--[[ ]]` 块注释，把必须在首行的 `function` 顶下去了 | 删掉块注释，第一行直接 `function`，说明文字改成 `--` 单行注释放进函数体内 |
| 3 | 不确定拨号 API | 银尔达任务环境支持合宙 `cc` 库 | `cc.dial(0, 号码)`，配 `cc.init(0)` + 订阅 `CC_IND` 状态事件 |
| 4 | 不确定短信 API | API 手册「十五、短信类 API」 | `SmsSend(号码, 内容)`，返回 1/0 |
| 5 | WS63 连发两条 JSON，DTU `json.decode` 失败 | 一次 `UartGetRecChAndDel` 读到两条粘在一起 | 收到的数据先进缓冲区，按 `\r\n` 拆成整行后逐条 `json.decode` |
| 6 | 担心短信阻塞拨号 | `SmsSend` 可能阻塞数秒 | 同一批指令**先处理 `call` 再处理 `sms`**，保证“立刻拨号” |
| 7 | 完整任务跑起来了，但手机不响 | 见 #8 / #9 / #10 | 拆成最小测试逐步隔离 |
| 8 | 不确定 DTU 本身能力 | —— | **selftest**：DTU 自己上电直接拨号+发短信 → 通过，证明 `cc.dial`/`SmsSend`/SIM/VoLTE/网络/任务上传都正常 |
| 9 | **DTU 收不到 WS63 的串口数据**（核心 bug） | 任务里写死 `UartGetRecChAndDel(1)`，而 WS63 实际接在 DTU 的**串口 id=2** | **uarttest**：同时监听串口 1/2/3，哪个口收到数据就发短信报告 → 短信回报 `id=2`。任务改 `uid=2` |
| 10 | WS63 早发的数据丢失 | `UartStopProRecCh` 排在 `sys.waitUntil("CC_READY")` 之后，注册网络的几十秒里串口数据没人收 | 把 `UartStopProRecCh(1)` 挪到任务**最前面**，一上电就开始缓存串口数据 |
| 11 | 没有 USB 线，看不了 DTU 日志 | 官方调试要 USB 线 + Luatools + 平台开「DTU日志输出」 | 改用“手机响铃 / 收到短信”作为可观测信号，配合 selftest/uarttest 定位 |
| 12 | 怀疑 WS63 串口 pinmux 配错 | —— | 对照 SDK `tiot_board_uart_port_config.h`：`GPIO15/16 + PIN_MODE_1 + UART_BUS_1` 是正确的 UART 配置，排除该项 |

**最关键的两条**：#9（串口号 1→2）和 #10（`UartStopProRecCh` 提前）。修正后链路全部打通。

调试时用到的隔离测试脚本，思路是“去掉变量，一次只验证一环”：

- `selftest`：不接 WS63、不收串口，DTU 自己上电就拨号+发短信 → 验证 **DTU 自身能力**。
- `uarttest`：同时监听串口 1/2/3，收到任意数据就拨号并发短信报告是几号口 → 验证 **UART 链路**并定位串口号。

---

## 8. 文件清单

DTU 侧（银尔达平台「任务」，本仓库 `tools/`）：

| 文件 | 用途 |
|---|---|
| `tools/v100c_uart_call_task.lua` | **最终正式任务**：收 WS63 JSON → 拨号 + 发短信。`uid=2` |
| `tools/V100C_PASTE_THIS_TO_TASK1.lua` | 同上，内容一致，作为“直接粘贴到任务1”的副本 |
| `tools/v100c_uart_test.lua` | 串口链路诊断：监听串口 1/2/3，定位 WS63 接的是哪个 id |
| `tools/v100c_min_call_test.lua` | 早期最小拨号测试 |
| `tools/v100c_min_sms_test.lua` | 早期最小短信测试 |

WS63 侧（WS63 工程，不在本仓库）：

| 文件 | 用途 |
|---|---|
| `application/samples/my_demo/fall_detect/src/fall_alert_4g_dtu.c` | 跌倒后经 UART1 发 JSON 指令 |
| `application/samples/my_demo/fall_detect/inc/fall_alert_4g_dtu_config.h` | 串口/号码/短信内容/自检开关等配置 |
| `application/samples/my_demo/fall_detect/src/sle_client_task.c` | 收到 SLE `0x05` 时调用 `fall_alert_4g_dtu_post_fall()` |

---

## 9. 验收 / 测试方法

1. DTU 侧：把 `tools/v100c_uart_call_task.lua` 粘到银尔达平台「任务」，保存，重启 DTU。
2. WS63 侧自检（不用真摔）：把 `fall_alert_4g_dtu_config.h` 的
   `FALL_ALERT_4G_DTU_BOOT_TEST_ENABLED` 设为 `1`，编译烧录。上电 8 秒后会自动发一次测试 JSON。
3. 先给 DTU 上电、等约 1 分钟联网就绪，再复位 WS63。
4. 目标手机应**响铃 + 收到短信**。
5. 验收通过后，把 `FALL_ALERT_4G_DTU_BOOT_TEST_ENABLED` 改回 `0` 并重新烧录，
   否则每次上电都会拨号。改回 `0` 后只有真实跌倒（SLE 收到 `0x05`）才触发。

WS63 串口日志中出现下面三行即代表 WS63 侧已正常发出：

```text
[FALL_DTU] fall event queued, payload=0x55, count=1.
[FALL_DTU] JSON cmd=sms sent to V100C: count=1, len=148, phone=configured.
[FALL_DTU] JSON cmd=call sent to V100C: payload=0x55, count=1, len=120, phone=configured.
```

DTU 侧日志需 USB 线接 DTU + Luatools，并在平台「基本参数」页把「DTU日志输出」设为开启。

---

## 10. 备注

- WS63 侧有 60 秒冷却（`FALL_ALERT_4G_DTU_COOLDOWN_MS`），同一次跌倒反复触发只通知一次。
- 短信正文默认英文，避开编码问题；如需中文需确认 DTU 固件对 UCS2 的支持。
- DTU 脚本里 `outgoing_number` 的占位号码仅作兜底，实际号码以 WS63 下发 JSON 的 `phone` 为准；
  要改号码改 WS63 的 `fall_alert_4g_dtu_config.h` 里 `FALL_ALERT_4G_DTU_PHONE`。
