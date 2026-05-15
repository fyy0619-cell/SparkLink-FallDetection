# Edge Impulse 模型部署小白指南

本文面向第一次接触「机器学习模型 + 嵌入式工程」的同学。目标是把一件事讲透：

> 你在 Edge Impulse 网站上训练出来的跌倒检测模型，是怎么**一步一步**变成 WS63 开发板里能跑的代码的？

读完你应该能回答三个问题：

1. Edge Impulse 到底给了我哪些文件，每个文件是干嘛的？
2. 这些文件是怎么被「塞进」WS63 工程并参与编译的？
3. 一个传感器数据从产生到被判定为「跌倒」，中间经历了什么？

---

## 0. 先建立几个直觉

在看代码之前，先用大白话把名词解释清楚，否则后面会一直卡。

| 名词 | 大白话解释 |
| --- | --- |
| **Edge Impulse（EI）** | 一个在线网站。你上传传感器数据、点几下鼠标，它就帮你训练好一个 AI 模型，并能导出成 C/C++ 代码。 |
| **模型（Model）** | 一个「数学函数」。喂给它一段传感器数据，它吐出「这是跌倒的概率是 95%」这样的结果。 |
| **Impulse（脉冲/处理流水线）** | EI 里的专有名词。指「原始数据 → 特征提取(DSP) → 神经网络 → 分类结果」这一整条流水线。不是只有神经网络。 |
| **DSP（数字信号处理）** | 推理前的「预处理」。原始的 1536 个加速度/角速度数字不会直接喂给神经网络，而是先做频谱分析(FFT)，压缩成 222 个「特征」。 |
| **推理（Inference）** | 让训练好的模型「跑一次」，给出预测结果。和「训练」相对：训练是学习，推理是使用。 |
| **TensorFlow Lite Micro（TFLite Micro）** | 谷歌的一个超小型 AI 运行库，专门让神经网络能在单片机这种「内存只有几十 KB」的设备上跑起来。 |
| **EON Compiler** | EI 的一个优化器。它把神经网络直接「编译成 C++ 代码」，而不是一个需要解析的模型文件，这样更省内存、更快。 |
| **量化（Quantization）** | 把模型里的 32 位浮点数压成 8 位整数以省内存。**你这个模型没有量化**（用的是 float32），后面会看到。 |

一句话总览：

```text
                Edge Impulse 网站                          WS63 开发板
   ┌───────────────────────────────────┐      ┌──────────────────────────────────┐
   │  采集数据 → 设计 Impulse → 训练     │      │  MPU6050 传感器 → 你写的胶水代码   │
   │         → 导出 C++ library         │ ───▶ │   → Edge Impulse SDK → 出结果      │
   └───────────────────────────────────┘  拷贝  └──────────────────────────────────┘
            （在浏览器里完成）              文件        （在单片机里实时运行）
```

---

## 1. 你的模型到底长什么样

所有模型参数都写死在一个自动生成的头文件里：
`application/samples/my_demo/fall_detect/src/model-parameters/model_metadata.h`

把关键参数读出来，做成一张表（你不需要背，知道去哪查就行）：

