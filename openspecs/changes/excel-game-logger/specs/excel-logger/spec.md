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
