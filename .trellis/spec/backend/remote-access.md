# Remote Game Data Access Spec

> `remote/` 子项目的架构契约。  
> 实现于 2026-06，见 `remote/extractor/` 和 `remote/relay/`。

---

## 1. 架构：双模式中继

```
场景A（本地抓包在线）
  游戏机 → 网络 → 游戏服务器
              ↑ 流量经过软路由或本机
         extractor/
           被动嗅探 port 7777
           提取 token → POST /register（一次性）
           推送 snapshot → POST /push（每局每帧）
                    ↓ HTTP
              relay/（云服务器）
              GET /state → 返回最新 snapshot

场景B（extractor 离线，如外出打牌）⚠️ 不可用
  游戏机 → 网络 → 游戏服务器
                       ↑ relay 试图作为第二客户端
              relay/ GameClient
              主动 TCP 连接 → 跳过 SRS 认证层(0x0001/0x0005 native .so)
              → 服务端立即关闭连接（存活 0.0 秒）
              → GameClient 无法工作

> **2026-06-11 最终结论**：GameClient 不可行。游戏连接的 SRS 认证层
> （0x0001 sub=0x0000 握手、0x0005 reauth 加密帧、m_key 协商）全部
> 在 native libcocos2dlua.so 中实现，纯 Python 无法复现。
> apk_research 结论已确认。正确的断热点方案是软路由/NAS 部署 extractor，
> 或使用 VPN 隧穿（见场景C）。
> 当缺少 auth_token_12b 时 GameClient 自动启动已被禁用。

场景C（VPN 隧穿，出门 4G 可用）
```
手机(任意网络/4G) ──IKEv2 IPSec──▶ 云服务器[strongSwan + extractor + relay]
  系统 VPN（无需 app）                 │ sniff -i any    GET /state
  全量隧道 0.0.0.0/0                  │                  │
  (Android 原生 VPN 强制)            └── POST /push ────┘
                                               │
                                         游戏服务器:7777
```

> **VPN 隧穿原理（Option A：纯 PSK）**：手机用 Android 系统自带 VPN
> （Settings > VPN > Add > 类型 **`IKEv2/IPSec PSK`**），不需要装任何 app、
> 不需要证书、不需要用户名密码。认证为**双向 PSK**：strongSwan 配置
> `leftauth=psk` + `rightauth=psk`，`ipsec.secrets` 用单行 `: PSK "..."`
> 匹配 `%any` road-warrior 客户端；`rightsourceip=10.99.0.0/24` 给手机分配虚拟 IP。
> 手机端只需手填 **3 个字段**：类型（`IKEv2/IPSec PSK`）、服务器、预共享密钥
> （标识符留空、不填用户名密码）。**类型必须选 PSK，选 RSA/证书 或 MSCHAPv2
> 都会卡在"正在连接…不安全"连不上。**
> **隧道必须全量 `leftsubnet=0.0.0.0/0`（不能 split tunnel）**：Android 系统自带
> VPN 客户端请求 `0.0.0.0/0`，若服务器把流量选择器收窄成 `47.96.0.227/32`，
> 客户端会拒绝并在握手成功后立刻发 DELETE 自杀（现象＝手机"已连接"零点几秒即变"失败"）。
> server-side split tunnel **只有 strongSwan app 支持**，系统 VPN 不支持。代价：手机全部
> 流量经云服务器（需 `iptables -t nat ... -s 10.99.0.0/24 -o eth0 MASQUERADE` + FORWARD ACCEPT）。
> 云服务器上 strongSwan 解密 IPSec → 内核 xfrm → extractor 用 `tcpdump -i any` 嗅探。
> 手机自己完成登录/加密/打牌，extractor 不碰认证层。
> 详见 `remote/extractor/vpn/README.md`。
>
> **实战三坑（2026-06-11 真机打通存档）**：
> 1. **手机类型选错**：选 `IKEv2/IPSec RSA`/`MSCHAPv2` → 永远卡"正在连接…不安全"。必须 `IKEv2/IPSec PSK`。
> 2. **抓包解析全失败（大帧在流但 relay 一直 idle）**：新版 libpcap 的 `tcpdump -i any`
>    产出链路类型 **LINUX_SLL2（DLT 276，头20字节）**，旧 `PcapParser` 只认以太网/raw-IP，
>    每包错位丢弃。已在 `stable/protocol.py` 的 `PcapParser._parse_packet` 增加 SLL(113)/SLL2(276) 分支修复。
> 3. **解析出帧但 push 401**：extractor 与 relay 的 `api_token` 必须一致，否则 `/push` 被拒、relay 永远 idle。
> 4. **服务端进程存活**：extractor 用 `systemd-run --unit=mjx ...` 常驻；裸 `nohup &` 经 SSH 会话起会被 HUP 收掉。
> 5. **阿里云**：安全组必须放行入方向 **UDP 500 + UDP 4500**（TCP 通不代表 UDP 通，否则握手包根本到不了，且报错很安静）。
>
> **部署**：`package_extractor.py --with-vpn --vpn-server-ip <公网IP>` 将 strongSwan 模块
> （`install_vpn.sh`, `vpn_configure.py`, README + 生成的纯 PSK `ipsec.conf`/`ipsec.secrets`/
> `phone-setup.txt`）预配置打包进 bundle。云端解包后按 vpn/README.md 部署。
> 纯 PSK 方案首次在手机手填 3 字段即可，无需 captive portal / `portal.py` 自动投送配置。
> 一次配置手机，之后永远自动连接。
```

**模式切换**：`push_timeout` 可配置（默认 10s），超过此时间无 `/push` →
检查凭证完备性。若 auth_token_12b 缺失则不启动 GameClient（已知不可行），
仅通过 `/state` 的 `credential_ready: false` 告知调用方需部署 extractor。

---

## 1.5 三模式架构（2026-06-12）

三种手牌读取模式独立运行，各自监听不同端口，拥有独立的 StateStore 和 FastAPI app。

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
│     │            │(vpn接口) │    │ :8003       │               │
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
└────────────────────────────────────────┘
```

### 端口分配

| 模式 | 端口 | API Token 配置 | 配置文件 | 说明 |
|------|------|----------------|----------|------|
| hotspot | 8000 | `config_hotspot.yaml` | `acec67bfa9e518b5906d3e6a` | 手机连PC热点 → PC抓包推送 |
| vpn | 8001 | `config_vpn.yaml` | `8f2e7c91b4d53a6f10e9c827` | 手机VPN → ECS抓包推送 |
| noconfig | 8002 | `config_noconfig.yaml` | `d4a8e1f29c6b7305e8d1f264` | SRS spectator直连游戏服务器 |
| spectator | 8003 | (noconfig模式子进程) | 同noconfig token | 无配置模式的旁观服务 |

### 启动命令

```bash
# 单模式
python remote/relay/main.py --mode hotspot          # :8000
python remote/relay/main.py --mode vpn              # :8001
python remote/relay/main.py --mode noconfig         # :8002

# 三模式同时
python remote/relay/main.py --all                   # :8000/:8001/:8002

# 自定义端口
python remote/relay/main.py --mode hotspot --port 9000
```

### 本地 bat 快捷启动

| Bat 文件 | 功能 | 端口 |
|----------|------|------|
| `1_relay_hotspot.bat` | 热点模式 relay | :8000 |
| `2_relay_vpn.bat` | VPN模式 relay | :8001 |
| `3_relay_noconfig.bat` | 无配置模式 relay + spectator | :8002/:8003 |
| `4_relay_all.bat` | 三模式同时启动 | :8000-8002 |
| `5_extractor_hotspot.bat` | 热点模式 extractor (Npcap, 需管理员) | → :8000 |
| `6_extractor_vpn_ecs.bat` | VPN模式 extractor → ECS | → :8001 |
| `hotspot_one_click.bat` | 热点一键启动 relay+extractor | :8000 |
| `0_three_mode_e2e.bat` | 三模式E2E总控(启动+验证) | :8000-8002 |
| `deploy_ecs_local.bat` | 打包→上传→SSH到ECS一键部署 | - |

### 模块化目录结构（2026-06-12）

每个模式已抽成独立 Python 包，**不要把三个模式的代码写在一起**：

```
remote/
├── hotspot/           # 热点模式独立包（已稳定，不要修改）
│   ├── __init__.py
│   ├── app.py         # FastAPI app + configure()，仅含 hotspot 路由
│   └── main.py        # argparse 入口，default port 8000
├── vpn/               # VPN模式独立包
│   ├── __init__.py
│   ├── app.py         # FastAPI app + configure()，含 /vpn-setup /ca.crt /mahjong-vpn.p12
│   └── main.py        # argparse 入口，default port 8001
├── noconfig/          # 无配置模式独立包
│   ├── __init__.py
│   ├── app.py         # FastAPI app + configure()，含 /register-room /watch-info + spectator 管理
│   └── main.py        # argparse 入口，default port 8002
├── relay/             # 多模式兼容入口（保留，勿删）
│   ├── main.py        # --mode hotspot/vpn/noconfig/--all，使用 RelayApp from core.py
│   ├── core.py        # RelayApp 类（--all 模式的子进程 worker 用）
│   ├── state_store.py # StateStore（三个模块共用）
│   └── ...
├── srs_spectator/     # SRS旁观协议实现（不含 relay 逻辑）
└── extractor/         # 抓包工具
```

> **黄金规则**：新增功能找对目录再动手。热点专属改 `remote/hotspot/`，VPN 专属改 `remote/vpn/`，noconfig/spectator 改 `remote/noconfig/`，多模式兼容改 `remote/relay/`。

### sys.path 规范

每个模块的 `app.py` 和 `main.py` 都必须在文件头设置三条 sys.path：

```python
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_RELAY_DIR = os.path.join(_ROOT, "remote", "relay")
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if _RELAY_DIR not in sys.path:
    sys.path.insert(0, _RELAY_DIR)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
