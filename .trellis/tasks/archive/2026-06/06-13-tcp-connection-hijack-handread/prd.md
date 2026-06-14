# TCP连接状态接管：绕过单连接限制的伪装读取手牌

## Goal

**用户目标**："只连一次热点获取凭证，之后手机离开热点、任意网络，云端仍能伪装成手机持续读取手牌数据。"

**核心假设**：服务端"踢连接"基于TCP连接状态（心跳超时），而非立即生效。如果手机**主动断开**TCP连接，云端在**极短时间内**用相同sessionid重连，服务端可能误判为"同一连接恢复"而非"新连接"，从而允许云端接管。

---

## 核心假设（待实测验证）

**假设A：服务端区分"主动断开"和"被动踢线"**
- 手机主动断开（如飞行模式、切换网络）→ 服务端标记为"离线"，sessionid保留一段时间
- 云端重连 → 服务端认为是"同一设备恢复连接"
- 云端被接受，手机不受影响

**假设B：存在接管时间窗口（<1秒）**
- 手机断网 → 服务端检测到超时（120s idle timeout）前，sessionid仍有效
- 云端在窗口期内重连 → 服务端接受
- 窗口期外重连 → 服务端视为新连接，踢掉手机

**假设C：服务端不校验IP变化**
- 手机从热点IP变为4G IP，云端从ECS IP连接
- 服务端只校验sessionid，不校验IP连续性

**假设D（新增）：不同 usertype 不触发单连接限制**
- Lua 源码显示 USERTYPE 枚举包含多种登录方式（0=USERID, 1=PTID, 5=IDENTIFY, 7=SESSION, 9=PHONENUM）
- 当前使用 usertype=7 (SESSION)，已验证会踢手机
- usertype=5 (IDENTIFY) 使用硬件码登录，可能不触发单连接限制
- 如果服务端按 (userid, usertype) 组合管理连接，则不同 usertype 可共存

---

## 方案架构

### 方案一：TCP连接状态接管（原方案）

```
Phase A — 凭证提取（连一次热点，约1分钟）:
  手机连 PC 热点
    → ECS 被动嗅 7777 + SRS 握手包
    → 提取 srs_sessionid（SRS 握手中明文或可解密）
    → 提取 handshake_blob + auth_token_12b
    → 存入云端 credential store

Phase B — 连接接管（断开热点，任意网络）:
  手机主动断开游戏连接（飞行模式/切换网络）
    → 服务端检测到连接断开
    → 云端立即用存储的 srs_sessionid 连接游戏服务器
    → SRS 握手 → PlayerConnect（usertype=7, flag目标=0）
    → 服务端接受连接，认为是"同一设备恢复"
    → 云端接收 0x2bc0 手牌帧
    → stable/MJProtocol + PacketStateTracker 解码
    → BattleState → 网页展示

Phase C — 手机重连（不影响云端）:
  手机重新连接网络（4G/WiFi）
    → 游戏App自动重连
    → 服务端踢掉云端连接（单连接限制生效）
    → 云端检测到被踢 → 等待下次接管窗口
```

### 方案二：usertype=5 (IDENTIFY) 绕过（新发现）

```
Phase A — 凭证提取（连一次热点）:
  手机连 PC 热点
    → 提取 identify（硬件码，从 PlayerConnect 帧中）
    → 提取 userid（账号）
    → 存入云端

Phase B — 云端双连（任意网络）:
  云端用 identify + userid 以 usertype=5 连接游戏服务器
    → PlayerConnect（usertype=5, pwd=identify）
    → flag=0（假设服务端接受硬件码登录）
    → 云端接收 0x2bc0 手牌帧
    → 手机同时在线，不受影响
```

**方案二优势**：
- 不需要手机断网
- 云端和手机同时在线
- 服务端可能不视为"同一玩家"，不触发单连接限制
    → 游戏App自动重连
    → 服务端踢掉云端连接（单连接限制生效）
    → 云端检测到被踢 → 等待下次接管窗口
