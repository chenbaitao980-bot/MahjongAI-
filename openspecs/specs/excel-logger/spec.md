# Capability: excel-logger

## Purpose

将每局对战事件实时写入 xlsx 文件，供人工复盘和识别准确率标注。

## Requirements

### 文件位置

`game/excel_logger.py`

### 依赖

- `openpyxl>=3.1.0`（新增到 `requirements.txt`）
- `game.tiles.tile_display_name`（已有）

### 接口

```python
class ExcelGameLogger:
    COLUMNS = [
        ("序号", 6), ("时间", 10), ("事件", 14), ("触发方", 8),
        ("涉及牌", 10), ("我方手牌", 40), ("我方弃牌", 30), ("我方副露", 22),
        ("对方弃牌", 30), ("对方副露", 22), ("剩余牌数", 8), ("数据来源", 8),
        ("识别正确?", 12), ("纠正值", 22), ("备注", 26),
    ]

    def __init__(self, path: str) -> None:
        """创建 xlsx，写表头（样式见下），初始化 _seq=0, _wb, _ws, _path。path 的父目录必须已存在。"""

    def log_row(self, *, event_type: str, actor: str, tile: str,
                self_hand: list[str], self_discards: list[str], self_melds: list[dict],
                enemy_discards: list[str], enemy_melds: list[dict],
                remaining: int, source: str, ts: str = "") -> None:
        """在 Sheet 末尾追加一行。调用 tile_display_name 转换所有 tile_id。特殊行高亮整行底色。不自动保存文件。"""

    def close(self) -> str:
        """保存 xlsx，关闭文件句柄。幂等：重复调用直接返回路径，不报错。返回最终文件路径。"""
```

### 行格式规则

**F 列（我方手牌）**：`tile_display_name(t) for t in self_hand`，结果如 "一万 三万 五条 二筒 ..."

**G 列（我方弃牌）**：同 F，按传入列表顺序（时间序）

**H / J 列（副露）**：
```python
TYPE_CN = {"pon": "碰", "chi": "吃", "kan_open": "明杠", "kan_closed": "暗杠", "kan_added": "补杠"}
# 格式：碰[一万一万一万]  吃[二筒三筒四筒]
```

**E 列（涉及牌）**：传入 tile_id 时调用 `tile_display_name` 转换；已是中文字符串时直接写；空字符串写 `""`

### 样式规范

**标题行**：深蓝底（`#2C3E50`）白色加粗字体，居中，自动换行

**数据行着色**：
- F/G/H 列（我方区）：浅蓝 `#EBF5FB`
- I/J 列（对方区）：浅橙 `#FEF0E7`
- M/N 列（纠错区）：浅黄 `#FFFACD`
- event_type == "开局发牌"：整行绿 `#D5F5E3`（覆盖上述）
- event_type == "胡牌"：整行橙 `#FDEBD0`（覆盖上述）

**M 列数据校验**：下拉选项 `"未确认,✓正确,✗错误"`，每行默认填 `"未确认"`

### 线程安全

`ExcelGameLogger` 不是线程安全的，调用方负责确保单线程调用：
- `GameSession.log_state_change()` 在 writer 线程中调用
- `main_window._log_stable_excel_row()` 在 Qt 主线程中调用

### 错误处理

`log_row()` 内部 try/except，异常静默（不影响主流程）。`close()` 静默处理重复调用。
