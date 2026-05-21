# 任务：stable-reader-response-hu-mapping-fixes

## 实施

- [ ] 1. 定位 `data/stable_reader/events_20260521_185429.jsonl` 中 19:03:33、19:04:57、19:05:24-19:05:29 的 raw_key / snapshot 状态。
- [ ] 2. 修复可选动作响应建议：`optional_actions` 非空时输出吃/碰/杠/胡/过建议，且胡优先。
- [ ] 3. 修复九万、白未识别：按实际 raw_key 补映射或修正事件 context。
- [ ] 4. 修复胡牌优先级：已胡/可胡时清空出牌推荐并覆盖 UI 旧建议。
- [ ] 5. 补 `tests/test_stable_reader.py` 与 `tests/test_stable_hard_analysis.py` 回归。

## 验证

- [ ] `python -m unittest tests.test_stable_reader tests.test_stable_hard_analysis`
- [ ] 回放 `data/stable_reader/events_20260521_185429.jsonl` 检查 19:03:33、19:04:57、19:05:24-19:05:29。
- [ ] `python -m compileall stable game ui tests`
- [ ] `gitnexus detect-changes --scope all -r mahjong-learning`
