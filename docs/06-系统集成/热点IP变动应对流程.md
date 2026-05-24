# 热点 IP 变动应对流程

> 演示前/演示中,只要笔记本 IP 与板 B 固件期望的 IP 不一致,
> **板 B 收到 SLE 0x05 后蜂鸣器/灯带能响,但微信永远收不到 PushPlus 推送**。
> 这份文档专门治这个病。

---

## 0. 为什么会"蜂鸣器响 + 微信不响"

整条上行链路有 6 段:

```
真摔 板A ─SLE 0x05─► 板B ─触发本机声光─► (蜂鸣器/灯) ✅
                            │
                            └─HTTP POST─► 笔记本:8080 ─► PushPlus API ─► 微信
                              (走 WiFi)
                                ↑
                                这一段需要"笔记本 IP" = "板 B 固件硬编码的 IP"
                                两者不一致 → POST 飞向空气 → backend 收不到 → 微信无推送
```

**板 B 收到 SLE 后会立刻触发本机声光**(蜂鸣器/灯),这一段不依赖 WiFi。
**HTTP POST 是另一回事**:`fall_alert_gateway.c` 状态机要 WiFi `READY` + 目标 IP 可达才发得出去。

---

## 1. 现行配置硬编码的关键值

| 文件 | 行 | 字段 | 当前值 |
|------|----|------|--------|
| `fall_alert_gateway_config.h` | 12 | `FALL_GATEWAY_WIFI_SSID` | `"OPPO Find X9s Pro"` |
| `fall_alert_gateway_config.h` | 13 | `FALL_GATEWAY_WIFI_PASSWORD` | `"yyfu0619"` |
| `fall_alert_gateway_config.h` | 16 | `FALL_GATEWAY_SERVER_HOST` | `"10.189.231.184"` |
| `fall_alert_gateway_config.h` | 17 | `FALL_GATEWAY_SERVER_PORT` | `8080` |
| `fall_alert_gateway_config.h` | 21 | `FALL_GATEWAY_AUTH_TOKEN` | `"change-me-demo-token"` |
| `tools/fall_alert_backend.env` | — | `FALL_BACKEND_TOKEN` | `change-me-demo-token` (与固件一致) |

**板 B 上电后只会往 `10.189.231.184:8080` 发**。这个 IP 必须正好是当前笔记本接热点拿到的 IP。

---

## 2. 推荐方案:笔记本设静态 IP(一劳永逸)

让笔记本接 OPPO Find X9s Pro 热点时,IP 永远固定为 `10.189.231.184`。
**设置一次,以后所有演示都不用改、不用编、不用烧。**

### 2.1 Windows 11 设置步骤

1. 笔记本接 `OPPO Find X9s Pro` 热点
2. **设置 → 网络和 Internet → WLAN**
3. 点当前 WiFi 名 (`OPPO Find X9s Pro`)
4. 滚到 **"IP 分配"** → 点 **"编辑"**
5. 把下拉框从 **"自动 (DHCP)"** 改成 **"手动"**
6. 打开 **IPv4** 开关,填:

```
IPv4 地址      : 10.189.231.184
子网掩码       : 255.255.255.0
网关           : 10.189.231.181
首选 DNS       : 114.114.114.114
DNS over HTTPS : 关        ← ★ 必填,否则保存时报"无效项"
备用 DNS       : 8.8.8.8
DNS over HTTPS : 关        ← ★ 同上
```

7. **保存** → 提示成功

### 2.2 验证

```bash
ipconfig | grep "IPv4"     # 应看到 10.189.231.184
ping 10.189.231.181        # 网关应通,验证 WiFi 能正常上网
```

### 2.3 ⚠️ 注意事项

- **演示结束后**:如果之后想接其它 WiFi 上网,要回到上面 "IP 分配" 把 **"手动" 改回 "自动 (DHCP)"**,否则在新网下上不了网
- **DNS over HTTPS 必须选"关"**:Windows 11 默认下拉是"开 (自动模板)",但下面的模板字段空着 → 红字 `无效项` → 保存按钮报 `无法保存 IP 设置`。**这是这一步最容易踩的坑**
- **网关 IP 别填错**:必须是手机热点的网关,不是任意值。一般是热点子网的 `.181` 或 `.1`,以 `ipconfig` 的 `默认网关` 为准
- **DHCP 池冲突**:若 OPPO 之前把 `.184` 分配给了别的设备,笔记本拿不到 → 静态 IP 失效,只能换地址(同时改板 B 固件)

---

## 3. 后备方案:每次脚本一键改 + 重编

若方案 2 失效(OPPO 热点 DHCP 网段变了 / 换其它 WiFi),用脚本:

```bash
cd D:/fbb_ws63/SparkLink-FallDetection/tools
python update_gateway_ip.py
```

### 脚本会做的

1. 列出笔记本上所有 IPv4 网卡(WLAN / 以太网 / VMware 等)
2. 默认推荐"WLAN"那行
3. 让你回车选 / 输序号选其它 / 输 `q` 取消
4. 显示**旧 IP vs 新 IP** Y/n 确认才写入(避免误改)
5. 改完提示下一步:HiSpark Studio Build + BurnTool 烧板B

