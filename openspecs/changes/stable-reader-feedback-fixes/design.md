# 设计：稳定版反馈与解码补完

## 当前状态

### 协议解码

[stable/protocol.py::MJProtocol._decode_game_event](stable/protocol.py:339) 只识别 6 个 sub_cmd：

| sub_cmd | event | 处理 |
|---|---|---|
| 0x0003 | deal | 设 untrusted hand/baida candidate |
| 0x0216 | hand_update | 解码 hand + tail extra |
| 0x021A | draw | 解码摸牌 |
| 0x021B | discard | 解码弃牌 |
| 0x021F | kong | 解码 kong + meld_info（含 chi/pon 但只有这个入口） |
| 0x0220 | win | 胡牌 |

`_extract_meld_info` 已经能区分 `kan_open / pon / chi`，但**只在 `sub_cmd=0x021F` 路径调用一次**——真正的吃/碰 sub_cmd 进不来这个函数，所以副露事件丢失。

财神当前唯一来源是 `0x0003 deal` 的 `untrusted_baida_raw_candidate`（trusted=False），tracker 的 `_apply_baida` 必须 trusted=True 才应用——所以财神永远没被应用。

### 状态层

[stable/tracker.py::analysis_blocked_reason](stable/tracker.py:496) 严格门控：
- 必须 `hand_trusted` ✅
- 必须 `baida_trusted` ✅
- 必须 `turn_trusted` ✅
- 当前回合必须 `self` ✅
- `effective_self_count == 14` ✅

任意一条不满足，`should_analyze() == False`，BattleAnalysisThread 不启动，[stable_battle_panel.py::set_advice](ui/stable_battle_panel.py:333) 永不被调用。

### UI 层

[stable_battle_panel.py::set_snapshot](ui/stable_battle_panel.py:224) 用 `setPlainText` 全量覆盖事件流，QTextEdit 默认保留旧滚动位置。

[stable_battle_panel.py:152-168](ui/stable_battle_panel.py:152) 的 mapping_box 在右栏权重 1（advice_box 是 2），且 ComboBox / Table 没设字号和高度。

## 实测证据

### 财神

来自 `data/stable_reader/events_20260519_192721.jsonl` 解析（4 局完整对局）：

| 局 | 真值（用户口报） | 0x0218 body | body[1] |
|---|---|---|---|
| 1 | 7p | `01 37 01 53` | `0x37` ✅ |
| 2 | 4p | `01 34 01 53` | `0x34` ✅ |
| 3 | 6m | `01 16 01 53` | `0x16` ✅ |
| 4 | 1m | `01 11 01 53` | `0x11` ✅ |

`0x0218` 在每局开局 hand_update（trusted）前 2 个事件出现，时序稳定。

### 吃/碰候选

每局 `sub_0x021d` 出现 0~2 次，`sub_0x05dc` 出现 ~6 次。其中 `0x021d` 集中在 hand_update 之间（疑似副露），`0x05dc` 高频且分布散（疑似 stat 类）。**最终值留到实施第 1 步验证**。

## GitNexus 影响范围

- `stable/protocol.py::MJProtocol._decode_game_event` → 调用方仅 `_decode_frame` (同文件)；新增分支向后兼容。
- `stable/tracker.py::_apply_game_event` → 调用方仅 `apply`（同文件）；新增 chi/pon event 不影响现有 deal/draw/discard/kong。
- `stable/tracker.py::analysis_blocked_reason / should_analyze` → 用于 [main_window.py::_on_stable_message](ui/main_window.py:2385) 的门控；放宽门控会使 BattleAnalysisThread 启动更频繁，需要保守模式 signature 去重避免风暴。
- `stable_battle_panel.py::set_snapshot` → 仅被 [main_window.py::_refresh_stable_snapshot](ui/main_window.py) 调用；UI 行为变更，接口不变。
- `BattleState` 新增 `is_conservative: bool = False` 字段——`battle/state.py` 改造；下游 [battle/service.py::analyze_state_with_ai](battle/service.py) 读取该字段调整提示词。

## 方案设计

### 修复 1：事件流自动滚动（靠近底部才滚）

避免用户手动拖到上面查历史时被踢回底部：用「滚动前距底部 ≤ 60 px 才自动滚」策略。

