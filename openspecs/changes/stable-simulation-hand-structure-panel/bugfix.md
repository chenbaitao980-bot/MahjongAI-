# BugFix Log: stable-simulation-hand-structure-panel

## Bug Index

| bug_id | 现象 | 关联文件/函数 | bugfix_count | 当前状态 | 是否需沉淀 |
|---|---|---|---:|---|---|
| hand-structure-single-arrangement | 手牌结构只显示一种贪心拆分；推荐打 `2条` 时，没有优先展示 `2条` 为孤张或劣势牌型。 | `stable/hand_structure.py::build_hand_structure_groups`, `ui/stable_battle_panel.py::_render_hand_structure` | 1 | open | 否 |

## Bug Events

### hand-structure-single-arrangement / 第 1 次修复
- 触发时间: 2026-05-22
- 用户现象: “五条可以是孤张，二条也可以是，手牌结构显示的时候应该把多种排列组合都展示出来；孤张二应该优先展示，因为推荐打掉孤张二。”
- 复现路径: 稳定版模拟对局右侧“手牌结构”面板展示当前手牌。
- 触发条件: 同一手牌存在多种合理拆分；当前推荐弃牌为其中一张可能处于孤张或低质量搭子的牌。
- 失败验证: UI 只展示单一贪心结构，未显示多种排列组合，也没有把推荐弃牌的劣势结构置前。
- 本轮根因假设: `build_hand_structure_groups()` 只返回一个贪心拆分结果，且 `_render_hand_structure()` 没有传入推荐弃牌用于展示排序。
- 最终根因: `build_hand_structure_groups()` 只返回一个顺子/对子/搭子优先的贪心拆分，UI 也没有把硬算推荐弃牌传入展示排序。
- 修复点: `stable/hand_structure.py`, `ui/stable_battle_panel.py`, `tests/test_stable_simulator.py`
- 验证结果: passed; `python -m unittest tests.test_stable_simulator` 和稳定版相关测试通过。
- 是否同一 bug: 是；属于手牌结构展示解释链路问题。
