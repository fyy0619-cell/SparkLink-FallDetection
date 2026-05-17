# Edge Impulse 自采模型集成与 B+NN 混合判定

> 记录日期：2026-05-17 ~ 2026-05-18
> 主题：把腰部自采数据训练的 Edge Impulse 神经网络模型集成进 WS63 固件，
> 并与确定性序列检测器组成「路径 B 触发 + 神经网络复核否决」的混合判定。
> 上一版（SisFall 公开数据集模型）部署见
> [`EdgeImpulse_WS63_部署调试记录_2026-05-07.md`](EdgeImpulse_WS63_部署调试记录_2026-05-07.md)。

---

## 0. 一句话总览

这两天做的是「**把训练好的模型真正装进固件并跑起来**」。过程中遇到并解决了
6 个问题：备份目录污染编译、移植层缺口、链接符号冲突、C++ 全局构造函数不可靠、
量纲一致性、系统黑盒无可观测性。最后澄清了一个**非缺陷的现象** —— 手晃传感器
不报警是正确行为。

---

## 1. 背景：为什么要做这次集成

### 1.1 上一版模型的问题

2026-05-07 部署的模型用的是 **SisFall 公开数据集**。它能演示，但存在「**板端
数据分布不匹配**」：SisFall 用的是别的传感器、别的佩戴方式、别的采样链路，
训练分布和 WS63 + MPU6050 实采分布不一致，模型在真机上的判断并不可靠。

### 1.2 这次的改进

1. **重新采集数据**：用本工程的 WS63 + MPU6050、**腰部佩戴**、固件自带的
   `FALL_LOG_MODE` 串口 CSV 采集模式，逐样本采真机数据。
2. **重新训练**：在 Edge Impulse 训练新工程 `fall_ws63_waist`，
   二分类 `{fall, normal}`，**Raw Data + 1D 卷积网络（Conv1D）**。
3. **集成进固件**：本文档的主题。
4. **混合判定**：不让 NN 单独决策，而是和已有的确定性算法（路径 B）组合。

### 1.3 新模型的关键指标

| 指标 | 数值 | 说明 |
|------|------|------|
| 测试集准确率 | 91.67% | 数据集偏小（42 个 fall 样本） |
| 误报率（normal 被判 fall） | 0% | 特异性好 |
| 漏检率（fall 被判 normal） | 14.3% | 召回 85.7%，漏检是主要短板 |
| ROC AUC | 0.90 | — |

**结论**：模型「不误报、但会漏检」。这个特性直接决定了下面的混合判定策略 ——
**NN 只能用来否决，不能用来单独拍板**。

---

## 2. 总体架构：B+NN 混合判定

### 2.1 两条判定路径

**路径 B —— 确定性序列状态机**（`fall_algo.c`）

真实跌倒有固定的物理特征序列，按 200Hz 采样依次满足三段才算跌倒：

```
① 自由落体（失重）  →  ② 着地冲击  →  ③ 冲击后躺地静止
   |acc| 明显跌破 1G     |acc| 骤升      |acc| 回到 ~1G 且基本不动
```

- 优点：**可解释、可调、零误报倾向、不依赖数据量**。
- 缺点：阈值是按「模块跌落测试」标定的，佩戴方式变化需要现场微调；
  对不典型跌倒（缓慢滑倒等）可能漏检。

**路径 NN —— Edge Impulse 卷积网络**

- 优点：从数据里学到的特征，能识别路径 B 死板规则覆盖不到的模式。
- 缺点：14.3% 漏检、数据集小。

### 2.2 为什么是「B 触发 + NN 复核否决」

| 方案 | 问题 |
|------|------|
| 只用 NN | 14.3% 漏检 + 数据量小，单独决策风险高 |
| 只用 B | 某些剧烈动作（用力坐下、跳跃落地）可能骗过三段序列 |
| NN 触发、B 复核 | NN 漏检的那 14.3% 直接丢了，B 没机会补 |
| **B 触发、NN 复核否决** ✅ | B 负责「宁可多报不漏报」，NN 负责砍掉 B 的误报 |

最终策略（`main_task.c`）：

