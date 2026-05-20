# 任务：round2-bugfix-batch

## 实施

- [x] 1. `stable/tracker.py::reset()` 保留已可信解析的 `baida_tile` / `baida_trusted`，避免后续 deal/hand_update reset 清空财神。
- [x] 2. `stable/protocol.py::_extract_meld_info` 增加 `body[3]` 判据：`body[3] <= 0x03` 按吃/碰三张副露解析，`body[3] >= 0x04` 才按明杠四张解析。
- [x] 3. `stable/protocol.py::_decode_game_event` 的 `0x021F` 分支复用新的 meld 判据，碰牌不再落入 `kong`。
- [x] 4. `ui/stable_battle_panel.py` 移除右栏「未知映射修正」表格区域。
- [x] 5. `ui/stable_battle_panel.py` 新增 `UnknownTileDialog(QDialog)`，显示未识别牌值并提供牌面下拉选择。
- [x] 6. `ui/stable_battle_panel.py::_notify_unknowns` 改为弹出 `UnknownTileDialog`，确认后通过现有保存入口永久保存并回放历史。
- [x] 7. 更新 tests 中受影响的断言（`meld_type` pon vs kan_open、财神跨 reset 保留）。

## 验证

- [x] `python -m py_compile stable\tracker.py stable\protocol.py ui\stable_battle_panel.py`
- [x] `python -m unittest tests.test_stable_reader` 全通过
- [x] `gitnexus detect-changes --scope all -r mahjong-learning` 已执行，风险等级 medium
- [x] 启动主程序实测：财神正确显示、碰显示 3 张、弹框可选牌保存
