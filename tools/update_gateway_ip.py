#!/usr/bin/env python3
"""演示前 / 热点重连后，一键把板 B 固件里的 backend IP 同步成笔记本当前 WiFi IP.

用法:
    cd D:/fbb_ws63/SparkLink-FallDetection/tools
    python update_gateway_ip.py

脚本干什么:
    1) 调 ipconfig 列出笔记本上所有 IPv4 网卡
    2) 让你选择哪一个是 "板 B 要走的那张 WiFi"（避免误选虚拟机 / 以太网）
    3) 显示固件里现在的 IP vs 新选 IP, 询问 Y/n 确认才写入
    4) 提示去 HiSpark Studio Build + 烧板 B 的下一步
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


# 板 B 固件源码所在的绝对路径（如果工程移了位置改这一行就行）
GATEWAY_CONFIG_H = Path(
    r"D:\fbb_ws63\fbb_ws63-master\src\application\samples\my_demo\fall_detect\inc\fall_alert_gateway_config.h"
)


def list_ipv4_adapters() -> list[tuple[str, str]]:
    """返回 [(adapter_name, ipv4), ...]，按 ipconfig 出现顺序。"""
    out = subprocess.check_output(["ipconfig"], stderr=subprocess.STDOUT)
    text = out.decode("gbk", errors="replace")

    adapters: list[tuple[str, str]] = []
    current_name = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        # 适配器块的标题行
        # "无线局域网适配器 WLAN:"  或  "Wireless LAN adapter Wi-Fi:"
        # "以太网适配器 VMware Network Adapter VMnet8:"  或  "Ethernet adapter ..."
        if line and not line.startswith(" ") and not line.startswith("\t") and line.endswith(":"):
            current_name = line.rstrip(":")
            continue
        # IPv4 行
        m = re.search(r"IPv4[^\:]*:\s*([\d\.]+)", line)
        if m and current_name:
            adapters.append((current_name, m.group(1)))
    return adapters


def read_current_host_in_firmware() -> str:
    text = GATEWAY_CONFIG_H.read_text(encoding="utf-8")
    m = re.search(r'#define\s+FALL_GATEWAY_SERVER_HOST\s+"([^"]+)"', text)
    if not m:
        raise RuntimeError(f"找不到 FALL_GATEWAY_SERVER_HOST 宏: {GATEWAY_CONFIG_H}")
    return m.group(1)


def write_host_in_firmware(new_ip: str) -> None:
    text = GATEWAY_CONFIG_H.read_text(encoding="utf-8")
    pattern = re.compile(r'(#define\s+FALL_GATEWAY_SERVER_HOST\s+")([^"]+)(")')
    new_text = pattern.sub(rf'\g<1>{new_ip}\g<3>', text)
    GATEWAY_CONFIG_H.write_text(new_text, encoding="utf-8")


def guess_wlan_index(adapters: list[tuple[str, str]]) -> int:
    """猜哪个是真 WLAN——优先名字带 WLAN/无线/Wi-Fi 的，否则第一个。"""
    for i, (name, _) in enumerate(adapters):
        if any(k in name for k in ("WLAN", "无线", "Wi-Fi", "Wireless")):
            return i
    return 0


def main() -> int:
    # 1. 列网卡
    print("[1/4] 笔记本上能看到的所有 IPv4:")
    print("-" * 70)
    adapters = list_ipv4_adapters()
    if not adapters:
        print("[err] 没找到任何 IPv4 地址。先确认笔记本至少连了一个网。", file=sys.stderr)
        return 1

    default_idx = guess_wlan_index(adapters)
    for i, (name, ip) in enumerate(adapters):
        marker = " ← 默认推荐 (WLAN)" if i == default_idx else ""
        print(f"  [{i}]  {ip:<18}  {name}{marker}")
    print("-" * 70)

    # 2. 读旧值
    try:
        old_ip = read_current_host_in_firmware()
    except Exception as exc:
        print(f"[err] {exc}", file=sys.stderr)
        return 1
    print(f"[2/4] 板 B 固件里现在写的 backend IP: {old_ip}")

    # 3. 让用户选
    print(f"[3/4] 选哪一个作为新的 backend IP？")
    print(f"      直接回车 = 选 [{default_idx}] {adapters[default_idx][1]}")
    print(f"      或输入序号 / 或输入 q 取消")
    while True:
        choice = input("      > ").strip()
        if choice.lower() in ("q", "quit", "exit"):
            print("已取消，固件不改。")
            return 0
        if choice == "":
            picked = default_idx
            break
        try:
            picked = int(choice)
            if 0 <= picked < len(adapters):
                break
        except ValueError:
            pass
        print(f"      无效输入,再来一遍 (0~{len(adapters)-1} / 回车 / q)")

    new_ip = adapters[picked][1]
    if new_ip == old_ip:
        print(f"\n选中的 IP = 旧 IP = {new_ip},未变更; 板 B 固件不用重编重烧.")
        return 0

    # 4. Y/n 确认
    print()
    print(f"      旧: {old_ip}")
    print(f"      新: {new_ip}")
    print(f"      确认改写 fall_alert_gateway_config.h ? [Y/n]")
    ans = input("      > ").strip().lower()
    if ans not in ("", "y", "yes"):
        print("已取消，固件不改。")
        return 0

    write_host_in_firmware(new_ip)
    print(f"\n[4/4] 已写入。下一步:")
    print(f"      a) 打开 HiSpark Studio,点 Build (锤子图标),等 'Build Success'")
    print(f"      b) BurnTool 烧固件到板 B:")
    print(f"         D:\\fbb_ws63\\fbb_ws63-master\\src\\output\\ws63\\fwpkg\\ws63-liteos-app\\ws63-liteos-app_all.fwpkg")
    print(f"      c) 笔记本上启动 backend:")
    print(f"         cd D:\\fbb_ws63\\SparkLink-FallDetection\\tools")
    print(f"         set -a && source ./fall_alert_backend.env && set +a")
    print(f"         python fall_alert_backend_demo.py")
    print(f"      d) 板 B 上电后应该能找到 backend = {new_ip}:8080")
    return 0


if __name__ == "__main__":
    sys.exit(main())
