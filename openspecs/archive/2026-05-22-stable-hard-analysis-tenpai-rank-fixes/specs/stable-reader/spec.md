# Delta: stable-hard-analysis-tenpai-rank-fixes

## 与主规范关系
Bug Against Spec / Same Requirement

## 命中的主规范
- Capability: `stable-reader`
- Requirement: 稳定版硬算建议、策略建议区域可读性
- Scenario: 硬算推荐、候选重排、听牌列表展示

## 变更类型
MODIFIED

## 业务冲突检查
| 维度 | 状态 |
|------|------|
| 主规范 Req 命中 | `stable-reader` |
| 关系判断 | Bug Against Spec |
| 其他 active change 撞车 | `stable-reader-hard-analysis-panel` 处理硬算面板展示；本 change 修改硬算状态与排序口径。`stable-simulation-hand-structure-panel` 只做 UI 分组解释，不冲突。 |
| 冲突状态 | 无冲突 |
| 是否允许 ADDED | 否；修改现有硬算能力 |
| 归档完整性 | 是 |

## 原规则
稳定版硬算模块必须展示当前向听、听牌列表、最佳进听打法、候选重排、推荐理由和强提醒。

## 新规则
### Scenario: 14 张出牌态听牌判断
- WHEN 我方处于 14 张出牌态
- THEN `是否听牌` SHALL 基于“是否存在打出后仍听牌的候选”判断
- AND 系统 SHALL NOT 仅因当前 14 张 `current_shanten == 0` 就显示“听牌是”
- AND 若听牌列表为空，UI SHALL NOT 同时显示“是否听牌：是”

### Scenario: 推荐理由与强提醒一致
- WHEN 最终推荐候选被选中
- THEN 推荐理由 SHALL NOT 与强提醒形成直接矛盾
- AND 若所有候选都会让 13 张弃后向听升高，系统 SHALL 明确表达这是整理牌型而非“已听牌退听”

### Scenario: 搭子质量排序
- WHEN 多个候选的弃后向听相同
- THEN 候选重排 SHOULD 根据搭子质量拉开分差
- AND 两面搭子 SHOULD 优先保留于边张、坎张和孤张
- AND 财神硬约束和向听数优先级 SHALL 高于搭子质量偏好

## 改动明细
- 文件: `game/stable_hard_analysis.py`
- 位置: `analyze_snapshot()` / `_discard_candidates()` / `_strong_reminders()`
- 改前: 14 张 `current_shanten == 0` 直接视为听牌，候选统一出现退听惩罚。
- 改后: 14 张听牌由打出后状态决定；强提醒只针对真实保听/退听冲突。

- 文件: `game/stable_strategy_model.py`
- 位置: `score_discard_candidate()` / `rank_discard_candidates()`
- 改前: 同向听候选主要依赖进张、危险度和花色集中度。
- 改后: 同向听候选增加搭子质量/孤张整理价值。
