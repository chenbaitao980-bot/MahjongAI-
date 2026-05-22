# 任务：stable-reader-ai-default-off

## 实施
- [x] 1. 将稳定版面板“开启 AI 分析”控件默认值改为关闭。
- [x] 2. 将稳定版配置归一化中的 `stable_reader.deepseek_enabled` 默认值改为 false。
- [x] 3. 增加/更新单测覆盖缺省配置和面板选项默认关闭。
- [x] 4. 维护 `regression-tests/cases/stable-reader-ai-default-off.md`。
- [x] 5. 更新 `delivery.md`。

## 验证
- [x] 历史 BugFixSpecs 命中的防复发检查项已执行或确认无命中。
- [x] bugfix_count 已按本轮触发情况更新。
- [x] 已维护本 change 的回归测试用例。
- [x] `python -m unittest tests.test_stable_reader`
- [x] `python -m py_compile ui/stable_battle_panel.py ui/main_window.py tests/test_stable_reader.py`
- [x] `gitnexus detect-changes --scope all -r mahjong-learning`
