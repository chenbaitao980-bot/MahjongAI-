# 回归测试：opponent-prediction-strategy

## 测试目标
验证对手预测结果是否正确整合到出牌策略中，且对手预测关闭时行为与修改前一致。

## 测试环境
- Python 3.12
- 依赖：game/stale_strategy_model.py, game/stable_hard_analysis.py, game/opponent_inference.py

## 测试用例

### TC1：对手预测关闭时行为一致
**入参：**
```python
snapshot = {
    "local_player": 0,
    "opponent_player": 1,
    "players": {
        0: {"hand": ["1m","2m","3m","4m","5m","6m","7m","8m","9m","1p","2p","3p","4p","5p"], "discards": [], "melds": []},
        1: {"hand": [], "discards": [], "melds": [], "hand_count": 13},
    },
    "baida_tile": "5z",
    "baida_trusted": True,
    "remaining_tiles": 80,
    "current_turn": "self",
    "turn_trusted": True,
    "hand_trusted": True,
    "phase": "playing",
}
analysis_config = {"opponent_prediction": {"enabled": False}}
```
**期望出参：**
- `candidates` 非空
- `candidates[0].model_reasons` 中不含 `[预测]` 前缀的原因
- 与修改前的候选排序一致

### TC2：对手预测开启时危险牌评分降低
**入参：**
```python
# 构造一个 snapshot，让对手预测认为某张牌是高危险
snapshot = {
    "local_player": 0,
    "opponent_player": 1,
    "players": {
        0: {"hand": ["1m","2m","3m","4m","5m","6m","7m","8m","9m","1p","2p","3p","4p","5p"], "discards": [], "melds": []},
        1: {"hand": [], "discards": ["6m","7m","8m"], "melds": [{"tiles": ["1m","1m","1m"]}], "hand_count": 10},
    },
    "baida_tile": "5z",
    "baida_trusted": True,
    "remaining_tiles": 30,
    "current_turn": "self",
    "turn_trusted": True,
    "hand_trusted": True,
    "phase": "playing",
}
analysis_config = {"opponent_prediction": {"enabled": True, "particle_count": 1000}}
```
**期望出参：**
- `candidates` 中，被对手预测标记为危险的牌的 `model_score` 低于未被标记的等价牌
- `candidates[0].model_reasons` 可能包含 `[预测]对手预测高危险` 或 `[预测]对手预测中危险`

### TC3：建议原因红色高亮
**入参：**
- 运行 TC2 的分析
- 调用 `_format_strategy_analysis_html`

**期望出参：**
- 返回的 HTML 中，`[预测]` 和 `对手预测X危险` 文本被 `<span style="color:#e74c3c">` 包裹

### TC4：对手听牌概率越高，danger 权重越大
**入参：**
```python
# 构造两个 snapshot，区别仅在于对手副露数量（影响听牌概率）
# snapshot_a: 对手无副露
# snapshot_b: 对手3组副露
```
**期望出参：**
- snapshot_b 中，同等危险度的牌的 `model_score` 低于 snapshot_a（因为 tenpai_danger_multiplier 更大）

## 断言规则
1. 对手预测关闭时，`model_reasons` 中不含 `[预测]` 前缀
2. 对手预测开启时，危险牌的 `model_score` <= 非危险等价牌的 `model_score`
3. HTML 输出中包含 `<span style="color:#e74c3c">对手预测` 或 `<span style="color:#e74c3c">[预测]`
