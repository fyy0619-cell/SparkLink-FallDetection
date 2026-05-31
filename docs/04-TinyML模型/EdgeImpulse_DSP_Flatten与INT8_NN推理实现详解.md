# DSP Flatten 与 INT8 NN 推理实现详解

> 配套阅读：
> - [EdgeImpulse_模型部署全流程_小白指南](EdgeImpulse_模型部署全流程_小白指南.md) — "怎么塞进 WS63"
> - [EdgeImpulse_run_classifier内部原理与参数拆解](EdgeImpulse_run_classifier内部原理与参数拆解.md) — "那一行调用的入口流程"
>
> 本篇深挖 `run_classifier` 内部最核心两步——**DSP（1200 floats → 14 维特征）** 和 **INT8 NN 推理（14 → 2 概率）**——的源码级实现。读完应该能在面试时把 EI 的 Flatten DSP 算什么、INT8 全连接怎么算、Softmax 怎么得到概率，从公式到内存布局讲一遍。

---

## 0. 两阶段总览

```text
[1200 floats]  ──DSP Flatten──▶  [14 floats]  ──量化──▶  [14 int8]
                                                              │
                                                              ▼
                                                       EON 计算图
                                                FC0 + ReLU → FC1 + ReLU
                                                  → FC2 → Softmax
                                                              │
                                                              ▼
                                                          [2 int8]
                                                              │
                                                          反量化
                                                              ▼
                                                  {fall: 0.91, normal: 0.09}
```

时间预算（基于 RISC-V @160MHz 估算）：
- DSP Flatten：**5~15 ms**（瓶颈，单遍 sqrt/pow 是大头）
- INT8 NN：**<1 ms**（500 次 INT8 MAC）
- 总单次推理 ~10 ms

---

# 第一阶段：DSP Flatten

## 1.1 入口与调度

主流程在 `process_impulse` 里调用（`ei_run_classifier.h:308-378`）：

```cpp
for (size_t ix = 0; ix < handle->impulse->dsp_blocks_size; ix++) {
    ei_model_dsp_t block = handle->impulse->dsp_blocks[ix];
    matrix_ptrs[ix] = std::unique_ptr<ei::matrix_t>(new ei::matrix_t(1, block.n_output_features));
    // 你工程: block.n_output_features = 14
    features[ix].matrix = matrix_ptrs[ix].get();

    SignalWithAxes swa(signal, block.axes, block.axes_size, handle->impulse);
    auto internal_signal = swa.get_signal();

    // 你工程: block.extract_fn = &extract_flatten_features
    int ret = block.extract_fn(internal_signal, features[ix].matrix, block.config, 200);
}
```

`block.extract_fn` 这个函数指针来自 `model_variables.h:69-81`：

```cpp
ei_model_dsp_t ei_dsp_blocks_999999_1[1] = {
    {
        .blockId           = 6,
        .n_output_features = 14,                          // ★ 输出 14 维
        .extract_fn        = &extract_flatten_features,   // ★ 处理函数
        .config            = (void*)&ei_dsp_config_999999_6,  // ★ 配置
        .axes              = ei_dsp_config_999999_6_axes, // {0, 1} = 用前 2 个通道
        .axes_size         = 2,
        ...
    }
};
```

配置体在 `model_variables.h:53-66`：

```cpp
ei_dsp_config_flatten_t ei_dsp_config_999999_6 = {
    .blockId               = 6,
    .implementationVersion = 1,
    .axes                  = 2,        // 2 通道 (|acc|, |gyro|)
    .scale_axes            = 1.0f,     // 不缩放
    .average               = true,     // ★ 7 个统计量全开
    .minimum               = true,
    .maximum               = true,
    .rms                   = true,
    .stdev                 = true,
    .skewness              = true,
    .kurtosis              = true,
    .moving_avg_num_windows = 0,       // 不算滑动均值
};
```

**关键算式**：输出维度 = 启用统计量个数 × 通道数 = **7 × 2 = 14**。这就是 14 怎么算出来的。

## 1.2 `extract_flatten_features` 实现拆解

源码 `edge-impulse-sdk/dsp/ei_flatten.h:55-169`。逐步拆解：

### Step 1：分配 input_matrix，从 signal 读数据