### 完整下一步

```
a) HiSpark Studio 点 Build (锤子图标),等 "Build Success"  (~5 分钟)
b) BurnTool 烧固件到板 B:
   D:\fbb_ws63\fbb_ws63-master\src\output\ws63\fwpkg\ws63-liteos-app\ws63-liteos-app_all.fwpkg
c) 启动 backend:
   cd D:\fbb_ws63\SparkLink-FallDetection\tools
   set -a && source ./fall_alert_backend.env && set +a
   python fall_alert_backend_demo.py
d) 板 B 上电 → 板A 真摔 → 应该收到微信推送
```

总耗时:**10~12 分钟**(主要是 build + 烧)。

---

## 4. 现场自检清单(演示前 5 分钟必做)

### Step 1:笔记本 IP 自检

```bash
ipconfig | grep "IPv4"
```

应看到 `10.189.231.184`(若没设静态 IP,则比对脚本里读到的 IP 是否等于板 B 固件 IP)。

### Step 2:backend 自检

```bash
netstat -ano | grep ":8080.*LISTEN"
```

应看到 `0.0.0.0:8080 LISTENING <pid>`。
若没看到 → backend 没起,跑:

```bash
cd D:/fbb_ws63/SparkLink-FallDetection/tools
set -a && source ./fall_alert_backend.env && set +a
python fall_alert_backend_demo.py
```

### Step 3:LAN 视角端到端自检(板 B 视角)

```bash
python -c "
import urllib.request, json
req = urllib.request.Request('http://10.189.231.184:8080/api/fall-alert',
    data=json.dumps({'event':'fall','device_id':'pre-demo-check','event_count':1,'payload':'0x05'}).encode(),
    headers={'Content-Type':'application/json','Authorization':'Bearer change-me-demo-token'},
    method='POST')
with urllib.request.urlopen(req, timeout=5) as r:
    print(r.status, r.read().decode())
"
```

预期:`200 {"ok": true, "notified": true}` + **你微信会收到一条 device_id=pre-demo-check 的推送**。
若没收到微信,看 backend stdout 里 `[NOTIFY] PushPlus response` 字段,排 PushPlus 那边(token / 公众号未关注 / 配额)。

### Step 4:板 B 上电后 WiFi 状态

板 B 串口必须出现:

```
[FALL_GW] Wi-Fi connected.
[FALL_GW] DHCP success, ip=10.189.231.xxx
[FALL_GW] gateway ready
```

**必须看到 `gateway ready` 才能做摔测试**。WiFi 扫描+DHCP 一般 15~30 秒,SLE 比 WiFi 快,**不要 SLE 一通就立刻摔**,否则板 B 收到 0x05 但 HTTP 路径还没准备好。

---

## 5. 故障速查表

| 现象 | 大概率原因 | 怎么修 |
|------|-----------|--------|
| 板 A 串口 `[Alert] Fall Detected. Sending SOS now...` 但板 B 蜂鸣器不响 | SLE 没连上 / 板B 还在扫描 | 看板 B 串口是否有 `[CLIENT] Connected to Server` |
| 板 B 蜂鸣器响 + 灯红闪,但 backend 完全没动静 | **本文档要解的问题** | 走 §2 或 §3 修 IP |
| 板 B 蜂鸣器响,backend 收到 [FALL ALERT] 但 PushPlus 报错 | PushPlus token 错 / 公众号取关 / 配额超 | 看 backend `[NOTIFY] PushPlus response`,改 `.env` 里 `PUSHPLUS_TOKEN` |
| backend 收到,微信也收到,但只第一次成功,之后摔都没反应 | backend `FALL_RATE_LIMIT_SECONDS` 默认 60s 频限 | `.env` 里改成 `FALL_RATE_LIMIT_SECONDS=5`,或两次摔间隔 > 1 分钟 |
| 静态 IP 设置时 Windows 报 `无法保存 IP 设置` | DNS over HTTPS 下拉默认是"开",模板字段空 → 无效项 | 把两处 DNS over HTTPS 下拉都改 **"关"** |

---

## 6. 这次踩坑实录(2026-05-24)

把这次的过程贴出来,以后看到类似现象能快速对号入座:

| 时间 | 现象 | 推理 | 实际根因 |
|------|------|------|---------|
| T+0 | 配 PushPlus token + 模拟 POST 通了 | 整条链路验证完毕 | (假象,只是 localhost 测试) |
| T+1 | 重烧板B 后真摔,蜂鸣器响,微信无推送 | "板B HTTP 失败了" | 实际 backend 还没起 |
| T+2 | 起 backend, 真摔, 还是无推送 | "板B HTTP 没到" | 笔记本 WiFi 漂移到了别的网,IP 不再是 `10.189.231.184` |
| T+3 | 静态 IP 设 `10.189.231.184` | 一劳永逸 | ✅ 这次的最终修法 |

**根本教训**:
1. 永远先做 §4 Step 1+2+3 自检,再做真摔。
2. 笔记本 IP 漂移是不可见的故障 ── ipconfig 不查就不知道。
3. 板 B 固件 IP 硬编码是**所有问题的源头**;静态 IP 是最便宜的解药。
