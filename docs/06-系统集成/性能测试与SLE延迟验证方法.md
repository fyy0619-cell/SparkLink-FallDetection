# 性能测试与 SLE 延迟验证方法

本文是《[实时性·可靠性·星闪优势量化分析](实时性_可靠性_星闪优势量化分析.md)》的配套实操手册。

那篇分析里有些数字标了〔推导〕或〔未实测〕——本文教你**怎么把它们真正测出来**，让数据从「按参数推算」变成「实验测得」。每个方法都写清楚：**怎么改代码、怎么接线、怎么读数、测出来能怎么向别人解释**。

---

## 0. 严谨测量三原则（先记住）

任何一个数字要能被别人信服，必须做到：

1. **多次重复**：每项至少测 50–100 次，记录 **最小值 / 平均值 / 最大值**（必要时加标准差），不要只报一个数。
2. **记录条件**：写下当时的连接参数、固件构建配置、板间距离、有无干扰源、室温——换条件结果会变。
3. **声明工具精度**：用 `uapi_systick_get_ms()` 就只有 1ms 分辨率；要更细必须上示波器/逻辑分析仪。报数时不能超过工具精度。

> 这三条本身就是「别人问起来你怎么测的」最该先答的部分。

---

## 1. 测 SLE 通信时长（重点）

有两种方法，**方法 A 不需要仪器、先做**；**方法 B 需要示波器、最精确**。

### 1.1 方法 A：应用层往返法（推荐，无需仪器）

**原理**：本工程已经有 `0x05`（告警）→ `0x06`（ACK）的闭环。让**服务端在自己这一个时钟上**记录「发出 `0x05` 的时刻」和「收到 `0x06` 的时刻」，两者之差就是往返时间 RTT。因为用的是同一块板的同一个时钟，**不存在两板时钟不同步的问题**。

```
服务端发 0x05  ──OTA──▶  客户端 notification_cb
   t1 记录                  客户端回写 0x06
服务端 write_cbk  ◀──OTA──
   t2 记录          RTT = t2 - t1
```

**改代码（服务端 `sle_server_task.c`）**：

```c
#include "systick.h"               // 顶部加

static uint64_t g_perf_send_ts = 0; // 全局，记录发送时刻

// 在 sle_send_fall_alert() 里，ssaps_notify_indicate() 调用前一行：
g_perf_send_ts = uapi_systick_get_ms();
errcode_t ret = ssaps_notify_indicate(g_server_id, g_sle_conn_hdl, &param);

// 在 ssaps_write_request_cbk() 里，检测到 0x06 ACK 的分支内：
if (write_cb_para->value[0] == 0x06) {
    uint64_t rtt = uapi_systick_get_ms() - g_perf_send_ts;
    osal_printk("[PERF] SLE RTT = %llu ms\r\n", (unsigned long long)rtt);
}
```

**怎么跑**：触发 50–100 次跌倒告警（或临时写个测试任务，每 500ms 调一次 `sle_send_fall_alert`），串口收集所有 `[PERF] SLE RTT` 行，算 min/avg/max。

**怎么读数**：
- RTT = 往返延迟。
- 单向延迟 ≈ (RTT − 客户端处理时间) / 2。客户端处理（`notification_cb` 里点灯+组包+发 ACK）通常只有几十 µs~1ms，可作为很小的偏置。

**别人问你怎么测的，你就答**：「我利用系统自带的 `0x05`/`0x06` ACK 闭环，在服务端同一个时钟上测发送到收到 ACK 的往返时间，跑了 100 次，RTT 平均 X ms、最坏 Y ms，单向约 X/2 ms。用单时钟测往返就避开了两块板时钟不同步的误差。」

### 1.2 方法 B：双 GPIO + 示波器（最精确，测真·单向空口延迟）

**原理**：服务端「即将发包」的瞬间拉高一个 GPIO，客户端「收到包回调触发」的瞬间拉高另一个 GPIO。用**双通道示波器/逻辑分析仪**同时抓这两个上升沿，沿到沿的时间差就是真正的单向「应用到应用」延迟。

**接线（关键）**：
- 服务端选一个空闲 GPIO（避开 I²C 的 GPIO15/16）→ 示波器 CH1
- 客户端选一个空闲 GPIO（避开蜂鸣器/LED 的 GPIO08/09）→ 示波器 CH2
- **两块板的 GND 必须和示波器共地**，否则边沿对不齐、读数无意义

**改代码**：

