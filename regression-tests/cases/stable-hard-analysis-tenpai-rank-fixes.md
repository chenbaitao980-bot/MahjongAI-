# Regression Cases: stable-hard-analysis-tenpai-rank-fixes

## Batch Test Endpoint
- command_or_url: `python -m unittest tests.test_stable_hard_analysis`
- auth: none
- env: local

## Cases
| case_id | 目标 | 入参摘要 | 期望出参关键字段 | 断言 | 来源 | 状态 |
|---|---|---|---|---|---|---|
| screenshot-14-tile-tenpai-state | 14 张出牌态听牌口径 | 财神西；手牌含 `2p 3p 5p 7p 1s 2s 456s 77s 567p` | `ting_tiles=[]` 时 `is_ting=False`；不出现退听强提醒冲突 | equals/not contains | user | pass |
| taatsu-quality-ranking | 搭子质量排序 | 同向听候选包含边张、坎张、两面 | 低质量搭子/孤张整理优先；不压过向听和财神 | order/contains | user | pass |
| one-pin-over-four-pin | 边张整理优先级 | 财神 `2m`；副露中中中；手牌 `2m 8m8m 3s3s4s 1p3p4p6p6p` | 推荐 `1p`；候选排序中 `1p` 位于 `4p` 前 | order/equals | user | pass |

## Notes
- 禁止把完整响应或长日志粘贴进用例；只保留关键字段。
