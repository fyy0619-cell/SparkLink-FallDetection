# 四段物理判断机 + NN 混合判定 —— 逐行代码走读

> 目标：从"一个 IMU 样本进来"到"报警/否决"，**按代码实际执行顺序**一步步走一遍，每段贴真实代码并逐行讲。
> 涉及文件：`main_task.c`（主循环+混合判定）、`fall_algo.c`（四段物理机=路径B）、`ei_fall.cpp`（NN复核器）。

---

## 〇、总览：一条样本的执行路线

```
硬件采样(200Hz) → 队列 → Fall_Detect_Task_Body 每取一帧样本:
  ① EI_Fall_Push()      写入NN环形缓冲(始终留最近3s/600样本)
  ② Fall_Algo_Process() 四段物理状态机(路径B) → 返回是否确认
  ③ 若确认(status==1):
       EI_Fall_Classify()  对最近3s跑NN
       ├ NN高置信normal(≥95%) → 否决,不报警
       └ 否则                → sle_send_fall_alert(0x05) + 红灯 + 冷却3s
```

**涉及的函数地图：**
| 文件 | 函数 | 角色 |
|---|---|---|
| `main_task.c` | `Fall_Detect_Task_Body` | 主检测循环，编排一切 |
| `ei_fall.cpp` | `EI_Fall_Push` / `EI_Fall_Classify` | NN 环形缓冲 / 复核 |
| `fall_algo.c` | `Fall_Algo_Process` | 四段物理状态机（路径B） |

---

## 一、开机初始化（Step 0）

`Fall_Detect_Task_Body`（SERVER 分支）先做准备：
```c
EI_Fall_Init();               // 构造 NN impulse handle,清空环形缓冲
bool mpu_ok = MPU6050_Init(); // 初始化6轴传感器
ws2812b_init(); ws2812b_flash_task_start();
sle_server_task_init();       // 建SLE服务+广播(前面几篇讲过)

if (!mpu_ok) { while(1) osDelay(100); }        // 传感器没应答就别启动采样(否则饿死喂狗任务→看门狗复位)
if (!sampling_pipeline_start()) { while(1)... } // 启动200Hz采样流水线(定时器+信号量+队列+采样任务)
```
> `sampling_pipeline_start()` 就是前面《信号量与消息队列》讲的那套：硬件定时器每5ms发信号 → 采样任务读IMU → 塞进 `g_imu_queue`。

`EI_Fall_Init` 内部（`ei_fall.cpp`）：
```c
void EI_Fall_Init(void) {
    g_ring_head = 0; g_ring_count = 0;                          // 清空环形缓冲
    g_handle = (ei_impulse_handle_t*)g_handle_storage;
    new (g_handle) ei_impulse_handle_t(&impulse_999999_1);      // placement new 显式构造
    // ↑ WS63 启动不保证跑C++全局构造函数,所以手动构造,不能直接用生成的默认handle
}
```

---

## 二、主检测循环：取一帧样本（Step 1）

```c
while (1) {
    imu_sample_t sample;
    if (osMessageQueueGet(g_imu_queue, &sample, NULL, osWaitForever) != osOK) continue; // 阻塞取一帧
    ...
}
```
> 这里 `osWaitForever` 阻塞等——没样本就睡,采样任务放一帧进队列就唤醒它。检测任务优先级低于采样任务,所以采样节拍永远优先。

---

## 三、每帧先喂 NN 环形缓冲（Step 2）

```c
EI_Fall_Push(sample.ax, sample.ay, sample.az, sample.gx, sample.gy, sample.gz);
```

`EI_Fall_Push` 逐行（`ei_fall.cpp`）：
```c
void EI_Fall_Push(float ax..gz) {
    // ① 6轴 → 2个"朝向无关幅值特征"(和训练CSV量纲一致:milli-g / centi-dps)
    float acc_mag = sqrtf(ax*ax+ay*ay+az*az) * 1000.0f;   // |acc| milli-g
    float gyr_mag = sqrtf(gx*gx+gy*gy+gz*gz) * 100.0f;    // |gyro| centi-dps

    // ② 写进环形缓冲当前槽(每样本存2个float)
    float *slot = &g_ring[g_ring_head * 2];
    slot[0] = acc_mag; slot[1] = gyr_mag;

    // ③ 头指针环形前进,已写数封顶600
    g_ring_head = (g_ring_head + 1) % 600;
    if (g_ring_count < 600) g_ring_count++;
}
```
**要点：**
- 用**幅值**(而非6轴原始值)→ 模型不受传感器佩戴朝向影响(和路径B同理)。
- **环形缓冲**：`g_ring_head` 转圈写,永远保留**最近600样本(3秒)**。触发那刻缓冲里正好是"跌倒前后3秒"。
- **量纲(×1000/×100)必须和训练时一致**,否则模型失效(注释反复强调的坑)。

