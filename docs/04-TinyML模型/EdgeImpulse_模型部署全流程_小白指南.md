# Edge Impulse 模型部署全流程（小白指南）

> 本文回答 6 个问题，逐节展开：
> 1. **AI 模型在我这个项目里扮演什么角色？**（不是主判，是复核器）
> 2. **它是怎么"塞进"WS63 单片机的？**（代码文件清单 + 编译链路）
> 3. **模型到底多大？**（字节级账本：纯权重 628 字节）
> 4. **INT8 量化和模型裁剪到底是什么？**（公式 + 你工程里的真实参数）
> 5. **运行时占多少内存？**（每一块 RAM 都拆开算）
> 6. **推理延迟多少？瓶颈在哪？怎么继续优化？**
>
> 最后一节给"重新训练后怎么更新"的操作清单。

---

## 0. 几个前置直觉

```text
                Edge Impulse 网站                          WS63 开发板
   ┌───────────────────────────────────┐      ┌──────────────────────────────────┐
   │  采集数据 → 设计 Impulse → 训练     │      │  MPU6050 → 路径 B 状态机(主判)    │
   │  导出 INT8 量化 C++ library        │ ───▶ │   → NN 复核(本文档主角)           │
   └───────────────────────────────────┘  拷贝  └──────────────────────────────────┘
            （浏览器里完成）                文件     （单片机里实时运行 + 报警）
```

| 名词 | 大白话解释 |
| --- | --- |
| **Edge Impulse（EI）** | 在线 TinyML 平台。喂数据、点鼠标，导出 C++ 库。 |
| **Impulse** | EI 专有名词：原始数据 → DSP 特征提取 → 神经网络 → 分类结果 这一整条流水线。 |
| **DSP（Flatten）** | 你这个模型用的预处理：把 600 样本 × 2 通道 = 1200 个浮点数，压缩成 **14 个统计量**（均值/最值/RMS/标准差/偏度/峰度 等 × 2 通道）。**不是 FFT**。 |
| **TFLite Micro** | 谷歌为单片机做的小型 AI 推理引擎。 |
| **EON Compiler** | EI 的优化器，把神经网络"编译成 C++ 代码"而不是模型文件，省去 flatbuffers 解析。 |
| **INT8 量化** | 把模型里 float32 权重压成 int8 + 一个 scale。**你这个模型已经量化**（与旧版 float32 不同）。详见第 4 节。 |

---

## 1. 角色：AI 不是主判，是"复核器"

这是理解整个项目最关键的一点。

你的项目里 **同时跑两套跌倒判定**，结果做"与"：

```text
                  MPU6050 @200Hz (5ms 节拍)
                          │
                          ▼
   ┌──────────────────────┴──────────────────────┐
   │                                              │
   ▼                                              ▼
┌─────────────────────┐                ┌──────────────────────┐
│ 路径 B (主判)       │                │ NN (复核)            │
│ fall_algo.c         │                │ ei_fall.cpp          │
│                     │                │                      │
│ 确定性状态机:        │                │ Edge Impulse 模型:    │
│   失重 → 冲击        │   ──触发──▶    │   14→20→10→2 全连接   │
│   → 静止 → 倾角      │                │   INT8 量化           │
│                     │                │   3 秒窗口            │
└─────────┬───────────┘                └──────────┬───────────┘
          │ status=1 (序列齐全)                  │ fall%/normal%
          │                                       │
          └──────────────┬────────────────────────┘
                          ▼
              ┌───────────────────────────┐
              │ 仲裁(main_task.c):        │
              │  默认信路径 B,           │
              │  仅当 NN 高置信度(>=95%)│
              │  判 normal 才否决报警   │
              └───────────┬───────────────┘
                          ▼
                  星闪/BLE 发 0x05 报警
```

**为什么这样设计？**

| 角色 | 优点 | 弱点 |
| --- | --- | --- |
| 路径 B（确定性状态机） | 物理可解释、调参直观、零数据也能跑、对真实硬摔灵敏 | 偶尔会被"快速躺下+静止"骗（误报） |
| NN（神经网络） | 见过类似动作就能区分 | 训练数据有限，单独信它会漏报 |
| **B + NN 混合** | B 保证不漏报、NN 帮忙挡误报 | 整体比"只用 NN"安全得多 |

具体仲裁规则（`main_task.c:245-272`）：

```c
} else if (status == 1) {                          // 路径 B 触发了
    ei_fall_result_t nn = EI_Fall_Classify();      // 让 NN 看看最近 3 秒
    if (nn.valid && nn.normal_percent >= 95) {     // NN 95%+ 确信是 normal
        // 否决报警
    } else {
        // 报警(包括 NN 同意、NN 不可用、NN 置信度不足)
    }
}
```

阈值 `NN_VETO_NORMAL_PCT = 95` 不是拍脑袋：板上实测**真摔 NN 输出 fall=100%/normal=0%**，偏软的摔约 50/50。设 95 既不会误否决真摔，又能在路径 B 偶尔误触发时挡掉。

