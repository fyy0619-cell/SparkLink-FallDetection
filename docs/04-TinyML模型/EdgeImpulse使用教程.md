# Edge Impulse使用教程

## Edge Impulse是什么

Edge Impulse是一个面向嵌入式设备的机器学习平台，支持：
- 在线数据采集与标注
- 特征工程设计
- 神经网络训练
- 模型量化（INT8）并导出为C++库

**官网**：https://studio.edgeimpulse.com（免费注册）

---

## 工作流程

```
上传数据 → 设计特征提取 → 训练模型 → 量化优化 → 导出C++库 → 集成到SDK
```

---

## 步骤一：准备数据

将你的CSV数据组织成Edge Impulse接受的格式：

```csv
timestamp,accX,accY,accZ
0,0.12,-0.05,0.98
10,0.13,-0.04,0.97
...
```

- `timestamp`：毫秒，采样间隔要一致（如50Hz → 间隔20ms）
- 标注：`normal`（正常）和 `fall`（跌倒）两类

---

## 步骤二：Impulse设计

| 组件 | 推荐配置 |
|------|----------|
| 输入块 | Time series，窗口大小2000ms，步长200ms |
| 处理块 | Spectral Analysis（频域特征，效果好） |
| 学习块 | Classification（神经网络分类） |

> **为什么选Spectral Analysis？**  
> 跌倒动作在频域有明显特征（高频分量突增），比直接用原始时序数据更容易区分。

---

## 步骤三：训练

- Epochs：建议50-100
- 学习率：0.001
- 验证集比例：20%
- 目标：验证精度 > 90%，混淆矩阵中fall类召回率 > 95%

---

## 步骤四：量化与导出

1. 进入 `Deployment` → 选择 `C++ Library`
2. 开启 `Enable EON Compiler`（减小模型体积）
3. 量化选 `INT8`（适合嵌入式推理）
4. 下载 `.zip` 解压，得到：

```
ei-fall-detection/
├── edge-impulse-sdk/        # EI推理引擎（C++）
├── model-parameters/        # 模型参数
│   ├── dsp_blocks_params.h
│   └── model_metadata.h
├── tflite-model/            # 量化后的TFLite模型
└── CMakeLists.txt
```

---

## 步骤五：集成到WS63 SDK

1. 将解压内容复制到 `src/tinyml/`
2. 在 SDK 的 CMakeLists.txt 中引用：

```cmake
add_subdirectory(src/tinyml)
target_link_libraries(${TARGET} edge_impulse)
```

3. 在应用代码中调用推理：

```cpp
#include "edge-impulse-sdk/classifier/ei_run_classifier.h"

// 准备100帧×3轴的特征数组
float features[EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE];

// 填充features...（从MPU6050读取）

// 运行推理
ei_impulse_result_t result = {0};
signal_t signal;
numpy::signal_from_buffer(features, EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE, &signal);
run_classifier(&signal, &result, false);

// 解析结果
for (int i = 0; i < EI_CLASSIFIER_LABEL_COUNT; i++) {
    if (result.classification[i].value > 0.8f) {
        // 检测到跌倒
    }
}
```

---

## 常见问题

**Q: 打印-22错误？**  
A: 内存分配失败。增大LiteOS配置中 `OS_SYS_MEM_SIZE`，至少保留512KB给推理引擎。

**Q: 推理结果全是0.5/0.5？**  
A: 特征提取参数（采样率、窗口大小）与训练时不一致，检查两端参数是否完全匹配。

**Q: 模型在板上精度远低于训练精度？**  
A: 1）检查INT8量化误差；2）检查自采数据是否有代表性；3）加入SisFall数据增强泛化能力。
