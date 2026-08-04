# 硬件定时器（Timer）驱动 —— 从物理原理到 200Hz 采样，手把手从 0 实现

> 本项目用**硬件定时器 1** 产生精确的 **200Hz（每 5ms 一次）** 节拍来采样 MPU6050，喂给 TinyML 推理。
> 本文从**物理原理 → 板子硬件 → 代码从 0 一步步实现**，目标是你能自己动手写出来。
> 对应源码：`main.c` 的 `hw_init()`（一次性初始化）+ `main_task.c` 的采样流水线。

---

## 一、物理原理：定时器到底"定"的是什么？

**一句话：硬件定时器 = 一个由时钟驱动、会自己数数的计数器；数到设定值就"啪"地产生一个硬件中断。**

拆开看三个要素：

1. **时钟源（心跳）**：芯片给定时器一路固定频率的时钟。本芯片定时器时钟 = **24 MHz**（编译宏 `CONFIG_TIMER_CLOCK_VALUE=24000000`）。
   - 24 MHz 意味着它**每秒跳 24,000,000 下**，每一下（1 tick）= `1 / 24MHz ≈ 41.67 纳秒`。

2. **计数器（数数的寄存器）**：一个硬件寄存器，被时钟每来一下就 +1（或从装载值 −1）。它**完全由硬件自动数，不占用 CPU**。

3. **比较/归零 → 触发中断**：你设一个目标值，计数器数到它时，硬件**自动产生一个中断信号**，CPU 立刻跳去执行你的**回调函数**。

### "微秒"是怎么换算成"数多少下"的

你调 API 时给的是**微秒（us）**，驱动帮你换成 tick：

```
ticks = 时间(us) × (时钟频率 / 1,000,000)
      = 时间(us) × (24,000,000 / 1,000,000)
      = 时间(us) × 24
```

本项目 5000us（200Hz）：`ticks = 5000 × 24 = 120,000`。
即计数器数 12 万下（约 5ms）就触发一次中断 —— 这就是"200Hz 精确节拍"的物理来源。

> **为什么用硬件定时器而不是 `osDelay` / 软件延时？**
> `osDelay` 靠操作系统调度，受任务优先级、系统负载影响，**节拍会抖**；硬件定时器由**独立硬件计数**，不受 CPU 忙不忙影响，**5ms 就是 5ms**，采样才不会失真。对采样/AI 这种要求等间隔的场景，必须用硬件定时器。

---

## 二、板子硬件：WS63 上有什么

- WS63 有 **3 个独立硬件定时器**，索引为 `TIMER_INDEX_0 / TIMER_INDEX_1 / TIMER_INDEX_2`（`timer_index_t`，共 `TIMER_MAX_NUM=3` 个）。
- 每个定时器有**自己的中断号**，例如 timer 1 的中断是 `TIMER_1_IRQN`。计数器归零 → 拉起这个中断 → CPU 进你的回调。
- **一个硬件定时器可以挂多个"逻辑定时器"**：`uapi_timer` 是一层软件多路复用——你可以在同一个 `TIMER_INDEX_1` 上 `create` 出好几个定时器句柄，驱动把它们复用到这一个硬件计数器上（官方 `timer_demo.c` 就在 index 1 上建了 4 个）。
  - **副作用**：多个逻辑定时器共用一个硬件计数器时，若在**中断里**重载定时器，可能和别的共享定时器抢 cycle 导致下溢出错（本项目特意把"重载"放到任务里做，见后文坑点）。

本项目分工：**硬件 timer 1 专门用于 200Hz 采样节拍。**

### 中断与中断号（为什么 `uapi_timer_adapter` 要传中断号）

调 `uapi_timer_adapter(index, TIMER_x_IRQN, prio)` 时那个 `TIMER_x_IRQN` 是**中断号**，这里讲清它是什么、为什么必须有。

**① 什么是中断，定时器为什么离不开它**
定时器在硬件里**自己数数**（不占 CPU）。数到 0 那一刻，它得**通知 CPU"时间到了"**，CPU 才好跳去跑你的回调——这个"通知"就是**发一个中断**。
没有中断，CPU 要么傻等/不停轮询计数器（浪费 CPU），要么永远不知道到点了。所以**定时器必须靠中断**来主动通知 CPU。

