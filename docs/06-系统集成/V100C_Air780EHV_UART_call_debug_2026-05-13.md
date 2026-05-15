# V100C / Air780EHV 串口触发电话报警调试记录（2026-05-13）

> 本文记录 WS63 跌倒检测系统接入银尔达 V100C / Air780EHV 4G DTU 后，从“收到跌倒信号”到“自动拨打电话”的完整调试流程、关键问题、验证方法和最终解决方案。文档不包含真实手机号、IMEI、SIM 信息或平台账号信息。
>
> 在打电话基础上新增的「短信告警」实现见 [V100C 短信告警实现](V100C_短信告警实现.md)。

## 1. 最终结论

2026-05-13 已验证通过的链路：

```text
Board A 跌倒检测
    -> SLE 通知 0x05
    -> Board B SLE Client 收到报警
    -> 本地蜂鸣器 / LED / WS2812B 红灯报警
    -> Board B UART1 输出 JSON
    -> V100C / Air780EHV 任务脚本读取外部 RXD/TXD 数据
    -> json.decode() 解析 cmd=call + phone
    -> cc.dial(0, phone)
    -> 电话响铃
```

关键结论：

- WS63 侧 SLE、报警联动、UART JSON 发送链路已经工作。
- V100C、SIM 卡、电话功能、`cc.dial()` 已通过极简脚本验证。
- 真正的阻塞点是银尔达后台“任务”脚本格式：任务必须以 `function` 开头、以 `end` 结尾，不能直接粘贴普通 LuatOS `sys.taskInit(function() ... end)` 工程脚本。
- 最终使用 `tools/V100C_PASTE_THIS_TO_TASK1.lua` 粘贴到银尔达后台任务1，报警时电话已打通。

## 2. 硬件与平台

| 项目 | 当前配置 |
| --- | --- |
| 跌倒检测节点 | WS63 Board A，MPU6050 + TinyML + SLE Server |
| 报警网关节点 | WS63 Board B，SLE Client + 本地声光报警 + UART DTU 输出 |
| 4G DTU | 银尔达 V100C / Air780EHV |
| V100C 平台 | `https://www.yinerda.com/dtupt` |
| 分组 | `fall` |
| 外部串口 | V100C 外部 RXD/TXD，银尔达任务 API 串口 ID 为 `1` |
| WS63 UART | `UART_BUS_1`，TX=`GPIO_15`，RX=`GPIO_16`，baud=`115200` |
| 连接方式 | WS63 TX -> V100C RXD；WS63 RX <- V100C TXD；GND 共地 |

V100C 后台配置入口：

```text
参数设置 -> 分组管理 -> fall -> 参数配置 -> 任务
```

## 3. WS63 侧验证现象

Board B 启动后日志显示 UART DTU 任务初始化成功：

```text
[FALL_DTU] UART ready: bus=1 tx=15 rx=16 baud=115200.
[FALL_DTU] task started.
```

收到 Board A 的 SLE 跌倒通知后，Board B 触发本地报警并发送 JSON：

```text
[CLIENT] Notification: data[0]=0x05
[ALERT] start: buzzer ON, normal LED ON, WS2812B RED request, hold_ms=0
[FALL_GW] fall event queued, payload=0x05, count=1.
[FALL_DTU] fall event queued, payload=0x05, count=1.
[FALL_DTU] JSON cmd=call sent to V100C: payload=0x05, count=1, len=119, phone=configured.
```

这说明：

- Board A -> Board B 的 SLE 报警链路正常。
- Board B 本地声光报警正常。
- Board B 已经通过 UART 写出了给 V100C 的 JSON。
- Wi-Fi 日志中的 `AP not found` 与 V100C 电话链路无关，不影响 4G DTU 拨号验证。

WS63 发给 V100C 的 JSON 形态：

```json
{"cmd":"call","phone":"<TARGET_PHONE>","device":"ws63-fall-client-001","payload":5,"event_count":1,"event":"fall_alert"}
```

手机号由 WS63 工程配置生成，不写死在 V100C 任务脚本中。

## 4. 关键问题与解决办法

### 4.1 不知道 V100C 后台与任务入口在哪里

问题表现：

- 一开始不清楚“V100C 配置工具 / 银尔达后台”指什么。
- 不知道 Lua 任务脚本应该放到哪里。

解决办法：

