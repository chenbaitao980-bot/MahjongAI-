# 设计：round2-bugfix-batch

## Bug 2：财神 reset 被清空

### 数据生命周期

```
写入链: baida_update(0x0218) → _apply_baida() → self.baida_tile / self.baida_trusted
读取链: snapshot() → set_snapshot() → _baida_status.setText()
破坏点: deal/hand_update → reset() → baida_tile="" / baida_trusted=False
```

### 修复方案

`reset()` 不再清空 `baida_tile` 和 `baida_trusted`。财神值仅被 `_apply_baida()` 覆盖（新的 `baida_update` 到达时）。

理由：baida_update 可能在 deal 之前到达（协议包乱序），reset 清除会丢失刚解析到的有效值。保留旧值最坏情况是短暂显示上一局财神，但新 baida_update 到达时立即覆盖。

## Bug 3：碰误判为明杠

### 协议数据证据

| body[1] | body[3] | 含义 | 样本数 |
|---------|---------|------|--------|
| 0x01 | 0x03 | 吃（3 tiles） | 64 |
| 0x02 | 0x03 | **碰**（3 tiles） | 14 |
| 0x03 | 0x04 | 杠（4 tiles body[4-7]） | 1 |
| 0x05 | 0x04 | 杠（4 tiles body[4-7]） | 1 |

body[3] = exposed tile count。当前代码忽略此字段，仅靠 tile 值去重判断。

### 修复方案

`_extract_meld_info(body)` 增加 body[3] 判据：

- body[3] <= 0x03：exposed = body[4,5,6]，claimed = body[8]
  - 3 tiles 全同 → **pon**（返回 3 tiles）
  - 3 tiles 顺序 → **chi**（返回 3 tiles）
- body[3] >= 0x04：exposed = body[4,5,6,7]（4 tiles）
  - 全同 → **kan_open**（返回 4 tiles）

同时更新 `_decode_game_event` 的 0x021F 分支，让 body[3]>=0x04 的 kong 走独立提取路径。

## Bug 4：未知映射改弹框

### 当前状态

右栏有 mapping_box（table + combo + 保存按钮）。用户需手动选行→选牌→点保存。

### 修复方案

1. 移除 `_setup_ui` 中 mapping_box 整个区域
2. `_notify_unknowns` 改为弹出 `UnknownTileDialog`（QDialog）：
   - 显示未识别牌值
   - 内置 combo 选择正确牌面
   - 点「确认」后触发 `mapping_save_requested` 信号永久保存
3. 信号链路不变：dialog → mapping_save_requested → main_window._on_stable_mapping_save → mapping_store.save_tile_mapping

## Bug 5：听牌信息（调研）

游戏 UI 的听牌面板（胡/100胡/2张）可能来自 action_notify（sub_cmd=0x0016）或客户端本地计算。本轮先记录需求，下轮做协议解析。但我们的本地 shanten/ukeire 分析已能算出同等信息，可在 AnalysisPanel 中增加展示。

## 回滚方案

每项改动独立可回滚：reset() 加回清空行、_extract_meld_info 去掉 body[3] 判据、mapping_box 恢复。
