# 模型内部拆解 —— 从 impulse 结构体到 14 特征与 INT8 量化

> 配套 [四段物理机+NN混合判定_逐行代码走读](../06-系统集成/四段物理机+NN混合判定_逐行代码走读.md)：那篇讲**代码流程**，本篇讲**模型内部**——模型怎么被代码引用、14 个特征怎么来、INT8 量化是什么。
> 基于本项目实际生成的 `model-parameters/`（`impulse_999999_1`，项目 `fall_ws63_waist`）。

---

## 〇、NN 侧全景

```
600样本×2通道(|acc|,|gyro|) = 1200个原始数(3秒窗口)
   │ DSP: Flatten 块 —— 每通道算7个统计量
   ▼
14个特征 (2通道 × 7统计)
   │ INT8量化的小型全连接NN (TFLite Micro)
   ▼
2个概率: fall=?% , normal=?%
```

---

## 一、模型怎么被代码引用：impulse 结构体 + EI_CLASSIFIER 宏

Edge Impulse 导出模型时**自动生成**两样东西（你不用手写）：

### 1) `impulse_999999_1` —— 模型的"完整说明书"（运行期对象）
`model_variables.h` 里一个 `const ei_impulse_t`，把模型一切写全：
```c
const ei_impulse_t impulse_999999_1 = {
    .project_name = "fall_ws63_waist",
    .raw_sample_count = 600, .raw_samples_per_frame = 2,  // 输入 600×2
    .dsp_input_frame_size = 600*2,                        // =1200 原始数
    .frequency = 200, .interval_ms = 5,                   // 200Hz
    .nn_input_frame_size = 14,                            // DSP后 → 14特征喂NN
    .dsp_blocks = ...,          // 【DSP：特征提取】
    .learning_blocks = ...,     // 【NN 本身】
    .inferencing_engine = EI_CLASSIFIER_TFLITE,
    .label_count = 2, ...       // 类别 {"fall","normal"}
};
```
- `EI_Fall_Init` 里 `new (g_handle) ei_impulse_handle_t(&impulse_999999_1)` = 让 handle 指向这本说明书；
- `run_classifier(g_handle, ...)` 就**照着它跑**：输入 600×2 → 先 DSP → 再 NN → 输出 fall/normal。

### 2) `EI_CLASSIFIER_*` 宏 —— 同样的形状（编译期常量）
`model_metadata.h`：
```c
#define EI_CLASSIFIER_RAW_SAMPLE_COUNT       600
#define EI_CLASSIFIER_RAW_SAMPLES_PER_FRAME  2
#define EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE   (600*2)  // 1200
#define EI_CLASSIFIER_FREQUENCY              200
#define EI_CLASSIFIER_LABEL_COUNT            2
#define EI_CLASSIFIER_NN_INPUT_FRAME_SIZE    14
```
`ei_fall.cpp` 的缓冲区大小**引用这些宏**，不是硬编码：
```c
#define EI_FALL_FRAME    EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE   // 1200
#define EI_FALL_SAMPLES  EI_CLASSIFIER_RAW_SAMPLE_COUNT       // 600
#define EI_FALL_AXES     EI_CLASSIFIER_RAW_SAMPLES_PER_FRAME  // 2
static float g_ring[EI_FALL_FRAME];   // 环形缓冲=1200,来自模型
```
> ⭐ **模型元数据是"唯一真相源"**：代码形状由它决定。重训换窗口/轴数 → 重新导出头文件 → 代码自动跟上，不用手改。

---

## 二、DSP（Flatten）块：1200 → 14 怎么来的

本项目 DSP 是 **Flatten 类型**（`ei_dsp_config_flatten_t`），配置里对 **2 个通道**各算 **7 个统计量**（全 `true`）：
```c
ei_dsp_config_flatten_t = {
    ... axes = {0,1}(|acc|,|gyro|)...
    true, // average  均值
    true, // minimum  最小值
    true, // maximum  最大值
    true, // rms      均方根
    true, // stdev    标准差
    true, // skewness 偏度
    true, // kurtosis 峰度
};
```
```
|acc|  这3秒 → [均值,最小,最大,rms,标准差,偏度,峰度] = 7
|gyro| 这3秒 → [均值,最小,最大,rms,标准差,偏度,峰度] = 7
                                                  2×7 = 14 个特征
```

**Flatten = 丢掉逐点波形，只保留每通道这 3 秒的"统计画像"。** 7 个统计量各抓：

| 统计量 | 抓什么 | 对跌倒的意义 |
|---|---|---|
| average | 整体水平 | 静止≈1G，跌倒后姿态变 |
| min/max | 极值 | 失重(低)+ 冲击(高峰值) |
| rms | 能量 | 跌倒能量大 |
| stdev | 波动幅度 | 跌倒剧烈 |
| skewness | 分布偏斜 | 冲击让分布偏一侧 |
| kurtosis | 有多"尖" | 冲击是尖峰，峰度高 |

> **为什么不把 1200 原始数直接喂 NN？** 那样 NN 要很大很慢。用 14 个统计特征，一个**极小全连接网络**就够区分"跌倒 vs 正常"——又小又快，适合 MCU。这就是"特征工程 + 小模型"。
> `.nn_input_frame_size = 14` 正好 = DSP 输出 = NN 输入宽度。

---

## 三、NN 是什么

**NN = 神经网络 = 从数据学出来的分类模型**：输入 14 个特征 → 输出 fall/normal 两个概率。
- 结构：输入层(14) → 若干隐藏层 → 输出层(2)。每个神经元做"加权求和 + 偏置 + 激活"。
- **权重是训练学出来的**（从标注的跌倒/正常 CSV），不是人写规则。
- 类比：一个看过成千上万例子的"打分员"，给 14 条线索就打分"多像跌倒"。
- 本项目：**小型全连接网络，TFLite Micro，INT8 量化**，2 类输出。

---

## 四、INT8 量化：把模型压成整数

`impulse` 用 `EI_CLASSIFIER_TFLITE` 跑 **INT8 量化**模型。

**是什么**：NN 权重训练时是 float32；量化 = 把浮点(权重/激活)压成 **8 位整数(-128~127)**。

**怎么做**：用缩放系数 scale 把浮点范围映射到整数范围
```
真实值 ≈ int8值 × scale (+零点)     // 只存 int8 + scale,用时还原
```

**为什么**：
| 好处 | 说明 |
|---|---|
| 省内存 | float32→int8 = 体积 **缩到 1/4**（MCU Flash/RAM 紧张） |
| 更快 | 整数乘加比浮点快（MCU 无强 FPU 时尤甚） |
| 省电 | 整数运算功耗低 |

**代价**：精度略降（量化误差），但对二分类通常影响很小 —— 用一点精度换"能在 WS63 上跑得起、跑得快"。

> ⚠️ **量化 scale 是训练时按数据范围定死的** → 推理喂入的数值范围必须和训练一致（milli-g / centi-dps）。喂错量纲 → 映射到错误整数区间 → 结果全乱。这就是代码 `×1000 / ×100` 的原因。

---

## 五、一句话

> Edge Impulse 生成 **`impulse_999999_1`（模型说明书）+ `EI_CLASSIFIER_*` 宏（形状常量）**，代码引用它们、形状永远与模型对齐；**DSP Flatten 块**把 3 秒 1200 原始数按"每通道 7 统计 × 2 通道"压成 **14 特征**；这 14 特征喂给 **INT8 量化的小型全连接 NN**（省 4 倍内存、更快，精度损失可忽略，但喂入量纲须与训练一致），输出 fall/normal 两概率。