1. 打开银尔达 DTU 管理平台：`https://www.yinerda.com/dtupt`。
2. 添加 V100C 设备。
3. 创建 V100C 分组，例如 `fall`。
4. 将设备加入该分组。
5. 进入 `参数设置 -> 分组管理 -> fall -> 参数配置 -> 任务`。
6. 在 `任务1` 文本框中粘贴任务脚本，`是否启动` 选择 `启动`。
7. 保存参数，确认设备参数版本同步成功。

已验证平台侧同步现象：

```text
分组参数版本 = 设备参数版本
未更新设备数量 = 0
```

### 4.2 任务脚本格式错误

最初错误做法：把完整 LuatOS 风格脚本或带注释头的脚本直接粘到银尔达任务框，例如：

```lua
-- V100C / Air780EHV DTU task ...
local UART_ID = 1
...
sys.taskInit(function()
    ...
end)
```

银尔达官方任务格式要求：

```lua
function
    -- 任务代码必须在这里
    while true do
        sys.wait(100)
    end
end
```

注意事项：

- 第一行必须是 `function`。
- 最后一行必须是 `end`。
- `function` 前面不要有注释、空格或其他 Lua 代码。
- `end` 后面不要再追加其他代码。
- 所有 `local function`、变量定义、循环逻辑都要写在外层 `function ... end` 内部。
- 后台任务框不要粘 `PROJECT`、`VERSION`、`sys.run()` 这类本地 Luatools 工程包装代码。

最终脚本已整理为可直接粘贴版：

```text
tools/V100C_PASTE_THIS_TO_TASK1.lua
```

该文件第一行就是 `function`，可直接全选复制到银尔达后台任务1。

### 4.3 极简拨号测试的作用

为避免同时怀疑 WS63、UART、V100C、SIM、任务格式，先做了极简拨号测试。

测试脚本：

```text
tools/v100c_min_call_test.lua
```

测试方法：

1. 将脚本中的占位号码改为测试手机号。
2. 只把这个极简脚本粘到 `任务1`。
3. 保存参数并同步到 V100C。
4. 必要时重启 V100C。
5. 观察手机是否响铃。

验证结果：

```text
极简拨号测试通过，电话响铃。
```

由此排除：

- SIM 卡不可用。
- V100C 不支持电话。
- `cc.dial()` 不可用。
- 银尔达后台参数未同步。

剩余问题只可能在：

- UART 任务脚本格式。
- WS63 -> V100C 串口数据接收。
- V100C 对 JSON 的解析和拨号逻辑。

### 4.4 电话号码应该在哪里改

最终设计中，V100C 脚本不保存目标号码，而是从 WS63 JSON 的 `phone` 字段读取：

```lua
if (obj.cmd == "call" or obj.cmd == "fall_alert") and type(obj.phone) == "string" then
    makeCall(obj.phone)
end
```

因此电话号码在 WS63 工程中配置：

```text
application/samples/my_demo/fall_detect/inc/fall_alert_4g_dtu_config.h
```

配置项：

```c
#define FALL_ALERT_4G_DTU_PHONE "<TARGET_PHONE>"
```

注意：

- GitHub 文档和示例脚本只保留 `<TARGET_PHONE>` 或 `123xxxx4567` 占位符。
- 不要把真实手机号、IMEI、SIM 卡号、后台账号或 token 提交到仓库。
- 修改 WS63 号码后需要重新编译并烧录 Board B。

### 4.5 报警时拨了两个电话

现象：

- 最终报警电话打通后，发现似乎还给之前极简测试号码拨了一次。

原因判断：

- 银尔达后台可能同时保留了多个任务。
- 或者任务1中没有完全清空旧极简拨号脚本，旧号码还留在任务框里。
- 极简脚本会在任务启动后自动拨一次；UART 脚本会在收到 WS63 JSON 后再拨一次，所以会表现为两个电话。

解决办法：

1. 进入 `参数设置 -> 分组管理 -> fall -> 参数配置 -> 任务`。
2. 只保留一个任务。
3. 删除多余任务，或确保多余任务未启动。
4. 清空任务1文本框。
5. 重新粘贴 `tools/V100C_PASTE_THIS_TO_TASK1.lua` 的完整内容。
6. 搜索任务框中是否还有旧测试号码。
7. 保存参数，同步到设备，必要时重启 V100C。

最终 UART 任务脚本本身没有写死号码，因此清理旧任务后不会再自动拨旧测试号码。

## 5. 当前仓库新增脚本

