# Edge Impulse 训练数据全过程记录（2026-05-07）

本文记录本项目在 Edge Impulse 上使用 SisFall 数据训练跌倒检测模型的完整过程，包括数据来源、标签设计、上传方式、Impulse 配置、训练评估、部署导出，以及每个关键设置为什么要这样选。本文与部署调试记录配套使用：训练侧决定模型参数，板端代码必须严格匹配这些参数。

---

## 1. 训练目标

本次训练目标不是做完整人体动作识别，而是面向比赛演示和嵌入式实时报警，训练一个二分类模型：

| 类别 | 含义 | 板端最终用途 |
|---|---|---|
| `normal` | 正常活动或非跌倒状态 | 不报警 |
| `fall_risk` | 跌倒、接近跌倒或高风险剧烈动作 | 进入告警候选，再经过物理门控确认 |

选择二分类的原因：

1. WS63 端侧资源有限，二分类模型更轻量。
2. 比赛目标是“是否需要报警”，不是识别所有动作类型。
3. SisFall 原始动作类别较多，如果直接做多分类，板端误判解释成本更高。
4. 二分类更容易与 `SLE SOS` 告警链路对应。

---

## 2. 数据来源与本地目录

原始数据目录：

```text
D:\Download_1\Three Classes
```

该目录中包含 SisFall 相关动作数据。训练时没有直接将全部原始类别上传，而是按最终业务目标归并：

```text
normal
fall_risk
```

本地曾使用脚本将 SisFall 数据转换为 Edge Impulse 可上传的 CSV：

```powershell
powershell -ExecutionPolicy Bypass -File D:\fbb_ws63\fbb_ws63-master\src\tools\sisfall_to_ei_csv.ps1 `
  -OutputDir D:\Download_1\ei_csv_binary_balanced_v2 `
  -BinaryFallRisk `
  -BinaryTrainNormalLimit 15000 `
  -BinaryTrainFallRiskCopies 5
```

这些参数的含义：

| 参数 | 作用 | 原因 |
|---|---|---|
| `-BinaryFallRisk` | 将数据转换为二分类标签 | 与比赛报警目标一致 |
| `-BinaryTrainNormalLimit 15000` | 限制 normal 训练样本数量 | 防止 normal 类过多压制 fall_risk |
| `-BinaryTrainFallRiskCopies 5` | 对 fall_risk 做复制增强 | 缓解跌倒类样本数量不足 |
| `-OutputDir` | 输出 Edge Impulse CSV 文件 | 便于分批上传和复查 |

注意：复制增强不是增加新的真实动作，只是改善训练阶段类别权重。最终可靠性仍依赖板端实测验证。

---

## 3. CSV 格式要求

Edge Impulse 上传的时序 CSV 必须包含时间戳和 6 轴传感器数据。本项目采用 6 轴输入：

```csv
timestamp,accX,accY,accZ,gyrX,gyrY,gyrZ
0,0.01,0.02,1.00,0.00,0.00,0.00
5,0.02,0.02,0.99,0.01,0.00,0.00
10,0.02,0.01,1.01,0.00,0.01,0.00
```

关键要求：

| 字段 | 要求 | 原因 |
|---|---|---|
| `timestamp` | 单调递增，单位 ms | Edge Impulse 根据时间轴识别采样率 |
| `accX/Y/Z` | 加速度，单位按训练转换保持一致 | 板端 MPU6050 输出为 g |
| `gyrX/Y/Z` | 陀螺仪，需与训练尺度一致 | 板端最终使用 `dps / 250.0f` 映射到模型尺度 |
| 采样间隔 | `5 ms` | 对应 `200 Hz` |
| 每行轴数 | 6 轴 | 必须匹配模型 `RAW_SAMPLES_PER_FRAME = 6` |

如果 CSV 缺轴、时间戳不连续、窗口长度不足或列名不一致，Edge Impulse 可能会上传成功但最终可用样本数减少。

---

## 4. Edge Impulse 上传：Label 与 Category 的区别

在 `Data acquisition -> Upload` 页面，两个概念必须区分：

