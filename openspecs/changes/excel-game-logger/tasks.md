# 任务清单：Excel 牌面流水记录 & 纠错模板（npcap 专用）

> 范围缩小确认：仅抓包(stable/npcap)模式；视觉模式暂不纳入。
> 每次状态变更一行，全字段可纠正，备注列随时填写。

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
