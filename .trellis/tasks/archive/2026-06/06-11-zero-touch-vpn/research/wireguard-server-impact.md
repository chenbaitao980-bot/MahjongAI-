# WireGuard 替代 strongSwan：云端服务端冲击分析

> 2026-06-11 — Research Agent
> Context: 当前云端是 strongSwan 5.9.5 IKEv2/IPSec PSK。
> 问题：如果切换到 WireGuard（为了手机端 QR 扫码配置能力），云端需要改什么？

---

## 当前 strongSwan 堆栈

```
手机 ──IKEv2/UDP:500,4500──▶ 云服务器
                                 ├─ strongSwan (charon) → xfrm 解密
                                 ├─ iptables MASQUERADE (10.99.0.0/24 → eth0)
                                 └─ extractor: tcpdump -i any port 7777
                                      → PcapParser(SLL2) → push → relay
```

### 当前部署文件：
- `remote/extractor/vpn/install_vpn.sh` — 安装 strongSwan
- `remote/extractor/vpn/vpn_configure.py` — 生成 ipsec.conf + ipsec.secrets + phone-setup.txt
- `remote/extractor/vpn/README.md` — 部署文档

---

## WireGuard 替换方案

### 协议对比

| 特性 | strongSwan IKEv2 | WireGuard |
|------|-----------------|-----------|
| 传输层 | UDP 500 (IKE) + UDP 4500 (ESP) | UDP 51820 (或任意端口) |
| 内核集成 | xfrm (Linux) | WireGuard 内核模块 (Linux 5.6+) |
| 密钥管理 | IKE_SA_INIT + IKE_AUTH 握手 | Noise 协议，静态密钥对 |
| 加密套件 | 协商 (aes256-sha256-modp2048 etc) | 固定: ChaCha20 + Poly1305 + Curve25519 |
| 漫游 (MOBIKE) | ✅ 内置 | ✅ 无连接 (基于密钥对) |
| 性能 | 较慢 (内核 xfrm 查找) | 更快 (极简代码路径) |
| 手机端 | Android 内置 (手动打字) | WireGuard app (QR 扫码) |
| 配置复杂度 | ipsec.conf + ipsec.secrets + 防火墙 | 单个 wg0.conf + 防火墙 |

### 云端部署变更

#### 1. 安装 WireGuard

```bash
# Ubuntu 20.04+ / Debian 11+
apt install wireguard-tools

# 或内核模块已内置 (Linux 5.6+) 无需额外安装
# wireguard-tools 提供 wg 和 wg-quick 工具
```

**与 strongSwan 对比**：strongSwan 需要 `apt install strongswan strongswan-pki libcharon-extra-plugins`，WireGuard 更轻量。

#### 2. 服务器配置

```ini
# /etc/wireguard/wg0.conf
[Interface]
PrivateKey = <server_private_key_base64>
Address = 10.99.0.1/24
ListenPort = 51820

# iptables 规则 (由 PostUp/PostDown 管理)
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT
PostUp = iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT
PostDown = iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

# 每个手机一个 [Peer] 段 (或所有手机共享一个密钥对)
[Peer]
PublicKey = <phone_public_key_base64>
PresharedKey = <optional_psk_base64>  # 可选，增强安全性
AllowedIPs = 10.99.0.2/32             # 该手机分配的内网 IP
```

#### 3. 启动

```bash
wg-quick up wg0
systemctl enable wg-quick@wg0
```

**vs. strongSwan**：`ipsec start` + 复杂的 xfrm 策略 → 更简单。

#### 4. 客户端 QR 码生成

```python
# 每个手机生成一个配置（或所有手机共享一个）
client_config = f"""
[Interface]
PrivateKey = <phone_private_key_base64>
Address = 10.99.0.2/24
DNS = 8.8.8.8

[Peer]
PublicKey = <server_public_key_base64>
PresharedKey = <optional_psk_base64>
Endpoint = {server_public_ip}:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
"""

# 编码为 QR 码 (png/svg)
import qrcode
img = qrcode.make(client_config)
img.save("phone-vpn-qr.png")
```

**vs. strongSwan**：不再需要 `phone-setup.txt`（手填 3 字段），改为输出一张 QR 图片。

#### 5. extractor 嗅探

**无需任何改变**。WireGuard 解密在内核完成，`tcpdump -i any port 7777` 仍然能抓到游戏的 TCP 流量。同样的 `PcapParser` (SLL2) 解析逻辑不变。

```
手机流量 → WireGuard 内核解密 → 进入 IP 栈 → tcpdump -i any 可见
```

#### 6. iptables 转发

```bash
# 与 strongSwan 完全相同的 MASQUERADE 规则
iptables -t nat -A POSTROUTING -s 10.99.0.0/24 -o eth0 -j MASQUERADE
iptables -A FORWARD -i wg0 -j ACCEPT
iptables -A FORWARD -o wg0 -j ACCEPT

# 开启 IPv4 转发
sysctl -w net.ipv4.ip_forward=1
```

---

## 客户端体验对比

### strongSwan (当前):
```
1. 打开 Settings
2. 点 Network & internet
3. 点 VPN
4. 点 "+"
5. 下拉选 Type = IKEv2/IPSec PSK
6. 输入服务器 IP
7. 输入预共享密钥 (长 hex 串，易出错)
8. 点 Save
9. 点齿轮图标
10. 点 Always-on VPN → ON
---
约 12-15 次点击 + 手动输入 2 个字符串
```