```

原因：`from state_store import StateStore` 需要 `_RELAY_DIR` 在 path 里；`from app import app, configure` 需要 `_HERE` 在 path 里。

### app.py 模板规范

每个模式的 `app.py` 必须遵循：

```python
# 全局运行时状态（线程不安全，uvicorn 单进程单线程 OK）
_cfg: dict = {}
_cfg_path: str = ""
_state_store: StateStore = StateStore()

def configure(cfg: dict, cfg_path: str = ""):
    """main.py 启动时调用一次，注入配置"""
    global _cfg, _cfg_path, _state_store
    _cfg = dict(cfg)
    _cfg_path = cfg_path
    push_timeout = float(cfg.get("push_timeout", 10.0))
    _state_store = StateStore(push_timeout=push_timeout)

app = FastAPI(title="MahjongAI <Mode> Relay")
```

### noconfig 模块 spectator 子进程契约

```python
# 模块级状态
_srs_spectator_proc: subprocess.Popen | None = None
_spectator_restart_count: int = 0
_SPECTATOR_MAX_RESTARTS: int = 5

# 必须注入的环境变量（缺一不可）
env["AUTH_TOKEN_12B"]  = cfg["auth_token_12b"]   # hex
env["HANDSHAKE_BLOB"]  = cfg["handshake_blob"]    # hex
env["SRS_SESSIONID"]   = cfg["srs_sessionid"]     # hex, 32+ chars
env["RELAY_URL"]       = "http://127.0.0.1:8002"  # noconfig 端口
env["API_TOKEN"]       = cfg["api_token"]
env["USERID"]          = cfg.get("userid", "newpt1084306678")
env["BIND_PORT"]       = "8003"                    # spectator 监听端口，固定
env["PYTHONPATH"]      = f"{_ROOT}:{_ROOT}/remote/srs_spectator"
```

健康检查逻辑：每次 `/state` 调用 `_ensure_spectator_running()`，用 `proc.poll() is not None` 检测进程退出，超过 `_SPECTATOR_MAX_RESTARTS` 后停止重启。`/push` 端点收到推送时调用 `_stop_spectator()`（extractor 上线，不需要 spectator）。

### VPN 模块证书服务端点

VPN 模块的 `app.py` 包含以下额外端点（不属于 hotspot 和 noconfig）：

| 端点 | 文件来源 | 说明 |
|------|----------|------|
| `GET /vpn-setup` | `static/vpn-setup.html` → inline fallback | 手机端 VPN 配置向导页 |
| `GET /mahjong-vpn.p12` | `/opt/mahjong-extractor/mahjong-vpn.p12` | PKCS12 客户端证书 |
| `GET /ca.crt` | `/etc/ipsec.d/cacerts/ca.crt` | strongSwan CA 证书 |

### 隔离性保证

- 每个模式有独立 Python 包 → 互不导入、互不依赖
- 每个模块的 `_cfg`/`_state_store` 是模块级私有 → 无跨模式状态污染
- api_token 各不相同 → 跨模式 token 自动被 401 拒绝
- 凭证持久化到各自配置文件 → 互不干扰
- `relay/main.py --all` 使用 `multiprocessing.Process` → 进程级隔离

### extractor 多目标推送

`relay_urls` 支持列表，可同时推送到多个模式：

```yaml
# remote/extractor/config.yaml
relay_urls:
  - http://8.136.37.136:8000   # 热点模式
  - http://8.136.37.136:8001   # VPN模式
```

向后兼容：`relay_url`（单字符串）仍可用，`relay_urls` 优先。

### ECS 云端部署

`deploy_ecs.sh` 一键部署 5 个 systemd 服务：

| 服务名 | 说明 | 自动重启 |
|--------|------|----------|
| `mahjong-relay-hotspot` | 热点模式 :8000 | always, 5s |
| `mahjong-relay-vpn` | VPN模式 :8001 | always, 5s |
| `mahjong-relay-noconfig` | 无配置模式 :8002 | always, 5s |
| `mahjong-spectator` | SRS旁观 :8003 | always, 10s |
| `mahjong-extractor-vpn` | VPN抓包(需VPN连接) | always, 5s |

安全组需放行：TCP 8000/8001/8002/8003，UDP 500/4500（IPSec）。

### E2E 测试

```bash
python e2e_test.py --temp         # 临时启动relay验证（不依赖已运行服务）
python e2e_test.py --local        # 测试已运行的本地relay
python e2e_test.py --cloud        # 验证云端ECS连通性
python e2e_test.py --cloud-only   # 仅验证云端
python e2e_test.py --ecs-ip X.X.X.X  # 指定ECS IP
```

覆盖 6 个测试套件：
1. **RelayStartup** — 三模式 /mode + /state 鉴权
2. **ModeIsolation** — 推送到A不影响B，跨模式token被拒绝
3. **ExtractorLink** — 模拟推送 + 凭证注册 + 房间注册
4. **CloudConnectivity** — ECS 三模式 + spectator 可达
5. **SpectatorCheck** — spectator /status + /watch 鉴权
6. **LocalRelayTemp** — 临时启动三模式relay完整集成测试

---

## 1.6 SRS 协议层实测结论（2026-06-13）

### SRS 保活/重连机制

| 结论 | 来源 | 细节 |
|------|------|------|
| **msgid=3 (ReqKey) 是握手消息，不是心跳** | 实测 + forensic 分析 | msgid=3 总是跟在 msgid=1 (EncryptVer) 后面出现，是三步握手的第二步 (EncryptVer→ReqKey→HandshakeRsp)。握手完成后发 msgid=3 → 服务端立即断连 |
| **服务端 idle timeout = 120s** | 实测验证 | 握手完成后不发任何数据，服务端精确在 120s 后主动关闭 TCP 连接 |
| **srs_sessionid 可在多条连接间复用** | 长期实测有效 | 同一个 16B sessionid 在断线后重连 flag=0（成功）；经长期实测验证永久有效，无需过期刷新 |
| **解法：断线后自动重连，不是心跳** | 架构决策 | 检测 on_disconnect → 2s 延迟 → 重新执行完整 SRS 握手 + PlayerConnect，无限循环到 stop_watch() |

### SRSSessionExtractor 断连重置 Bug（已修复）

**问题**：`SRSSessionExtractor` 第一次见到 HandshakeRsp 时设置了 `_session_key`，但若该连接未完成 PlayerConnect 提取（extractor 重启等情况），`_session_key` 非 None，下次新连接的 HandshakeRsp 被 `if self._session_key is None` 过滤掉，导致永远提取不到 srs_sessionid。

**修复**（`remote/extractor/token_extractor.py`）：
```python
# Wrong：首次提取后 session_key 永不重置，新连接 HandshakeRsp 被忽略
if msg_type == 4 and direction == "S->C" and self._session_key is None:
    ...

# Correct：每次新 HandshakeRsp 都重置，保证新连接能重新提取
if msg_type == 4 and direction == "S->C":
    self._session_key = None   # 重置旧 session_key，保证下一步能成功
    self._sessionid = None
    ...
```

### WatchState 自动重连模式

```python
RECONNECT_DELAY = 2.0  # 断线后等 2s 再重连

class WatchState:
    def _connect_once(self, roomid, gameid) -> bool:
        client = SRSClient(...)

        def on_disconnect():
            if self._stop_requested: return
            if self.active_roomid != roomid: return   # 房间已切换，不重连
            logger.info("SRS disconnected, reconnecting in 2s...")
            self.watching = False
            time.sleep(RECONNECT_DELAY)
            if not self._stop_requested and self.active_roomid == roomid:
                self.watching = True
                if not self._connect_once(roomid, gameid):
                    logger.error("Auto-reconnect failed, giving up")
                    self.watching = False

        client.on_disconnect(on_disconnect)
        ...
```

> **Gotcha**: `on_disconnect` 在 recv 线程调用，`time.sleep` 会阻塞 recv 线程直到下次重连完成。`_connect_once` 是递归调用——每次断线会新建 SRSClient，新线程。不会因递归栈溢出（每次 sleep 2s，服务端 idle timeout 120s，最多每 122s 一次递归）。

### PlayerData flag 含义（实测）

| flag | 含义 |
|------|------|
| 0 | 认证成功，sessionid 有效 |
| 22 | sessionid 完全无效（格式错误/全零） |
| 38 | 解密失败（乱码），密钥不匹配 |
| 41 | PlayerConnect 格式 bug（已修复后不再出现） |
| 72 | sessionid 无效/服务端不认识（长期实测验证 sessionid 永久有效，此 flag 仅在新连接使用错误 token 时出现） |

### SRS 旁观局限性（关键）

**旁观协议（ReqRealtimeGameRecord, msgid=3000, sub_type=100）只能看到公开信息（打出的牌、弃牌、鸣牌），手牌显示为"牌背"，无法获取隐藏手牌。**

这是服务端协议设计决定的——服务端只向旁观者发送公开事件，不发送手牌内容。

若目标是获取完整手牌（含隐藏牌），旁观模式走不通，唯一可行路径：
- **VPN 被动嗅探**（已上线 2026-06-13）：手机流量过 ECS，被动抓 7777 端口
- **Frida siphon**（手机进程 hook）：hook recv，拦截发给手机的数据包并转发云端（另立任务）
- **云端以玩家身份登录**（未探索）：理论上能收到手牌，但会踢掉手机

---

## 2. API 契约（relay/）

### POST /register

```
Request body (JSON):
  handshake_blob:  str  # hex 编码，账号绑定 blob（0x0001 payload）
  auth_token_12b:  str  # hex 编码，12B user token（0x0006 payload bytes 4-15）
  api_token:       str  # 与 relay config.yaml 中的 api_token 一致

