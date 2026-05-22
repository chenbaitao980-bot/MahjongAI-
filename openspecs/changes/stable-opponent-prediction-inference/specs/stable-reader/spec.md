# Delta: stable-opponent-prediction-inference

## 与主规范关系

Same Requirement / 追加 Scenario

## 命中的主规范

- Capability: `stable-reader`
- Requirement: `分析门控`
- Scenario: 稳定版策略分析展示

## 变更类型

MODIFIED / 追加 Scenario

## 业务冲突检查

| 维度 | 状态 |
|------|------|
| 主规范 Req 命中 | `stable-reader` 分析门控和策略分析展示 |
| 关系判断 | Same Requirement |
| 其他 active change 撞车 | 可能与 `stable-panel-layout-optimization`、`stable-simulation-hand-structure-panel` 同属 UI/策略面板区域；实施前需 GitNexus impact 和文件级检查 |
| 冲突状态 | 无业务冲突，存在潜在文件编辑重叠风险 |
| 是否允许 ADDED | 否，本次应扩展现有能力 |
| 归档完整性 | 待实施验证 |

## 原规则

稳定版读取器当且仅当满足财神已知、当前回合为我方、我方有效手牌数为 14 时触发策略分析。对面玩家的 `hand` 字段在 snapshot 出口始终为空或隐藏，不参与排序。

## 新规则

### Scenario: 对手预测使用公开信息

- WHEN 稳定版策略分析需要展示对手手牌预测
- THEN 系统 SHALL 只基于公开 snapshot 信息推断对手隐藏手牌、听牌范围和危险牌
- AND 系统 SHALL NOT 使用 `players[opponent]["hand"]` 中的真实隐藏手牌作为预测输入
- AND 模拟模式与抓包模式 SHALL 调用同一套对手预测入口

### Scenario: 贝叶斯网络推断听牌范围

- WHEN 对手预测配置启用贝叶斯网络
- THEN 系统 SHALL 融合弃牌、副露、动作、阶段、财神和粒子后验证据
- AND 输出对手听牌概率、向听分布、可能等待牌和危险牌概率
- AND 贝叶斯网络关闭时 SHALL 继续输出规则约束与粒子/MC 后验结果

### Scenario: 动态配置采样预算

- WHEN 用户在顶部控制条调整粒子数或蒙特卡洛次数
- THEN 系统 SHALL 使用新的配置执行后续对手预测
- AND 用户点击重新预测时 SHALL 用当前 snapshot 和当前配置刷新预测结果
- AND 长耗时推断 SHALL NOT 阻塞 UI 主线程

### Scenario: 动态分析按证据价值触发

- WHEN 用户启用对手预测且启用动态分析
- THEN 系统 SHALL 先根据公开信息判断当前局面是否具备概率分析价值
- AND 当证据不足时 SHALL NOT 启动粒子/MC/贝叶斯计算
- AND 预测区域 SHALL 展示跳过原因和证据评分
- AND 当动态分析关闭时 SHALL 只依据对手预测开关决定是否计算

### Scenario: 红框预测区域展示结构化结果

- WHEN 对手预测结果可用
- THEN 策略面板 SHALL 在对手手牌预测区域展示可信度、样本数、MC 次数、贝叶斯状态、听牌概率、向听分布、高概率持有牌、可能等待牌、危险牌排行和代表组合
- AND 代表组合 SHALL 标注为概率样本，不得暗示为确定手牌

## 改动明细

- 文件：`game/stable_hard_analysis.py`
  - 位置：`analyze_snapshot`
  - 改前：仅返回启发式对手预测文字
  - 改后：接入结构化 `OpponentPrediction`
- 文件：`ui/stable_battle_panel.py`
  - 位置：顶部控制条、策略建议区域
  - 改前：无动态粒子/MC 配置，无独立对手预测区域
  - 改后：新增配置控件和对手预测渲染
- 文件：`stable/simulator.py`
  - 位置：`snapshot`
  - 改前：对手 `hand` 已隐藏，但真实手牌在模拟对象内存在
  - 改后：预测入口不得读取模拟真实手牌，仅使用公开 snapshot
- 文件：`config/settings.yaml`
  - 位置：`stable_reader`
  - 改前：无对手预测采样预算配置
  - 改后：新增对手预测开关、粒子数、MC 次数、贝叶斯开关等配置
