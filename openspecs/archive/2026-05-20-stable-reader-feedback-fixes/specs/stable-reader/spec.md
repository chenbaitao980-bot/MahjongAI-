# Delta: stable-reader-feedback-fixes

## 与主规范关系

修订 [openspecs/specs/stable-reader/spec.md](openspecs/specs/stable-reader/spec.md)：

- **ADDED** Requirements: 副露事件解码（吃/碰）、财神协议解码（0x0218）、事件流自动滚动、未知映射可读性
- **MODIFIED** Requirements: 分析门控（新增保守模式）

## 关联业务行为声明

- 与已归档 `stable-packet-reader` 不冲突：本次新增的 sub_cmd 不在前者声明的解码范围。
- 与已归档 `stable-reader-display-fixes` 不冲突：前者改的是 hand 排序 + TCP 去重 + npcap 全口抓包；本次改 sub_cmd 解码 + UI 反馈，代码段不重叠。
- 与同期补漏的 `excel-game-logger` 不冲突：B 改 closeEvent / log_row 持久化路径，C 改 _on_stable_message 路径上下游 + protocol/panel。

## 变更摘要

| 维度 | 状态 |
|---|---|
| 主规范 Req 命中（ADDED） | 副露事件解码、财神协议解码、事件流自动滚动、未知映射可读性 |
| 主规范 Req 命中（MODIFIED） | 分析门控 |
| 其他 active change 撞车 | 无 |
| 关联行为 | excel-game-logger 补漏（同 _on_stable_message 路径但不同代码段） |
| 归档完整性 | 待实施后写 delivery.md |

---

## ADDED Requirements

### Requirement: 副露事件解码（吃/碰）

稳定版读取器必须将吃（chi）、碰（pon）副露事件作为独立解码路径产出，与现有 kong 路径并列，包含以下字段：

- `event`: `"chi"` 或 `"pon"`
- `player`: 副露玩家座位
- `meld_type`: `"chi"` 或 `"pon"`
- `meld_tiles_raw`: 副露包含的原始牌字节列表
- `tile_context`: `TILE_CONTEXT_STABLE`
- `source`: `SOURCE_TRUSTED_ACTION`
- `trusted`: `True`

`PacketStateTracker._apply_game_event` 必须在 `event in ("chi", "pon")` 时：

1. 把副露追加到 `players[player_id].melds`（格式 `{"type": meld_type, "tiles": meld_tiles}`）
2. 从被吃/碰一方的 `discards` 末尾移除一张同值牌（复用 `_remove_claimed_discard`）
3. 不扣 `remaining_tiles`（吃碰不摸牌）
4. 若 player 是我方，`current_turn = "self"`；若是对面，`current_turn = "enemy"`

`event_log` 必须追加形如 `"19:35:47 对面碰5万"` 的中文事件。

#### Scenario: 对面副露多组都被记录

- **WHEN** 对面在一局内发生 明杠东 → 吃5万6万7万 → 碰白白白 三个副露
- **THEN** `snapshot()["players"][opponent_id]["melds"]` 包含 3 个元素，类型分别 `kan_open / chi / pon`，UI 显示「明杠[东东东东] 吃[五万六万七万] 碰[白白白]」

#### Scenario: 吃/碰从被打出方弃牌区移除

- **WHEN** 对面打出 5万 后我方吃 5-6-7 万
- **THEN** `snapshot()["players"][opponent_id]["discards"]` 末尾的 5万 被移除；`players[local_id]["melds"]` 加入 chi 5万-6万-7万

### Requirement: 财神协议解码（0x0218）

稳定版读取器必须将 `msg_type=0x2BC0, sub_cmd=0x0218` 视为可信财神更新包：

- `body[0]` 必须为 marker `0x01`
- `body[1]` 为 baida raw（stable nibble 编码），不能为 `0` 或 `HIDDEN_TILE`
- 产出 `event="baida_update"`、`baida_raw=body[1]`、`baida_context=TILE_CONTEXT_STABLE`、`baida_trusted=True`、`trusted=True`

`MJProtocol.GAME_SUB_NAMES` 必须包含 `0x0218: "baida_update"`。

`PacketStateTracker._apply_game_event` 必须在 `event == "baida_update"` 时调用 `_apply_baida(game)` 应用财神。

`event_log` 必须追加形如 `"19:27:35 财神更新：七筒"`。

#### Scenario: 0x0218 在 hand_update 前被解码并应用

- **WHEN** 抓包中先后收到 `sub_cmd=0x0218, body=01 37 01 53` 和 `sub_cmd=0x0216 hand_update (count=13)`
- **THEN** snapshot 中 `baida_tile="7p"`、`baida_trusted=True`，且 `hand_trusted=True` 后 `should_analyze()` 立刻满足

