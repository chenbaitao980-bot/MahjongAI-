# 任务：fix-stable-hand-recognition-reset

## 实施
- [x] 1. 在 `tests/test_stable_reader.py` 增加首个可信稳定版手牌包识别回归测试。
- [x] 2. 在 `tests/test_stable_reader.py` 增加等待可信手牌状态下下一局可信手牌清空旧状态回归测试。
- [x] 3. 调整 `stable/tracker.py` 的本地玩家接管和新局清理判定。
- [x] 4. 维护 `regression-tests/cases/fix-stable-hand-recognition-reset.md`。

## 验证
- [x] 历史 BugFixSpecs 命中的防复发检查项已执行或确认无命中。
- [x] bugfix_count 已按本轮触发情况更新。
- [x] 已维护本 change 的回归测试用例。
- [x] `python -m unittest tests.test_stable_reader`
- [x] `gitnexus detect-changes --scope all -r mahjong-learning`