| 页面字段 | 应该填写 | 说明 |
|---|---|---|
| `Label` | `normal` 或 `fall_risk` | 这是模型要学习的类别 |
| `Category` | `Training` 或 `Testing` | 这是数据用途，不是类别 |

正确示例：

```text
Label: normal
Category: Training
```

```text
Label: fall_risk
Category: Testing
```

错误示例：

```text
Label: training
Label: testing
```

原因：如果把 `training` / `testing` 当成 label，模型会学习错误类别，最终部署端标签也会不一致。

---

## 5. 为什么上传 14670 个文件后平台只显示 6487 个

训练过程中遇到过：本地 `fall_risk` 上传数量约 `14670`，但 Edge Impulse 最终显示只有 `6487` 左右。这个现象不是单一原因导致，可能来自以下机制：

1. **CSV 不满足平台解析规则**：列名、时间戳、空行或非法值会导致样本丢弃。
2. **样本长度不足**：如果一个文件不足以切出完整窗口，平台不会计入有效训练样本。
3. **切窗后统计口径不同**：本地统计的是文件数，平台显示可能是有效 sample 或有效 window。
4. **浏览器批量上传中断或限流**：大量文件上传时，部分文件可能失败但没有明显提示。
5. **平台自动过滤重复或异常样本**：重复数据、空数据、异常时间轴可能被过滤。
6. **训练/测试分类不同**：上传到 Testing 的不会计入 Training 数量。

处理原则：

- 不只看本地文件数，要看 Edge Impulse `Data acquisition` 中最终可用样本数。
- 上传后随机打开样本曲线，检查 6 轴是否都有数据。
- 分批上传 fall_risk，避免一次性上传过多文件。
- 如果数量异常，先抽查 CSV 文件头、时间戳、样本长度。

---

## 6. Impulse Design 配置

本项目最终使用的 Impulse 配置应与板端一致：

| 模块 | 配置 |
|---|---|
| Input block | Time series data |
| Window size | 约 `1280 ms` |
| Sampling rate | `200 Hz` |
| Raw sample count | `256` |
| Axes | `accX, accY, accZ, gyrX, gyrY, gyrZ` |
| Processing block | Spectral Analysis |
| Learning block | Classification |
| Output labels | `fall_risk`, `normal` |

### 6.1 为什么窗口是 256 samples / 1.28 s

板端最终模型元数据为：

```text
EI_CLASSIFIER_RAW_SAMPLE_COUNT = 256
EI_CLASSIFIER_RAW_SAMPLES_PER_FRAME = 6
EI_CLASSIFIER_INTERVAL_MS = 5
EI_CLASSIFIER_FREQUENCY = 200
```

因此窗口时长为：

```text
256 samples * 5 ms = 1280 ms
```

选择这个窗口的理由：

1. 跌倒动作通常包含“失重/快速运动/撞击/翻转”连续过程，窗口太短会截断动作。
2. 窗口太长会增加模型输入和推理延迟，不适合端侧实时报警。
3. `1.28 s` 对比赛演示是可接受的实时性折中。
4. 板端采样循环为 `5 ms`，正好匹配 `200 Hz`。

### 6.2 为什么使用 6 轴

只用加速度可以识别冲击，但容易把快速坐下、放下板子等动作误判为跌倒。加入陀螺仪可以观察旋转特征：

- 跌倒通常伴随身体姿态快速变化。
- 陀螺仪能补充加速度无法表达的旋转信息。
- `fall_risk` 与普通冲击动作更容易区分。

因此训练和部署都使用：

```text
accX + accY + accZ + gyrX + gyrY + gyrZ
```

板端如果只喂 3 轴，模型输入维度会不匹配或特征分布严重错误。

### 6.3 为什么使用 Spectral Analysis

选择 Spectral Analysis 的理由：

1. 跌倒动作包含明显频域变化，例如冲击和快速旋转带来的高频能量。
2. 频域特征比直接原始时序更压缩，板端 NN 输入为 `222`，远小于原始 `1536`。
3. 对轻量化模型更友好，适合 WS63 这类嵌入式平台。

