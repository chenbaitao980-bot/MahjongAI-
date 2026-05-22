# Delta: stable-simulation-hand-structure-panel

## 与主规范关系
Same Requirement / 追加 Scenario

## 命中的主规范
- Capability: `stable-reader`
- Requirement: 稳定版模拟对局、策略建议区域、模拟吃碰杠胡事件
- Scenario: 模拟胡牌、策略建议空间

## 变更类型
追加 Scenario

## 业务冲突检查
| 维度 | 状态 |
|------|------|
| 主规范 Req 命中 | `stable-reader` |
| 关系判断 | Same Requirement |
| 其他 active change 撞车 | `stable-only-capture-module` 已覆盖模拟吃碰杠胡；`stable-reader-hard-analysis-panel` 已覆盖右侧硬算面板。本 change 只追加解释与分组展示。 |
| 冲突状态 | 无冲突 |
| 是否允许 ADDED | 否；追加现有能力场景 |
| 归档完整性 | 是 |

## 原规则
稳定版模拟模式 SHALL 支持基础吃、碰、杠、胡事件，并将副露和胡牌结果写入与稳定版 snapshot 兼容的数据结构。

稳定版右侧策略建议区域必须优先保证硬算明细可读。

## 新规则
### Scenario: 响应胡牌来源说明
- WHEN 模拟模式中对方打出一张牌，并且我方 `optional_actions` 包含 `hu`
- THEN UI SHALL 明确说明当前可胡来自“响应对方打出的该牌”
- AND UI SHALL NOT 把该状态误表达为我方已自摸

### Scenario: 手牌结构分组展示
- WHEN 稳定版右侧面板展示我方当前手牌
- THEN UI SHALL 在右侧显示手牌结构分组
- AND 已成面子/刻子、搭子、将牌候选、边张或孤张 SHALL 使用不同颜色区分
- AND 该分组 SHALL 只作为展示辅助，不参与胡牌判定、向听计算或推荐排序

### Scenario: 手牌结构多组合展示
- WHEN 同一手牌存在多种合理分组方式
- THEN UI SHALL 展示多种手牌结构组合
- AND 每种组合 SHALL 明确标示各自的顺子、刻子、将牌候选、搭子、孤张
- AND 展示组合数量 SHALL 有上限，避免挤压硬算明细区域
- AND 该多组合展示 SHALL 只作为展示辅助，不参与胡牌判定、向听计算或推荐排序

### Scenario: 推荐弃牌优先展示为劣势牌型
- WHEN 当前硬算推荐弃牌存在
- AND 多种手牌结构组合都合理
- THEN UI SHALL 优先展示推荐弃牌处于劣势牌型的组合
- AND 孤张 SHALL 优先于边张或坎张等低质量搭子
- AND 低质量搭子 SHALL 优先于完整顺子、对子或刻子
- AND 例如推荐打 `2s` 且 `2s`、`5s` 均可作为孤张时，UI SHALL 优先展示 `2s` 为孤张的组合

### Scenario: 右侧面板高度比例调整
- WHEN 稳定版右侧策略建议区域包含多个信息面板
- THEN UI SHALL 保证硬算明细面板有足够高度完整展示所有分析内容
- AND 策略摘要和手牌结构面板 SHALL 使用合理紧凑高度，不挤压硬算明细区域

## 改动明细
- 文件: `ui/stable_battle_panel.py`
- 位置: `StableBattlePanel._setup_ui()`、`set_snapshot()` 及辅助格式化函数
- 改前: 右侧只显示策略建议和硬算明细；手牌结构需要从左侧纯文本自行判断；面板高度比例未优化，硬算明细内容可能被截断。
- 改后: 右侧增加手牌结构分组展示，并解释响应胡牌来源；调整 `_summary_edit`/`_hand_structure_edit`/`_hard_calc_edit` 的 `minimumHeight` 以优化内容展示。
- 文件: `stable/hand_structure.py`
- 位置: `build_hand_structure_groups()` 及新增多方案分组辅助函数
- 改前: 展示层只做单一贪心拆分，顺子优先会吞掉其他合理解释，不能同时展示多种组合。
- 改后: 展示层可返回有限数量的合理拆分方案，并按当前推荐弃牌在方案中的劣势程度排序。

- 文件: `stable/simulator.py`
- 位置: `snapshot()` 或 pending response 构造
- 改前: snapshot 可通过 `optional_actions` 看出可胡，但 UI 不一定知道响应牌来源。
- 改后: snapshot/UI 能明确显示当前响应牌和来源。