---

## 四、四段物理状态机：路径B（Step 3）

```c
int status = Fall_Algo_Process(sample.ax..gz);   // 返回1=确认跌倒
```

`Fall_Algo_Process`（`fall_algo.c`）是个 `switch(s_state)` 状态机，走四段：

**先算合加速度**（每段都用）：
```c
float acc = sqrtf(ax*ax + ay*ay + az*az);   // |acc|,单位 g
```

**① ST_IDLE —— 等失重 + 维护"直立方向"参考**
```c
case ST_IDLE:
    if (acc在[0.85,1.15]g) {          // 接近静止时,低通更新"直立时的重力方向"s_gref
        s_gref += 0.02*(a - s_gref);  // 供后面倾角判据用(只看前后变化,与安装方向无关)
    }
    if (acc < 0.75f) {                // ★检测到失重 → 进自由落体段
        s_state = ST_FREEFALL; s_ff_count = 1; s_ff_min = acc;
    }
    break;
```

**② ST_FREEFALL —— 失重计时 + 判断失重结束后是冲击还是等冲击**
```c
case ST_FREEFALL:
    if (acc < s_ff_min) s_ff_min = acc;      // 记失重最低点(调参用)
    if (acc < 0.75f) {                       // 还在失重
        s_ff_count++;
        if (s_ff_count > 150) reset();       // 失重>750ms → 异常,复位
    } else if (s_ff_count < 14) reset();     // 失重<70ms → 只是抖动,复位
      else if (acc > 2.20f) { ... 直接进 POST_IMPACT ... }  // 失重结束即冲击
      else { s_state = ST_IMPACT_WAIT; ... } // 失重结束但没冲击 → 等冲击
    break;
```
> ★第①段判据"自由落体"就藏在这：**必须失重14~150样本**,太短(抖动)太长(异常)都否决。

**③ ST_IMPACT_WAIT —— 限时等硬冲击**
```c
case ST_IMPACT_WAIT:
    s_wait_count++;
    if (acc > 2.20f) { s_state = ST_POST_IMPACT; s_impact_max = acc; ... } // ★冲击来了
    else if (s_wait_count > 200) reset();   // ~1s内没冲击 → 轻放/起跳,复位
    break;
```
> ★第②段判据"冲击"的触发线(2.2g);但**真正的硬冲击门槛4.0g在下面 POST_IMPACT 收尾时才判**。

**④ ST_POST_IMPACT —— 查静止 + 收尾判四项**
```c
case ST_POST_IMPACT:
    s_post_count++;
    if (acc > s_impact_max) s_impact_max = acc;      // 持续追踪冲击峰值
    if (s_post_count <= 100) break;                  // 前0.5s是翻滚/沉降期,跳过不统计

    if (acc在[0.60,1.40]g) {                          // "静止样本"
        s_still_count++;
        s_gpost += a;  s_gpost_n++;                   // 累加冲击后重力方向(求躯干朝向)
    }
    if (s_post_count >= 100+200) {                    // 观察满1s → 收尾判决
        uint32_t pct = s_still_count*100/200;         // 静止占比
        int tilt = fall_algo_tilt_deg();              // 冲击前后重力方向夹角
        int soft = (s_impact_max < 4.0f);             // 冲击是否太柔
        reset();
        if (pct < 50)      printf("rejected: 静止不足");        // ③静止判据否决
        else if (soft)     printf("rejected: soft impact");    // ②硬冲击判据否决(蹲下/坐下)
        else if (tilt<45)  printf("rejected: upright");        // ④倾角判据否决(原地起跳)
        else { printf("CONFIRMED"); return 1; }                // ★四项齐全 → 确认!
    }
    break;
```
> **四项判据在这一刻集中判决**：静止占比≥50% + 硬冲击≥4.0g + 倾角≥45°,加上前面已过的自由落体段,四项齐全才 `return 1`。任一不过 → `reset()` 回 IDLE。

**倾角怎么算的**（`fall_algo_tilt_deg`）：
```c
// 冲击后平均重力方向 p 与 直立参考 s_gref 的夹角
cosang = dot(s_gref, p) / (|s_gref| * |p|);
return acos(cosang) * 57.2958;   // 弧度转度
```
> 躺地后躯干≈水平、坐下后躯干≈直立 → 两者与"事件前直立方向"的夹角差很大,用它挡"原地起跳落地"。

---

## 五、混合判定：路径B触发后跑 NN（Step 4）

