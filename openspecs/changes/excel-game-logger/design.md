# 设计：Excel 牌面流水记录 & 纠错模板

## 架构图

```
  [stable 模式]                          [视觉/battle 模式]
  PacketStateTracker.apply()              BattleService._analyze()
        ↓ changed=True                          ↓
  main_window._on_stable_message()        GameSession.append_analysis_event()
        ↓                                       ↓
  ExcelGameLogger.log_row(...)            GameSession.log_state_change(...)
                                                ↓
                                          ExcelGameLogger.log_row(...)
```

## Excel 文件结构

### Sheet 1: 牌面流水

| 列 | 中文名 | 内容 | 宽度 |
|---|---|---|---|
| A | 序号 | 自增整数 | 6 |
| B | 时间 | HH:MM:SS | 10 |
| C | 事件 | 中文（见事件映射表） | 14 |
| D | 触发方 | 我方 / 对方 / — | 8 |
| E | 涉及牌 | 中文牌名（如"三万"）或空 | 10 |
| F | 我方手牌 | 空格分隔中文，如"一万 三万 五条" | 40 |
| G | 我方弃牌 | 空格分隔，按时序 | 30 |
| H | 我方副露 | 格式：碰[三万三万三万] 吃[一万二万三万] | 22 |
| I | 对方弃牌 | 空格分隔，按时序 | 30 |
| J | 对方副露 | 格式同 H | 22 |
| K | 剩余牌数 | 整数 | 8 |
| L | 数据来源 | 抓包 / 视觉 / 手动 | 8 |
| **M** | **识别正确?** | **下拉：未确认 / ✓正确 / ✗错误** | 12 |
| **N** | **纠正值** | 用户填写（实际应该是什么） | 22 |
| **O** | **备注** | 用户填写 | 26 |

### 样式规范

- **标题行**：背景 `#2C3E50`（深灰蓝），字体白色加粗 11pt，高度 22px
- **冻结首行**：滚动时标题始终可见
- **F～H 列（我方）**：交替底色 `#EBF5FB`（浅蓝），便于视觉分离
- **I～J 列（对方）**：交替底色 `#FEF0E7`（浅橙）
- **M～N 列（纠错）**：底色 `#FFFACD`（浅黄），提示用户填写
- **开局行（事件="开局发牌"）**：整行底色 `#D5F5E3`（浅绿）
- **胡牌行（事件="胡牌"）**：整行底色 `#FDEBD0`（浅橙）
- 所有数据行：字体 10pt，行高 16px
- 自动筛选（Auto Filter）：首行开启

### 数据校验（M 列）

```python
from openpyxl.worksheet.datavalidation import DataValidation
dv = DataValidation(
    type="list",
    formula1='"未确认,✓正确,✗错误"',
    allow_blank=False,
    showDropDown=False,  # 显示下拉箭头
)
dv.sqref = "M2:M10000"
ws.add_data_validation(dv)
```

## `ExcelGameLogger` 接口设计

```python
# game/excel_logger.py

class ExcelGameLogger:
    def __init__(self, path: str) -> None:
        """创建 xlsx 文件，写表头，初始化行计数器。"""

    def log_row(
        self,
        *,
        event_type: str,        # 中文事件名
        actor: str,             # "我方" | "对方" | "—"
        tile: str,              # 涉及牌中文名，无则 ""
        self_hand: list[str],   # tile_id 列表
        self_discards: list[str],
        self_melds: list[dict], # [{"type": "pon", "tiles": ["3m","3m","3m"]}, ...]
        enemy_discards: list[str],
        enemy_melds: list[dict],
        remaining: int,
        source: str,            # "抓包" | "视觉" | "手动"
        ts: str = "",           # 时间字符串 HH:MM:SS，空则用 datetime.now()
    ) -> None:
        """追加一行数据。内部调用 tile_display_name 转中文。不自动保存文件。"""

    def close(self) -> str:
        """保存并关闭文件，返回文件路径。幂等：重复调用不报错。"""
```

### 内部辅助

```python
def _format_melds(melds: list[dict]) -> str:
    """[{"type":"pon","tiles":["3m","3m","3m"]}] → "碰[三万三万三万]" """
    parts = []
    for m in melds:
        type_cn = {"pon":"碰","chi":"吃","kan_open":"明杠",
                   "kan_closed":"暗杠","kan_added":"补杠"}.get(m.get("type",""),"副露")
        tiles_cn = "".join(tile_display_name(t) for t in m.get("tiles",[]))
        parts.append(f"{type_cn}[{tiles_cn}]")
    return "  ".join(parts)

def _format_tiles(tile_ids: list[str]) -> str:
    """["3m","1z"] → "三万 东" """
    return " ".join(tile_display_name(t) for t in tile_ids)
```

## `game/session.py` 改动

```python
# __init__ 末尾
from game.excel_logger import ExcelGameLogger
self._excel_logger = ExcelGameLogger(
    os.path.join(self.session_dir, "牌面流水.xlsx")
)

# 新增方法
def log_state_change(
    self,
    event_type: str,
    actor: str,
    tile: str,
    self_hand: list[str],
    self_discards: list[str],
    self_melds: list[dict],
    enemy_discards: list[str],
    enemy_melds: list[dict],
    remaining: int,
    source: str = "视觉",
    ts: str = "",
) -> None:
    """写一行到 Excel（非阻塞；异常静默）。"""
    try:
        self._excel_logger.log_row(
            event_type=event_type, actor=actor, tile=tile,
            self_hand=self_hand, self_discards=self_discards,
            self_melds=self_melds, enemy_discards=enemy_discards,
            enemy_melds=enemy_melds, remaining=remaining,
            source=source, ts=ts,
        )
    except Exception:
        pass

# append_analysis_event() 末尾追加：
    self.log_state_change(
        event_type="分析快照",
        actor="我方",
        tile=event.get("recommended_discard", ""),
        self_hand=event.get("hand", []),
        self_discards=event.get("self_discards", []),
        self_melds=event.get("self_melds", []),
        enemy_discards=event.get("enemy_discards", []),
        enemy_melds=event.get("enemy_melds", []),
        remaining=event.get("remaining_tiles", 0),
        source="视觉",
    )

# close() 末尾追加：
    try:
        self._excel_logger.close()
    except Exception:
        pass
```