Response 200: {"status": "registered"}
Response 401: {"detail": "Invalid api_token"}
```

**副作用**：注册成功后自动将 `handshake_blob` + `auth_token_12b` 持久化到 relay
的 `config.yaml`。relay 重启后自动从配置文件加载凭证，无需 extractor 重新注册。
若 `config.yaml` 不可写（只读文件系统、权限不足），仅写 WARNING 日志，不影响内存中的注册状态。

### POST /push

```
Request body (JSON):
  snapshot:   dict  # PacketStateTracker.snapshot() 的输出
  api_token:  str

Response 200: {"status": "ok"}
Response 401: {"detail": "Invalid api_token"}
```

### GET /

```
返回实时手牌展示页(static/index.html)。页面内 JS 轮询 /state?token= 渲染本家整桌
(手牌/摸牌高亮/弃牌/副露 + 对手弃牌/副露 + phase/剩余/百搭)，CSS 画牌零图片资源。
云端打开 http://<云IP>:8000/ 即可看；本地 http://127.0.0.1:8000/?token=<token>。
snapshot.players[pid].hand 是字符串牌列表(如 "3m")，页面直接解析。
```

### GET /state

```
Query params:
  token: str  # 与 relay config.yaml 中的 api_token 一致

Response 200: <snapshot dict>  或  {"phase": "idle", "data_source": "game_client"}（未注册或无数据时）
Response 401: {"detail": "Unauthorized"}
```

snapshot 固定包含 `data_source` 和 `credential_ready` 字段：
- `data_source`: `"extractor"`（场景A）/ `"game_client"`（场景B / idle）
- `credential_ready`: `true` 当 relay 持有有效认证凭证（断热点后 GameClient 可自动接管），`false` 表示需先连热点让 extractor 注册凭证

> **Design Decision**：`/state` 使用 `token` 而非 `api_token` 作为参数名，因为这是面向外部调用方的 API，与内部 extractor 通信的 `api_token` 区分开，但验证逻辑相同（对比同一个 config.api_token）。

---

## 3. extractor 配置

```yaml
# remote/extractor/config.yaml
relay_url: "http://your-server:8000"
api_token: "your-secret-token"  # 与 relay config 相同
game_port: 7777
```

## relay 配置

```yaml
# remote/relay/config.yaml
api_token: "your-secret-token"
game_server_ip: "47.96.0.227"   # 游戏服务器 IP（可能随版本变化）
game_server_port: 7777
handshake_blob: ""              # 十六进制，extractor 注册后自动填充
  # 持久化，relay 重启后仍可用
auth_token_12b: ""              # 十六进制，extractor 注册后自动填充
  # 持久化，relay 重启后仍可用
```

`handshake_blob` 和 `auth_token_12b` 在 extractor 调用 `/register` 时自动写入，
relay 重启后从文件加载。**不要把含真实凭证的 config.yaml 提交到仓库**——
仓库默认值应为空字符串占位符。部署到云服务器时用 `package_extractor.py`
生成的 `config.no-hotspot.yaml` 或通过 `bootstrap_remote_config.py` 本地生成。

---

## 4. sys.path 规则

extractor 和 relay 都复用 `stable/` 下的代码，必须在 import 前设置路径：

```python
import os, sys
# 从 remote/extractor/ 或 remote/relay/ 向上两级到项目根
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stable.protocol import MJProtocol, NpcapCapture, PcapParser
from stable.tracker import PacketStateTracker
from stable.mapping import MappingStore
```

> **Common Mistake**：在 `main.py` 设置了 sys.path，但在其他模块顶层直接 import stable.*。模块被首次 import 时 sys.path 修改可能还没执行。解决方案：在每个需要 import stable.* 的文件顶部都加路径设置，或确保 main.py 是唯一入口且在 import 其他本地模块前先设好路径。

---

## 5. 跨平台抓包（extractor）

| 平台 | 方式 | 依赖 |
|------|------|------|
| Windows | NpcapCapture（scapy） | Npcap 驱动 + scapy |
| Linux / OpenWRT | tcpdump subprocess + PcapParser | tcpdump（通常内置） |

> **VPN 自动检测**：在 Linux 上，当 `interface=any` 时 `TcpdumpCaptureAdapter` 会
> 检测虚拟网卡（wg0 等），存在则自动使用。strongSwan/IPSec 使用内核 xfrm 解密，
> 流量在 `-i any` 上可见，BPF filter `port 7777` 过滤。Windows 暂不支持自动检测。

> **抓包网卡必须是承载手机流量的那张（关键坑）**：全本机+热点拓扑下，手机流量走热点网卡（IP `192.168.137.1`，Microsoft Wi-Fi Direct Virtual Adapter），**不是** scapy 的默认 `conf.iface`。`NpcapCaptureAdapter` 必须把 interface 传给 `NpcapCapture(iface=...)`；当 interface 为 `any`/None 时用 `find_hotspot_iface()` 自动选中 IP==192.168.137.1 的网卡。早期 bug：adapter 丢弃 interface 参数 → 嗅探默认网卡 → 一个包都收不到、phase 永远 idle。验证：在热点网卡上 `tcp port 7777` 能抓到 `手机IP → 47.96.0.227:7777`。

```python
import platform

def create_capture(config):
    if platform.system() == 'Windows':
        return NpcapCaptureAdapter(config)
    else:
        return TcpdumpCaptureAdapter(config)
```

**软路由常开部署**：`remote/extractor/package_extractor.py` 把 extractor 运行所需最小模块集
（`stable/{protocol,tracker,mapping}` + `battle/{__init__,state}` + `game/` + `utils/`，**不含 cv2/numpy**，
依赖 `battle/__init__.py` 的 BattleService 懒加载解耦）打成 bundle，配 `install_openwrt.sh`(procd) /
`install_linux.sh`(systemd) / `selfcheck_capture.sh`(验证流量经过本机) / `DEPLOY.md`。relay 部署在云服务器。
详见 `remote/extractor/DEPLOY.md`。

普通 WiFi / no-hotspot 部署应优先用预配置打包，不要手工修改仓库默认配置：

```bash
python remote/extractor/package_extractor.py \
  --relay-url http://<云服务器公网IP>:8000 \
  --write-relay-config remote/relay/config.no-hotspot.yaml \
  -o mahjong-extractor-no-hotspot.tar.gz
```

该命令会生成共享 `API_TOKEN`、把云端 `relay_url` 写入 bundle 内部的
`remote/extractor/config.yaml`，并写出匹配的 relay config。安装脚本支持
`RELAY_URL/API_TOKEN/IFACE/INSTALL_DIR` 环境变量免交互安装。**不要把真实 token 写回仓库默认
`remote/extractor/config.yaml` 或 `remote/relay/config.yaml`。**

**OpenWRT Python 版本**：按 Python 3.6 兼容性编写 extractor：
- 禁用 `:=` walrus operator（3.8+）
- 禁用 `match` 语句（3.10+）
- 禁用 `dataclasses`（3.7+）
- 禁用 `dict | dict` 合并（3.9+）
- 允许 f-string（3.6+）

---

## 6. Token 提取触发条件

```python
# 只需一次：handshake_blob 和 auth_token_12b 都提取到后触发 /register
# 此后即使重启 extractor 也不再重新注册（relay 已有存储）

def on_message(self, message: ProtocolMessage):
    if self._handshake_blob is None:
        if message.msg_type == 0x0001 and message.direction == 'C->S':
            self._handshake_blob = message.payload.hex()

    if self._auth_token is None:
        if message.msg_type == 0x0006 and message.direction == 'C->S':
            if len(message.payload) == 16:
                self._auth_token = message.payload[4:16].hex()  # bytes 4-15！

    if self._handshake_blob and self._auth_token and not self._registered:
        self._do_register()
        self._registered = True
```

---

## 7. MappingStore 部署

relay/ 运行时需要 tile mapping 数据。两种方式：

1. **跟随部署**：将 `data/stable_reader/mappings.yaml` 复制到云服务器，保持路径结构
2. **内联模式**：`MappingStore(path=None)` 无 YAML 也能运行，使用内置 `_builtin_tile` 逻辑（遇到 unknown 会标记，但不报错）

推荐方式2（内联模式），减少部署文件数量。

---

## 8. 本地测试

### 全本机部署拓扑（单机 + 电脑模拟路由器）

当 extractor 与 relay 都跑在同一台 Windows 电脑、且用「电脑当路由器」给手机供网时：

```
手机登录游戏 ──Wi-Fi──▶ 电脑(Windows 移动热点/ICS) ──▶ 互联网→游戏服务器
                            │ 手机流量经过电脑网卡
                            ├─ extractor 嗅探共享网卡 → POST /register/push
                            └─ relay (127.0.0.1:8000) GET /state
```

- relay 与 extractor 同机 → `extractor/config.yaml` 的 `relay_url` 应为 `http://127.0.0.1:8000`（默认占位符 `your-relay-server` 需手动改）。
- **电脑必须先开 Windows 移动热点或 ICS**，手机连此热点，游戏流量才会过本机网卡被 Npcap/scapy 嗅探到。
- **关键自检信号**：Windows 移动热点和 ICS 的默认网关固定是 `192.168.137.1`。`ipconfig` 输出里出现该地址 = 路由器模拟已生效；没有 = 热点/ICS 未开，extractor 抓不到包。
- extractor 必须嗅探「承载手机流量的共享适配器」，不是 WAN/本地以太网口。
- 此拓扑下主路径是场景A（被动嗅探 + push）；场景B（GameClient 主动连云端）基本用不到。

