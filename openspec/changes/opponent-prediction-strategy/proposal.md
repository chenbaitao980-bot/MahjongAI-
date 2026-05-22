# opponent-prediction-strategy

## 为什么
用户反馈：稳定版（stable/）已经实现了基于粒子滤波+贝叶斯推断的对手手牌预测（`game/opponent_inference.py`），能够输出对手听牌概率、危险牌列表、高概率持有牌、可能等待牌。但这些预测结果目前**仅用于UI展示**，完全没有流入出牌策略决策逻辑。用户要求将对手预测结果整合到出牌策略中，提高胜率；同时当策略建议受到对手预测影响时，文本描述需要用红色字体体现，放在红框位置（截图中的建议原因区域）。

## 影响面
- `game/stable_strategy_model.py`：核心改动，StrategyModelContext 增加 opponent_prediction 字段，score_discard_candidate 增加对手预测相关的评分维度
- `game/stable_hard_analysis.py`：将 opponent_prediction 传入 StrategyModelContext
- `ui/stable_battle_panel.py`：_format_strategy_analysis_html 中 advice_reason 增加红色高亮标记
- 不涉及：game/opponent_inference.py（已有功能，只读使用）
- 不涉及：game/shanten.py、game/ukeire.py、game/win.py 等底层计算

## 业务规范关系
- 命中的主 spec：无（策略增强，不涉业务规则变更）
- 关系判断：New Capability（策略模型增强）
- 推荐动作：不改 spec 只修代码

## 改动范围
1. `game/stable_strategy_model.py`：
   - StrategyModelContext 增加 `opponent_prediction: OpponentPrediction | None`
   - score_discard_candidate 增加对手预测评分项：
     - 对手听牌概率高时，提高 danger 权重
     - 如果候选牌在 opponent_prediction.danger_tiles 中，额外增加危险度
     - 如果候选牌在 opponent_prediction.wait_probabilities 中，额外扣分
   - _reasons 增加对手预测相关原因描述（红色标记）
2. `game/stable_hard_analysis.py`：
   - rank_discard_candidates 调用时传入 opponent_prediction
3. `ui/stable_battle_panel.py`：
   - _format_strategy_analysis_html 中，如果 advice_reason 包含对手预测相关文本，用红色字体

## 验收
- [ ] 对手预测开启时，出牌建议会考虑危险牌/听牌概率
- [ ] 建议原因中，受对手预测影响的部分用红色字体显示
- [ ] 对手预测关闭时，策略行为与之前完全一致
- [ ] 已维护 `regression-tests/cases/opponent-prediction-strategy.md`
- [ ] `gitnexus detect-changes` 无异常范围外变更
