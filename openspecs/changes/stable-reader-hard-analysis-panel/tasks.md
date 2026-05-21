# 任务：stable-reader-hard-analysis-panel

## 实施

- [x] 1. 新增 `game/stable_hard_analysis.py`，输入 `snapshot()`，输出稳定版硬算结构。
- [x] 2. 在硬算模块中实现当前状态、财神、当前向听、是否听牌、听牌列表、最佳进听打法、有效进张、当前建议、建议原因、强提醒、财神风险、数据可信度。
- [x] 3. 提供 `getTingTiles()`/`get_ting_tiles()`，枚举进张并返回剩余张数。
- [x] 4. 修改 `ui/stable_battle_panel.py`，右侧去掉旧 `AnalysisPanel`，改为硬算文本面板。
- [x] 5. 防止 AI 流式文本和 `set_advice()` 覆盖右侧硬算结果。
- [x] 6. 新增 `tests/test_stable_hard_analysis.py` 覆盖数据不足与 14 张手牌硬算建议。

## 验证

- [x] `python -m compileall game ui tests`
- [x] `python -m unittest tests.test_stable_hard_analysis tests.test_stable_reader`
- [x] `gitnexus detect-changes --scope all -r mahjong-learning`

## 追加实施：策略模型重排

- [x] 新增 `game/stable_strategy_model.py`，对硬算合法候选做本地特征模型重排，不生成额外动作。
- [x] 稳定版右侧 UI 展示模型状态、推荐来源和候选重排，且只使用当前 `snapshot()` 同源分析结果。
- [x] 收紧推荐门槛：缺可信手牌、财神、回合、14 张有效牌、有未知映射、敌方回合或可选动作时不输出出牌候选。

## 追加实施：对方预测展示

- [x] 8. 在 `game/stable_hard_analysis.py` 增加对方手牌可能性预测和对方进度预测字段。
- [x] 9. 预测逻辑只使用当前 `snapshot()` 的可见信息，不读取或展示对方隐藏手牌。
- [x] 10. 在 `ui/stable_battle_panel.py` 右侧稳定版硬算文本中展示两项预测。
- [x] 11. 增加或更新 `tests/test_stable_hard_analysis.py`，覆盖对方预测字段存在且使用不确定表达。

## 追加验证

- [x] `python -m compileall game ui tests`
- [x] `python -m unittest tests.test_stable_hard_analysis`
- [x] `gitnexus detect-changes --scope all -r mahjong-learning`
