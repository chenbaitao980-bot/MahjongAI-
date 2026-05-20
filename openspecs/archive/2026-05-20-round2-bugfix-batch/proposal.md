# round2-bugfix-batch

## 为什么

用户实测又一局后发现 4 个并存问题：

1. **财神 UI 不更新** — 日志已识别财神但状态栏始终「等待抓包解析财神」。根因：`baida_update` 在 `deal` 或 `hand_update` 触发的 `reset()` 之前到达时，刚设好的 baida 被清空。
2. **碰误判为明杠** — UI 显示「明杠[南南南南]」4 张，实际是碰（3 张）。根因：`_extract_meld_info` 用 `len(set(tiles_raw))==1` 判杠，碰的 3 同+claimed 同=4 同值全部误判。协议数据证实 body[3]=0x03 时恒为 3 tiles（chi/pon），body[3]>=0x04 才是 kong。
3. **未知映射区改弹框** — 用户要求去掉右栏映射 table，改为识别失败时直接弹交互对话框让用户选牌并永久保存。
4. **听牌信息显示** — 游戏 UI 有听牌标记（胡/100 胡/2 张），用户要求在面板中显示。需进一步协议研究，本轮先做可行性调研，下轮实现。

## 影响面

| 文件 | 改动 |
|------|------|
| stable/protocol.py | `_extract_meld_info` 加 body[3] 判据 |
| stable/tracker.py | `reset()` 保留 baida；去掉 snapshot 的 unknowns 列表（改弹框驱动） |
| stable/mapping.py | 不变 |
| ui/stable_battle_panel.py | 移除 mapping_box；新增 `UnknownTileDialog` 弹框；显示听牌信息占位 |
| ui/main_window.py | 弹框信号连接 |

## 验收

- [ ] 财神在 baida_update 到达后立即显示，不受 deal/hand_update reset 影响
- [ ] 碰的副露区显示 3 张（碰[南南南]），不再显示 4 张
- [ ] 识别失败时弹出交互对话框，选牌后永久保存
- [ ] 右栏「未知映射修正」table 区域已移除
