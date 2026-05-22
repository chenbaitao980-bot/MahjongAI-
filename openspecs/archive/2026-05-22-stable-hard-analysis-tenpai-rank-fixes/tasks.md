# 任务：stable-hard-analysis-tenpai-rank-fixes

## 实施
- [x] 1. 修正 14 张出牌态的 `is_ting` 与听牌列表口径。
- [x] 2. 修正候选 `shanten_delta` / 推荐理由，避免所有合法出牌都被误标为退听惩罚。
- [x] 3. 调整强提醒，仅在真实听牌退听冲突时提示。
- [x] 4. 增加同向听候选的搭子质量评分，拉开两面、坎张、边张、孤张分差。
- [x] 5. 增加截图类回归测试。

## 验证
- [x] 历史 BugFixSpecs 命中的防复发检查项已执行或确认无命中。
- [x] bugfix_count 已按本轮触发情况更新。
- [x] 已维护本 change 的回归测试用例。
- [x] `python -m unittest tests.test_stable_hard_analysis`
- [x] `gitnexus detect-changes --scope all -r mahjong-learning`（已执行；当前工作区含既有 unrelated 变更，整体风险为 critical）
