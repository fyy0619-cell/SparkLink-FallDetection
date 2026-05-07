# Edge Impulse + SisFall 模型部署调试记录（2026-05-07）

本文记录 2026-05-07 在 WS63 LiteOS 开发板上部署 Edge Impulse 跌倒检测模型时遇到的主要问题、排查依据、解决方案和最终状态。内容面向比赛复现和后续维护，重点说明采样率、滑动窗口、6 轴输入、模型调用、串口实时状态、误报抑制和固件打包。

---

## 1. 当前目标

目标是在 WS63 + LiteOS 开发板上运行基于 SisFall 数据集训练的二分类跌倒检测模型，并在串口实时输出状态：

- `normal`：正常状态，不报警。
- `FALL_RISK`：跌倒风险，通过 SLE 发送 SOS 告警。

系统使用：

- 传感器：MPU6050。
- 输入轴：`accX, accY, accZ, gyrX, gyrY, gyrZ`，共 6 轴。
- 机器学习平台：Edge Impulse。
- 部署方式：Edge Impulse C++ Library + WS63 LiteOS 工程集成。
- 通信：SLE Server 向 Client 发送跌倒告警。

---

## 2. Edge Impulse 模型参数

本次最终集成的 Edge Impulse 模型参数如下：

| 参数 | 值 |
|---|---|
| Edge Impulse Project ID | `985336` |
| Project name | `latest_fall` |
| 标签 | `fall_risk`, `normal` |
| 输入轴 | `accX + accY + accZ + gyrX + gyrY + gyrZ` |
| 原始窗口采样点 | `256 samples` |
| 每帧轴数 | `6 axes` |
| 原始输入长度 | `1536 = 256 * 6` |
| 采样率 | `200 Hz` |
| 采样间隔 | `5 ms` |
| DSP 输入长度 | `1536` |
| NN 输入长度 | `222` |
| DSP 模块 | Spectral Analysis |
| 学习模块 | Classification |
| 部署格式 | C++ Library / EON / INT8 |

工程串口启动时应打印：

```text
[AI] model ready: 256 samples, 6 axes, 200 Hz, interval=5 ms
```

这行日志是判断固件模型参数是否与 Edge Impulse 一致的关键依据。

---

## 3. 数据集与 Edge Impulse 上传经验

### 3.1 使用的数据

原始数据来自：

```text
D:\Download_1\Three Classes
```

后续按二分类处理：

- `normal`
- `fall_risk`

SisFall 原始动作类别不直接作为最终标签使用，而是归并成二分类。这样更适合比赛演示和嵌入式实时告警。

### 3.2 上传时标签不是 Train/Test

在 Edge Impulse 的 `Data acquisition -> Upload` 页面，`Label` 应填写样本类别，例如：

```text
normal
fall_risk
```

不要把标签写成 `training` 或 `testing`。训练集和测试集是在上传时通过 `Category` 选择：

- `Training`
- `Testing`

也就是说：

```text
Label = normal / fall_risk
Category = Training / Testing
```

### 3.3 上传数量不等于最终样本数量的原因

上传 fall_risk CSV 后，Edge Impulse 页面显示的最终样本数可能少于本地文件数量。常见原因：

1. CSV 格式或时间戳不符合 Edge Impulse 要求，被平台丢弃。
2. 文件内窗口长度不足，无法切成完整 `256 samples` 窗口。
3. 部分数据被平台识别为空数据、重复数据或非法数据。
4. 上传时浏览器/平台批处理存在限制，需要分批上传。
5. 本地统计的是原始文件数，平台统计的是可用样本或切片后的有效数据。

因此本地转换脚本必须输出标准 EI CSV，并且上传后要在 Data acquisition 中抽查数据曲线是否完整。

---

## 4. 问题一：烧录后串口没有 AI 跌倒检测信息

### 现象

烧录后串口只看到系统初始化、SLE Client 或雷达日志，没有实时 AI 状态：

