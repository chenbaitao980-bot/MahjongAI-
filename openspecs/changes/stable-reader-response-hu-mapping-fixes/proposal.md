# stable-reader-response-hu-mapping-fixes

## 为什么

2026-05-21 实测稳定版读取器仍有三个同一链路问题：

1. 客户端已弹出“碰/吃/杠/胡/过”可选动作时，UI 策略区只显示等待完整数据，没有给出响应建议。
2. 19:03:33 左右九万未识别，19:04:57 左右白未识别。
3. 19:05 左右画面已经可胡/已胡，硬算仍推荐打五条，胡牌优先级被出牌建议压过或旧建议残留。

## 影响面

- `stable/protocol.py`：复核 `0x0016 action_notify` 的 options、关联牌和 context 解析。
- `stable/tracker.py`：复核 `optional_actions`、未知映射、最近可信事件进入 snapshot 的状态。
- `game/stable_hard_analysis.py`：增加响应型硬建议；可胡/已胡时禁止输出出牌建议。
- `ui/stable_battle_panel.py`：展示响应建议并覆盖旧出牌建议。
- `tests/test_stable_reader.py` / `tests/test_stable_hard_analysis.py`：补当晚回归。

## 业务规范关系

- 命中的主 spec：`stable-reader/spec.md`
- 关系判断：Same Requirement / Bug Against Spec
- 处理动作：MODIFIED Requirement，不新增 capability。
- active change 撞车：`stable-reader-optional-action-round2-fixes` 与 `stable-reader-hard-analysis-panel` 均涉及相关链路；本 change 仅覆盖 2026-05-21 反馈的补漏，不改其已完成目标。

## 改动范围

- `stable/protocol.py`
- `stable/tracker.py`
- `game/stable_hard_analysis.py`
- `ui/stable_battle_panel.py`
- `tests/test_stable_reader.py`
- `tests/test_stable_hard_analysis.py`

## 验收

- [ ] 可选动作包含 `pon` / `chi` / `kong` 时，UI 给出响应建议和原因，而不是只等待。
- [ ] 可选动作包含 `hu` 或 phase 为 `hupai` 时，当前建议优先显示胡牌，不输出 `recommended_discard`。
- [ ] 回放 `data/stable_reader/events_20260521_185429.jsonl`，19:03:33 九万、19:04:57 白不再进入 unknowns。
- [ ] `python -m unittest tests.test_stable_reader tests.test_stable_hard_analysis`
- [ ] `python -m compileall stable game ui tests`
- [ ] `gitnexus detect-changes --scope all -r mahjong-learning`
