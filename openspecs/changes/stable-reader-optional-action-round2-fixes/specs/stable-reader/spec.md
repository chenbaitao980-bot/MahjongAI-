# Delta: stable-reader-optional-action-round2-fixes

## 与主规范关系

无冲突。本变更修改 `stable-reader` 的协议解码、分析门控和 UI 展示要求，延续“只从可信手牌包更新手牌”的主规范，并补充可选动作、特殊副露、标记牌展示。

## 变更摘要

| 维度 | 状态 |
| --- | --- |
| 主规范 Req 命中 | 协议解码、分析门控、手牌显示排序、回放兼容 |
| 其他 active change 撞车 | 无 active change；上一轮 `round2-bugfix-batch` 已归档 |
| 归档完整性 | 待实现与验证后归档 |

## MODIFIED Requirements

### 协议解码

稳定版读取器必须把可选动作通知解码为结构化事件，并在事件中保留动作集合与原始证据。

#### Scenario: 展示吃或过

- WHEN 抓包收到表示“吃/过”的 action notify 包
- THEN 解码结果包含 `event="optional_action"` 和 `options`，至少包含 `chi` 与 `pass`
- AND UI 显示“可选动作：吃 / 过”

#### Scenario: 展示碰或过

- WHEN 抓包收到表示“碰/过”的 action notify 包
- THEN 解码结果包含 `event="optional_action"` 和 `options`，至少包含 `pon` 与 `pass`
- AND UI 显示“可选动作：碰 / 过”

### 手牌可信更新

稳定版读取器不得把副露/桌面汇总型 `0x0216` payload 当作我方手牌覆盖已有手牌。

#### Scenario: 副露汇总包不污染手牌

- WHEN `0x0216` payload 的 `count` 很小且 tail 呈现多组副露结构
- THEN 协议层不得输出可信 `hand_raw` 覆盖本地手牌
- AND tracker 保留上一份可信手牌或进入“等待可信手牌包”状态

#### Scenario: 20:46 缺九条时显式提示

- WHEN 增量事件无法恢复完整手牌且没有后续可信全量手牌包
- THEN UI 不得静默展示少牌为可信结果
- AND UI/日志必须显示手牌可能不完整的原因

### 副露解析

稳定版读取器必须识别特殊杠牌和含财神替代的副露，不得因为 meld body 含重复来源牌或财神值就丢弃副露信息。

#### Scenario: 20:51 西杠解析

- WHEN 收到 body `00050104434343430343434300000000`
- THEN 解码结果包含 `event="kong"`、`meld_type` 和 `meld_tiles_raw`
- AND tracker 杠后我方手牌不再多出被杠的西

#### Scenario: 含财神替代的副露

- WHEN 收到类似 `01010003375339015300000000` 的副露包
- THEN 解码结果保留 meld tiles 和“含财神替代”备注
- AND UI 可显示该副露而不是仅记录 warning

### 分析门控

当当前回合不是我方时，稳定版读取器不得触发新的策略建议或候选分析。

#### Scenario: 敌方回合等待

- WHEN `current_turn` 为 `enemy` 或 `none`
- THEN `should_analyze()` 返回 false
- AND 策略建议区域显示“等待敌方出牌”或“等待我方回合”
- AND 候选分析清空或显示等待态

### LLM 兜底

LLM 输出应先归一化为合法候选牌，再进行合法性校验；归一化失败时必须回退到程序候选。

#### Scenario: 中文牌名可归一化

- WHEN LLM 返回 `recommended_discard` 为 `五万`、`打五万` 或候选描述中包含合法牌
- THEN 系统将其映射到合法候选 ID 后接受

#### Scenario: 输出仍不合法

- WHEN LLM 输出无法映射到任一合法候选
- THEN 系统返回程序评分最高的候选
- AND UI 显示降级原因，不得表现为没有出牌建议

### 标记牌备注

稳定版读取器必须在可识别时把头上三角形标记牌展示到备注。

#### Scenario: 标记五万和一条

- WHEN 抓包或状态中识别到 20:52:04 这类标记牌
- THEN snapshot 包含 `marked_tiles`
- AND UI/Excel 备注显示“标记牌：五万、一条”

## 变更明细

- `stable/protocol.py`：新增 action notify 解码、副露汇总识别、特殊杠/财神副露解析。
- `stable/tracker.py`：新增 optional actions、marked tiles、敌方回合门控、手牌完整性状态。
- `ui/stable_battle_panel.py`：新增可选动作/等待态/标记备注展示。
- `game/llm_advisor.py`：新增 LLM 出牌归一化与更清晰 fallback。
- `tests/test_stable_reader.py`：增加协议、tracker、LLM 回归测试。
