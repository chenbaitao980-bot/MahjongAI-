# 交付：stable-reader-optional-action-round2-fixes

## 已完成

- `stable/protocol.py`
  - 新增 `action_notify` 可选动作轻量解析。
  - 将小 count 且尾部呈现多组副露结构的 `0x0216` 识别为 `meld_summary`，不再输出可信 `hand_raw` 覆盖手牌。
  - 兼容特殊杠 body `00050104434343430343434300000000`，以及含财神替代的顺子 body `01010003375339015300000000`。
  - 保留尾部标记牌 raw 值，交给 tracker 进入备注。

- `stable/tracker.py`
  - snapshot 增加 `optional_actions`、`action_note`、`hand_incomplete_reason`、`marked_tiles`。
  - 敌方回合或无回合时阻断分析，返回等待原因，避免复用旧建议。
  - 副露汇总包只记录“不完整/等待可信手牌包”，不污染既有手牌。
  - 明杠升级已有碰时更新副露，不重复追加。

- `ui/stable_battle_panel.py`
  - 状态区增加备注展示。
  - blocked 等待态会刷新推荐区与候选分析，避免显示上轮旧建议。
  - 可显示 tracker 下发的可选动作、标记牌、手牌不完整原因。

- `game/llm_advisor.py`
  - 新增 `normalize_discard()`，支持 `5m`、`打5m`、`5万`、`五万`、描述文本中包含合法牌等格式。
  - LLM 推荐先归一化再校验；无法归一化时继续走程序候选 fallback。

## 验证结果

- `python -m unittest tests.test_stable_reader`：通过，39 tests。
- `python -m compileall stable game ui tests`：通过。
- 回放 `data/stable_reader/events_20260520_204016.jsonl`：
  - 20:51 特殊杠识别为 `kan_open`，不再因 `0x021F` body 未识别丢副露。
  - 20:52 副露汇总识别为 `meld_summary`，snapshot 显示“等待可信手牌包，忽略副露汇总包”。
  - 20:52 `current_turn=none` 时 blocked，显示“等待我方回合”。
  - 20:54 `current_turn=enemy` 时 blocked，显示“等待敌方出牌”。
- `gitnexus detect-changes --scope all -r mahjong-learning`：完成；因协议解析、tracker、UI/LLM 主链路变更，GitNexus 标记 risk level 为 `critical`。

## 注意

- 真实回放文件中的短 `action_notify` 多为 `ffff` 形态的心跳/定位类 body，本次解析没有把它们误判为可选动作；结构明确的 action notify 会输出 `optional_action`。
- 工作区存在本次任务外的 `.obsidian/workspace.json` 变更和已归档 change 删除/新增，未做处理。
