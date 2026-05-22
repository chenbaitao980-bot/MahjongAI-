# Regression Cases: stable-response-action-details

## Batch Test Endpoint
- command_or_url: `python -m unittest tests.test_stable_simulator tests.test_stable_hard_analysis`
- auth: none
- env: local

## Cases
| case_id | 目标 | 入参摘要 | 期望出参关键字段 | 断言 | 来源 | 状态 |
|---|---|---|---|---|---|---|
| simulator-response-details | snapshot 保留响应明细 | 对方弃 `5p`，我方可三种吃 | `optional_action_details` 包含 3 个 `chi` 且每个有 `tiles` | contains | user | pass |
| hard-analysis-chi-detail-advice | 硬算显示具体吃法 | snapshot 带 `optional_action_details` | `current_advice`/`advice_reason` 包含具体牌组；不只显示 `chi / chi / chi / pass` | contains/not contains | user | pass |

## Notes
- 只记录关键字段，不保存完整 UI 截图。