```
路径 B 确认跌倒  →  调用 NN 对最近 3 秒数据复核
   ├─ NN 高置信度（≥80%）判 "normal"  →  否决报警（判定为误报）
   └─ 其余情况（NN 同意 / NN 不可用 / NN 置信度不足）  →  照常报警
```

**设计原则**：阈值 `NN_VETO_NORMAL_PCT = 80` 设得高，是刻意保守 ——
宁可「漏否决」（B 误报仍发出去）也不「误否决」（把真实跌倒砍掉）。
对跌倒检测，漏报的代价远大于误报。

### 2.3 数据通路

```
硬件定时器 5ms 节拍
   → 采样任务读 MPU6050 → 入队列
   → 推理任务出队列
        ├─ EI_Fall_Push()      每个样本写入 NN 环形缓冲（始终保留最近 3s）
        ├─ Fall_Algo_Process() 路径 B 状态机
        └─ B 触发时 EI_Fall_Classify() → run_classifier → 否决/报警
```

---

## 3. 新模型的部署关键参数

来自 `model-parameters/model_metadata.h`，集成时必须逐项对齐：

| 参数 | 值 | 含义 |
|------|----|----|
| 采样率 | 200 Hz | 与固件硬件定时器节拍一致 |
| 窗口 | 600 样本 × 6 轴 = 3600 float | 3 秒窗口 |
| DSP 块 | Raw Data | 不做频域变换，原始时序直接喂网络 |
| 网络 | Conv1D（EON 编译） | EON Compiler 生成 C 代码，比解释器省内存 |
| 量化 | int8 | 权重/激活 8 位定点 |
| tensor arena | 20256 字节（静态） | 推理张量空间 |
| 类别 | `{fall, normal}` | 注意标签是 `fall` 不是旧版的 `fall_risk` |

### 量纲一致性（最容易踩的坑）

采集固件 `FALL_LOG_MODE` 输出 CSV 时，对数值做了缩放：

- 加速度：`ax * 1000`（单位 milli-g）
- 角速度：`gx * 100`（单位 centi-dps）

模型就是在这个量纲上训练的（再经 StandardScaler 归一化）。**部署推理时必须
喂入完全相同量纲的数值**，否则训练分布和推理分布不一致，模型输出全错。
`ei_fall.cpp` 里 `EI_Fall_Push()` 严格做 `×1000 / ×100` 换算。

---

## 4. 集成过程中的 6 个问题与解决

### 问题 1：备份目录污染编译

**现象**：旧的模型备份目录（如 `tflite-model.bak_xxx/`）当初被放在了固件
工程的 `src/` 目录下，里面有 `.cpp` 文件。

**根因**：固件工程的 `CMakeLists.txt` 用
`file(GLOB_RECURSE APP_SRCS "*.c" "*.cpp" "*.cc")` 递归收集源码 ——
**它会把 `src/` 下任何子目录里的 `.cpp` 都拉进编译**，包括备份目录里的旧模型。
旧模型 `.cpp` 被一起编译，既拖慢编译，又埋着符号冲突隐患。

**解决**：替换 EI 库时，把全部备份（旧 `edge-impulse-sdk/`、`model-parameters/`、
`tflite-model/`、`ai_model.cpp`，以及历史 `.bak_*` 目录）统一移到固件工程
`src/` **之外**的 `_ei_backup_<日期>/`。`GLOB_RECURSE` 只扫 `src/`，备份移出去
就不再被编译。

**经验**：用 `GLOB_RECURSE` 的工程，**任何不想编译的文件都不能留在被扫描的
目录树里**，哪怕扩展名看起来无害的子目录也会被递归命中。

---

### 问题 2：移植层缺口（porting gap）—— 最关键的发现

**背景**：Edge Impulse SDK 把一批函数（`ei_printf`、`ei_malloc`、`ei_calloc`、
`ei_free`、计时 `ei_read_timer_ms/us`、`ei_sleep`、`ei_putchar`、`DebugLog` 等）
声明为「**用户必须为目标平台实现**」。SDK 自带了一堆现成实现，放在
`edge-impulse-sdk/porting/<平台>/`（arduino、mbed、posix、zephyr…）。

