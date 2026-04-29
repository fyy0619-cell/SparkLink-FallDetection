# Fall Detect + SLE 联调问题复盘（2026-04-29）

## 1. 项目目标
- Server 端检测跌倒后，通过 SLE/SSAP 向 Client 发送告警数据（0x05）。
- Client 收到 0x05 后触发蜂鸣器报警，并在 10 秒后自动停止。

## 2. 今日遇到的问题

### 2.1 Client 侧 SSAP 注册失败
- 现象：`ssapc_register_client failed: 0x80006011`
- 影响：SSAP 客户端未注册成功，后续 MTU/服务发现/通知接收链路失效。

### 2.2 任务重复启动导致状态混乱
- 现象：Client 日志出现两次 `Running in CLIENT mode (Board B)`。
- 影响：同一业务线程和回调重复注册，造成连接/扫描/回调时序异常。

### 2.3 只收到握手包，不触发蜂鸣器
- 现象：Client 只收到 `data[0]=0x01`，没有 `data[0]=0x05`。
- 影响：蜂鸣器逻辑只对 0x05 生效，因此不报警。

### 2.4 Server 有“跌倒检测”日志但未发送告警
- 现象：看到 `WARNING: FALL DETECTED`，但未见 `Fall Confirmed` / 发送成功日志。
- 根因：原先“窗口累计判定”与 AI 有效输出节奏不匹配，导致告警触发条件不稳定。

## 3. 已实施的修复方案

### 3.1 修复 SSAP 注册时机
- 调整为：在 `enable_sle` 成功回调后执行 `ssapc_register_client`。
- 目的：避免 SLE 栈未 ready 时注册导致的 0x80006011。
- 文件：`application/samples/my_demo/fall_detect/src/sle_client_task.c`

### 3.2 移除重复启动入口
- 删除重复 `app_run(Fall_Detect_Entry)`，仅保留主入口调用。
- 文件：`application/samples/my_demo/fall_detect/src/main_task.c`

### 3.3 服务发现按 UUID 精确匹配
- 在 Client 服务发现回调中仅匹配 `0xABCD` 服务句柄用于后续写/激活。
- 文件：`application/samples/my_demo/fall_detect/src/sle_client_task.c`

### 3.4 增加蜂鸣器 10 秒自动停止
- 新增守护逻辑：收到 0x05 后启动计时，到期关闭蜂鸣器与告警灯效。
- 文件：`application/samples/my_demo/fall_detect/src/sle_client_task.c`

### 3.5 端到端链路联调验证（临时代码）
- 临时在 Server 建链后主动发一次 0x05，验证链路和蜂鸣器触发。
- 结果：验证通过（蜂鸣器响约 10 秒后自动停止）。
- 验证完成后已移除临时发送代码。

### 3.6 报警策略改为“单次命中即报警”
- 由“窗口累计阈值触发”改为：`status == 1` 立即发送 0x05。
- 保留冷却时间用于抑制重复告警。
- 冷却时间由 5000ms 调整为 2000ms（更灵敏）。
- 文件：`application/samples/my_demo/fall_detect/src/main_task.c`

## 4. 当前协议与行为约定
- `0x01`：握手/链路激活验证包。
- `0x05`：跌倒告警包（触发蜂鸣器）。
- `0x06`：Client 回写 ACK（Server 可在写回调中确认）。

## 5. 涉及技术栈与原理

### 5.1 SLE（NearLink）
- 负责广播、扫描、连接、配对、链路管理等底层能力。

### 5.2 SSAP（SLE Service Access Protocol）
- 类似 GATT 的服务访问模型：Server 暴露 service/property，Client 发现并收发数据。
- Notify 用于低时延推送；如需业务可靠性，可结合 ACK 机制。

### 5.3 任务/回调时序要点
1. `enable_sle`
2. 注册连接/扫描/SSAP回调
3. 建链与配对
4. MTU 交换
5. 服务发现与句柄绑定
6. 通知接收与业务处理（蜂鸣器）

## 6. 当前状态
- Client 可稳定连接并完成服务发现。
- Server 可在跌倒命中时发送告警。
- Client 收到 0x05 后蜂鸣器报警，10 秒后自动停止。
- 报警策略已调至更灵敏（单次命中立即报警，2 秒冷却）。

## 7. 后续优化建议
- 增加 `0x00` 恢复包：允许 Server 远程提前停止蜂鸣器。
- 告警包增加序列号/时间戳，便于重传排查。
- 在 Server 记录每次 `sle_send_fall_alert` 返回码，提升现场可观测性。
