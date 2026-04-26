# C++编译链移植到LiteOS

## 背景

**核心问题**：C++标准库的编译链默认依赖Linux系统调用（如 `malloc`、`new`、异常处理等），而LiteOS是极小的轻量化RTOS，不提供这些依持。

**表现**：链接阶段报错，找不到 `__cxa_atexit`、`__dso_handle` 等符号。

---

## 解决方案

### 1. 禁用C++不需要的特性

在CMakeLists中添加编译选项：

```cmake
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} \
    -fno-exceptions \
    -fno-rtti \
    -fno-use-cxa-atexit \
    -fno-threadsafe-statics")
```

### 2. 提供缺失符号的最小实现

创建文件 `src/liteos_compat.cpp`：

```cpp
// 提供C++运行时所需的最小符号
extern "C" {
    void *__dso_handle = nullptr;
    void __cxa_atexit(void (*)(void*), void*, void*) {}
    void __cxa_pure_virtual() { while(1); }  // 纯虚函数调用保护
}

// 替换 operator new/delete（使用LiteOS内存分配）
#include "los_memory.h"

void* operator new(size_t size) {
    return LOS_MemAlloc(OS_SYS_MEM_ADDR, size);
}

void* operator new[](size_t size) {
    return LOS_MemAlloc(OS_SYS_MEM_ADDR, size);
}

void operator delete(void* ptr) noexcept {
    LOS_MemFree(OS_SYS_MEM_ADDR, ptr);
}

void operator delete[](void* ptr) noexcept {
    LOS_MemFree(OS_SYS_MEM_ADDR, ptr);
}
```

### 3. C调用C++接口（extern "C"）

```cpp
// my_cpp_module.h
#pragma once
#ifdef __cplusplus
extern "C" {
#endif

void cpp_module_init(void);
int  cpp_module_run(float* data, int len);

#ifdef __cplusplus
}
#endif
```

```cpp
// my_cpp_module.cpp
#include "my_cpp_module.h"

extern "C" void cpp_module_init(void) {
    // C++初始化逻辑
}

extern "C" int cpp_module_run(float* data, int len) {
    // C++推理逻辑
    return 0;
}
```

---

## 注意事项

- 不要使用 `std::vector`、`std::string` 等需要大量堆内存的STL容器
- Edge Impulse导出库内部可能使用了STL，需要提供足够的堆内存（在LiteOS配置中调大 `OS_SYS_MEM_SIZE`）
- 路径配置要正确，CMakeLists中 `include_directories` 必须包含所有头文件路径

---

## 成功标志

串口输出看到推理结果打印，说明C++代码已在LiteOS上成功运行。
