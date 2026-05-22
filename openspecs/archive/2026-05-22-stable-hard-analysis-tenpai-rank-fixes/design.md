# 设计：stable-hard-analysis-tenpai-rank-fixes

## 当前状态
当前 `analyze_snapshot()` 使用 `current_shanten == 0` 直接设置 `is_ting = True`。这在 13 张响应态或摸前态是合理的，但在 14 张出牌态不完整：14 张必须先打出一张，只有“存在至少一个打出后 13 张仍为听牌”的候选，才应展示为当前听牌。

截图复现结果：
```text
current_shanten = 0
ting_tiles = []
所有 discard candidate 的 shanten_after = 1
recommended = 2筒/7筒（取决于可见牌危险度）
strong_reminders = 当前推荐会导致向听变差；已听牌，避免选择退听打法
```

根因不是 `calc_shanten` 一定算错，而是调用层把 14 张出牌态的 shanten 和 13 张弃牌后 shanten 直接比较，导致：
- 听牌状态口径错。
- `shanten_delta = shanten_after - current_shanten` 错把所有合法出牌标为退听。
- 强提醒和推荐之间出现自相矛盾。

## 方案
1. 增加“出牌态听牌”口径：
   - `effective_count % 3 == 1`: 直接用 `get_ting_tiles(hand)` 判断当前 13 张是否听牌。
   - `effective_count % 3 == 2`: 只有存在 `candidate.shanten_after == 0` 且 `candidate.ting_tiles` 非空时，才算“打后听牌”。
2. 修正候选 `shanten_delta`：
   - 14 张出牌态不再用 `current_shanten` 直接和 `shanten_after` 比较。
   - 若所有候选都为 `shanten_after == 1`，它们之间不应都显示“退听惩罚”；应按整理价值排序。
3. 调整强提醒：
   - 只有真实打后听牌状态下，才提示“已听牌，避免退听打法”。
   - 若没有任何保听候选，不应把最终推荐描述成“违规退听”。
4. 加入搭子/孤张质量特征：
   - 优先整理边张、孤张、低质量坎张。
   - 保留两面和高价值复合搭子。
   - 该特征只用于同向听级别候选之间拉开分差，不压过向听数和财神硬约束。

## 业务规则处理
- 原 Requirement / Scenario: 稳定版右侧策略建议、硬算推荐、模拟对局推荐。
- 本次处理方式: Bug Against Spec，修改同一硬算能力。
- 不新增独立业务能力；不改胡牌核心算法。

## 历史 BugFixSpecs 命中
未发现 `openspecs/bugfixspecs` 目录或命中文件。

## Bug 根因分析
- 用户可见现象: 向听 0、听牌是、听牌列表空；推荐和强提醒互相打架。
- 真实失败层: 硬算状态解释层 / 候选排序层。
- 根本原因: 14 张出牌态的当前 shanten 被当成听牌状态，并和打出后的 13 张 shanten 直接比较。
- 不是根因: `calc_shanten` 本身的基础返回值；本 change 先不改它。
- 防复发检查项: 截图类 14 张出牌态必须有测试，断言 `is_ting == False` 或至少不出现空听牌列表却显示听牌。

## 回归测试方案
- 用例文件: `regression-tests/cases/stable-hard-analysis-tenpai-rank-fixes.md`
- 命令: `python -m unittest tests.test_stable_hard_analysis`
- 入参来源: 截图局面手牌、财神西、当前我方出牌态。
- 期望出参: 不显示空听牌列表的“听牌是”；最终推荐理由不和强提醒冲突；边张/低质量搭子候选排序合理。

## 回滚方案
还原 `game/stable_hard_analysis.py` 和 `game/stable_strategy_model.py` 本 change 修改；删除新增测试用例。
