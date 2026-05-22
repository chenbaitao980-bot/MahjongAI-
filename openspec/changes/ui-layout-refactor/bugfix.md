# BugFix Log: ui-layout-refactor

## Bug Index

| bug_id | 现象 | 关联文件/函数 | bugfix_count | 当前状态 | 是否需沉淀 |
|---|---|---|---:|---|---|
| qt-dialog-widget-reparent | RuntimeError: wrapped C/C++ object of type QCheckBox has been deleted | ui/stable_battle_panel.py:_open_*_dialog | 1 | fixed | 否 |

## Bug Events

### qt-dialog-widget-reparent / 第 1 次修复

- 触发时间：2026-05-22 14:30
- 用户现象：点击模拟出牌后崩溃，报错 `RuntimeError: wrapped C/C++ object of type QCheckBox has been deleted`
- 复现路径：
  1. 启动应用
  2. 进入稳定版标签
  3. 点击"模拟出牌"
  4. 崩溃
- 触发条件：弹框内使用了主面板的控件（self._opponent_prediction_checkbox 等），弹框关闭后 Qt 销毁这些控件，后续 _opponent_prediction_config() 访问已删除对象
- 失败验证：堆栈显示 _start_opponent_prediction -> _analysis_config -> _opponent_prediction_config -> isChecked() 时崩溃
- 本轮根因假设：弹框关闭时销毁了通过 layout.addRow() 添加的控件
- 最终根因：Qt 的 QDialog 关闭时会销毁其布局内的所有子控件。当把主面板已有的控件（如 self._opponent_prediction_checkbox）通过 addRow() 添加到弹框布局时，Qt 会改变控件的父对象。弹框关闭后这些控件被销毁，主面板再访问就崩溃。
- 修复点：ui/stable_battle_panel.py 的三个弹框方法
- 验证结果：语法检查通过，待用户验证
- 是否同一 bug：是（本次布局调整引入）
