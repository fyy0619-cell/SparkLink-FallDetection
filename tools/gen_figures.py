"""Generate diagrams for TECHNICAL_REPORT.docx (Chinese-friendly)."""
from __future__ import annotations

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

# --- Chinese font selection (Windows) ---
for candidate in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"):
    matplotlib.rcParams["font.sans-serif"] = [candidate]
    matplotlib.rcParams["axes.unicode_minus"] = False
    break

OUT = r"D:\SparkLink-FallDetection\assets\figures"
os.makedirs(OUT, exist_ok=True)

# Brand palette
C_PRIMARY = "#1F4E79"       # deep blue
C_ACCENT  = "#C00000"       # accent red (alerts)
C_OK      = "#2E7D32"       # green
C_WARN    = "#E8A33D"       # amber
C_BG      = "#F4F6FA"       # very light blue-gray
C_BG2     = "#E7ECF4"       # block bg
C_GRID    = "#D9D9D9"
C_TXT     = "#1A2230"


def _round_box(ax, x, y, w, h, *, fc, ec=C_PRIMARY, lw=1.4, text="", fs=11,
               color=C_TXT, bold=False):
    p = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.10",
        linewidth=lw, edgecolor=ec, facecolor=fc, zorder=2,
    )
    ax.add_patch(p)
    if text:
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=fs, color=color, zorder=3,
                fontweight="bold" if bold else "normal")


def _arrow(ax, x0, y0, x1, y1, *, color=C_PRIMARY, lw=1.6, ls="-"):
    a = FancyArrowPatch(
        (x0, y0), (x1, y1),
        arrowstyle="-|>", mutation_scale=14,
        linewidth=lw, color=color, zorder=2, linestyle=ls,
    )
    ax.add_patch(a)