### 一键测试 + 诊断脚本

```bash
# 在项目根目录，命令行
python test_remote.py        # 单元 + 集成测试（13 用例），日志 logs/test_remote_<ts>.log
python diagnose_remote.py    # 本机链路在线诊断（A-E 五项），日志 logs/diagnose_remote_<ts>.log

# 或一键：项目根双击
test_remote.bat              # 检查 Python/venv/依赖 → 跑上面两个脚本 → 汇总 + 日志路径
```

`diagnose_remote.py` 五项检查：A relay 依赖、B extractor 抓包依赖(scapy+Npcap)、C relay `/state` 可达性、D 路由器模拟自检(查 192.168.137.1)、E 游戏服务器 7777 连通(参考项)。四态 PASS/WARN/FAIL/SKIP，仅 FAIL 才 exit 1（WARN 不算失败）。**凭证/token 落盘前必须 `_mask` 脱敏**（只露前 4 位 + 长度）。

### 一键真实运行 launcher（区别于上面的测试）

`test_remote.bat` 只做测试/体检、不碰真实链路；**真正跑起来抓数据**用 `run_remote.bat`：

```
run_remote.bat   (项目根双击，纯 ASCII)
  1. UAC 自提权（extractor 抓包需管理员）
  2. 检查 Python/venv/依赖
  3. python bootstrap_remote_config.py  — 幂等：占位符 api_token → secrets.token_hex(12)，
       同步写 relay+extractor 两个 config，extractor relay_url=127.0.0.1:8000
  4. enable_hotspot.ps1  — WinRT NetworkOperatorTetheringManager 尝试自动开移动热点，
       失败回退手动指引；再轮询 ipconfig 等 192.168.137.1
  5. 新窗口起 relay (remote/relay/main.py)，轮询 /state 直到就绪（token 'x' 收 401 也算就绪）
  6. 新窗口起 extractor (remote/extractor/main.py)
  7. 前台跑 watch_state.py — 每 2s GET /state，snapshot 变化才打印
```

配套脚本：
- `bootstrap_remote_config.py`：幂等生成/同步配置，stdout 打印 `API_TOKEN=<token>`。**不要把生成后的真 token 提交进仓库**——仓库里两个 config 保持占位符，用户首次运行本地生成。
- `watch_state.py`：实时轮询打印牌局，ConnectionError 每 5s 提示一次不刷屏，401 提示重跑 bootstrap，Ctrl+C 优雅退出。
- `enable_hotspot.ps1`：任何异常都 `exit 0`（不让热点失败中断 launcher）。

> bat 的 `set FLAG=1` + `goto :label` 跳出 `for` 循环是规避延迟展开的正确模式；不要在括号块内 `%FLAG%` 读同块刚 set 的值。

覆盖三个层次：
- **Suite 1 StateStore**：直接 import `remote/relay/state_store.py`，4 个纯单元测试，无网络依赖
- **Suite 2 TokenExtractor**：import `remote/extractor/token_extractor.py`，用 `namedtuple` 构造 FakeMsg 模拟协议消息，4 个单元测试
- **Suite 3 RelayAPI**：用 `subprocess.Popen` 在 `127.0.0.1:18765` 启动真实 relay 进程，5 个 HTTP 集成测试

### 集成测试的临时 config 模式

Suite 3 采用「写临时 config → 传 --config → finally 删除」模式，避免污染正式配置：

```python
# 写临时配置
tmp_cfg = "remote/relay/test_config_tmp.yaml"
with open(tmp_cfg, "w") as f:
    f.write('api_token: "test_secret"\n...')

# 以子进程启动
proc = subprocess.Popen([sys.executable, "remote/relay/main.py",
                         "--config", tmp_cfg,
                         "--host", "127.0.0.1", "--port", "18765"])

# 等待就绪（轮询 GET /state，最多 10 秒）
for _ in range(20):
    time.sleep(0.5)
    try:
        r = requests.get("http://127.0.0.1:18765/state", params={"token": "test_secret"}, timeout=2)
        if r.status_code in (200, 401):
            break  # 服务就绪
    except Exception:
        pass

# finally 中终止进程并删除临时 config
proc.terminate()
os.remove(tmp_cfg)
```

### FakeMsg 模式（TokenExtractor 单元测试）

`TokenExtractor.feed()` 读取五个字段，用 `namedtuple` 即可模拟，无需真实 `ProtocolMessage`：

```python
FakeMsg = namedtuple("FakeMsg", ["msg_type", "sub_type", "direction", "raw_hex", "pay_len"])

# 构造 0x0001 握手包（19字节 payload）
HEADER = bytes(12)
payload = bytes(range(19))
msg = FakeMsg(
    msg_type=0x0001,
    sub_type=0x047B,
    direction="C->S",
    raw_hex=(HEADER + payload).hex(),
    pay_len=19
)
```

> **注意**：`raw_hex` 是完整帧的 hex（头 + payload），`token_extractor.py` 内部做 `bytes.fromhex(raw_hex)[12:]` 来跳过帧头取 payload。

### 测试退出码

- 全通过：`exit(0)`
- 有失败：`exit(1)`（SKIP 不算失败）

可在 CI 中直接用 `python test_remote.py && echo OK` 检查。

---

## 9. 热点模式独立部署（ECS 云端）

### 部署拓扑

```
手机(游戏App) ──WiFi──▶ PC(Windows 移动热点, 192.168.137.1) ──▶ 互联网
                            │ NpcapCapture 嗅探热点网卡
                            │ extractor → POST /register + /push
                            ↓ HTTP
                     ECS 云服务器 (8.136.37.136)
                     relay :8000 (hotspot mode)
                     GET / → 手牌展示页 (static/index.html)
                     GET /state?token=... → JSON 牌局数据
```

### ECS 部署步骤（已验证 2026-06-12）

```bash
# 1. 上传代码到 ECS
tar -cf ecs-update.tar --exclude=".git" --exclude=".venv" --exclude="__pycache__" \
    --exclude="*.pyc" --exclude="logs" --exclude="dist" --exclude=".obsidian" \
    --exclude=".trellis" --exclude=".claude" --exclude="*.spec" \
    remote/ stable/ game/ config/ deploy_ecs.sh e2e_test.py
scp ecs-update.tar root@8.136.37.136:/tmp/mahjong-update.tar

# 2. SSH 登录 ECS
ssh root@8.136.37.136

# 3. 解压代码
mkdir -p /opt/mahjong-remote
cd /opt/mahjong-remote
tar -xf /tmp/mahjong-update.tar

# 4. 停掉旧版 relay (如果存在)
pkill -f "remote/relay/app.py" 2>/dev/null || true
pkill -f "remote/relay/main.py" 2>/dev/null || true

# 5. 安装 Python deps
pip3 install fastapi uvicorn pyyaml requests cryptography -q

# 6. 创建 systemd 服务
cat > /etc/systemd/system/mahjong-relay-hotspot.service << 'SERVICE'
[Unit]
Description=MahjongAI Relay - Hotspot Mode (Port 8000)
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/mahjong-remote
ExecStart=/usr/bin/python3 remote/relay/main.py --mode hotspot --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

# 7. 启动
systemctl daemon-reload
systemctl enable mahjong-relay-hotspot
systemctl start mahjong-relay-hotspot

# 8. 验证
sleep 3
curl -s http://localhost:8000/mode
# 期望: {"mode":"hotspot","port":8000,"credential_ready":true,...}
curl -s "http://localhost:8000/state?token=acec67bfa9e518b5906d3e6a"
# 期望: {"phase":"idle","credential_ready":true,...}
```

### ECS 配置文件

热点模式配置文件路径：`remote/relay/config_hotspot.yaml`

```yaml
mode: hotspot
port: 8000
api_token: acec67bfa9e518b5906d3e6a  # 与 extractor/config.yaml 中的 api_token 一致
game_server_ip: 47.96.0.227
game_server_port: 7777
handshake_blob: 459937d169da1ecda3c63f5a89a70b94e55d92  # 已提取（extractor 注册后自动填充）
auth_token_12b: 846a29fd572fbbdf89af0fb4  # 已提取
srs_sessionid: ''  # 待提取
push_timeout: 10
spectator_url: ''
```

> **关键约束**：`api_token` 必须与 `remote/extractor/config.yaml` 中的 `api_token` 一致。
> 不一致会导致 `/push` 返回 401，relay 永远 idle。这是一个重复踩坑的高频错误。

### extractor 配置（PC 本地）

```yaml
# remote/extractor/config.yaml
api_token: acec67bfa9e518b5906d3e6a  # 必须与 relay config_hotspot.yaml 一致
relay_url: http://8.136.37.136:8000   # ECS 公网 IP + 端口
game_port: 7777
spectator_forensic_all_heads: true
```

### 阿里云 ECS 安全组

| 端口 | 协议 | 授权对象 | 说明 |
|------|------|----------|------|
| 8000 | TCP | 0.0.0.0/0 | 热点模式 relay (已开放) |
| 8001 | TCP | 0.0.0.0/0 | VPN 模式 relay (待开放) |
| 8002 | TCP | 0.0.0.0/0 | 无配置模式 relay (待开放) |
| 8003 | TCP | 0.0.0.0/0 | SRS spectator (待开放) |
| 500 | UDP | 0.0.0.0/0 | IPSec IKE (VPN) |
| 4500 | UDP | 0.0.0.0/0 | IPSec NAT-T (VPN) |