> 这种"确定性主判 + ML 复核"是工业 TinyML 系统的常见模式：让 ML 干它最擅长的事（处理"我说不清但你看着像")，不让它干它不擅长的事（保证不漏报、对从未见过的动作鲁棒）。

---

## 2. 它是怎么"塞进" WS63 的？—— 代码文件清单

打开 `application/samples/my_demo/fall_detect/`，按"谁是谁"分三类：

```text
fall_detect/
├── inc/
│   ├── ei_fall.h          ← 自写：NN 模块的 C 接口
│   ├── fall_algo.h        ← 自写：路径 B 状态机接口
│   ├── mpu6050.h          ← 自写：传感器驱动接口
│   └── ...
└── src/
    ├── edge-impulse-sdk/  ← EI 自动生成（运行引擎，几百个文件，别动）
    ├── model-parameters/  ← EI 自动生成（模型参数）
    │   ├── model_metadata.h        ← 一堆宏：窗口大小、量化标志、arena 大小
    │   └── model_variables.h       ← 关键结构体 impulse_999999_1（"装配图"）
    ├── tflite-model/      ← EI 自动生成（编译后的神经网络）
    │   ├── tflite_learn_999999_3_compiled.cpp  ← 28 KB，权重 + EON 编译图
    │   ├── tflite_learn_999999_3_compiled.h
    │   └── trained_model_ops_define.h
    │
    ├── ei_fall.cpp        ← 自写：NN 推理封装（环形缓冲 + run_classifier 调用）
    ├── ei_porting_ws63.cpp← 自写：把 EI SDK 适配到 WS63 RISC-V/LiteOS
    ├── fall_algo.c        ← 自写：路径 B 确定性状态机（主判）
    ├── mpu6050.c          ← 自写：I2C 驱动
    ├── main_task.c        ← 自写：采样/推理双任务 + 仲裁 + 报警
    ├── sle_server_task.c  ← 自写：星闪 SLE 报警链路
    ├── ws2812b.c          ← 自写：报警灯带
    └── CMakeLists.txt     ← 把上面所有东西串起来编译
```

### 三类文件分别在做什么

**第一类：EI 自动生成的"素材"**（你不要手改）

| 目录/文件 | 内容 | 关键点 |
| --- | --- | --- |
| `edge-impulse-sdk/` | EI 的运行引擎：分类器框架、DSP 算子、裁剪版 TensorFlow Lite Micro、各平台 porting 桩 | 几百个 .cpp，CMake 里要剔掉用不上的平台 porting |
| `model-parameters/model_metadata.h` | 模型的"身份证"：项目 ID、窗口大小、量化是否启用、arena 大小 | 第 3 节会逐行解读 |
| `model-parameters/model_variables.h` | 全局变量 `impulse_999999_1`，把 DSP/NN/后处理拼装起来 | `EI_Fall_Init()` 里用 `placement new` 显式构造 |
| `tflite-model/tflite_learn_999999_3_compiled.cpp` | **神经网络本体**：INT8 权重数组 + EON 编译出来的计算图 | 28 KB 文件，但**纯权重只有 628 字节**，详见第 5 节 |

**第二类：你自己写的 4 个 C/C++ 文件**（部署的真正工作量）

| 文件 | 角色 | 大小 |
| --- | --- | --- |
| `ei_fall.cpp` | NN 推理封装：环形缓冲 + 单位换算 + `run_classifier()` 调用 + 结果解析 | 5 KB |
| `ei_porting_ws63.cpp` | 平台 porting：`ei_malloc/free/printf/timer`，并维护 64 KB 静态内存池 | 4 KB |
| `fall_algo.c` | 路径 B 主判状态机（IDLE→FREEFALL→IMPACT_WAIT→POST_IMPACT） | 11 KB |
| `main_task.c` | 200Hz 硬件定时采样 + 推理任务 + B/NN 仲裁 + 星闪报警 | 13 KB |

**第三类：编译胶水**

| 文件 | 作用 |
| --- | --- |
| `CMakeLists.txt` | 收集源码、剔掉用不上的 EI porting（arduino/stm32/...）、强制 C++14 -fno-exceptions -fno-rtti、塞 `EI_CLASSIFIER_ALLOCATION_STATIC=1` 等宏 |
| `Kconfig` | 在 `menuconfig` 图形菜单里挂"是否启用跌倒检测"开关 |

### CMakeLists 的几个关键魔法

`fall_detect/src/CMakeLists.txt` 里 5 件事：

