# `run_classifier()` 内部原理与参数拆解

> 配套阅读：[EdgeImpulse_模型部署全流程_小白指南](EdgeImpulse_模型部署全流程_小白指南.md)。
> 那一篇讲"怎么把模型塞进 WS63"；本篇深挖**那一行 `run_classifier(...)` 的内部是怎么跑的**——大厂面试官常追问这个，必须能从 SDK 源码层面说清楚。

定位：`application/samples/my_demo/fall_detect/src/ei_fall.cpp:120`

```cpp
EI_IMPULSE_ERROR res = run_classifier(g_handle, &signal, &result, false);
```

读完本文你能回答：

1. 这 4 个参数分别是什么？
2. `run_classifier` 内部按什么顺序执行？
3. 为什么传 `signal` 而不是直接传内存指针？
4. EON Compiler 在这里起到了什么作用？
5. 出错时怎么靠返回值定位问题？

---

## 1. 函数签名

EI SDK 里 `run_classifier` 有 **3 个重载**（`edge-impulse-sdk/classifier/ei_run_classifier.h`）：

| 行号 | 签名 | 用途 |
|---|---|---|
| 1061 | `run_classifier(signal_t*, result_t*, bool)` | 用默认 impulse（`ei_default_impulse`） |
| **1094** | **`run_classifier(handle*, signal_t*, result_t*, bool)`** | **你用的这一个** |
| 973 | `run_classifier_continuous(...)` | 流式推理（你没用） |

你那行调的是 1094 行的版本：

```cpp
extern "C" EI_IMPULSE_ERROR run_classifier(
    ei_impulse_handle_t *impulse,   // 哪个模型
    signal_t            *signal,    // 数据从哪来
    ei_impulse_result_t *result,    // 结果写到哪
    bool                 debug);    // 要不要打调试日志
```

返回值是枚举：

| 返回值 | 含义 |
|---|---|
| `EI_IMPULSE_OK` | 推理成功 |
| `EI_IMPULSE_INFERENCE_ERROR` | 入参为 null，或 NN invoke 失败 |
| `EI_IMPULSE_DSP_ERROR` | DSP 块返回失败（特征数组越界、`extract_fn` 报错） |
| `EI_IMPULSE_ALLOC_FAILED` | `new ei_feature_t[]` 或 `matrix_t` 内存不够（在 WS63 = `g_ei_heap` 没了） |
| `EI_IMPULSE_CANCELED` | `ei_run_impulse_check_canceled()` 返非 OK（你工程里恒为 OK） |
| `EI_IMPULSE_OUT_OF_MEMORY` | DSP state 句柄分配失败 |

> 工程里只用 `if (res != EI_IMPULSE_OK)` 一并兜底（`ei_fall.cpp:121-124`），调试时建议加 switch 分别打印不同枚举值，能直接定位是 DSP 错了还是 NN 错了。

---

## 2. 你工程里这 4 个实参分别是什么

### 2.1 `g_handle` —— "整个 Impulse 的句柄"

定义在 `ei_model_types.h:496`：

```cpp
class ei_impulse_handle_t {
public:
    ei_impulse_state_t   state;                  // DSP 流式状态（单次推理用不到）
    const ei_impulse_t  *impulse;                // ★ 指向"装配图"
    void               **post_processing_state;  // 后处理状态
    ei_input_params     *input_params;           // 图像输入参数（你用不到）
};
```

`g_handle->impulse` 指向 `model_variables.h:141` 里实例化的 **装配图 `impulse_999999_1`**：