```cpp
matrix_t input_matrix(signal->total_length / config.axes, config.axes);
//                    = matrix_t(1200/2, 2) = matrix_t(600, 2)
signal->get_data(0, signal->total_length, input_matrix.buffer);
//          一次回调，把 1200 个 float 全拉过来
```

此时 `input_matrix` 的内存布局是**行优先 (600 行 × 2 列)**：

```
input_matrix[0] = |acc|[0], |gyro|[0]
input_matrix[1] = |acc|[1], |gyro|[1]
...
input_matrix[599] = |acc|[599], |gyro|[599]
```

即按时间顺序：每一行是一个时刻的 (|acc|, |gyro|) 对。

### Step 2：scale（你工程是 1.0，等于不做）

```cpp
ret = numpy::scale(&input_matrix, config.scale_axes);  // = 1.0
```

如果训练时 EI Studio 里勾选了 scaling，这里会把所有元素乘上 `scale_axes`。你 EI 项目里 `scale_axes = 1.0`，所以这一步是空跑。

### Step 3：转置 —— 关键一步

```cpp
numpy::transpose_in_place(&input_matrix);
// (600, 2)  →  (2, 600)
```

转置后内存布局变成**按通道分行**：

```
input_matrix[0] = |acc|[0],  |acc|[1],  |acc|[2],  ..., |acc|[599]    ← 600 个值, 通道 0
input_matrix[1] = |gyro|[0], |gyro|[1], |gyro|[2], ..., |gyro|[599]   ← 600 个值, 通道 1
```

为什么要转置？因为后面要**按通道单独算统计量**，需要每个通道连续在内存里——这样取一行就是一个通道的全部 600 个样本，可以直接喂给 `numpy::mean` 等向量函数。

> in_place 转置不分新内存，原地交换。代价是 O(N) 时间，但省 4.7 KB 内存。

### Step 4：逐通道、逐统计量计算

```cpp
size_t out_matrix_ix = 0;
for (size_t row = 0; row < input_matrix.rows; row++) {  // row = 0, 1 (两个通道)
    matrix_t row_matrix(1, input_matrix.cols,
                        input_matrix.buffer + (row * input_matrix.cols));
    // row_matrix 是当前通道的 600 个值（共享底层 buffer，不复制）

    if (config.average) {
        numpy::mean(&row_matrix, &out_matrix);
        output_matrix->buffer[out_matrix_ix++] = ...;
    }
    if (config.minimum) { ... numpy::min ... }
    if (config.maximum) { ... numpy::max ... }
    if (config.rms)     { ... numpy::rms ... }
    if (config.stdev)   { ... numpy::stdev ... }
    if (config.skewness){ ... numpy::skew ... }
    if (config.kurtosis){ ... numpy::kurtosis ... }
}
```

输出顺序**完全决定于 if 语句的顺序**——这就是你模型 14 个输入特征的物理意义：

| 索引 | 含义 |
|---|---|
| `output[0]` | `|acc|` 的 mean (均值) |
| `output[1]` | `|acc|` 的 min (最小值) |
| `output[2]` | `|acc|` 的 max (最大值) |
| `output[3]` | `|acc|` 的 RMS (均方根) |
| `output[4]` | `|acc|` 的 stdev (标准差) |
| `output[5]` | `|acc|` 的 skewness (偏度) |
| `output[6]` | `|acc|` 的 kurtosis (峰度) |
| `output[7]` | `|gyro|` 的 mean |
| `output[8]` | `|gyro|` 的 min |
| ... | ... |
| `output[13]` | `|gyro|` 的 kurtosis |

**直觉理解**：
- mean / RMS 描述"窗口里能量整体多大"——跌倒能量大；
- max / min 抓"瞬时峰值/谷值"——跌倒既有自由落体（min 接近 0）又有冲击（max 大）；
- stdev 描述"波动剧烈度"；
- skewness 描述"不对称性"——冲击是个尖峰，分布偏；
- kurtosis 描述"尾巴有多重"——冲击是重尾。

这 7 个统计量加在一起，足够把"跌倒（不对称尖峰）"和"正常活动（平稳分布）"区分开。

### Step 5：reshape 为 (1, 14)

```cpp
output_matrix->cols = output_matrix->rows * output_matrix->cols;  // = 14
output_matrix->rows = 1;
```

把 (2, 7) 看成 (1, 14)——一维向量，正好喂给后面 NN。

