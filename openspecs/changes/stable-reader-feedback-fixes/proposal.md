# 稳定版反馈与解码补完

## 为什么要做

实测一局后用户反馈 5 个并存问题，全是反馈层（UI、解码、UX）的疏漏，需要打包修复：

1. **事件流不自动滚到底** —— 新事件来后视图保留旧滚动位置，必须手动拖到底看最新。
2. **副露区只显示明杠，缺失吃/碰** —— 实测对面副露区是「东东东 七万白七万」，识别只显示「明杠[东东东]」；后续的吃/碰事件**根本没产出**。
3. **财神识别一直失败** —— 状态栏始终「等待抓包解析财神」。用户实测 4 局财神分别是 7p / 4p / 6m / 1m，现有 `0x0003 deal` 包里 byte[17] 与真值完全无关——财神不在 deal 包里。
4. **策略建议区永远显示 "--"** —— 因为问题 3 导致 `should_analyze()` 一直返回 False，BattleAnalysisThread 不启动，建议永远不刷新。即使财神缺失，也应能给保守建议。
5. **未知映射修正区域过小，字号过小** —— ComboBox 高度仅约 16 px，「1万 (1m)」几乎看不清；用户不知道怎么修正。

## 实测协议事实（来自 `data/stable_reader/events_20260519_192721.jsonl` 解析）

| 事实 | 数据 |
|---|---|
| 财神协议位置 | `sub_cmd=0x0218`，`body=01 [baida_raw] 01 53`，每局精确出现 1 次 |
| 财神 4 局真值匹配 | 7p→`0x37`、4p→`0x34`、6m→`0x16`、1m→`0x11` 全部 100% 命中 body[1] |
| 当前 deal 包 byte[17] | 第 1 局 = `0x46`（非财神），现有代码误把它当成 untrusted candidate |
| 副露候选 sub_cmd | `sub_0x021d`（2 次）、`sub_0x05dc`（26 次）、`sub_0x0211`（16 次）—— 具体哪个是 chi/pon 需在实施第 1 步验证 |

## 变更内容

### 协议层（`stable/protocol.py`）

1. **新增 `sub_cmd=0x0218 → baida_update` 解码路径**：取 `body[1]` 为 `baida_raw`，置 `baida_trusted=True`，附 `baida_context=TILE_CONTEXT_STABLE`。
2. **新增吃/碰副露解码**：在实施第 1 步用 `events_*.jsonl` 关联 hand_update/discard 时序定位 chi/pon 对应的 sub_cmd 值（强烈候选 `0x021d` / `0x05dc`），按 `_extract_meld_info` 复用 chi/pon 分支输出 `meld_type` + `meld_tiles_raw`。
3. **`GAME_SUB_NAMES` 新增映射**：`0x0218: "baida_update"` 以及 chi/pon 的 sub_name。

### 状态层（`stable/tracker.py`）

1. **`_apply_game_event` 新增 `event == "chi" / "pon"` 分支**：追加到 `players[pid].melds`，被吃/碰的弃牌从对方 discards 移除（复用 `_remove_claimed_discard`），更新 `current_turn`，扣手牌（如果我方副露）。
2. **`_append_event` 新增 chi/pon 事件日志**。
3. **`analysis_blocked_reason` / `should_analyze` 不改逻辑**，但新增 `analysis_mode` 属性返回 `"full"|"conservative"|"blocked"`：
   - `full`：所有 trusted 满足
   - `conservative`：`hand_trusted=True` 但 `baida_trusted=False` 或 `turn_trusted=False`——允许跑保守分析
   - `blocked`：连手牌都不可信
4. **`should_analyze` 在 `conservative` 模式下也返回 True**（仍受 signature 去重），但 `to_battle_state` 标注 `state.baida_tile = ""`、`state.is_conservative = True`。

### UI 层（`ui/stable_battle_panel.py`）

1. **事件流自动滚动**：`set_snapshot` 内 `setPlainText` 后调 `verticalScrollBar().setValue(.maximum())` 把视口顶到最底。实时数据视图同样处理。
2. **策略建议区显示 blocked_reason**：当 `snapshot["analysis_blocked_reason"]` 非空时，把 `_recommended_label` 设为「等待中：<原因>」，`_strategy_label` 设为对应模式（`等待门槛 / 保守模式`）；正常分析完成后由 `set_advice` 覆盖。
3. **保守模式视觉提示**：`set_advice` 收到 `state.is_conservative=True` 时，策略类型行前缀「[保守] 」并把 `_summary_edit` 框背景色调浅黄。
4. **未知映射区放大**：
   - `right.addWidget(mapping_box, 1)` 权重保持，但给 `mapping_box.setMinimumHeight(220)`
   - `_mapping_table.verticalHeader().setDefaultSectionSize(28)`、`setFont(QFont("", 10))`
   - `_mapping_tile_combo.setMinimumHeight(32)`、`setFont(QFont("微软雅黑", 11))`
   - `_mapping_save_btn.setMinimumHeight(32)`、`setFont(QFont("微软雅黑", 11, QFont.Weight.Bold))`
   - 在 mapping_box 顶部加一行说明 QLabel：「① 选中表格中一行（未识别牌值）；② 在下拉选实际是哪张牌；③ 点保存映射，所有历史会按新映射重解码。」

### 不在范围

- 不改 `_decode_game_event` 中 deal / hand_update / draw / discard / kong / win 的解码语义（仅 0x0218 新增、chi/pon 新增）。
- 不改 mapping_store 内部逻辑（资源仍是 `data/stable_reader/mappings.yaml`）。
- 不改 BattleService 的 conservative 分析实现细节（仍走 `analyze_state_with_ai`，state 上带 is_conservative 标记由 AI 提示词决定）。
- 不动 visual / battle 模式。

## 成功标准

- 截图同样场景下打一把：实时数据中对方副露区显示「明杠[东东东] 吃[五万六万七万] 碰[白白白]」（或实测对应组合）。
- 财神在第一手 hand_update 之前的 1~2 秒内识别成功，状态栏显示 `财神：七筒`（或对局真值）。
- 事件流每次新事件后自动滚到底，无需手动拖动。
- 即使财神识别失败（或刚开局还未到 0x0218 包），策略建议区显示「等待中：等待抓包解析财神」而不是默认 "--"；财神可信后切换到正常建议；保守模式时显示「[保守] ...」前缀。
- 未知映射区放大至 220 px 高，ComboBox 字号 11pt 高 32 px，下拉项可读。