> **高频坑**：只开了 TCP 不开 UDP 500/4500，VPN 握手包根本到不了，
> 报错很安静（strongSwan 日志才能看到）。

---

## 10. 本地 bat 快捷启动文件

所有 bat 必须遵守以下规则：

### bat 编码规则（2026-06-12 踩坑沉淀）

> **⚠️ Critical**: Windows CMD 默认编码 GBK（cp936），bat 文件中的中文会乱码，
> 导致 `echo 中文` 和 `:: 中文注释` 执行时报错 `'帹閫佸埌relay' 不是内部或外部命令`。
> 这是 CMD 对 UTF-8 bat 的解析 bug。

**规则**：
1. 每个 bat 开头必须加 `chcp 65001 >nul 2>&1` 切换到 UTF-8
2. `::` 注释中不使用中文（CMD 会把 `::` 后的中文字符当作命令执行）
3. `echo` 中文在 `chcp 65001` 后可正常显示，但推荐用英文更可靠
4. `REM` 中文注释比 `::` 更安全（`REM` 不会被当作命令），但仍需 `chcp 65001`

**Wrong vs Correct**:
```bat
:: Wrong - 中文注释被 CMD 当命令执行，乱码报错
:: 热点模式 Extractor — 需管理员权限
echo [启动] 热点模式 extractor ...

:: Correct - chcp 65001 + 英文注释 + 英文 echo
@echo off
setlocal
chcp 65001 >nul 2>&1
REM Hotspot Mode Extractor - needs admin
echo [Start] Hotspot extractor (Npcap) ...
```

### bat 文件索引

| Bat | 功能 | 关键点 |
|-----|------|--------|
| `1_relay_hotspot.bat` | 热点 relay :8000 | 纯 relay，无 extractor |
| `2_relay_vpn.bat` | VPN relay :8001 | 通常在 ECS 上运行 |
| `3_relay_noconfig.bat` | 无配置 relay :8002 | 含 spectator :8003 |
| `4_relay_all.bat` | 三模式同时启动 | multiprocessing |
| `5_extractor_hotspot.bat` | 热点 extractor (Npcap) | 自动 UAC 提权 + 自动检测热点网卡 |
| `6_extractor_vpn_ecs.bat` | VPN extractor → ECS | 本地调试用 |
| `hotspot_one_click.bat` | 热点一键: relay+extractor | 最常用的 bat |
| `0_three_mode_e2e.bat` | E2E 总控: 启动+验证 | 含 e2e_test.py |
| `deploy_ecs_local.bat` | 打包→scp→SSH 部署 | 需要 SSH key 免密 |

---

## 11. 热点模式已踩坑记录

### Common Mistake: `--interface WLAN` 导致抓不到包

**Symptom**: extractor 启动后日志显示 `抓包网卡（显式指定）: WLAN`，但之后零帧日志，relay `phase: idle`。

**Cause**: 手机连 PC 热点时，流量走的是 `Microsoft Wi-Fi Direct Virtual Adapter`（IP 192.168.137.1），不是 WLAN 物理网卡。WLAN 是 PC 连外网的网卡，手机流量不在上面。

**Fix**: 不传 `--interface`，让 extractor 自动检测。`find_hotspot_iface()` 会找 IP==192.168.137.1 的适配器。

**Prevention**: bat 文件中不要硬编码 `--interface WLAN`。`5_extractor_hotspot.bat` 只用 `python remote\extractor\main.py --mode npcap`（不带 --interface）。

### Common Mistake: core.py `/` 路由返回 API 端点页而非手牌页

**Symptom**: `http://ECS:8000/` 显示模式信息页（API 端点列表），看不到手牌数据。

**Cause**: `RelayApp._build_mode_page()` 生成的 HTML 是模式诊断页（/mode 端点列表），旧版 `app.py` 的 `/` 路由用的是 `static/index.html`（实时手牌展示页 + JS 轮询 /state）。三模式 `core.py` 复制路由时用了模式页替代了手牌页。

**Fix**: `core.py` 的 `/` 路由改为 `_build_hand_display_page()`，读取 `static/index.html`；模式诊断页保留在 `/mode` GET 端点。

```python
# core.py _register_routes() — Correct
@self.app.get("/")
async def index():
    return HTMLResponse(content=self._build_hand_display_page())

# _build_hand_display_page() reads static/index.html
# _build_mode_page() only shown at GET /mode
```

**Prevention**: 任何新增 relay 模式的首页路由必须返回手牌展示页，不是模式信息页。模式信息通过 `/mode` API 端点获取。

### Common Mistake: extractor api_token 与 relay 不一致 → push 401

**Symptom**: extractor 日志有帧数据但 `POST /push` 返回 401，relay `phase` 永远 idle。

**Cause**: `remote/extractor/config.yaml` 的 `api_token` 与 `remote/relay/config_hotspot.yaml` 的 `api_token` 不同。

**Fix**: 确保两端配置文件的 `api_token` 值完全一致。

**Prevention**: 部署时先检查两个文件的 api_token 是否一致。或者用 `bootstrap_remote_config.py` 同步生成。

### Gotcha: NpcapCapture L2 sniff 静默失败

> **Warning**: scapy `sniff(filter="tcp port 7777")` 在某些虚拟网卡上可能静默失败
> （不抓任何包也不报错，`_running` 仍为 True）。
> `NpcapCapture.sniff()` 有 L2→L3 回退逻辑，但如果 L2 正常返回且 `_running` 仍 True，
> 会被误判为"L2 成功但无数据"而非"L2 失败需回退"。
>
> 当前实测：热点网卡上 `scapy sniff(iface=hot, filter="tcp port 7777")` **正常工作**
> （抓到 10 个包），但 extractor 运行时可能因其他进程占用 Npcap 或 scapy 全局状态
> 导致静默失败。**解决方法：关闭所有占用 Npcap 的进程后重新启动 extractor**。

### Gotcha: ECS 安全组只开 8000 不开 8001/8002

> **Warning**: 阿里云 ECS 默认安全组只开放了 :8000（热点模式）。
> :8001（VPN）、:8002（无配置）、:8003（spectator）需要手动添加入方向规则。
> 不开的症状：ECS 内网 `curl localhost:8001/mode` 正常，外网 `curl ECS_IP:8001/mode` 超时。
> 需在阿里云控制台添加 TCP 8001/8002/8003 入方向规则。

---

## 12. VPN 模式真机验证记录（2026-06-13）

VPN 模式已真机测试通过：手机连 IKEv2/IPSec PSK VPN → ECS strongSwan 解密 → mjx-vpn extractor 抓包 → :8001 relay → 浏览器实时手牌。

### ECS VPN extractor 部署约定

```bash
# VPN extractor 必须从 /opt/mahjong-extractor 运行（完整模块集含 battle/）
# /opt/mahjong-remote 缺少 battle 模块，会报 ModuleNotFoundError: No module named 'battle'
cd /opt/mahjong-extractor

# config_vpn_ecs.yaml 需手动创建（/opt/mahjong-extractor/remote/extractor/ 目录下）
cat > remote/extractor/config_vpn_ecs.yaml <<'YAML'
relay_url: http://127.0.0.1:8001
api_token: 8f2e7c91b4d53a6f10e9c827
game_port: 7777
YAML

# 常驻启动（必须 systemd-run，裸 nohup 经 SSH 断连会被 HUP 收掉）
systemd-run --unit=mjx-vpn \
  --working-directory=/opt/mahjong-extractor \
  /usr/bin/python3 remote/extractor/main.py --mode tcpdump \
  --config remote/extractor/config_vpn_ecs.yaml

# 验证
systemctl is-active mjx-vpn   # → active
journalctl -u mjx-vpn -n 5    # 应有 "extractor 启动，监听 port 7777 → relay http://127.0.0.1:8001"
```

### Common Mistake: `--interface ipsec0` 导致 extractor 启动失败

**Symptom**: extractor 报错 `No such device: ipsec0` 或卡住不抓包。

**Cause**: `config_vpn_ecs.yaml` 文件头注释写了 `--interface ipsec0`，但 strongSwan 走内核 xfrm 解密，**没有独立的 ipsec0 网络接口**。xfrm 的解密结果直接进入内核 netfilter，tcpdump `-i any` 可以看到，`-i ipsec0` 找不到接口。

**Fix**: 不传 `--interface`，extractor 默认 `any`（代码中 `default="any"`）。

**Prevention**: `config_vpn_ecs.yaml` 里的 `vpn_interface: ipsec0` 字段**从未被代码读取**（`ExtractorApp.__init__` 只读命令行参数，忽略 config 里的 `vpn_interface`）。不要把 `vpn_interface` 当作有效配置使用。

### Common Mistake: 改 `app.py` 的路由无效，真正的路由在 `core.py`

**Symptom**: 修改 `remote/relay/app.py` 的 `index()` 路由后，ECS 上的行为没有变化。

**Cause**: `main.py` 启动的是 `from core import RelayApp`，`RelayApp` 在 `core.py` 里定义，有自己的 `self._cfg`。`app.py` 的模块级 `_cfg = {}` 是孤立的占位符，没有被 `main.py` 注入，也没有被实际路由使用。

**Fix**: 修改路由必须改 `remote/relay/core.py` 的 `_register_routes()` 方法，不是 `app.py`。

```python
# core.py _register_routes() — Correct 修改位置
@self.app.get("/")
async def index(token: str = Query(default="")):
    if not token:
        api_token = self._cfg.get("api_token", "")
        if api_token:
            return RedirectResponse(url=f"/?token={api_token}")
    return HTMLResponse(content=self._build_hand_display_page())
```

