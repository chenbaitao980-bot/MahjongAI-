# Delta: stable-response-action-details

## 与主规范关系
Bug Against Spec / Same Requirement

## 命中的主规范
- Capability: `stable-reader`
- Requirement: 模拟吃碰杠胡事件、策略建议区域
- Scenario: 模拟吃牌、响应建议

## 变更类型
MODIFIED

## 业务冲突检查
| 维度 | 状态 |
|------|------|
| 主规范 Req 命中 | `stable-reader` |
| 关系判断 | Bug Against Spec |
| 其他 active change 撞车 | `stable-simulation-hand-structure-panel` 只做右侧手牌结构展示，不冲突。 |
| 冲突状态 | 无冲突 |
| 是否允许 ADDED | 否；修改现有响应建议能力 |
| 归档完整性 | 是 |

## 原规则
模拟模式 SHALL 支持基础吃、碰、杠、胡事件，并将副露和胡牌结果写入与稳定版 snapshot 兼容的数据结构。

## 新规则
### Scenario: 多个吃牌响应说明
- WHEN 我方可对对方弃牌执行多个吃牌响应
- THEN 稳定版 snapshot SHALL 保留每个响应动作的具体组合明细
- AND 策略建议 SHALL 显示推荐吃哪一组具体牌
- AND 策略建议 SHALL NOT 只显示 `chi / chi / chi / pass`
- AND 若建议吃，策略建议 SHALL 说明 `过` 为备选；若吃牌收益不明确，SHALL 建议过

## 改动明细
- 文件: `stable/simulator.py`
- 位置: `StableSimulationGame.snapshot()`
- 改前: 只输出 `optional_actions` 动作类型列表。
- 改后: 额外输出 `optional_action_details`，保留响应组合。

- 文件: `game/stable_hard_analysis.py`
- 位置: `_response_advice()` / `_simulate_response_shanten()`
- 改前: 只按动作类型评估，吃牌只取默认第一组。
- 改后: 按每个吃牌组合分别评估并输出具体组合。
