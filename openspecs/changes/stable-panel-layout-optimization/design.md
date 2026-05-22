# 设计：stable-panel-layout-optimization

## 当前状态
`StableBattlePanel._setup_ui()` 中右侧策略建议区域布局：
- `_summary_edit`: FixedHeight(45)，策略摘要
- `_hand_structure_edit`: FixedHeight(85)，手牌结构展示
- `_hard_calc_edit`: MinimumHeight(600)，硬算明细

问题：
1. `_hand_structure_edit` 使用 `FixedHeight(85)`，当手牌存在多种组合（组合1/2/3）时，内容超出被截断。
2. `_hard_calc_edit` 使用 `MinimumHeight(600)`，但内容行数多（当前状态、财神、向听、听牌、最佳进听、有效进张、对方预测、建议、原因、强提醒、财神风险、模型状态、推荐来源、候选重排、数据可信度），单列表导致垂直空间紧张。

## 方案
1. **手牌结构区域自动撑开**：
   - 将 `_hand_structure_edit` 从 `FixedHeight(85)` 改为 `MinimumHeight(60)` + 设置 `QSizePolicy.Expanding`
   - 这样内容少时保持紧凑，内容多时自动占用所需空间

2. **硬算明细两列布局**：
   - 将硬算明细内容按信息类型分为左右两列：
     - **左列**（牌局状态类）：当前状态、财神、当前向听、是否听牌、听牌列表、最佳进听打法、有效进张
     - **右列**（分析建议类）：当前建议、建议原因、强提醒、财神风险、模型状态、推荐来源、数据可信度
   - 候选重排因行数不固定，放在两列下方全宽展示
   - 使用 HTML `<div style="display:flex;">` 实现两列布局

3. **整体高度策略调整**：
   - `_summary_edit`: 保持 `FixedHeight(45)`，策略摘要不需要变
   - `_hand_structure_edit`: `setMinimumHeight(60)`，移除 `FixedHeight`，让内容决定高度
   - `_hard_calc_edit`: 保持 `MinimumHeight` 但可适当降低（因为两列布局更高效利用空间），改为 `MinimumHeight(400)`

## 业务规则处理
- 原 Requirement / Scenario: 稳定版右侧策略建议区域、手牌结构分组展示、右侧面板高度比例调整。
- 本次处理方式: 追加 Scenario（布局优化）。
- 不是新增独立业务能力；属于展示层布局调优。

## 历史 BugFixSpecs 命中
未发现命中。

## 回归测试方案
- 用例文件: `regression-tests/cases/stable-panel-layout-optimization.md`
- 验证方式: 启动 UI 后检查布局是否正确，因纯 UI 布局变更无断言接口，采用人工验证。
- 期望: 手牌结构多组合时不截断；硬算明细两列展示；整体布局协调。

## 回滚方案
恢复 `_hand_structure_edit` 为 `FixedHeight(85)`；恢复硬算明细为单列表布局。