注：`append_analysis_event()` 现有的 `event` 参数已经包含 `hand`、`remaining_tiles` 等字段，
但缺少 `self_discards`、`self_melds`、`enemy_*` 字段。需要在 `battle/service.py`
的 `_analyze()` 调用 `append_analysis_event()` 时补充这些字段。

## `ui/main_window.py` 改动（stable 模式）

```python
# 新增实例变量（在 __init__ 里）
self._stable_excel_logger: ExcelGameLogger | None = None
self._stable_excel_row_seq: int = 0

# 修改 _on_stable_message()
def _on_stable_message(self, message):
    changed = self._stable_tracker.apply(message)
    if not changed:
        # 已有逻辑不变
        ...
        return
    self._stable_non_game_messages = 0
    # ← 新增：写 Excel 行
    self._log_stable_excel_row(message)
    # 已有逻辑不变
    self._refresh_stable_snapshot()
    ...

# 新增方法
def _log_stable_excel_row(self, message) -> None:
    snap = self._stable_tracker.snapshot()
    if self._stable_excel_logger is None:
        import os
        from game.excel_logger import ExcelGameLogger
        from datetime import datetime
        out_dir = os.path.join(self._output_dir, "stable_logs")
        os.makedirs(out_dir, exist_ok=True)
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(out_dir, f"牌面流水_{ts_str}.xlsx")
        self._stable_excel_logger = ExcelGameLogger(path)

    local_pid = snap["local_player"]
    opp_pid = snap["opponent_player"]
    players = snap.get("players", {})
    self_p = players.get(str(local_pid)) or players.get(local_pid, {})
    opp_p = players.get(str(opp_pid)) or players.get(opp_pid, {})

    # 从 event_log 最后一行提取事件信息（已是中文）
    last_event_text = snap.get("events", [""])[-1] if snap.get("events") else ""
    event_type, actor, tile = _parse_event_text(last_event_text)

    self._stable_excel_logger.log_row(
        event_type=event_type,
        actor=actor,
        tile=tile,
        self_hand=self_p.get("hand", []),
        self_discards=self_p.get("discards", []),
        self_melds=self_p.get("melds", []),
        enemy_discards=opp_p.get("discards", []),
        enemy_melds=opp_p.get("melds", []),
        remaining=snap.get("remaining_tiles", 0),
        source="抓包",
        ts=message.ts[11:19] if message.ts else "",
    )

# 辅助函数（模块级）
def _parse_event_text(text: str) -> tuple[str, str, str]:
    """从 event_log 文本（如"12:34:56 我方打出三万"）解析事件类型/触发方/涉及牌。"""
    import re
    text = re.sub(r"^\d{2}:\d{2}:\d{2}\s+", "", text).strip()
    for actor in ("我方", "对面"):
        if text.startswith(actor):
            body = text[len(actor):]
            for kw in ("摸牌", "打出", "碰牌", "吃牌", "明杠", "暗杠", "补杠", "手牌更新"):
                if body.startswith(kw):
                    tile = body[len(kw):].strip()
                    return kw, ("我方" if actor == "我方" else "对方"), tile
            return body, ("我方" if actor == "我方" else "对方"), ""
    if "开局" in text:
        return "开局发牌", "—", ""
    if "财神" in text:
        return "财神", "—", text.replace("财神更新：", "").strip()
    if "胡牌" in text:
        return "胡牌", "—", ""
    return text, "—", ""

# 修改 _stop_stable_capture() 末尾
    if self._stable_excel_logger:
        self._stable_excel_logger.close()
        self._stable_excel_logger = None
```

## 风险与注意事项

| 风险 | 评估 | 缓解 |
|------|------|------|
| openpyxl 写大文件卡顿 | 单局通常 < 500 行，可接受 | `write_only=False`，内存中追加，局末一次性保存 |
| 多线程写 Excel | `log_row()` 被主线程调用，`GameSession._writer_loop` 在后台线程 | GameSession 的 log_state_change 在 writer 线程里调用；stable 的 log 在 Qt 主线程里调用——分别保证单线程 |
| session.py 的 append_analysis_event 中缺少字段 | 需要同步修改 service.py 调用处 | 见 tasks.md |
| 文件名包含中文 | Windows/Linux 均支持，需 UTF-8 文件系统 | openpyxl 默认 UTF-8 |

## GitNexus 影响范围

直接改动文件：
- `game/excel_logger.py`（新建）
- `game/session.py` → d=1 直接调用方：`battle/service.py`（`append_analysis_event`），影响点是新增字段，向后兼容
- `ui/main_window.py` → 无外部调用方，自包含
- `battle/service.py` → `_analyze()` 调用 `append_analysis_event` 时补充字段
- `requirements.txt` → 新增依赖

不影响：`stable/tracker.py`、`battle/state.py`、`battle_panel.py`、所有 vision 模块
