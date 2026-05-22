# stable-reader-locked-hand-and-waiting-fixes

## 为什么
2026-05-22 实战稳定版抓包中暴露三处同一链路缺口：

1. 已听牌/报听锁手后，游戏只允许打新摸牌，但推荐候选仍从整手牌生成，可能推荐用户无法点击的原手牌。
2. 12:44:18 对面刚打出南，随后我方真实摸到南；tracker 把同牌摸牌误判成弃牌回声，导致手牌少南。
3. 12:51:15 我方明杠九条后，12:51:44/48/52 的 DeepSeek 请求返回 `response_text=""` 且 `error_message=""`，界面仍保持等待态；进入下一把时也可能残留等待/忙碌状态。

## 影响面
- `_discard_candidates`: HIGH。直接影响 `analyze_snapshot`，间接影响稳定版面板、训练样本、模拟推荐。
- `_consume_discard_echo`: HIGH。直接影响 `PacketStateTracker._apply_game_event`，间接影响抓包回放、训练导出和 tracker 状态。
- `_on_stable_analysis_finished`: LOW。只影响稳定版分析完成后的 UI 状态。
- `LLMClient.chat_stream`: HIGH。影响 BattleService 的 AI 分析链路；本 change 优先在调用方/结果处理层补空响应保护，避免扩大网络客户端语义。

## 业务规范关系
- 命中的主 spec: `openspecs/specs/stable-reader/spec.md`
- 关系判断: Bug Against Spec / Same Requirement
- 处理方式: 追加 Scenario，不新增 capability。
- active change 撞车:
  - `stable-reader-optional-action-round2-fixes` 已覆盖可选动作、敌方回合等待、副露汇总包；本 change 只补锁手合法出牌、同牌摸牌回声误判、空 AI 响应等待态。
  - `stable-capture-training-data` 约束训练数据来源；本 change 会保持训练样本仍使用可信 snapshot。
  - `stable-panel-layout-optimization` 与 `stable-simulation-hand-structure-panel` 只涉及 UI 展示/布局，不改其目标。

## 改动范围
- `game/stable_hard_analysis.py`: 推荐候选支持合法出牌集合；听牌/锁手时只推荐新摸牌或明确给出等待/人工确认。
- `stable/tracker.py`: 收紧弃牌回声消费条件，避免真实同牌摸牌被吞；新局/可信手牌包重置等待状态。
- `battle/service.py` 或 `game/llm_advisor.py`: DeepSeek 空响应时回退本地程序建议或报可恢复失败，不让 UI 永久等待。
- `ui/main_window.py` / `ui/stable_battle_panel.py`: 分析空结果、失败、新局切换时清理 busy/pending，显示明确原因。
- `tests/test_stable_hard_analysis.py`: 覆盖锁手后合法推荐。
- `tests/test_stable_reader.py`: 覆盖 12:44:18 同牌摸牌不误吞、12:51 杠后状态不永久等待。
- 视情况补充 `tests/test_llm_advisor.py` 或现有服务测试，覆盖空 AI 响应回退。

## 验收
- [ ] 已听牌/报听锁手后，推荐牌必须属于当前可打集合；若只允许新摸牌，则不得推荐原手牌。
- [ ] 12:44:18 同一张南先由对面打出、再由我方摸到时，我方手牌必须增加南，不得被 `_consume_discard_echo` 吞掉。
- [ ] 12:51:15 明杠九条后补摸、出牌、下一把切换时，UI 不得永久显示“等待数据/等待 AI 返回”；空 DeepSeek 响应必须回退本地建议或显示明确错误。
- [ ] 已维护 `regression-tests/cases/stable-reader-locked-hand-and-waiting-fixes.md`。
- [ ] 相关单元测试通过。
- [ ] `gitnexus detect-changes --scope all -r mahjong-learning` 无异常范围外变更。

## Bug 修复记录
| bug_id | 现象 | 首次发现时间 | bugfix_count | 当前状态 |
|---|---|---|---:|---|
| locked-hand-illegal-recommendation | 已听牌/报听锁手后推荐无法点击的原手牌 | 2026-05-22 | 1 | open |
| same-tile-draw-swallowed-as-echo | 对面打南后我方摸南，手牌少南 | 2026-05-22 12:44:18 | 1 | open |
| kong-empty-ai-response-waiting | 明杠九条后空 AI 响应导致一直等待，下一把仍可能残留 | 2026-05-22 12:51:43 | 1 | open |

## Bug 触发历史
- 第 1 次：用户截图和描述指出报听/听牌锁手后只能打新摸牌，但推荐仍会让打不可打牌。
- 第 1 次：`data/stable_reader/events_20260522_124321.jsonl` 中 12:44:18 对面 `discard tile_raw=66` 后我方 `draw tile_raw=66`，`_consume_discard_echo` 仅凭同牌值消费。
- 第 1 次：`data/requestdeepseek/20260522_125144_758695.json`、`20260522_125148_660331.json`、`20260522_125152_546166.json` 中 `response_text` 与 `error_message` 均为空。