```text
[System] Running in CLIENT mode (Board B).
[System] Fall Detect Task Registered to LiteOS!
APP|[SYS INFO] mem: used:..., free:...
```

### 根因

当时固件运行在 `CLIENT mode`，而 MPU6050 采样和 Edge Impulse 推理逻辑只在 `SERVER mode` 中执行。Client 板只负责接收或转发告警，不会采集 MPU6050，也不会调用 AI 模型。

### 解决方案

强制传感器板运行在 Server 模式：

- `application\samples\my_demo\fall_detect\src\main_task.c`
- `application\samples\my_demo\fall_detect\src\CMakeLists.txt`

最终启动日志应为：

```text
[System] Running in SERVER mode (Board A).
[AI] model ready: 256 samples, 6 axes, 200 Hz, interval=5 ms
[MPU6050] Wakeup success
```

---

## 5. 问题二：AI 一直 collecting，没有正常结果

### 现象

串口反复打印：

```text
[AI] collecting window... need 256 samples, 6 axes, 200 Hz
```

或者：

```text
[AI] collecting window: 200/256 samples, 6 axes, 200 Hz
```

### 判断

这不是错误。Edge Impulse 模型需要先收满一个完整窗口：

```text
256 samples * 6 axes = 1536 float values
```

采样率为 `200 Hz`，所以第一个窗口需要：

```text
256 / 200 = 1.28 s
```

收满后才会进入 DSP 和神经网络推理。

### 解决方案

保留 collecting 日志，但降低打印频率，避免串口刷屏。当前逻辑每隔一定采样数打印一次采集进度。

---

## 6. 问题三：`run_classifier()` 返回 `-22`

### 现象

收满窗口后推理失败：

```text
[AI] inference failed: -22; no normal/fall_risk result for this window
```

加入调试日志后发现：

```text
[AI_DBG] process_impulse bad ptr: handle=0xa37148 impulse=0 result=0xa59810 signal=0xa597fc
```

### 根因

Edge Impulse 生成的全局 C++ 对象 `ei_default_impulse` 依赖全局构造函数。WS63/LiteOS 启动流程中 C++ 全局构造函数没有可靠执行，导致 `ei_default_impulse` 内部的 `impulse` 指针为 `0`。

因此推理接口拿到的是无效 impulse handle，最终返回 `-22`。

### 解决方案

不直接使用生成的全局 `ei_default_impulse`，而是在运行时通过 placement new 显式构造 `ei_impulse_handle_t`：

```cpp
static ei_impulse_handle_t *get_ai_impulse_handle(void)
{
    static bool initialized = false;
    static uint8_t handle_storage[sizeof(ei_impulse_handle_t)] __attribute__((aligned(16)));
    ei_impulse_handle_t *handle = reinterpret_cast<ei_impulse_handle_t *>(handle_storage);
    if (!initialized) {
        new (handle) ei_impulse_handle_t(&impulse_985336_1);
        initialized = true;
    }
    return handle;
}
```

调用时使用：

```cpp
run_classifier(get_ai_impulse_handle(), &features_signal, &result, false);
```

修复后串口显示 DSP、归一化和 TFLite 推理可以正常执行。

---

## 7. 问题四：推理时间显示异常大

### 现象

串口打印过异常时间：

```text
dsp=4294960293 ms infer=784048289 ms
```

### 根因

Edge Impulse SDK 内部计时函数没有适配当前 WS63 LiteOS 平台，导致时间统计溢出或无效。

### 解决方案

比赛演示不依赖该时间字段，因此去掉 `dsp` 和 `infer` 耗时打印，避免误导。保留最终分类、门控、峰值和确认窗口信息。

---

## 8. 问题五：`fall_risk` 一开始一直是 0%，后来又一直是 100%

### 现象 A：一直 normal

早期串口：

```text
[AI] status=normal fall_risk=0% normal=100%
```

### 现象 B：修改陀螺仪缩放后一直 fall_risk

后来串口：

```text
[AI] status=FALL_RISK fall_risk=100% normal=0%
```

### 根因