**问题**：这些现成实现**每一个都被 `#if EI_PORTING_<平台> == 1` 条件包起来**。
`ei_classifier_porting.h` 靠探测编译器预定义宏来决定启用哪个平台。WS63 是
RISC-V + LiteOS，不匹配任何一个已知平台 → 理论上所有 porting 文件都编译成空 →
`ei_printf` 等符号无人提供。

旧的 `ai_model.cpp` 只补了 `ei_malloc/calloc/free`。那 `ei_printf` 当初是怎么
链接通过的？**这个疑问在问题 4 才解开**（剧透：WS63 工具链定义了 `__unix__`，
偷偷启用了 posix 移植）。

**解决**：不依赖 SDK 自带 porting 的「碰巧命中」，而是写一个专门的
**`ei_porting_ws63.cpp`**，集中、显式地提供全部移植函数：

- `ei_printf` → 经 `vsnprintf` + 固件 `printf`（输出到 UART）
- `ei_printf_float` → 手动拆整数+小数，**不用 `%f`**（WS63 的 printf 对 `%f`
  支持不稳，这是本工程一贯的约定）
- 计时 → WS63 原生 `uapi_tcxo_get_us()`（比 posix 的 `gettimeofday` 正确）
- `ei_malloc/calloc/free` → 见问题 5 的静态内存池
- `ei_sleep` → `osal_msleep`

**经验**：集成第三方 SDK 前，**先搞清它的「移植层 / 弱符号」机制** —— 哪些函数
要你实现、它默认怎么选平台、选不中会怎样。把这层自己显式接管，比依赖它的
自动探测「碰巧对」要可靠得多。

---

### 问题 3：NN 推理封装的两个细节

**封装文件 `ei_fall.cpp`**：600 样本环形缓冲；路径 B 触发时把环形缓冲按时间
顺序展开成连续的 3600-float 窗口，调用 `run_classifier`。

**细节 A —— C++ 全局构造函数在 WS63 启动不可靠**

Edge Impulse 生成的 `model_variables.h` 里有个全局对象
`ei_default_impulse`（带构造函数）。但 **WS63 的启动流程不保证执行 C++ 全局
构造函数**，直接用这个全局对象，它可能根本没被构造。

解决：不用生成的全局对象，改用 **placement new** 在一块静态存储上**显式构造**
`ei_impulse_handle_t`，并调用 `run_classifier` 的「带 handle 版本」。
模型描述符 `impulse_999999_1` 本身是 `const` 聚合体（编译期常量初始化，进
`.rodata`），不需要运行时构造，可以安全取地址使用。

**细节 B —— 推理耗时与采样节拍**

`run_classifier` 一次要上百毫秒。推理任务优先级低于采样任务，所以推理期间
采样任务照常以 200Hz 跑、把样本压进队列（深度 128 ≈ 640ms 缓冲）。推理结束后
推理任务再快速排空积压。只要推理 < 640ms，就不会丢样（`drops` 恒为 0）。

**经验**：嵌入式 C++ **别依赖全局构造函数**；需要的对象用 placement new
显式构造。耗时操作和实时节拍要用「队列 + 双任务」解耦。

---

### 问题 4：posix 链接符号冲突

**现象**：链接阶段报错

```
multiple definition of `ei_read_timer_ms()'
multiple definition of `ei_read_timer_us()'
  ... first defined here: edge-impulse-sdk/porting/posix/ei_classifier_porting.cpp
```

**根因（同时解开了问题 2 的疑问）**：WS63 的 RISC-V GCC 工具链**预定义了
`__unix__` 宏**。`ei_classifier_porting.h` 里：

```c
#if defined(__unix__) || (defined(__APPLE__) && defined(__MACH__))
#define EI_PORTING_POSIX 1
#endif
```

于是 `EI_PORTING_POSIX` 被自动置 1，**`posix/ei_classifier_porting.cpp` 实际
参与了编译**。它的 `ei_printf`、`ei_malloc` 等是 **weak 弱符号**（能被
`ai_model.cpp` 覆盖，所以旧工程没炸）；但 `ei_read_timer_ms/us` 是
**非 weak 强符号** —— 和新写的 `ei_porting_ws63.cpp` 里的同名实现硬碰硬，
链接器报重复定义。