### WireGuard (新):
```
1. 安装 WireGuard app (Play Store, 一次性)
2. 打开 app
3. 点 "+"
4. 点 "Scan from QR code"
5. 扫描 QR 码
6. 点 "Create tunnel"
7. 点开关激活
8. Settings → VPN → WireGuard → Always-on = ON
---
约 8 次点击 + 零输入
```

**摩擦降低**: ~40% 点击减少 + 完全消除手动输入（没有打字错误）。

---

## 「多设备/共享」场景优势

当前 strongSwan 方案：每台手机都需要手动输入 3 个字段。

WireGuard 方案：
- **共享密钥对**：所有手机用同一个客户端密钥对 → 同一个 QR 码 → 扫完即用
- **或每设备独立密钥**：服务端 `[Peer]` 每台手机加一段 → 对应 QR 码 → 便于吊销
- **QR 码可打印/分享链接**：发给对方一个链接/图片即可

对于"给朋友用"的场景，WireGuard QR = 发一个图片 → 对方装 app → 扫码 → 连上。
vs. strongSwan = 发"服务器IP: xxx, PSK: xxx, 类型选 IKEv2 PSK…" → 对方照着打 → 可能打错。

---

## 安全对比

| 方面 | strongSwan IKEv2 PSK | WireGuard |
|------|---------------------|-----------|
| 认证 | 预共享密钥 (对称) | 公钥密码学 (Curve25519 非对称) |
| 密钥分发 | PSK 必须安全传输给用户 | 公钥可公开，私钥在 QR 中 |
| 前向安全性 | ✅ (IKE SA 每次重协商) | ✅ (Noise 协议天然 PFS) |
| 审计 | 代码量大 (~100k LOC) | 极简代码 (~4k LOC, 已审计) |
| 漫游 | MOBIKE (IKEv2 扩展) | 无连接，天然支持 |
| PSK 泄露风险 | 共享同一 PSK = 全泄露 | 每设备独立密钥对 (推荐) |

WireGuard 在公钥加密和多设备隔离方面更安全。如果共享密钥对，则与 PSK 安全等级类似。

---

## 需要改动的文件清单

### 新增:
1. `remote/extractor/vpn/wireguard_configure.py` — 替代 `vpn_configure.py`
   - 生成服务端 wg0.conf
   - 生成客户端配置
   - 生成 QR 码图片 (png)
2. `remote/extractor/vpn/install_wireguard.sh` — 替代 `install_vpn.sh`
   - `apt install wireguard-tools`
   - 启用 IP 转发
   - iptables 规则
3. `remote/extractor/vpn/README_WG.md` — WireGuard 部署文档

### 修改:
4. `remote/extractor/package_extractor.py` — `--with-vpn` 改为打包 WireGuard 文件
5. `remote/relay/static/vpn-setup.html` — 更新指引 (扫码装 WireGuard vs. 手填 IKEv2)
6. `.trellis/spec/backend/remote-access.md` — 更新场景C 描述

### 保留 (不删，向后兼容):
7. 现有 strongSwan 文件保留，标记 `legacy` 或移到 `vpn/legacy/`
8. 现有 `phone-setup.txt` 生成逻辑保留（当用户坚持不想装 app 时回退）

---

## 多协议共存 (推荐架构)

最优策略：**同时支持 WireGuard 和 strongSwan**。

```
                ┌─ 不想装app → strongSwan IKEv2 PSK (手填3字段)
手机 VPN 配置 ──┤
                └─ 能装app   → WireGuard (扫QR码)
```

云端同时运行两个 VPN 服务（不同端口，不冲突）：
- strongSwan 监听 UDP 500 + UDP 4500
- WireGuard 监听 UDP 51820
- extractor 的 `tcpdump -i any` 都能嗅探到

这样用户可选择：零 app 方案（打字但系统级）或 QR 方案（装一个开源 app 扫一下）。

---

## 服务端性能预估

| 指标 | strongSwan | WireGuard |
|------|-----------|-----------|
| 单隧道吞吐 | ~500 Mbps (aes256 软件) | ~1 Gbps (ChaCha20) |
| CPU 占用 | 中 (xfrm 查找 + 加解密) | 低 (无查找表，O(1) 路由) |
| 内存 | ~10 MB (charon 进程) | ~2 MB (内核模块) |
| 连接建立 | ~2 RTT (IKE_SA_INIT+IKE_AUTH) | 0 RTT (Noise IK) |
| 阿里云 ECS 兼容 | ✅ (Linux 3.10+ 都行) | ✅ (需 5.6+, 阿里云 Alinux3/Ubuntu 20.04 满足) |

WireGuard 在各方面更优，尤其是吞吐和延迟。

---

## 结论

**WireGuard 替代 strongSwan 是合理的技术选择**：
- 服务端改动小（安装工具 → 配置 wg0.conf → 启动，~10 行 bash）
- extractor/relay 完全不用动（嗅探层透明）
- 手机端摩擦从"手打 3 个字段"降为"扫码即用"
- 推荐**多协议共存**：保留 strongSwan 给不想装 app 的用户，新增 WireGuard QR 给追求方便的用户
- 对"给朋友用"场景，QR 码一张图搞定，体验碾压手打 IP+PSK
