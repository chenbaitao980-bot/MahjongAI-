# Regression Cases: stable-simulation-hand-structure-panel

## Batch Test Endpoint
- command_or_url: `python -m unittest tests.test_stable_simulator`
- auth: none
- env: local

## Cases
| case_id | 目标 | 入参摘要 | 期望出参关键字段 | 断言 | 来源 | 状态 |
|---|---|---|---|---|---|---|
| sim-response-hu-source | 响应胡牌来源说明 | 我方 13 张，设定对方弃 `2p` 可胡 | `optional_actions` 含 `hu`; `action_tile=2p`; `action_source=opponent_discard` | equals/contains | user | pass |
| hand-structure-groups | 手牌结构分组 | `111m 234m 55p 78p 9s` | 包含刻子、顺子、将牌候选、搭子、孤张 | contains | user | pass |
| hand-structure-multiple-arrangements | 手牌结构多组合与推荐弃牌排序 | 同一手牌存在 `2s`/`5s` 均可作为孤张，推荐弃牌 `2s` | 返回多种组合；第一种组合中 `2s` 处于孤张或低质量搭子 | order/contains | user | pass |

## Notes
- 分组仅用于 UI 解释，不参与胡牌、向听或推荐排序。
