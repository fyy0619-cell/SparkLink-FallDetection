# SDK编译环境配置

## 目标

能在本地完成海思WS63 SDK的编译，并成功烧录到开发板。

---

## 前提条件

- Linux系统（推荐Ubuntu 20.04）或WSL2
- 海思WS63 SDK压缩包
- USB转串口工具（用于日志查看与烧录）

---

## 步骤一：安装依赖工具链

```bash
sudo apt update
sudo apt install -y build-essential cmake git python3 python3-pip
# 安装交叉编译工具链（海思提供）
tar -xzf arm-himix200-linux.tar.gz
export PATH=$PATH:$(pwd)/arm-himix200-linux/bin
```

## 步骤二：解压SDK并了解目录结构

```
ws63_sdk/
├── build/          # 构建脚本与配置
├── drivers/        # 外设驱动（I2C、SPI、GPIO等）
├── kernel/         # LiteOS内核源码
├── middleware/      # 中间件（BLE协议栈、SLE协议栈）
├── applications/   # 用户应用层（在这里写业务代码）
└── output/         # 编译输出目录
```

> **关键**：当找不到某个外设的宏定义时，不要只看原理图，直接在SDK中搜索：
> ```bash
> grep -r "GPIO15" drivers/
> grep -r "I2C_SCL" drivers/
> ```

## 步骤三：编译SDK

```bash
cd ws63_sdk/build
python3 build.py all
# 输出bin文件位于 output/ 目录
```

## 步骤四：串口日志配置

波特率：`115200`，8N1，使用 `minicom` 或 `SecureCRT` 查看。

---

## 常见问题

**Q: 找不到某头文件？**  
A: 先在SDK目录全局搜索 `grep -r "xxx.h" .`

**Q: 编译报找不到符号？**  
A: 检查 `CMakeLists.txt` 中是否包含了对应的源文件目录。