| 参数（宏名） | 值 | 含义 |
| --- | --- | --- |
| `EI_CLASSIFIER_PROJECT_ID` | `985336` | 你的 EI 项目编号 |
| `EI_CLASSIFIER_PROJECT_NAME` | `"latest_fall"` | 项目名 |
| `EI_CLASSIFIER_SENSOR` | `SENSOR_FUSION` | 用的是「多传感器融合」 |
| `EI_CLASSIFIER_FUSION_AXES_STRING` | `accX+accY+accZ+gyrX+gyrY+gyrZ` | 6 个轴：3 轴加速度 + 3 轴角速度 |
| `EI_CLASSIFIER_RAW_SAMPLES_PER_FRAME` | `6` | 每个采样点有 6 个数 |
| `EI_CLASSIFIER_RAW_SAMPLE_COUNT` | `256` | 一个「窗口」是 256 个采样点 |
| `EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE` | `256 × 6 = 1536` | 喂给流水线的原始数字总数 |
| `EI_CLASSIFIER_FREQUENCY` | `200` | 训练数据是 200 Hz 采的（每秒 200 个采样点） |
| `EI_CLASSIFIER_INTERVAL_MS` | `5` | 即每 5 ms 一个采样点（1000 / 200） |
| `EI_CLASSIFIER_NN_INPUT_FRAME_SIZE` | `222` | DSP 之后剩 222 个特征喂给神经网络 |
| `EI_CLASSIFIER_LABEL_COUNT` | `2` | 2 个类别 |
| 类别名 | `fall_risk` / `normal` | 「有跌倒风险」/「正常」 |
| `EI_CLASSIFIER_INFERENCING_ENGINE` | `TFLITE` | 用 TFLite Micro 跑神经网络 |
| `EI_CLASSIFIER_COMPILED` | `1` | 用了 EON Compiler（编译成 C++ 代码） |
| `EI_CLASSIFIER_QUANTIZATION_ENABLED` | `0` | **没量化**，是 float32 模型 |
| `EI_CLASSIFIER_TFLITE_LARGEST_ARENA_SIZE` | `4192` | 神经网络运行时需要的临时内存（约 4 KB） |

直觉理解：**这个模型每次「看」的是 256 个采样点（约 1.28 秒）的一段动作，6 个轴，判断这 1.28 秒里人是「正常」还是「有跌倒风险」。**

窗口还会被切成 4 片（`EI_CLASSIFIER_SLICES_PER_MODEL_WINDOW = 4`），每片 64 个采样点 —— 这一点在第 6 节讲「滑动窗口」时会用到。

---

## 2. 部署涉及的文件分三类

打开 `application/samples/my_demo/fall_detect/`，你会看到三类文件。**分清楚谁是谁，是看懂部署的关键。**

```text
fall_detect/
├── CMakeLists.txt          ← 第三类：构建脚本
├── Kconfig                 ← 第三类：菜单开关
├── inc/
│   ├── ai_model.h          ← 第二类：你写的胶水代码（头文件）
│   ├── mpu6050.h           ← 第二类：传感器驱动头文件
│   └── ...
└── src/
    ├── edge-impulse-sdk/   ← 第一类：EI 导出的（SDK 引擎，别动）
    ├── model-parameters/   ← 第一类：EI 导出的（模型参数）
    ├── tflite-model/       ← 第一类：EI 导出的（编译后的神经网络）
    ├── ai_model.cpp        ← 第二类：你写的胶水代码（核心！）
    ├── mpu6050.c           ← 第二类：传感器驱动
    ├── main_task.c         ← 第二类：主循环，把传感器和 AI 串起来
    └── CMakeLists.txt      ← 第三类：构建脚本
```

### 第一类：Edge Impulse 自动导出的（你**不要手改**）

从 EI 网站下载的 zip 解压后就这三个文件夹，原样拷进来即可：

| 文件夹 | 里面是什么 | 关键文件 |
| --- | --- | --- |
| `edge-impulse-sdk/` | EI 的「运行引擎」。包含分类器框架、DSP 算法、裁剪版 TensorFlow、CMSIS 数学库、各平台适配层。**几百个文件，是死的库**。 | `classifier/ei_run_classifier.h` |
| `model-parameters/` | 描述「你这个模型」的参数。 | `model_metadata.h`（宏定义表）、`model_variables.h`（模型结构体） |
| `tflite-model/` | 你训练出来的**神经网络本体**，已被 EON Compiler 编译成 C++ 代码。 | `tflite_learn_985336_3_compiled.cpp`（373 KB，里面全是权重数字和计算图） |

> `model_variables.h` 里有个最重要的结构体 `impulse_985336_1`（约第 162 行）。它像一张「装配图」，把 DSP 配置、数据归一化参数、神经网络入口函数全部组装在一起。后面调用 `run_classifier()` 时，传进去的就是它。