**② 中断"号"是干什么的**
芯片里能发中断的东西很多：timer0/1/2、UART、GPIO、I2C… 几十个，都走 CPU 同一套中断机制。
问题：中断来了，CPU 怎么知道是谁发的？→ **给每个中断源分配一个唯一编号 = 中断号（IRQ number）**。
```c
// drivers/chips/ws63/include/chip_core_irq.h
TIMER_0_IRQN = LOCAL_INTERRUPT0 + 0,   // timer0 的中断号
TIMER_1_IRQN = LOCAL_INTERRUPT0 + 1,   // timer1 的中断号
TIMER_2_IRQN = LOCAL_INTERRUPT0 + 2,   // timer2 的中断号
```
> 类比：酒店前台（中断控制器）管很多房间（外设），每个房间有**房间号**。202 房按呼叫铃，前台一看"是 202 号"就知道派谁去。**房间号=中断号**，用来区分是谁在呼叫。

**③ adapter 传中断号 = 登记"这个号归谁处理"**
```c
uapi_timer_adapter(2, TIMER_2_IRQN, 1);
//                 定时器2  它的中断号  优先级
```
这句在登记："**中断号 `TIMER_2_IRQN` 一旦触发，就是 timer2 的中断，交给定时器驱动处理**。" 有了它，中断才能被正确路由到你的回调：
```
硬件timer2数到0 → 拉起中断号 TIMER_2_IRQN
   → 中断控制器识别"TIMER_2_IRQN 归timer驱动"(adapter登记的)
   → 进驱动内部ISR timer_int_callback
   → 调你的回调 hello_timer_cb
```
**中断号就是这条通知链的"地址标签"。**

**④ 号必须和定时器 index 对上**
timer2 硬件上物理拉的就是 `TIMER_2_IRQN` 这根线。若写成 `TIMER_1_IRQN`，等于"我是 timer2 却去监听 timer1 的门铃"——timer2 真正按的门铃没人登记 → **中断进不来、回调永不触发**（还可能和 timer1 打架）。所以 `index=2` 就必须配 `TIMER_2_IRQN`。

**⑤ 最后那个优先级参数**
`adapter(2, TIMER_2_IRQN, 1)` 的 `1` 是**中断优先级**：多个中断同时来时，谁先处理、能否打断别人。一般小 demo 给个固定值即可。

---

## 三、API 全景（`include/driver/timer.h`）

| 函数 | 作用 | 何时调 |
|---|---|---|
| `uapi_timer_init()` | 初始化定时器模块 | 开机一次 |
| `uapi_timer_adapter(index, int_id, prio)` | 把某个硬件定时器**绑定到它的中断号+优先级** | 开机一次 |
| `uapi_timer_create(index, &handle)` | 在某硬件定时器上**创建一个逻辑定时器**，拿到句柄 | 用前一次 |
| `uapi_timer_start(handle, time_us, cb, data)` | **启动**：`time_us` 微秒后触发 `cb`（**单次！**） | 每次要计时 |
| `uapi_timer_stop(handle)` | 停止 | 不用时 |
| `uapi_timer_delete(handle)` | 删除、释放句柄 | 清理 |

回调类型：
```c
typedef void (*timer_callback_t)(uintptr_t data);   // data 是你 start 时传入的透传参数
```

> **最重要的一条：`uapi_timer_start` 是"单次触发（one-shot）"**——响一次就停。想要**周期性**，必须在响过之后**再 start 一次**（重载/re-arm）。这点是新手最容易栽的坑。

---

## 四、代码从 0 一步步实现

### 步骤 0：一次性的底层初始化（开机时，已在 main.c 做好）

`main.c` 的 `hw_init()` 里已经有：
```c
uapi_timer_init();                                   // ① 初始化定时器模块
uapi_timer_adapter(1, TIMER_1_IRQN, irq_prio(TIMER_1_IRQN)); // ② 绑定 timer1 的中断
```
- `init` 让定时器模块可用；`adapter` 把 **timer 1** 和它的**中断号 `TIMER_1_IRQN`**、**优先级**挂上钩——这样计数器归零时中断能正确进来。
- **这两句全局只做一次**。你后面用 timer 1 时，不用再重复 init/adapter（若你要用 timer 2，则需为它 adapter 一次）。