最终模型元数据证明：

```text
EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE = 1536
EI_CLASSIFIER_NN_INPUT_FRAME_SIZE = 222
```

说明原始 6 轴窗口经过 DSP 后被压缩为 222 维神经网络输入。

---

## 7. Spectral Features 页面处理

在 `Spectral features` 页面应执行：

1. 确认输入轴包含全部 6 轴。
2. 点击 `Save parameters`。
3. 点击 `Generate features`。
4. 查看 Feature explorer 中 `normal` 与 `fall_risk` 是否有一定分离。

判断依据：

- 如果两类完全混在一起，模型很难学到稳定边界。
- 如果 `fall_risk` 明显分散或与 `normal` 有部分区分，二分类模型有训练价值。
- 如果数据点数量与上传数量明显不符，应回到 Data acquisition 检查 CSV。

不要在这一步只追求页面图好看。关键是后续板端验证能否稳定输出 `status`。

---

## 8. Classifier 训练配置

训练页面建议配置：

| 参数 | 建议 |
|---|---|
| Training cycles / Epochs | 50 到 100 起步 |
| Learning rate | `0.001` 起步 |
| Validation split | 平台默认或 20% 左右 |
| Model type | Classification |
| Output classes | `fall_risk`, `normal` |
| Quantization | Deployment 阶段使用 INT8 |

训练判断原则：

1. 不只看 overall accuracy，要看 confusion matrix。
2. 对跌倒检测，`fall_risk` 的召回率比 normal 精确率更关键。
3. 但如果 `normal` 大量误判为 `fall_risk`，比赛演示会频繁误报，也不可接受。
4. 如果训练页面效果很好但板端静止仍 `ai_fall=100%`，说明训练数据和板端真实数据分布不一致。

本次最终结论就是：平台模型可部署，但模型原始输出在板端存在 domain mismatch，因此必须加物理门控。

---

## 9. Model Testing 的使用原则

训练完成后应在 `Model testing` 页面运行测试集评估。重点看：

| 指标 | 判断 |
|---|---|
| `fall_risk` recall | 越高越不漏报 |
| `normal` precision | 越高越少误报 |
| Confusion matrix | 看两类互相混淆情况 |
| 测试集来源 | 必须与训练集隔离 |

注意：Edge Impulse 页面测试准确率不能直接等同于板端真实准确率。原因：

1. 测试集仍来自 SisFall 转换数据，和 MPU6050 实机数据不同。
2. 板端传感器安装方向、量程、滤波和噪声不同。
3. 板端推理使用 INT8 / EON，与页面浮点训练环境有差异。
4. 板端输入还涉及采样时序、I2C 抖动和实时滑动窗口。

因此最终判定必须以串口实测为准。

---

## 10. Deployment 导出

Deployment 页面选择：

```text
C++ Library
```

建议开启：

```text
Enable EON Compiler
INT8 quantized model
```

理由：

1. C++ Library 方便集成进 WS63 LiteOS 工程。
2. EON 能减小模型体积和内存占用。
3. INT8 更适合嵌入式端侧推理。
4. WS63 工程可以直接编译 `edge-impulse-sdk`、`model-parameters`、`tflite-model`。

下载解压后，关键目录为：

```text
edge-impulse-sdk/
model-parameters/
tflite-model/
```

在 WS63 工程中对应位置：

```text
application\samples\my_demo\fall_detect\src\edge-impulse-sdk
application\samples\my_demo\fall_detect\src\model-parameters
application\samples\my_demo\fall_detect\src\tflite-model
```

---

## 11. 导出模型与板端代码一致性检查

每次从 Edge Impulse 重新下载模型后，必须检查：

```text
application\samples\my_demo\fall_detect\src\model-parameters\model_metadata.h
application\samples\my_demo\fall_detect\src\model-parameters\model_variables.h
```

重点确认：

```c
#define EI_CLASSIFIER_RAW_SAMPLE_COUNT 256
#define EI_CLASSIFIER_RAW_SAMPLES_PER_FRAME 6
#define EI_CLASSIFIER_INTERVAL_MS 5
#define EI_CLASSIFIER_FREQUENCY 200
```