> 你还会看到 `model-parameters.bak_20260507_201051/` 和 `tflite-model.bak_...` 这种带 `.bak` 的文件夹 —— 那是**上一个版本的模型**（项目编号 945439）。每次重新训练换模型，本质就是替换这三个文件夹，旧的备份留着回退用。

### 第二类：你自己写的「胶水代码」（部署的真正工作量）

EI 的 SDK 是 C++ 写的，而 WS63 工程主体是 C，并且 EI 默认假设你跑在 Linux/Arduino 上。**把两者粘起来的代码，需要你自己写**：

| 文件 | 作用 |
| --- | --- |
| `inc/ai_model.h` | 给 C 代码用的「简化接口」。只暴露 5 个函数，藏掉所有 C++ 细节。 |
| `src/ai_model.cpp` | **部署的核心**。用 C++ 写，负责内存管理、攒数据、调用 `run_classifier()`、解析结果。 |
| `src/mpu6050.c` | MPU6050 传感器驱动，通过 I2C 读出 6 轴数据。 |
| `src/main_task.c` | 主任务循环：读传感器 → 喂给 AI → 拿到结果 → 报警。 |

### 第三类：构建与配置（让编译器认识这些新文件）

| 文件 | 作用 |
| --- | --- |
| `src/CMakeLists.txt` | 告诉 CMake：把这些 .c/.cpp 都编进去，并且要开 C++14、关异常。 |
| `Kconfig` | 在 `menuconfig` 图形菜单里加一个「是否启用跌倒检测」的开关。 |

---

## 3. 一步一步部署流程

下面是「从零把一个 EI 模型部署进来」的完整步骤。你的工程已经做完了，这里是把**已经发生的事**讲清楚，顺便让你以后能自己复现。

### Step 0 —— 在 Edge Impulse 网站训练并导出

1. 在 EI Studio 里采集数据（戴着 MPU6050 录「正常活动」和「跌倒」两类动作）。
2. 设计 Impulse：选「Spectral Analysis」做 DSP，选一个分类神经网络。
3. 训练，看准确率，满意为止。
4. 进入 **Deployment** 页面，选择 **C++ library**，点 **Build**，下载 zip。
   - 注意：因为想要 EON Compiler 的省内存效果，导出时勾了「EON Compiler」+「TensorFlow Lite」，所以 `EI_CLASSIFIER_COMPILED = 1`。

> ⚠️ 小白最容易错的地方：**采集训练数据时的传感器量程、采样率、单位，必须和开发板上实际跑的时候一致**。你训练时是 200 Hz、加速度单位是 g，那么板子上也必须是 200 Hz、单位 g。否则模型「看到的世界」和训练时不一样，准确率会崩。这条贯穿后面 Step 4 和 Step 5。

### Step 1 —— 把导出的三个文件夹放进工程

把 zip 里的 `edge-impulse-sdk/`、`model-parameters/`、`tflite-model/` 三个文件夹，整个拷到：

```
application/samples/my_demo/fall_detect/src/
```

到这一步，模型的「素材」就进工程了。但它们现在只是一堆躺着的文件，**还不会被编译、也没人调用**。后面 Step 2~6 才是真正的「部署」。

### Step 2 —— 写 C++ 封装 `ai_model.cpp`（核心难点）

这是整个部署最难、最值得细看的一步。文件：`src/ai_model.cpp`，对外接口：`inc/ai_model.h`。

`ai_model.h` 只暴露 5 个 C 函数（注意用 `extern "C"` 包起来，这样 C 代码能调用 C++ 编译出来的函数）：

```c
void AI_Model_Init(void);                                    // 初始化
int  AI_Feed_And_Predict_6Axis(float ax,ay,az,gx,gy,gz);     // 喂一个采样点，可能返回结果
int  AI_Get_Last_Fall_Risk_Percent(void);                    // 取上次「跌倒概率」
// ...
```

`ai_model.cpp` 里解决了 4 个嵌入式上的「坑」，逐个看：

#### 坑 1：内存从哪来？——自己造一个内存池

EI 的 SDK 在推理时需要动态申请内存（`malloc`）。但单片机上直接用系统 `malloc` 容易内存碎片、申请失败。解决办法是**自己开一块固定大小的静态内存当「专用内存池」**：

