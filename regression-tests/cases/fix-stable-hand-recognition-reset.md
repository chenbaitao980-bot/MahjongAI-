# Regression Cases: fix-stable-hand-recognition-reset

## Batch Test Endpoint
- command_or_url: `python -m unittest tests.test_stable_reader`
- auth: none
- env: local pytest

## Cases
| case_id | 目标 | 入参摘要 | 期望出参关键字段 | 断言 | 来源 | 状态 |
|---|---|---|---|---|---|---|
| stable-first-hand-lock | 首个可信稳定版手牌包能识别初始手牌 | `hand_update player=0 hand_raw=13 stable source=trusted_hand`，tracker 默认 `local_player=1` | `local_player=0`; `players[0].hand` 有 13 张; `hand_trusted=True` | equals | bugfix/user | pass |
| stable-next-round-clear-untrusted-wait | 等待可信手牌状态下下一局可信包清空旧局 | 旧局有双方弃牌，随后本地 partial `hand_update` 使 `hand_trusted=False`，再收新 `trusted_hand` | `remaining_tiles=108`; 双方 `discards=[]`; 旧事件清空后只保留新手牌事件 | equals | bugfix/user | pass |
| stable-untrusted-deal-still-blocked | 0x0003 deal 候选手牌仍不作为权威手牌 | `deal source=untrusted_round_marker` | `players[local].hand=[]`; `analysis_blocked_reason` 仍为等待可信手牌 | equals | existing-regression | pass |

## Notes
- 只记录关键状态字段，不保存完整抓包或完整响应。