并确认 fusion string：

```text
accX + accY + accZ + gyrX + gyrY + gyrZ
```

如果这些值变化，板端必须同步修改：

- 采样周期 `FALL_DETECT_LOOP_DELAY_MS`
- 输入轴数量
- 滑动窗口长度
- `features_buffer` 填充逻辑
- MPU6050 采样率配置

否则会出现推理结果极端、`0%/100%` 跳变或误报。

---

## 12. 训练设置与板端代码的对应关系

| Edge Impulse 设置 | 板端对应实现 |
|---|---|
| 采样率 `200 Hz` | `osDelay(5 ms)` + MPU6050 `SMPLRT_DIV=0x04` |
| 6 轴输入 | `AI_Feed_And_Predict_6Axis(ax, ay, az, gx, gy, gz)` |
| `256 samples` | `features_buffer[1536]` |
| 6 轴每帧 | 每次写入 6 个 float |
| Spectral Analysis | 调用 `run_classifier()` 内部 DSP |
| 标签 `fall_risk`, `normal` | 按字符串解析 `result.classification[i].label` |
| C++ Library | 集成 EI SDK 源码到 CMake |
| EON / INT8 | 使用导出的 `tflite-model` |

这个对应关系是部署成功的核心。训练侧和板端只要有一个参数不一致，结果就不可信。

---

## 13. 为什么最终没有继续盲目提高训练精度

训练过程中曾尝试继续提升精度，但部署到板端后提升不明显。原因判断如下：

1. 当前主要瓶颈不是神经网络训练轮数，而是训练数据与板端实测数据分布不一致。
2. 静止状态下 `ai_fall` 仍可能接近 `100%`，说明模型学到的边界不能直接迁移到 MPU6050 实机数据。
3. 继续在同一批 SisFall 转换数据上训练，可能只会提高平台测试集分数，不一定提高板端效果。
4. 比赛当前更需要稳定演示，因此优先采用物理门控和连续确认控制误报。

后续如果要真正提升模型，应采集 WS63 + MPU6050 板端真实数据重新训练，而不是只在 SisFall 上继续调参。

---

## 14. 推荐复现流程

从零复现时按以下顺序操作：

1. 本地将 SisFall 数据转换为 6 轴、200 Hz、带 timestamp 的 CSV。
2. 在 Edge Impulse `Data acquisition -> Upload` 上传 CSV。
3. `Label` 填 `normal` 或 `fall_risk`，`Category` 选择 `Training` 或 `Testing`。
4. 在 `Create impulse` 中选择 Time series 输入。
5. 设置窗口为约 `1280 ms`，输入轴为 6 轴。
6. 添加 `Spectral Analysis` processing block。
7. 添加 `Classification` learning block。
8. 在 Spectral features 页面 `Save parameters` 并 `Generate features`。
9. 在 Classifier 页面训练模型。
10. 在 Model testing 页面查看混淆矩阵，不只看总准确率。
11. 在 Deployment 页面选择 `C++ Library`，开启 EON，导出 INT8 模型。
12. 将 `edge-impulse-sdk`、`model-parameters`、`tflite-model` 更新到 WS63 工程。
13. 编译并烧录固件。
14. 串口确认模型参数：`256 samples, 6 axes, 200 Hz`。
15. 做静止、走动、快速拿起、模拟跌倒、连续晃动五类实机测试。

---

## 15. 最终训练侧结论

本次 Edge Impulse 训练过程的有效结论：

1. 使用二分类 `normal` / `fall_risk` 是合理的，符合比赛报警目标。
2. 必须使用 6 轴输入，不能只用加速度。
3. 训练采样率、窗口长度和板端采样必须严格一致。
4. Spectral Analysis 能压缩输入并保留冲击/旋转频域特征，适合端侧部署。
5. 平台测试结果只能作为参考，最终必须以 WS63 串口实测为准。
6. 当前模型可以配合物理门控用于比赛演示，但产品级方案应使用板端自采数据重训。