### 步骤 1：定义句柄和周期

```c
#define SAMPLE_PERIOD_US    5000U        /* 5ms = 200Hz */
#define SAMPLE_TIMER_INDEX  1            /* 用硬件 timer 1（已 adapter） */

static timer_handle_t g_sample_timer = NULL;   // 定时器句柄(create 回填)
```

### 步骤 2：写回调函数（⚠️ 运行在中断上下文，必须极短）

```c
/*
 * 硬件 timer 回调：运行在【中断上下文】。
 * 铁律：只做最短的事，绝不能调用会阻塞的函数(如 I2C 读 MPU6050、printf 大量输出)。
 * 这里只释放一个信号量，把"该采样了"这个事件甩给任务去做。
 */
static void sample_timer_cb(uintptr_t data)
{
    (void)data;
    (void)osSemaphoreRelease(g_tick_sem);   // 只发个"节拍到"的信号
}
```

> **为什么回调里不能读 MPU6050？** 因为回调在**中断上下文**跑，`uapi_i2c_master_read` 是**阻塞调用**，在中断里阻塞会拖垮系统甚至死锁。正确姿势：**中断只发信号，重活交给任务**（下一步）。

### 步骤 3：创建 + 启动定时器

```c
// 创建：在 timer1 上生成一个逻辑定时器句柄
if (uapi_timer_create(SAMPLE_TIMER_INDEX, &g_sample_timer) != ERRCODE_SUCC) {
    osal_printk("[Sample] timer create failed\r\n");
    return false;
}
// 启动：5000us 后触发 sample_timer_cb（单次）
if (uapi_timer_start(g_sample_timer, SAMPLE_PERIOD_US, sample_timer_cb, 0) != ERRCODE_SUCC) {
    osal_printk("[Sample] timer start failed\r\n");
    return false;
}
```

### 步骤 4：让它"周期"起来（关键！one-shot → 周期）

因为 start 是单次的，要 200Hz 持续跑，必须**每响一次就重载一次**。本项目在**采样任务**里重载（不是在中断里，原因见坑点）：

```c
static void Sample_Task_Body(void *arg)
{
    (void)arg;
    while (1) {
        // 等"节拍到"信号(由中断回调释放)
        if (osSemaphoreAcquire(g_tick_sem, osWaitForever) != osOK) continue;

        // ★立刻重载定时器(尽早重载,减小周期误差) —— 这就是"变周期"的那一步
        (void)uapi_timer_start(g_sample_timer, SAMPLE_PERIOD_US, sample_timer_cb, 0);

        // 现在在【任务上下文】里，可以安心做阻塞的重活:读 IMU
        imu_sample_t sample;
        MPU6050_Read_Accel_Gyro(&sample.ax, &sample.ay, &sample.az,
                                &sample.gx, &sample.gy, &sample.gz);
        osMessageQueuePut(g_imu_queue, &sample, 0U, 0U);  // 入队给推理任务
    }
}
```

### 步骤 5：把三者拼起来（信号量 + 队列 + 任务 + 定时器）

```c
static bool sampling_pipeline_start(void)
{
    g_tick_sem  = osSemaphoreNew(TICK_SEM_MAX_COUNT, 0, NULL);   // 节拍信号量
    g_imu_queue = osMessageQueueNew(IMU_QUEUE_DEPTH, sizeof(imu_sample_t), NULL);
    if (g_tick_sem == NULL || g_imu_queue == NULL) return false;

    osThreadAttr_t attr = {0};
    attr.name = "ImuSampler";
    attr.stack_size = 1024 * 4;
    attr.priority = osPriorityAboveNormal;       // 采样任务优先级要高，别被推理阻塞
    if (osThreadNew((osThreadFunc_t)Sample_Task_Body, NULL, &attr) == NULL) return false;

    if (uapi_timer_create(SAMPLE_TIMER_INDEX, &g_sample_timer) != ERRCODE_SUCC) return false;
    if (uapi_timer_start(g_sample_timer, SAMPLE_PERIOD_US, sample_timer_cb, 0) != ERRCODE_SUCC) return false;

    osal_printk("[Sample] 200Hz hardware-timed sampling started\r\n");
    return true;
}
```

