# ui-layout-refactor

## 为什么
用户反馈当前稳定版对战面板（stable_battle_panel）顶部工具栏按钮过于局促，所有控件平铺在一行导致字体被迫缩小到 9px、高度 22px，视觉拥挤且不易操作。同时右侧策略建议区域的对手预测信息需要上下滚动查看，策略分析只有两列布局，空间利用不够充分。

## 影响面
- 仅影响 `ui/stable_battle_panel.py` 的 UI 布局和渲染逻辑
- 不涉及业务逻辑、AI 决策、抓包协议等核心功能
- 不影响 `ui/main_window.py`（只嵌入面板，不改动）

## 业务规范关系
- 命中的主 spec：无（纯 UI 布局调整，不涉业务规则变更）
- 关系判断：New Capability（UI 体验优化）
- 推荐动作：不改 spec 只修代码

## 改动范围
- `ui/stable_battle_panel.py`：
  - `_setup_ui()`：重构顶部工具栏，按钮分组到弹框
  - `_format_opponent_prediction_html()`：预测结果三列并排展示
  - `_format_strategy_analysis_html()`：策略分析增加第三列

## 验收
- [x] 顶部工具栏按钮按功能分组成 3 个弹框按钮（AI / 记录+训练 / 预测）
- [x] 抓包选择下拉框已移除，默认使用 npcap
- [x] 对手预测区域（危险牌/高概率持有/可能等待）分列展示，无需上下滚动
- [x] 策略分析区域增加第三列，信息展示更充分
- [x] 对手手牌预测区域高度增加（160px → 240px），内容显示更完整
- [ ] 已维护 `regression-tests/cases/ui-layout-refactor.md`
- [x] `gitnexus detect-changes` 无异常范围外变更

## Bug 修复记录
无
