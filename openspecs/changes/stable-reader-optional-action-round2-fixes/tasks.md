# 任务：stable-reader-optional-action-round2-fixes

## 实施

- [x] 1. 在 `stable/protocol.py` 中解码 `action_notify` 为可选动作事件，并保留无法确认结构的 raw evidence。
- [x] 2. 区分可信全量手牌包和副露/桌面汇总型 `0x0216`，避免小 count 汇总包覆盖我方手牌。
- [x] 3. 修正特殊杠与含财神替代副露解析，覆盖 20:51:06 和 20:53:49 的 body。
- [x] 4. 在 `stable/tracker.py` 维护可选动作、手牌完整性、标记牌和敌方回合等待状态。
- [x] 5. 在 `ui/stable_battle_panel.py` 展示可选动作、等待敌方出牌、标记牌备注，并清空过期候选分析。
- [x] 6. 在 `game/llm_advisor.py` 归一化 LLM 出牌字段，非法输出时稳定回退程序建议。

## 验证

- [x] `python -m unittest tests.test_stable_reader`
- [x] 回放 `data/stable_reader/events_20260520_204016.jsonl`，检查 20:46、20:51、20:52、20:54 场景。
- [x] `python -m compileall stable game ui tests`
- [x] `gitnexus detect-changes --scope all -r mahjong-learning`