```cpp
#define AI_POOL_SIZE (40 * 1024)                       // 划 40 KB
static uint8_t ai_custom_heap[AI_POOL_SIZE];           // 这块内存只给 AI 用

void *ei_malloc(size_t size) { ... LOS_MemAlloc(ai_custom_heap, ...) ... }
void  ei_free(void *ptr)     { ... LOS_MemFree(ai_custom_heap, ...) ... }
```

`ei_malloc / ei_calloc / ei_free` 是 EI SDK 规定的「钩子函数」——SDK 内部要内存时就调它们。我们重写这三个函数，让 AI 的所有内存申请都落在 `ai_custom_heap` 这 40 KB 里，和系统内存隔离开。`AI_Model_Init()` 里用 LiteOS 的 `LOS_MemInit()` 把这块池子初始化好。

（代码里还做了 32 字节对齐，因为某些数学运算要求内存地址对齐，这是细节，知道有这回事即可。）

#### 坑 2：C++ 全局对象没人初始化——用 placement new 手动建

EI 生成的 `model_variables.h` 里有个全局对象 `ei_default_impulse`。正常 PC 程序启动时，C++ 运行时会自动「构造」所有全局对象。但 **WS63 开机流程不保证会运行 C++ 全局构造函数**，直接用 `ei_default_impulse` 可能拿到一个没初始化的烂对象。

解决办法（`get_ai_impulse_handle()` 函数）：自己留一块内存，第一次用的时候用「placement new」手动在上面构造对象：

```cpp
static uint8_t handle_storage[sizeof(ei_impulse_handle_t)];
new (handle) ei_impulse_handle_t(&impulse_985336_1);   // 手动构造，指向第 1 节说的「装配图」
```

#### 坑 3：神经网络一次要 256 个采样点——攒一个「滑动窗口」

主循环每次只读到**一个**采样点（6 个数）。但模型一次要 256 个采样点（1536 个数）。所以要先攒够：

```cpp
static float features_buffer[1536];   // 攒数据的缓冲区
static int   feature_index = 0;       // 攒到哪了
```

`AI_Feed_And_Predict_6Axis()` 每次被调用，就把 6 个数塞进 `features_buffer`：
- 没攒满 1536 个 → 直接返回 `-1`（意思是「还没结果，再喂」）。
- 攒满了 → 触发一次推理（见坑 4），然后**滑动窗口**：丢掉最旧的 384 个数（`SLIDE_STEP = 64 × 6`），保留后 1152 个，下次只要再攒 384 个就能再推理一次。这样不用每次都从零攒，结果更连续。

#### 坑 4：真正调用模型——`run_classifier()`

窗口攒满后：

```cpp
signal_t features_signal;
numpy::signal_from_buffer(features_buffer, 1536, &features_signal);   // 把数组包装成 EI 要的 signal
ei_impulse_result_t result = {0};
run_classifier(get_ai_impulse_handle(), &features_signal, &result, false);  // ★ 跑整条流水线
```

`run_classifier()` 是 EI SDK 的总入口。它内部依次做了：**DSP（频谱分析，1536 个数 → 222 特征） → 标准化（StandardScaler 归一化） → 神经网络推理（222 → 2 个概率） → 输出**。

结果在 `result.classification[]` 里，按类别名取出来：

```cpp
for (i = 0; i < EI_CLASSIFIER_LABEL_COUNT; i++) {
    if (strcmp(result.classification[i].label, "fall_risk") == 0)
        fall_risk_prob = result.classification[i].value;   // 0.0 ~ 1.0
}
```

#### 额外一层：物理规则「门控」+ 连续确认（降低误报）

光信任神经网络容易误报（比如快速坐下也可能被判成跌倒）。所以 `ai_model.cpp` 在模型结果之外又加了一道「物理保险」：

