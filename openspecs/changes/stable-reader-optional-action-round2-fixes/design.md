# 设计：stable-reader-optional-action-round2-fixes

## 当前状态

### 数据生命周期

```
抓包字节 -> MJProtocol._decode_frame -> _decode_game_event
-> PacketStateTracker.apply -> snapshot/to_battle_state
-> StableBattlePanel.set_snapshot/set_advice -> UI/ExcelGameLogger
```

当前破损点：

- `0x0016 action_notify` 仅出现在 `GAME_SUB_NAMES`，没有结构化字段，导致“可选动作”无法进入 tracker 和 UI。
- `0x0216 hand_update` 只要 `count` 合法就当作手牌更新；但实战中存在副露/桌面汇总型 payload，`count=1/5` 时会把副露值误塞进我方手牌。
- `0x021F meld` 对含财神替代或特殊杠格式的 body 识别不足，20:51:06 的 `00050104434343430343434300000000` 未产生 `meld_tiles_raw`，导致杠后从手牌扣牌失败。
- `analysis_mode()` 允许 conservative 模式在敌方回合继续触发分析，UI 也不会清空旧候选表。
- LLM 校验只接受模型原样输出的 `recommended_discard`，没有处理中文牌名、空格、候选描述里带牌名等常见返回形态。
- 三角标记目前没有协议字段承接，也没有备注展示位。

## 方案

### 1. 可选动作解析与展示

- 在 `stable/protocol.py` 为 `0x0016 action_notify` 增加轻量解析：
  - 识别候选动作类别：`chi`、`pon`、`kong`、`hu`、`pass`。
  - 保留 `body_hex`、候选牌原始值、方向、时间戳。
  - 无法确认结构时仍输出 `event="optional_action"` 和 `raw_options`，避免 UI 完全无信息。
- 在 `stable/tracker.py` 增加 `optional_actions` 和 `last_optional_action_ts`：
  - 出现可选动作时写入 snapshot。
  - 我方摸/打/吃/碰/杠或过期后清空。
- 在 `ui/stable_battle_panel.py` 中用现有“备注/候选动作”区域展示“可选动作：吃 / 碰 / 过”。

### 2. 手牌完整性与副露汇总包防污染

- `0x0216` 仅当满足可信手牌形态时更新手牌：
  - 本地玩家全量手牌：`count in (13, 14)` 或 `count=13` 且 tail 可确认第 14 张。
  - 小 `count` 包如果 tail 里呈现多组副露结构，则解析为 `meld_summary` 或忽略手牌字段，不覆盖 `players[local].hand`。
- tracker 遇到非全量/不可信手牌包时：
  - 不清空或覆盖既有手牌。
  - snapshot 增加 `hand_incomplete_reason`，UI 显示“等待可信手牌包/增量可能不完整”。

### 3. 杠与财神替代副露

- `_extract_meld_info()` 兼容：
  - `body[3] >= 4` 的明杠/补杠格式。
  - `body` 中重复牌后跟来源牌的格式，例如 20:51:06 `43 43 43 43 ...`。
  - 含财神替代值的顺子，如 `37 53 39`，应保留原始 meld，展示中可标注“含财神替代”。
- tracker 对本地杠：
  - 明杠/补杠按实际从手牌移除的张数扣除，避免 claimed tile 已来自弃牌时多扣或少扣。
  - 如果协议给出了可信 full hand，则以 full hand 校准增量状态。

### 4. 敌方回合分析门控

- `analysis_mode()` 在 `current_turn != "self"` 时返回 `blocked` 或新增 `waiting_enemy`。
- `analysis_blocked_reason()` 明确返回“等待敌方出牌/等待我方摸牌”。
- UI 收到该状态时：
  - 当前推荐出牌显示 `--` 或“等待敌方出牌”。
  - 候选分析表清空并显示等待态。
  - 不保留上一轮建议造成误导。

### 5. LLM 输出归一化与兜底

- 在 `game/llm_advisor.py` 增加 `normalize_discard()`：
  - 支持 `5m`、`五万`、`打五万`、`候选方案：打5m` 等映射到合法候选 ID。
  - 只在归一化后结果属于 `legal_discards` 时接受。
- 当 LLM 不合法时，继续返回程序 top candidate，并把原始响应截断保存到 `raw_response`，UI 展示“已降级为程序推荐”而不是没有建议。

### 6. 三角标记备注

- 在协议层先保留疑似标记字段和 raw evidence。
- tracker snapshot 增加 `marked_tiles`。
- UI 和 Excel 备注显示“标记牌：五万、一条”等；如果只知道 raw 值，则显示 raw key，待映射确认后自动重建。

## 根因排序

P1：`0x0216` 副露汇总包误当手牌更新，解释 20:52:47 后“西 西 西”污染手牌。验证：用 `body_hex=000405010443...` 回放，当前会得到 `hand_raw=[1,4,67,67,67]`。

P2：`0x021F` 特殊杠/财神替代副露未识别，解释 20:51:06 warning 和杠后手牌扣减不完整。验证：新增单测覆盖 `00050104434343430343434300000000`。

P3：敌方回合 conservative 分析仍触发，解释截图中敌方回合仍显示保守建议和 LLM 不合法。验证：构造 `current_turn="enemy"`，`should_analyze()` 应为 false。

P4：LLM 输出格式未归一化，解释第二把开始持续“不合法”但仍应有程序建议。验证：用中文牌名/带“打”字的 JSON 响应跑 `validate_llm_output()`。

## 回滚方案

每个改动点独立回滚：移除 action_notify 解析、恢复 `0x0216` 原手牌判定、恢复副露解析、恢复 conservative 分析门控、恢复 LLM 原校验逻辑、隐藏标记备注字段。
