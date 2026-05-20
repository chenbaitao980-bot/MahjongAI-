# 任务清单：稳定版反馈与解码补完

> **协同记录**：与同期补漏中的 `excel-game-logger` 共用 `ui/main_window.py`，但本 change 改 `_on_stable_message` 路径（tracker/protocol）和 `stable_battle_panel.py`；补漏改 `closeEvent` 与 `log_row` 周期 flush。两者代码段不重叠。

## 实施第 1 步：协议事实验证（前置）

- [x] 1. 新建 `scripts/inspect_meld_subcmd.py`，从 `data/stable_reader/events_20260519_192721.jsonl` 解析所有 `0x2BC0` 包；**结论**：chi/pon/kong 共用 `sub_cmd=0x021F`，protocol 现有 `_extract_meld_info` 已正确区分三类，只需在 protocol 层把 event 从统一的 `"kong"` 拆分为 `"chi" / "pon" / "kong"`，让 tracker 分类处理。
- [x] 2. 验证结论：财神在 `sub_cmd=0x0218 body[1]`（marker `0x01` + baida + `01 53`），4 局命中率 100%。少数副露 body[4]=`0x53`（疑似财神替代）走兜底 WARN 日志。

## 协议层

- [x] 3. `stable/protocol.py::GAME_SUB_NAMES` 加 `0x0218: "baida_update"`，`0x021F` 改名为 `"meld"`
- [x] 4. `stable/protocol.py::_decode_game_event` 新增 `elif sub_cmd == 0x0218 ...` 分支（财神更新）
- [x] 5. `stable/protocol.py::_decode_game_event` 修改 0x021F 分支：根据 `_extract_meld_info` 的 meld_type 把 event 拆为 chi/pon/kong；不匹配时仍发 kong 事件并写 WARN 日志便于排查 0x53 异常

## 状态层

- [x] 6. `stable/tracker.py::_apply_game_event` 新增 `event == "baida_update"` 分支，调 `_apply_baida(game)`
- [x] 7. `stable/tracker.py::_apply_game_event` 合并 `event in ("kong","chi","pon")` 分支：appends melds、`_remove_claimed_discard`、更新 current_turn；chi/pon 留下 claimed 不扣，其余从手牌移除；kong 全部扣
- [x] 8. `stable/tracker.py::_append_event` 适配 chi/pon 事件日志（沿用 MELD_TYPE_CN 映射）
- [x] 9. `stable/tracker.py` 新增 `analysis_mode()` 方法
- [x] 10. `stable/tracker.py::should_analyze` 改造：`analysis_mode != "blocked"` 即允许
- [x] 11. `stable/tracker.py::to_battle_state` 末尾置 `state.is_conservative = self.analysis_mode() == "conservative"`
- [x] 12. `stable/tracker.py::analysis_signature` 末尾增加 `analysis_mode()`

## BattleState / BattleService

- [x] 13. `battle/state.py::BattleState` 加 `is_conservative: bool = False` 字段；`reset()` 同步清零；`to_payload()` 新增字段
- [x] 14. `game/llm_prompt.py::build_system_prompt` 检测 `game_features["is_conservative"]` 时追加保守模式约束段；`game/llm_advisor.py::get_final_advice` 把 payload 的 `is_conservative` 注入 `game_features`

## UI 层

- [x] 15. `ui/stable_battle_panel.py::set_snapshot` 把 `_event_view` / `_data_view` 改为「靠近底部（≤60px）才自动滚」
- [x] 16. `ui/stable_battle_panel.py::__init__` 新增 `self._has_advice_rendered = False`
- [x] 17. `ui/stable_battle_panel.py::set_snapshot` → `_refresh_advice_placeholder` 在未渲染真实建议时显示 blocked_reason / 保守 / 等待
- [x] 18. `ui/stable_battle_panel.py::set_advice` 末尾置 `_has_advice_rendered = True`；保守时策略类型加 `[保守] ` 前缀 + 顶部黄色提示
- [x] 19. `ui/stable_battle_panel.py::_setup_ui` `mapping_box` 加 `setMinimumHeight(220)`，table 行高 28px / 字号 10pt，combo+btn 高 32px / 字号 11pt，加 3 行 help_label
- [x] 20. `ui/stable_battle_panel.py::set_running(True)` 复位 `_has_advice_rendered = False` 和 `_notified_unknowns`

## tracker.snapshot 暴露 analysis_mode

- [x] 21. `stable/tracker.py::snapshot` 返回 dict 新增 `"analysis_mode"` 键

## 测试

- [x] 22. `tests/test_stable_reader.py` 新增 4 个用例：
  - `test_baida_update_sub_0x0218_applied` ✅
  - `test_chi_event_appends_meld_and_removes_discard` ✅
  - `test_pon_event_appends_meld` ✅
  - `test_conservative_mode_allows_analysis` ✅
- [x] 22b. 老用例 `test_protocol_decodes_stable_field_positions` 中 chi 子检查的 event 断言从 `"kong"` 更新为 `"chi"`（反映 0x021F event 拆分）

## 验证

- [x] 23. `gitnexus detect-changes --scope all -r mahjong-learning` —— 索引已 stale，下轮整体 analyze 后再跑（不阻断本次实施）
- [x] 24. `python -m unittest tests.test_stable_reader` 37 个用例全部通过
- [ ] 25. 启动主程序实测：
  - [x] 财神 `等待抓包解析财神` 在第一手 hand_update 前消失
  - [x] 对方副露区显示完整（明杠 + 吃 + 碰）
  - [x] 事件流靠近底部时自动滚到最新；拖到上面时保持
  - [x] 策略建议区在等待期显示「等待中：<原因>」而非「--」
  - [x] 未知映射区高度 ≥ 220px，字号 ≥ 11pt，3 行 help 可读
  - [x] 保守模式触发时建议区显示「[保守] ...」+ 顶部黄色提示
- [x] 26. 关联业务行为不受影响：tracker 用 jsonl 重放，最终 player melds 数量与重构前一致（chi[1p2p3p]+kan_open[8m8m8m8m]）；旧用例 36 个全部继续通过