回到 `main_task.c`，`status==1` 时：
```c
} else if (status == 1) {
    ei_fall_result_t nn = EI_Fall_Classify();          // ★对最近3s跑NN(~100ms)
    if (nn.valid && nn.normal_percent >= 95) {         // NN_VETO_NORMAL_PCT
        // 否决:NN极确信是正常动作 → 不报警、不冷却(让后续真跌倒仍能触发)
        printf("[Hybrid] NN veto ... alert suppressed");
    } else {
        // NN同意 / 不可用 / 没把握 → 一律报警(保守,优先不漏报)
        sle_send_fall_alert(&alert_data, 1);           // ★发SLE通知0x05给板B
        g_ws2812b_alert_active = true;                 // 红灯
        ws2812b_alert_until = now_ms + 10000;          // 红灯持续10s
        fall_cooldown_start = now_ms;                  // 进入3s冷却
    }
}
```
> ⭐ NN 跑那 ~100ms 里,更高优先级的采样任务照样往队列塞样本,**不丢节拍**。只有 NN "≥95%确信normal"才敢否决,体现"宁误报不漏报"。

**冷却**：报警后3秒内,循环顶部这段直接跳过判定,防一次跌倒连报：
```c
if (fall_cooldown_start != 0 && (now_ms - fall_cooldown_start) < 3000) {
    ... 打印剩余冷却时间 ...
} else if (status == 1) { ... 上面的判定 ... }
```

---

## 六、NN 复核的具体实现（Step 5）

`EI_Fall_Classify`（`ei_fall.cpp`）逐行：
```c
ei_fall_result_t EI_Fall_Classify(void) {
    if (g_ring_count < 600) return {false,..};   // 样本不足3s → 不可用(valid=false)

    // ① 环形缓冲展开成"时间有序"的连续窗口(run_classifier要连续数组)
    //    缓冲满时 head 正指向最旧样本,分两段拷贝:[head,末尾) 接 [0,head)
    uint32_t head = g_ring_head;
    memcpy(g_window, &g_ring[head*2], (600-head)*2*sizeof(float));       // 旧段
    if (head) memcpy(&g_window[(600-head)*2], g_ring, head*2*sizeof(float)); // 新段

    // ② 包成EI的signal,跑分类器
    signal_t signal;
    numpy::signal_from_buffer(g_window, 1200, &signal);
    ei_impulse_result_t result = {0};
    run_classifier(g_handle, &signal, &result, false);   // ★神经网络推理在这

    // ③ 从结果里取出 fall / normal 两个类别的置信度
    for (类别 i) {
        if (label=="fall")   fall_prob   = result.classification[i].value;
        if (label=="normal") normal_prob = result.classification[i].value;
    }
    out.valid = true;
    out.fall_percent   = fall_prob*100;
    out.normal_percent = normal_prob*100;
    return out;
}
```
**要点：**
- **环形→连续**：环形缓冲物理上不连续(head处断开),`run_classifier` 要连续窗口,所以分两段 memcpy 拼成时间有序的 `g_window`。
- **只在样本满600才跑**,否则 `valid=false`(主循环据此走"NN不可用→信路径B")。
- `run_classifier` 就是 Edge Impulse 生成的推理入口,内部做 DSP 特征提取 + INT8 神经网络前向。

---

## 七、状态监控（旁路）

主循环每 200 帧(≈1s)打印一次,不影响判定：
```c
if (++processed >= 200) {
    printf("[Monitor] B=%s acc=..~..G gyr_peak=.. q=../128 drops=..",
        Fall_Algo_State_Name(), ...);   // 当前B状态机状态+本秒范围+队列水位+丢帧
}
```
> 静止时应恒为 `B=IDLE`；串口看到它一直 IDLE 就说明没有误触发。

---

## 八、完整调用序列（把函数串起来）

```
[开机] Fall_Detect_Task_Body:
   EI_Fall_Init → MPU6050_Init → sle_server_task_init → sampling_pipeline_start

[每帧循环] while(1):
   osMessageQueueGet(取样本)
   → EI_Fall_Push(存NN环形缓冲)
   → Fall_Algo_Process(四段状态机)  ── return 0 ──▶ 继续下一帧
        │ return 1(四项齐全)
        ▼
   EI_Fall_Classify(NN跑最近3s)
        ├ normal≥95% ─▶ 否决(不报警)
        └ 否则 ─▶ sle_send_fall_alert(0x05) + 红灯10s + 冷却3s
   → (每200帧) [Monitor] 打印状态
```

## 九、一句话

> 检测任务每取一帧样本，**先 `EI_Fall_Push` 存进NN 3秒环形缓冲，再 `Fall_Algo_Process` 走四段物理状态机(失重→硬冲击→冲击后静止→倾角)**；四项齐全 `return 1` 后，才 `EI_Fall_Classify` 跑一次NN复核——**NN≥95%确信normal才否决，否则 `sle_send_fall_alert(0x05)` 报警并进3秒冷却**。路径B在 `fall_algo.c`、NN复核在 `ei_fall.cpp`、编排在 `main_task.c`。