## 1.3 7 个统计量的具体公式

简化的 numpy 风格表达（设 x = [x_0, x_1, ..., x_{N-1}], N=600）：

| 统计量 | 公式 | 代价 |
|---|---|---|
| mean | μ = (1/N) Σ x_i | N 加法 |
| min | min(x_i) | N 比较 |
| max | max(x_i) | N 比较 |
| RMS | √((1/N) Σ x_i²) | N 乘 + N 加 + 1 sqrt |
| stdev | σ = √((1/N) Σ (x_i − μ)²) | 需先算 μ：2N 加 + N 平方 + 1 sqrt |
| skewness | E[((x−μ)/σ)³] | 需 μ, σ：N 立方 + 加和 |
| kurtosis | E[((x−μ)/σ)⁴] − 3 | 需 μ, σ：N 四次方 + 加和 |

**注意**：EI 的实现里这 7 个**各遍历一次**`row_matrix` —— 每个通道总共**遍历 7 遍 × 600 = 4200 次浮点操作**，两通道 8400 次。这就是 DSP 慢的根本原因。

> **优化点**：用 Welford 单遍算法可以**一次遍历同时算出** mean / var / skew / kurt（min/max 顺便）。从 7 遍压到 1 遍，理论上 7× 加速。EI 出于通用性没做这个优化（每个统计量独立配置），但工程上把这段重写是回报最高的 ROI。

## 1.4 内存分配在哪发生？

```cpp
matrix_t input_matrix(600, 2);  // new matrix_t → ei_malloc → 从 g_ei_heap 分配
                                //  600 * 2 * 4 = 4800 bytes
```

这就是 `g_ei_heap` 那 64 KB 里**最大的临时块**。如果你压缩 `g_ei_heap` 到 32 KB，DSP 这一步分不出 4800 字节就会 OOM。

> 还有几个小的：`row_matrix` 是 view（共享底层 buffer，不分配新内存）；`fbuffer` 是栈上的 single float，不走 heap。

---

# 第二阶段：INT8 NN 推理

## 2.1 入口与调度

`process_impulse` 调用 `run_inference`（`ei_run_classifier.h:413`），再委托给 `block.infer_fn` —— 在你工程里指向 `run_nn_inference`（`tflite_eon.h:199`）。

`run_nn_inference` 做 5 件事：

1. 调 `inference_tflite_setup` 初始化模型 + 拿到输入/输出张量描述符
2. 调 `fill_input_tensor_from_matrix` 把 DSP 输出的 14 个 float **量化** 成 INT8
3. 调 `inference_tflite_run` 触发 EON 编译图执行
4. 把输出张量拷出来到 `result->_raw_outputs`（INT8 原始值，反量化交给后处理）
5. 调 `model_reset` 释放 tensor_arena

## 2.2 Setup：分配 tensor_arena、拿张量句柄

`tflite_eon.h:57-90`：

```cpp
static EI_IMPULSE_ERROR inference_tflite_setup(...) {
    TfLiteStatus init_status = graph_config->model_init(ei_aligned_calloc);
    // ↑ 调用 tflite_learn_999999_3_init(ei_aligned_calloc)
    //   函数体在 tflite_learn_999999_3_compiled.cpp:527-545:
    //     tensor_arena = (uint8_t*)alloc_fnc(16, kTensorArenaSize);  // = 368 字节
    //     memset(tensor_arena, 0, 368);
    //     初始化所有张量描述符的 data 指针，把它们指到 tensor_arena 上对应偏移

    graph_config->model_input(0, input);
    //   ↑ 拿到输入张量的 TfLiteTensor 描述符：
    //     - type = kTfLiteInt8
    //     - dims = (1, 14)
    //     - data.int8 = tensor_arena + 32
    //     - params.scale = 816.97f
    //     - params.zero_point = -128

    graph_config->model_output(0, &outputs[0]);
    //   ↑ 拿到输出张量描述符：
    //     - type = kTfLiteInt8
    //     - dims = (1, 2)
    //     - data.int8 = tensor_arena + 0
    //     - params.scale = 0.00390625f
    //     - params.zero_point = -128
}
```

**关键**：这一步没做任何"算"，只是把 368 字节 arena 分出来 + 把每个张量的"门牌号"记好。算的活全在 `model_invoke()` 里。