1. **递归收源码** `file(GLOB_RECURSE APP_SRCS "*.c" "*.cpp" "*.cc")`，把 EI SDK 里所有 cpp 都吞进来。
2. **剔除不用的平台 porting**：EI SDK 自带 arduino / mbed / stm32 / silabs / ti 等十几个平台适配，WS63 用不上。CMake 里 `REMOVE_ITEM` 删掉，**只留 `ei_porting_ws63.cpp`**（注意：连 `posix` 也删了，因为 WS63 的 RISC-V 工具链定义了 `__unix__` 会自动启用 POSIX porting，与 `ei_porting_ws63.cpp` 的 `ei_read_timer_*` 重名冲突）。
3. **切到 C++14、关异常**：EI SDK 是 C++ 写的，WS63 默认 `gnu99`。CMake 里把 `-std=gnu99` 换成 `-std=c++14`，并加 `-fno-exceptions -fno-rtti -Wno-narrowing`。
4. **加宏定义**强制 EI 走静态内存、关掉 ARM 专属加速库：
   ```cmake
   add_compile_definitions(
       EI_CLASSIFIER_ALLOCATION_STATIC=1     # 走静态内存池，不用 malloc
       EI_CLASSIFIER_TFLITE_ENABLE_CMSIS_NN=0 # CMSIS 是 ARM 的，RISC-V 用不了
       EIDSP_USE_CMSIS_DSP=0)                 # 同上
   ```
5. **加头文件路径**：`model-parameters/` 和 `tflite-model/` 进 `PUBLIC_HEADER`，否则 `#include` 找不到。

---

## 3. 模型参数账本

`model-parameters/model_metadata.h` 是模型的"出厂铭牌"。挑关键宏列出来：

| 宏 | 值 | 含义 |
| --- | --- | --- |
| `EI_CLASSIFIER_PROJECT_ID` | `999999` | EI 项目编号（旧版是 985336，已替换） |
| `EI_CLASSIFIER_PROJECT_NAME` | `"fall_ws63_waist"` | 项目名：腰部佩戴版本 |
| `EI_CLASSIFIER_SENSOR` | `SENSOR_FUSION` | 传感器融合（不是单 IMU） |
| `EI_CLASSIFIER_FUSION_AXES_STRING` | `"Unnamed 1 + Unnamed 2"` | **2 个通道**：`|acc|` 幅值（milli-g）+ `|gyro|` 幅值（centi-dps） |
| `EI_CLASSIFIER_RAW_SAMPLE_COUNT` | `600` | 一个窗口 600 个采样点 |
| `EI_CLASSIFIER_RAW_SAMPLES_PER_FRAME` | `2` | 每帧 2 个数（两个幅值） |
| `EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE` | `1200` | 窗口总数据量 = 600 × 2 |
| `EI_CLASSIFIER_FREQUENCY` | `200` | 200 Hz 采样 |
| `EI_CLASSIFIER_INTERVAL_MS` | `5` | 每 5 ms 一帧 |
| **窗口时长** | **3 秒** | 600 / 200Hz |
| `EI_CLASSIFIER_NN_INPUT_FRAME_SIZE` | `14` | DSP 之后只剩 14 个数喂给 NN |
| `EI_CLASSIFIER_LABEL_COUNT` | `2` | 类别数 |
| 类别名 | `fall` / `normal` | 注意：旧版叫 `fall_risk/normal`，已改名 |
| `EI_CLASSIFIER_INFERENCING_ENGINE` | `TFLITE` | TFLite Micro |
| `EI_CLASSIFIER_COMPILED` | `1` | 走 EON Compiler |
| **`EI_CLASSIFIER_QUANTIZATION_ENABLED`** | **`1`** | **已量化为 INT8**（旧版是 0） |
| `EI_CLASSIFIER_TFLITE_INPUT_DATATYPE` | `INT8` | NN 输入：INT8 |
| `EI_CLASSIFIER_TFLITE_OUTPUT_DATATYPE` | `INT8` | NN 输出：INT8 |
| `EI_CLASSIFIER_TFLITE_LARGEST_ARENA_SIZE` | `2944` | EI 标注的 arena 上界（实际 EON 编译后只用 **368 字节**，见第 5 节） |
| `EI_STUDIO_VERSION` | `1.93.3` | EI Studio 版本 |

### 模型在做的事，一句话

> 「每 5 ms 接收一个 6 轴 IMU 样本（加速度 g、角速度 dps），换算成 `|acc|` 和 `|gyro|` 两个幅值（朝向无关），攒满 600 个（=3 秒）后，过一道 Flatten DSP 压成 14 个统计特征，喂给 14→20→10→2 的 INT8 全连接网络，输出 `fall` / `normal` 两个概率。」

### 为什么换成"朝向无关"幅值？

旧模型用 6 轴原始值，结果只要传感器戴歪一点就掉精度。换成 `|acc| = √(ax²+ay²+az²)` 和 `|gyro| = √(gx²+gy²+gz²)`，模型看到的世界与传感器朝向解耦，腰间挂得正不正都不影响。代价是丢了方向信息，但跌倒"失重 → 冲击 → 静止"的能量轮廓本来就和方向无关。

代码在 `ei_fall.cpp:66-83`：