> 这也回答了问题 2 的疑问：旧工程的 `ei_printf` 一直是 posix 移植层提供的
> （weak），并非凭空出现。

**解决**：在固件工程 `CMakeLists.txt` 的 `UNWANTED_PORTS` 排除列表里追加
`edge-impulse-sdk/porting/posix/*.cpp`，把整个 posix 移植从编译中剔除。
之后 `ei_porting_ws63.cpp` 成为**唯一**的 WS63 移植层，且计时用的是 WS63
原生的 `uapi_tcxo_get_us()`，比 posix 的 `gettimeofday`（在 WS63 上未必有
真实时基）更正确。

**经验**：**工具链的预定义宏会暗中改变第三方库的行为**。库用宏探测平台时，
要核对你的工具链到底定义了哪些宏（`__unix__`、`__MINGW32__` 等），否则会
「莫名其妙」启用了不该启用的代码路径。

---

### 问题 5：NN 的内存占用

**做法**：不走系统堆，`ei_porting_ws63.cpp` 里开一块 **64KB 静态内存池**，
用 LiteOS 的 `LOS_MemInit/Alloc/Free` 管理，`ei_malloc` 等走这块池子。

**原因**：

1. 一次性框定 NN 的 RAM 占用，不与系统其它分配相互挤占、相互碰撞。
2. 与旧 `ai_model.cpp` 的做法一致（当初用于消除 `-22` 分配失败）。

**本次新增的静态内存（约 113KB）**：

| 用途 | 大小 |
|------|------|
| EI 内存池（`ei_malloc` 用，主要是 DSP 中间矩阵） | 64 KB |
| NN 环形缓冲 `g_ring`（600×6 float） | 14.4 KB |
| 推理输入窗口 `g_window`（3600 float） | 14.4 KB |
| tensor arena（在 EON 编译的模型 `.cpp` 里，静态） | 20.25 KB |

实测开机后系统堆仍 `free` 约 130KB，链接也通过，RAM 放得下。
EI 内存池在**首次推理时惰性初始化**。

---

### 问题 6：系统是黑盒，没有可观测性

**现象**：晃动传感器没有任何报警，**也没有任何日志** —— 完全看不出板子在干什么。

**根因**：路径 B 状态机停在 `IDLE`（等待失重）时一行日志都不打。用户无从判断
「板子是不是死了 / 传感器是不是坏了 / 它到底在想什么」。

**解决**：

1. `fall_algo.c` 新增 `Fall_Algo_State_Name()`，对外暴露状态机当前状态名。
2. `main_task.c` 加每秒一次的 `[Monitor]` 状态日志：

```
[Monitor] B=IDLE acc=1.00~1.01G gyr_peak=2 dps q=0/128 drops=0
```

| 字段 | 含义 |
|------|------|
| `B=` | 路径 B 状态机状态（IDLE/FREEFALL/IMPACT_WAIT/POST_IMPACT） |
| `acc=min~max G` | 本秒内合加速度范围（静止≈1.00~1.01，运动时变宽） |
| `gyr_peak` | 本秒角速度峰值（dps） |
| `q= / drops=` | 队列水位 / 累计丢样数 |

这样晃动时能看到 `acc` 范围变宽、`gyr_peak` 抬升 —— 证明数据通路是活的；
而 `B=IDLE` 不变 —— 证明它正确判定「这不是跌倒」。

**经验**：确定性算法在「无事发生」时也要有**周期性的状态心跳日志**，否则
「没反应」和「坏了」无法区分。可观测性要在设计时就留出来。

---

## 5. 澄清：为什么「晃一晃」不报警 —— 这不是缺陷

集成后实测，**用手晃动传感器不会报警**。这是**正确行为**，原理如下。

路径 B 要求三段**严格连续**满足（阈值见 `fall_algo.c`，按 200Hz、模块跌落
测试标定）：

