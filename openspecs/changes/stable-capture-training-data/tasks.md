# 任务：stable-capture-training-data

## 实施

- [x] 1. 定义训练样本 JSONL schema，覆盖局面、动作、可见信息、硬算特征和可信门槛。
- [x] 2. 新增离线导出脚本：从 `events_*.jsonl` 回放到训练样本 JSONL。
- [x] 3. 导出器复用 `analyze_snapshot()`，在数据不足时只记录阻断原因，不输出动作标签。
- [x] 3.1 稳定版 UI 增加“记录本局 / 加入训练”开关，样本写入 `record_only` / `train_enabled` / `paused` 模式。
- [ ] 4. 增加人工纠错字段，把 Excel 复盘结果转换为样本修正输入。
- [ ] 5. 新增监督学习 baseline：只重排硬算合法候选，不生成额外动作。
- [ ] 6. 增加离线评估指标：top-1/top-3 命中率、退听率、打财神率、阻断率。
- [ ] 7. 在完整计分、包牌/不死包规则完成前，保持自博弈强化训练关闭。

## 验证

- [x] `python -m compileall game stable scripts tests`
- [x] `python -m unittest discover -s tests`
- [ ] 使用至少一份 `events_*.jsonl` 回放并导出样本。
- [x] 验证未知映射、财神未可信、非我方回合不会生成动作标签。
- [x] `gitnexus detect-changes --scope all -r mahjong-learning`
