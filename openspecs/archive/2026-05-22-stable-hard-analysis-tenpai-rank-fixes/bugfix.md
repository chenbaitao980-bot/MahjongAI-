# BugFix Log: stable-hard-analysis-tenpai-rank-fixes

## Bug Index

| bug_id | 现象 | 关联文件/函数 | bugfix_count | 当前状态 | 是否需沉淀 |
|---|---|---|---:|---|---|
| tenpai-state-rank-conflict | 14 张出牌态显示听牌但听牌列表空，推荐和退听强提醒冲突 | `game/stable_hard_analysis.py`, `game/stable_strategy_model.py` | 1 | fixed | 否 |

## Bug Events

### tenpai-state-rank-conflict / 第 1 次修复
- 触发时间: 2026-05-22
- 用户现象: “向听 0、听牌是，但听牌列表空；一边说退听危险，一边推荐退听；搭子质量权重不足。”
- 复现路径: 使用截图局面手牌、财神西、我方 14 张出牌态调用 `analyze_snapshot()`。
- 触发条件: 14 张出牌态 `current_shanten == 0`，但所有弃后候选 `shanten_after == 1`。
- 失败验证: `is_ting=True`、`ting_tiles=[]`、强提醒包含退听提示、最终推荐仍来自候选排序。
- 本轮根因假设: 14 张出牌态的 current shanten 和弃后 shanten 被直接比较，状态口径混淆。
- 最终根因: 14 张出牌态的 current shanten 和弃后 13 张 shanten 被直接比较，状态口径混淆；同向听候选缺少搭子质量特征。
- 修复点: `is_ting` 改由可见听牌列表/保听候选决定；14 张候选 delta 改为同批弃后最佳向听基准；同向听候选增加 shape_value。
- 验证结果: `python -m unittest tests.test_stable_hard_analysis` 通过。
- 是否同一 bug: 是；当前为首次记录。