```c
// —— 公共：测试引脚初始化（开机各调一次，PIN 换成你选的空闲引脚）——
#define PERF_PIN  GPIO_xx
uapi_pin_set_mode(PERF_PIN, PIN_MODE_0);
uapi_gpio_set_dir(PERF_PIN, GPIO_DIRECTION_OUTPUT);
uapi_gpio_set_val(PERF_PIN, GPIO_LEVEL_LOW);

// —— 服务端 sle_send_fall_alert()：notify 前拉高 ——
uapi_gpio_set_val(PERF_PIN, GPIO_LEVEL_HIGH);
ssaps_notify_indicate(g_server_id, g_sle_conn_hdl, &param);

// —— 客户端 my_sle_speed_notification_cb()：收到 0x05 立刻拉高 ——
if (data->data[0] == 0x05) {
    uapi_gpio_set_val(PERF_PIN, GPIO_LEVEL_HIGH);
    /* ...原有点灯/报警逻辑... */
}
```

每次测完把两个引脚拉低（`GPIO_LEVEL_LOW`）以便测下一次，或用示波器单次触发逐次记录。

**怎么读数**：Δt(CH2 上升沿 − CH1 上升沿) = 单向延迟，含「notify 等到下一个连接事件 + 空口传输 + 客户端协议栈送达回调」。这正是有工程意义的端到端链路延迟。

**别人问你怎么测的**：「我在服务端发包瞬间和客户端收包回调瞬间各翻转一个 GPIO，双通道示波器共地同时抓上升沿，直接读出单向空口延迟，精度到 µs，测了 N 次取 min/avg/max。」

### 1.3 两种方法怎么选

| 方法 | 需要仪器 | 测的是 | 精度 | 适用 |
| --- | --- | --- | --- | --- |
| A 往返法 | 无（只用串口） | 往返 RTT，单向靠估 | 1ms（systick） | 快速验证、答辩演示 |
| B 双 GPIO + 示波器 | 双通道示波器 | 真·单向延迟 | µs 级 | 正式量化、写进报告 |

建议：先用 A 拿到量级，再用 B 拿到可写进文档的精确值。

---

## 2. 测单次推理耗时（分析文档里唯一的〔未实测〕项）

**为什么之前没数**：Edge Impulse SDK 自带的计时函数没适配 WS63（开发日志已记录）。所以要**自己在外层包夹计时**。

**改代码（`ai_model.cpp`，`run_classifier()` 调用处）**：

```c
#include "systick.h"   // 顶部加（C++ 中包含，注意 extern "C"）

uint64_t t0 = uapi_systick_get_ms();
EI_IMPULSE_ERROR res = run_classifier(get_ai_impulse_handle(), &features_signal, &result, false);
uint64_t t1 = uapi_systick_get_ms();
ei_printf("[PERF] run_classifier = %llu ms\n", (unsigned long long)(t1 - t0));
```

**读数与精度**：
- 若结果是几百 ms：`systick` 的 1ms 分辨率够用，直接报。
- 若结果只有几 ms：1ms 分辨率不够 → 改用 **GPIO 翻转 + 示波器**（`run_classifier` 前拉高、后拉低，示波器量高电平宽度），或累计 100 次求平均。
- 想拆出「DSP 谱分析」vs「神经网络」各自耗时：需要进 Edge Impulse SDK 内部、在 DSP 块和 NN 块前后分别打点，属于进阶操作。

**端到端含义**：`run_classifier` 是同步阻塞的，这段时间主循环不采样。测出它，分析文档第 1.4 节的端到端公式就能补全。

---

## 3. 测喂样率（验证「~100Hz」这个推导）

**改代码（`main_task.c` 主循环里）**：

```c
static uint32_t s_cnt = 0;
static uint64_t s_t0 = 0;
if (s_t0 == 0) { s_t0 = uapi_systick_get_ms(); }
s_cnt++;
if (s_cnt >= 500) {
    uint64_t dt = uapi_systick_get_ms() - s_t0;
    osal_printk("[PERF] feed rate = %llu Hz\r\n", (unsigned long long)(s_cnt * 1000ULL / dt));
    s_cnt = 0;
    s_t0 = uapi_systick_get_ms();
}
```

每采 500 个样本打印一次实际频率。若印出来约 `100 Hz`，就证实了与模型期望的 200Hz 存在 2× 偏差；把循环 `osDelay` 改成 5ms 后重测，应接近 200Hz。

---

