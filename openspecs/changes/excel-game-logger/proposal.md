# Excel 牌面流水记录 & 纠错模板

## 为什么要做

识别（HOG/SVM + 抓包解码）仍有偏差，但 bug 复现难：
- 打牌时无法分心核对识别结果；
- 日志是 JSON/SQLite，没法快速翻看和批注；
- 用户录屏后需要事后对照，逐帧找到识别错的一张牌，然后定位代码修。

需要一个**对人友好的复盘工具**：打完一局后直接打开 Excel，对照录屏视频，
在「识别正确?」列打勾或标记错误，在「纠正值」列填实际应该是什么，
积累样本后再针对性地修代码。

## 变更内容

1. **新增 `game/excel_logger.py`** — `ExcelGameLogger` 类
   - 每次牌面状态发生变更时追加一行（流水）
   - 列：序号 / 时间 / 事件 / 触发方 / 涉及牌 / 我方手牌 / 我方弃牌 / 我方副露 / 对方弃牌 / 对方副露 / 剩余牌数 / 数据来源 / 识别正确? / 纠正值 / 备注
   - 全部中文显示（牌名用中文，事件用中文）
   - 「识别正确?」列带下拉校验（未确认 / ✓正确 / ✗错误）
   - 关闭时（局末）保存 xlsx 文件

2. **修改 `game/session.py`** — 视觉模式（HOG 识别）集成 logger
   - `GameSession.__init__` 创建 `ExcelGameLogger`（路径在 session_dir）
   - `append_analysis_event()` 写入分析快照行（每次识别/分析完成后）
   - `close()` 时保存 xlsx

3. **修改 `ui/main_window.py`** — stable 抓包模式集成 logger
   - 第一个有效包事件到来时懒创建 `ExcelGameLogger`（路径在 `output_dir/stable_logs/`）
   - `_on_stable_message()` 里 `changed=True` 后，从 `snapshot()` 提取数据写一行
   - 停止抓包时关闭 logger

4. **`requirements.txt`** — 新增 `openpyxl>=3.1.0`

## 不在范围内

- 不改协议解码逻辑（`stable/protocol.py`、`stable/tracker.py`）
- 不改识别流水线（`vision/`）
- 不记录每次 UI 按钮操作（弃牌添加按钮等）——v1 只记录分析快照和抓包事件
- 不做「纠错汇总」Sheet（用户直接在 Sheet 1 筛选即可）

## 成功标准

- 对局结束后，`output_dir/stable_logs/` 或 `session_dir/` 下有 `牌面流水_*.xlsx`
- 打开 Excel 可见每一次牌面变更的完整中文记录（手牌/弃牌/副露均显示）
- M 列（识别正确?）有下拉选项，可点击选「✓正确」或「✗错误」
- 标题行、我方区、对方区、纠错列有不同颜色区分，便于视觉扫描

---

## 补漏：第 2 轮（2026-05-19）

### 现象

用户实测打了一把，关掉程序后 `data/stable_logs/` 下没有 xlsx 文件。

### 根因（已查实）

| 证据 | 推断 |
|---|---|
| 同时段 `data/stable_reader/raw_20260519_192721.pcap` 14 MB | 抓包链路正常，业务包到达 |
| `data/stable_logs/` 创建时间 19:27（与抓包同时段） | logger 懒创建逻辑跑过，`os.makedirs` 执行了 |
| 目录内为空 | `ExcelGameLogger.close()` 中的 `wb.save()` 从未执行 |
| [main_window.py:2577](ui/main_window.py:2577) `closeEvent` 只 stop worker | **关程序窗口路径漏调** `_close_stable_excel_logger()` |
| `log_row` 后立即 return，不调 `wb.save()` | openpyxl 一局全靠最后那次 save 落盘——只要 close 漏掉，整局数据全失 |

### 补漏范围

1. `closeEvent` 兜底：关窗口前调 `_close_stable_excel_logger()`
2. `_on_stable_capture_failed` / `_on_stable_capture_finished` 也加入 close 兜底
3. `ExcelGameLogger.log_row()` 每 N 行做一次 `wb.save()`（默认 N=5），异常被吞但留 INFO 日志
4. 启动/创建/关闭时 INFO 日志记录路径，方便排查
5. 把抓包结束时 status 栏的「Excel 已保存：...」消息也展示绝对路径

### 不在范围

- 不改 Excel 列结构、样式、纠错列下拉
- 不引入额外 worker 线程
- 不改 tracker/protocol 逻辑（那归 `stable-reader-feedback-fixes`）

### 补漏验收

- [ ] 打一局后**直接关程序窗口**（不点停止按钮），重新打开看 `data/stable_logs/` 下有 `牌面流水_*.xlsx`，内容完整
- [ ] 打一局**中途**强制终止程序（Task Manager 杀进程），看 xlsx 至少保存了开局到最后一次定期 flush 的数据
- [ ] 日志 `logs/mahjongai_*.log` 含「ExcelGameLogger created path=... seq=... saved」字样