# ---------------------------------------------------------------------------
# Fig 1. 系统总体架构 (三层)
# ---------------------------------------------------------------------------
def fig_arch():
    fig, ax = plt.subplots(figsize=(11.5, 6.8), dpi=170)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 9.2)
    ax.axis("off")

    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    # Layer backgrounds
    for y, label, fc in [
        (6.2, "感知层 Board A — WS63 + MPU6050 (腰部佩戴)", "#E3EEF9"),
        (3.4, "汇聚 / 报警层 Board B — SLE Client + Wi-Fi + 4G DTU", "#FFF1E5"),
        (0.6, "云端 / 家属层 — Python 后端 / PushPlus / GSM 拨号短信", "#E9F6EC"),
    ]:
        _round_box(ax, 0.2, y, 11.6, 2.6, fc=fc, ec="#B6C9DE", lw=1.0)
        ax.text(0.5, y + 2.35, label, fontsize=11, color=C_PRIMARY,
                fontweight="bold")

    # ---- 感知层 modules ----
    boxes_a = [
        (0.6, 6.9, "I2C\nMPU6050", "#FFFFFF"),
        (3.0, 6.9, "200 Hz 硬件\n定时器采样", "#FFFFFF"),
        (5.6, 6.9, "路径 B\n四段状态机", "#FFFFFF"),
        (8.0, 6.9, "Edge Impulse\nNN 复核", "#FFFFFF"),
        (10.4, 6.9, "SLE Server\n0xABCD/0xABCE", "#FFFFFF"),
    ]
    for x, y, t, fc in boxes_a:
        _round_box(ax, x, y, 1.4, 1.4, fc=fc, ec=C_PRIMARY, text=t, fs=9.4)
    for i in range(len(boxes_a) - 1):
        _arrow(ax, boxes_a[i][0] + 1.4, 7.6, boxes_a[i + 1][0], 7.6)

    # ---- 汇聚层 modules ----
    boxes_b = [
        (0.6, 4.1, "SLE Client\n收 0x05", "#FFFFFF"),
        (3.0, 4.1, "WS2812B 灯带\n+ 蜂鸣器", "#FFFFFF"),
        (5.6, 4.1, "Wi-Fi HTTP\nPOST", "#FFFFFF"),
        (8.0, 4.1, "UART → 4G\nV100C / Air780", "#FFFFFF"),
        (10.4, 4.1, "0x06 ACK\n回写 Server", "#FFFFFF"),
    ]
    for x, y, t, fc in boxes_b:
        _round_box(ax, x, y, 1.4, 1.4, fc=fc, ec="#C9621F", text=t, fs=9.4)
    # cross arrow A→B
    _arrow(ax, 11.1, 6.9, 1.3, 5.5, color=C_ACCENT, lw=2.2)
    ax.text(6.2, 6.05, "SLE  Notify  0x05  (≤ 12.5 ms)",
            color=C_ACCENT, fontsize=11, fontweight="bold")
    for i in range(len(boxes_b) - 1):
        _arrow(ax, boxes_b[i][0] + 1.4, 4.8, boxes_b[i + 1][0], 4.8,
               color="#C9621F")

    # ---- 云端 modules ----
    boxes_c = [
        (1.3, 1.3, "Python 后端\n(token / 限流)", "#FFFFFF"),
        (5.0, 1.3, "PushPlus 微信\n推送家属", "#FFFFFF"),
        (8.7, 1.3, "GSM 拨号\n+ 短信 SMS", "#FFFFFF"),
    ]
    for x, y, t, fc in boxes_c:
        _round_box(ax, x, y, 2.4, 1.5, fc=fc, ec=C_OK, text=t, fs=10)
    _arrow(ax, 6.2, 4.1, 2.5, 2.8, color=C_OK)
    _arrow(ax, 6.2, 4.1, 6.2, 2.8, color=C_OK)
    _arrow(ax, 8.7, 4.1, 9.9, 2.8, color=C_OK)

    plt.savefig(os.path.join(OUT, "fig_arch.png"),
                bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Fig 2. 200Hz 采样管线
# ---------------------------------------------------------------------------
def fig_pipeline():
    fig, ax = plt.subplots(figsize=(11.5, 5.6), dpi=170)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 7)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    # HW Timer
    _round_box(ax, 0.3, 5.4, 2.4, 1.2,
               fc="#FDEAEA", ec=C_ACCENT,
               text="HW Timer1\n5 ms 周期 (200 Hz)", fs=10.5, bold=True)
    # ISR
    _round_box(ax, 3.3, 5.4, 2.6, 1.2,
               fc="#FFF6E5", ec=C_WARN,
               text="ISR 回调\n只释放信号量", fs=10.5)
    # Sample task
    _round_box(ax, 6.5, 5.0, 5.0, 2.0,
               fc="#E3EEF9", ec=C_PRIMARY,
               text="采样任务 (优先级 AboveNormal)\n"
                    "① 重载定时器  ② 读 MPU6050\n"
                    "③ 入队 IMU sample (深度 128)",
               fs=10.3)

    _arrow(ax, 2.7, 6.0, 3.3, 6.0, color=C_ACCENT, lw=2)
    _arrow(ax, 5.9, 6.0, 6.5, 6.0, color=C_WARN, lw=2)

    # IMU queue
    _round_box(ax, 4.0, 2.6, 4.0, 1.4,
               fc="#FFFFFF", ec="#8895A8",
               text="IMU 队列\nosMessageQueue • depth = 128",
               fs=10.5, bold=True)

    _arrow(ax, 9.0, 5.0, 7.5, 4.0, color=C_PRIMARY, lw=2)

    # Detect task
    _round_box(ax, 0.3, 0.4, 5.4, 1.6,
               fc="#E9F6EC", ec=C_OK,
               text="路径 B 状态机\nFall_Algo_Process()\n确定性序列检测", fs=10.5)
    _round_box(ax, 6.3, 0.4, 5.2, 1.6,
               fc="#FDEAEA", ec=C_ACCENT,
               text="Edge Impulse NN\nEI_Fall_Classify()\n触发后同步复核", fs=10.5)

    _arrow(ax, 5.0, 2.6, 3.0, 2.0, color=C_OK, lw=2)
    _arrow(ax, 6.5, 2.6, 8.5, 2.0, color=C_ACCENT, lw=2)

    ax.text(6.0, 4.4, "队列解耦  采样不被推理阻塞",
            ha="center", fontsize=11, color="#445", style="italic")

    plt.savefig(os.path.join(OUT, "fig_pipeline.png"),
                bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Fig 3. 路径 B 状态机
# ---------------------------------------------------------------------------
def fig_state_machine():
    fig, ax = plt.subplots(figsize=(11.5, 5.6), dpi=170)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    states = [
        (0.2, 2.2, "IDLE",        "等待失重",                "#E3EEF9", C_PRIMARY),
        (2.7, 2.2, "FREEFALL",    "失重计时",                "#FFF6E5", C_WARN),
        (5.1, 2.2, "IMPACT_WAIT", "等冲击",                  "#FFE9D6", "#C9621F"),
        (7.5, 2.2, "POST_IMPACT", "沉降 0.5s\n静止 1s",       "#FDEAEA", C_ACCENT),
        (9.9, 2.2, "确认跌倒",   "返回 1\n→ 发 0x05",         "#E9F6EC", C_OK),
    ]
    for x, y, name, sub, fc, ec in states:
        _round_box(ax, x, y, 1.9, 1.6, fc=fc, ec=ec, text=f"{name}\n\n{sub}",
                   fs=9.8, bold=True)

    # arrows + conditions (上方标注, 避免与方框文字重叠)
    conds = [
        (2.45, "|acc| < 0.75 G"),
        (4.85, "失重 70-750 ms"),
        (7.25, "|acc| > 2.2 G"),
        (9.65, "四项齐全"),
    ]
    for i, (cx, cond) in enumerate(conds):
        x0 = states[i][0] + 1.9
        x1 = states[i + 1][0]
        _arrow(ax, x0, 3.0, x1, 3.0, color=C_PRIMARY, lw=1.8)
        ax.text(cx, 4.2, cond, ha="center", fontsize=9.5, color="#223",
                bbox=dict(boxstyle="round,pad=0.18", facecolor="white",
                          edgecolor="#CCC", lw=0.6))

    # 4 judges
    ax.text(0.3, 0.6,
            "四道判据 (200 Hz)\n"
            "① 自由落体  |acc| < 0.75 G, 持续 70 ms\n"
            "② 硬冲击    |acc| ≥ 4.0 G   (主判据)\n"
            "③ 冲击后静止  静止样本占比 ≥ 50%\n"
            "④ 倾角倒下  事件前后重力方向夹角 ≥ 45°",
            fontsize=10, color=C_TXT,
            bbox=dict(boxstyle="round,pad=0.6",
                      facecolor=C_BG, edgecolor=C_GRID))

    plt.savefig(os.path.join(OUT, "fig_state_machine.png"),
                bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Fig 4. B + NN 混合判定
# ---------------------------------------------------------------------------
def fig_hybrid():
    fig, ax = plt.subplots(figsize=(10.5, 5.8), dpi=170)
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 7)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    _round_box(ax, 0.3, 5.4, 10.4, 1.2,
               fc="#E3EEF9", ec=C_PRIMARY,
               text="200 Hz IMU 数据流 (|acc|, |gyro|)", fs=11, bold=True)

    _round_box(ax, 0.3, 3.0, 4.8, 1.9,
               fc="#E9F6EC", ec=C_OK,
               text="路径 B (主力 — 检出)\n四段确定性状态机\n"
                    "宁可多报 · 不漏报", fs=10.5, bold=True)
    _round_box(ax, 5.9, 3.0, 4.8, 1.9,
               fc="#FDEAEA", ec=C_ACCENT,
               text="路径 NN (复核 — 否决)\nEdge Impulse Conv1D\n"
                    "硬真摔 fall = 100%", fs=10.5, bold=True)
    _arrow(ax, 2.7, 5.4, 2.7, 4.9, color=C_PRIMARY, lw=2)
    _arrow(ax, 8.3, 5.4, 8.3, 4.9, color=C_PRIMARY, lw=2)

    _round_box(ax, 2.6, 0.5, 5.8, 1.9,
               fc="#FFF6E5", ec=C_WARN,
               text="协同：B 触发 OK  且  NN normal% < 95\n"
                    "→ 发星闪 0x05 报警，进入 3 s 冷却",
               fs=11, bold=True)
    _arrow(ax, 2.7, 3.0, 4.4, 2.4, color=C_OK, lw=2)
    _arrow(ax, 8.3, 3.0, 6.6, 2.4, color=C_ACCENT, lw=2)

    plt.savefig(os.path.join(OUT, "fig_hybrid.png"),
                bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Fig 5. impact 分界散点 — 蹲下 vs 真摔
# ---------------------------------------------------------------------------
def fig_threshold():
    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=170)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#FAFBFD")

    # 实测数据 (from 调参复盘 doc)
    squat_impact = np.array([2.32, 2.68, 3.05])
    squat_tilt   = np.array([61, 78, 91])
    fall_impact  = np.array([5.30, 11.57, 15.62, 16.05])
    fall_tilt    = np.array([73, 88, 95, 112])

    ax.scatter(squat_impact, squat_tilt, s=180, c=C_OK, marker="s",
               label="快速蹲下 / 用力坐下", edgecolor="white", linewidth=1.5,
               zorder=3)
    ax.scatter(fall_impact, fall_tilt, s=180, c=C_ACCENT, marker="o",
               label="真实跌倒", edgecolor="white", linewidth=1.5, zorder=3)

    ax.axvline(4.0, color="#444", linestyle="--", linewidth=2, zorder=2)
    ax.axhline(45,  color="#888", linestyle=":",  linewidth=1.4, zorder=2)
    ax.text(4.05, 110, "IMPACT_HARD_G = 4.0 G  (主判据)",
            color="#222", fontsize=10.5, fontweight="bold")
    ax.text(2.0, 42.5, "TILT_DEG_MIN = 45°", color="#666", fontsize=10)

    ax.set_xlabel("冲击峰值  |acc| (G)", fontsize=11)
    ax.set_ylabel("躯干倾角变化 (deg)", fontsize=11)
    ax.set_title("阈值标定数据：4.0 G 把跌倒和蹲下干净分开",
                 fontsize=13, color=C_PRIMARY, pad=12, fontweight="bold")
    ax.set_xlim(1.5, 18)
    ax.set_ylim(40, 120)
    ax.grid(alpha=0.5, color=C_GRID)
    ax.legend(loc="upper left", framealpha=1.0)

    plt.tight_layout()
    plt.savefig(os.path.join(OUT, "fig_threshold.png"),
                bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Fig 6. SLE vs BLE 延迟对比
# ---------------------------------------------------------------------------
def fig_sle_vs_ble():
    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=170)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#FAFBFD")

    labels = ["SLE\n规格下限", "SLE\n本工程实配", "BLE\n规格下限", "BLE\n仓库示例配置"]
    values = [1.0, 12.5, 7.5, 60.0]
    colors = [C_OK, C_PRIMARY, "#7E8A99", C_ACCENT]

    bars = ax.bar(labels, values, color=colors, edgecolor="white",
                  linewidth=2, width=0.6, zorder=3)
    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 1.5,
                f"{v} ms", ha="center", fontsize=11, fontweight="bold")

    ax.set_ylabel("单向 Notify 送达延迟 (ms, 最坏值)", fontsize=11)
    ax.set_title("SLE vs BLE — 通信链路延迟可量化对比",
                 fontsize=13, color=C_PRIMARY, pad=12, fontweight="bold")
    ax.set_ylim(0, 72)
    ax.grid(axis="y", alpha=0.5, color=C_GRID, zorder=1)
    ax.set_axisbelow(True)

    # callouts
    ax.annotate(
        "相对 BLE 示例配置\n≈ 5× 快",
        xy=(1, 12.5), xytext=(1.5, 38),
        fontsize=11, color=C_PRIMARY, fontweight="bold",
        arrowprops=dict(arrowstyle="-|>", color=C_PRIMARY, lw=1.8),
    )

    plt.tight_layout()
    plt.savefig(os.path.join(OUT, "fig_sle_vs_ble.png"),
                bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Fig 7. 端到端时序
# ---------------------------------------------------------------------------
def fig_timeline():
    fig, ax = plt.subplots(figsize=(11.5, 4.2), dpi=170)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    events = [
        (0,    "T0  失重 |acc|<0.75G", C_PRIMARY),
        (70,   "失重 ≥ 70 ms 确认",     C_PRIMARY),
        (200,  "冲击 |acc|>4G",         C_WARN),
        (700,  "沉降期结束\n开始静止统计", "#666"),
        (1700, "四项齐全\n路径 B 确认",   C_OK),
        (1720, "NN 复核 fall=100%",      C_OK),
        (1750, "SLE Notify 0x05",        C_ACCENT),
        (1762, "板 B 触发声光报警",       C_ACCENT),
        (1800, "Wi-Fi POST 上报",         C_ACCENT),
        (2500, "PushPlus 推送家属",       C_OK),
    ]

    times = [e[0] for e in events]
    ax.hlines(0, 0, max(times) * 1.05, color="#BBB", linewidth=2.2, zorder=1)

    for t, label, color in events:
        ax.plot(t, 0, "o", markersize=11, color=color, zorder=3)
        # alternate above/below
        idx = events.index((t, label, color))
        y = 0.55 if idx % 2 == 0 else -0.65
        va = "bottom" if y > 0 else "top"
        ax.text(t, y, label, ha="center", va=va, fontsize=9.5,
                color="#222")

    ax.set_xlim(-100, 2700)
    ax.set_ylim(-1.6, 1.6)
    ax.set_xlabel("时间 (ms 自跌倒发生起)", fontsize=11)
    ax.set_yticks([])
    for spine in ("left", "right", "top"):
        ax.spines[spine].set_visible(False)
    ax.set_title("一次真实跌倒 — 端到端时序",
                 fontsize=13, color=C_PRIMARY, pad=10, fontweight="bold")

    plt.tight_layout()
    plt.savefig(os.path.join(OUT, "fig_timeline.png"),
                bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Fig 8. 全局技术地图  需求 -> 挑战 -> 我们的回答 -> 产出
# ---------------------------------------------------------------------------
def fig_overview():
    fig, ax = plt.subplots(figsize=(12, 6.4), dpi=170)
    fig.patch.set_facecolor("white")
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 9)
    ax.axis("off")

    # 4 column headers
    headers = [
        (0.3, 8.0, 3.0, "① 社会需求",      C_PRIMARY),
        (3.6, 8.0, 3.0, "② 技术挑战",      C_ACCENT),
        (6.9, 8.0, 3.0, "③ 我们的回答",     C_OK),
        (10.2, 8.0, 3.5, "④ 系统产出",     C_WARN),
    ]
    for x, y, w, t, ec in headers:
        _round_box(ax, x, y, w, 0.7, fc="white", ec=ec, lw=2,
                   text=t, fs=12, bold=True, color=ec)

    # column 1 — needs
    needs = [
        "独居老人摔倒\n第一时间被发现",
        "户外运动 / 康复\n脱机也能报警",
        "智能手表 / 摄像\n隐私 + 误报问题",
    ]
    for i, t in enumerate(needs):
        _round_box(ax, 0.3, 6.4 - i * 2.0, 3.0, 1.4,
                   fc="#E3EEF9", ec=C_PRIMARY, text=t, fs=10)

    # column 2 — challenges
    chals = [
        "200 Hz 严格采样\nLiteOS tick=10ms",
        "区分摔与蹲下\n物理 vs ML",
        "端侧资源紧\n40 KB AI 内存",
    ]
    for i, t in enumerate(chals):
        _round_box(ax, 3.6, 6.4 - i * 2.0, 3.0, 1.4,
                   fc="#FDEAEA", ec=C_ACCENT, text=t, fs=10)

    # column 3 — our answers
    answers = [
        "硬件 timer 5ms 节拍\n+ 双任务 + 队列",
        "B 触发 + NN 复核\n四段状态机 + 1D Conv",
        "全静态内存池\nplacement-new",
    ]
    for i, t in enumerate(answers):
        _round_box(ax, 6.9, 6.4 - i * 2.0, 3.0, 1.4,
                   fc="#E9F6EC", ec=C_OK, text=t, fs=10)

    # column 4 — outputs
    outs = [
        "硬真摔 fall=100%\n蹲坐跳零误报",
        "SLE 12.5ms 单向\nvs BLE 60ms (5×)",
        "Wi-Fi + 4G 三级\n冗余告警闭环",
    ]
    for i, t in enumerate(outs):
        _round_box(ax, 10.2, 6.4 - i * 2.0, 3.5, 1.4,
                   fc="#FFF6E5", ec=C_WARN, text=t, fs=10)

    # connector arrows between columns
    for i in range(3):
        y = 7.1 - i * 2.0
        _arrow(ax, 3.3, y, 3.6, y, color="#888", lw=1.4)
        _arrow(ax, 6.6, y, 6.9, y, color="#888", lw=1.4)
        _arrow(ax, 9.9, y, 10.2, y, color="#888", lw=1.4)

    # bottom slogan
    _round_box(ax, 1.5, 0.2, 11, 0.9,
               fc="#1F4E79", ec="#1F4E79",
               text="一句话：物理建模做主力 · 神经网络做复核 · 国产星闪做血脉 · 三级冗余落地告警",
               fs=11.5, color="white", bold=True)

    plt.savefig(os.path.join(OUT, "fig_overview.png"),
                bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Fig 9. 问题层次拆解
# ---------------------------------------------------------------------------
def fig_problem_decomp():
    fig, ax = plt.subplots(figsize=(12, 6.6), dpi=170)
    fig.patch.set_facecolor("white")
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 8)
    ax.axis("off")

    # Layer 0 — social problem
    _round_box(ax, 4.0, 6.8, 6.0, 1.0,
               fc="#1F4E79", ec="#1F4E79",
               text="社会问题：跌倒后无人发现 → 错过黄金救治窗口",
               fs=12, color="white", bold=True)

    # Layer 1 — three sub-problems
    sub = [
        (0.3, 4.6, 4.2, "①  感知问题\n如何低成本、隐私友好地\n感知人体跌倒？", C_PRIMARY),
        (4.9, 4.6, 4.2, "②  判定问题\n如何区分跌倒 vs\n蹲、坐、跳？", C_ACCENT),
        (9.5, 4.6, 4.2, "③  传输问题\n如何把告警低延迟、\n可靠送出去？", C_OK),
    ]
    for x, y, w, t, c in sub:
        _round_box(ax, x, y, w, 1.6, fc="white", ec=c, lw=2,
                   text=t, fs=10.5, color=c, bold=True)
        _arrow(ax, x + w / 2, 6.8, x + w / 2, 6.2, color="#666", lw=1.4)

    # Layer 2 — concrete answers
    answers = [
        (0.3, 2.4, 4.2,
         "腰部 MPU6050\n+ 200 Hz 硬件定时器采样",
         "幅值特征 |acc|/|gyro|\n旋转不变、隐私友好"),
        (4.9, 2.4, 4.2,
         "路径 B：四段确定性状态机\n(失重→冲击→静止→倾角)",
         "路径 NN：Edge Impulse\n1D Conv + Flatten 复核"),
        (9.5, 2.4, 4.2,
         "SLE 板间 12.5 ms 单向\n+ Wi-Fi HTTP / 4G DTU",
         "三级冗余：本地 + 室内 + 户外\n全部场景覆盖"),
    ]
    for x, y, w, a1, a2 in answers:
        _round_box(ax, x, y, w, 1.7,
                   fc="#F4F6FA", ec="#8895A8",
                   text=a1 + "\n\n" + a2, fs=9.5)
        _arrow(ax, x + w / 2, 4.6, x + w / 2, 4.1, color="#666", lw=1.4)

    # bottom row
    _round_box(ax, 4.0, 0.4, 6.0, 1.0,
               fc="#E9F6EC", ec=C_OK, lw=2,
               text="项目交付：可解释 · 低误报 · 国产星闪 · 全栈打通",
               fs=11, bold=True, color=C_OK)

    plt.savefig(os.path.join(OUT, "fig_problem_decomp.png"),
                bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Fig 10. 设计决策树
# ---------------------------------------------------------------------------
def fig_decision_tree():
    fig, ax = plt.subplots(figsize=(12, 7.4), dpi=170)
    fig.patch.set_facecolor("white")
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 9)
    ax.axis("off")

    # Root question
    _round_box(ax, 4.5, 7.8, 5.0, 0.9,
               fc="#1F4E79", ec="#1F4E79",
               text="如何做端侧跌倒检测？", fs=12, color="white", bold=True)

    # Branch 1 — 算法选型
    _round_box(ax, 0.3, 5.6, 4.2, 1.2,
               fc="#FDEAEA", ec=C_ACCENT,
               text="算法：纯 AI / 纯规则 / 混合？",
               fs=10.5, bold=True, color=C_ACCENT)
    _round_box(ax, 0.3, 3.7, 4.2, 1.4,
               fc="#E9F6EC", ec=C_OK,
               text="● 混合\nB 触发 (不漏报)\n+ NN 否决 (不误报)",
               fs=10.5, bold=True, color=C_OK)
    _round_box(ax, 0.3, 1.6, 4.2, 1.6,
               fc="white", ec="#999",
               text="× 纯 AI：漏检不可控\n× 纯规则：边角案例误报",
               fs=9.5, color="#444")

    # Branch 2 — 通信选型
    _round_box(ax, 4.9, 5.6, 4.2, 1.2,
               fc="#FFF6E5", ec=C_WARN,
               text="通信：BLE / SLE / Wi-Fi / 4G？",
               fs=10.5, bold=True, color="#9F6B1A")
    _round_box(ax, 4.9, 3.7, 4.2, 1.4,
               fc="#E9F6EC", ec=C_OK,
               text="● SLE 板间 (12.5ms)\n+ 三级冗余 (本地/Wi-Fi/4G)",
               fs=10.5, bold=True, color=C_OK)
    _round_box(ax, 4.9, 1.6, 4.2, 1.6,
               fc="white", ec="#999",
               text="× 纯 BLE：延迟 5×\n× 纯 Wi-Fi：户外无网",
               fs=9.5, color="#444")

    # Branch 3 — 采样选型
    _round_box(ax, 9.5, 5.6, 4.2, 1.2,
               fc="#E3EEF9", ec=C_PRIMARY,
               text="采样：osDelay / 硬件 timer？",
               fs=10.5, bold=True, color=C_PRIMARY)
    _round_box(ax, 9.5, 3.7, 4.2, 1.4,
               fc="#E9F6EC", ec=C_OK,
               text="● 硬件 timer 5ms\n+ ISR 释放信号量",
               fs=10.5, bold=True, color=C_OK)
    _round_box(ax, 9.5, 1.6, 4.2, 1.6,
               fc="white", ec="#999",
               text="× osDelay(1)=10ms\n无法表达 200 Hz",
               fs=9.5, color="#444")

    # connectors
    for x in (2.4, 7.0, 11.6):
        _arrow(ax, 7.0, 7.8, x, 6.8, color="#666", lw=1.4)
        _arrow(ax, x, 5.6, x, 5.1, color=C_OK, lw=1.6)
        _arrow(ax, x, 3.7, x, 3.2, color="#999", lw=1.0, ls=":")

    # legend
    ax.text(0.3, 0.6, "● = 本项目选择    × = 评估后排除",
            fontsize=10, color="#444", style="italic")

    plt.savefig(os.path.join(OUT, "fig_decision_tree.png"),
                bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Fig 11. 能力矩阵 雷达图
# ---------------------------------------------------------------------------
def fig_capability_radar():
    categories = ["实时性", "可靠性", "可解释性", "低功耗", "隐私保护",
                  "数据效率", "星闪契合", "工程完整性"]
    # 0-5 scale
    ours      = [4.5, 4.6, 4.8, 4.0, 5.0, 4.0, 4.7, 4.8]
    pure_ai   = [3.5, 3.2, 2.0, 3.5, 4.5, 2.0, 3.0, 3.0]
    pure_rule = [4.0, 3.8, 5.0, 4.2, 5.0, 5.0, 3.0, 3.5]
    smartwatch= [3.0, 4.0, 2.5, 2.5, 3.0, 3.5, 1.0, 3.0]

    N = len(categories)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(9, 7), dpi=170,
                           subplot_kw={"projection": "polar"})
    fig.patch.set_facecolor("white")

    def _plot(values, color, label, lw=2.2):
        v = values + values[:1]
        ax.plot(angles, v, "-", color=color, linewidth=lw, label=label)
        ax.fill(angles, v, color=color, alpha=0.18)

    _plot(ours,       C_ACCENT,  "本项目 (B+NN 混合)", lw=2.6)
    _plot(pure_ai,    "#7A9BD8", "纯 AI 端侧方案")
    _plot(pure_rule,  "#9DB89D", "纯规则阈值法")
    _plot(smartwatch, "#C99",    "智能手表方案")

    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_thetagrids(np.degrees(angles[:-1]), categories,
                      fontsize=11, color="#222")
    ax.set_ylim(0, 5)
    ax.set_yticks([1, 2, 3, 4, 5])
    ax.set_yticklabels(["1", "2", "3", "4", "5"], color="#888", fontsize=8)
    ax.set_rlabel_position(180 / N)
    ax.grid(color=C_GRID, alpha=0.7)
    ax.spines["polar"].set_color(C_GRID)

    plt.title("项目能力矩阵 vs 主流方案对比",
              fontsize=13, color=C_PRIMARY, pad=24, fontweight="bold")
    plt.legend(loc="lower right", bbox_to_anchor=(1.35, -0.05),
               fontsize=10, framealpha=1.0)

    plt.savefig(os.path.join(OUT, "fig_capability_radar.png"),
                bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# 物理示意图辅助：人体侧面剪影 + IMU + 重力向量
# ---------------------------------------------------------------------------
def _rot(pts, theta_deg, cx, cy):
    th = np.deg2rad(theta_deg)
    c, s = np.cos(th), np.sin(th)
    out = []
    for x, y in pts:
        dx, dy = x - cx, y - cy
        out.append((cx + c * dx - s * dy, cy + s * dx + c * dy))
    return out


def _draw_person_side(ax, cx, cy, *, rot=0.0, scale=1.0,
                      skin="#F2D6BA", suit="#34536B",
                      imu_label="MPU6050", show_imu=True,
                      gravity_in_imu=True):
    """Draw a side-view human silhouette at (cx, cy) (hip joint) rotated by
    rot degrees (around the hip). Returns the rotated hip and IMU world coords
    so the caller can attach annotations.
    """
    s = scale
    # Skeleton in local coords (hip at origin, body axis +y up)
    head_c    = (0.0,   1.55 * s)
    neck      = (0.0,   1.20 * s)
    shoulder  = (0.0,   1.10 * s)
    elbow     = (0.18 * s,  0.65 * s)
    wrist     = (0.05 * s,  0.15 * s)
    hip       = (0.0,   0.0)
    knee      = (-0.04 * s, -0.85 * s)
    ankle     = (-0.18 * s, -1.65 * s)
    toe       = (0.05 * s, -1.70 * s)

    # Torso outline (hip-narrow, chest-wider, shoulder-narrow): hexagon
    torso = [
        (-0.20 * s, 0.05 * s),   # hip left
        (-0.26 * s, 0.55 * s),   # chest left
        (-0.22 * s, 1.05 * s),   # shoulder left
        ( 0.22 * s, 1.05 * s),   # shoulder right
        ( 0.26 * s, 0.55 * s),   # chest right
        ( 0.20 * s, 0.05 * s),   # hip right
    ]

    # IMU patch local pos & corners (waist-front: slightly forward of hip)
    imu_c  = (0.30 * s, 0.20 * s)
    imu_w  = 0.32 * s
    imu_h  = 0.22 * s
    imu_corners_local = [
        (imu_c[0] - imu_w / 2, imu_c[1] - imu_h / 2),
        (imu_c[0] + imu_w / 2, imu_c[1] - imu_h / 2),
        (imu_c[0] + imu_w / 2, imu_c[1] + imu_h / 2),
        (imu_c[0] - imu_w / 2, imu_c[1] + imu_h / 2),
    ]

    # Rotate everything around (0,0) then translate
    def world(p):
        x, y = p
        th = np.deg2rad(rot)
        c, sn = np.cos(th), np.sin(th)
        return (cx + c * x - sn * y, cy + sn * x + c * y)

    torso_w     = [world(p) for p in torso]
    head_w      = world(head_c)
    neck_w      = world(neck)
    shoulder_w  = world(shoulder)
    elbow_w     = world(elbow)
    wrist_w     = world(wrist)
    hip_w       = world(hip)
    knee_w      = world(knee)
    ankle_w     = world(ankle)
    toe_w       = world(toe)
    imu_world_c = world(imu_c)
    imu_world_corners = [world(p) for p in imu_corners_local]

    # Torso polygon
    torso_poly = mpatches.Polygon(torso_w, closed=True, facecolor=suit,
                                  edgecolor="#1A2230", linewidth=1.4, zorder=2)
    ax.add_patch(torso_poly)

    # Head (ellipse, long axis along body)
    # Approximate as circle since rotation is uniform anyway
    head_patch = mpatches.Circle(head_w, 0.20 * s, facecolor=skin,
                                 edgecolor="#1A2230", linewidth=1.4, zorder=3)
    ax.add_patch(head_patch)

    # Neck line
    ax.plot([neck_w[0], shoulder_w[0]], [neck_w[1], shoulder_w[1]],
            color="#1A2230", linewidth=2.2, zorder=2)

    # Limbs (thick lines)
    def _seg(p1, p2, color, lw=5.0):
        ax.plot([p1[0], p2[0]], [p1[1], p2[1]], color=color, linewidth=lw,
                solid_capstyle="round", zorder=2)

    _seg(shoulder_w, elbow_w, suit, lw=5.0)
    _seg(elbow_w,    wrist_w, skin, lw=4.4)
    _seg(hip_w,      knee_w,  suit, lw=5.4)
    _seg(knee_w,     ankle_w, suit, lw=5.4)
    _seg(ankle_w,    toe_w,   "#1A2230", lw=3.4)

    if show_imu:
        imu_poly = mpatches.Polygon(imu_world_corners, closed=True,
                                    facecolor="#FFFFFF",
                                    edgecolor=C_ACCENT, linewidth=1.6,
                                    zorder=4)
        ax.add_patch(imu_poly)
        if imu_label:
            ax.text(imu_world_c[0], imu_world_c[1], imu_label,
                    ha="center", va="center", fontsize=7.5,
                    color=C_ACCENT, fontweight="bold", zorder=5)

        if gravity_in_imu:
            # Gravity arrow attached to IMU center, ALWAYS pointing world -y
            glen = 0.55 * s
            gx0, gy0 = imu_world_c
            gx1, gy1 = gx0, gy0 - glen
            ax.annotate(
                "", xy=(gx1, gy1), xytext=(gx0, gy0),
                arrowprops=dict(arrowstyle="-|>", color=C_ACCENT, lw=1.8),
                zorder=5,
            )
            ax.text(gx1 + 0.05 * s, gy1 - 0.05 * s, "g",
                    fontsize=10, color=C_ACCENT, fontweight="bold", zorder=6,
                    style="italic")

    return {"hip": hip_w, "imu": imu_world_c, "head": head_w,
            "shoulder": shoulder_w}


# ---------------------------------------------------------------------------
# Fig 12. 5.1.1 加速度计物理本质 — 比力 (静止 vs 自由落体)
# ---------------------------------------------------------------------------
def fig_physics_specific_force():
    fig, ax = plt.subplots(figsize=(11.5, 5.6), dpi=170)
    fig.patch.set_facecolor("white")
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6)
    ax.axis("off")

    ax.text(6.0, 5.55, "加速度计测量的是 “比力 (specific force)”",
            ha="center", fontsize=14, fontweight="bold", color=C_PRIMARY)
    ax.text(6.0, 5.15,
            "—— 除重力之外作用在它身上的所有力的合力, 单位 G (1 G = 9.81 m/s²)",
            ha="center", fontsize=10.5, color="#445", style="italic")

    # ---- Left panel: 静止 ----
    _round_box(ax, 0.3, 0.4, 5.5, 4.4, fc=C_BG, ec=C_PRIMARY, lw=1.6)
    ax.text(3.05, 4.45, "① 静止 (放在桌面 / 直立站立)",
            ha="center", fontsize=12, fontweight="bold", color=C_PRIMARY)

    # IMU box
    _round_box(ax, 2.4, 2.2, 1.3, 0.85, fc="white", ec=C_PRIMARY, lw=1.6,
               text="IMU", fs=10, bold=True, color=C_PRIMARY)
    # Ground
    ax.plot([0.8, 5.3], [1.5, 1.5], color="#333", linewidth=2.4)
    for xx in np.linspace(0.95, 5.15, 14):
        ax.plot([xx, xx - 0.18], [1.5, 1.32], color="#333", linewidth=1.0)

    # Support force ↑ (from ground)
    ax.annotate("", xy=(3.05, 2.18), xytext=(3.05, 1.55),
                arrowprops=dict(arrowstyle="-|>", color=C_OK, lw=2.5))
    ax.text(3.4, 1.85, "支撑力\nF_N = mg ↑", color=C_OK,
            fontsize=10, fontweight="bold")
    # Gravity ↓
    ax.annotate("", xy=(2.55, 1.55), xytext=(2.55, 2.18),
                arrowprops=dict(arrowstyle="-|>", color=C_ACCENT, lw=2.5))
    ax.text(1.55, 1.85, "重力\nmg ↓", color=C_ACCENT,
            fontsize=10, fontweight="bold", ha="right")

    # Reading
    _round_box(ax, 1.1, 0.55, 3.9, 0.75, fc="white", ec=C_OK, lw=1.8,
               text="读数 |acc| = 1 G    (= 支撑力)", fs=11, bold=True,
               color=C_OK)

    # ---- Right panel: 自由落体 ----
    _round_box(ax, 6.2, 0.4, 5.5, 4.4, fc="#FDEAEA", ec=C_ACCENT, lw=1.6)
    ax.text(8.95, 4.45, "② 自由落体 (失去支撑下坠)",
            ha="center", fontsize=12, fontweight="bold", color=C_ACCENT)

    # IMU box (no ground beneath)
    _round_box(ax, 8.3, 2.5, 1.3, 0.85, fc="white", ec=C_ACCENT, lw=1.6,
               text="IMU", fs=10, bold=True, color=C_ACCENT)
    # Motion arrows (falling)
    for dy, col in [(0.0, "#888"), (-0.35, "#AAA"), (-0.7, "#CCC")]:
        ax.annotate("", xy=(8.95, 1.7 + dy), xytext=(8.95, 1.95 + dy),
                    arrowprops=dict(arrowstyle="-|>", color=col, lw=1.6))
    ax.text(9.85, 1.9, "下坠中\n无支撑面", color="#666",
            fontsize=10, fontweight="bold")

    # Gravity ↓ only
    ax.annotate("", xy=(7.95, 2.0), xytext=(7.95, 2.65),
                arrowprops=dict(arrowstyle="-|>", color=C_ACCENT, lw=2.5))
    ax.text(6.95, 2.3, "重力\nmg ↓", color=C_ACCENT,
            fontsize=10, fontweight="bold", ha="right")
    # Crossed-out support force
    ax.text(7.05, 3.6, "F_N = 0  (失去支撑)", color="#888",
            fontsize=10, fontweight="bold", style="italic")

    # Reading
    _round_box(ax, 7.0, 0.55, 3.9, 0.75, fc="white", ec=C_ACCENT, lw=1.8,
               text="读数 |acc| ≈ 0 G    (失重)", fs=11, bold=True,
               color=C_ACCENT)

    # Footer takeaway
    ax.text(6.0, 0.05,
            "★ 静止时 |acc| 恒 ≈ 1 G, 与姿态无关 → 这是后续 4 道判据的零点",
            ha="center", fontsize=10.5, color=C_PRIMARY, fontweight="bold")

    plt.savefig(os.path.join(OUT, "fig_physics_specific_force.png"),
                bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Fig 13. 5.1.2-5.1.4 跌倒 4 阶段序列 (核心物理示意图)
# ---------------------------------------------------------------------------
def fig_fall_sequence():
    fig, ax = plt.subplots(figsize=(15, 9.6), dpi=170)
    fig.patch.set_facecolor("white")
    ax.set_xlim(0, 15)
    ax.set_ylim(0, 9.6)
    ax.axis("off")

    ax.text(7.5, 9.25,
            "跌倒过程的 4 个物理阶段 (200 Hz 采样, 腰部 IMU 观察)",
            ha="center", fontsize=14, fontweight="bold", color=C_PRIMARY)

    # State ribbon at top
    band_y = 8.20
    stages = [
        ("IDLE",         "#1F4E79", 2.4, 4.6,   0, 0.80,
         "|acc| = 1.00 G\ntilt = 0°"),
        ("FREEFALL",     "#E8A33D", 6.0, 4.9,  10, 0.80,
         "|acc| = 0.21 – 0.71 G\ntilt = 5° – 15°"),
        ("IMPACT_WAIT",  "#C9621F", 9.6, 3.5, -55, 0.80,
         "|acc| 峰 = 5.30 – 16.05 G\nΔt ≤ 16 ms"),
        ("POST_IMPACT",  "#C00000", 12.8, 3.4, -88, 0.70,
         "|acc| ≈ 1.0 G (静止)\ntilt = 73° – 112°"),
    ]

    for name, color, x, _y, _rot, _sc, _txt in stages:
        _round_box(ax, x - 1.35, band_y, 2.7, 0.85,
                   fc="white", ec=color, lw=2,
                   text=name, fs=11.5, bold=True, color=color)

    conds = [
        (4.20, "|acc| < 0.75 G\n持续 70 ms"),
        (7.80, "失重段结束\n|acc| > 2.2 G"),
        (11.20, "跳过 0.5 s 沉降\n统计 1 s 静止"),
    ]
    for i, (cx, cond) in enumerate(conds):
        x0 = stages[i][2] + 1.35
        x1 = stages[i + 1][2] - 1.35
        _arrow(ax, x0, band_y + 0.42, x1, band_y + 0.42,
               color="#666", lw=1.7)
        ax.text(cx, band_y - 0.30, cond, ha="center", fontsize=8.8,
                color="#223",
                bbox=dict(boxstyle="round,pad=0.20", facecolor="white",
                          edgecolor="#CCC", lw=0.6))

    # Ground line
    ground_y = 1.85
    ax.plot([0.2, 14.8], [ground_y, ground_y], color="#333", linewidth=2.2)
    for xx in np.linspace(0.35, 14.65, 75):
        ax.plot([xx, xx - 0.15], [ground_y, ground_y - 0.15],
                color="#333", linewidth=0.7)

    # Draw each person
    for name, color, cx, cy, rot, sc, _txt in stages:
        _draw_person_side(ax, cx, cy, rot=rot, scale=sc,
                          suit=color if name != "IDLE" else "#34536B")

    # Stage 2: motion lines for falling
    for off in (-0.20, 0.05, 0.30):
        ax.annotate("", xy=(6.0 + off, ground_y + 0.20),
                    xytext=(6.0 + off, ground_y + 1.05),
                    arrowprops=dict(arrowstyle="-|>", color="#888",
                                    lw=1.2, linestyle="--"))
    ax.text(6.0, ground_y - 0.30, "下坠", ha="center", fontsize=9.5,
            color="#666", fontweight="bold")

    # Stage 3: impact starburst on ground
    for ang in range(0, 360, 30):
        r0 = 0.05
        r1 = 0.34
        a = np.deg2rad(ang)
        ax.plot([9.6 + r0 * np.cos(a), 9.6 + r1 * np.cos(a)],
                [ground_y + 0.02 + r0 * np.sin(a),
                 ground_y + 0.02 + r1 * np.sin(a)],
                color=C_ACCENT, linewidth=1.8)
    ax.text(9.6, ground_y - 0.30, "撞地",
            ha="center", fontsize=9.5, color=C_ACCENT, fontweight="bold")

    # Stage 4: tilt arc — rotation of body axis from world vertical
    cx4, cy4 = stages[3][2], stages[3][3]
    arc = mpatches.Arc((cx4, cy4), 1.5, 1.5, angle=0, theta1=2, theta2=88,
                       color=C_OK, linewidth=2.4)
    ax.add_patch(arc)
    ax.text(cx4 + 0.95, cy4 + 0.55, "Δθ ≈ 88°\n(≥ TILT_MIN = 45°)",
            fontsize=9.5, color=C_OK, fontweight="bold")

    # Bottom data bar — outside ground, well-separated
    bar_y = 0.30
    for name, color, cx, _cy, _rot, _sc, txt in stages:
        _round_box(ax, cx - 1.50, bar_y, 3.0, 1.05,
                   fc="#F4F6FA", ec=color, lw=1.6,
                   text=txt, fs=10.5, color=C_TXT)

    # Physics-law side note (left side, mid-height)
    note = ("牛顿第二定律  F = m · a    →    撞地越硬 (Δt 越小) → a 越大\n"
            "冲量定理       F · Δt = Δ(m · v)    →    跌倒和蹲下的根本物理差异")
    ax.text(0.30, 7.10, note, fontsize=9.8, color="#222",
            bbox=dict(boxstyle="round,pad=0.45", facecolor=C_BG2,
                      edgecolor=C_GRID))

    plt.savefig(os.path.join(OUT, "fig_fall_sequence.png"),
                bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Fig 14. 5.1.3 跌倒 vs 快速蹲下 — 冲击波形物理对比
# ---------------------------------------------------------------------------
def fig_fall_vs_squat_impact():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.6), dpi=170,
                                   gridspec_kw={"wspace": 0.22})
    fig.patch.set_facecolor("white")

    fig.suptitle("撞地是 “失控刹停”, 蹲坐是 “肌肉缓冲刹停” —— "
                 "冲量定理 F · Δt = Δ(mv)",
                 fontsize=13, color=C_PRIMARY, fontweight="bold", y=0.99)

    t = np.linspace(0, 0.40, 800)  # 400 ms window

    # ---- 真实跌倒：尖锐冲击峰 ----
    # baseline 1G, FF 段下到 0.3G, 撞地瞬间冲到 ~12G, 然后回 1G
    a_fall = np.full_like(t, 1.0)
    ff_mask = (t > 0.05) & (t < 0.20)
    a_fall[ff_mask] = 0.35
    # sharp impact pulse around t=0.205 with FWHM ~12 ms
    impact_t0 = 0.205
    a_fall += 11.0 * np.exp(-((t - impact_t0) / 0.008) ** 2)
    # settle wobble
    a_fall += 0.15 * np.exp(-((t - 0.27) / 0.05) ** 2)

    ax1.plot(t * 1000, a_fall, color=C_ACCENT, linewidth=2.2)
    ax1.fill_between(t * 1000, 0, a_fall, color=C_ACCENT, alpha=0.15)
    ax1.axhline(4.0, color="#444", linestyle="--", linewidth=1.6)
    ax1.axhline(1.0, color="#999", linestyle=":",  linewidth=1.0)
    ax1.axhline(0.75, color="#999", linestyle=":", linewidth=1.0)

    ax1.text(295, 4.25, "IMPACT_HARD_G = 4.0 G", color="#222",
             fontsize=10, fontweight="bold")
    ax1.text(395, 1.1,  "1 G 基线", color="#666", fontsize=9, ha="right")
    ax1.text(395, 0.82, "FF_ACC_G = 0.75 G", color="#666", fontsize=9,
             ha="right")
    ax1.annotate("冲击峰 ≈ 5 – 16 G\n(实测 5.30 / 11.57 / 15.62 / 16.05)",
                 xy=(205, 12.0), xytext=(238, 13.5),
                 fontsize=10, color=C_ACCENT, fontweight="bold",
                 arrowprops=dict(arrowstyle="-|>", color=C_ACCENT, lw=1.6))
    ax1.annotate("自由落体段\n|acc| ≈ 0.3 G", xy=(120, 0.35),
                 xytext=(60, 6.5), fontsize=10, color="#A0581E",
                 fontweight="bold",
                 arrowprops=dict(arrowstyle="-|>", color="#A0581E", lw=1.4))
    # Δt annotation
    ax1.annotate("", xy=(220, 2.0), xytext=(190, 2.0),
                 arrowprops=dict(arrowstyle="<|-|>", color=C_PRIMARY, lw=1.4))
    ax1.text(205, 2.3, "Δt ≈ 10 ms", ha="center", fontsize=9,
             color=C_PRIMARY, fontweight="bold")

    ax1.set_title("(a) 真实跌倒 — 失控撞地", fontsize=12,
                  color=C_ACCENT, fontweight="bold")
    ax1.set_xlabel("时间 (ms)", fontsize=11)
    ax1.set_ylabel("|acc| (G)", fontsize=11)
    ax1.set_xlim(0, 400)
    ax1.set_ylim(0, 17)
    ax1.grid(alpha=0.5, color=C_GRID)

    # ---- 快速蹲下：钝峰 ----
    a_squat = np.full_like(t, 1.0)
    # mild dip 0.6G (轻微失重感)
    dip_mask = (t > 0.08) & (t < 0.16)
    a_squat[dip_mask] = 0.65
    # broad impact ~2.8G, FWHM ~80 ms
    a_squat += 1.8 * np.exp(-((t - 0.22) / 0.040) ** 2)

    ax2.plot(t * 1000, a_squat, color=C_OK, linewidth=2.2)
    ax2.fill_between(t * 1000, 0, a_squat, color=C_OK, alpha=0.15)
    ax2.axhline(4.0, color="#444", linestyle="--", linewidth=1.6)
    ax2.axhline(1.0, color="#999", linestyle=":",  linewidth=1.0)
    ax2.axhline(0.75, color="#999", linestyle=":", linewidth=1.0)

    ax2.text(295, 4.25, "IMPACT_HARD_G = 4.0 G", color="#222",
             fontsize=10, fontweight="bold")
    ax2.annotate("钝峰 ≈ 2.3 – 3.1 G\n(实测 2.32 / 2.68 / 3.05)\n→ 拦在阈值下",
                 xy=(220, 2.8), xytext=(245, 8.0),
                 fontsize=10, color=C_OK, fontweight="bold",
                 arrowprops=dict(arrowstyle="-|>", color=C_OK, lw=1.6))
    # Δt annotation
    ax2.annotate("", xy=(270, 1.6), xytext=(170, 1.6),
                 arrowprops=dict(arrowstyle="<|-|>", color=C_PRIMARY, lw=1.4))
    ax2.text(220, 1.85, "Δt ≈ 100 ms (肌肉缓冲)",
             ha="center", fontsize=9, color=C_PRIMARY, fontweight="bold")

    ax2.set_title("(b) 快速蹲下 — 肌肉控制刹停", fontsize=12,
                  color=C_OK, fontweight="bold")
    ax2.set_xlabel("时间 (ms)", fontsize=11)
    ax2.set_ylabel("|acc| (G)", fontsize=11)
    ax2.set_xlim(0, 400)
    ax2.set_ylim(0, 17)
    ax2.grid(alpha=0.5, color=C_GRID)

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    plt.savefig(os.path.join(OUT, "fig_fall_vs_squat_impact.png"),
                bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Fig 15. 5.1.5 倾角判据 — 重力向量旋转 ~90°
# ---------------------------------------------------------------------------
def fig_tilt_judgment():
    fig, ax = plt.subplots(figsize=(13, 7.6), dpi=170)
    fig.patch.set_facecolor("white")
    ax.set_xlim(0, 13)
    ax.set_ylim(0, 7.6)
    ax.axis("off")

    ax.text(6.5, 7.25,
            "倾角判据 — 比较 “事件前直立时重力方向” 与 “冲击后静止时重力方向”",
            ha="center", fontsize=13, fontweight="bold", color=C_PRIMARY)
    ax.text(6.5, 6.85,
            "重力始终指向地心, 因此 IMU 内部重力向量的方向就是 IMU 自身姿态",
            ha="center", fontsize=10.5, color="#445", style="italic")

    # Two-panel outer frames
    _round_box(ax, 0.3, 1.30, 6.0, 5.20, fc=C_BG, ec=C_PRIMARY, lw=1.6)
    _round_box(ax, 6.7, 1.30, 6.0, 5.20, fc="#FDEAEA", ec=C_ACCENT, lw=1.6)

    ax.text(3.30, 6.10, "① 直立 (事件前参考 s_gref)",
            ha="center", fontsize=12, fontweight="bold", color=C_PRIMARY)
    ax.text(9.70, 6.10, "② 躺地 (冲击后静止 s_gpost)",
            ha="center", fontsize=12, fontweight="bold", color=C_ACCENT)

    # Shared ground across both panels (inside frames)
    ground_y_left  = 2.60
    ax.plot([0.55, 6.05], [ground_y_left, ground_y_left],
            color="#333", linewidth=2.0)
    for xx in np.linspace(0.65, 5.95, 30):
        ax.plot([xx, xx - 0.12], [ground_y_left, ground_y_left - 0.12],
                color="#333", linewidth=0.7)

    ground_y_right = 2.60
    ax.plot([6.95, 12.45], [ground_y_right, ground_y_right],
            color="#333", linewidth=2.0)
    for xx in np.linspace(7.05, 12.35, 30):
        ax.plot([xx, xx - 0.12], [ground_y_right, ground_y_right - 0.12],
                color="#333", linewidth=0.7)

    # ---- Panel 1: 直立 ----
    p1 = _draw_person_side(ax, 2.30, 4.35, rot=0, scale=0.85,
                           gravity_in_imu=False)
    bx, by = p1["imu"]

    # Body axis (dashed blue) — parallel to and offset from the actual body
    ba_x = bx + 0.55
    ax.annotate("", xy=(ba_x, by + 1.10), xytext=(ba_x, by - 0.10),
                arrowprops=dict(arrowstyle="-|>", color=C_PRIMARY, lw=1.8,
                                linestyle="--"))
    ax.text(ba_x + 0.08, by + 0.90, "身体竖轴", color=C_PRIMARY,
            fontsize=9.5, fontweight="bold")

    # Gravity arrow inside / starting from IMU, pointing world -y
    ax.annotate("", xy=(bx, by - 1.10), xytext=(bx, by),
                arrowprops=dict(arrowstyle="-|>", color=C_ACCENT, lw=2.4))
    ax.text(bx - 0.65, by - 0.55, "g\n|g|=1G", color=C_ACCENT,
            fontsize=9.5, fontweight="bold", ha="right",
            style="italic")

    # tiny "Δθ = 0°" indicator near the parallel arrows
    ax.text(ba_x - 1.0, by + 0.50, "夹角 = 0°", color=C_OK,
            fontsize=10, fontweight="bold")

    _round_box(ax, 0.55, 1.45, 5.5, 0.55, fc="white", ec=C_PRIMARY, lw=1.2,
               text="重力方向 ∥ 身体竖轴   →   tilt = 0°",
               fs=10.5, bold=True, color=C_PRIMARY)

    # ---- Panel 2: 躺地 ----
    p2 = _draw_person_side(ax, 9.30, 3.10, rot=-88, scale=0.75,
                           gravity_in_imu=False)
    bx2, by2 = p2["imu"]

    # Body axis: local +y rotated by rot=-88°  →  world unit vector
    rot_deg = -88
    th = np.deg2rad(rot_deg)
    ux, uy = -np.sin(th), np.cos(th)
    L = 1.20
    ax.annotate("", xy=(bx2 + L * ux, by2 + L * uy), xytext=(bx2, by2),
                arrowprops=dict(arrowstyle="-|>", color=C_ACCENT, lw=1.8,
                                linestyle="--"))
    ax.text(bx2 + L * ux + 0.10, by2 + L * uy + 0.05, "身体竖轴",
            color=C_ACCENT, fontsize=9.5, fontweight="bold")

    # Gravity still world -y
    ax.annotate("", xy=(bx2, by2 - 1.05), xytext=(bx2, by2),
                arrowprops=dict(arrowstyle="-|>", color=C_ACCENT, lw=2.4))
    ax.text(bx2 - 0.65, by2 - 0.55, "g\n|g|=1G", color=C_ACCENT,
            fontsize=9.5, fontweight="bold", ha="right",
            style="italic")

    # Arc between body axis (world ux,uy) and gravity (0,-1) ≈ 92° / 88°
    # body axis at angle atan2(uy,ux) measured from +x; gravity at 270°
    a_body = np.degrees(np.arctan2(uy, ux))   # ~ 92°
    a_grav = 270.0
    arc = mpatches.Arc((bx2, by2), 1.40, 1.40, angle=0,
                       theta1=a_grav, theta2=a_grav + 88,
                       color=C_OK, linewidth=2.4)
    ax.add_patch(arc)
    ax.text(bx2 + 0.85, by2 - 0.05, "Δθ ≈ 88°",
            color=C_OK, fontsize=10.5, fontweight="bold")

    _round_box(ax, 6.95, 1.45, 5.5, 0.55, fc="white", ec=C_ACCENT, lw=1.2,
               text="重力方向 ⊥ 身体竖轴   →   tilt = 73° – 112°",
               fs=10.5, bold=True, color=C_ACCENT)

    # Threshold bar at the very bottom (outside panels)
    _round_box(ax, 1.0, 0.30, 11.0, 0.65, fc="white", ec=C_OK, lw=1.8,
               text="判据 4   TILT_DEG_MIN = 45°    "
                    "(夹角 ≥ 45° 才认为是 “躯干由直立倒为水平”)",
               fs=11, bold=True, color=C_OK)

    plt.savefig(os.path.join(OUT, "fig_tilt_judgment.png"),
                bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    fig_arch()
    fig_pipeline()
    fig_state_machine()
    fig_hybrid()
    fig_threshold()
    fig_sle_vs_ble()
    fig_timeline()
    fig_overview()
    fig_problem_decomp()
    fig_decision_tree()
    fig_capability_radar()
    fig_physics_specific_force()
    fig_fall_sequence()
    fig_fall_vs_squat_impact()
    fig_tilt_judgment()
    print("All figures written to", OUT)