| 文件 | 用途 |
| --- | --- |
| `tools/v100c_min_call_test.lua` | V100C 电话能力最小验证脚本；只用于排查 SIM / cc.dial / 任务同步问题 |
| `tools/v100c_uart_call_task.lua` | V100C 正式 UART JSON 触发拨号任务脚本 |
| `tools/V100C_PASTE_THIS_TO_TASK1.lua` | 与正式脚本内容一致，文件名强调“复制这个到任务1”，避免误复制旧脚本或注释头 |

## 6. 正式操作步骤

### 6.1 V100C 后台

1. 打开 `tools/V100C_PASTE_THIS_TO_TASK1.lua`。
2. 确认第一行是：

```lua
function
```

3. `Ctrl+A` 全选，`Ctrl+C` 复制。
4. 到银尔达后台任务1文本框中清空旧内容。
5. 粘贴脚本。
6. 确认最后一行是：

```lua
end
```

7. 设置 `是否启动 = 启动`。
8. 保存参数，等待设备参数版本同步。
9. 必要时重启 V100C。

### 6.2 WS63 Board B

修改目标号码：

```text
application/samples/my_demo/fall_detect/inc/fall_alert_4g_dtu_config.h
```

编译：

```powershell
cd D:\fbb_ws63\fbb_ws63-master\src

$env:PATH = "D:\tools_link\tools\cfbb\thirdparty\ccache;D:\tools_link\tools\Windows\cc_riscv32_musl_win\bin;D:\tools_link\tools\Windows\cc_riscv32_musl_fp_win\bin;D:\tools_link\tools\Windows\cc_riscv32_win_env;D:\tools_link\tools\Windows\ninja;D:\tools_link\tools\python\Scripts;D:\tools_link\tools\python\Lib\site-packages\cmake\data\bin;D:\fbb_ws63\fbb_ws63-master\src\tools\bin\compiler\riscv\cc_riscv32_musl_105\cc_riscv32_musl_win\bin;D:\fbb_ws63\fbb_ws63-master\src\tools\bin\compiler\riscv\cc_riscv32_musl_105_fp\cc_riscv32_musl_fp_win\bin;$env:PATH"

d:\tools_link\tools\python\python.exe build.py ws63-liteos-app
```

烧录：

```text
D:\fbb_ws63\fbb_ws63-master\src\output\ws63\acore\ws63-liteos-app\ws63-liteos-app-sign.bin
```

### 6.3 触发测试

1. Board A 触发跌倒检测。
2. Board B 收到 `0x05`。
3. Board B 本地声光报警。
4. Board B 发送 UART JSON。
5. V100C 解析 JSON 并拨号。
6. 手机响铃。

## 7. 调试检查表

| 现象 | 优先检查项 | 处理方式 |
| --- | --- | --- |
| 极简拨号不响 | V100C 电话系统、SIM、任务格式、参数同步 | 先用 `v100c_min_call_test.lua`，看 `CC_IND` 和 `dial result` |
| 极简拨号响，跌倒不拨号 | UART 接线、串口 ID、正式任务脚本 | 检查 WS63 TX -> V100C RXD、GND 共地、`UartGetRecChAndDel(1)` |
| 任务不运行 | 第一行不是 `function`、最后一行不是 `end` | 使用 `V100C_PASTE_THIS_TO_TASK1.lua` 完整覆盖任务1 |
| 拨了旧号码 | 旧极简任务未删除或任务框未清空 | 删除多余任务，清空任务1后重粘正式脚本 |
| 频繁触发但只拨一次 | WS63 冷却合并生效 | `FALL_ALERT_4G_DTU_COOLDOWN_MS` 默认 60 秒，是正常保护 |
| 日志里 Wi-Fi AP not found | Wi-Fi 网关路径未连上热点 | 与 V100C 电话链路无关，可暂时忽略 |

## 8. 后续建议

- 比赛演示前固定一套流程：先极简拨号验证 V100C，再切正式 UART 任务，再触发 WS63 跌倒。
- 保留 `V100C_PASTE_THIS_TO_TASK1.lua`，防止误复制带注释头的旧脚本。
- 演示前确认银尔达后台只有一个启动任务，避免旧测试号码残留。
- 若需要现场展示日志，优先展示 WS63 串口日志中的 `JSON cmd=call sent to V100C` 和手机响铃结果。
- GitHub 仓库只保存占位号码；真实号码只放在本地 WS63 配置或现场后台中。