#### Scenario: 4 局连续财神切换

- **WHEN** 对局 4 局，财神 raw 依次 `0x37 / 0x34 / 0x16 / 0x11`
- **THEN** `snapshot["baida_tile"]` 在每局 `0x0218` 包到达后更新为 `7p / 4p / 6m / 1m`

#### Scenario: deal 包的 untrusted candidate 不被应用

- **WHEN** `0x0003 deal` 的 `untrusted_baida_raw_candidate=0x46` 到达
- **THEN** `baida_trusted` 保持 `False`，`baida_tile` 不变；只有后续 `0x0218` 才真正应用

### Requirement: 事件流与实时数据视图自动滚动（靠近底部触发）

`StableBattlePanel.set_snapshot` 必须在刷新 `_event_view` 与 `_data_view` 前判断滚动条距底部距离：若 ≤ 60 px（或 maximum=0），则在 setPlainText 后把滚动条置最大；否则保持原位置。

#### Scenario: 新事件来时自动滚到底

- **WHEN** 用户当前停留在视图底部（距底 ≤ 60 px），snapshot 追加新事件
- **THEN** 视图自动滚到底显示最新事件

#### Scenario: 用户手动查历史时不被踢回

- **WHEN** 用户拖动滚动条到视图中部查历史，snapshot 仍持续追加新事件
- **THEN** 视图保持在用户拖动的位置，不自动滚回底部

### Requirement: 未知映射修正区可读性

`StableBattlePanel` 的「未知映射修正」区必须满足：

- 区块 `setMinimumHeight(220)`
- 表格行高 `>= 28 px`，字体 `>= 10pt`
- 牌面下拉框 `setMinimumHeight(32)`、字体 `>= 11pt`
- 「保存映射」按钮 `setMinimumHeight(32)`、字体 `>= 11pt 加粗`
- 区块顶部必须有 3 行使用说明 QLabel，指导用户「选行 → 选实际牌 → 点保存」流程

#### Scenario: 下拉项内容可读

- **WHEN** 用户点开牌面下拉
- **THEN** 每一项「1万 (1m)」「2万 (2m)」... 在 11pt 字号下完整可见

---

## MODIFIED Requirements

### Requirement: 分析门控（新增保守模式）

`PacketStateTracker` 必须暴露三态 `analysis_mode()` 方法，返回 `"full" | "conservative" | "blocked"`：

- `"full"`：`hand_trusted` 且 `baida_trusted` 且 `turn_trusted` 且 `current_turn == "self"` 且 `effective_self_count == 14` 且无未识别牌值
- `"conservative"`：`hand_trusted` 但缺其中任一条件（除「无未识别牌值」外，仍要求映射完整以避免误识别）
- `"blocked"`：`hand_trusted == False`

`should_analyze()` 必须在 `analysis_mode != "blocked"` 时允许分析（仍受 `analysis_signature` 去重，避免风暴）。

`to_battle_state()` 必须在 `analysis_mode == "conservative"` 时置 `state.is_conservative = True`，否则置 `False`。

`BattleState` 必须新增字段 `is_conservative: bool = False`。

`BattleService.analyze_state_with_ai` 必须读取 `state.is_conservative`，若 `True`，在 system prompt 中明确「当前财神或回合信息不全，请仅基于已知手牌给出保守建议，避免依赖财神或推断对方禁手」。

`StableBattlePanel.set_snapshot` 必须：

- 当 `analysis_blocked_reason` 非空且未渲染过真实建议时，把推荐出牌标签设为「等待中：<原因>」
- 当 `analysis_mode == "conservative"` 时，策略类型前缀「[保守] 」
- 一旦 `set_advice` 被调用，标记 `_has_advice_rendered=True`，后续 snapshot 不再覆盖建议区

#### Scenario: 财神缺失仍能给保守建议

- **WHEN** hand_trusted=True、baida_trusted=False、current_turn="self"、count=14
- **THEN** `analysis_mode() == "conservative"`、`should_analyze() == True`，BattleAnalysisThread 启动并最终调用 `set_advice`，UI 显示「策略类型：[保守] ...」

#### Scenario: 等待门槛阶段 UI 不显示初始 "--"

- **WHEN** hand_trusted=False、刚启动抓包尚未收到 hand_update
- **THEN** 策略建议区显示「等待中：等待可信手牌包」，不显示「当前推荐出牌：--」

#### Scenario: 真实建议覆盖等待提示

- **WHEN** 先进入 conservative 模式收到一次 AI 建议
- **THEN** `_recommended_label` 显示具体出牌；后续 snapshot 即使再有 blocked_reason，也不会再覆盖回「等待中」