```cpp
float acc_mag = sqrtf(ax*ax + ay*ay + az*az) * 1000.0f;   // 单位 milli-g
float gyr_mag = sqrtf(gx*gx + gy*gy + gz*gz) * 100.0f;    // 单位 centi-dps
slot[0] = acc_mag;
slot[1] = gyr_mag;
```

> 量纲要和训练 CSV（`make_features.py` 生成）严格一致，否则"训练/部署量纲不一致"立刻让模型崩。

---

## 4. INT8 量化和模型裁剪

### 4.1 量化是什么

训练时模型用 32 位浮点数（float32）。部署到单片机时把它们压成 8 位整数（int8）。压缩比 **4× 内存 + 大概 3~4× 速度**，代价是几个百分点的精度。

**仿射量化公式（对称/非对称）**：

```
q = round(r / scale) + zero_point
r = (q - zero_point) × scale
```

- `r`：真实浮点数
- `q`：量化后整数（INT8 范围 -128~127）
- `scale`：缩放因子（float）
- `zero_point`：零点偏移（int8，对称量化时为 0）

EI 用的是 **per-tensor affine quantization**：每个张量（权重/激活）独立一组 scale + zero_point。

### 4.2 你模型里的真实量化参数

打开 `tflite_learn_999999_3_compiled.cpp:158-232`，每层的 `quant*_scale / quant*_zero` 都写死了：

| 张量 | 类型 | shape | scale | zero_point | 说明 |
| --- | --- | --- | --- | --- | --- |
| 输入 (NN input) | int8 | (1, 14) | 816.97 | -128 | DSP 输出的 14 个特征，**scale 很大**（特征值大，能到 1000+） |
| W0 权重 | int8 | (20, 14) | 0.00347 | 0 | 输入层权重 |
| B0 bias | int32 | (20,) | 2.836 | 0 | bias 用 int32 防溢出，scale = 输入 scale × W0 scale |
| 中间激活 | int8 | (1, 20) | 334.03 | -128 | FC0+ReLU 输出 |
| W1 权重 | int8 | (10, 20) | 0.00370 | 0 | 隐藏层权重 |
| B1 bias | int32 | (10,) | 1.236 | 0 | |
| 中间激活 | int8 | (1, 10) | 168.12 | -128 | FC1+ReLU 输出 |
| W2 权重 | int8 | (2, 10) | 0.00533 | 0 | 输出层权重 |
| B2 bias | int32 | (2,) | 0.896 | 0 | |
| Softmax 前激活 | int8 | (1, 2) | 66.08 | 127 | |
| **Softmax 输出** | **int8** | **(1, 2)** | **0.00390625** | **-128** | **标准 INT8 softmax 输出，0.00390625 = 1/256** |

读 `result.classification[i].value` 时（`ei_fall.cpp:128-137`），SDK 已经做完反量化，给的是 0.0~1.0 的浮点概率。

### 4.3 模型裁剪（架构裁剪）

「裁剪」可以是两件事：
- **结构裁剪**：网络层数/神经元减少
- **稀疏化**（pruning）：把小权重置 0

你这个模型走的是**极致结构裁剪**。看 `tflite_learn_999999_3_compiled.cpp:233-244`：

```text
┌────────────┐     FullyConnected + ReLU      ┌────────────┐
│ INT8 [1,14]├──────────────────────────────▶ │ INT8 [1,20]│
└────────────┘  W0(20×14)+b0(20)              └────────────┘
                                                     │
                                                     ▼  FullyConnected + ReLU
┌────────────┐                                ┌────────────┐
│ INT8 [1,10]│◀──── W1(10×20)+b1(10) ────────│ INT8 [1,20]│
└────────────┘                                └────────────┘
        │
        ▼  FullyConnected (no activation)
┌────────────┐                                ┌────────────┐
│ INT8 [1,2] ├───────── Softmax ────────────▶│ INT8 [1,2] │
└────────────┘                                └────────────┘
   logits                                       概率 (×1/256)
```

总参数数：

| 层 | 权重 | bias | 小计 |
| --- | --- | --- | --- |
| FC0 | 14×20 = 280 | 20 | 300 |
| FC1 | 20×10 = 200 | 10 | 210 |
| FC2 | 10×2 = 20 | 2 | 22 |
| **总参数** | | | **532 个数** |

INT8 权重 + INT32 bias 的字节占用：

| 张量 | 字节 |
| --- | --- |
| W0 (20×14 int8) | 280 |
| B0 (20 int32) | 80 |
| W1 (10×20 int8) | 200 |
| B1 (10 int32) | 40 |
| W2 (2×10 int8) | 20 |
| B2 (2 int32) | 8 |
| **纯参数总量** | **628 字节** |

**也就是你这个模型的"骨头"只有 0.6 KB**。

### 4.4 那 28 KB 的 .cpp 文件里装了什么？

`tflite_learn_999999_3_compiled.cpp` 文件大小 28705 字节。但纯权重才 628 字节，其余 ~28 KB 是：

