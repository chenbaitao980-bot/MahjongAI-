# Regression Cases: stable-opponent-prediction-inference

## Batch Test Endpoint

- command_or_url: `python -m pytest tests/test_stable_hard_analysis.py`
- auth: none
- env: local

## Cases

| case_id | 目标 | 入参摘要 | 期望出参关键字段 | 断言 | 来源 | 状态 |
|---|---|---|---|---|---|---|
| opponent-visible-estimate | 对手预测返回结构化后验 | 对手有弃牌、副露、隐藏手牌为空 | `opponent_prediction.enabled=true`、`sampled_count>0` | unittest assertions | spec | pass |
| opponent-hidden-isolation | 模拟真实对手手牌不参与展示预测 | 两个 snapshot 公开信息相同，一个额外带 opponent hand | tile probabilities 与 summary 相同 | unittest assertions | spec | pass |
| opponent-config-switches | 顶部配置进入推断入口 | enabled false / bayes false / particle 300 / MC 100 | 开关和次数按配置返回 | unittest assertions | spec | pass |
| opponent-probability-display | 概率展示可读 | 对手预测有低概率等待/危险牌 | 非零小概率不显示为 `0%`，危险牌在顶部，代表样本不展示 | py_compile / code review | user | pass |
| opponent-dynamic-gate | 动态分析节省性能 | 早期局面、对手弃牌少、无副露 | 不启动预测线程，显示证据不足评分 | py_compile / code review | user | pass |

## Notes

- 只记录公开 snapshot 摘要，不保存完整抓包体。
- 模拟模式真实对手手牌仅用于隔离测试，不允许作为预测输入。
