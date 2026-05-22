# Regression Cases: ui-layout-refactor

## Batch Test Endpoint
- command_or_url: 手动启动应用验证
- auth: 无
- env: 本地开发环境

## Cases
| case_id | 目标 | 入参摘要 | 期望出参关键字段 | 断言 | 来源 | 状态 |
|---|---|---|---|---|---|---|
| layout-1 | 顶部工具栏分组 | 启动应用，进入稳定版标签 | 看到 开始读取/停止/模拟出牌/AI/记录+训练/预测/重新预测 按钮 | 按钮数量=7 | user | pending |
| layout-2 | AI 弹框功能 | 点击 AI 按钮 | 弹出对话框，含开启AI分析/Provider/模型输入 | 弹框显示正常 | user | pending |
| layout-3 | 记录+训练弹框功能 | 点击 记录+训练 按钮 | 弹出对话框，含记录本局/加入训练复选框 | 弹框显示正常 | user | pending |
| layout-4 | 预测弹框功能 | 点击 预测 按钮 | 弹出对话框，含对手预测/动态分析/粒子/MC/贝叶斯 | 弹框显示正常 | user | pending |
| layout-5 | 对手预测三列展示 | 触发对手预测渲染 | 危险牌/高概率持有/可能等待 三列并排 | 无需滚动即可看到全部 | user | pending |
| layout-6 | 策略分析三列展示 | 触发策略分析渲染 | 状态/建议/候选重排 三列并排 | 三列均可见 | user | pending |

## Notes
- 纯 UI 变更，以视觉验证为主
- 抓包选择已移除，默认 npcap
