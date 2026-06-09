# remote/relay — 云端中继服务

接收 extractor 注册的认证 token，主动连接游戏服务器（extractor 离线时），暴露 `/state` API 供外部查询当前游戏状态。

## 架构

- **场景A（extractor 在线）**：extractor 推送 snapshot → relay 存储 → `/state` 返回
- **场景B（extractor 离线）**：relay 主动连接游戏服务器 → 解析数据 → `/state` 返回
- 两个场景对外暴露同一 `/state` API，格式相同

---

## 部署说明

### 前置要求

- Python 3.8+
- 云服务器（公网可访问）

### 安装依赖

```bash
cd remote/relay
pip install -r requirements.txt
```

同时需要安装项目根目录的依赖（用于复用 stable/ 代码）：

```bash
cd ../..  # 项目根目录
pip install pyyaml  # 最小依赖（stable/mapping.py 需要）
```

### 配置

编辑 `config.yaml`：

```yaml
api_token: "your-shared-secret"       # 与 extractor 保持一致
game_server_ip: "47.96.0.227"         # 游戏服务器 IP
game_server_port: 7777
# 以下由 extractor POST /register 自动填充，也可手动填写
handshake_blob: ""
auth_token_12b: ""
```

### 启动

```bash
# 方式1：直接运行（带参数）
python main.py --host 0.0.0.0 --port 8000

# 方式2：uvicorn（生产环境推荐）
uvicorn main:app --host 0.0.0.0 --port 8000

# 方式3：后台运行
nohup uvicorn main:app --host 0.0.0.0 --port 8000 > relay.log 2>&1 &
```

### systemd 服务（推荐）

创建 `/etc/systemd/system/mahjong-relay.service`：

```ini
[Unit]
Description=MahjongAI Remote Relay
After=network.target

[Service]
WorkingDirectory=/opt/mahjongai/remote/relay
ExecStart=/usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

然后：
```bash
systemctl daemon-reload
systemctl enable mahjong-relay
systemctl start mahjong-relay
```

---

## API 说明

### POST /register

接收 extractor 上传的认证凭证。

**请求体**：
```json
{
  "handshake_blob": "c92eae92aa6bfea336590fc1392644343d9eba",
  "auth_token_12b": "7ad8c993c1b08b44392e4014",
  "api_token": "your-shared-secret"
}
```

**响应**：
```json
{"status": "ok", "message": "凭证已注册"}
```

---

### POST /push

接收 extractor 推送的实时游戏状态。

**请求体**：
```json
{
  "snapshot": { "phase": "playing", "players": {...}, ... },
  "api_token": "your-shared-secret"
}
```

**响应**：
```json
{"status": "ok"}
```

---

### GET /state?token=xxx

返回最新游戏状态。

**查询参数**：
- `token`：鉴权 token（与 api_token 相同）

**响应**（游戏进行中）：
```json
{
  "phase": "playing",
  "local_player": 1,
  "current_turn": "self",
  "remaining_tiles": 72,
  "players": {
    "1": {"hand": ["1m","2m",...], "discards": [...], "melds": [...]},
    "3": {"hand": [], "discards": [...], "melds": [...]}
  },
  ...
}
```

**响应**（游戏未进行）：
```json
{"phase": "idle"}
```

**无效 token**：
```
HTTP 401 Unauthorized
```

---

## 注意事项

- `stable/` 目录需要在 Python 路径中（relay 自动处理，确保项目根目录结构完整）
- 状态仅保存在内存中，重启后需要 extractor 重新推送或等待游戏服务器发送数据
- 多账号支持不在当前范围内（单账号）