## 2.3 量化输入：float[14] → int8[14]

`tflite_helper.h:93-100`：

```cpp
case kTfLiteInt8: {
    for (size_t ix = 0; ix < matrix->rows * matrix->cols; ix++) {  // 14 次
        float val = (float)matrix->buffer[ix];                      // 来自 DSP
        input->data.int8[input_idx++] = static_cast<int8_t>(
            pre_cast_quantize(val,
                              input->params.scale,     // = 816.97
                              input->params.zero_point, // = -128
                              true));                  // is_signed
    }
}
```

`pre_cast_quantize` 做的事（仿射量化公式）：

```
q = clamp(round(val / scale) + zero_point, -128, 127)

  val 例如 1500.0   (DSP 算出来的 |acc| mean)
  scale = 816.97
  zero_point = -128

  → round(1500.0 / 816.97) + (-128)
  = round(1.836) + (-128)
  = 2 + (-128)
  = -126
```

写到 `tensor_arena + 32` 起的 14 个字节里——下一步 NN 计算从这里读输入。

**为什么 scale 这么大（816）？** 因为 DSP 输出的特征值能到几千（|acc| milli-g、|gyro| centi-dps、RMS 大值），要让 -128~127 这 256 个 INT8 档位覆盖到 [-128×816, 127×816] ≈ [-104K, 104K]。EI 在训练时统计校准集的 min/max 算出来的。

## 2.4 触发 EON 编译图：`model_invoke()`

`tflite_eon.h:115`：

```cpp
if (graph_config->model_invoke() != kTfLiteOk) {
    return EI_IMPULSE_TFLITE_ERROR;
}
```

这一行调的就是 `tflite_learn_999999_3_invoke()`——EON Compiler 生成的"硬编码 4 算子链"。函数大概结构（实际是几百行的展开代码）：

```cpp
TfLiteStatus tflite_learn_999999_3_invoke() {
    // Op 0: FullyConnected + ReLU      输入 tensor_arena+32 输出 tensor_arena+0
    tflite::ops::micro::FullyConnectedEval(
        &tflTensors[0].tensor,   // input    int8[14]  arena+32
        &tflTensors[6].tensor,   // weights  int8[20,14] (在 .rodata, 280 字节)
        &tflTensors[5].tensor,   // bias     int32[20]   (在 .rodata, 80 字节)
        &tflTensors[7].tensor,   // output   int8[20]  arena+0
        &opdata0                 // {activation=ReLU, ...}
    );

    // Op 1: FullyConnected + ReLU      输入 tensor_arena+0  输出 tensor_arena+32
    tflite::ops::micro::FullyConnectedEval(
        &tflTensors[7].tensor,   // input    int8[20]  arena+0
        &tflTensors[4].tensor,   // weights  int8[10,20] (.rodata, 200 字节)
        &tflTensors[3].tensor,   // bias     int32[10]   (.rodata, 40 字节)
        &tflTensors[8].tensor,   // output   int8[10]  arena+32
        &opdata1
    );

    // Op 2: FullyConnected (no act)    输入 tensor_arena+32 输出 tensor_arena+16
    tflite::ops::micro::FullyConnectedEval(
        &tflTensors[8].tensor,   // input    int8[10]  arena+32
        &tflTensors[2].tensor,   // weights  int8[2,10]  (.rodata, 20 字节)
        &tflTensors[1].tensor,   // bias     int32[2]    (.rodata, 8 字节)
        &tflTensors[9].tensor,   // output   int8[2]   arena+16   (logits)
        &opdata2
    );

    // Op 3: Softmax                    输入 tensor_arena+16 输出 tensor_arena+0
    tflite::ops::micro::SoftmaxEval(
        &tflTensors[9].tensor,   // input    int8[2]   arena+16
        &tflTensors[10].tensor,  // output   int8[2]   arena+0    (概率)
        &opdata3
    );

    return kTfLiteOk;
}
```

> **EON 不是新算子库**——它调用的还是 TFLite Micro 自带的 `FullyConnectedEval` / `SoftmaxEval` 内核。EON 的"魔法"在于：
> 1. **去掉了 flatbuffers 解析**：张量描述符和算子参数都是 C++ 常量数组，直接 link 进二进制；
> 2. **去掉了算子调度循环**：不用解析器对图节点遍历，直接 4 行顺序调用；
> 3. **手工排好 tensor_arena 偏移**：每个张量在 arena 里的位置由 EON 静态算好（+0/+16/+32），自动复用——所以才能从默认 2944 字节缩到 368 字节。

