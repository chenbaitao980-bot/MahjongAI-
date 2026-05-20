# Delta: round2-bugfix-batch

## 与主规范关系

无冲突。本次修改不改变已有事件处理语义，只修正 3 处具体 bug。

## 变更摘要

| 维度 | 状态 |
|------|------|
| 主规范 Req 命中 | 协议解码（MODIFIED：meld 判据）、分析门控（MODIFIED：baida 保留）、映射修正（MODIFIED：弹框 UX） |
| 其他 active change 撞车 | 无 |
| 归档完整性 | ✅ |

## 改动明细

### stable/protocol.py

`_extract_meld_info(body)` 增加 body[3] 判据区分 pon / kan_open。body[3]<=0x03 时 exposed=body[4,5,6]，body[3]>=0x04 时 exposed=body[4,5,6,7]。

### stable/tracker.py

`reset()` 不再清空 `baida_tile` 和 `baida_trusted`。

### ui/stable_battle_panel.py

移除 mapping_box（table+combo+btn）。新增 `UnknownTileDialog` 交互弹框替代 `_notify_unknowns` 中的 QMessageBox。