```python
# ui/stable_battle_panel.py 模块级辅助
def _scroll_if_near_bottom(view: QTextEdit, threshold_px: int = 60) -> None:
    sb = view.verticalScrollBar()
    distance = sb.maximum() - sb.value()
    near_bottom = distance <= threshold_px or sb.maximum() == 0
    return near_bottom  # 调用方在 setPlainText 之前判断

# set_snapshot 末尾
ev_was_near = _scroll_if_near_bottom(self._event_view)
self._event_view.setPlainText("\n".join(snapshot.get("events", [])[-120:]))
if ev_was_near:
    esb = self._event_view.verticalScrollBar()
    esb.setValue(esb.maximum())

dv_was_near = _scroll_if_near_bottom(self._data_view)
self._data_view.setPlainText("\n\n".join(lines))
if dv_was_near:
    dsb = self._data_view.verticalScrollBar()
    dsb.setValue(dsb.maximum())
```

注意：`_scroll_if_near_bottom` 必须在 `setPlainText` **前**判断（之后 maximum 会变），所以函数仅返回布尔，不直接执行滚动。

### 修复 2：吃/碰副露解码

**实施第 1 步**：写一次性脚本 `scripts/inspect_meld_subcmd.py`，从 `events_*.jsonl` 读出，逐 hand_update 前后扫描 `sub_0x021d` / `sub_0x05dc` body：

- 验证哪个 sub_cmd 的 body 结构匹配 `_extract_meld_info` 的 4/5/6/8 位置 stable 牌字节
- 找出 chi / pon 各自的 sub_cmd 与 body 偏移

定位后修改 `_decode_game_event`：

```python
elif sub_cmd in (CHI_SUB_CMD, PON_SUB_CMD):
    result.update({
        "event": "chi" if sub_cmd == CHI_SUB_CMD else "pon",
        "player": int(body[0]) if body and body[0] <= 3 else None,
        "source": SOURCE_TRUSTED_ACTION,
        "trusted": True,
    })
    meld_info = self._extract_meld_info(body)
    if meld_info:
        result.update(meld_info)
```

`GAME_SUB_NAMES` 新增对应 sub_name。

### 修复 3：财神 0x0218 解码

`sub_cmd=0x0218` 的 body 格式（4 字节）：`01 [baida_raw] 01 53` —— 第 1 字节是 marker `0x01`，第 2 字节是 baida raw（stable nibble 格式），第 3 字节 `0x01` 和第 4 字节 `0x53` 暂作魔数固定值忽略。

```python
elif sub_cmd == 0x0218 and len(body) >= 2 and int(body[0]) == 0x01:
    baida_raw = int(body[1])
    if baida_raw not in (0, HIDDEN_TILE):
        result.update({
            "event": "baida_update",
            "baida_raw": baida_raw,
            "baida_context": TILE_CONTEXT_STABLE,
            "baida_trusted": True,
            "source": SOURCE_TRUSTED_ACTION,
            "trusted": True,
        })
```

`GAME_SUB_NAMES` 加 `0x0218: "baida_update"`。

tracker 端不动 `_apply_baida` 内部逻辑——它已经支持 `baida_trusted=True` 时应用。`_apply_game_event` 在 `event == "baida_update"` 时调 `_apply_baida(game)` 即可。

### 修复 4：策略建议区显示 blocked_reason + 保守模式

#### tracker 新增 analysis_mode

```python
def analysis_mode(self) -> str:
    if not self.hand_trusted:
        return "blocked"
    if not (self.baida_trusted and self.turn_trusted and self.current_turn == "self"
            and self._effective_self_count() == 14
            and not self.mapping_store.unknowns()):
        return "conservative"
    return "full"

def should_analyze(self) -> bool:
    mode = self.analysis_mode()
    if mode == "blocked":
        return False
    # full 或 conservative 都允许；用 signature 去重
    sig = self.analysis_signature()
    return sig != self._last_analyzed_signature
```

`to_battle_state` 加：

```python
state.is_conservative = self.analysis_mode() == "conservative"
```

`analysis_signature` 加 `self.analysis_mode()` 防止模式切换时不刷新。

#### BattleState 加字段

[battle/state.py::BattleState](battle/state.py) 加 `is_conservative: bool = False`。

#### BattleService 保守提示词