```cpp
const ei_impulse_t impulse_999999_1 = {
    .project_id              = 999999,
    .nn_input_frame_size     = 14,          // NN 期望 14 维输入
    .raw_sample_count        = 600,
    .raw_samples_per_frame   = 2,
    .dsp_input_frame_size    = 1200,        // ★ 必须 == signal->total_length
    .frequency               = 200,
    .dsp_blocks              = ei_dsp_blocks_999999_1,        // ★ DSP 算子表
    .dsp_blocks_size         = 1,                              // 1 个 Flatten 块
    .learning_blocks         = ei_learning_blocks_999999_1,    // ★ NN 算子表
    .learning_blocks_size    = 1,
    .postprocessing_blocks   = ei_postprocessing_blocks_999999_1,
    .categories              = {"fall", "normal"},
    .label_count             = 2,
};
```

`run_classifier` 就是按这张装配图一步步执行的：

| 装配图字段 | 指向 | 在哪一阶段被调 |
|---|---|---|
| `dsp_blocks[0].extract_fn` | `extract_flatten_features` | 第 ④ 步 DSP |
| `learning_blocks[0].infer_fn` | `run_nn_inference` → 内部调 `tflite_learn_999999_3_invoke()` | 第 ⑤ 步 NN |
| `postprocessing_blocks[0].postprocess_fn` | `process_classification_i8` | 第 ⑥ 步后处理 |

> **重要**：装配图是 `const`，烧进 Flash 不占 RAM。`g_handle` 只是个 RAM 里的"指针 + 状态"壳子，包了对装配图的引用。`ei_fall.cpp:50-59` 用 placement new 在 `g_handle_storage` 上手工构造它——**为什么不能用 EI 默认的全局对象 `ei_default_impulse`？** 因为 LiteOS 启动不保证执行 C++ 全局构造函数，那个全局可能内存未初始化，`state` 字段是垃圾值。

### 2.2 `signal` —— "数据读数回调"（不是直接传指针！）

`numpy_types.h:679`：

```cpp
typedef struct ei_signal_t {
    std::function<int(size_t offset, size_t length, float *out_ptr)> get_data;
    size_t total_length;   // 你的工程里 = 1200
} signal_t;
```

**关键设计**：SDK **不让你直接传内存指针**，而是要你提供一个**回调函数** `get_data(offset, length, out_ptr)`——SDK 需要数据时反过来调你：「我要从 offset 开始的 length 个 float，写到 out_ptr」。

为什么这样设计？

1. **流式 / 分页友好**：摄像头的几十 KB 输入可以按需读、不必一次摆好。SDK 跑分块 DSP 时只读它当前需要的那一段。
2. **零拷贝**：如果你的数据在 Flash 或外部 PSRAM，回调里可以直接 memcpy，不必预先搬进 SRAM。
3. **解耦**：SDK 不需要知道你数据在哪、连续不连续，只通过回调拿值——这才是真"接口"。

你用 `numpy::signal_from_buffer(g_window, 1200, &signal)` 是一个**便捷封装**，本质大致是：

```cpp
int signal_from_buffer(float *buf, size_t len, signal_t *out) {
    out->total_length = len;
    out->get_data = [buf](size_t offset, size_t length, float *out_ptr) {
        memcpy(out_ptr, buf + offset, length * sizeof(float));
        return EIDSP_OK;
    };
    return EIDSP_OK;
}
```

用一个 C++ lambda 把"读 `g_window` 的连续段"封装成回调。SDK 拿到 `signal` 后只看到回调，不知道你背后是连续数组。

> 这就是为什么 `ei_fall.cpp` 里要先把环形缓冲 `g_ring` **按时间顺序展开到连续数组 `g_window`**（`ei_fall.cpp:99-110`）——`signal_from_buffer` 需要连续内存，不能直接喂环形缓冲。

### 2.3 `result` —— 输出结构体

`ei_classifier_types.h:271-348`：

```cpp
typedef struct {
    ei_impulse_result_bounding_box_t   *bounding_boxes;       // 物体检测用，= NULL
    uint32_t                            bounding_boxes_count; // = 0
    ei_impulse_result_classification_t *classification;       // ★ 分类结果数组
    float                               anomaly;              // 你没开异常检测 = 0
    ei_impulse_result_timing_t          timing;               // ★ 各阶段耗时
    ei_feature_t                       *_raw_outputs;         // NN 原始输出张量
    ei_post_processing_output_t         postprocessed_output;
} ei_impulse_result_t;
```

