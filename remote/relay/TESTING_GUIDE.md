# MahjongAI 三模式远程架构 — 测试指南

## 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│                    ECS 云服务器 (8.136.37.136)                 │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │ 热点 relay   │  │ VPN relay   │  │ 无配置 relay │          │
│  │  :8000       │  │  :8001       │  │  :8002       │          │
│  │ StateStore A │  │ StateStore B │  │ StateStore C │          │
│  └──┬──────────┘  └──┬──────────┘  └──┬──────────┘          │
│     │ (外部推)        │ (本地推)       │ (spectator推)        │
│     │                 │               │                      │
│     │            ┌────▼────┐    ┌─────▼──────┐               │
│     │            │tcpdump   │    │ spectator   │               │
│     │            │(vpn接口) │    │ :8001       │               │
│     │            └─────────┘    └────────────┘               │
└─────┼───────────────────────────────────────────────────────┘
      │
      │ HTTP POST /push
      │
┌─────▼──────────────────────────────────┐
│        用户 PC (Windows)                │
│  ┌──────────────────────────────────┐  │
│  │ extractor (npcap/tcpdump)        │  │
│  │ 嗅探共享热点流量                  │  │
│  └──────────────────────────────────┘  │
│              ▲ 热点共享                │
│     ┌────────┴───────┐                │
│     │   手机(游戏App)  │                │
│     └────────────────┘                │
└──────────────────────────────────────┘
```

## 模式一：共享热点模式 (Port 8000)

### 原理
手机连PC共享热点 → PC抓包 → 推送到云端 relay :8000

### 前置条件
1. ECS 云端 relay-hotspot 服务已启动（:8000）
2. 手机已连上 PC 的共享热点
3. PC 上安装了 Npcap（Windows）或 tcpdump（Linux）

### 测试步骤

#### Step 1: 启动云端服务
```bash
# 在 ECS 上
cd /opt/mahjong-remote
python3 remote/relay/main.py --mode hotspot --host 0.0.0.0 --port 8000

# 或使用 systemd
systemctl start mahjong-relay-hotspot
```

#### Step 2: 验证云端服务
```bash
# 检查服务是否运行
curl http://8.136.37.136:8000/mode
# 预期返回: {"mode":"hotspot","port":8000,...}

# 检查状态（先无数据）
curl "http://8.136.37.136:8000/state?token=acec67bfa9e518b5906d3e6a"
# 预期返回: {"phase":"idle","data_source":"extractor","credential_ready":false,...}
```

#### Step 3: 配置 extractor
编辑 `remote/extractor/config.yaml`:
```yaml
relay_url: http://8.136.37.136:8000
api_token: acec67bfa9e518b5906d3e6a
game_port: 7777
```

#### Step 4: 手机连PC热点
- Windows: 设置→网络和Internet→移动热点→开启
- 手机 WiFi 连接到 PC 热点

#### Step 5: 启动 PC 端 extractor
```bash
# Windows (管理员权限运行)
cd E:\claude\project\MahjongAI\MahjongAI
python remote/extractor/main.py --mode npcap

# 预期日志:
# [INFO] extractor 启动，监听 port 7777 → relay http://8.136.37.136:8000
```

#### Step 6: 打开游戏触发流量
- 在手机上打开台州麻将游戏
- **重要**：如果游戏已登录，需清除 App 数据后重新登录
  - Android: 设置→应用→台州麻将→存储→清除数据

#### Step 7: 验证数据流通
```bash
# 查询状态
curl "http://8.136.37.136:8000/state?token=acec67bfa9e518b5906d3e6a"

# 预期返回包含游戏数据：
# {"phase":"playing","your_hand":["1m","2m",...],"credential_ready":true,...}
```

### 测试通过标准
- [ ] `/mode` 返回 `{"mode":"hotspot"}`
- [ ] extractor 启动后日志显示捕获到数据包
- [ ] `/register` 端点收到凭证（日志显示"已注册凭证"）
- [ ] `/state` 返回实际的游戏状态（非 idle）
- [ ] PC 断开热点后，relay 检测到 extractor 离线（约 10 秒）

---

## 模式二：手机VPN模式 (Port 8001)

### 原理
手机配置 IPSec VPN → 流量经 ECS → ECS 上抓包 → 推送到 relay :8001

### 前置条件
1. ECS 云端 relay-vpn 服务已启动（:8001）
2. ECS 上已配置 IPSec VPN 服务（strongSwan）
3. VPN 接口能抓到游戏流量

### 测试步骤

#### Step 1: 启动云端 VPN relay
```bash
# 在 ECS 上
cd /opt/mahjong-remote
python3 remote/relay/main.py --mode vpn --host 0.0.0.0 --port 8001