[battle/service.py::analyze_state_with_ai](battle/service.py) 检查 `state.is_conservative`，若 True，在 system prompt 中说明：「当前财神/回合信息不全，请给出仅基于已知手牌的保守建议，避免提及无法判断的禁手」。

#### UI 反馈

`stable_battle_panel.py::set_snapshot` 中：

```python
reason = snapshot.get("analysis_blocked_reason", "")
mode = snapshot.get("analysis_mode", "full")  # 新增 tracker.snapshot 返回字段
if reason and mode == "blocked":
    if not self._has_advice_rendered:  # 只在没真实建议时显示
        self._recommended_label.setText(f"等待中：{reason}")
        self._strategy_label.setText("策略类型：等待门槛")
elif mode == "conservative" and not self._has_advice_rendered:
    self._strategy_label.setText("策略类型：[保守] 缺少财神/回合信息")
```

`set_advice` 调用后置 `self._has_advice_rendered = True`，避免下次 set_snapshot 覆盖真实建议。

### 修复 5：未知映射区放大

```python
mapping_box.setMinimumHeight(220)

self._mapping_table.verticalHeader().setDefaultSectionSize(28)
self._mapping_table.setFont(QFont("微软雅黑", 10))
self._mapping_table.horizontalHeader().setFont(QFont("微软雅黑", 10, QFont.Weight.Bold))

self._mapping_tile_combo.setMinimumHeight(32)
self._mapping_tile_combo.setFont(QFont("微软雅黑", 11))

self._mapping_save_btn.setMinimumHeight(32)
self._mapping_save_btn.setFont(QFont("微软雅黑", 11, QFont.Weight.Bold))

help_label = QLabel(
    "① 选中表格中的一条未识别牌值\n"
    "② 在下方下拉选实际牌面\n"
    "③ 点「保存映射」，历史会按新映射重解码"
)
help_label.setStyleSheet("color: #8b949e; font-size: 11px; padding: 4px 0;")
mapping_layout.insertWidget(0, help_label)
```

权重保持 `right.addWidget(mapping_box, 1)` 不变，靠 `setMinimumHeight` 把它撑开。

## 关联业务行为（来自预检）

| 维度 | 影响 |
|---|---|
| 主 spec [stable-reader](openspecs/specs/stable-reader/spec.md) `协议解码` Requirement | ADD chi/pon 与 baida_update 子事件 |
| 主 spec `分析门控` Requirement | MODIFIED 增加 `conservative` 模式 |
| 主 spec `映射修正` Requirement | MODIFIED 加 UX 可读性约束 |
| 已归档 stable-packet-reader / stable-reader-display-fixes | 无冲突（前者只定义 deal/hand_update/draw/discard/kong/win 等已有路径；本次为 ADDED 子事件） |
| excel-game-logger（补漏中） | 不撞代码段（B 改 closeEvent / log_row；C 改 _on_stable_message 路径） |

## 风险与回滚

| 风险 | 评估 | 缓解 |
|---|---|---|
| chi/pon sub_cmd 实测识别错误 | 高（值未敲定） | 实施第 1 步靠脚本验证，写单元测试用真实 events.jsonl 样本 |
| 0x0218 body 结构不止 `01 baida 01 53` 一种 | 中 | 实施时检查 4 局所有 0x0218 包 body 长度与 marker；不匹配时打 WARN 日志 |
| 保守模式 AI 提示词导致建议偏弱 | 中 | service 层加 `[保守模式]` 前缀，让 AI 明确知道前提；UI 也明确标注 |
| 事件流自动滚动破坏用户手动浏览历史 | 低 | 仅在每次 set_snapshot 后滚到底；用户手动拖回上面时下一帧又强制回底——折衷可考虑「靠近底部时才自动滚」（QScrollBar 距离判定） |
| 未知映射 UI 高度 220 px 把右栏挤变形 | 低 | 实测调整；必要时把右栏整体 minimum width 收紧 |

## 回滚方案

- 协议解码：删除 `sub_cmd == 0x0218 / CHI / PON` 三个分支
- 状态层：删除 `analysis_mode` 方法，`should_analyze` 还原
- UI：还原 set_snapshot 末尾的 setValue 滚动 + advice 区 placeholder + mapping 区字体高度
- BattleState：删 is_conservative 字段（service.py 同步删除分支）

每项改动独立可回滚。
