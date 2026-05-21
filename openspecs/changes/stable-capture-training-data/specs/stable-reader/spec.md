# Delta: stable-capture-training-data

## 与主规范关系

补充 `stable-reader` 的数据闭环要求。无冲突：现有稳定读取器继续负责抓包、解码、回放、UI 驱动；本规划只约束后续训练数据导出必须复用同一可信数据源。

## 变更摘要

| 维度 | 状态 |
| --- | --- |
| 主规范 Req 命中 | `协议解码`、`分析门控`、`回放兼容` |
| 其他 active change 撞车 | `stable-reader-hard-analysis-panel` 已使用同源 `snapshot()`，方向一致 |
| 归档完整性 | 待实现后校验 |

## ADDED Requirements

### 训练数据事实源

稳定抓包训练数据导出 MUST 只使用结构化事件回放后的 `PacketStateTracker.snapshot()` 和同源事件元数据，不得使用 AI/LLM 文案、UI 文案或人工推断文本作为事实源。

#### Scenario: 可信 snapshot 导出样本

- WHEN 回放 `events_*.jsonl` 得到可信 `snapshot()`
- AND `hand_trusted`、`baida_trusted`、`turn_trusted` 均为 true
- THEN 导出器 SHALL 生成包含局面、真实动作、可见信息、向听和有效进张的训练样本

#### Scenario: 数据不足阻断样本

- WHEN 手牌不可信、财神不可信、回合不可信或存在未知映射
- THEN 导出器 SHALL 记录阻断原因
- AND SHALL NOT 为该局面生成可训练动作标签

### 监督学习候选约束

监督学习模型 MUST 只重排硬算模块给出的合法候选，不得生成硬算模块不存在的出牌或响应动作。

#### Scenario: 模型只重排候选

- WHEN 硬算模块返回候选列表
- AND 监督模型给出排序分
- THEN 最终推荐 SHALL 从原候选列表中选择
- AND SHALL preserve 数据不足时不推荐的门槛

### 自博弈前置条件

自博弈强化训练 MUST 在完整计分、包牌/不死包和终局责任归因可验证后启用。

#### Scenario: 计分未闭环

- WHEN 完整计分或包牌规则未通过回放测试
- THEN 自博弈训练 SHALL remain disabled
- AND 只能运行监督学习或离线评估流程