## 2.5 INT8 全连接到底怎么算

最关键的一步。一个 FC 层数学上是 `y = W·x + b`，量化版本要复杂一些。

### 数学定义（per-tensor 仿射量化）

设：
- 输入 x：int8，scale `Sx`，zero_point `Zx` (你模型里 = -128)
- 权重 W：int8，scale `Sw`，zero_point `Zw` (= 0，对称量化)
- bias b：int32，scale `Sb` = Sx × Sw（强制对齐方便累加）
- 输出 y：int8，scale `Sy`，zero_point `Zy` (= -128)

理论计算：

```
                       ┌─真实浮点版─┐
y_float[i] = Σ_j ( W_float[i,j] × x_float[j] ) + b_float[i]

                       ┌─代入量化关系─┐
W_float[i,j] = Sw × W_int8[i,j]
x_float[j]   = Sx × (x_int8[j] - Zx)
b_float[i]   = Sx × Sw × b_int32[i]

→ y_float[i] = Sx × Sw × ( Σ_j W_int8[i,j] × (x_int8[j] - Zx) + b_int32[i] )

                       ┌─再量化回 int8─┐
y_int8[i] = clamp(round(y_float[i] / Sy) + Zy, -128, 127)

→ y_int8[i] = clamp(round( (Sx × Sw / Sy) × accum_int32 ) + Zy, -128, 127)
```

其中 `accum_int32` 是 INT32 累加器：

```
accum_int32 = Σ_j W_int8[i,j] × (x_int8[j] - Zx) + b_int32[i]
```

### 实际单片机怎么算

TFLite Micro 的 `FullyConnectedEval` 内核走这条路：

```cpp
// 简化版伪代码
for (i = 0; i < output_size; i++) {        // 比如 20 个输出
    int32_t acc = b_int32[i];               // bias 先放进累加器
    for (j = 0; j < input_size; j++) {      // 比如 14 个输入
        int16_t x_shifted = x_int8[j] - Zx; // x − zero_point
        acc += W_int8[i, j] * x_shifted;    // INT8×INT8 = INT16, 再累加进 INT32
    }
    // 重缩放: acc × (Sx × Sw / Sy)
    //   实际用定点乘法器, 而不是浮点除法:
    //   multiplier_int32 + shift_int32 已经在编译期算好
    int32_t out = MultiplyByQuantizedMultiplier(acc, multiplier_int32, shift);
    out += Zy;                                   // 加输出 zero_point
    if (op->activation == kTfLiteActRelu) {
        out = max(out, Zy);                      // ReLU 在量化域 = clamp 到 zero_point
    }
    y_int8[i] = clamp(out, -128, 127);
}
```

几个工程细节：

1. **乘加全程 INT8/INT16/INT32 整数运算，绝不出浮点** — 这是单片机推理快的根本原因。
2. **重缩放 `× (Sx·Sw/Sy)` 用定点乘法器 + 移位** — `MultiplyByQuantizedMultiplier(acc, M, shift)` 等价于 `acc × M / 2^31 >> shift`，全是整数。
3. **ReLU 在 INT8 域**：浮点 `max(0, y)` 对应量化域 `max(Zy, y_int8)`（因为 0 在浮点对应 Zy 在量化域）。

### 一个例子：FC0 算第 0 个输出

设 DSP 给出第 0 个特征 `|acc| mean = 1500.0`，量化后 `x_int8[0] = -126`。
W0 的第 0 行（你 `tflite_learn_..._compiled.cpp:196-216`）：

```
-1, -17, -26, 99, 34, 58, 34, -77, 40, -95, -4, 43, -105, -77
```

bias B0[0] = 0（你模型里 bias 全 0，看 `tensor_data5`）。