SisFall 数据集和 WS63 + MPU6050 实测数据存在分布差异：

1. SisFall 中的陀螺仪单位/尺度与 MPU6050 实时输出不完全一致。
2. MPU6050 输出陀螺仪原始单位为 `deg/s`，训练数据中陀螺仪数值范围更接近归一化后的 `-1..1`。
3. Edge Impulse 模型对输入尺度非常敏感。
4. 真实板子的安装方向、噪声、采样抖动、量程、滤波方式与 SisFall 采集设备不同。

### 解决方案

在喂给模型前对陀螺仪进行尺度转换：

```cpp
#define GYRO_DPS_TO_MODEL_SCALE 250.0f

gyr_model = gyro_dps / GYRO_DPS_TO_MODEL_SCALE;
```

同时将模型判断和物理门控分离，不再直接把 `ai_fall` 作为最终告警条件。

---

## 9. 问题六：静止时模型仍输出 `ai_fall=100%`

### 现象

静止状态下，串口可能出现：

```text
[AI] status=normal ai_fall=100% normal=0% gate=NO confirm=0/2 peak_acc=1.11G min_acc=1.09G peak_gyr=0.00 hits=0/0/0
```

### 判断

这说明传感器物理状态是正常的：

```text
peak_acc ≈ 1.1G
peak_gyr ≈ 0
hits = 0/0/0
gate = NO
status = normal
```

但模型原始输出仍然偏向 `fall_risk`。这不是部署链路错误，而是模型与真实硬件数据存在 domain mismatch。

### 当前工程策略

最终状态不直接相信模型，而使用三层判断：

```text
最终跌倒 = AI 模型认为 fall_risk AND 物理门控通过 AND 连续窗口确认通过
```

串口中：

- `ai_fall`：模型原始输出，仅作参考。
- `gate`：物理门控是否通过。
- `confirm`：连续窗口确认计数。
- `status`：最终状态，用于报警。

比赛演示时应重点解释 `status`，不要单独展示 `ai_fall` 作为最终结论。

---

## 10. 问题七：静止或轻微动作时 peak 值异常

### 现象

早期门控版本中，静止或轻微动作时可能出现：

```text
peak_acc=2.00G peak_gyr=1.00
```

导致 `gate=YES`，进而误报警。

### 根因

1. MPU6050 未显式配置采样率、低通滤波、加速度量程和陀螺仪量程。
2. 陀螺仪没有启动零偏校准。
3. 早期 `peak_acc` 使用单轴最大值，而不是三轴合加速度模长。
4. 单个异常采样点可能进入 1.28 秒滑动窗口，连续影响多次判断。

### 解决方案 A：配置 MPU6050

MPU6050 初始化时显式配置：

```c
mpu6050_write_reg(MPU6050_REG_CONFIG, 0x03);     // DLPF ~44 Hz
mpu6050_write_reg(MPU6050_REG_SMPLRT_DIV, 0x04); // 1 kHz / (1 + 4) = 200 Hz
mpu6050_write_reg(MPU6050_REG_ACCEL_CFG, 0x08);  // +/-4 g
mpu6050_write_reg(MPU6050_REG_GYRO_CFG, 0x08);   // +/-500 dps
```

并在启动时做陀螺仪零偏校准：

```c
#define MPU6050_GYRO_CALIB_SAMPLES 128
```

启动时应打印：

```text
[MPU6050] cfg: accel=+/-4g gyro=+/-500dps dlpf=44Hz sample=200Hz gyro_offset=...
```

### 解决方案 B：改用三轴模长

加速度峰值改为：

```cpp
acc_mag = sqrt(ax * ax + ay * ay + az * az);
```

陀螺仪峰值改为：

```cpp
gyr_mag = sqrt(gx * gx + gy * gy + gz * gz);
```

这样比单轴峰值更符合物理意义。

---

## 11. 问题八：单个异常点导致误触发 gate

### 现象

即使只是一个瞬态尖峰，也可能让早期门控输出：

```text
gate=YES
```

### 根因

