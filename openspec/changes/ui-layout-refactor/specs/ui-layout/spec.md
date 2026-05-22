# Delta: ui-layout-refactor

## 与主规范关系
New Capability（UI 体验优化），不涉及业务规则变更。

## 命中的主规范
- Capability：无
- Requirement：无
- Scenario：无

## 变更类型
不改 spec 只修代码

## 业务冲突检查
| 维度 | 状态 |
|------|------|
| 主规范 Req 命中 | 无 |
| 关系判断 | New Capability（纯 UI） |
| 其他 active change 撞车 | 无 |
| 冲突状态 | 无冲突 |
| 是否允许 ADDED | 不适用 |
| 归档完整性 | ✅ |

## 原规则
无

## 新规则
不改变业务规则

## 改动明细
- 文件：`ui/stable_battle_panel.py`
- 位置：`_setup_ui()` 方法（约第 137-286 行）
- 改前：顶部工具栏平铺所有控件，字体 9px，高度 22px
- 改后：顶部工具栏分组为 3 个弹框按钮（AI / 记录+训练 / 预测），移除抓包选择

- 文件：`ui/stable_battle_panel.py`
- 位置：`_format_opponent_prediction_html()` 方法（约第 754-816 行）
- 改前：三个概率表格垂直堆叠
- 改后：三个概率表格水平三列并排

- 文件：`ui/stable_battle_panel.py`
- 位置：`_format_strategy_analysis_html()` 方法（约第 843-895 行）
- 改前：两列布局（状态 / 建议）
- 改后：三列布局（状态 / 建议 / 候选重排）