```
acc = 0 (bias)
     + (-1)  × (-126 - (-128))    =  (-1)  × 2  = -2
     + (-17) × (x_int8[1] + 128)  = ...
     + ...
     + (-77) × (x_int8[13] + 128) = ...
     = (假设结果) 73529

重缩放: Sx × Sw / Sy = 816.97 × 0.00347 / 334.03 = 0.00849
multiplier_int32 ≈ 0.00849 × 2^31 ≈ 18,243,000
shift ≈ 0

out = (73529 × 18243000) >> 31 = 624
out += -128 (Zy)               = 496

ReLU: max(496, -128) = 496
clamp to [-128, 127]:           = 127  ← 饱和

y_int8[0] = 127
```

> 实际数字未经计算只是示意，但结构如此。INT8 输出常常因为重缩放后偏大而饱和到 127，这是 INT8 量化的固有特性，训练时 QAT 已经把它考虑进去了。

### 算力账

| 层 | 乘加次数 | 重缩放次数 |
|---|---|---|
| FC0 14→20 | 14 × 20 = 280 | 20 |
| FC1 20→10 | 20 × 10 = 200 | 10 |
| FC2 10→2  | 10 × 2  = 20  | 2 |
| 总计 | **500 MAC + 32 重缩放** | |

RISC-V @160MHz 算 500 次 INT8 MAC，即使没有专门的乘加指令也就 **几十微秒级**。这就是为什么 NN 不是瓶颈。

## 2.6 Softmax INT8 怎么算

`tflite_learn_..._compiled.cpp:227-232`：

```cpp
// Softmax 输入: int8[2], scale=66.08, zero_point=127
// Softmax 输出: int8[2], scale=1/256, zero_point=-128
```

数学上 Softmax(z)_i = exp(z_i) / Σ exp(z_j)。

但 INT8 域上直接算 exp 太慢，TFLite Micro 的标准实现用**查表 + 定点近似**：

1. 把 INT8 输入反量化回 float 概念上的"logit"（保留定点形式）；
2. 减去 max 防溢出（数值稳定性）；
3. 查 EXP_LUT 表得到 exp 的定点近似；
4. 累加 + 除法（用定点倒数）；
5. 把结果重新量化到 [-128, 127]，scale=1/256, zp=-128。

**为什么 scale 一定是 1/256？** 因为这是标准做法："INT8 表示 [0, 1] 概率"——把 INT8 整数 0~255（即 -128~127 加上 128）映射到 0.0~0.996...，scale = 1/256，zero_point = -128。这样**每个 INT8 整数 = 一档概率**，反量化时 `prob = (q + 128) / 256`。

## 2.7 后处理：INT8 → float 概率

回到 `process_impulse:418`：

```cpp
res = run_postprocessing(handle, result);
```

按 `model_variables.h:124-135` 的配置，调用 `process_classification_i8`：

```cpp
ei_fill_result_classification_i8_config_t ei_fill_result_classification_i8_config_999999_3 = {
    .zero_point = -128,
    .scale = 0.00390625    // = 1/256
};
```

`process_classification_i8` 内部做的就是反量化：

```cpp
for (i = 0; i < label_count; i++) {                       // 2 次
    int8_t q = output_tensor.data.int8[i];
    float prob = (q - (-128)) * 0.00390625f;              // = (q + 128) / 256
    result->classification[i].label = categories[i];       // "fall" / "normal"
    result->classification[i].value = prob;
}
```

最终 `result.classification[0] = {"fall", 0.91}` `result.classification[1] = {"normal", 0.09}`。

你 `ei_fall.cpp:128-138` 那段 strcmp 取出来的就是这两个浮点数。

---

## 3. 完整数据流图

把两阶段连起来：