每个分类项是 `{const char *label; float value;}`。你 `ei_fall.cpp:128-138` 那段 strcmp 比对 `"fall"`/`"normal"` 就是在这里取：

```cpp
for (uint16_t i = 0; i < EI_CLASSIFIER_LABEL_COUNT; i++) {
    const char *label = result.classification[i].label;     // "fall" 或 "normal"
    if (strcmp(label, "fall") == 0)   fall_prob   = result.classification[i].value;
    else if (strcmp(label, "normal") == 0) normal_prob = result.classification[i].value;
}
```

`timing` 字段对调优非常有用：

| 字段 | 含义 |
|---|---|
| `timing.dsp_us` | DSP（Flatten）耗时 |
| `timing.classification_us` | NN 推理耗时 |
| `timing.postprocessing_us` | 后处理耗时 |
| `timing.anomaly_us` | 异常检测耗时（你没开 = 0） |

> 想验证"瓶颈在 DSP 不在 NN"？直接加一行：
> ```cpp
> ei_printf("[EI] timing: dsp=%lld us, nn=%lld us, post=%lld us\n",
>           result.timing.dsp_us, result.timing.classification_us, result.timing.postprocessing_us);
> ```
> 这是 EI 给你预埋的**内置 profiler**，免费拿。

### 2.4 `debug = false` —— 调试开关

设 `true` 会做两件事（`ei_run_classifier.h:390-405`）：

- 把 DSP 出来的 14 个特征值用 `ei_printf_float` 逐个打到串口
- 打印 "Running impulse..." 等过程信息

**在 WS63 上一定要传 `false`**：`ei_printf_float` 走同步串口，每个 float 几百微秒，14 个特征就是 5+ ms 的额外开销，会把 10 ms 推理拖到 15-20 ms。临时调试时再开。

---

## 3. 推理实现 —— 7 步全链路

`run_classifier(g_handle, &signal, &result, false)` 内部转给 `process_impulse`（`ei_run_classifier.h:210`），整个流程：

