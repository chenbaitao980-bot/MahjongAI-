# 交付记录：稳定版反馈与解码补完

## 实测协议事实

来源：`scripts/inspect_meld_subcmd.py` 重放 `data/stable_reader/events_20260519_192721.jsonl`（2816 个 game_event 包）

### 财神（baida）

| 协议位置 | sub_cmd | body 结构 | 验证 |
|---|---|---|---|
| `0x0218` 是 trusted 财神更新包 | 4 字节 | `01 [baida_raw] 01 53` | 4 局命中：`0x37 / 0x34 / 0x16 / 0x11` ↔ `7p / 4p / 6m / 1m` 100% |
| `0x0003 deal` 中的 `untrusted_baida_raw_candidate` | byte[17] | 单字节 | **非财神**（第 1 局 byte[17]=`0x46` 与真值 `0x37` 不一致），保留为 untrusted 不应用 |

### 副露

| 类型 | sub_cmd | body 结构（识别字段） | 备注 |
|---|---|---|---|
| 吃 / 碰 / 明杠 | `0x021F` | body[4..6]=exposed 三张、body[8]=claimed | 全部走同一个 sub_cmd，由 `_extract_meld_info` 根据 exposed 关系区分 chi / pon / kan_open |
| 异常副露（财神替代？） | `0x021F` | body[4]=`0x53` (7z) | 实测 4 次，无法套 chi/pon/kan_open 规则；本轮兜底为 `event=kong` 但不附 meld_type，并写 WARN 日志 |

## 已完成

### 协议层

- [game/excel_logger.py](game/excel_logger.py) `flush_every=5` 周期保存 + INFO/WARN 日志（属补漏 B）
- [stable/protocol.py](stable/protocol.py)：
  - `GAME_SUB_NAMES` 加 `0x0218: "baida_update"`，`0x021F` 改名为 `"meld"`
  - `_decode_game_event` 新增 `sub_cmd==0x0218` 财神解码（marker `0x01` + body[1]）
  - `_decode_game_event` 修改 `sub_cmd==0x021F` 分支：根据 `_extract_meld_info` 的 `meld_type` 把 event 拆为 `"chi"/"pon"/"kong"`；不可识别的副露 body 走 WARN 日志兜底

### 状态层

- [stable/tracker.py](stable/tracker.py)：
  - `apply` 路径加 `event == "baida_update"` 处理
  - 副露分支合并为 `event in ("kong","chi","pon")`，chi/pon 留下 claimed 不扣手牌，kong 全部扣；副露后置 current_turn
  - 事件日志支持 chi/pon
  - 新增 `analysis_mode()`，`should_analyze()` 改为 mode!=blocked 即允许；`analysis_signature` 加入 mode 字段
  - `to_battle_state()` 末尾置 `state.is_conservative`
  - `snapshot()` 返回 dict 新增 `"analysis_mode"`

### 状态对象 + AI 提示词

- [battle/state.py](battle/state.py)：`BattleState` 加 `is_conservative: bool = False` 字段，`reset()` 清零，`to_payload()` 新增字段
- [game/llm_prompt.py](game/llm_prompt.py) `build_system_prompt`：检测 `game_features["is_conservative"]` 时追加保守模式约束段，强调「不依赖财神 / 不推断对方禁手 / 仅基于已知手牌给安全弃牌 / 在 strategy_type 前缀加 [保守]」
- [game/llm_advisor.py](game/llm_advisor.py) `get_final_advice`：把 payload 的 `is_conservative` 注入 `game_features` 传给 build_system_prompt

### UI

- [ui/stable_battle_panel.py](ui/stable_battle_panel.py)：
  - `_event_view` / `_data_view` 在「距底部 ≤ 60 px」时才自动滚到底
  - 新增 `_has_advice_rendered` 状态机；未渲染建议时根据 `analysis_mode` 显示「等待中：<原因>」或「[保守] 等待中」
  - `set_advice` 渲染保守模式：策略类型前缀 `[保守] `、顶部黄色提示
  - `set_running(True)` 时复位 advice 与 unknown 状态
  - 未知映射区：`setMinimumHeight(220)`、3 行 help、表格行高 28 / 字号 10pt、ComboBox+按钮高 32 / 字号 11pt
- [ui/main_window.py](ui/main_window.py)（属补漏 B）：`closeEvent` / `_on_stable_capture_failed` / `_on_stable_capture_finished` 全部调用 `_close_stable_excel_logger`；状态栏消息改为完整路径

### 测试

- [tests/test_stable_reader.py](tests/test_stable_reader.py)：
  - 新增 `test_baida_update_sub_0x0218_applied`
  - 新增 `test_chi_event_appends_meld_and_removes_discard`
  - 新增 `test_pon_event_appends_meld`
  - 新增 `test_conservative_mode_allows_analysis`
  - 老用例 `test_protocol_decodes_stable_field_positions` 中的 chi 子检查同步把 event 断言从 `"kong"` 改为 `"chi"`

### 工具脚本

- [scripts/inspect_meld_subcmd.py](scripts/inspect_meld_subcmd.py) 用于追加抓包样本时复检副露 sub_cmd 假设

## 修改文件

- `game/excel_logger.py`
- `ui/main_window.py`
- `stable/protocol.py`
- `stable/tracker.py`
- `battle/state.py`
- `game/llm_prompt.py`
- `game/llm_advisor.py`
- `ui/stable_battle_panel.py`
- `tests/test_stable_reader.py`
- `scripts/inspect_meld_subcmd.py`（新）
- `openspecs/changes/excel-game-logger/{proposal,design,tasks}.md`
- `openspecs/changes/excel-game-logger/specs/excel-logger/spec.md`
- `openspecs/changes/stable-reader-feedback-fixes/{proposal,design,tasks,delivery}.md`
- `openspecs/changes/stable-reader-feedback-fixes/specs/stable-reader/spec.md`
- `openspecs/archive/2026-05-19-stable-reader-display-fixes/`（git mv 自 changes/）

## 验证结果

- `python -m py_compile game/excel_logger.py ui/main_window.py stable/protocol.py stable/tracker.py battle/state.py game/llm_prompt.py game/llm_advisor.py ui/stable_battle_panel.py tests/test_stable_reader.py` ✅
- `python -m unittest discover tests` ✅ 37 个用例全部通过（包含 4 个新增）

## 已知风险与后续

- `gitnexus mahjong-learning` 索引在 commit `617e91b` 处 stale，本次未运行 `detect-changes`；下次大批改动前建议 `gitnexus analyze --name mahjong-learning --force` 重建
- `0x021F` body[4]=`0x53` 的少数副露包仍走 WARN 日志兜底，后续如能锁定它是「财神替代副露」可补 chi/pon 派生分支
- 实测验收（[tasks.md](openspecs/changes/stable-reader-feedback-fixes/tasks.md) 第 25 项）需要用户启动主程序确认 UI 反馈和保守模式真实链路