```text
┌───────────────────────────────────────────────────────────────┐
│ g_window: float[1200]  =  600 × (|acc|, |gyro|)              │
│   按时间顺序: (|acc|_0, |gyro|_0, |acc|_1, |gyro|_1, ...)     │
└─────────────────────────────────┬─────────────────────────────┘
                                  │  signal->get_data() 一次拉完
                                  ▼
┌───────────────────────────────────────────────────────────────┐
│ DSP Stage (ei_flatten.h)                                       │
│                                                                │
│  input_matrix (600, 2)  ──transpose──▶  input_matrix (2, 600) │
│                                          │                     │
│                                          ▼ row 0 (|acc|)       │
│              mean min max rms stdev skew kurt = 7 floats       │
│                                          │                     │
│                                          ▼ row 1 (|gyro|)      │
│              mean min max rms stdev skew kurt = 7 floats       │
│                                                                │
│  output_matrix (1, 14):                                        │
│   [μ_acc, min_acc, max_acc, RMS_acc, σ_acc, skew_acc, kurt_acc,│
│    μ_gyr, min_gyr, max_gyr, RMS_gyr, σ_gyr, skew_gyr, kurt_gyr]│
└─────────────────────────────────┬─────────────────────────────┘
                                  │  fill_input_tensor_from_matrix
                                  │  每个 float 跑 pre_cast_quantize:
                                  │    q = clamp(round(f/816.97)-128, -128, 127)
                                  ▼
┌───────────────────────────────────────────────────────────────┐
│ NN Stage (tflite_eon.h → tflite_learn_999999_3_invoke)        │
│                                                                │
│  arena+32: int8[14]                                            │
│        │                                                       │
│        │ FC0 (W0 int8[20,14], b0 int32[20], ReLU)              │
│        │   acc_int32 = Σ W·(x-Zx) + b                          │
│        │   y_int8 = clamp(round(acc × Sx·Sw/Sy) + Zy)         │
│        ▼                                                       │
│  arena+0: int8[20]                                             │
│        │                                                       │
│        │ FC1 (W1 int8[10,20], b1 int32[10], ReLU)              │
│        ▼                                                       │
│  arena+32: int8[10]                                            │
│        │                                                       │
│        │ FC2 (W2 int8[2,10], b2 int32[2], no activation)       │
│        ▼                                                       │
│  arena+16: int8[2]  ← logits                                   │
│        │                                                       │
│        │ Softmax (查表 + 定点近似)                              │
│        ▼                                                       │
│  arena+0: int8[2]  ← 概率, scale=1/256                         │
└─────────────────────────────────┬─────────────────────────────┘
                                  │  process_classification_i8
                                  │    prob = (q + 128) / 256
                                  ▼
┌───────────────────────────────────────────────────────────────┐
│ result.classification[0] = {"fall",   0.91}                    │
│ result.classification[1] = {"normal", 0.09}                    │
└───────────────────────────────────────────────────────────────┘
```

---

## 4. 速记结论（面试用）

> **DSP** 把 1200 个 float（600 时刻 × 2 通道，分别是 `|acc|` 和 `|gyro|` 幅值）转置成"按通道分行"，逐通道算 7 个统计量（mean/min/max/RMS/stdev/skewness/kurtosis），输出 14 维特征向量。瓶颈是每个统计量独立遍历一遍，可以用 Welford 单遍算法压到 1/7。
>
> **NN 推理** 把 14 维 float 用 `q = clamp(round(f/scale) + zp, -128, 127)` 量化成 INT8，喂给 EON 编译出来的 `tflite_learn_..._invoke()`——它直接调 TFLite Micro 的 INT8 内核做 3 层全连接（500 次 MAC，INT32 累加器 + 定点重缩放）+ 1 次 Softmax 查表。整条路径全部整数运算，**没有 flatbuffers 解析、没有算子调度循环、张量地址全是 EON 静态排好的 (arena+0/+16/+32)**，所以 tensor_arena 从 EI 标的 2944 字节缩到实际 368 字节，整个 NN 跑下来不到 1 ms。

---

## 附：源码定位速查

| 内容 | 文件 | 行 |
|---|---|---|
| `extract_flatten_features` 入口 | `edge-impulse-sdk/classifier/ei_run_dsp.h` | 214 |
| `flatten_class::extract` 实现 | `edge-impulse-sdk/dsp/ei_flatten.h` | 55 |
| `run_nn_inference` (TFLite EON) | `edge-impulse-sdk/classifier/inferencing_engines/tflite_eon.h` | 199 |
| `inference_tflite_setup` | 同上 | 57 |
| `inference_tflite_run` | 同上 | 104 |
| `fill_input_tensor_from_matrix` (量化输入) | `edge-impulse-sdk/classifier/inferencing_engines/tflite_helper.h` | 57 |
| `tflite_learn_999999_3_init/invoke/...` | `tflite-model/tflite_learn_999999_3_compiled.cpp` | (函数体在文件底部) |
| Flatten DSP 配置实例 | `model-parameters/model_variables.h` | 53 |
| Quantization scale/zero_point | `tflite-model/tflite_learn_999999_3_compiled.cpp` | 158-232 |
