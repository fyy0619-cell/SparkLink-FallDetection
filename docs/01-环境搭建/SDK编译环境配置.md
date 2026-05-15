# SDK编译环境配置

本文是 WS63 编译环境与工具链的速查。完整的开发板上手步骤（装 IDE → 编译 → 烧录 → 测试）见 [WS63开发板上手指南](WS63开发板上手指南.md)。

## 目标

能在本地完成海思 WS63 SDK 的编译，并烧录到开发板。

---

## 前提条件

- Windows 10 / 11
- HiSpark Studio（海思官方 IDE，基于 VSCode；**自带 RISC-V 工具链**）
- WS63 SDK 工程（含 `demo.hiproj`、`build.py`、`application/` 等）
- USB 数据线 + USB 转串口驱动（CH340 / CP2102）

---

## 工具链

WS63 是 **RISC-V** 架构，工具链为 `cc_riscv32_musl_fp_win`，**随 HiSpark Studio 一起安装，无需手动配置**。位于：

```
tools/bin/compiler/riscv/cc_riscv32_musl_105/cc_riscv32_musl_fp_win/bin
```

> 注意：WS63 不是 ARM 芯片，不要使用 `arm-none-eabi-gcc` / `arm-himix` 之类的 ARM 工具链。

---

## SDK 目录结构

```
src/
├── build.py            # 构建入口脚本
├── CMakeLists.txt      # 顶层构建配置
├── demo.hiproj         # HiSpark Studio 工程文件
├── config.in           # menuconfig 配置入口
├── application/        # 用户应用层（业务代码写这里）
├── drivers/            # 外设驱动（I2C、SPI、GPIO 等）
├── kernel/             # LiteOS 内核源码
├── middleware/         # 中间件（BLE / SLE 协议栈等）
├── build/              # 构建脚本与 target 配置
└── output/             # 编译输出（固件 fwpkg 在这里）
```

> **关键**：找不到某个外设的宏定义时，不要只看原理图，直接在 SDK 里全局搜索宏名（如 `GPIO15`、`I2C_SCL`）。

---

## 编译

在 HiSpark Studio 里点「编译」按钮即可，底层调用 `build.py`。命令行等价写法：

```
python build.py ws63-liteos-app
```

产物固件：`output/ws63/fwpkg/ws63-liteos-app/ws63-liteos-app_all.fwpkg`

---

## 串口

- **看日志**：波特率 `115200`，8N1，可用 HiSpark Studio 自带终端 / SecureCRT / 串口助手
- **烧录**：波特率 `921600`

> 两个波特率不同，别混用。

---

## 常见问题

**Q: 找不到某头文件 / 编译报找不到符号？**  
A: 全局搜索头文件名；检查 `CMakeLists.txt` 是否包含了对应的源文件目录。

**Q: C++ / Edge Impulse 相关的链接报错？**  
A: 见同目录《C++编译链移植到LiteOS》。
