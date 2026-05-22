# 任务：stable-panel-layout-optimization

## 实施
- [x] 1. 修改 `_setup_ui()`：调整 `_hand_structure_edit` 尺寸策略（FixedHeight -> MinimumHeight + Expanding）
- [x] 2. 修改 `_setup_ui()`：调整 `_hard_calc_edit` minimumHeight（600 -> 400）
- [x] 3. 修改 `_format_strategy_analysis_html()`：实现硬算明细两列 HTML 布局（flex 失败，改用 HTML table）
- [x] 4. 修改 `_format_hand_structure_arrangements_html()`：确保多组合时容器正确撑开
- [x] 5. 运行 `gitnexus detect-changes --scope all -r mahjong-learning`
- [x] 6. 修复两列布局：CSS flex 在 QTextEdit 中不支持，改用 HTML table 布局

## 验证
- [x] 历史 BugFixSpecs 命中的防复发检查项已执行或确认无命中
- [x] 已维护本 change 的回归测试用例
- [x] `gitnexus detect-changes --scope all -r mahjong-learning`
- [x] 手牌结构多组合时内容不被截断（用户确认）
- [x] 硬算明细两列布局在常规窗口下完整展示（用户确认）