# 或使用 systemd
systemctl start mahjong-relay-vpn
```

#### Step 2: 配置手机 VPN
- 打开手机浏览器访问 `http://8.136.37.136:8000/vpn-setup`
- 按照页面指引：
  1. 下载并安装 CA 证书
  2. 添加 VPN 配置：类型 IPSec IKEv2 RSA
  3. 服务器: 8.136.37.136
  4. 用户名/密码按页面显示填写
  5. 开启 Always-on VPN

#### Step 3: 启动云端 extractor（抓 VPN 接口流量）
```bash
# 在 ECS 上，先找到 VPN 接口名
ip link show | grep -E '(ipsec|tun|ppp)'
# 通常是 ipsec0 或 ppp0

# 启动 extractor，监听 VPN 接口
cd /opt/mahjong-remote
python3 remote/extractor/main.py --mode tcpdump --interface ipsec0

# 如果 extractor 部署在另一台机器，修改 config.yaml:
# relay_url: http://127.0.0.1:8001  (本地)
# 如果 extractor 在 ECS 上，使用 localhost
```

#### Step 4: 验证 VPN 连接
```bash
# 在 ECS 上检查 VPN 连接状态
ipsec status

# 检查是否有游戏流量经过
tcpdump -i ipsec0 port 7777 -nn -c 10
```

#### Step 5: 打开游戏触发流量
- 手机确保 VPN 已连接
- 打开台州麻将游戏
- 重新登录以触发认证包

#### Step 6: 验证数据流通
```bash
# 查询 VPN 模式 relay
curl "http://8.136.37.136:8001/state?token=8f2e7c91b4d53a6f10e9c827"

# 预期：返回游戏状态，data_source 为 "extractor"
# {"phase":"playing","data_source":"extractor",...}
```

### 测试通过标准
- [ ] `/mode` 返回 `{"mode":"vpn"}`
- [ ] 手机 VPN 连接成功，ECS 能抓到 7777 端口的包
- [ ] VPN relay 的 `/state` 返回游戏数据
- [ ] 与热点模式互不干扰（:8000 状态不受影响）

---

## 模式三：无配置模式 (Port 8002)

### 原理
利用 SRS 旁观协议直连游戏服务器 → 手机完全不需要任何配置

### 前置条件
1. ECS 云端 relay-noconfig 服务已启动（:8002）
2. SRS spectator 服务已启动（:8001 内部）
3. relay 已有有效的 SRS 凭证（handshake_blob + auth_token_12b + srs_sessionid）
4. 游戏服务器可被 ECS 访问

### 测试步骤

#### Step 1: 启动无配置 relay 和 spectator
```bash
# 在 ECS 上
systemctl start mahjong-relay-noconfig
systemctl start mahjong-spectator

# 检查状态
systemctl status mahjong-relay-noconfig
systemctl status mahjong-spectator
```

#### Step 2: 验证服务状态
```bash
# 检查无配置 relay
curl http://8.136.37.136:8002/mode
# 预期: {"mode":"noconfig","credential_ready":true,...}

# 检查 spectator
curl http://8.136.37.136:8001/status
# 预期: {"watching":false,"roomid":null,...}
```

#### Step 3: 注册 SRS 凭证
**前提**：需要先用热点模式获取 SRS 凭证（仅首次）。

方法 A：通过热点模式 extractor 获取并注册到无配置 relay
```bash
# PC 热点模式运行时，extractor 会自动捕获 srs_sessionid
# 然后手动将凭证写入 config_noconfig.yaml

# 或通过 API 直接注册
curl -X POST http://8.136.37.136:8002/register \
  -H "Content-Type: application/json" \
  -d '{
    "handshake_blob": "459937d169da1ecda3c63f5a89a70b94e55d92",
    "auth_token_12b": "846a29fd572fbbdf89af0fb4",
    "srs_sessionid": "YOUR_SRS_SESSIONID_HEX",
    "api_token": "d4a8e1f29c6b7305e8d1f264"
  }'
```

方法 B：通过 Frida hook 获取
```bash
# 在 PC 上（手机 USB 连接）
cd frida
python run_lobby_hook.py
# 日志中会打印 handshake_blob, auth_token, srs_sessionid
```

