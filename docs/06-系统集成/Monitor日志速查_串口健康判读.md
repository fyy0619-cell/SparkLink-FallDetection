# `[Monitor]` 日志速查 —— 串口一眼判断系统是否正常

> 服务端(板A)每 ~1 秒打印一条 `[Monitor]` 状态行。演示/调试时,对着串口看这一条就能判断系统健康。
> 对应源码：`main_task.c` 的检测循环(每帧累计统计 + 每 `MONITOR_INTERVAL`(200帧≈1s)打印一次)。

---

## 一、日志长这样

```
[Monitor] B=IDLE acc=0.94~0.95G gyr_peak=1 dps q=0/128 drops=0
```

| 字段 | 含义 | 来源 |
|---|---|---|
| `B=IDLE` | 物理状态机(路径B)当前状态 | `Fall_Algo_State_Name()` |
| `acc=0.94~0.95G` | 本秒 \|acc\| 的**最小~最大**范围 | `mon_acc_min ~ mon_acc_max` |
| `gyr_peak=1 dps` | 本秒 \|gyro\| 的**峰值** | `mon_gyr_max` |
| `q=0/128` | 消息队列**当前水位 / 深度** | `osMessageQueueGetCount` / `IMU_QUEUE_DEPTH` |
| `drops=0` | 累计**丢帧数** | `g_drop_count` |

---

## 二、正常 vs 异常判读表 ⭐

| 字段 | ✅ 正常 | ⚠️ 异常 → 说明什么 |
|---|---|---|
| `B=` | 静止/日常时**恒为 `IDLE`** | 长期卡在 `FREEFALL/IMPACT_WAIT/POST_IMPACT` → 有持续异常运动或阈值太松 |
| `acc=` | 静止≈`1.00~1.00G`;走动会变宽(如 `0.8~1.4G`) | 一直是 `0.00~0.00G` 或恒定不变 → 传感器没数据/没在采 |
| `gyr_peak=` | 静止≈`0`;动作时抬升 | 静止时也很大 → 传感器噪声大/校准问题 |
| `q=` | **`0/128`**(检测跟得上,不积压) | 持续增长(如 `40/128`↑)→ 检测/推理**追不上**采样 |
| `drops=` | **恒为 `0`** | 非 0 且增长 → **队列溢出丢帧**,系统过载 |

**一句话健康标准**:静止时看到 `B=IDLE acc≈1.00~1.00G gyr_peak≈0 q=0/128 drops=0` = 一切正常。

---

## 三、常见故障 → 看哪个字段

| 现象 | 看 | 可能原因 |
|---|---|---|
| 完全没有 `[Monitor]` 打印 | — | 采样流水线没启动 / MPU6050 没应答(看开机日志) |
| `acc` 恒 `0.00~0.00` | acc | I2C 读不到数据(接线/地址/上拉) |
| `q` 越涨越高、`drops` 开始增长 | q / drops | 推理太慢或有任务饿死;正常时 NN 那 ~100ms 积压也应被 128 深度吸收 |
| `B` 卡在非 IDLE 不回 | B | 阈值太松 / 传感器持续异常;正常事件后 1~2s 内应回 IDLE |
| 明明跌倒却没报警 | 配合 `[Fall]` 日志 | 看 `[Fall] rejected:` 说明被哪项判据否决(impact/tilt/still) |

---

## 四、这条日志是怎么统计出来的(原理)

### 每帧累计(检测循环里,每个样本都做)
```c
float acc_mag = sqrt(ax²+ay²+az²);   // 合幅值(朝向无关,一个数概括)
float gyr_mag = sqrt(gx²+gy²+gz²);
if (acc_mag < mon_acc_min) mon_acc_min = acc_mag;   // 滚动 min
if (acc_mag > mon_acc_max) mon_acc_max = acc_mag;   // 滚动 max
if (gyr_mag > mon_gyr_max) mon_gyr_max = gyr_mag;   // 滚动 peak
```

### 每 200 帧(≈1s)打印一次并重置
```c
if (++processed >= MONITOR_INTERVAL) {   // 200帧≈1s
    processed = 0;
    osal_printk("[Monitor] ...");        // 打印本秒统计
    mon_acc_min = 999.0f;                // 重置:哨兵初值,保证下一帧就替换
    mon_acc_max = 0.0f;                  // (min起大、max起小)
    mon_gyr_max = 0.0f;
}
```

**两个要点：**
- **打"范围/峰值"而非瞬时值**:200Hz 下一秒只打一行,瞬时值会漏掉转瞬即逝的尖峰;`min~max`/峰值能把这一秒里出现过的极端都记下(哪怕只持续一帧)。
- **初值 `999/0/0` + 每秒重置**:滚动 min/max 的哨兵初值(min 起大、max 起小,保证第一帧就替换掉),每秒清零 → 每条日志只反映**那一秒**。
- **`%d.%02d` 拆浮点**:嵌入式 `printf` 常不支持 `%f`,故拆成整数+两位小数打印(`0.94`→`"0.94"`)。

> 注意:这套 `mon_*` 统计**纯为监控显示,不参与跌倒判定**(检测由 `Fall_Algo_Process` 和 NN 独立完成)。是"仪表盘",不是"驾驶"。

---

## 五、一句话

> `[Monitor]` 是每 ~1 秒的系统仪表盘:`B=状态机状态 / acc=本秒范围 / gyr_peak=本秒峰值 / q=队列水位 / drops=丢帧数`。
> **正常判据**:静止时 `B=IDLE、acc≈1.00~1.00G、gyr_peak≈0、q=0/128、drops=0`。
> 统计靠**每帧滚动 min/max/peak + 每秒重置**;打范围而非瞬时值是为抓住尖峰;它是旁路监控,不参与检测。
