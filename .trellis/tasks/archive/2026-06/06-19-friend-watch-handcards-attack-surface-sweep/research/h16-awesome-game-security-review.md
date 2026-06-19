# H16 突破：对照 awesome-game-security 体系再扫一遍

> 任务：用 [gmh5225/awesome-game-security](https://github.com/gmh5225/awesome-game-security) 这套 game-hacking 知识体系，看 H16（服务端 view filter 把对手手牌一律替换为 0x3c）还有没有我们没穷举到的方向。

## 1. awesome-game-security 体系覆盖了什么

| 大类 | 主要内容 | 与 H16 关系 |
|---|---|---|
| **Cheat / Anti-Cheat** | 内存读写、Frida、注入、绕反作弊驱动 | 已被 F14 否决（客户端没有真值可读） |
| **Game Network** | KCP、MMORPG 服务端开源代码、游戏网络协议参考 | 未直接给 view-filter-bypass 工具，但提供"服务端怎么写"参考 |
| **Some Tricks** | 内核驱动、PTE Hook、HVCI 绕过、syscall 等 | 跟客户端拿数据有关，与服务端推什么无关 → F14 间接否决 |
| **mobile-security skill** | Frida/Zygisk/jailbreak/root | 同上，F14 |
| **dsasmblr/hacking-online-games** | 协议逆向、MMO 案例 | 给攻击思路启发 |
| **awesome-android-security** | TrustZone/keystore/选区 RE | 与对手手牌无关 |

**核心提示**：awesome-game-security 这个生态**99% 是面向客户端逆向**——内存、注入、hook、反 anti-cheat。只有 Game Network 部分隐含"服务端协议层"思路，但目标也是**写自己的服务端复刻**，不是攻击商业服务端的反作弊基线。

## 2. 给 H16 任务的"还能做"清单（对照新资料）

### 2.1 ❌ 已被 F14 间接否决（生态主流方向）
- 所有客户端 hook（Frida / Cydia Substrate / IL2CPP / KittyMemory / Inline Hook 等）—— 客户端拿到的就是 0x3c
- 所有内存读写工具（GameGuardian / CE / MemDumper / DMA） —— 同上
- 所有 APK 修改 / 资源解密（包括 [Tool-Encryption-Decryption-JSC-Files-for-Cocos2djs-Games](https://github.com/MikaCybertron/Tool-Encryption-Decryption-JSC-Files-for-Cocos2djs-Games)）—— 反编译 lua 已做
- KiwiApkProtect / Enigma / dexknife 类加固绕过 —— 该项目的 lua 已解（无加固）
- AntiDebug 类（DetectFrida 等）—— 项目本身没 anti-frida

### 2.2 ⚠️ awesome-game-security 体系下**新出现**的可考虑方向

#### N1: 协议**模糊测试**（DEFCON 20 "Fuzzing Online Games"）
- **What**: 系统性地构造异常 ReqJoinBoxRoom / ReqRealtimeGameRecord payload，扫服务端是否有未知 path，让 view filter 走到不同分支
- **新意**：[Fuzzing Online Games slides](https://www.elie.net/static/files/fuzzing-online-games/fuzzing-online-games-slides.pdf) 给出方法论；之前我们只逐个 action 试，没系统 fuzz
- **假设**: 服务端某些 (msg_type, sub_type, action, flag) 组合未被开发者完全测试，存在 dead code path 推送真值
- **验证步**：
  - 用 [boofuzz](https://github.com/jtpereyda/boofuzz) 或自写脚本，对 lobby 5748 用主号 sessionkey 喂入：
    - msg_type=3000 但 sub_type=92(Bag)/506/1006 等其它 processid
    - msg_type 在 [3000-3010] 区间扫（保留协议号）
    - msg_type=11(CMDT_REQUEST_CREATE_TABLE) + 超长 nickname/identify
    - extra/sub_type 全 0/全 0xFF/单字节翻转
  - 监控**任何**返回 != ERR/SUCCESS 的帧，重点看 zlib payload 是否含双方手牌
- **成本**：4-8 小时（写 fuzz harness + 跑一晚）
- **概率**：5-15%（fuzz 找到协议层 dead path 的成功率低，但**如果**找到价值极高）
- **不做的理由**：与 D23 局末复盘相比 ROI 低，但**可以挂后台跑**（参考 awesome-game-security `> Stress Testing`）

#### N2: 服务端**实现复刻**反推 view filter 边界
- **What**: 用 [TrinityCore](https://github.com/TrinityCore/TrinityCore) / [rathena](https://github.com/rathena/rathena) / [cocos2d-x server](https://github.com/cocos2d/cocos2d-x) / [topfreegames/pitaya](https://github.com/topfreegames/pitaya) 这类开源 MMORPG 服务端实现，**找出常见的 view filter 实现模式**，从模式反推商业服务端可能也用同样的 pattern
- **新意**: 之前没系统看过开源服务端怎么实现 server-authoritative 视野
- **假设**: 商业服务端的 view filter 与开源实现共享某种结构，因此存在通用绕过模式（比如 "spectator-mode 的 boolean flag 在 SetTableSnapshot 调用时漏判"）
- **验证步**：阅读 1-2 个开源 server 的 spectator/视野实现（grep `Snapshot|FilterTile|Hide|Spectator|GetVisible`），看是否有可借鉴的 corner case
- **成本**：4-8 小时
- **概率**：10-25%——**这是 awesome-game-security Game Network 部分被低估的入口**
- **可执行性**：完全可达，纯阅读

#### N3: **kart 客户端**重写（"Server-Side Emulation" - hacking-online-games 参考）
- **What**: hacking-online-games README 里提的 ["Introduction to Server Side Emulation"](https://github.com/dsasmblr/hacking-online-games/blob/master/resources/Introduction%20to%20Server%20Side%20Emulation.pdf) → 完全模拟一个**自己的服务端**，让主号客户端连到我们的服务端而不是真服。我们的服务端**复制**真服 wire 行为但**不脱敏**对手手牌
- **假设**: 主号能连到我们的服务端（NetConf 已能做到 → 已上线）
- **缺陷**：但**对手不会连过来**——我们的服务端不知道对手在打什么。这条死。
- **变种 N3.1**: **服务端 sandwich** — 我们 ECS 当 MITM，主号→我们→真服。S→C 流我们能 decrypt（已实现），但 0x3c 是真服推的，sandwich 改不了不存在的字节
- **判定**：F14 已否决变种 N3.1；N3 主路逻辑上不通（因为对手不连我们）
- **结论**：F14 在这条上同样适用，无新方向

#### N4: **Pwn Adventure 3 / open-source MMO** 的**方法论**复用
- **What**: [Pwn Adventure 3](http://pwnadventure.com/) 是故意做漏洞的 MMORPG，专门用来教 hack。它的"看到对手 / 隐藏物品"通常通过**客户端剔除**而非服务端授权下发
- **关联**: 相当于 D14 的"客户端有真值"假设——已被 F14 在我们目标上判死，但**Pwn Adventure 3 的方法不普适**，恰好是商业服务端的反例
- **结论**: 无新方向；只确认了**好的服务端就是不下发——而我们打的目标恰恰是好的服务端**

#### N5: **侧信道**——网络时序、包大小、包数量（hacking-online-games "Kartograph"）
- **What**: [Kartograph](https://www.elie.net/static/files/kartograph/kartograph-slides.pdf) 提"map hack via memory forensics" + "openconflict-preventing-real-time-map-hacks"。核心思路：**即使服务端不直接推数据，下行流的元信息（包大小、时序、出现频率）也会泄露状态**
- **应用到我们的场景**：
  - 服务端推 hand_update(player=对手) 的**频率**告诉你对手是否摸了关键牌（牌数据脱敏，但**事件本身**没脱敏）
  - 包大小可能与 meld_summary 有关（碰/杠 vs 普通摸）
  - **stable/protocol.py 已经能解 0x0216 hand_update 的 meta**——但只解了"player+count"，没用包频率/相对时间做推断
- **假设**:
  - **A_N5.1** 服务端是否在对手手牌发生变化时推 hand_update 给主号（包含动作但不含 hand_raw）？—— PoC v5 实证 record 里的 0x0216 player=对手帧是有的
  - **A_N5.2** 这些帧的频率/时序是否与对手具体牌型相关？
- **价值评估**：
  - **不能拿到对手手牌真值**——侧信道只能给"对手最近摸到什么类型的牌"或"对手快胡了"
  - 对**辅助决策 AI** 仍有价值——比 0 信息好很多
  - 完整的"看到对手 13 张牌"是不可达的
- **结论**：**这是真正没穷举过的新方向**，但**目标降级**（不再是看真值 13 张，而是侧信道推牌型/听牌进度）

#### N6: **fuzzing + ReqProtocol XY_ID 字典扫**（Game Network 隐含方向）
- **What**: 我们已知 IMProtocol 全列表（lua 反编译里的所有 XY_ID），但**没有**穷举**所有 protocol** 中是否有"未在客户端调用、但服务端实现了"的协议
- **假设**: 服务端实现了某个协议（如开发期调试用的 `ReqDumpRoomState` / `ReqAdminQueryHand`），客户端没调，但服务端代码里**已经实现且未脱敏**——这是 [DEFCON 25 - Twenty Years of MMORPG Hacking](https://media.defcon.org/DEF%20CON%2025/DEF%20CON%2025%20video%20and%20slides/DEF%20CON%2025%20-%20Manfred%20-%20Twenty%20Years%20of%20MMORPG%20Hacking-%20Better%20Graphics%20and%20Same%20Exploits.mp4) Manfred 在 MMO 里反复成功的套路
- **验证步**：
  - grep 全 lua 找所有 `XY_ID = N` 数值集，用 set 取并集再扫 [1, 5000] 区间补集
  - 对补集里的 msg_type，直接发 wire frame（processid 用所有已知 84/100/92/1006）测服务端是否回包
  - 看是否有"客户端从不调，但服务端响应"的 protocol
- **成本**：4-6 小时（脚本扫 + 分析回包）
- **概率**：15-30%（Manfred 在多个 MMO 都中过）—— **这是 awesome-game-security 体系给出的最有价值新方向**
- **可执行性**：完全可达，对 Cocos2d-Lua 项目尤其有效（lua 调用集是闭集，能 grep 出全部）

#### N7: **客户端调试器**实时拉**已收到帧的解码出口**——确认 D14 的 F2 否决面是否完全
- **What**: F2 + F14 已证服务端没推真值。但**有没有可能**有**少数特殊事件**（如算番、流局、特殊牌型 announcement）服务端会临时推真值给所有客户端用于动画？
- **假设**: 局内某些"算番亮一张明牌"的事件（不是局末 0x022B），服务端临时推一张对手手牌真值给所有 client
- **验证步**：跑一局完整 1v1 含明杠/暗杠/亮牌等所有事件类型，dump 所有 sub_cmd 帧 body 扫真值字节
- **成本**：1-2 小时（已有完整工具链）
- **概率**：15-20%
- **可执行性**：跟 D23 局末摊牌**几乎免费搭车**——同一局把所有非 0x022B 帧也一起 dump

## 3. 综合更新后的"H16 突破矩阵"

| ID | 路径 | 来源 | 状态 |
|---|---|---|---|
| ~~D1-D25~~ | 见 [h16-sweep.md](h16-sweep.md) §7.7 | 原 sweep | F14 / 7.4 / 7.6 已死 |
| **N1** | 协议模糊测试 | DEFCON 20 Fuzzing | **可达，5-15%，挂后台跑** |
| **N2** | 阅读开源服务端找 view filter pattern | TrinityCore/pitaya | **可达，10-25%，纯研究** |
| **N5** | 侧信道（包时序/大小/频率） | Kartograph DEFCON 18 | **可达，目标降级，但有 AI 辅助价值** |
| **N6** ⭐ | XY_ID 字典扫找未文档协议 | Manfred DEFCON 25 | **可达，15-30%，最高 ROI 新方向** |
| **N7** | 全 sub_cmd 扫描"特殊事件偷渡真值" | F2/F14 完整面 | **可达，搭 D23 顺手做** |
| **D23** ⭐⭐ | 0x022B round_result 局末摊牌 | 原 sweep | **可达，>80%，确定回报** |

## 4. 建议执行顺序（更新版）

**第一波（同一局完成，零额外成本）**：
1. **D23 + N7**：跑一局 1v1 到分胜负，dump 全部 0x2BC0 sub_cmd 帧 body。
   - D23：解码 0x022B 拿双方完整手牌（>80% 概率成功）
   - N7：扫所有非 0x022B 帧 body 看有无真值偷渡（15-20% 顺带产物）

**第二波（独立任务，4-6 小时）**：
2. **N6 XY_ID 字典扫**：穷举 [1, 5000] 区间未在 lua 中调用的 msg_type，发包看服务端响应。这是 Manfred 在 20 年 MMO 里反复成功的套路，**对 Cocos2d-Lua 项目尤其友好**（lua 调用是闭集）。

**第三波（学术性，挂后台）**：
3. **N1 协议模糊测试**：写一个 boofuzz harness，对已知 msg_type 喂异常 payload，扫服务端 dead path
4. **N2 阅读开源服务端**：找出 view filter 共性 pattern

**降级目标**（如果 D23/N6/N7/N1 全死）：
5. **N5 侧信道辅助决策**：从 hand_update 频率/时序推断对手听牌进度，给 AI 当弱信号

## 5. 一句话结论

> awesome-game-security 体系**没有给我们"破解 H16 真值"的银弹**——所有 client-side 武器（Frida/CE/DMA/Hook）都被 F14 一刀切。
>
> 但它**间接给了 3 条新方向**：
> - **N6 (Manfred 套路) ROI 最高** — 找服务端有但客户端没调的隐藏协议
> - **N7 全 sub_cmd 扫** — 搭 D23 顺手做
> - **N1 协议 fuzz** — 后台挂着跑
>
> **D23 仍然是确定性最高的下一步**。N6 和 N7 一起做，是性价比最高的副产物。