| 内容 | 估算 | 说明 |
| --- | --- | --- |
| EON Compiler 生成的接入代码 | ~15 KB | `tflite_learn_999999_3_init/invoke/input/output/reset` 等函数体，把 4 个算子手工拼成一个计算图 |
| Tensor 元数据 + Quantization 参数 struct | ~5 KB | 每张量一组 `TfArray<scale>`、`TfArray<zero_point>`、`TfLiteAffineQuantization`、`tensor_dimension*` |
| Op resolver 和 registrations | ~3 KB | 把 `FullyConnected`、`Softmax` 算子注册进 TFLite Micro |
| 注释 + 头文件 + 代码缩进格式 | ~5 KB | C++ 源码的"白纸"开销 |

**核心认识**：模型本身（权重 + 结构）极小，**编译后的 .cpp 文件 ≠ 模型大小**。真正烧进 Flash 的、和"模型"对应的，是这 628 字节的常量数组 + 几 KB 的计算图代码。

> 旧版（float32 + 旧架构）这个 cpp 文件 373 KB，新版（INT8 + 14→20→10→2）只有 28 KB。**13× 缩小**主要来自架构裁剪（旧模型 NN 输入 222 维，新模型只有 14 维），其次才是 INT8 量化的 4× 收益。

---

## 5. 内存账本 —— 每一块 RAM 都拆开算

这是用户最关心的问题之一。把整个跌倒检测系统占的 RAM 拆开看：

### 5.1 编译时分配（.data / .bss）

| 区块 | 位置 | 大小 | 来源 |
| --- | --- | --- | --- |
| EI 静态内存池 `g_ei_heap` | `.bss` (RAM) | **64 KB** | `ei_porting_ws63.cpp:30` |
| NN 环形缓冲 `g_ring` | `.bss` (RAM) | **4800 B** | `ei_fall.cpp:41` (1200 floats) |
| NN 推理窗口 `g_window` | `.bss` (RAM) | **4800 B** | `ei_fall.cpp:46` (1200 floats) |
| impulse handle 占位 `g_handle_storage` | `.bss` | ~32 B | `ei_fall.cpp:50` |
| **模型权重（const）** | **`.rodata` (Flash)** | **628 B** | `tflite_learn_..._compiled.cpp` |
| Tensor 元数据 / quant scale / op registrations | `.rodata` (Flash) | ~10 KB | 同上 |
| **小计（RAM）** | | **~73.7 KB** | |
| **小计（Flash）** | | **~11 KB** | |

### 5.2 运行时动态分配（在 `g_ei_heap` 这 64 KB 池子内）

`run_classifier()` 跑起来后，`ei_malloc` 会临时申请几块：

| 临时块 | 估算大小 | 用途 |
| --- | --- | --- |
| **tensor_arena** | **368 B** | 4 个算子的输入/输出/中间激活，复用 |
| Flatten DSP 矩阵 | ~14 KB | 把 (600,2) reshape 成 (2,600) 计算 7 个统计量 |
| scratch buffer 上限 | ~几 KB | TFLite Micro 算子内部 scratch |
| 对齐 + 池子碎片余量 | ~46 KB | 64 KB - 上面已用 ≈ 留作缓冲 |

> **关键发现**：`model_metadata.h` 里 `EI_CLASSIFIER_TFLITE_LARGEST_ARENA_SIZE = 2944` 是 EI 给的"保守上界"。但看 `tflite_learn_999999_3_compiled.cpp:99`：
> ```cpp
> constexpr int kTensorArenaSize = 368;
> ```
> EON Compiler 编译后**实际只用 368 字节** arena！因为 EON 已经预先做了张量内存复用（看那些 `tensor_arena + 0/16/32` 偏移就是手工排好的）。

### 5.3 任务栈

| 任务 | 栈大小 | 来源 | 优先级 |
| --- | --- | --- | --- |
| `FallTask`（仲裁 + 推理 + 报警） | **32 KB** | `main_task.c:326` | Normal |
| `ImuSampler`（5 ms 节拍读 I2C） | **4 KB** | `main_task.c:57` | AboveNormal |
| **栈小计** | **36 KB** | | |

### 5.4 进程间通信

| 对象 | 大小 |
| --- | --- |
| `g_imu_queue`（IMU 样本队列）= 128 × `sizeof(imu_sample_t)`(24B) | **3 KB** |
| `g_tick_sem`（节拍信号量） | <100 B |

### 5.5 总账

