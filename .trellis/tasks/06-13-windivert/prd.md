# 断线窗口双连：可行性验证 + 正式集成

## Goal

验证"断线窗口双连"机制可重复触发，cloud_player 建立持久双连后整局持续读牌；验证通过后再集成到正式 noconfig 模式。

## 背景（重大发现 2026-06-13）

手机因网络抖动**异常中断** TCP 连接时，服务端进入 grace period。
cloud_player 在此窗口内连入，被识别为"玩家重连"，建立**持久双连**：
- 手机重连后两条连接共存，cloud_player 整局持续收 0x2bc0 手牌帧
- 手机换网络不影响 cloud_player（ECS IP 稳定，TCP 不断）
- 一次触发，整局有效

详见 `.trellis/spec/backend/remote-access.md` §14。

---

## 阶段一：独立测试脚本（MVP，先验证可行性）

### 目标

写一个独立的 Python 测试脚本，**不依赖任何现有 relay/noconfig 基础设施**，
直接验证：手动关/开 WiFi 后 cloud_player 能否建立持久双连并持续读到手牌。

### 脚本职责

```
scripts/test_dual_connect.py

1. 从 data/cloud_credentials.json 读取凭证
   （handshake_blob / auth_token_12b / srs_sessionid）

2. 启动持续重连循环：
   while not connected:
       connect() → 如果 2~3s 内被踢 → wait 2s → retry
       如果收到 0x2bc0 帧 → 打印手牌 → 标记"已建立双连"

3. 建立双连后：
   持续打印每一帧收到的手牌变化（摸牌/出牌）
   Ctrl-C 退出

4. 不推送到任何 relay，直接 print 到终端
```

### 触发方式（测试期间）

用户进入牌局后：
1. 运行 `python scripts/test_dual_connect.py`
2. 手机 WiFi 关 3s → 开
3. 观察脚本是否打印出手牌

### 验收标准（阶段一）

- [ ] 手动关/开 WiFi 3 次，至少 2 次成功建立双连
- [ ] 建立后打印出完整手牌（13/14 张），与手机屏幕一致
- [ ] 手机换网络后脚本继续打印手牌（不中断）
- [ ] 手机正常打牌，无断线提示

---

## 阶段二：集成到正式 noconfig 模式（验证通过后）

在阶段一确认可行后，将以下改动合并到正式代码：

### 改动点

**`remote/cloud_player.py` — `SRSPlayerClient._run()`**
- 当前：最多 2 次重连，然后退出（`Restart=no`）
- 改为：持续重连循环（`while not stop_requested`），直到成功建立双连
- 建立双连标志：收到 ≥1 帧 0x2bc0 后连接未被踢（存活 >10s）

**`remote/relay/core.py` — 网页**
- 添加"开始监控"按钮（当前已有 `/api/start-player`）
- 添加状态提示："等待触发（请手机关/开 WiFi）" / "已连接，正在读牌"

**无需改动：**
- `push_to_relay()` — 已有
- `PacketStateTracker` 解码链路 — 已有
- relay `/push` 接口 — 已有

### 阶段二验收标准

- [ ] 点"开始监控"→ 关/开手机 WiFi → 浏览器自动显示手牌（无需手动干预）
- [ ] 整局手牌持续更新
- [ ] 下一局开始时自动恢复（cloud_player 继续循环）

---

## 实现顺序

```
M1: 写 scripts/test_dual_connect.py（~100行）
M2: 手机实测验证 × 3次
M3: 结论写入 spec
M4: 若通过 → 改 cloud_player._run() + 网页按钮
```

## Technical Notes

- 凭证来源：`data/cloud_credentials.json`（`capture_credentials.py` 已抓好）
- 复用：`remote/cloud_player.py` 的 `SRSPlayerClient`（已有 decode→push 管道）
- 测试脚本不依赖 relay，直接 print 手牌验证
- grace period 时长待实测（估计 5~30s，关 WiFi 3s 应已足够）

## Out of Scope（本任务）

- WinDivert / TCP RST 注入（方案B，留后续）
- 热点旁路嗅探
- Android 辅助 app