**Prevention**: 任何 relay 路由改动都在 `remote/relay/core.py` 的 `RelayApp._register_routes()` 里做。`app.py` 已废弃（被 `core.py` 的 RelayApp 替代），不要再往里加路由。

### 自动 token redirect（2026-06-13 新增）

访问 `http://ECS_IP:<port>/`（无 token 参数）→ 307 重定向到 `/?token=<config.api_token>`，浏览器自动跟随，前端 JS 从 URL 读取 token 填入轮询请求，不再需要手动填写。

实现在 `core.py` 的 `index()` 路由（见上方代码），需要在 imports 里加 `RedirectResponse`：

```python
from fastapi.responses import HTMLResponse, RedirectResponse
```

三个模式各自的自动跳转 URL：
- `:8000/` → `/?token=acec67bfa9e518b5906d3e6a`（热点）
- `:8001/` → `/?token=8f2e7c91b4d53a6f10e9c827`（VPN）
- `:8002/` → `/?token=d4a8e1f29c6b7305e8d1f264`（无配置）

---

## 14. 断线窗口双连突破（2026-06-13 重大发现）

### 结论

**Phase B（云端双连）并非死路。** 之前的测试结论"手机在线时 cloud_player 被踢"仅在"手机 TCP 连接仍存活时主动双连"场景成立。当手机 TCP 连接因**异常中断**（非主动断开）触发服务端进入"等待重连 grace period"时，cloud_player 在该窗口内连入会被服务端识别为"玩家重连"，进而建立持久双连。

### 实测现象（2026-06-13 用户真机）

- 手机连接朋友路由器热点（**PC 不在流量路径**）
- **IKEv2 VPN 未开启**
- 网络自然抖动 → 手机游戏短暂卡顿/掉线 → 自动重连
- 重连后：cloud_player（noconfig 模式）**持续收到 0x2bc0 手牌帧，整局游戏有效**
- 手机全程正常打牌，无感知

### 机制推断

```
T0: 手机正常在线（TCP连接A → 游服）
T1: 网络抖动 → TCP连接A RST / timeout → 游服进入"等待重连 grace period"
T2: cloud_player 自动重连循环（on_disconnect→2s→retry）恰好落在窗口内
    服务端：判定为"玩家断线重连" → flag=0 ✅ → 发送当前游戏状态（含0x2bc0手牌）
T3: 手机也重连成功
    服务端：允许双连共存（两条连接均存活）
T∞: cloud_player 持续接收全部游戏帧，手机正常打牌
```

### 关键区分

| 场景 | 服务端行为 |
|---|---|
| 手机 TCP 在线，cloud_player 主动连入 | 识别为"非法双连" → 踢 cloud_player（2~3s）|
| 手机 TCP **异常中断**后，cloud_player 在 grace 窗口连入 | 识别为"玩家重连" → 放行 → **双连持久共存** |

### 如何工程化触发

**方案A（手动，任意网络）：**
用户进入牌局后，手机 WiFi 关闭 2~3s 再开启（模拟网络抖动）。
cloud_player 持续自动重连循环，会在窗口内自动连入。
此后整局游戏 cloud_player 持续读牌，无需任何干预。

**方案B（自动，手机在 PC 热点时）：**
PC 通过 Npcap 嗅探到手机→游服的 TCP 四元组，向游服发送伪造 TCP RST 包，
主动触发服务端的 grace period，cloud_player 立即连入。
用户点"开始读牌"按钮即可，全自动，手机无感知（游戏仅短暂卡约 1~2s）。

### 待验证

- [ ] grace period 的时间长度（估计 5~30s，需实测）
- [ ] 方案A 的可靠性（每次抖动后 cloud_player 都能成功进入？）
- [ ] 方案B 的 RST 注入实现（scapy sendp 或 WinDivert 伪包）
- [ ] 断线窗口共存后，下一局开始时双连是否自动延续

### SRSPlayerClient continuous 模式（2026-06-14 实现）

双连机制已集成进 `SRSPlayerClient`，通过 `continuous=True` 启用无限重连循环。

#### 签名

```python
# remote/cloud_player.py
class SRSPlayerClient:
    RETRY_DELAY_SECONDS = 2   # 被踢后等待时间

    def __init__(
        self,
        srs_sessionid: str,
        ...
        continuous: bool = False,   # ← 新增
        on_state_update: Callable | None = None,
        on_connected: Callable | None = None,
        on_disconnected: Callable | None = None,
    ): ...
```

#### continuous=False（默认，向后兼容）

保留原有 2 次尝试逻辑（`_run_legacy`）：
- 首次连接
- 若收到游戏帧后断线 → 等 8s → 再尝试一次
- 否则退出

适合 systemd `Restart=on-failure` 模式，由 OS 层面重启。

#### continuous=True（双连自动模式）

`_run_continuous` 无限循环：

```python
while not _stop_requested:
    _connect_once()   # 握手 + 接收帧直到断线
    if _stop_requested: break
    _sleep(RETRY_DELAY_SECONDS)   # 2s 可中断
```

适合：
- relay 内联启动（非 Linux / ECS 无 systemd）
- 双连场景：持续重试直到落在 grace period 窗口内

#### relay 内联启动路径

`/api/start-player` 在 systemd 不可用时自动 fallback 到内联模式：

```
POST /api/start-player  body: {"api_token": "...", "continuous": true}
  → 尝试 systemctl start mahjong-cloud-player
  → 失败（非 Linux / ECS）→ 读 data/cloud_credentials.json
    → SRSPlayerClient(srs_sessionid=..., continuous=True).start()
    → 存入 self._player_client

POST /api/stop-player
  → _stop_inline_player()  # client.stop() + _player_client = None
  → 也尝试 systemctl stop（非致命）

GET /api/player-status?token=...
  → 检查 _player_client._thread.is_alive()
  → 返回 {"active": true/false, "status": "active"/"inactive", "mode": "inline"/"systemd"/"none"}
```

**凭证格式**（`data/cloud_credentials.json`）：

```json
{
  "srs_sessionid": "<hex32>",   // 必须
  "userid": "newpt1084306678"   // 可选，缺省用默认值
}
```

#### 注意事项

- `continuous=False` 行为**完全不变**，现有 systemd 部署无需改动
- `_player_client` 引用在 relay 重启时丢失，不持久化（由 systemd/用户重启补
- 新上传凭证（`/api/creds`）会自动调 `_stop_inline_player()` 停旧连接

## 15. PC 热点 RST 注入自动化（2026-06-14 实现）

### 背景与动机

2026-06-14 实测验证：朋友的软路由热点通过脚本（捕凭证 + TCP RST 注入）实现了
"进游戏自动卡一下 → 云端持续读牌"的完整自动化，手机无需安装任何东西，
用户无需手动操作（不需要手动关/开 WiFi）。

本节记录复现该效果的 PC Windows 热点实现方案。

---

### 完整自动化链路

```
用户：手机连 PC 热点 → 打开游戏 → 运行 grab_credentials.bat

PC 端（capture_credentials.py）：
  1. Npcap 捕包（port 7777）
  2. 捕到 SRS 握手 → 提取 sessionid/handshake_blob/auth_token_12b
  3. POST /api/creds → ECS（保存凭证 + 自动启动 continuous player）
  4. rst_injector.inject_rst(phone_ip, phone_port, phone_seq)
     → Scapy sendp(Ether()/IP(src=phone_ip)/TCP(flags="R", seq=phone_seq))
     → 游服识别为手机异常断线 → grace period 开始

ECS 端（SRSPlayerClient continuous=True）：
  5. 在 grace period 内连入 → flag=0 → 持久双连建立

手机端：
  6. 游戏自动重连（"卡了一下"，约 1~2s）
  7. 游服允许双连共存，手机正常打牌

结果：云端网页展示实时手牌，无需任何额外操作
```

---

### 关键文件与职责

| 文件 | 职责 |
|---|---|
| `remote/extractor/capture.py` | `NpcapCaptureAdapter` 捕包 + 追踪 TCP 四元组 |
| `remote/extractor/rst_injector.py` | 新文件：Scapy 伪造 RST 并发送 |
| `remote/capture_credentials.py` | 捕凭证后调 RST 注入；移除了旧的手动 trigger |
| `remote/relay/core.py` | `/api/creds` 接收凭证后自动启动 continuous player |

---

### API 契约变更：`/api/creds`（cloud 模式）

**变更前**：只保存凭证，返回"请手动点 Start Monitor"。
**变更后**：保存凭证后自动启动 `SRSPlayerClient(continuous=True)`。

```
POST /api/creds
Body: {
  "api_token":       str,         // 必须
  "srs_sessionid":   str (hex32), // 必须
  "userid":          str,         // 可选，缺省 "newpt1084306678"
  "handshake_blob":  str (hex),   // 可选
  "auth_token_12b":  str (hex)    // 可选
}

成功响应:
{
  "status": "ok",
  "message": "Credentials saved and monitor started. Switch phone WiFi to own network to trigger dual-connect."
}

副作用（按顺序）:
  1. 写 data/cloud_credentials.json
  2. _stop_inline_player()（停旧连接）
  3. systemctl stop mahjong-cloud-player（非致命）
  4. _start_inline_player_with_creds(sessionid, userid)
     → 若 inline 失败 + Linux：systemctl start mahjong-cloud-player
```

**注意**：`/api/creds` 调用后不再需要额外调 `/api/start-player`。
`capture_credentials.py` 中已移除 Phase 1 结束时的立即 trigger，Phase 2（RespJoinTable 检测）仍保留。

