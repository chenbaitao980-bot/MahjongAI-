# 任务：stable-response-action-details

## 实施
- [x] 1. 在模拟 snapshot 中新增 `optional_action_details`，保持 `optional_actions` 兼容。
- [x] 2. 让硬算响应建议读取具体吃牌组合并逐个评估。
- [x] 3. 调整响应建议文案，显示“建议吃 <组合>；过为备选”或“建议过”。
- [x] 4. 增加模拟 snapshot 和硬算响应建议回归测试。

## 验证
- [x] 历史 BugFixSpecs 命中的防复发检查项已执行或确认无命中。
- [x] bugfix_count 已按本轮触发情况更新。
- [x] 已维护本 change 的回归测试用例。
- [x] `python -m unittest tests.test_stable_simulator tests.test_stable_hard_analysis`
- [x] `gitnexus detect-changes --scope all -r mahjong-learning`（已执行；当前工作区含既有 unrelated 变更，整体风险为 critical）
