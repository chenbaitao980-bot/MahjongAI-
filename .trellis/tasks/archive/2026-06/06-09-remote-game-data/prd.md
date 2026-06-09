# remote real-time game data access

## Goal

用户在任意游戏机上打牌时，云服务器能实时获取其对战数据。
- **家里**：软路由器被动嗅探经过它的游戏流量，提取 token 并实时推送游戏状态到云端
- **外出**：云服务器用已存储的 token 独立连接游戏服务器获取数据
- 游戏机无需安装任何软件；token 自动上传，无需手工复制

## 已确认的关键前提

* ✅ 游戏服务器**允许同一账号同时双端在线**（已实测）
* ✅ 游戏机无需运行任何额外软件
* ⚠️ **认证凭证是二进制 token，非明文密码**（见 research/auth-protocol.md）：
  - `handshake_blob`：19~23 bytes，账号绑定，从 0x0001 C->S 包提取
  - `auth_token_12b`：12 bytes 用户 session token，从 0x0006 C->S 包 bytes 4-15 提取
  - 软路由器被动嗅探所有经过的游戏流量，自动提取这两个值并 POST 到云端

## 项目结构

在本项目根目录下新建两个独立子目录：

```
remote/
  extractor/    # 运行在 Windows PC 或软路由器（Linux）上
  relay/        # 运行在云服务器上
```

## Architecture

```
场景A（家里，软路由器/Windows PC）
  游戏机 → [软路由器嗅探 port 7777] → 游戏服务器
               ↓ 被动抓包
           extractor/
             提取 handshake_blob + auth_token_12b
             POST /register → cloud relay（一次性注册）
             实时推送 game state → POST /push → cloud relay（每次牌面变化）

场景B（外出，无本地设备）
  云服务器 relay/ 用已存 token 主动连接游戏服务器
             接收 S->C 数据包 → PacketStateTracker → 内存中最新状态

两个场景共用同一个 relay/ 的 GET /state API
```

## Requirements

### extractor/ 子项目（Windows PC + 软路由 Linux 双平台）

1. **跨平台抓包**：
   - Windows：调用 Npcap（复用 `stable/protocol.py` 的 `NpcapCapture`）
   - Linux/OpenWRT 软路由：调用系统 `tcpdump`（复用 `stable/protocol.py` 的 `build_tcpdump_command`）
   - 通过命令行参数 `--mode npcap|tcpdump` 或自动检测切换

2. **Token 自动提取**：首次运行时监听 0x0001 C->S（提取 `handshake_blob`）和 0x0006 C->S（提取 `auth_token_12b`），提取成功后自动 POST 到 relay 的 `POST /register` 接口，无需手工操作

3. **实时状态推送**：持续运行，每次 `PacketStateTracker` 输出 `changed=True` 时，将 `snapshot()` POST 到 relay 的 `POST /push` 接口

4. **配置文件** `extractor/config.yaml`：`relay_url`、`api_token`（与 relay 共享的鉴权密钥）、`game_port`

5. **依赖极简**：仅依赖 Python 标准库 + `requests`（软路由 Python 环境有限）；Npcap 仅 Windows 需要

### relay/ 子项目（云服务器）

6. **状态存储**：内存 dict，存最新 snapshot（仅保留当前局）

7. **HTTP API**（FastAPI）：
   - `POST /register`：接收 extractor 上传的 `{handshake_blob, auth_token_12b, api_token}`，存入配置
   - `POST /push`：接收 extractor 推送的实时 snapshot（场景A）
   - `GET /state?token=xxx`：返回最新 snapshot；无数据时 `{"phase": "idle"}`；无效 token 401

8. **主动客户端模式**（场景B，extractor 不在线时自动启用）：用存储的 token 主动 TCP 连接游戏服务器，完整握手序列（0x000F×2 → 0x0001 → keepalive → 0x0006），响应心跳（0x0002），通过 `SocketMJDecoder` + `PacketStateTracker` 重建状态；extractor 上线推送时自动降级为被动接收

9. **断线重连**：主动模式下指数退避重连