## 4. 测端到端延迟（跌倒动作 → 客户端报警）

难点：「跌倒发生的精确瞬间」很难打点。两种办法：

### 方法 1：计算法（推荐，用前面的实测组合）

```
端到端 ≈ T_推理(第2节实测) + 触发节拍640ms + 2窗确认(再 +640ms+T_推理) + T_SLE(第1节实测)
```

各分量都能单独测，组合即可，不必直接测整体。

### 方法 2：接触开关法（要直接测整体时）

把开发板固定在一块带**接触开关**的垫子上方，板子落到垫子时开关闭合：
- 接触开关的闭合边沿 → 示波器 CH1（视为「跌倒发生」时刻）
- 客户端报警 GPIO（收到 `0x05` 拉高）→ 示波器 CH2
- Δt(CH2 − CH1) = 含传感、攒窗、推理、确认、SLE 的完整端到端延迟

注意这个数会比较大且有抖动（取决于跌倒动作落在滑动窗口的哪个位置），同样要多测取分布。

---

## 5. SLE vs BLE 对比测试（凸显星闪优势的关键）

要让「星闪更快」有说服力，必须**同条件**对比。

**步骤**：
1. 先在 SLE 构建下，用第 1 节方法 A 或 B 测出延迟。
2. 切到 BLE 构建：`fall_detect/src/CMakeLists.txt` 里把 `MANUAL_SLE_SWITCH` 设为 `OFF`，重新编译烧录（告警走 `Ble_Send_Fall_Alert`）。
3. 用**完全相同的方法、相同的 1 字节载荷**再测一遍。
4. 做对比表。

| 链路 | 连接间隔 | 单向延迟实测(min/avg/max) | 测试方法 |
| --- | --- | --- | --- |
| SLE | 6.25–12.5ms | （填实测） | 方法 B |
| BLE | （填 BLE 配置） | （填实测） | 方法 B |

> BLE 路径若没有 `0x06` ACK 回写，就只能用方法 B（双 GPIO）测，不能用方法 A。

进阶：把 SLE 的连接间隔从 `0x0032/0x0064` 下调到 `0x0008`（1ms）等更小值（改 `sle_speed_server_adv.c`），重测，验证 SLE 能逼近亚毫秒——这才真正体现 SLE 的规格优势。

---

## 6. 抗干扰 / 丢包率测试

体现 SLE 可靠性的另一个维度：强干扰下还能不能送达。

**步骤**：
1. 写个测试模式：服务端循环发 `N = 1000` 次 `0x05`，每次间隔固定（如 200ms），用第 1 节方法 A 统计收到多少次 `0x06` ACK。
2. **送达率 = 收到 ACK 次数 / 发送次数**。
3. 分两种环境各测一轮：① 安静环境；② 旁边放 Wi-Fi 路由器灌流量 / 微波炉等 2.4GHz 干扰源。
4. SLE 构建和 BLE 构建各做一遍，对比。

| 环境 | 链路 | 发送 | 收到ACK | 送达率 |
| --- | --- | --- | --- | --- |
| 安静 | SLE | 1000 | | |
| 干扰 | SLE | 1000 | | |
| 安静 | BLE | 1000 | | |
| 干扰 | BLE | 1000 | | |

---

## 7. 测量记录模板

每轮测试用这张表存档，保证可复现、可追溯：

```
测试项目：______________________
日期 / 室温：____________________
固件构建：SLE / BLE   ；角色：Server / Client
连接参数：conn_interval=____  supervision_timeout=____
板间距离：______ cm   ；干扰源：无 / ____________
测量工具：systick(1ms) / 示波器(型号____, 采样率____)
样本数 N：______
结果：min=____  avg=____  max=____  (单位____)
备注：__________________________
```

---

## 8. 严谨性自查清单

向别人汇报前，对照检查：

- [ ] 每个数字都说明了来源方法（A/B/计算法）
- [ ] 每个数字都是 N≥50 次的 min/avg/max，不是单次值
- [ ] 报告精度不超过工具精度（systick 不报小数 ms）
- [ ] 记录了连接参数、构建配置、干扰条件
- [ ] SLE/BLE 对比是同方法、同载荷、同环境
- [ ] 测试用的临时打点代码，正式固件里可关掉或保留为调试开关

---

> 配套文档：[实时性·可靠性·星闪优势量化分析](实时性_可靠性_星闪优势量化分析.md)、[SLE SSAP 通知链路全解析](SLE_SSAP通知链路.md)