```text
run_classifier(g_handle, &signal, &result, false)               (ei_run_classifier.h:1094)
   │
   └─▶ process_impulse(handle, signal, result, debug)            (ei_run_classifier.h:210)
        │
        ├── ① 参数校验 + memset(result, 0)                       :215-219
        │    任一指针为 null → 直接返 EI_IMPULSE_INFERENCE_ERROR
        │
        ├── ② 为分类标签预填占位                                  :221-247
        │    static vector<classification_t> ←
        │      {"fall",   0.0f},
        │      {"normal", 0.0f}
        │    result.classification = vector.data()
        │    (这一步保证后面就算 NN 失败, result.classification[i].label
        │     也是有效字符串, 不至于 strcmp 时段错误)
        │
        ├── ③ 分配 ei_feature_t[] 装 DSP 输出                    :281-292
        │    new ei_feature_t[1]  ← 只有 1 个 DSP block
        │
        ├── ④ ★ DSP 阶段 ★                                        :304-378
        │    dsp_start_us = ei_read_timer_us()                  // ← 你工程里走 tcxo_get_us
        │
        │    FOR each dsp_block (你只有 1 个 Flatten):
        │      matrix_t *out = new matrix_t(1, 14)               // 给 14 维特征腾位置
        │      SignalWithAxes swa(signal, axes={0,1}, axes_size=2, impulse)
        │                                                        // 包装 signal,
        │                                                        // 只暴露当前 block 关心的轴
        │      ret = block.extract_fn(internal_signal, out, block.config, 200)
        │            │
        │            └─▶ extract_flatten_features():
        │                  通过 signal->get_data() 分批读 1200 个 float
        │                  对每个通道分别算 7 个统计量:
        │                    mean / min / max / RMS /
        │                    stdev / skewness / kurtosis
        │                  → 写入 out->buffer (14 个 float)
        │      features[0].matrix = out
        │
        │    result.timing.dsp_us = ei_read_timer_us() - dsp_start_us
        │
        ├── ⑤ ★ NN 推理阶段 ★                                     :413
        │    res = run_inference(handle, features, result, false)   (ei_run_classifier.h:144)
        │            │
        │            └─▶ FOR each learning_block (你只有 1 个):
        │                  block.infer_fn(impulse, features, ix,
        │                                  input_ids, n, result,
        │                                  block.config, debug)
        │                   │
        │                   └─▶ run_nn_inference()  (TFLite INT8 量化路径)
        │                        ├── 量化输入: float[14] → int8[14]
        │                        │     q_i = round(f_i / 816.97) - 128
        │                        │
        │                        ├── tflite_learn_999999_3_invoke()       ← EON 编译图
        │                        │     FC0(W0 14×20, b0) + ReLU → int8[20]
        │                        │     FC1(W1 20×10, b1) + ReLU → int8[10]
        │                        │     FC2(W2 10×2,  b2)        → int8[2]   (logits)
        │                        │     Softmax                   → int8[2]   (概率)
        │                        │
        │                        ├── 拷贝输出张量 → result._raw_outputs
        │                        └── 记 classification_us
        │
        ├── ⑥ ★ 后处理 ★                                          :418
        │    res = run_postprocessing(handle, result)
        │            │
        │            └─▶ process_classification_i8():
        │                  反量化: prob_i = (q_i - (-128)) × (1/256)
        │                  按 categories 顺序填:
        │                    classification[0] = {"fall",   X}
        │                    classification[1] = {"normal", Y}
        │
        ├── ⑦ 时间单位换算                                        :423
        │    ei_result_struct_timing_us_to_ms(result):
        │      把 timing.dsp_us / classification_us / postprocessing_us
        │      复制一份为 timing.dsp / classification / postprocessing (ms)
        │
        └── return EI_IMPULSE_OK
```

---

## 4. EON Compiler 在哪一步发挥作用

EON Compiler 的角色集中在**第 ⑤ 步**。

**未启用 EON**（普通 TFLite Micro 解释器）会这样跑：

```text
解释器加载 .tflite 文件 (flatbuffers)
  → 解析模型结构 (动态)
  → 分配 tensor_arena (按最坏情况预留 2944 B)
  → 算子调度: for each op in graph: dispatch(op) → 解释执行
  → 每个 op 调用都有 vtable / 函数指针开销
```

**启用 EON** 后（你工程 `EI_CLASSIFIER_COMPILED=1`）：

```text
EON Compiler 在 EI Studio 编译时把整张图编成 C++ 源码:
  tflite_learn_999999_3_invoke() {
    // 全部硬编码, 没有解释器, 没有 flatbuffers 解析
    FullyConnectedInt8(input, W0, b0, output_a);
    ReLU(output_a);
    FullyConnectedInt8(output_a, W1, b1, output_b);
    ReLU(output_b);
    FullyConnectedInt8(output_b, W2, b2, output_c);
    SoftmaxInt8(output_c, output);
  }
  // 张量地址 (tensor_arena + 0/16/32) 也预先排好, 复用 → arena 缩到 368 B
```

收益：
1. 省掉 flatbuffers 解析代码（~10 KB Flash）
2. 省掉算子注册表查找开销（速度提升 1.5-2×）
3. **tensor_arena 从 2944 B 缩到 368 B**（手工排布、复用）

代价：
- 改算法/换模型必须重新跑 EI Studio Build；
- 调试时看不到中间张量（解释器有 hook，EON 直接是裸 C++）。

> 对部署到死板子的场景，这个交易是完全划算的。

---

## 5. 一次失败排查指南

`run_classifier` 出错时，按返回值分类对应排查动作：