```

---

## 里程碑

| # | 里程碑 | 交付 | 验收 |
|---|--------|------|------|
| M1 | 凭证提取自动化 | 热点连接时自动抓 srs_sessionid + handshake_blob + auth_token_12b 存云端 | 控制台打印 `sessionid=xxx` |
| M2 | 手机主动断网测试 | 手机开飞行模式，观察服务端多久释放sessionid | 日志记录断网→服务端释放时间 |
| M3 | 云端接管窗口测试 | 手机断网后X秒内云端重连，观察flag | 找到最大窗口期（秒） |
| M4 | 云端接收手牌帧 | 接管成功后收到0x2bc0帧并解码 | 打印手牌 |
| M5 | 手机重连影响测试 | 手机重连后是否踢云端 | 记录踢线时间 |
| M6 | 完整流程验证 | 热点→断网→接管→手机重连→云端被踢→循环 | 端到端流程跑通 |
| **M7** | **usertype=5 测试** | **测试 usertype=5 (IDENTIFY) 是否能绕过单连接限制** | **flag=0 且手机不被踢** |
| **M8** | **usertype=5 手牌接收** | **usertype=5 连接成功后接收0x2bc0帧** | **打印手牌** |

---

## 约束

- **无 VPN**：Phase B 不依赖任何 VPN
- **原装 APK**：手机侧零修改
- **主动断网代价**：需要手动/自动让手机断网（可接受）
- **接管窗口**：可能只有几秒到几十秒（待实测）

---

## 关键技术点

### 方案一：TCP连接状态接管

**核心问题**：服务端如何检测"连接断开"？

可能机制：
1. **TCP RST/FIN**：手机主动断开时发送RST/FIN，服务端立即知道
2. **心跳超时**：120s无数据则服务端主动关闭
3. **sessionid状态表**：服务端维护sessionid→连接映射，新连接到达时踢旧连接

**测试策略**：
1. 先用PC Frida server手动测试：手机在牌局中，PC同时以相同账号PlayerConnect
2. 观察手机是否掉线
3. 如果踢线：测试不同usertype或连接时序优化

### 方案二：usertype=5 (IDENTIFY) 绕过

**核心发现**：SRSProtocol.lua 中 USERTYPE 枚举：
```lua
USERTYPE = {
    USERID = 0,           -- 平台帐号
    PTID = 1,             -- PT帐号
    NMY = 2,
    GLOBAL_ANONYMITY = 3,  -- 全局匿名帐号
    IDENTIFY = 5,          -- 硬件码登录(移动设备)
    DEVELOPER = 6,
    SESSION = 7,           -- 当前使用的
    REGISTER = 8,
    PHONENUM = 9,          -- 手机加密码登录
    ANONYMITY = 255        -- 匿名
}
```

**关键差异**：
- `usertype=7` (SESSION): pwd = 16B sessionid，已验证会踢手机
- `usertype=5` (IDENTIFY): pwd = identify（硬件码），可能不触发单连接限制

**PlayerConnect 格式差异**（usertype≠7 时）：
```lua
if self.usertype ~= self.USERTYPE.SESSION then
    -- 非 SESSION 模式：pwd 是变长字符串
    bos:writeString(self.pwd)
else
    -- SESSION 模式：pwd 是定长16B
    bos:write(self.pwd, 16)
end
```

**测试脚本**：`scripts/test_usertype_bypass.py`

**测试方法**：
```bash
# 测试 usertype=5 (IDENTIFY)
python scripts/test_usertype_bypass.py --sessionid <hex32> --usertype 5

# 测试所有 usertype
python scripts/test_usertype_bypass.py --sessionid <hex32> --all
```

### 手机断网时机

**触发方式**：
- 手动：飞行模式开关
- 自动：脚本控制WiFi/4G切换
- 定时：每局结束后自动断网接管

---

## Open Questions

1. **服务端释放sessionid的时间**：手机断网后，服务端多久才认为sessionid可用？
2. **接管窗口大小**：从手机断网到云端成功连接，最大允许延迟？
3. **手机重连行为**：手机自动重连是否会立即踢云端？
4. **sessionid有效期**：接管窗口内sessionid是否仍然有效？

---

## 已有可复用资产

| 资产 | 位置 | 用途 |
|------|------|------|
| SRS握手破解 | `srs-key-derivation.md`, `srs-fully-solved.md` | Phase B认证 |
| stable解码器 | `stable/protocol.py`, `stable/tracker.py` | 解码手牌帧 |
| relay+网页 | `remote/relay/` | 网页展示 |
| SRS客户端 | `remote/srs_spectator/client.py` | 云端连接游戏服务器 |
| PlayerConnect构建 | `remote/srs_spectator/player_connect.py` | 构建连接请求 |

---

## Out of Scope

- 旁观模式（死路，协议层无手牌）
- Frida Siphon / APK修改
- VPN方案
- 热点实时解码（已有方案）

---

## 实测计划

### 测试1：服务端释放sessionid时间
```
1. 手机连热点，打开游戏，完成SRS握手
2. 记录当前sessionid
3. 手机开飞行模式（主动断开）
4. 每隔5秒用PC尝试用相同sessionid连接
5. 记录第一次flag=0的时间点
```

### 测试2：接管窗口大小
```
1. 手机断网
2. 等待X秒后云端连接（X=0,1,2,5,10,30,60,120）
3. 记录每个X对应的flag
4. 找到最大可接管窗口
```

### 测试3：手机重连影响
```
1. 云端成功接管
2. 手机关闭飞行模式，游戏自动重连
3. 观察多久后云端被踢
4. 记录踢线时间
```
