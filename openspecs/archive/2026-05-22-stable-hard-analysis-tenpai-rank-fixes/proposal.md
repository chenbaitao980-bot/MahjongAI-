# stable-hard-analysis-tenpai-rank-fixes

## 为什么
截图局面暴露出稳定版硬算的三个一致性问题：
1. 14 张出牌态下 `current_shanten == 0` 被直接显示为“听牌是”，但听牌列表为空。
2. 推荐文案显示“建议打 2筒”，原因和强提醒却同时说“退听惩罚 / 避免退听”。
3. 候选排序主要看向听、进张、危险度，没有把边张、坎张、两面等搭子质量充分拉开，导致边张/孤张优先级不稳定。

## 影响面
GitNexus impact:
- `analyze_snapshot`: HIGH。影响 UI `set_snapshot` / `set_advice`、模拟推荐、训练样本生成。
- `_discard_candidates`: HIGH。影响候选生成、推荐排序、UI 和训练样本。
- `_choose_recommendation`: HIGH。影响 UI、模拟推荐、训练样本。
- `_strong_reminders`: HIGH。影响 UI、模拟推荐、训练样本。
- `rank_discard_candidates`: HIGH。影响 UI、模拟推荐、训练样本。
- `score_discard_candidate`: LOW。只被 `rank_discard_candidates` 直接调用。
- `get_ting_tiles`: LOW。只在硬算内部和兼容包装中使用。

因上述 HIGH 风险，本 change 必须用回归测试覆盖截图类 14 张出牌态，避免修完一个文案却把推荐链路改乱。

## 业务规范关系
- 命中的主 spec: `stable-reader`
- 关系判断: Bug Against Spec / Same Requirement
- 推荐动作: 修改硬算听牌状态、候选理由和搭子质量排序，不修改 `calc_shanten` 核心胡牌/向听算法。

## 改动范围
- `game/stable_hard_analysis.py`: 修正 14 张出牌态的听牌状态定义、强提醒和候选理由。
- `game/stable_strategy_model.py`: 给搭子质量/孤张质量加入评分特征，拉开边张、坎张、两面、孤张的候选分差。
- `tests/test_stable_hard_analysis.py`: 增加截图类局面的回归测试。
- `regression-tests/cases/stable-hard-analysis-tenpai-rank-fixes.md`: 记录本 change 回归用例。

## 验收
- [x] 14 张出牌态只有 `current_shanten == 0` 但没有任何打出后听牌候选时，不显示“听牌是”。
- [x] 推荐候选不得同时被标记为“退听惩罚”且作为最终推荐，除非所有候选都退听且文案明确是“被迫整理/退向听”。
- [x] 截图类局面中，候选排序能优先识别边张/孤张整理价值；至少不再因“听牌态”误判触发退听强提醒。
- [x] 不修改 `calc_shanten`。
- [x] `python -m unittest tests.test_stable_hard_analysis`
- [x] `gitnexus detect-changes --scope all -r mahjong-learning`

## Bug 修复记录
| bug_id | 现象 | 首次发现时间 | bugfix_count | 当前状态 |
|---|---|---|---:|---|
| tenpai-state-rank-conflict | 14 张出牌态显示听牌但听牌列表空，并推荐退听候选 | 2026-05-22 | 1 | open |

## Bug 触发历史
- 第 1 次：用户截图显示当前向听 0、是否听牌是、听牌列表空，同时推荐“打 2筒”，强提醒/原因却说退听危险。