- `get_window_motion_stats()` 统计这个窗口里的加速度峰值、自由落体特征、角速度峰值。
- 只有「神经网络说是跌倒」**且**「物理特征也像跌倒（先失重再撞击 / 剧烈旋转+冲击）」才算数。
- 还要求**连续 2 个窗口**都满足（`FALL_CONFIRM_WINDOWS = 2`）才最终确认。

这一层不是 EI 给的，是工程里为了实际可用补的业务逻辑。`AI_Feed_And_Predict_6Axis()` 最终返回 `1`（确认跌倒）/ `0`（正常）/ `-1`（窗口还没满）。

### Step 3 —— 改 `CMakeLists.txt` 让编译器接纳这些文件

文件：`src/CMakeLists.txt`。EI 的 SDK 不能直接编译进 WS63，需要几处改动：

1. **收集源码**：`file(GLOB_RECURSE APP_SRCS "*.c" "*.cpp" "*.cc")` —— 递归把所有源码（包括 EI SDK）都收进来。
2. **剔除不需要的平台适配**：EI SDK 自带 arduino、stm32、mbed 等十几个平台的适配代码，WS63 用不上。CMake 里用 `list(REMOVE_ITEM ...)` 把 `edge-impulse-sdk/porting/` 下 arduino/android/mbed/stm32... 全删掉，**只留 `porting/posix/`**（POSIX 适配在 LiteOS 上能用）。
3. **切换到 C++14、关掉异常**：EI SDK 是 C++，所以把编译标准从 `gnu99` 换成 `c++14`；又因为单片机不支持 C++ 异常，加 `-fno-exceptions -fno-rtti`。
4. **加宏定义**强制 EI 用静态内存、关掉用不上的加速库：
   ```cmake
   add_compile_definitions(
       EI_CLASSIFIER_ALLOCATION_STATIC=1      # 配合坑 1 的静态内存池
       EI_CLASSIFIER_TFLITE_ENABLE_CMSIS_NN=0
       EIDSP_USE_CMSIS_DSP=0)
   ```
5. **加头文件搜索路径**：把 `model-parameters`、`tflite-model` 目录加进 `PUBLIC_HEADER`，否则 `#include "model-parameters/model_metadata.h"` 会找不到。

### Step 4 —— 传感器驱动 `mpu6050.c`：让真实数据「长得和训练数据一样」

文件：`src/mpu6050.c`。这一步最容易被小白忽略，但**直接决定准确率**。

`MPU6050_Init()` 里对传感器寄存器的配置，是刻意去**对齐 EI 模型的训练条件**的：

```c
mpu6050_write_reg(MPU6050_REG_SMPLRT_DIV, 0x04);  // 1kHz/(1+4) = 200 Hz —— 对齐模型的 200 Hz
mpu6050_write_reg(MPU6050_REG_ACCEL_CFG, 0x08);   // 加速度 ±4 g
mpu6050_write_reg(MPU6050_REG_GYRO_CFG, 0x08);    // 角速度 ±500 dps
mpu6050_write_reg(MPU6050_REG_CONFIG, 0x03);      // 低通滤波 ~44 Hz，滤掉抖动毛刺
```

`MPU6050_Read_Accel_Gyro()` 把传感器读出来的「原始整数」换算成**带物理单位的浮点数**：

```c
*ax = (float)ax_raw / 8192.0f;        // ±4g 量程下，8192 个数 = 1 g  →  得到「g」
*gx = (float)gx_raw / 65.5f - offset; // ±500dps 量程下，65.5 个数 = 1 dps  →  得到「dps」
```

加速度输出单位是 **g**，角速度输出单位是 **dps（度/秒）**。还做了陀螺仪**零偏校准**（开机时静止采 128 次求平均，之后每次读数都减掉这个偏置），消除传感器固有误差。

### Step 5 —— 主循环 `main_task.c`：把传感器和 AI 串起来

文件：`src/main_task.c`。这是「指挥中心」，`Fall_Detect_Task_Body()` 里的死循环就是整个系统的心跳：