```text
┌────────────────────────────────────────────────────────────┐
│  WS63 上跌倒检测的 RAM 占用                                │
├────────────────────────────────────────────────────────────┤
│  EI 内存池 g_ei_heap                          64 KB        │
│    └─ run_classifier 时分到:                              │
│         tensor_arena                  368 B               │
│         DSP Flatten 临时矩阵         ~14 KB              │
│         其余对齐 + 碎片余量          ~50 KB              │
│                                                            │
│  NN 环形缓冲 g_ring (1200 floats)              4.7 KB     │
│  NN 推理窗口 g_window (1200 floats)            4.7 KB     │
│                                                            │
│  FallTask 栈                                   32 KB      │
│  ImuSampler 栈                                  4 KB      │
│                                                            │
│  IMU 样本队列                                    3 KB     │
│  其它（信号量/句柄）                            <1 KB     │
├────────────────────────────────────────────────────────────┤
│  小计 RAM                                    ~113 KB      │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  Flash 占用（模型相关，不含 EI SDK 引擎）                  │
├────────────────────────────────────────────────────────────┤
│  纯权重 + bias                              628 B         │
│  Tensor 元数据 / quant scale / EON 计算图   ~10 KB        │
│  自写 C/C++ 代码（ei_fall + porting + algo  ~33 KB        │
│       + main_task + mpu6050 + sle/ws2812）                │
│  EI SDK 库代码（裁剪后）                     几百 KB      │
└────────────────────────────────────────────────────────────┘
```

> WS63 总 SRAM 是 384 KB。AI 相关占 113 KB ≈ 30%，留给 LiteOS 内核 + 星闪协议栈 + 其它任务还有充足空间。

### 5.6 如果想再压 RAM

**最大的可压目标是 `g_ei_heap = 64 KB`**。实测最大单次需求是 DSP 临时矩阵 ~14 KB + 抗碎片余量。可以压到 **24~32 KB**。压的方法：

```cpp
// ei_porting_ws63.cpp:26
#define EI_WS63_HEAP_SIZE   (32 * 1024)   // 从 64 KB 压到 32 KB
```

风险：DSP 算子内部可能在不同帧分配大小不同，压得太狠会 OOM。串口日志里盯 `[EI] OOM: request N bytes`，如果出现就调回去。

---

## 6. 推理延迟与瓶颈

### 6.1 系统两个时间尺度

```text
连续每 5 ms 一次:        采样 → 路径 B 状态机一步 → 状态监控统计
不连续, 触发时一次:      run_classifier()  (DSP + NN + 后处理)
                         |
                         └─ 路径 B 完成"失重-冲击-静止"序列才触发
                            ⇒ 一次跌倒生命周期内只跑 1 次
```

### 6.2 一次 `run_classifier()` 估算耗时

| 阶段 | 计算量 | 估算 |
| --- | --- | --- |
| DSP Flatten | 遍历 1200 floats × 计算 7 个统计量（mean/min/max/RMS/stdev/skew/kurt）× 2 通道 = 14 次 reduce | **5~15 ms** （含 sqrt/pow） |
| NN 推理 | INT8 MAC = 14×20 + 20×10 + 10×2 = **500 次乘加** + ReLU + Softmax | **<1 ms** |
| 拼装 result 结构 + ei_printf | 拷贝 + 反量化 + 串口打印 | <1 ms |
| **单次推理总耗时** | | **~10 ms 量级** |

> NN 部分极便宜，500 次 INT8 MAC 在 RISC-V @160MHz 上算下来几十微秒级。**瓶颈 100% 在 DSP**。

### 6.3 真正的瓶颈在哪？

按"系统总采样节拍"看：

| 候选瓶颈 | 实测/估算开销 | 是否瓶颈 |
| --- | --- | --- |
| MPU6050 I2C 读 14 字节 @400kHz | ~700 µs | ⭐ 占 5ms 周期的 14% |
| 路径 B 状态机一帧 | <100 µs | 否 |
| `run_classifier` 推理 | 10~20 ms（一次跌倒触发一次） | ⭐ 触发时 |
| 串口打印 `[Monitor]` | 一次 1~2 ms（每秒一次） | 否 |
| 系统调度抖动 | 几十 µs | 否 |

**关键设计：推理被故意做成"事件触发"**——只在路径 B 状态机走完"失重 → 冲击 → 静止"序列才跑一次。这样即使单次推理要 15 ms，也不会拖慢每 5 ms 的采样节拍。

推理期间采样怎么办？看 `main_task.c:74-109`：
- 采样任务（高优先级 `AboveNormal`）继续被 5 ms 硬件 timer 唤醒，读 I2C，把样本压入 128 深度的 `g_imu_queue`。
- 推理任务（`Normal` 优先级）正在跑 `run_classifier`，从队列里慢慢吃。
- 15 ms 推理期间 ≈ 3 个采样积压，128 深度的队列绰绰有余。
- 实测 `g_drop_count` 恒为 0（永不丢样本）。

### 6.4 优化路线（按 ROI 排序）