#### Step 4: 触发旁观
```bash
# 注册房间信息，触发 spectator 开始旁观
# room_id 和 game_id 需要从游戏中获取
curl -X POST http://8.136.37.136:8002/register-room \
  -H "Content-Type: application/json" \
  -d '{
    "room_id": 123456,
    "game_id": 789,
    "api_token": "d4a8e1f29c6b7305e8d1f264"
  }'

# 检查 spectator 状态
curl http://8.136.37.136:8001/status
# 预期: {"watching":true,"roomid":123456,...}
```

#### Step 5: 验证数据流通
```bash
# 查询无配置模式 relay
curl "http://8.136.37.136:8002/state?token=d4a8e1f29c6b7305e8d1f264"

# 预期：返回游戏数据
# {"phase":"playing","data_source":"game_client",...}
# 注意：旁观数据不含隐藏手牌（仅牌背），这是已知限制
```

### 测试通过标准
- [ ] `/mode` 返回 `{"mode":"noconfig"}`
- [ ] spectator 能连接到游戏服务器（状态 watching=true）
- [ ] `/state` 返回游戏状态（phase 非 idle）
- [ ] 手机端不需要任何配置就能在中继页看到游戏状态

---

## 三模式并行测试

### 同时启动所有模式
```bash
# 方式一：多进程
cd /opt/mahjong-remote
python3 remote/relay/main.py --all

# 方式二：Docker
docker-compose up -d

# 方式三：systemd（全部启动）
systemctl start mahjong-relay-hotspot mahjong-relay-vpn mahjong-relay-noconfig mahjong-spectator
```

### 隔离性验证
```bash
# 三个模式应该返回各自独立的状态
curl http://8.136.37.136:8000/mode | jq .mode
# "hotspot"

curl http://8.136.37.136:8001/mode | jq .mode
# "vpn"

curl http://8.136.37.136:8002/mode | jq .mode
# "noconfig"

# 推送数据到热点模式不应该影响 VPN 模式
curl -X POST http://8.136.37.136:8000/push \
  -H "Content-Type: application/json" \
  -d '{"snapshot":{"test":true},"api_token":"acec67bfa9e518b5906d3e6a"}'

# VPN 模式应该仍然是 idle
curl "http://8.136.37.136:8001/state?token=8f2e7c91b4d53a6f10e9c827" | jq .phase
# "idle"  ← 不受热点模式影响
```

### 日志检查
```bash
# 每个模式有独立的日志文件
tail -f /opt/mahjong-remote/remote/relay/relay_hotspot.log
tail -f /opt/mahjong-remote/remote/relay/relay_vpn.log
tail -f /opt/mahjong-remote/remote/relay/relay_noconfig.log
```

---

## 快速诊断命令

| 目的 | 命令 |
|------|------|
| 检查热点 relay | `curl http://ECS_IP:8000/mode` |
| 检查 VPN relay | `curl http://ECS_IP:8001/mode` |
| 检查无配置 relay | `curl http://ECS_IP:8002/mode` |
| 检查 spectator | `curl http://ECS_IP:8001/status` |
| 查询热点状态 | `curl "http://ECS_IP:8000/state?token=HOTSPOT_TOKEN"` |
| 查询 VPN 状态 | `curl "http://ECS_IP:8001/state?token=VPN_TOKEN"` |
| 查询无配置状态 | `curl "http://ECS_IP:8002/state?token=NOCONFIG_TOKEN"` |
| 热点服务日志 | `journalctl -u mahjong-relay-hotspot -f` |
| VPN 服务日志 | `journalctl -u mahjong-relay-vpn -f` |
| 无配置日志 | `journalctl -u mahjong-relay-noconfig -f` |

---

## 常见问题

### Q: 三个模式都用同一个游戏账号吗？
A: 是的，但三种模式的数据入口不同。热点/VPN 模式通过抓包获取完整数据（含隐藏手牌），无配置模式通过旁观获取（不含隐藏手牌）。建议优先使用热点或 VPN 模式。

### Q: 为什么无配置模式看不到隐藏手牌？
A: SRS 旁观协议的设计限制——服务器不会向旁观者发送其他玩家的手牌数据（只发送牌背）。这是已知限制，详见 `.trellis/tasks/06-11-srs-client-finish/research/siphon-final-goal.md`。

### Q: VPN 模式的 extractor 部署在哪里？
A: 部署在 ECS 云服务器上，与 relay 同机。抓取 VPN 接口（ipsec0）的流量。

### Q: 能否同时使用三种模式？
A: 可以。三种模式完全独立，互不影响。你可以同时用热点模式看手牌、VPN 模式做备用、无配置模式测试旁观功能。
