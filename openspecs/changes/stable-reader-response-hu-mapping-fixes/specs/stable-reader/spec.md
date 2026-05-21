# Delta: stable-reader-response-hu-mapping-fixes

## 与主规范关系

Same Requirement / Bug Against Spec。修复 `stable-reader` 已有协议解码、分析门控、硬算建议、未知映射展示能力的漏判，不新增 capability。

## 命中的主规范

- Capability: `stable-reader`
- Requirement: `协议解码`、`映射修正`、`分析门控`
- Scenario: 可选动作展示、未知映射补全、策略建议门控

## 变更类型

MODIFIED Requirement

## 业务冲突检查

| 维度 | 状态 |
| --- | --- |
| 主规范 Req 命中 | `stable-reader/spec.md` |
| 关系判断 | Same Requirement / Bug Against Spec |
| 其他 active change 撞车 | `stable-reader-optional-action-round2-fixes`、`stable-reader-hard-analysis-panel` 有链路重叠；本 change 只补 2026-05-21 反馈 |
| 冲突状态 | 无冲突，需实施时注意不回退现有已完成逻辑 |
| 是否允许 ADDED | 否，使用 MODIFIED |
| 归档完整性 | 待实施与验证 |

## 原规则

- 稳定版读取器必须把可选动作通知解码为结构化事件，并在 UI 展示动作集合。
- 稳定版读取器必须将未知 raw_key 显示为未知映射候选；用户绑定后可重建。
- 稳定版硬算建议必须在手牌、财神、当前事件可信时输出基于硬规则的建议；数据不足时明确等待。

## 新规则

### Requirement: 可选动作必须给响应建议

稳定版硬算面板在 `snapshot.optional_actions` 非空时 SHALL 输出响应建议，不得只显示“等待完整数据”。

#### Scenario: 碰或过弹窗

- WHEN 客户端弹出“碰/过”，且 `snapshot.optional_actions` 至少包含 `pon` 与 `pass`
- THEN `StableHardAnalysis.current_advice` SHALL 显示“建议碰”或“建议过”
- AND `advice_reason` SHALL 说明进听/退听、有效进张、数据不足保守过，或人工确认原因
- AND UI SHALL 覆盖上一轮出牌建议

#### Scenario: 吃或杠弹窗

- WHEN `snapshot.optional_actions` 包含 `chi` 或 `kong`
- THEN UI SHALL 给出吃/杠/过的响应建议
- AND 当缺少关联弃牌或完整手牌时，SHALL 明确说明“数据不足，建议保守过/人工确认”

#### Scenario: 胡牌弹窗

- WHEN `snapshot.optional_actions` 包含 `hu`
- THEN 当前建议 SHALL 优先显示“建议胡”
- AND `recommended_discard` SHALL 为空
- AND 候选列表 SHALL NOT 把出牌方案排在胡牌响应前

### Requirement: 九万与白的稳定映射不得误报未知

稳定版读取器 SHALL 在 2026-05-21 抓包上下文中正确解析九万与白板，不得把它们作为未知映射弹出。

#### Scenario: 19:03:33 九万

- WHEN 回放 `data/stable_reader/events_20260521_185429.jsonl` 到 19:03:33 左右
- THEN 与截图中九万对应的 raw_key SHALL 解析为 `9m`
- AND `snapshot.unknowns` SHALL NOT 因该牌新增未知项

#### Scenario: 19:04:57 白

- WHEN 回放 `data/stable_reader/events_20260521_185429.jsonl` 到 19:04:57 左右
- THEN 与截图中白对应的 raw_key SHALL 解析为 `7z`
- AND `snapshot.unknowns` SHALL NOT 因该牌新增未知项

### Requirement: 胡牌状态优先级最高

稳定版硬算建议 SHALL 把可胡/已胡作为最高优先级，压过出牌推荐。

#### Scenario: 已经胡牌后不再建议出牌

- WHEN snapshot phase 为 `hupai` 或最近可信事件为 `win`
- THEN `recommended_discard` SHALL 为空
- AND `current_advice` SHALL 显示胡牌/结算状态
- AND UI SHALL 覆盖旧出牌建议，不得继续显示“建议打五条”等历史建议

## 改动明细

- 文件：`stable/protocol.py`
- 位置：`_extract_optional_action`、可选动作关联牌解析
- 改前：只产生动作集合，硬算不一定消费为响应建议
- 改后：保留足够证据供响应建议使用

- 文件：`stable/tracker.py`
- 位置：`apply()`、`snapshot()`
- 改前：可选动作和 win 状态不足以压过出牌建议
- 改后：snapshot 能表达响应/胡牌优先级

- 文件：`game/stable_hard_analysis.py`
- 位置：`analyze_snapshot()`、推荐门控
- 改前：只推荐出牌或等待完整数据
- 改后：支持响应建议，胡牌优先，禁止已胡后推荐出牌

- 文件：`ui/stable_battle_panel.py`
- 位置：硬算结果渲染
- 改前：可能保留上一轮出牌建议
- 改后：响应/胡牌状态覆盖旧建议