| 段 | 判据 | 手晃为什么不满足 |
|----|------|------------------|
| ① 失重 | `\|acc\| < 0.65G` 持续 **≥ 120ms（24 样本）** | 手甩只能制造一两个样本的瞬间低值，凑不够 120ms 连续失重 |
| ② 冲击 | `\|acc\| > 2.2G` | 这个手晃容易做到 |
| ③ 冲击后静止 | 冲击后 1.2s 内 **≥ 70%** 样本落在 0.70~1.30G | 冲击后手还在动 → 永远不静止 |

**真实跌倒一定以「躺地不动」收尾**，手里一直拿着晃，第 ③ 段永远过不了。
晃动不报警，恰恰说明检测器没有把剧烈但非跌倒的动作误判成跌倒。

**正确的触发测试方法**：

1. 手拿稳模块（`[Monitor]` 应显示 `B=IDLE acc≈1.00~1.00G`）；
2. 从约 0.5~1m 高度**松手让它自由下落**（真正撒手才有干净的持续失重段）；
3. 落到偏硬的面上；
4. **落地后不要碰它，静置至少 2 秒**。

做对了会依次出现：

```
[Fall] freefall 75 samples, waiting for impact...
[Fall] impact detected, checking stillness...
[Fall] CONFIRMED (post-impact still 88%)
[EI] NN result: fall=xx% normal=xx%
[Hybrid] B+NN agree ...
[Alert] Fall Detected...
```

若看到 `[Fall] rejected: still only 30% after impact` —— 说明前两段过了，
是落地后太快拿起来了，让它多躺一会即可。

---

## 6. 改动文件清单

| 类型 | 文件 | 说明 |
|------|------|------|
| 新增 | `inc/ei_fall.h` | NN 推理封装对外 C 接口 |
| 新增 | `src/ei_fall.cpp` | 环形缓冲 + `run_classifier` 封装 |
| 新增 | `src/ei_porting_ws63.cpp` | WS63 移植层（`ei_printf`/`ei_malloc`/计时…） |
| 修改 | `src/main_task.c` | 接入 B+NN 混合判定、状态监控、关闭 `FALL_LOG_MODE` |
| 修改 | `src/fall_algo.c` / `inc/fall_algo.h` | 新增 `Fall_Algo_State_Name()` 状态查询 |
| 修改 | `src/CMakeLists.txt` | `UNWANTED_PORTS` 追加排除 `posix/*.cpp` |
| 替换 | `edge-impulse-sdk/` `model-parameters/` `tflite-model/` | 换成新模型 `fall_ws63_waist` 的导出库 |
| 移除 | `ai_model.cpp` / `ai_model.h` | 旧 SisFall 模型封装，移入工程外备份目录 |

---

## 7. 关键经验总结

1. **`GLOB_RECURSE` 工程**：不想编译的文件不能留在被扫描的目录树里，备份要
   移出去。
2. **集成第三方 SDK**：先吃透它的移植层 / 弱符号机制，自己显式接管移植层，
   不要赌它的平台自动探测「碰巧命中」。
3. **工具链预定义宏会暗改库行为**：`__unix__` 让 EI 偷偷启用了 posix 移植，
   引发链接冲突。核对工具链的预定义宏。
4. **嵌入式 C++ 别依赖全局构造函数**：用 placement new 显式构造。
5. **量纲一致性**：训练用什么单位/缩放，部署推理就必须喂什么 —— 否则模型
   输出全错。
6. **可观测性要设计进去**：确定性算法在「无事发生」时也要有心跳日志，
   否则「没反应」和「坏了」分不清。
7. **混合判定的方向取决于各路径的错误特性**：NN「不误报但会漏检」，所以
   只能用它「否决」，不能让它「单独拍板」。

---

## 8. 后续待办

- [ ] 物理跌倒测试（真实自由落体），核对 `[Fall]` / `[EI] NN result` /
      `[Hybrid]` 日志，确认整条链路。
- [ ] 观察 `[Monitor]` 里推理期间的队列水位，确认 `drops` 恒为 0
      （推理未拖慢采样）。
- [ ] 数据集偏小（42 个 fall 样本）是当前模型精度的天花板，后续继续扩充
      自采数据、重训 v2。
- [ ] 现场微调路径 B 阈值以匹配实际腰部佩戴方式。
