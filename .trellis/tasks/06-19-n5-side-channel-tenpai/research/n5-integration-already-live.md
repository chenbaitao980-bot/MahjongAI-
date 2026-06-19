# N5 集成现状核查 (2026-06-20 凌晨自主分析)

> 用户授权自主推进。本文件核查 N5 信号是否已在 codebase 中 live，避免重复造轮子。

## 核心结论：N5 的强信号**已经 ship 了**，不是新能力

追踪完整调用链，确认对手 discard 河 + meld 副露 → 危险度 的强信号链路**已端到端打通并 live**：

```
stable/tracker.py
  players[opponent].discards / .melds        # 事件解码时已累积(line 244+)
  → to_battle_state() (line 588-589)         # 复制进 BattleState
      state.enemy_discards = [...]
      state.enemy_melds = [...]
  → BattleState.to_payload() (state.py:109-110, 148-149, 190-191)
      "enemy_discards": [...], "enemy_melds": [...]
  → game/evaluator.py (line 135-138)
      calc_tile_danger(tile, enemy_discards, enemy_melds, ...)
  → game/advisor.py (line 145, 200-201)
      同样吃 enemy_discards/enemy_melds
  → BattleAdvice 危险度评级
```

**即：对手弃牌河 + 副露推危险牌，这个标准日麻防守功能在 stable 模式下早已工作。** N5 PoC 的价值是**实证确认**这条链路的数据（对手 discard/meld）在该协议/record 下可靠可解（26K:24/24, 33K:29/29 弃牌全解真值，meld 全解真值），而非新增能力。

## N5 真正能新增的：只有弱信号字段

既有链路没有的、N5 可加的：
1. `opponent_draw_count`（数 0x021A player≠self 事件）—— 弱，仅巡目进度
2. `est_tenpai_prob`（公开信息启发式）—— 弱，看不到隐藏 13 张
3. `opponent_last_act_gap`（record 时间戳间隔）—— 弱，1 秒粒度噪声大

## 判断：弱信号该不该接？

**倾向不接 `est_tenpai_prob` 进 LLM prompt**。理由：
- 强信号(danger)已 live 且准确，是真实防守输入
- `est_tenpai%` 看不到对手手牌，本质是「巡目 + 弃牌型」的粗启发式，给 LLM 一个带数字的「听牌概率」反而可能被当成 ground truth 误导决策
- 与 H16 诚实性原则冲突：我们拿不到对手手牌，不该暗示「知道对手听牌」

**可接的低风险增强**：
- `opponent_draw_count` / 巡目深度 —— 客观计数，LLM 可用来判断牌局阶段，不误导
- 把 danger_top（已有）在 prompt 里**显式标注**为「来自弃牌河分析的权威防守输入」，强化既有强信号的利用

## 给用户的建议（明天决策）

N5 的"降级目标"在 codebase 层面**其实已达成**（强信号 live）。剩下是产品选择：
- **A. 接 N5 弱信号**：加 draw_count + 巡目深度到 payload + prompt（低风险增强）；`est_tenpai%` 标注"低置信"或干脆不接
- **B. 不动**：认为既有 danger 已够，N5 PoC 作为"协议可解性验证"归档即可
- **C. 强化强信号**：检查 stable 模式实战中 enemy_discards 是否真的填充了（PoC 证明 record 可解，但要确认 live tracker 在 1v1/金币局都正确 populate）—— 这条最有实战价值

我倾向 **C**：验证 live 链路在真实对局中确实填充 enemy_discards（而非只在离线 record 可解），因为这才是"对 AI 有用"的落点。需要用户打一局并 dump BattleState 验证。

## 不需用户的后续

无。N5 强信号已 live，弱信号增强需产品决策，强信号 live 验证需真实对局。N5 PoC 阶段到此为止。
