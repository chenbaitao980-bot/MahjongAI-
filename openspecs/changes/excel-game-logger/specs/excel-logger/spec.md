# 规范：ExcelGameLogger

## 文件位置

`game/excel_logger.py`

## 依赖

- `openpyxl>=3.1.0`（新增到 `requirements.txt`）
- `game.tiles.tile_display_name`（已有）

## 接口

```python
class ExcelGameLogger:
    COLUMNS = [
        ("序号", 6), ("时间", 10), ("事件", 14), ("触发方", 8),
        ("涉及牌", 10), ("我方手牌", 40), ("我方弃牌", 30), ("我方副露", 22),
        ("对方弃牌", 30), ("对方副露", 22), ("剩余牌数", 8), ("数据来源", 8),
        ("识别正确?", 12), ("纠正值", 22), ("备注", 26),
    ]

    def __init__(self, path: str) -> None:
        """
        创建 xlsx，写表头（样式见下），初始化 _seq=0, _wb, _ws, _path。
        path 的父目录必须已存在。
        """

    def log_row(
        self,
        *,
        event_type: str,
        actor: str,
        tile: str,
        self_hand: list[str],
        self_discards: list[str],
        self_melds: list[dict],
        enemy_discards: list[str],
        enemy_melds: list[dict],
        remaining: int,
        source: str,
        ts: str = "",
    ) -> None:
        """
        在 Sheet 末尾追加一行。调用 tile_display_name 转换所有 tile_id。
        特殊行（开局发牌、胡牌）高亮整行底色。
        不自动保存文件（避免每行 IO）。
        """

    def close(self) -> str:
        """
        保存 xlsx 到 self._path，关闭文件句柄。
        幂等：重复调用直接返回路径，不报错。
        返回最终文件路径。
        """
```

## 行格式规则

### F 列（我方手牌）
```
tile_display_name(t) for t in self_hand
→ "一万 三万 五条 二筒 ..."
```

### G 列（我方弃牌）
同 F，按传入列表顺序（时间序）

### H / J 列（副露）
```python
def _format_melds(melds: list[dict]) -> str:
    TYPE_CN = {
        "pon": "碰", "chi": "吃",
        "kan_open": "明杠", "kan_closed": "暗杠", "kan_added": "补杠",
    }
    parts = []
    for m in melds:
        cn = TYPE_CN.get(m.get("type", ""), "副露")
        tiles_cn = "".join(tile_display_name(t) for t in m.get("tiles", []))
        parts.append(f"{cn}[{tiles_cn}]")
    return "  ".join(parts)
```

### E 列（涉及牌）
- 传入 tile_id（如 `"3m"`）时调用 `tile_display_name` 转换
- 传入已是中文字符串时直接写（`_parse_event_text` 可能已解析）
- 空字符串写 `""`

## 样式规范

### 标题行（第 1 行）
```python
from openpyxl.styles import PatternFill, Font, Alignment

header_fill = PatternFill("solid", fgColor="2C3E50")
header_font = Font(color="FFFFFF", bold=True, size=11)
header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
```

### 数据行（第 2 行起）
```python
FILL_SELF  = PatternFill("solid", fgColor="EBF5FB")   # 我方区
FILL_ENEMY = PatternFill("solid", fgColor="FEF0E7")   # 对方区
FILL_FIX   = PatternFill("solid", fgColor="FFFACD")   # 纠错列
FILL_DEAL  = PatternFill("solid", fgColor="D5F5E3")   # 开局行（整行）
FILL_WIN   = PatternFill("solid", fgColor="FDEBD0")   # 胡牌行（整行）
```

列着色规则：
- F/G/H（索引 5/6/7）：`FILL_SELF`
- I/J（索引 8/9）：`FILL_ENEMY`
- M/N（索引 12/13）：`FILL_FIX`
- event_type == "开局发牌"：整行 `FILL_DEAL`（覆盖上述）
- event_type == "胡牌"：整行 `FILL_WIN`（覆盖上述）

### M 列数据校验
```python
from openpyxl.worksheet.datavalidation import DataValidation
dv = DataValidation(
    type="list",
    formula1='"未确认,✓正确,✗错误"',
    allow_blank=False,
    showDropDown=False,
    showErrorMessage=True,
    error="请从下拉列表选择",
    errorTitle="输入无效",
)
dv.sqref = "M2:M10000"
ws.add_data_validation(dv)
```

### M 列默认值
每行写入时 M 列填 `"未确认"`。

## 线程安全

`ExcelGameLogger` **不是线程安全的**，调用方负责确保单线程调用：
- `GameSession.log_state_change()` 在 writer 线程中调用
- `main_window._log_stable_excel_row()` 在 Qt 主线程中调用

## 错误处理

`log_row()` 内部 try/except，异常静默（不影响主流程）。
`close()` 静默处理重复调用，文件已关闭时直接返回路径。

---

## MODIFIED Requirements（补漏，第 2 轮）

### Requirement: 持久化时机与 close 路径覆盖

`ExcelGameLogger` 必须保证调用方在以下任一路径退出时数据落盘：

1. 用户点击"停止抓包"按钮 → `_on_stable_stop_requested`
2. 用户直接关闭主窗口 → `closeEvent`
3. 抓包线程报错失败 → `_on_stable_capture_failed`
4. 抓包线程自然结束 → `_on_stable_capture_finished`

`ExcelGameLogger.__init__` 必须接受可选参数 `flush_every: int = 5`，并在 `log_row` 每写入 `flush_every` 行时调用一次 `wb.save(path)`（吞异常）。

`ExcelGameLogger.__init__` / `close` / 周期 flush 必须通过 `logging.getLogger("mahjongai.excel_logger")` 写 INFO 日志，至少包含：

- created 时：完整路径、`flush_every`
- 周期 flush 成功时：当前 `_seq`、路径
- close 时：当前 `_seq`、路径、是否实际保存

#### Scenario: 关程序窗口路径数据完整

- **WHEN** 用户启动 stable 抓包写入至少 5 行后**关闭主窗口**（不点停止按钮）
- **THEN** `data/stable_logs/牌面流水_*.xlsx` 存在且包含所有已 `log_row` 的数据

#### Scenario: 进程被强制终止仍保留已 flush 数据

- **WHEN** 已写入 5 行后通过任务管理器结束进程
- **THEN** 重启后 xlsx 至少含前 5 行（受 `flush_every` 限制，最坏丢失最后 `flush_every-1` 行）

#### Scenario: 多路径 close 幂等

- **WHEN** 任意两条退出路径相继触发 `_close_stable_excel_logger`
- **THEN** 不抛异常、不重复写文件，第二次调用直接返回路径