**数据流全景**：
```
硬件timer1 每5ms归零 → 中断 → sample_timer_cb 释放信号量
                                        ↓
采样任务 拿到信号 → 重载定时器 → 读MPU6050 → 入队
                                        ↓
                                推理任务 从队列取样本跑 TinyML
```

### 步骤 6：清理（需要停时）
```c
uapi_timer_stop(g_sample_timer);
uapi_timer_delete(g_sample_timer);
```

---

## 五、最小可跑 Demo（先跑通再改，从 0 验证）

想先验证"定时器能不能响"，用最简单的版本——每 1 秒打印一次（回调里只做轻量打印，仅用于验证；生产别在中断里大量 printf）：

```c
#include "timer.h"
#include "chip_core_irq.h"
#include "soc_osal.h"

static timer_handle_t g_test_timer = NULL;
static volatile uint32_t g_tick = 0;

static void test_cb(uintptr_t data)
{
    (void)data;
    g_tick++;
    uapi_timer_start(g_test_timer, 1000000, test_cb, 0);  // 重载1秒(周期)
}

void timer_hello(void)
{
    // 若 main.c 已 adapter 过 timer1，可略过下面两句；这里为独立可跑演示保留
    uapi_timer_init();
    uapi_timer_adapter(1, TIMER_1_IRQN, 1);

    uapi_timer_create(1, &g_test_timer);
    uapi_timer_start(g_test_timer, 1000000, test_cb, 0);  // 1秒后第一次触发

    while (1) {
        osal_printk("tick = %u\r\n", g_tick);  // 在任务里打印(安全)
        osal_msleep(1000);
    }
}
```
烧录后串口应每秒 `tick` 加 1 —— 说明硬件定时器跑起来了。跑通后，把周期改成 `5000`（µs）、把回调换成"释放信号量"，就过渡到 200Hz 采样版了。

---

## 六、常见坑（血泪总结）

| 坑 | 现象 | 正解 |
|---|---|---|
| **回调里干重活/阻塞** | 系统卡死、看门狗复位 | 中断回调只发信号量；重活放任务 |
| **忘了 start 是单次的** | 只响一次就没了 | 每次响完在任务里重载 `uapi_timer_start` |
| **在中断里重载 + 与其它共享 timer1** | 偶发 cycle 下溢/漏节拍 | 重载放到**任务上下文**做（本项目的写法） |
| **没 adapter 就 create/start** | 中断进不来，回调不触发 | 先 `uapi_timer_init` + `uapi_timer_adapter(index, IRQ, prio)` |
| **周期设太小** | 中断风暴，CPU 全耗在中断 | 周期别小于任务能处理的极限；本项目 5ms 已较快 |
| **time_us 超过最大值** | 启动失败 | 用 `uapi_timer_get_max_us` 查上限（约 178s@24MHz/32位计数器） |

---

## 七、动手清单（照着做一遍）

1. ☐ 确认 `main.c hw_init()` 里已有 `uapi_timer_init()` + `uapi_timer_adapter(1, TIMER_1_IRQN, ...)`。
2. ☐ 定义句柄 `static timer_handle_t g_xxx_timer;` 和周期宏。
3. ☐ 写一个**极短**的回调（只 `osSemaphoreRelease` 或置标志）。
4. ☐ `uapi_timer_create(index, &handle)`。
5. ☐ `uapi_timer_start(handle, 周期us, 回调, 0)`。
6. ☐ 想周期化 → 在任务里收到信号后**重载** `uapi_timer_start`。
7. ☐ 先用"每秒打印"最小 Demo 验证，再换成真实周期与业务。
8. ☐ 用完 `uapi_timer_stop` + `uapi_timer_delete`。

---

## 八、一句话总结

> 硬件定时器 = **24MHz 时钟驱动的自动计数器，数到设定 tick 就触发中断**；`time_us × 24 = tick`。
> 代码四步：**init/adapter（开机一次）→ create（拿句柄）→ start（单次触发）→ 在任务里重载（变周期）**。
> 铁律：**回调在中断里，只发信号；重活交任务**。本项目就靠它产生不抖动的 200Hz 采样节拍。
