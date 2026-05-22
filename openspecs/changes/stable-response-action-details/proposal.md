# stable-response-action-details

## 为什么
模拟响应动作弹框能显示多个具体吃法，例如“吃 3筒 4筒 5筒 / 吃 4筒 5筒 6筒 / 吃 5筒 6筒 7筒 / 过”，但右侧策略建议只显示 `chi / chi / chi / pass` 或“建议吃”，没有说明应该吃哪一组，也没有清楚说明是否建议过。

## 影响面
GitNexus impact:
- `analyze_snapshot`: HIGH。影响 UI `set_snapshot` / `set_advice`、模拟推荐、训练样本生成。
- `_response_advice`: HIGH。影响 UI、模拟推荐、训练样本。
- `StableSimulationGame.snapshot`: GitNexus 名称解析失败，但该方法由稳定版模拟 UI 直接调用；本次只追加字段，保持旧字段兼容。

## 业务规范关系
- 命中的主 spec: `stable-reader`
- 关系判断: Bug Against Spec / Same Requirement
- 推荐动作: 修改稳定版模拟响应 snapshot 和硬算响应建议文案，不修改胡牌/向听核心算法。

## 改动范围
- `stable/simulator.py`: snapshot 增加 `optional_action_details`，保留每个响应动作的 `type` / `tile` / `tiles` / `label`。
- `game/stable_hard_analysis.py`: 响应建议按具体吃牌组合逐个评估，输出推荐组合和过牌态度。
- `tests/test_stable_simulator.py` / `tests/test_stable_hard_analysis.py`: 增加多吃法响应明细回归测试。
- `regression-tests/cases/stable-response-action-details.md`: 记录本 change 回归用例。

## 验收
- [ ] 多个吃牌响应时，右侧建议显示具体组合，例如 `建议吃 3筒 4筒 5筒`。
- [ ] 右侧不得只显示 `chi / chi / chi / pass`。
- [ ] 若建议吃，理由中说明 `过为备选`；若吃后收益不明确，建议过。
- [ ] 原有 `optional_actions` 字段保持兼容。
- [ ] `python -m unittest tests.test_stable_simulator tests.test_stable_hard_analysis`
- [ ] `gitnexus detect-changes --scope all -r mahjong-learning`

## Bug 修复记录
| bug_id | 现象 | 首次发现时间 | bugfix_count | 当前状态 |
|---|---|---|---:|---|
| response-chi-details-missing | 可吃时策略建议不显示吃哪组，只显示动作类型 | 2026-05-22 | 1 | open |