| 返回值 | 大概率根因 | 排查 |
|---|---|---|
| `EI_IMPULSE_INFERENCE_ERROR` | `handle/signal/result` 任一为 null；或 NN invoke 失败 | 检查 `g_handle` 是否在 `EI_Fall_Init()` 里 placement new 过；NN 失败要看 `DebugLog` 串口输出 |
| `EI_IMPULSE_DSP_ERROR` | DSP `extract_fn` 返非 `EIDSP_OK`，常见是特征数组越界 | 检查 `signal->total_length` 是否等于 `impulse->dsp_input_frame_size`（你工程都是 1200） |
| `EI_IMPULSE_ALLOC_FAILED` | `new ei_feature_t[]` / `matrix_t` 在 `g_ei_heap` 上分不出来 | 串口看 `[EI] OOM: request N bytes`；把 `EI_WS63_HEAP_SIZE` 调大；检查是否有 ei_free 漏调 |
| `EI_IMPULSE_OUT_OF_MEMORY` | DSP state 句柄分配失败（你单次推理走不到这条） | 检查 `g_ei_heap` 是否已 init |
| `EI_IMPULSE_CANCELED` | `ei_run_impulse_check_canceled()` 返非 OK | 你工程里这函数恒为 OK，理论上不该出 |

另外有"返 `EI_IMPULSE_OK` 但结果错"的情况（**最阴险**）：

| 症状 | 根因 |
|---|---|
| `fall_percent` 永远接近 0 | 量纲不对（训练 milli-g、部署 g），或者 `g_ring → g_window` 拷贝顺序错 |
| 特征全 NaN | `g_ring` 里有 NaN（MPU6050 掉线返回 0/0 sqrt 错误） |
| 特征值全是同一个数 | `signal_from_buffer` 的 lambda 闭包捕获了局部变量 → 出作用域 |
| 串口能看到 `[EI] NN result` 但板子从不报警 | NN 输出正确但 `NN_VETO_NORMAL_PCT` 阈值或类别名字符串没对齐 |

这些都不会被 `EI_IMPULSE_OK` 拦住，**只能靠 `result.timing.*` + 把 `debug=true` 临时打开打印特征值** 来分辨。

---

## 6. 一句话总结

> `run_classifier(g_handle, &signal, &result, false)` 接受一个**装配图句柄**（说明 DSP/NN/后处理是什么）、一个**数据回调**（按需读 g_window）和一个**输出结构体**，内部 7 步同步执行：参数校验 → 占位分类结果 → DSP（1200 floats → 14 维 Flatten 特征）→ NN（INT8 全连接 + Softmax，EON 直接调用，无解释器）→ 反量化填 `classification[]` → 各阶段耗时记入 `timing` → 返回 `EI_IMPULSE_OK`。**整条路径没有动态算子调度**，所以才能在 WS63 这种 RAM 几十 KB 的单片机上跑得起来。

---

## 附：源码定位速查

| 内容 | 文件 | 行 |
|---|---|---|
| `run_classifier` 4 参版本入口 | `edge-impulse-sdk/classifier/ei_run_classifier.h` | 1094 |
| `process_impulse` 主流程 | 同上 | 210 |
| `run_inference` NN 入口 | 同上 | 144 |
| `signal_t` 定义 | `edge-impulse-sdk/dsp/numpy_types.h` | 679 |
| `ei_impulse_handle_t` 定义 | `edge-impulse-sdk/classifier/ei_model_types.h` | 496 |
| `ei_impulse_result_t` 定义 | `edge-impulse-sdk/classifier/ei_classifier_types.h` | 271 |
| `impulse_999999_1` 装配图 | `model-parameters/model_variables.h` | 141 |
| `tflite_learn_999999_3_invoke` 入口 | `tflite-model/tflite_learn_999999_3_compiled.cpp` | (init/invoke/input/output/reset 一组) |
| 你的调用点 | `ei_fall.cpp` | 120 |
