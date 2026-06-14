# PC 热点双连全自动化：复现软路由效果

## 目标

**完整复现朋友软路由的效果**：

1. 手机连 PC Windows 热点
2. 在手机上打开游戏
3. 运行 `grab_credentials.bat`
4. 游戏"卡一下"自动恢复（无需用户手动操作）
5. 云端持续读牌，网页展示手牌

## 已验证的机制（朋友软路由 2026-06-14 实测）

```
T0: 手机连上软路由热点，进游戏
T1: 软路由捕获 SRS 凭证（sessionid/handshake），上传到 ECS
T2: 软路由向游服注入伪造 TCP RST（src=手机IP:手机port）
    → 游服识别为"手机异常断线" → 进入 grace period
T3: ECS cloud_player（已预启动，continuous 模式）在窗口内连入
    → 游服识别为"玩家重连" → flag=0 → 建立持久双连
T4: 手机自动重连（游戏显示"卡了一下然后好了"）
    → 游服允许两条连接共存
T∞: ECS 持续收 0x2bc0 手牌帧，手机正常打牌，无感知
```

---

## 实现方案

### 改动 1：`remote/relay/core.py` — `/api/creds` 自动启动 player

**现状**：`/api/creds` 接收凭证后只保存，要求用户手动点"Start Monitor"。
**改后**：接收凭证后立即 `_start_inline_player_with_creds(sessionid, userid)`。

已添加 `_start_inline_player_with_creds` 辅助方法（见 relay/core.py L501-540）。
需修改 `/api/creds` 路由末尾（L250-260），调用该方法取代旧的 "click Start Monitor" 提示。

### 改动 2：`remote/extractor/capture.py` — 追踪 TCP 四元组

在捕包循环中，记录最新的手机→游服方向包的：
- `phone_ip`、`phone_port`（手机发出的源地址）
- `phone_seq`（手机当前发送 seq，即服务端 ack 的值）

通过已有 `PcapParser._parse_ip_tcp_static` 提取（已有 `src`, `dst`, `seq` 字段）。

暴露方法：`get_tcp_state() -> dict | None` 返回 `{phone_ip, phone_port, phone_seq}`。

### 改动 3：`remote/capture_credentials.py` — 凭证捕获后注入 RST

**现状**：`_save_and_enter_phase2()` 捕获凭证后，调 `/api/start-player`（现在由 `/api/creds` 自动处理）。
**改后**：
1. 移除独立的 `_trigger_cloud_player()` 立即调用（`/api/creds` 已自动启动 player）
2. 凭证上传成功后，调用 `rst_injector.inject_rst(capture_adapter)` 注入 RST

### 改动 4：`remote/extractor/rst_injector.py` — TCP RST 注入（新文件）

```python
# remote/extractor/rst_injector.py

def inject_rst(phone_ip: str, phone_port: int, phone_seq: int,
               server_ip: str = "47.96.0.227", server_port: int = 7777,
               iface=None) -> bool:
    """
    向游服发送伪造 RST 包（src=手机IP:port），触发服务端 grace period。

    实现：
    - scapy.sendp(Ether()/IP(src=phone_ip, dst=server_ip)/TCP(
          sport=phone_port, dport=server_port,
          flags='R', seq=phone_seq))
    - 通过热点网卡（ICS 网关接口）发出
    - 需要管理员权限（grab_credentials.bat 已 UAC 提权）

    返回 True 成功，False 失败（Scapy 未安装等）
    """
```

**技术细节**：
- RST seq 使用捕到的最新手机→游服 seq（服务端已 ack 的值，在其接收窗口内）
- 通过 `scapy.sendp()` 在热点网卡发出（二层发送，绕过系统路由）
- 网卡用 `find_hotspot_iface()` 查找（已在 capture.py 中实现）
- Scapy 已是 Npcap 的依赖，项目已安装

---

## 实现后的完整流程

```
用户运行 grab_credentials.bat（已 UAC 提权）
  ↓
capture_credentials.py 启动 Npcap 捕包
  ↓ 手机已在游戏中，数据流过热点
捕到 SRS 握手 → 提取 sessionid + handshake_blob
  ↓
POST /api/creds → ECS 保存凭证 + 自动启动 SRSPlayerClient(continuous=True)
  ↓
rst_injector.inject_rst(phone_ip, phone_port, phone_seq)
  → 向游服发送伪造 RST（src=手机IP）
  → 游服认为手机异常断线 → grace period 开始
  ↓
ECS cloud_player 在 grace period 内连入
  → flag=0 → 持久双连建立
  ↓
手机自动重连（游戏"卡了一下"）
  → 游服允许双连共存
  ↓
capture_credentials.py 打印：
  "[OK] 双连已建立，手牌已在云端。"
  "[Browser] http://ECS:8003/?token=..."
```

---

## 验收标准

- [ ] 运行 bat 后，无需任何手动操作，游戏自动"卡一下"恢复
- [ ] ECS 网页出现手牌（< 15s）
- [ ] 整局手牌持续更新
- [ ] 手机离开热点后云端继续读牌
- [ ] 手机正常打牌无感知（不报错、不断线提示）

## Out of Scope

- 自动重抓凭证（sessionid 过期后）—— 下一个任务
- Linux/OpenWrt 移植（先 Windows）
- 多账号

## Technical Notes

- RST 注入需管理员权限，bat 已有 UAC，无需额外处理
- `scapy` 已安装（Npcap 依赖），直接用 `from scapy.all import sendp, IP, TCP, Ether`
- 热点接口查找：`remote/extractor/capture.py::find_hotspot_iface()`（返回 scapy NetworkInterface）
- `PcapParser._parse_ip_tcp_static` 已提取 `src`, `dst`, `seq`，字段已可用
- 游服 IP：`47.96.0.227:7777`（`remote/cloud_player.py::_GAME_SERVER_HOST/PORT`）
- grace period 时长：估计 10~30s（§14 spec 待实测）