滑动窗口长度为：

```text
256 samples / 200 Hz = 1.28 s
```

一个异常采样点会在窗口中保留一段时间，并影响后续多个推理窗口。

### 解决方案

加入 `hits` 机制，不再只看最大值，而是要求窗口内有足够数量的采样点满足条件：

```cpp
#define FALL_GATE_MIN_HIT_SAMPLES 3
```

输出格式新增：

```text
hits=冲击点数/失重点数/旋转点数
```

示例：

```text
[AI] status=normal ai_fall=96% normal=4% gate=NO confirm=0/2 peak_acc=1.61G min_acc=0.63G peak_gyr=1.77 hits=0/0/4
```

此时虽然有旋转峰值，但冲击点数不足，因此不报警。

---

## 12. 最终实时判定逻辑

当前判定逻辑为：

```cpp
bool model_fall = (fall_risk_percent >= 80);

bool shock_with_rotation =
    (acc_shock_hits >= 3) &&
    (gyr_hits >= 3);

bool freefall_then_shock =
    (acc_freefall_hits >= 3) &&
    (acc_peak >= 1.50f);

bool motion_gate = shock_with_rotation || freefall_then_shock;

if (model_fall && motion_gate) {
    consecutive_fall_windows++;
} else {
    consecutive_fall_windows = 0;
}

bool final_fall = consecutive_fall_windows >= 2;
```

最终报警条件：

```text
status=FALL_RISK
gate=YES
confirm >= 2/2
```

---

## 13. 当前串口输出字段说明

示例：

```text
[AI] status=normal ai_fall=99% normal=1% gate=NO confirm=0/2 peak_acc=1.10G min_acc=1.09G peak_gyr=0.00 hits=0/0/0
```

字段含义：

| 字段 | 含义 |
|---|---|
| `status` | 最终状态，只有这里是 `FALL_RISK` 才触发报警 |
| `ai_fall` | Edge Impulse 模型原始 fall_risk 概率 |
| `normal` | Edge Impulse 模型原始 normal 概率 |
| `gate` | 物理门控是否通过 |
| `confirm` | 连续确认窗口计数 |
| `peak_acc` | 当前 1.28 秒窗口内最大三轴合加速度 |
| `min_acc` | 当前 1.28 秒窗口内最小三轴合加速度，用于判断失重 |
| `peak_gyr` | 当前 1.28 秒窗口内最大三轴合角速度归一化值 |
| `hits` | 冲击点数 / 失重点数 / 旋转点数 |

---

## 14. 最终验证日志

### 14.1 静止状态

```text
[AI] status=normal ai_fall=99% normal=1% gate=NO confirm=0/2 peak_acc=1.10G min_acc=1.09G peak_gyr=0.00 hits=0/0/0
[AI] status=normal ai_fall=95% normal=5% gate=NO confirm=0/2 peak_acc=1.11G min_acc=1.09G peak_gyr=0.00 hits=0/0/0
```

判断：静止不报警，合理。

### 14.2 剧烈动作但未满足完整跌倒条件

```text
[AI] status=normal ai_fall=0% normal=100% gate=NO confirm=0/2 peak_acc=1.61G min_acc=0.63G peak_gyr=1.77 hits=0/0/3
[AI] status=normal ai_fall=17% normal=83% gate=NO confirm=0/2 peak_acc=1.61G min_acc=0.63G peak_gyr=1.77 hits=0/0/4
```

判断：有旋转但冲击不足，不报警，合理。

### 14.3 跌倒/撞击/翻转动作

```text
[AI] status=normal ai_fall=100% normal=0% gate=YES confirm=1/2 peak_acc=2.35G min_acc=0.24G peak_gyr=2.90 hits=4/1/20
[AI] status=FALL_RISK ai_fall=100% normal=0% gate=YES confirm=2/2 peak_acc=3.20G min_acc=0.24G peak_gyr=3.12 hits=7/2/28
[Alert] Fall Detected (single hit). Sending SOS now...
```

