# 任务清单：Excel 牌面流水记录 & 纠错模板（npcap 专用）

> 范围缩小确认：仅抓包(stable/npcap)模式；视觉模式暂不纳入。
> 每次状态变更一行，全字段可纠正，备注列随时填写。

> **协同记录**（与 `stable-reader-display-fixes` 的代码层交叉）：
> 本 change 在 `ui/main_window.py` 修改了 `_on_stable_message()`（新增 `_log_stable_excel_row()` 调用）和 `_run_npcap()`（启动时关闭旧 logger）。
> 同期 `stable-reader-display-fixes` 也修改了 `_run_npcap()`（改为抓全 TCP `port_filter=0` 并启用 `auto_detect_frames`）。
> **归档前必须确认**：两处对 `_run_npcap()` 的修改互不覆盖——本 change 的 logger 关闭逻辑应在另一 change 的 npcap 启动参数变更之前/之后清楚分隔，且 `_on_stable_message()` 中的 `_log_stable_excel_row()` 调用未被另一 change 的事件处理路径绕过。

## 依赖准备

- [x] `requirements.txt`：新增 `openpyxl>=3.1.0`

## 新增文件

- [x] **新建 `game/excel_logger.py`**
  - `ExcelGameLogger.__init__(path)` — 创建 wb/ws，写表头（15列），设列宽，冻结首行，加数据校验
  - `ExcelGameLogger.log_row(...)` — 追加一行，调用 `tile_display_name` 转中文，特殊行着色
  - `ExcelGameLogger.close()` — 保存并关闭，幂等
  - 辅助函数 `_format_melds(melds)` / `_format_tiles(tile_ids)` / `_maybe_tile_cn(tile)`

## 修改 `ui/main_window.py`（stable 抓包模式）

- [x] 新增实例变量：`self._stable_excel_logger: "ExcelGameLogger | None" = None`
- [x] 新增模块级辅助函数 `_parse_stable_event_text(text)` — 从 event_log 中文文本解析 (事件类型, 触发方, 涉及牌)
- [x] 新增方法 `_log_stable_excel_row(message)` — 懒创建 logger，从 snapshot 提取数据调 `log_row()`
- [x] `_on_stable_message()` 中 `changed=True` 分支：记录 prev_log_len，apply 后对比得到 event_text，调用 `_log_stable_excel_row`
- [x] `_stop_stable_capture()` 末尾：关闭并清空 `self._stable_excel_logger`
- [x] `_run_npcap()` 开始时：若 `_stable_excel_logger` 非 None 先关闭（切换会话时重建）

## 不需要修改的文件

- `stable/tracker.py` — 不改，通过 snapshot + event_log 对比获取事件
- `battle/state.py` — 不改
- `game/session.py` — 不改（视觉模式不做）
- `battle/service.py` — 不改

## 验证

- [ ] stable 模式启动后打几轮，停止后在 `output_dir/stable_logs/` 检查 xlsx 存在
- [ ] 打开 Excel：手牌/弃牌列中文显示；事件列正确；行数与实际操作对应
- [ ] M 列有下拉（未确认/✓正确/✗错误），点选有效
- [ ] 开局发牌行浅绿，胡牌行浅橙
- [ ] F~H 列浅蓝，I~J 列浅橙，M~N 列浅黄
- [ ] 首行冻结，自动筛选可用
- [ ] 切换/重开 stable 抓包：旧 xlsx 已保存，新会话新文件

---

## 补漏：第 2 轮（2026-05-19）

### 实施

- [x] 9. `ui/main_window.py::closeEvent` 在 `self._stable_capture_worker.wait(3000)` 后追加 `self._close_stable_excel_logger()`
- [x] 10. `ui/main_window.py::_on_stable_capture_failed` 追加 `self._close_stable_excel_logger()`
- [x] 11. `ui/main_window.py::_on_stable_capture_finished` 追加 `self._close_stable_excel_logger()`
- [x] 12. `game/excel_logger.py::ExcelGameLogger.__init__` 增加 `flush_every: int = 5` 参数，存 `self._flush_every`
- [x] 13. `game/excel_logger.py::ExcelGameLogger` 新增 `_flush()` 私有方法（吞异常但记 warning 日志）
- [x] 14. `game/excel_logger.py::ExcelGameLogger.log_row` 末尾按 `self._seq % self._flush_every == 0` 调 `_flush()`
- [x] 15. `game/excel_logger.py` 顶部加 `import logging; _LOGGER = logging.getLogger("mahjongai.excel_logger")`，`__init__`/`close`/`_flush` 写 INFO/WARNING 日志
- [x] 16. `ui/main_window.py::_close_stable_excel_logger` 状态栏消息改为完整路径

### 补漏验证

- [ ] `gitnexus detect-changes --scope all -r mahjong-learning` 无异常范围外变更
- [ ] 实测：启动抓包 → 打一局 → **点右上角 X 关闭窗口** → 重启 → `data/stable_logs/牌面流水_*.xlsx` 存在且数据完整
- [ ] 实测：启动抓包 → 写入 ≥5 行后通过任务管理器杀掉进程 → 重启后 xlsx 至少有前 5 行
- [ ] 日志 `logs/mahjongai_*.log` 含 `ExcelGameLogger created` / `ExcelGameLogger flushed` / `ExcelGameLogger closed` INFO 行
