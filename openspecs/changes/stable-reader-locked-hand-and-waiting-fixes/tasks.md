# 任务：stable-reader-locked-hand-and-waiting-fixes

## 实施
- [x] 1. 在 `game/stable_hard_analysis.py` 为推荐候选接入合法出牌集合，锁手时不从整手牌推荐。
- [x] 2. 在 `stable/tracker.py` 收紧弃牌回声消费，覆盖“对面打南后我方摸南”不误吞。
- [x] 3. 在 AI 分析结果处理链路中为空响应增加本地 fallback 或明确失败状态。
- [x] 4. 在稳定版 UI 状态链路中确保分析失败、空响应、新局切换会清理 busy/pending 等待态。
- [x] 5. 补充/更新相关单元测试。
- [x] 6. 维护 `regression-tests/cases/stable-reader-locked-hand-and-waiting-fixes.md`。

## 验证
- [x] 历史 BugFixSpecs 命中的防复发检查项已执行或确认无命中。
- [x] bugfix_count 已按本轮触发情况更新。
- [x] 已维护本 change 的回归测试用例。
- [x] `python -m unittest tests.test_stable_hard_analysis tests.test_stable_reader`
- [x] 如涉及 AI 空响应测试，执行对应服务/LLM 单测。
- [x] `gitnexus detect-changes --scope all -r mahjong-learning`
