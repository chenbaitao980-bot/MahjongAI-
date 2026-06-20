# D22 验证：主号实时 7777 流非游戏帧是否泄漏对手手牌

- **Query**: 主号自己桌的实时 game 7777 流里，非 0x2BC0 帧（player_detail/player_info/unknown_0f/round_start 等名册/详情帧）局开始时是否一次性下发了对手 hand_raw（客户端预渲染缓存但 UI 不渲染）
- **Scope**: internal（离线只读 data/*.pcap，复用 stable/protocol.py 不改）
- **Date**: 2026-06-20
- **判定**: ❌ **D22 证伪**。H16（服务端 view filter）在主号自己的实时 7777 流里同样是 hard wall。

复现脚本（纯离线，零网络）：
- `.trellis/tasks/06-19-n6-hidden-protocol-scan/research/d22_frame_dump.py` — 全帧类型直方图 + 非游戏帧 13B 真值手牌块扫描 + 局开始时刻帧序列
- `.trellis/tasks/06-19-n6-hidden-protocol-scan/research/d22_decode_check.py` — 把 deal/round_start/room_info/0xc355 body 完整 dump + ASCII 还原，用于人工坐实"误报是字符串而非手牌"

数据源（明文，热点链路抓的 4 人金币局）：`data/phone_7777.pcap`、`data/stable_reader/raw_20260517_193242.pcap`、`raw_20260517_195618.pcap`、`raw_20260517_195549.pcap`、`data/phone_full.pcap`（前 60MB 流式抽样）。

---

## §1 各 pcap 全帧类型直方图（含非 0x2BC0）

把每个 wire 帧的外层 msg_type 与 0x2BC0 内层 sub_cmd 都统计了。**目标的非 0x2BC0 名册/详情帧确实存在**：

| 帧类型 (外层 msg_type) | 出现 | 首帧 body 实际是什么 |
|---|---|---|
| `0x0007 room_info` | 多次 | 房间元数据 + **服务器 IP 字符串**（如 `103.145.1.26:9000`） |
| `0x000A player_info` | 每局 1 | 短帧（28B），玩家 id/分数元数据，无 tile 块 |
| `0x000F unknown_0f` | 每 pcap 2 | 28B 固定密文样态（auth 相关），无 tile 块 |
| `0x0017 player_detail` | phone_full 中 3 | 短帧，无 tile 块 |
| `0x0019 score_update` | phone_full 中 30 | 分数更新，无 tile 块 |
| `0x0010 room_state` | 2 | 78B，房间状态位 + 0 填充，无 tile 块 |
| `0xC355`（未命名） | 1 | **整桌玩家名册 protobuf**：昵称（"LOLLAPALOOZA" 等）+ 微信头像 URL，无 tile 块 |
| `0x2B01`（未命名） | 1 | 118B，多为 0 填充，无 tile 块 |
| `0x2BC0 game_event` | 主体 | 真正的游戏事件（deal/draw/discard/meld/win/round_start...） |

phone_full 前 60MB 实测含 282 个 0x2BC0 + 全套名册/详情帧（0x17 player_detail×3、0xa player_info×1、0xf unknown_0f×10、0x19 score_update×30、0x7 room_info×1），即 D22 假设要找的"局开始名册预下发"帧**确实在主号实时流里出现过**——但里面没有对手手牌（见 §2/§4）。

> 关键校正：sweep 把 `0x000A` / `0x000F` 当作可能的 hand 载体，实测它们都是 28B 短帧（auth/分数元数据），body 根本放不下 3×13B 手牌。真正承载"全桌玩家信息"的大帧是 `0x2BC0 sub=0x0004 round_start`（313–345B，含昵称+头像URL+分数）和未命名的 `0xC355` 名册帧——两者都被检过，都不含手牌。

---

## §2 非游戏帧 body 扫描结果（13B 真值块搜索）

对所有非 0x2BC0 帧 body 滑窗扫 13B 块。判据：窗口内**无** 0x3c(占位)/0x72(mask)，非全 0/0xFF，**非 ASCII 文本串**（>=10/13 可打印 = IP/昵称/URL），且全字节在某编码（stable 或 instance）下合法 + >=5 个不同字节。

**初版（未加 ASCII 过滤）的"命中"全部是误报**，已逐一坐实：

| 误报帧 | off | 解码出的"tiles" | 真相（ASCII 还原） |
|---|---|---|---|
| `room_info` off=29 | `31 30 33 2e 31 34 35 2e 31 2e 32 36 3a...` | `[3,12,11,11,...]` | ASCII 字符串 `103.145.1.26:9000`（服务器 IP，字节恰落在 instance id [1..136] 区间） |
| `0xC355` off=53.. | 杂乱 | 杂乱 | 玩家名册 protobuf 的昵称/numid 字段（"LOLLAPALOOZA" 等） |

加上"ASCII 文本串过滤"（`printable >= 10/13` 直接 reject）后：

```
data/phone_7777.pcap:                  frames=205  nongame_big=2   real_hand_hits=0
data/stable_reader/raw_20260517_193242 frames=337  nongame_big=12  real_hand_hits=0
data/stable_reader/raw_20260517_195618 frames=661  nongame_big=14  real_hand_hits=0
data/stable_reader/raw_20260517_195549 frames=72   nongame_big=3   real_hand_hits=0
data/phone_full.pcap (前 8MB):          frames=5    nongame_big=0   real_hand_hits=0
data/phone_full.pcap (前 60MB 抽样):    7777帧=282+ 名册帧齐全       real_hand_hits=0
```

**所有 pcap 的非游戏帧里，真值对手手牌块命中数 = 0。**

---

## §3 局开始时刻帧序列人工检查

每局 deal/round_start 前后帧按时间序 dump，逐个看大帧。典型局开始序列（raw_20260517_195549）：

```
room_info(58B) -> player_info(28B) -> 0x2BC0/sub_0x0002(36B)
  -> 0x2BC0/deal(45B)           <== 自己起手
  -> 0x2BC0/round_start(329B)   <== 整桌名册（昵称+头像URL+分数+对手手牌占位 0x3c）
  -> 0x2BC0/sub_0x0005 / sub_0x0006 ...
```

逐帧拆 body（d22_decode_check.py 实跑）：

**deal (0x2BC0 sub=0x0003)** — body 29B：
```
0b 0b 26 25 03 02 0e 20 07 12 13 14 15   <- 前 13B = 自己手牌真值（stable 编码）
0b 02 02 02 46                            <- tail
3c 3c 3c 3c 3c 3c 3c                      <- 7 个 0x3c 占位
```
=> deal 只给自己 13 张真牌，**没有任何对手的牌**，尾部是 0x3c 占位。

**round_start (0x2BC0 sub=0x0004)** — body 313–345B，结构（4 人桌每人一段）：
```
[player id/score] [昵称 UTF-8] [大段 00 填充] 
[对手手牌位置 -> 3c 05 00 00 00 00 00 00] x4   <- 每个玩家槽位手牌字段 = 0x3c 占位 + 分数
[330000... 状态位]
[IP 字符串, 如 130.116.122.138]
[昵称重复] [https://thirdwx.qlogo.cn/.../132 头像 URL]
```
=> round_start 确实"一次性下发全桌玩家信息"，但**对手手牌字段就是 0x3c 占位**（每槽 `3c 05 00...`），与 H16 推 game-event 时把非归属玩家 hand_raw 替换 0x3c 的行为完全一致。昵称、头像 URL、分数、IP 都明文给了——唯独手牌被服务端 view filter 抹成 0x3c。

room_info 那帧（被初版误报）人工还原后是 `....7 ...(.0.@..:H...*`...10.145.1.26:9000`，纯属服务器地址字符串。

---

## §4 判定：D22 证伪 + 证据

❌ **D22 证伪。** H16 在主号自己的实时 7777 流上同样是 hard wall。

证据链：
1. **目标帧确实存在**：主号实时流里 room_info/player_info/unknown_0f/player_detail/round_start/0xC355 名册帧全都抓到了（§1），不是"没抓到所以没结论"。
2. **名册大帧被逐字节拆开**：round_start（最大的全桌信息帧）里对手槽位手牌字段是 `3c 05 00...`（0x3c 占位），昵称/头像URL/分数/IP 全明文，唯独手牌被抹（§3）。
3. **全 pcap 滑窗扫 0 命中**：5 个 pcap（含 phone_full 前 60MB）的非 0x2BC0 帧，加 ASCII 过滤后真值 13B 手牌块命中 = 0（§2）。初版的 18 个"命中"全部坐实为 IP 字符串 / 昵称 protobuf。
4. **deal 帧只给自己**：0x2BC0 deal body 前 13B 是自己真牌，对手位是 7×0x3c。

结论与已证伪的 D23/N7/N6 一致：**服务端 view filter 在任何下发给主号 client 的链路（含主号自己桌的实时 game-event 与名册帧）上，都把非归属玩家手牌替换为 0x3c。协议层离线读对手手牌的路在主号实时流上同样走不通。**

### Caveats / Not Found
- phone_full.pcap（161MB）只抽样了前 60MB（含完整若干局，名册帧齐全），未全量解；但全量解的边际价值低——帧类型已覆盖全，且 0 命中的结论在 4 个完整局 pcap 上一致。
- 本结论限定"协议明文层"。不否定昨晚 MEMORY 里记的结论：远程读自己手牌唯一可行路仍是手机进程内 Frida siphon；对手手牌在服务端就被过滤，离线协议层任何角度都拿不到。
- 扫描判据用了 ASCII 文本过滤（printable>=10/13 reject）+ 编码合法性 + >=5 distinct 字节。理论上一段恰好全非 ASCII、恰好编码合法、恰好 >=5 distinct 的真手牌若被嵌在非游戏帧，仍会被捕获；实测无此情况。
