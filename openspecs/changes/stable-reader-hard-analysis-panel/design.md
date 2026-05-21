# 设计：stable-reader-hard-analysis-panel

## 当前状态

稳定版面板左侧展示来自 `PacketStateTracker.snapshot()` 的状态数据，右侧此前展示 AI 建议、原因和 `AnalysisPanel` 候选分析表。右侧内容可能来自 `BattleState.last_analysis`、DeepSeek 返回或 MC/危险度评分，不满足“硬算且与 UI 展示完全同源”的要求。

现有可复用能力：

- `snapshot()`：稳定版 UI 的唯一展示状态来源。
- `game.shanten.calc_shanten()`：支持财神 wildcard 的向听计算。
- `game.ukeire.calc_ukeire()`：计算打出后有效进张。
- `game.tiles.build_visible_tiles()`：从手牌、弃牌、副露统计可见牌。

## 方案

新增 `game/stable_hard_analysis.py`，定义独立硬算模块：

1. 输入只接受 `snapshot: dict`。
2. 从 `snapshot.players[local_player]` 读取我方手牌、弃牌、副露，从 `snapshot.players[opponent_player]` 读取对方弃牌、副露。
3. 从同一 `snapshot` 读取财神、回合、可信度、未知牌值、可选动作。
4. 使用 `hand_to_counts()` + `calc_shanten()` 计算当前向听。
5. 提供 `getTingTiles()`/`get_ting_tiles()`，枚举 34 种进张，返回能胡牌及剩余张数。
6. 14 张有效手牌时枚举每张可打牌，计算打后向听、听牌列表、有效进张。
7. 推荐牌只按硬规则排序：不打财神优先、向听更低优先、有效进张更多优先。
8. 输出 `StableHardAnalysis`，UI 只负责格式化渲染。

`ui/stable_battle_panel.py` 调整：

- 删除右侧 `AnalysisPanel` 使用。
- 新增只读硬算文本框。
- `set_snapshot()` 每次刷新都调用 `analyze_snapshot(snapshot)`，确保右侧与左侧同源。
- `clear_stream_buffer()`、`append_stream_chunk()`、`set_advice()` 不再让 AI 流式文本覆盖硬算面板。

## 数据生命周期

```text
抓包事件
  -> PacketStateTracker.apply()
  -> PacketStateTracker.snapshot()
  -> 左侧实时数据渲染
  -> game.stable_hard_analysis.analyze_snapshot(snapshot)
  -> 右侧硬算面板渲染
```

## 边界

- 不修改 `calc_shanten()`，避免扩大共享规则引擎影响面。
- 不改抓包协议解析。
- 不改 `BattleState`、LLM prompt、MC 模拟。
- 当前只展示硬算事实，不做番数、危险度、MC 胜率和软策略。

## 回滚方案

删除 `game/stable_hard_analysis.py` 和 `tests/test_stable_hard_analysis.py`，并把 `ui/stable_battle_panel.py` 右侧恢复为 `AnalysisPanel` 与原 AI 文案渲染。

## 追加方案：对方预测

当前稳定版抓包不会提供对方隐藏手牌明文，`stable-reader` 主规范也要求对面玩家的 `hand` 字段始终为空或隐藏。因此追加预测只能基于可见信息做概率/风险估计，不能把预测结果渲染为确定手牌。

实现方式：

1. 在 `StableHardAnalysis` 增加两个展示字段：
   - `opponent_hand_prediction`: 对方手牌可能性预测，描述对方副露形态、弃牌缺门/偏好、剩余危险花色或字牌倾向。
   - `opponent_progress_prediction`: 对方进度预测，描述对方可能处于早期/中期/接近听牌/已高度危险的阶段。
2. 计算输入只使用同源 `snapshot()`：
   - 对方弃牌、副露、手牌计数。
   - 我方手牌、双方弃牌、副露构成的可见牌。
   - 当前剩余牌数、当前回合。
3. 预测策略保持保守：
   - 有 3 组以上副露或弃牌很少且副露多时，标记为高进度/高风险。
   - 有 2 组副露时，标记为中高进度。
   - 有 0-1 组副露且弃牌较多时，标记为中低进度。
   - 按对方弃牌较少的花色/字牌、对方副露花色，提示“可能保留/需要关注”的类别。
4. UI 展示在右侧硬算文本中，文案必须包含“估计/可能/关注”等不确定表达。

## 追加业务规则处理

- 原 Requirement / Scenario：稳定版硬算面板使用同源 snapshot 展示可验证数据。
- 本次处理方式：追加 Scenario，不修改隐藏手牌规则，不改变抓包协议和 `PacketStateTracker.snapshot()` 的对方手牌隐藏约束。
- 非目标：不实现真实对方手牌还原，不引入 AI 文案，不使用历史局外数据。
