# BugFix Log: stable-opponent-prediction-inference

## Bug Index

| bug_id | 现象 | 关联文件/函数 | bugfix_count | 当前状态 | 是否需沉淀 |
|---|---|---|---:|---|---|
| opponent-probability-display-confusing | 对手预测概率展示出现 0%，危险牌含义不清，代表样本业务价值低，字体偏大 | `ui/stable_battle_panel.py::_format_opponent_prediction_html` | 1 | fixed | 否 |

## Bug Events

### opponent-probability-display-confusing / 第 1 次修复

- 触发时间：2026-05-22
- 用户现象：可能等待显示 0%，危险牌含义不清，代表样本不需要，顶部按钮和预测区字体偏大，希望概率表格化并按高到低排序。
- 复现路径：打开稳定版模拟或抓包面板，查看“对手手牌预测”区域。
- 触发条件：概率用整数百分比四舍五入，低于 0.5% 的后验概率被显示成 0%；危险牌标题没有说明是对我方危险；代表样本被直接展示。
- 本轮根因假设：展示层精度和文案不适合业务决策。
- 最终根因：概率展示过度压缩且缺少语义说明。
- 修复点：`ui/stable_battle_panel.py`、`game/opponent_inference.py`
- 验证结果：待本轮测试。
- 是否同一 bug：是。