---

### TCP 四元组追踪接口

```python
# remote/extractor/capture.py

class NpcapCaptureAdapter:
    _tcp_state: dict | None  # 追踪最新手机→游服包

    def get_tcp_state(self) -> dict | None:
        """返回最新手机→游服方向的 TCP 状态。
        返回格式: {"phone_ip": str, "phone_port": int, "phone_seq": int}
        手机未发包时返回 None。
        """

class TcpdumpCaptureAdapter:
    def get_tcp_state(self) -> None:  # Linux 不支持 RST 注入，直接返回 None
        return None
```

**更新条件**：每收到 `dst_ip == "47.96.0.227" and dst_port == 7777` 的包时更新。

---

### RST 注入接口

```python
# remote/extractor/rst_injector.py

def inject_rst(
    phone_ip: str,
    phone_port: int,
    phone_seq: int,
    server_ip: str = "47.96.0.227",
    server_port: int = 7777,
    iface=None,          # scapy NetworkInterface；None 时自动调 find_hotspot_iface()
) -> bool:
    """
    向游服发送伪造 RST（src=hand机IP:port），触发服务端 grace period。

    返回: True 成功，False 失败（Scapy 未安装 / 权限不足 / 接口找不到）

    实现细节:
    - scapy import 延迟在函数内（避免无 Npcap 环境 ImportError）
    - 包结构: Ether()/IP(src=phone_ip, dst=server_ip)/TCP(sport=phone_port, dport=server_port, flags="R", seq=phone_seq)
    - sendp(pkt, iface=iface, verbose=False)
    - 需要管理员权限（grab_credentials.bat 已 UAC 提权）
    """
```

**seq 选取规则**：使用捕到的最新手机→游服 TCP seq（即服务端 ack 的值），确保在服务端接收窗口内。

---

### 错误矩阵

| 条件 | 行为 |
|---|---|
| Scapy 未安装 / ImportError | inject_rst 返回 False，打印 warning；capture_credentials 打印"请手动切换WiFi" |
| get_tcp_state() 返回 None（手机未发包） | _inject_rst_if_possible 返回 False，打印"请手动切换WiFi" |
| find_hotspot_iface() 返回 None（未检测到热点网卡） | inject_rst 返回 False，打印 warning |
| 发包失败（权限/Npcap 错误） | inject_rst 捕 Exception，返回 False，log error |
| /api/creds inline 启动失败（ImportError） | Linux 下尝试 systemctl start；Windows 下返回 ok（启动失败不影响凭证保存） |

---

### 使用约束

- RST 注入**仅在 Windows 热点环境**有效（Npcap 必须已安装）
- **必须管理员权限**（bat 已包含 UAC 提权）
- RST 注入后约 1~2s 游戏卡顿，属正常现象
- grace period 时长估计 10~30s（待实测）；ECS continuous player 2s 重试间隔通常足够
- Phase 2（RespJoinTable 检测 → `/api/start-player`）仍保留，用于下一局自动重触发

---

## 13. 热点 / VPN 模式独立开发约定

热点模式和 VPN 模式均已真机验证通过（热点 2026-06-12，VPN 2026-06-13）。后续修改热点模式时，只需关注以下文件：

| 文件 | 作用 | 改动频率 |
|------|------|----------|
| `remote/relay/main.py` | relay 入口 + `--mode hotspot` | 低 |
| `remote/relay/core.py` | RelayApp 路由 + spectator 管理 | 中（首页、推送逻辑） |
| `remote/relay/config_hotspot.yaml` | 热点模式配置 | 低（凭证更新时改） |
| `remote/relay/state_store.py` | StateStore 数据管理 | 低 |
| `remote/relay/static/index.html` | 手牌展示页 | 中（UI 调整） |
| `remote/extractor/main.py` | extractor 入口 | 低 |
| `remote/extractor/capture.py` | 网卡检测 + NpcapCapture 适配 | 低 |
| `remote/extractor/uploader.py` | HTTP 推送客户端 | 低 |
| `remote/extractor/config.yaml` | extractor 配置（relay_url + api_token） | 低 |
| `5_extractor_hotspot.bat` | 本地一键启动 extractor | 低 |
| `1_relay_hotspot.bat` | 本地一键启动 relay | 低 |
| `hotspot_one_click.bat` | 热点一键: relay + extractor | 低 |

> **约定**：修改热点模式时，不需要考虑 VPN/无配置模式的代码。
> 三模式在 `core.py` 中通过 `self._mode` 完全隔离，各自独立 StateStore。
> 热点模式 `spectator_url` 为空，不启动 spectator 子进程。

### 验证链路（每次修改后必做）

```bash
# 1. 本地单元测试
python test_remote.py           # 13/13 必须全 pass

# 2. 本地 E2E 临时测试
python e2e_test.py --temp       # 3/3 必须全 pass

# 3. ECS 部署验证
scp 修改的文件 root@8.136.37.136:/opt/mahjong-remote/对应路径/
ssh root@8.136.37.136 "systemctl restart mahjong-relay-hotspot"
sleep 2
curl -s http://8.136.37.136:8000/mode    # {"mode":"hotspot"}
curl -s http://8.136.37.136:8000/ | head -5  # 手牌展示页 HTML

# 4. 实机验证
# 手机连热点 → 双击 5_extractor_hotspot.bat → 手机进游戏打牌
# 看 http://8.136.37.136:8000/ 是否有手牌数据
```

---

## 16. 代码同步流向铁律（2026-06-17 立规）

### 16.1 唯一允许的流向

```
本地修改 → git commit → restart_hotspot_mitm_and_ecs.bat → 服务器
                                                              ↑
                                                              单向
```

**禁止**：直接登录服务器编辑代码、直接 scp/sftp 修文件、用 ssh 跑 sed/echo 改代码。

### 16.2 唯一允许的反向操作

服务器上**只能读、不能写**。如果发现服务器代码意外比本地新（被人手改、被脚本同步覆盖、被 codex 直接动），处理流程**必须**是：

```bash
# 1. 把服务器代码拉回本地（覆盖本地工作目录）
scp root@8.136.37.136:/opt/mahjong-remote/<差异文件> <本地对应路径>

# 2. 本地 git diff 看清楚到底差了什么
git diff -- <差异文件>

# 3. 本地审完，commit 进 git
git add <差异文件>
git commit -m "sync: pull <文件> back from server"

# 4. 之后再走正常 restart_hotspot_mitm_and_ecs.bat 重新部署
```

**严禁**：在服务器上当场 patch、跑修改命令；服务器永远只能是"本地 git 的镜像"，发现差异就立刻把服务器版本拉回本地走 git。

### 16.3 这条规矩为什么必须存在

历史教训（2026-06-17，整整 4 小时排查）：

| 时间 | 事件 |
|------|------|
| 6/16 14:07 | 服务器上 `handshake.py::parse_player_data` 被手改成正确版本（1B 长度前缀），LOLLAPALOOZA 上报开始正常 |
| 6/16 | 这个手改**没有提交 git**，本地仓库依然是 2B `<H` 的 bug 版本 |
| 6/17 7:53 | codex 修 `crypto.py::reset_cfb`，部署时（可能是 sftp 同步整个 `remote/srs_spectator/` 目录）把仓库里 2B bug 版本覆盖回服务器 |
| 6/17 8:07 | 用户跑 `restart_hotspot_mitm_and_ecs.bat`，再一次把本地代码（bug 版本）推到服务器 |
| 6/17 上午 | LOLLAPALOOZA 永久消失，admin 上只剩 default lobby 兜底用户 |
| 6/17 10:00–14:00 | 反复手工 ssh 改服务器、scp 来回拉、systemd 重启 70+ 次，越改越乱 |

**根因不是 codex 写错了代码，是服务器上长期存在"未入库的正确版本"**，任何一次部署都会把它覆盖掉。如果当初遵守"服务器只读，发现差异先 pull 回来 git commit"，6/16 14:07 那次手改就会进入 git，6/17 的部署不会回滚它。

### 16.4 `restart_hotspot_mitm_and_ecs.bat` 的覆盖范围（必须知道）

脚本 (`scripts/restart_hotspot_mitm_and_ecs.py:181-185`) 打包 tar 时**只包含**：

- `remote/noconfig/hijack/` （整个目录）
- `remote/relay/` （整个目录）
- `apk/game_base.apk`

**不包含**：`remote/noconfig/app.py`、`remote/noconfig/user_store.py`、`remote/srs_spectator/`、`remote/extractor/`、`remote/vpn/`、`remote/hotspot/` 等。

→ 改这些目录里的文件时，**单跑 bat 脚本不会同步到服务器**，必须显式 scp + systemctl restart。

### 16.5 部署前自检脚本

任何部署到服务器前，先跑一次 md5 对比，确认本地与服务器无差异（差异 = 服务器有未入库改动，**必须先拉回 git**）：

```bash
# 单文件对比
LOCAL=$(md5sum remote/noconfig/hijack/tcp_proxy.py | awk '{print $1}')
REMOTE=$(ssh root@8.136.37.136 'md5sum /opt/mahjong-remote/remote/noconfig/hijack/tcp_proxy.py' | awk '{print $1}')
[ "$LOCAL" = "$REMOTE" ] && echo "OK in sync" || echo "DIFF! pull server back first"

# 整个 noconfig 目录批量对比
for f in $(cd remote/noconfig && find . -name '*.py'); do
  L=$(md5sum "remote/noconfig/$f" 2>/dev/null | awk '{print $1}')
  R=$(ssh root@8.136.37.136 "md5sum /opt/mahjong-remote/remote/noconfig/$f 2>/dev/null" | awk '{print $1}')
  [ "$L" != "$R" ] && echo "DIFF: $f (local=$L  remote=$R)"
done
```

