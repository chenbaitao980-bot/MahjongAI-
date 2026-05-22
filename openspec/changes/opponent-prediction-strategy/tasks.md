# 任务：opponent-prediction-strategy

## 实施
- [x] 1. StrategyModelContext 增加 opponent_prediction 字段
- [x] 2. _danger_score 增加对手预测危险牌判断
- [x] 3. score_discard_candidate 增加对手听牌概率加权和危险牌惩罚
- [x] 4. _reasons 增加对手预测相关原因描述
- [x] 5. stable_hard_analysis.py 将 opponent_prediction 传入 StrategyModelContext
- [x] 6. _advice_reason 中标记对手预测相关原因
- [x] 7. UI _format_strategy_analysis_html 中红色高亮对手预测文本
- [x] 8. 候选重排增加对手预测扣分列
- [x] 9. 验证对手预测关闭时行为一致

## 验证
- [x] 历史 BugFixSpecs 命中的防复发检查项已执行或确认无命中
- [x] 已维护本 change 的回归测试用例
- [x] 对手预测开启时，危险牌评分降低
- [x] 建议原因中对手预测文本为红色
- [x] 候选重排中显示预测扣分（红色）
- [x] 对手预测关闭时，行为与修改前一致
- [x] `gitnexus detect-changes --scope all -r mahjong-learning`
- [x] bugfix_count 已更新（无新增bug）
- [x] 语法检查通过
