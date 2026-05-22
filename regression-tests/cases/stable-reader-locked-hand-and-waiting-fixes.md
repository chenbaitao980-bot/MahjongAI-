# Regression Cases: stable-reader-locked-hand-and-waiting-fixes

## Batch Test Endpoint
- command_or_url: `python -m unittest tests.test_stable_hard_analysis tests.test_stable_reader`
- auth: none
- env: local

## Cases
| case_id | 目标 | 入参摘要 | 期望出参关键字段 | 断言 | 来源 | 状态 |
|---|---|---|---|---|---|---|
| locked-hand-legal-discard | 锁手后不推荐不可点击原手牌 | 14 张手牌 + 锁手合法集合仅含新摸牌 | `recommended_discard in legal_discards`; `candidates` 不含非法牌 | equals/contains | user/spec | pass |
| same-tile-draw-not-echo | 同牌摸牌不被回声去重吞掉 | 对面 discard 南后我方 draw 南 | local hand 增加 `2z`; effective count 正确 | contains/count | user/log | pass |
| empty-ai-response-recovers | DeepSeek 空响应不永久等待 | AI response text 为空且无 error | fallback 来源或明确错误；busy/pending 清理 | contains/status | user/log | pass |
| new-round-clears-waiting | 下一把不继承上一局等待态 | 旧局空响应后收到新可信 hand_update | 新 snapshot 重新门控；旧 pending 清空 | status | user | pass |

## Notes
- 12:44:18 证据来自 `data/stable_reader/events_20260522_124321.jsonl`：对面 `discard tile_raw=66` 后我方 `draw tile_raw=66`。
- 12:51 证据来自 `data/requestdeepseek/20260522_125144_758695.json`、`20260522_125148_660331.json`、`20260522_125152_546166.json`：`response_text` 和 `error_message` 均为空。