| 优化点 | 收益 | 难度 | 建议 |
| --- | --- | --- | --- |
| **量化已开 INT8** | 4× 内存 + 3~4× 速度 | ✅ 已完成 | — |
| **结构已极致裁剪** 14→20→10→2 | 模型从几十 KB 缩到 0.6 KB | ✅ 已完成 | 再裁意义不大 |
| **EON Compiler** | 省去 flatbuffers 解析、tensor_arena 自动复用到 368 B | ✅ 已启用 | — |
| `g_ei_heap` 64KB → 32KB | 省 32 KB RAM | 🟢 简单 | 改一行宏，串口盯 OOM |
| Flatten DSP 改手写 Welford 单遍统计 | DSP 5~15 ms → 2~3 ms | 🟡 中等 | 一次遍历同时算 mean/var/min/max/skew/kurt |
| 推理优先级降低、不阻塞采样 | 已经做了 | ✅ 已完成 | — |
| 用更高量化（INT4 / 二值化） | 更省 | 🔴 难 | 当前模型已经够小，不必 |
| 训练数据扩充 / 模型重训 | 提升 NN 真正区分能力 | 🟡 中等 | **当前 ROI 最高的方向**：模型小不是问题，"会不会判"才是 |
| 加 CMSIS-NN 加速 | 3~10× NN 加速 | 🔴 不适用 | CMSIS 是 ARM 的，WS63 是 RISC-V，不能直接用 |
| 换 NPU 平台 | 100× NN 加速 | 🔴 换板 | WS63 没 NPU；如果未来上 BES 系列或带 NPU 的 SoC 再说 |

> **结论**：从计算角度，这套系统已经在 WS63 这级 MCU 上做到接近极致的工程化。后续投入应该转向**数据**（采更多真摔/疑似动作样本，重训 NN），而不是继续抠 ML 流水线的字节和毫秒。

---

## 7. 一帧数据的完整旅程（端到端）

把前 6 节串起来，跟踪一帧 IMU 数据：

```text
① MPU6050 内部 1kHz / DLPF44Hz / ±16g / ±2000dps
        │  WS63 硬件 timer 1 每 5 ms 中断 → sample_timer_cb → 释放 g_tick_sem
        ▼
② ImuSampler 任务（AboveNormal 优先级）
   I2C 读 0x3B 起 14 字节 → 换算物理单位（g, dps）→ 入 g_imu_queue
        │  (~700 µs)
        ▼
③ FallTask 主循环（Normal 优先级）从队列拿到样本
        │
        ├─▶ EI_Fall_Push():  acc_mag = √(ax²+ay²+az²)·1000  → g_ring[head][0]
        │                    gyr_mag = √(gx²+gy²+gz²)·100   → g_ring[head][1]
        │                    head++  (环形缓冲始终持有最近 600 样本 = 3 秒)
        │
        ├─▶ 状态监控统计累计 |acc| min/max, |gyro| peak
        │
        └─▶ Fall_Algo_Process(ax,ay,az,gx,gy,gz):  路径 B 状态机一步
                IDLE → FREEFALL → IMPACT_WAIT → POST_IMPACT
                |
                └─ 完整序列齐全(失重+硬冲击+静止+躯干倾倒) → 返回 1
                              │
                              ▼
④ NN 复核（仅在路径 B 触发后）：EI_Fall_Classify()
        ┌── 把 g_ring 按时间顺序展开到 g_window（环形 → 连续）
        ├── numpy::signal_from_buffer(g_window, 1200, &signal)
        ├── run_classifier(handle, &signal, &result, false):
        │     ┌─ DSP Flatten: 1200 floats → 14 个统计特征
        │     │    (mean/min/max/RMS/stdev/skew/kurt × 2 通道)
        │     ├─ 量化输入: float → int8 (scale=816.97, zp=-128)
        │     ├─ FC0+ReLU: int8 [14] → int8 [20]  (W0 280B, B0 80B)
        │     ├─ FC1+ReLU: int8 [20] → int8 [10]  (W1 200B, B1 40B)
        │     ├─ FC2:       int8 [10] → int8 [2]   (W2 20B,  B2 8B)
        │     ├─ Softmax:   int8 [2] → int8 [2]    (scale=1/256, zp=-128)
        │     └─ 反量化输出: int8 → float 概率 [0..1]
        └── 解析 result.classification[i].label == "fall" / "normal"
            打印 [EI] NN result: fall=X% normal=Y%
        │  耗时 ~10 ms
        ▼
⑤ 仲裁（main_task.c:251-272）
   if (nn.valid && nn.normal_percent >= 95)  否决报警 ([Hybrid] B triggered, NN veto)
   else                                        触发报警 ([Hybrid] B+NN agree)
        │
        ▼
⑥ 报警（仅在仲裁通过时）
   ┌─ 星闪 SLE: sle_send_fall_alert(&payload, 1)  → 0x05 字节通知客户端
   ├─ WS2812B 灯带常亮 10 秒
   └─ 进入 3 秒报警冷却（避免抖动二次触发）
```

---

## 8. 模型重训后怎么更新？

EI Studio 重新训练并 Build → `C++ library`（勾 EON Compiler + TensorFlow Lite）→ 下载 zip。

