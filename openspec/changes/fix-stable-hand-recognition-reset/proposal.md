# fix-stable-hand-recognition-reset

## 为什么
用户反馈稳定版存在两个相关问题：

- 初始手牌无法识别出来。
- 等待下一局时，上一局手牌/可见状态无法清空，导致继续显示旧局状态并影响后续识别。

当前定位到稳定版抓包状态机 `PacketStateTracker` 的可信手牌包处理、新局判定与本地玩家锁定逻辑需要修复。

## 影响面
GitNexus impact 结果：

- `_apply_game_event`：HIGH 风险；直接调用者 `apply`，影响 `rebuild_from_history`、`scripts/replay_stable_reader.py`、`stable/training_data.py`、`scripts/export_training_samples.py`，并影响稳定版读包测试。
- `_is_new_round_hand_update`：HIGH 风险；由 `_apply_game_event` 调用，影响 `apply`、`rebuild_from_history`、稳定版回放与训练样本导出流程。

风险说明：这是稳定版状态机核心路径，任何修改都可能影响实时抓包、历史回放、训练样本导出和 UI 展示。

## 业务规范关系
- 命中的主 spec：无明确稳定版手牌识别主 spec。
- 关系判断：Bug Against Spec / Spec Gap。
- 推荐动作：新增本 change 的 delta spec，不改变业务目标，只修复稳定版状态机行为。

## 改动范围
- `stable/tracker.py`
  - `PacketStateTracker._maybe_lock_local_player`
  - `PacketStateTracker._is_new_round_hand_update`
  - 必要时调整 `PacketStateTracker._apply_game_event` 中 `hand_update` 分支。
- `tests/test_stable_reader.py`
  - 增加初始可信手牌包识别回归用例。
  - 增加上一局未可信/等待可信手牌时，新一局可信手牌包应清空旧状态的回归用例。
- `regression-tests/cases/fix-stable-hand-recognition-reset.md`

## 验收
- [ ] 稳定版首个可信 `hand_update` 能锁定本地玩家并填充我方手牌。
- [ ] 新一局可信 `hand_update` 到达时，即使上一局处于等待可信手牌状态，也能清空旧局弃牌、副露、事件与回合状态。
- [ ] 不重新启用 0x0003 untrusted deal 作为权威手牌。
- [ ] 已维护 `regression-tests/cases/fix-stable-hand-recognition-reset.md`。
- [x] 相关 `tests/test_stable_reader.py` 用例通过。
- [x] `gitnexus detect-changes --scope all -r mahjong-learning` 无异常范围外变更。

## Bug 修复记录
| bug_id | 现象 | 首次发现时间 | bugfix_count | 当前状态 |
|---|---|---|---:|---|
| stable-initial-hand-not-recognized | 稳定版初始手牌无法识别出来 | 2026-05-22 | 1 | open |
| stable-next-round-not-cleared | 等待下一局时旧手牌/状态无法清空 | 2026-05-22 | 1 | open |

## Bug 触发历史
- 第 1 次：用户反馈稳定版初始手牌无法识别、等待下一局手牌无法清空；定位到 `PacketStateTracker` 的可信手牌包状态迁移和新局判定。
