# Delta: stable-reader-hard-analysis-panel

## 与主规范关系

无冲突。本变更补充 `stable-reader` 的 UI 分析展示要求：稳定版右侧面板必须优先展示可由当前抓包状态硬算出的数据，并在数据不足时显式说明可信度问题。

## 变更摘要

| 维度 | 状态 |
| --- | --- |
| 主规范 Req 命中 | 分析门控、稳定版 UI 展示、财神/手牌可信度 |
| 其他 active change 撞车 | `stable-reader-optional-action-round2-fixes` 已完成但未归档；本变更不修改协议解析，只复用其 snapshot 字段 |
| 归档完整性 | 待用户确认后归档 |

## MODIFIED Requirements

### 稳定版硬算面板

稳定版右侧面板必须展示由当前抓包状态硬算出的数据，不得依赖 AI 文案、MC 胜率或软策略判断作为主要展示内容。

#### Scenario: 使用同源 snapshot 计算

- WHEN 稳定版面板刷新 `snapshot`
- THEN 左侧实时数据和右侧硬算面板必须来自同一个 `snapshot`
- AND 右侧不得重新读取另一套手牌状态

#### Scenario: 展示硬算字段

- WHEN 数据足够计算
- THEN 右侧必须显示当前状态、财神、当前向听、是否听牌、听牌列表、最佳进听打法、有效进张、当前建议、建议原因、强提醒、财神风险、数据可信度

### 数据可信度

稳定版硬算面板必须在手牌、财神、当前事件或牌值映射不完整时显式提示数据不足，不得输出看似确定的出牌建议。

#### Scenario: 未拿到可信手牌

- WHEN `hand_trusted` 为 false
- THEN 当前状态显示“等待手牌”
- AND 当前建议显示“等待完整数据”
- AND 强提醒包含数据不足说明

#### Scenario: 未解析财神

- WHEN `baida_tile` 为空或 `baida_trusted` 为 false
- THEN 财神显示“等待财神”
- AND 当前建议显示“等待完整数据”

#### Scenario: 存在未知牌值

- WHEN `unknowns` 非空
- THEN 数据可信度显示未知牌值数量
- AND 当前建议不得作为确定建议

### 财神与听牌计算

硬算模块必须把财神作为 wildcard 参与胡牌/向听/听牌判断，不得把财神固定替换成某一张普通牌。

#### Scenario: 当前向听

- WHEN 我方手牌与财神可信
- THEN 系统使用 `calc_shanten()` 基于我方手牌、副露数量和财神数量计算当前向听

#### Scenario: 听牌列表

- WHEN 当前手牌已听或打出某牌后听牌
- THEN 系统调用 `getTingTiles()` 枚举所有可能进张
- AND UI 展示每张进张及剩余张数，例如 `3万x2 / 6万x3`

### 硬规则建议

当前建议必须来自候选出牌的硬算评分，不得引用 AI 自然语言判断。

#### Scenario: 未听牌推荐

- WHEN 当前可枚举 14 张有效手牌
- THEN 系统枚举每张可打牌
- AND 优先选择不打财神、打后向听最低、有效进张最多的牌
- AND 建议原因只包含进听、有效进张最多、不打财神、不退听等可验证原因

#### Scenario: 强提醒只显示硬错误

- WHEN 推荐或候选存在退听、打财神、漏听、吃碰后变差、向听变差等硬错误
- THEN 强提醒显示对应问题
- AND 没有硬错误时显示“无硬错误”

## 变更明细

- `game/stable_hard_analysis.py`：新增硬算模块与 `getTingTiles()`。
- `game/stable_strategy_model.py`：新增本地特征模型重排器，只接收硬算合法候选并输出分数、原因和特征。
- `ui/stable_battle_panel.py`：右侧面板改为硬算展示，AI 流式/返回不覆盖硬算结果。
- `tests/test_stable_hard_analysis.py`：新增硬算模块回归测试。

### 候选重排与同源展示

稳定版右侧策略建议必须使用当前 `PacketStateTracker.snapshot()` 生成的同一个 `StableHardAnalysis` 对象展示硬算结果、模型状态、推荐来源和候选重排，不得混用上一轮 `BattleState.last_analysis` 或大模型流式文本。

#### Scenario: 完整可信数据下输出模型重排
- WHEN 当前抓包状态包含可信手牌、可信财神、可信我方回合、无未知牌值、无可选动作且我方有效手牌数为 14
- THEN 系统必须先生成硬算合法候选
- AND 本地特征模型只允许对这些合法候选打分排序
- AND 右侧 UI 必须展示推荐牌、模型状态、推荐来源、候选分数和候选原因

#### Scenario: 数据不足时不输出候选
- WHEN 当前抓包状态缺可信手牌、财神、回合、14 张有效牌，或存在未知牌值、敌方回合、可选动作
- THEN 系统不得输出出牌候选或推荐出牌
- AND 右侧 UI 必须显示等待原因和“暂无候选”

### 对方预测展示

稳定版右侧硬算面板应展示基于可见信息的对方手牌可能性预测和对方进度预测。预测必须保持不确定表达，不得把隐藏手牌渲染为确定牌面。

#### Scenario: 展示对方手牌可能性预测

- WHEN 稳定版面板刷新 `snapshot`
- THEN 系统基于对方弃牌、对方副露、我方手牌、双方已见牌和剩余牌生成对方手牌可能性预测
- AND UI 必须展示该预测
- AND 预测文案必须明确表示“可能/估计/关注”，不得声称已知对方隐藏手牌

#### Scenario: 展示对方进度预测

- WHEN 稳定版面板刷新 `snapshot`
- THEN 系统基于对方副露数量、弃牌数量、当前回合和剩余牌数生成对方进度预测
- AND UI 必须展示该预测
- AND 在对方副露多、弃牌少或牌局后段时提示更高风险

#### Scenario: 不破坏隐藏手牌约束

- WHEN 生成对方预测
- THEN `PacketStateTracker.snapshot()` 中对方 `hand` 字段仍保持为空或隐藏
- AND 预测不得依赖对方隐藏手牌明文
