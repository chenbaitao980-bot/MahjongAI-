# 交付说明：stable-reader-locked-hand-and-waiting-fixes

## 修复内容
- 听牌/锁手推荐：稳定版硬规则分析在已知本轮新摸牌且当前为听牌状态时，只从新摸牌生成出牌候选，避免推荐原手牌中无法点击的牌。
- 少识别南：收紧弃牌回声消费逻辑，只消费我方弃牌后的同牌回声，不再把“对面打南后我方摸南”误判为回声并吞掉。
- 杠后一直等待：LLM 返回空内容时降级为程序推荐，并在结果中标注空响应 fallback，避免 UI 卡在等待数据。
- 新局清理：牌局重置和稳定版 tracker 快照会清空新摸牌状态，避免上一局锁手上下文带入下一局。

## 验证
- `python -m unittest tests.test_stable_hard_analysis tests.test_stable_reader tests.test_ai_fallbacks`
- `python -m unittest tests.test_stable_simulator tests.test_training_data_export`
- `python -m unittest discover tests`
- `npx gitnexus detect-changes --scope all -r mahjong-learning`

## GitNexus 影响面
- 变更检测结果：7 files, 27 symbols, 54 affected processes。
- 风险等级：critical。
- 主要原因：本次修改触达 `BattleState._compute_analysis`、`stable.tracker.PacketStateTracker`、`game.stable_hard_analysis.analyze_snapshot`、`game.llm_advisor.get_final_advice` 等稳定版实时分析主链路符号。
- 缓解方式：补充了锁手候选、同牌摸牌、AI 空响应 fallback 的定向单测，并执行全量 `unittest discover tests` 通过。
