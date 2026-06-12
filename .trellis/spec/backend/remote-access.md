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

### 隔离性保证

- 每个模式拥有独立的 `RelayApp` 实例 → 独立 `StateStore`、`FastAPI app`、配置
- api_token 各不相同 → 跨模式 token 自动被 401 拒绝
- 凭证持久化到各自配置文件 → 互不干扰
- `--all` 模式使用 `multiprocessing.Process` → 进程级隔离

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
