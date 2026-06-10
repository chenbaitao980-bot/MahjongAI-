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

场景B（extractor 离线，如外出打牌）
  游戏机 → 网络 → 游戏服务器
                       ↑ relay 作为第二客户端
              relay/ GameClient
              主动 TCP 连接 → 接收游戏数据包
              PacketStateTracker 重建状态
              GET /state → 返回最新 snapshot
```

**模式切换**：`StateStore.PUSH_TIMEOUT = 60s`，超过此时间无 `/push` → 自动启动 GameClient。

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

### POST /push

```
Request body (JSON):
  snapshot:   dict  # PacketStateTracker.snapshot() 的输出
  api_token:  str

Response 200: {"status": "ok"}
Response 401: {"detail": "Invalid api_token"}
```

### GET /state

```
Query params:
  token: str  # 与 relay config.yaml 中的 api_token 一致

Response 200: <snapshot dict>  或  {"phase": "idle"}（未注册或无数据时）
Response 401: {"detail": "Unauthorized"}
```

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
```

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

```python
import platform

def create_capture(config):
    if platform.system() == 'Windows':
        return NpcapCaptureAdapter(config)
    else:
        return TcpdumpCaptureAdapter(config)
```

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

`TokenExtractor.feed()` 只读四个字段，用 `namedtuple` 即可模拟，无需真实 `ProtocolMessage`：

```python
FakeMsg = namedtuple("FakeMsg", ["msg_type", "direction", "raw_hex", "pay_len"])

# 构造 0x0001 握手包（19字节 payload）
HEADER = bytes(12)
payload = bytes(range(19))
msg = FakeMsg(
    msg_type=0x0001,
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