### 16.6 `restart_hotspot_mitm_and_ecs.bat` 的真实行为（2026-06-19 校验）

仓库根目录的 `restart_hotspot_mitm_and_ecs.bat` **不是**直接调 PowerShell，
而是包装 `scripts/restart_hotspot_mitm_and_ecs.py`：

```bat
@echo off
setlocal
python "%~dp0scripts\restart_hotspot_mitm_and_ecs.py" %*
...
```

这意味着后续日常恢复时，**双击 bat 即可**，它会按下面顺序处理：

1. 先检查本机热点 IP `192.168.137.1` 是否存在；不存在则直接失败退出
2. 杀掉本机旧的 `run_hijack.py` / `setup_mitm.py` Python 进程
3. 重新启动本机热点 MITM（443 + `192.168.137.1:53` + `DnsDivert`）
4. 本机自检 `https://127.0.0.1/hotfix_update ...`
5. 打包并上传：
   - `remote/noconfig/`
   - `remote/relay/`
   - `apk/game_base.apk`
6. 远端重启：
   - `mahjong-mitm-hotupdate`
   - `mahjong-tcp-proxy`
   - `mahjong-relay-noconfig`
7. 远端再做一次 `REMOTE_OK` 热更链自检

**结论**：对这次“热点热更 + noconfig ECS”链路来说，后续你只跑
`restart_hotspot_mitm_and_ecs.bat` 就够了，它会把这条链上该杀的本地 MITM 进程、
该重启的 ECS 三个 systemd 服务都重启掉。

**边界也必须记住**：

- 它不是“清空整台机器全部资源”；只处理匹配 `run_hijack.py/setup_mitm.py` 的本地 Python 进程
- 它不会重启或同步 `remote/srs_spectator/`、`remote/extractor/`、`remote/vpn/` 等未打包目录
- 它要求热点先开起来；没开热点时会在第 1 步就停住

### 16.7 2026-06-19 本次 bug 根因：热点热更偶发卡死不是 ECS 挂，而是本机回源被代理污染

这次“重进游戏后热变更偶尔卡住/不触发”的根因，最终确认属于 **E. Implicit Assumption**：
`setup_mitm.py::_origin_fetch()` 默认相信主机环境是“直连公网”的，但实际 Windows 热点机上
常驻了系统代理/环境代理，导致回源请求偶尔被带到本地代理端口。

**现场证据**：

- 本地日志曾出现 `ProxyError`
- 目标代理是 `127.0.0.1:7897`
- 随后同一批请求出现 `origin failed status=502/404`
- 这会让 `version.manifest / project.manifest / CDN 文件` 的透明回源不完整，从而表现成
  “热更偶发卡住”、“本地校验资源卡住”或“这次没触发热更”

**容易误判的点**：

- ECS 服务其实是正常的，问题不在远端服务是否 `active`
- 热点热更是否触发，前提是手机真的走了本机热点 MITM + `DnsDivert`
- 只看 ECS `systemctl active` 会产生假安全感；真正决定热更是否稳定的是
  本机 443/53/WinDivert 是否起来，以及回源是否被代理污染

**最终修复**：

- 在 `remote/noconfig/hijack/setup_mitm.py::_origin_fetch()` 中改为：
  `requests.Session().trust_env = False`
- 强制热点 MITM 回源忽略系统/环境代理，永远直连真实 CDN

**防复发规则**：

- 任何“本机 MITM / 回源 / 透明代理”代码，默认都要假设宿主机可能挂着代理
- 这类回源请求必须显式禁用 `HTTP_PROXY/HTTPS_PROXY`
- 判断“热更链是否恢复”时，必须同时看：
  - 本机 `hotspot_mitm_bg.err.log`
  - 本机 `443` / `192.168.137.1:53`
  - ECS `mahjong-mitm-hotupdate` / `mahjong-tcp-proxy` / `mahjong-relay-noconfig`
  - 是否出现新的 `/hotfix_update -> version.manifest -> project.manifest` 连续日志

---

## 17. ECS 故障兜底（noconfig Path Y）

> **铁律**：noconfig 链路下发的客户端补丁必须让手机**在 ECS 整机宕机时仍能走真服玩所有玩法**（含金币局）。这是产品承诺，不是 nice-to-have。

### 17.1 默认下发形态（强制）

noconfig 设置期热更必须**双注入**——只下 NetConf.luac 不够：

| 文件 | 改写规则 |
|---|---|
| `NetConf.luac` | `LOCAL_TCP_LIST[5045]` **保留真服 47.96.101.155** + 追加 ECS；`LOCAL_TCP_LIST_50[5067/5167]` 改为 `[ECS_entry, 真服 entry]` 两项；**禁止注入 `LOCAL_TCP_LIST_50[5045]`**（让代码 fallthrough 到普通 random 路径） |
| `NetEngine.luac` | 注入全局 `XH._srsConnFailCount`、把 `getTcpConnectInfoByGroupId` 中 _50 分支 `return list[1]` 改成 `return list[(_failCount % #list) + 1]`、在所有 `addLinkStateScriptFunc` 回调里挂 LINK_STATE FAIL 自增 + 自重连 |

### 17.2 必须知道的客户端事实

`NetEngine.lua::getTcpConnectInfoByGroupId` 的 _50 分支硬编码 `return list[1]`，无 fallback、无 random、无重选。**只改 NetConf.luac 不动 NetEngine.luac 时，金币局兜底数学上做不到**——ECS 一挂，5067/5167 永久不可达。

### 17.3 故障兜底验证工具

| 杠杆 | 用途 |
|---|---|
| `stop_ecs_services.bat` | SSH 跑 `systemctl stop` 关 ECS 进程（不关机），用于验证 4G 用户回路真服 |
| `start_ecs_services.bat` | 配套 start，验证回归 ECS 抓牌 |

**仅关进程，不关机**——`stop` 完后端口立即 `connect refused`（不是 SYN 黑洞），客户端能立刻拿到 FAIL 触发轮询。

### 17.4 服务名（实际部署，2026-06-17 起）

bat / systemctl 命令**必须用以下实际部署单元名**，不要照抄 PRD 里的占位：

| 服务 | 用途 |
|---|---|
| `mahjong-mitm-hotupdate` | 443 + DNS 热更 MITM |
| `mahjong-tcp-proxy` | 大厅 + 金币游服 SRS 代理 |
| `mahjong-relay-noconfig` | :8002 spectator relay（**不是** `noconfig-multi`） |
| `mjx-vpn` | VPN extractor |

---

## 18. 客户端 Lua Patch 改动纪律

> **触发**：任何 patch 模块改写 APK 内 `*.luac`（NetConf / NetEngine / 其它资源）。

### 18.1 幂等（强制）

再次 patch 已 patched 的 luac 必须是 **noop**（0 替换、0 注入）。用 sentinel（独有变量名 / 注入语句字面量）检测注入痕迹后 early-return；**禁止盲目 sub**——双重注入会把客户端代码改成无效 Lua。

### 18.2 XXTEA inc 标记（不要新写）

| 文件 | inc 标记 | 走哪条 |
|---|---|---|
| `NetConf.luac` | `inc=False`（密文长 == 明文长） | `xxtea_decrypt/encrypt` |
| `NetEngine.luac` 及其它 cocos `.luac` | `inc=True`（明文末尾带 4 字节长度尾） | `unwrap_luac/wrap_luac` |

**统一从 `remote/noconfig/hijack/netconf_patch.py` 复用 `unwrap_luac/wrap_luac/SIGN/KEY`**——不要在新模块里手写 XXTEA。

### 18.3 定位用结构匹配，不用行号

游戏官方热更覆盖时行号会变。改写定位**必须**用：

- 正则匹配函数名 / 表名（`LOCAL_TCP_LIST_50\s*=\s*\{`）
- 花括号配平截块（参考 `_find_real_block_span`）
- 字面量唯一性判断（必含字符串 `must_contain`）

**禁止**：`source.split("\n")[N]`、`re.sub` 不限范围在全文乱替（NetConf.lua 里 `47.96.101.155` 出现在多个区，会污染非台州的区）。

### 18.4 LOCAL_TCP_LIST_50 改写约束

任何对 `LOCAL_TCP_LIST_50[*]` 的注入 / 改写**必须保留至少一项真服 entry** 在列表里。违者 = ECS 整机宕机时该玩法永久不可达 = 违反 §17 产品承诺。Code-spec 检查表：

- [ ] 改后的 list `#list >= 2`
- [ ] 文本含原真服 IP / hostname 字符串
- [ ] 不要用 `_inject_srs50_block(5045)` 风格的「钉死 list[1]」

### 18.5 必备 selftest CLI（强制）

每个 patch 模块必须暴露 `--selftest` 入口，覆盖：

1. 解密 → 改写 → 加密 → 再解密的 XXTEA 往返
2. 改后明文断言（含/不含若干字面量）
3. 二次 patch 幂等（0 改动）

### 18.6 Wrong vs Correct

**Wrong**——钉死单点（ECS 一挂金币局必死）：

```lua
[5067] = { {id=0, ip="8.136.37.136", port=5767} }
```

**Correct**——ECS 在前抓凭证、真服在后做兜底：

```lua
[5067] = {
    {id=0, ip="8.136.37.136", port=5767},
    {id=0, ip="srs-zj.tt2kj.com", port=7777},
}
```

配合 NetEngine 轮询补丁，ECS 死 → `_srsConnFailCount++` → 下次连真服。