判断：冲击 + 旋转 + 连续窗口确认，触发报警，合理。

---

## 15. 固件构建与烧录产物

构建命令：

```powershell
$env:PATH='D:\tools_link\tools\Windows\cc_riscv32_musl_fp_win\bin;D:\tools_link\tools\cfbb\thirdparty\ccache;D:\tools_link\tools\python\Scripts;D:\tools_link\tools\python\Lib\site-packages\cmake\data\bin;D:\tools_link\tools\Windows\ninja;' + $env:PATH
D:\tools_link\tools\python\python.exe build.py ws63-liteos-app
```

最终固件包：

```text
D:\fbb_ws63\fbb_ws63-master\src\output\ws63\fwpkg\ws63-liteos-app\ws63-liteos-app_all.fwpkg
```

2026-05-07 晚间最终验证包：

```text
LastWriteTime: 2026/5/7 22:41:28
Length: 1622440 bytes
```

内存占用参考：

```text
SRAM:    about 236704 B / 548608 B, 43.15%
PROGRAM: about 1457544 B / 2357504 B, 61.83%
```

该内存占用可以接受。

---

## 16. 比赛演示建议

当前系统可以用于比赛演示，但应如实表述技术路线：

```text
Edge Impulse 模型 + MPU6050 物理特征门控 + 连续窗口确认 + SLE SOS 通信
```

不建议宣称为“纯 AI 直接判断跌倒”，因为当前 `ai_fall` 在静止时仍可能偏高。最终系统的可靠性来自：

1. AI 模型提供动作类别倾向。
2. 加速度峰值判断冲击。
3. 最小加速度判断失重。
4. 陀螺仪判断旋转。
5. hits 机制过滤单个异常点。
6. confirm 机制要求连续窗口确认。

比赛前必须测试：

| 测试场景 | 期望结果 |
|---|---|
| 平放静止 30 秒 | `status=normal`, `gate=NO`, `hits=0/0/0` |
| 手持正常走动 | 不应触发 `FALL_RISK` |
| 快速拿起放下 | 尽量不报警，允许短暂 `confirm=1/2` |
| 模拟跌倒/撞击/翻转 | 应触发 `FALL_RISK` 和 SOS |
| 连续晃动但无撞击 | 尽量不报警 |

---

## 17. 后续优化方向

当前工程已达到比赛演示可用状态，但仍有优化空间：

1. 重新采集板端真实数据训练模型：最好直接用 WS63 + MPU6050 采集 normal/fall_risk，而不是只依赖 SisFall。
2. 加速度六面标定：降低静止时 `1.10G` 的比例误差。
3. 比赛展示模式：串口可隐藏 `ai_fall` 原始概率，避免评委看到 `ai_fall=100%` 但 `status=normal` 时困惑。
4. SLE Client 联调：确保 `FALL_RISK` 后客户端能收到 SOS，而不是 `No client connected, drop alert`。
5. 动作阈值微调：根据比赛演示动作，微调 `FALL_GATE_ACC_PEAK_G`、`FALL_GATE_ACC_FREEFALL_G` 和 `FALL_GATE_MIN_HIT_SAMPLES`。

---

## 18. 本日结论

今日解决的问题包括：

1. Server/Client 固件角色错误导致 AI 不运行。
2. Edge Impulse C++ 全局对象未构造导致 `run_classifier()` 返回 `-22`。
3. 推理计时字段在 WS63 平台无效。
4. SisFall 模型与 MPU6050 实测数据尺度不匹配。
5. 静止状态下模型 `ai_fall` 偏高。
6. MPU6050 未配置采样率、滤波和量程导致峰值异常。
7. 单个异常采样点导致门控误触发。
8. 最终通过物理门控 + hits + 连续窗口确认实现稳定报警。

最终状态：

```text
静止：status=normal, gate=NO
跌倒/撞击/翻转：status=FALL_RISK, gate=YES, confirm>=2/2
```

工程当前可以用于比赛演示，但真实产品级仍建议使用板端自采数据重新训练模型。