```c
AI_Model_Init();      // 开机各初始化一次
MPU6050_Init();
ws2812b_init();
sle_server_task_init();

while (1) {
    float ax,ay,az,gx,gy,gz;
    MPU6050_Read_Accel_Gyro(&ax,&ay,&az,&gx,&gy,&gz);   // ① 读一个采样点
    int status = AI_Feed_And_Predict_6Axis(ax,ay,az,gx,gy,gz);  // ② 喂给 AI
    if (status == 1) {                                  // ③ 确认跌倒
        sle_send_fall_alert(&alert_data, 1);            //    通过星闪发 0x05 报警
        // 点亮灯带、进入 10 秒冷却...
    }
    osDelay(10);                                        // ④ 歇 10 ms 再来
}
```

注意一个**单位再加工**的细节，在 `ai_model.cpp` 的 `AI_Feed_And_Predict_6Axis()` 里：

```cpp
clamp_value(gx / GYRO_DPS_TO_MODEL_SCALE, -4.0f, 4.0f)  // GYRO_DPS_TO_MODEL_SCALE = 250
```

角速度 `dps` 还会再除以 250 并裁剪到 ±4 范围 —— 这是为了让喂进模型的数值范围，和 EI 训练时数据的数值范围对得上。**这就是 Step 0 那句警告的落地**：训练和部署的数据必须同一个「尺子」。

### Step 6 —— 注册任务 + Kconfig 菜单开关

光有代码还不够，得让系统**启动时真的去跑它**，并且能在配置菜单里开关。

**注册任务**：`Fall_Detect_Entry()`（`main_task.c:112`）用 `osThreadNew()` 把 `Fall_Detect_Task_Body` 创建成一个 LiteOS 线程。而 `Fall_Detect_Entry()` 本身在系统主入口被直接调用：

```
application/ws63/ws63_liteos_application/main.c:257  →  Fall_Detect_Entry();
```

**Kconfig 开关链**：WS63 用 `menuconfig` 图形菜单决定编译什么。开关是一层层「套娃」的：

```text
SAMPLES_ENABLE
  └─ ENABLE_MY_DEMO_SAMPLE          (application/samples/Kconfig)
       └─ SAMPLE_SUPPORT_FALL_DETECT (application/samples/my_demo/Kconfig)
            └─ ENABLE_FALL_DETECT_APP        (fall_detect/Kconfig)
                 ├─ FALL_DETECT_USE_SLE      ← 选星闪还是蓝牙
                 └─ FALL_DETECT_ROLE_SERVER / _CLIENT  ← 这块板子是「采集+AI」还是「接收」
```

CMake 这边对应地用 `if(DEFINED CONFIG_ENABLE_MY_DEMO_SAMPLE)` 决定要不要 `add_subdirectory(my_demo)`，一层层往下走，最终 `fall_detect/src/CMakeLists.txt` 把所有源码交给底层。

### Step 7 —— 编译并烧录

配置好 menuconfig 后，用工程的 `build.py` 编译，生成固件，烧进 WS63。开机串口会打印：

```
[AI] model ready: 256 samples, 6 axes, 200 Hz, interval=5 ms
[MPU6050] cfg: accel=+/-4g gyro=+/-500dps dlpf=44Hz sample=200Hz ...
[AI] collecting window: 120/256 samples ...      ← 正在攒窗口
[AI] status=normal ai_fall=2% normal=98% ...     ← 推理出结果了
```

看到这些日志，就说明模型已经成功在板子上跑起来了。

---

## 4. 追踪一个数据的完整旅程

把前面所有步骤连起来，跟踪「一个传感器读数」从产生到「报警」的全过程：

