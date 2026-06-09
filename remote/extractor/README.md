# remote/extractor — 游戏流量嗅探器

被动嗅探经过本机或软路由器的游戏 TCP 流量（port 7777），自动提取认证 token 并实时推送游戏状态到云端 relay。

## 工作原理

1. 监听网卡上的 port 7777 TCP 流量（被动嗅探，不影响游戏连接）
2. 从 C->S 0x0001 包提取 `handshake_blob`，从 C->S 0x0006 包提取 `auth_token_12b`
3. 两个凭证都提取到后，POST 到 relay `/register` 接口（一次性）
4. 每次游戏状态变化，POST 到 relay `/push` 接口（实时）

---

## Windows 安装说明

### 前置要求

- Python 3.6+
- Npcap（Windows 抓包驱动）：https://npcap.com/#download
  - 安装时勾选 **"WinPcap API-compatible Mode"**

### 安装依赖

```bat
cd remote\extractor
pip install -r requirements.txt
pip install scapy  # Npcap 支持需要 scapy
```

**注意**：`scapy` 是运行时依赖（不在 requirements.txt 中，因为 Linux 软路由不需要），Windows 需手动安装。

### 配置

编辑 `config.yaml`：

```yaml
relay_url: "http://your-relay-server:8000"
api_token: "your-shared-secret"  # 与 relay config.yaml 保持一致
game_port: 7777
```

### 运行

```bat
# 自动检测模式（Windows 自动使用 Npcap）
python main.py

# 明确指定 Npcap 模式
python main.py --mode npcap
```

---

## OpenWRT 软路由安装说明

### 前置要求

- Python 3.6+（`opkg install python3`）
- requests（`opkg install python3-requests`）
- tcpdump（`opkg install tcpdump`，通常已内置）

### 部署步骤

1. 将项目根目录（含 `stable/`、`game/`、`battle/` 等）上传到软路由，例如 `/opt/mahjongai/`

2. 将 `remote/extractor/` 目录上传到同一位置

3. 配置 `config.yaml`

4. 运行：

```sh
# 自动检测模式（Linux 自动使用 tcpdump）
python3 /opt/mahjongai/remote/extractor/main.py

# 指定网卡
python3 /opt/mahjongai/remote/extractor/main.py --mode tcpdump --interface br-lan
```

### 开机自启（OpenWRT init.d）

创建 `/etc/init.d/mahjong-extractor`：

```sh
#!/bin/sh /etc/rc.common
START=99

start() {
    python3 /opt/mahjongai/remote/extractor/main.py \
        --mode tcpdump --interface br-lan \
        > /tmp/mahjong-extractor.log 2>&1 &
}
```

然后：`chmod +x /etc/init.d/mahjong-extractor && /etc/init.d/mahjong-extractor enable`

---

## 常见问题

**Q: 提示 "requests 未安装"**
A: `pip install requests` 或 `opkg install python3-requests`

**Q: Windows 提示权限错误**
A: 以管理员身份运行 cmd/PowerShell

**Q: 抓不到包**
A: 检查游戏是否走经过本机的流量；确认 Npcap/tcpdump 已正确安装；确认监听的网卡接口正确
