# BugFix Log: fix-stable-hand-recognition-reset

## Bug Index

| bug_id | 现象 | 关联文件/函数 | bugfix_count | 当前状态 | 是否需沉淀 |
|---|---|---|---:|---|---|
| stable-initial-hand-not-recognized | 稳定版初始手牌无法识别出来 | `stable/tracker.py:PacketStateTracker` | 1 | fixed | 否 |
| stable-next-round-not-cleared | 等待下一局时旧手牌/状态无法清空 | `stable/tracker.py:_is_new_round_hand_update` | 1 | fixed | 否 |

## Bug Events

### stable-initial-hand-not-recognized / 第 1 次修复
- 触发时间：2026-05-22
- 用户现象：稳定版初始手牌无法识别出来。
- 复现路径：tracker 默认本地玩家与首个可信稳定版 `hand_update` 的玩家不一致时，首包需要接管本地玩家并填充手牌。
- 触发条件：`source=trusted_hand`、`hand_raw` 为 13/14 张、当前还没有可信手牌。
- 失败验证：缺少稳定版首个可信手牌包接管测试。
- 本轮根因假设：可信手牌包没有被明确作为当前局入口，状态仍可能停留在 `idle`。
- 最终根因：可信 `hand_update` 填充手牌后未保证 `phase=playing`，且本地玩家锁定只允许 `raw_len >= 13`，边界不够严格。
- 修复点：`PacketStateTracker._maybe_lock_local_player`、`PacketStateTracker._apply_game_event`。
- 验证结果：`python -m unittest tests.test_stable_reader` passed。
- 是否同一 bug：是；对应用户初始手牌识别失败。

### stable-next-round-not-cleared / 第 1 次修复
- 触发时间：2026-05-22
- 用户现象：等待下一局手牌无法清空，识别有问题。
- 复现路径：旧局已有弃牌/事件后，本地手牌变为不可信等待状态，再收到下一局可信手牌包。
- 触发条件：`hand_trusted=False` 且旧局有事件/弃牌等残留，新 `trusted_hand` 到达。
- 失败验证：新增 `test_new_round_hand_update_resets_old_state_even_when_waiting_for_trusted_hand` 初次失败，`phase` 仍为 `idle`。
- 本轮根因假设：新局判定要求上一局已经 `hand_trusted=True`，等待可信手牌状态下不会清空旧局。
- 最终根因：`_is_new_round_hand_update` 对 `hand_trusted=False` 直接返回，遗漏“旧局有残留但正在等待可信手牌”的新局入口。
- 修复点：`PacketStateTracker._is_new_round_hand_update`。
- 验证结果：`python -m unittest tests.test_stable_reader` passed。
- 是否同一 bug：是；对应用户下一局清空失败。
