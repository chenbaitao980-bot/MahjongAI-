# BugFix Log: stable-response-action-details

## Bug Index

| bug_id | 现象 | 关联文件/函数 | bugfix_count | 当前状态 | 是否需沉淀 |
|---|---|---|---:|---|---|
| response-chi-details-missing | 可吃时策略建议不显示吃哪组，只显示动作类型 | `stable/simulator.py`, `game/stable_hard_analysis.py` | 1 | fixed | 否 |

## Bug Events

### response-chi-details-missing / 第 1 次修复
- 触发时间: 2026-05-22
- 用户现象: “轮到我可以吃了但是推荐动作没有显示吃哪些，要不要过。”
- 复现路径: 模拟对局中对方打 `5筒`，我方存在三种吃法。
- 触发条件: `optional_actions` 中有多个 `chi`，但 snapshot 未保留 `tiles` 明细。
- 失败验证: 策略建议只显示 `chi / chi / chi / pass` 或“建议吃”，没有组合。
- 本轮根因假设: 响应动作在 snapshot 层被降维。
- 最终根因: 模拟响应动作在 snapshot 层只保留类型，丢失吃牌组合明细；硬算只能按 `chi` 类型给泛化建议。
- 修复点: snapshot 新增 `optional_action_details`；硬算按具体吃牌组合逐个模拟并输出推荐组合。
- 验证结果: `python -m unittest tests.test_stable_simulator tests.test_stable_hard_analysis` 通过。
- 是否同一 bug: 是；当前为首次记录。