10. **配置文件** `relay/config.yaml`：`api_token`、`game_server_ip`、`game_server_port`

## Acceptance Criteria

* [ ] 软路由器/PC 运行 extractor 时，首局游戏结束后 relay `/register` 已收到 token
* [ ] 随后打牌，`GET /state` 在 2 秒内返回正确手牌（场景A：extractor 推送）
* [ ] 停止 extractor 后，relay 自动切换到主动客户端模式（场景B）
* [ ] 两种场景下 `GET /state` 均返回相同格式数据
* [ ] 无效 token 返回 401；游戏未进行返回 `{"phase": "idle"}`

## Definition of Done

* `remote/extractor/` — 跨平台抓包 + token 提取 + 自动上传 + 实时推送
* `remote/relay/` — FastAPI 服务，token 存储 + 主动客户端 + 状态 API
* `remote/extractor/README.md` — Windows 和 OpenWRT 部署说明
* `remote/relay/README.md` — 云服务器部署说明（pip install + uvicorn 启动命令）

## Research Findings（已完成）

详见 `research/auth-protocol.md`，关键结论：

- 握手序列：`0x000F×2 → 0x0001(handshake_blob) → keepalive → 0x0006(auth token) → 0x0004(服务端确认)`
- `auth_token` = `[4B session prefix][12B user token]`，后12字节跨会话固定，前4字节可用随机值
- `PacketStateTracker` 零改造可复用；`MJProtocol._decode_frame()` 需加 socket 适配器 `SocketMJDecoder`
- 心跳 0x0002 必须响应；0x0003 在认证阶段发送（payload 固定）
- `handshake_blob` 和初始化包（0x000F）payload 从真实 pcap 提取后固定使用

## Decision (ADR-lite)

**Context**: 用户在家有软路由，外出无本地设备；游戏服务器允许同账号双端在线

**Decision**: 双模式 relay —— 有 extractor 在线时被动接收推送，extractor 离线时主动连接游戏服务器；两个场景对外暴露同一 API

**Consequences**: 家里和外出均可用；软路由无需 Npcap；relay 逻辑稍复杂但两种数据源格式相同（都是 snapshot JSON）

## Out of Scope

* 历史局数据持久化
* 多账号支持
* WebSocket 实时推送（HTTP 轮询即可）
* Android/ADB 场景
* extractor 的图形界面

## Technical Notes

### 可复用代码（来自 stable/）
* `stable/protocol.py` → `NpcapCapture`（Windows）、`build_tcpdump_command`（Linux）、`MJProtocol._decode_frame()`
* `stable/tracker.py` → `PacketStateTracker`（完整复用，零改造）
* `stable/mapping.py` → `MappingStore`（relay/ 需携带 `data/stable_reader/mappings.yaml` 或内联映射）

### extractor/ 新增组件
* `SocketMJDecoder`：从 TCP socket bytes 流解码 ProtocolMessage（绕过 pcap dict 格式）
* token 提取逻辑：监听 0x0001/0x0006 C->S 包，过滤出 handshake_blob 和 auth_token_12b

### relay/ 新增组件
* `GameClient`：asyncio TCP 客户端，主动握手 + 认证 + 心跳响应
* FastAPI app：`/register`、`/push`、`/state` 三个端点
* 模式切换逻辑：extractor 推送超时（>30s 无 /push）→ 自动启动 GameClient

### 帧构造（主动发包）
```python
def build_frame(msg_type, payload, sub_type=0x047b, extra=b'\x38\x56\x4c\x05'):
    hdr = bytes([0x01, 0x40])
    hdr += struct.pack('<H', len(payload))
    hdr += struct.pack('<H', msg_type)
    hdr += struct.pack('<H', sub_type)
    hdr += extra
    return hdr + payload
```

### OpenWRT 软路由注意事项
* Python 3.6+ 即可（避免使用 3.10+ 新语法）
* 依赖仅 `requests`（`opkg install python3-requests`）
* tcpdump 通常已内置，用 `build_tcpdump_command` 生成命令并 subprocess 调用
