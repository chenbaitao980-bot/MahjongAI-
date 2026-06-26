# MITM 代理部署指南（移动网络可用）

## 架构概览

```
手机(任意网络/4G/WiFi)
  │
  ▼
DNS 劫持: gxb-api.imeete.com → ECS_IP
  │
HTTPS 热更服务(ECS:443): 返回改写的 project.manifest
  │ (NetConf.luac 指向 ECS 大厅 IP)
  ▼
游戏连接 ECS:5748/5749 (大厅代理)
  │
大厅代理: RespSRSAddr.szIP → ECS_IP
  │
游戏连接 ECS:5700~5723 (动态游服代理)
  │
游服代理: SRS 解密 → 0x2bc0 手牌 → POST /push → relay:8002
  │
网页 GET /state → 显示手牌
```

## 部署步骤

### 1. 远程服务器 (ECS) 配置

**前提条件：**
- ECS 公网 IP: `8.136.37.136`
- 安全组放行: TCP 443, 5748, 5749, 7777, 5700-5799, 8002
- 已安装 Python 3.10+, pip, cryptography 库

**部署命令：**

```bash
# 1. 创建目录
mkdir -p /opt/mahjong-mitm
cd /opt/mahjong-mitm

# 2. 上传代码（从本地执行）
scp remote/noconfig/hijack/*.py root@8.136.37.136:/opt/mahjong-mitm/
scp remote/srs_spectator/*.py root@8.136.37.136:/opt/mahjong-mitm/
scp stable/*.py root@8.136.37.136:/opt/mahjong-mitm/

# 3. 安装依赖
pip3 install cryptography requests

# 4. 停止旧服务
pkill -f 'ecs_run.py'
pkill -f 'tcp_proxy.py'

# 5. 启动新服务
nohup python3 /opt/mahjong-mitm/ecs_run.py \
  --ecs-ip 8.136.37.136 \
  --relay-url http://localhost:8002 \
  --listen-host 0.0.0.0 \
  > /var/log/mahjong-mitm.log 2>&1 &

# 6. 验证
ps aux | grep ecs_run
tail -f /var/log/mahjong-mitm.log
```

**systemd 服务（推荐生产环境）：**

创建 `/etc/systemd/system/mahjong-mitm.service`：

```ini
[Unit]
Description=MahjongAI MITM Proxy
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/mahjong-mitm
ExecStart=/usr/bin/python3 /opt/mahjong-mitm/ecs_run.py --ecs-ip 8.136.37.136 --relay-url http://localhost:8002 --listen-host 0.0.0.0
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

启用：
```bash
systemctl daemon-reload
systemctl enable mahjong-mitm
systemctl start mahjong-mitm
systemctl status mahjong-mitm
```

### 2. 热更 MITM 服务（解决"校验资源"卡住）

**问题**：手机用自己的移动网络时，热更下载走真实 CDN，NetConf 不被改写，游戏连真服大厅。

**解决**：在 ECS 上部署 DNS 劫持 + HTTPS 服务。

```bash
# 1. 启动 DNS 劫持（UDP:53）
python3 /opt/mahjong-mitm/setup_mitm.py \
  --dns-port 53 \
  --http-port 443 \
  --ecs-ip 8.136.37.136 \
  --apk /opt/mahjong-mitm/game_base.apk

# 2. 手机改 DNS 为 ECS_IP (8.136.37.136)
#    或在路由器/DHCP 层面下发 ECS_IP 作为 DNS
```

**手机端配置：**
1. 进入手机 WiFi 设置 → 修改当前网络 → 高级选项
2. IP 设置改为"静态"
3. DNS 1: `8.136.37.136`
4. DNS 2: `119.29.29.29`（备用）

### 3. 本地开发环境配置

**运行测试：**

```bash
# 1. 运行自测
python remote/noconfig/hijack/tcp_proxy.py --selftest

# 2. 本地启动代理（调试模式）
python remote/noconfig/hijack/ecs_run.py \
  --ecs-ip 127.0.0.1 \
  --relay-url http://localhost:8002 \
  --listen-host 127.0.0.1
```

**依赖安装：**

```bash
pip install -r requirements.txt
# 确保包含: cryptography, requests, pyyaml
```

### 4. 验证流程

**步骤 1: 验证热更 MITM**
```bash
# 在 ECS 上检查 DNS 服务
netstat -tlnp | grep :53
netstat -tlnp | grep :443

# 测试 DNS 解析
dig @8.136.37.136 gxb-api.imeete.com
# 应返回 8.136.37.136
```

**步骤 2: 验证大厅代理**
```bash
# 在 ECS 上检查端口监听
ss -tlnp | grep -E '5748|5749|7777'

# 测试连接
telnet 8.136.37.136 5748
```

**步骤 3: 验证手牌推送**
```bash
# 检查 relay 日志
tail -f /var/log/mahjong-relay.log

# 或直接测试 /push 端点
curl -X POST http://localhost:8002/push \
  -H "Content-Type: application/json" \
  -d '{"snapshot":{"hand":["1m","2m","3m"],"phase":"playing"},"api_token":""}'

# 检查 /state
curl http://localhost:8002/state
```

## 故障排查

### 问题 1: "校验资源"卡住 0%

**根因**: DNS 劫持未生效，或 HTTPS 证书问题。

**排查:**
1. 确认手机 DNS 指向 ECS
2. 确认 ECS 上 DNS 服务在跑: `ps aux | grep dns_divert`
3. 确认 HTTPS 服务在跑: `netstat -tlnp | grep :443`
4. 抓包检查: `tcpdump -i any port 53 or port 443 -w /tmp/hotfix.pcap`

### 问题 2: 大厅代理无响应

**根因**: 安全组未放行端口，或大厅代理未启动。

**排查:**
1. 确认安全组放行 5748/5749
2. 确认代理进程: `ps aux | grep ecs_run`
3. 检查日志: `tail -f /var/log/mahjong-mitm.log`

### 问题 3: 手牌不显示

**根因**: SRS 解密失败，或 0x2bc0 未解出。

**排查:**
1. 检查日志中 `[game-decrypt] session key learned` 是否出现
2. 检查日志中 `[game] 0x2bc0 hand_trusted` 是否出现
3. 确认动态端口代理已创建: `curl http://localhost:8002/mode`

## 文件清单

| 文件 | 用途 |
|------|------|
| `tcp_proxy.py` | 核心代理（大厅改写 + 游服解密 + 动态端口） |
| `ecs_run.py` | ECS 部署入口（systemd 服务调用） |
| `setup_mitm.py` | 热更 MITM（DNS + HTTPS） |
| `netconf_patch.py` | NetConf.luac 改写 |
| `manifest_forge.py` | manifest 伪造 |
| `dns_divert.py` | DNS 劫持 |
