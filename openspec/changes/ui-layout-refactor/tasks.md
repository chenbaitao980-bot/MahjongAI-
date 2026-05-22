# 任务：ui-layout-refactor

## 实施
- [x] 1. 重构顶部工具栏：创建 3 个分组弹框（AI / 记录+训练 / 预测），移除抓包选择
- [x] 2. 修改对手预测 HTML 渲染：危险牌/高概率持有/可能等待三列并排
- [x] 3. 修改策略分析 HTML 渲染：增加第三列展示候选重排
- [x] 4. 同步 apply_config 和配置保存逻辑（移除 _capture_mode_combo 引用）
- [x] 5. 修复弹框控件生命周期 bug：弹框内创建临时控件，确认后同步回主面板
- [x] 6. 增加对手手牌预测区域高度（FixedHeight 160 → 240）

## 验证
- [x] 历史 BugFixSpecs 命中的防复发检查项已执行或确认无命中
- [x] 已维护本 change 的回归测试用例
- [x] 顶部按钮分组弹框功能正常
- [x] 对手预测三列展示无需滚动
- [x] 策略分析三列布局正确
- [x] `gitnexus detect-changes --scope all -r mahjong-learning`
- [x] bugfix_count 已更新（qt-dialog-widget-reparent = 1）
- [x] 语法检查通过