```text
①  MPU6050 芯片内部以 200 Hz 采样
        │  I2C 读寄存器 0x3B 起共 14 字节
        ▼
②  mpu6050.c：原始整数 → 物理单位
        ax=0.98g  ay=-0.03g  az=0.12g  gx=5.2dps ...
        │  main_task.c 循环调用
        ▼
③  ai_model.cpp：单位再缩放 + 裁剪
        gx/250 → 0.02 ，clamp 到 ±4
        │  存进 features_buffer[]
        ▼
④  攒窗口：不到 1536 个数 → 返回 -1（继续喂）
        │  攒满 256 个采样点
        ▼
⑤  run_classifier()  ┌─ DSP：频谱分析 FFT，1536 → 222 个特征
                      ├─ 归一化：StandardScaler（减均值、除标准差）
                      └─ 神经网络：222 → 2 个概率
        │  result.classification[] = { fall_risk:0.91, normal:0.09 }
        ▼
⑥  阈值判断：fall_risk 91% ≥ 80%  →  模型认为是跌倒
        │
        ▼
⑦  物理门控：加速度峰值/自由落体/旋转 也都像跌倒？  → 是
        │
        ▼
⑧  连续确认：连续 2 个窗口都满足？  → 是  →  返回 1
        │
        ▼
⑨  main_task.c：status==1  →  星闪发 0x05  →  另一块板子报警
        │  随后进入 10 秒冷却，避免连环触发
        ▼
   滑动窗口：丢掉最旧 384 个数，回到 ④ 继续
```

---

## 5. 以后重新训练了，怎么更新模型？

这是最实用的一节。当你在 EI 上采了新数据、重新训练后：

1. EI 网站 → Deployment → **C++ library** → Build → 下载新的 zip。
2. 解压，得到新的 `edge-impulse-sdk/`、`model-parameters/`、`tflite-model/`。
3. 把工程里**这三个文件夹整体替换**掉（建议先把旧的改名成 `xxx.bak_日期` 备份，工程里已经有这种备份就是这么来的）。
4. **检查类别名有没有变**：如果新模型的类别不再叫 `fall_risk` / `normal`，要去 `ai_model.cpp` 第 211~217 行同步改 `strcmp(...)` 里的字符串。
5. **检查窗口参数有没有变**：`ai_model.cpp` 用的 `EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE`、`RAW_SAMPLES_PER_FRAME` 都是宏，会随新 `model_metadata.h` 自动更新，一般不用手改。
6. 重新编译烧录。

> 关键认知：**第二类「胶水代码」（ai_model.cpp / mpu6050.c / main_task.c）通常不用动，只换第一类的三个文件夹**。这就是为什么第 2 节要花力气把文件分清楚——它决定了你以后改东西时该动哪、不该动哪。

---

## 6. 小白常见坑总结

| 现象 | 原因 | 怎么查 |
| --- | --- | --- |
| 模型一直不出结果，只打印 `collecting window` | 窗口还没攒满 256 个采样点，正常现象，等 1~2 秒 | 看 `[AI] collecting window` 的进度 |
| 准确率很差，乱报警 | 部署时的采样率/量程/单位和 EI 训练时不一致 | 对照 Step 4：200 Hz、±4g、±500dps、单位 g/dps |
| 编译报 C++ 异常相关链接错误 | 没加 `-fno-exceptions -fno-rtti` | 见 Step 3 的 CMakeLists 改动 |
| 编译报 `model_metadata.h` 找不到 | 头文件搜索路径没加 | 见 Step 3 第 5 点 |
| `[AI] OOM` 内存不足 | 40 KB 内存池不够 | 调大 `ai_model.cpp` 的 `AI_POOL_SIZE` |
| 改了模型后类别对不上、概率永远是 0 | 新模型类别名变了，`strcmp` 没同步 | 见第 5 节第 4 点 |
| 模型结果对，但实际没报警 | 卡在物理门控或连续确认 | 看串口 `gate=NO` 或 `confirm=1/2` |

---

## 7. 一句话回顾

> Edge Impulse 帮你把「训练好的模型」打包成三个文件夹（SDK 引擎 + 模型参数 + 编译后的神经网络）。
> 部署的真正工作，是写一层 **C++ 胶水代码**（`ai_model.cpp`）：管好内存、攒够一个窗口的数据、调用 `run_classifier()`、解析概率；
> 再配好**构建脚本**让它能编译、配好 **Kconfig** 让它能开关、配好**传感器驱动**让真实数据和训练数据同一把尺子；
> 最后在**主循环**里把「读传感器 → 喂 AI → 报警」串成一个永远运行的心跳。
