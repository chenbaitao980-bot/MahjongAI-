# Delta: stable-panel-layout-optimization

## 与主规范关系
Same Requirement / 追加 Scenario

## 命中的主规范
- Capability: `stable-reader`
- Requirement: 稳定版模拟对局、策略建议区域、右侧面板高度比例调整
- Scenario: 右侧面板高度比例调整

## 变更类型
追加 Scenario

## 业务冲突检查
| 维度 | 状态 |
|------|------|
| 主规范 Req 命中 | `stable-reader` |
| 关系判断 | Same Requirement |
| 其他 active change 撞车 | `stable-simulation-hand-structure-panel` 已覆盖手牌结构和面板高度；本 change 在其基础上优化布局。 |
| 冲突状态 | 无冲突 |
| 是否允许 ADDED | 否；追加现有能力场景 |
| 归档完整性 | 是 |

## 原规则
稳定版右侧策略建议区域 SHALL 保证硬算明细面板有足够高度完整展示所有分析内容。
策略摘要和手牌结构面板 SHALL 使用合理紧凑高度，不挤压硬算明细区域。

## 新规则
### Scenario: 手牌结构区域自适应高度
- WHEN 稳定版右侧手牌结构面板展示多种组合
- THEN 该面板 SHALL 根据内容自动调整高度
- AND 内容较多时 SHALL 自动撑开，不被截断
- AND 内容较少时 SHALL 保持紧凑，不浪费空间

### Scenario: 硬算明细两列布局
- WHEN 稳定版右侧硬算明细面板展示分析结果
- THEN 牌局状态类信息（当前状态、财神、向听、听牌、最佳进听、有效进张）SHALL 与 分析建议类信息（建议、原因、强提醒、风险、模型状态、推荐来源、数据可信度）分双列展示
- AND 候选重排 SHALL 在两列下方全宽展示
- AND 常规窗口大小下 SHALL 无需滚动即可看到全部内容

## 改动明细
- 文件: `ui/stable_battle_panel.py`
- 位置: `_setup_ui()`、`_format_strategy_analysis_html()`、`_format_hand_structure_arrangements_html()`
- 改前: `_hand_structure_edit` 使用 FixedHeight(85)，硬算明细使用单列表，`_hard_calc_edit` MinimumHeight(600)
- 改后: `_hand_structure_edit` 使用 MinimumHeight(60) + Expanding 策略；硬算明细使用 HTML 双列布局；`_hard_calc_edit` MinimumHeight(400)