**8.1 必改 / 自动同步项目矩阵**

| 项 | 是否需要手改 | 在哪 |
| --- | --- | --- |
| `edge-impulse-sdk/` | 否，整体替换 | 直接覆盖目录 |
| `model-parameters/` | 否，整体替换 | 直接覆盖目录 |
| `tflite-model/` | 否，整体替换 | 直接覆盖目录（注意：编译后的 .cpp 文件名里带 project_id，要在 `model_variables.h` 里同步 include） |
| `impulse_999999_1` 这个全局变量名 | 是 | `ei_fall.cpp:59` `new (g_handle) ei_impulse_handle_t(&impulse_999999_1);` 要改成新 project_id |
| 类别名 `"fall"` / `"normal"` | 是（如果改名） | `ei_fall.cpp:133, 135` |
| 量纲（milli-g, centi-dps） | 是（如果训练 CSV 用了别的单位） | `ei_fall.cpp:37-38, 72-73` |
| 量化是否启用、INT8 vs float32 | 否，SDK 自适应 | `model_metadata.h` 中宏会自动切换 |

**8.2 标准更新流程**

```bash
# 1. 把旧的三个文件夹改名备份
mv edge-impulse-sdk    edge-impulse-sdk.bak_$(date +%Y%m%d)
mv model-parameters    model-parameters.bak_$(date +%Y%m%d)
mv tflite-model        tflite-model.bak_$(date +%Y%m%d)

# 2. 解压 EI 下载的 zip，三个新目录拷进来
unzip -d . ei-export-fall-vN.zip

# 3. 改 ei_fall.cpp 的 project_id 引用
#    (vim ei_fall.cpp，把 impulse_999999_1 改成新 project_id)

# 4. 重新 menuconfig（无需改）+ build.py
python build.py
```

**8.3 怎么验证新模型在板上跑通**

开机串口应出现：

```
[EI] NN ready: 600 samples x 2 axes @ 200 Hz, window=1200 floats
[MPU6050] cfg: accel=+/-16g gyro=+/-2000dps dlpf=44Hz sample=200Hz ...
[Sample] 200Hz hardware-timed sampling started
[Monitor] B=IDLE acc=0.99~1.01G gyr_peak=2 dps q=0/128 drops=0
```

模拟跌倒（搬起板子做"失重→拍桌→静止"动作）应看到：

```
[Fall] freefall 38 samples, waiting for impact...
[Fall] impact detected, checking stillness...
[Fall] CONFIRMED (impact 5.43G, tilt 87 deg, ffmin 0.21G, still 89%)
[EI] NN result: fall=98% normal=2%
[Hybrid] B+NN agree (fall=98% normal=2%)
[Alert] Fall Detected. Sending SOS now...
```

---

## 9. 常见小白坑

| 现象 | 根因 | 解 |
| --- | --- | --- |
| `[EI] window not full (xxx/600), skip NN` | 路径 B 在开机不到 3 秒就触发，环形缓冲还没攒满 600 | 正常，等 3 秒后路径 B 再触发 |
| 准确率差，乱报警 | 部署的采样率/量程/单位和 EI 训练数据不一致 | 对照第 3 节核查：200 Hz、±16g、±2000dps、`|acc|` milli-g、`|gyro|` centi-dps |
| `[EI] OOM: request N bytes` | `g_ei_heap` 64 KB 不够 | 把 `EI_WS63_HEAP_SIZE` 调回 64 KB；或继续排查泄漏 |
| 编译报 `-Wnarrowing` 错 | `model_variables.h` 里整数字面量被 `-Werror` 升级成错误 | `ei_fall.cpp:26-31` 已用 `#pragma GCC diagnostic` 局部抑制 |
| 编译报"找不到 `model_metadata.h`" | CMake 没把 `model-parameters/` 加进 `PUBLIC_HEADER` | 看 `CMakeLists.txt:88` |
| 路径 B 触发但 NN 总输出 `normal=100%` | 类别名或量纲与训练数据不符 | 串口看 `[EI] NN result: ...`，对照 8.1 |
| `[Hybrid] B triggered, NN veto: alert suppressed` | NN 否决了报警 | 如果是误否决，把训练数据补上、重训；如果误触发被正确否决，不用动 |
| 模型改了字段名，编译过但运行崩 | `ei_fall.cpp` 里 `impulse_999999_1` 没同步改 | 见 8.1 |

---

## 10. 一句话回顾

> **AI 不是这个项目的主判，是复核器**：路径 B（确定性状态机）保证不漏报，NN（INT8 量化的 14→20→10→2 全连接网络）帮忙挡误报。模型本体只有 **628 字节权重 + 368 字节 arena**，跑一次推理约 10 ms，被设计成"事件触发"避开每 5 ms 的采样节拍。整个 AI 部分占 WS63 大概 30% 的 SRAM。接下来要再压模型已经没什么收益，重心应该转到训练数据扩充和重训。
