# 设计：opponent-prediction-strategy

## 当前状态

### 对手预测模块（`game/opponent_inference.py`）
已完整实现，输出 `OpponentPrediction` 包含：
- `tenpai_probability`：对手听牌概率（0~1）
- `danger_tiles`：对我方危险牌列表（含 probability/level/reasons）
- `wait_probabilities`：对手可能听的牌及概率
- `tile_probabilities`：对手高概率持有的牌
- `shanten_distribution`：对手向听分布

### 策略模型（`game/stable_strategy_model.py`）
当前 `StrategyModelContext` 仅包含：
- current_shanten, remaining_tiles, caishen_tile
- enemy_discards, self_discards, enemy_meld_tiles, self_meld_tiles

**没有 opponent_prediction 字段。**

当前 `score_discard_candidate` 的危险度计算（`_danger_score`）仅基于：
- 现物（enemy_discards 中是否出现过）
- 可见数量
- 中张惩罚
- 对手清一色推断（基于 enemy_meld_tiles 花色分布）
- 生牌阶段加成

**没有使用 opponent_inference 的预测结果。**

### 硬算分析（`game/stable_hard_analysis.py`）
`analyze_snapshot` 中：
1. 先调用 `infer_opponent_hand()` 得到 `opponent_prediction`
2. 但 `rank_discard_candidates()` 调用时**没有传入** `opponent_prediction`
3. `opponent_prediction` 只用于生成展示文本（opponent_hand_prediction / opponent_progress_prediction）

### UI 展示（`ui/stable_battle_panel.py`）
- `_format_strategy_analysis_html()` 渲染 advice_reason，当前没有红色高亮机制
- 截图中的红框区域显示 advice_reason 纯文本

## 方案

### 1. StrategyModelContext 扩展

```python
@dataclass(frozen=True)
class StrategyModelContext:
    current_shanten: int | None
    remaining_tiles: int
    caishen_tile: str | None
    enemy_discards: list[str] = field(default_factory=list)
    self_discards: list[str] = field(default_factory=list)
    enemy_meld_tiles: list[str] = field(default_factory=list)
    self_meld_tiles: list[str] = field(default_factory=list)
    opponent_prediction: Any = None  # OpponentPrediction | None
```

### 2. score_discard_candidate 增加对手预测评分

在现有评分公式基础上，增加以下维度：

#### 2.1 危险牌直接惩罚
```python
opponent_danger_bonus = 0
if ctx.opponent_prediction and ctx.opponent_prediction.enabled:
    for dt in ctx.opponent_prediction.danger_tiles:
        if dt.tile == discard:
            # danger_tiles 的 probability 已经是综合评分（0~0.99）
            # high=probability>=0.35, medium>=0.16, low<0.16
            if dt.level == "high":
                opponent_danger_bonus += 80
            elif dt.level == "medium":
                opponent_danger_bonus += 35
            else:
                opponent_danger_bonus += 12
```

#### 2.2 对手听牌概率加权
```python
# 对手听牌概率越高，danger 权重越大
tenpai = ctx.opponent_prediction.tenpai_probability if ctx.opponent_prediction else 0.0
tenpai_danger_multiplier = 1.0 + tenpai * 0.8  # 听牌100%时 danger 权重 *1.8
```

#### 2.3 对手可能等待牌惩罚
```python
for wp in ctx.opponent_prediction.wait_probabilities:
    if wp.tile == discard:
        opponent_danger_bonus += wp.probability * 60  # 最高约60分
```

#### 2.4 综合到 score 公式
```python
# 原公式
score -= danger * _danger_weight(ctx.remaining_tiles)
# 新公式
score -= danger * _danger_weight(ctx.remaining_tiles) * tenpai_danger_multiplier
score -= opponent_danger_bonus
```

### 3. _danger_score 增强

在 `_danger_score` 中增加对手预测的直接调用：
```python
def _danger_score(tile: str, ctx: StrategyModelContext) -> int:
    # ... 现有逻辑 ...
    
    # 新增：对手预测危险牌
    if ctx.opponent_prediction and ctx.opponent_prediction.enabled:
        for dt in ctx.opponent_prediction.danger_tiles:
            if dt.tile == tile:
                if dt.level == "high":
                    danger += 50
                elif dt.level == "medium":
                    danger += 25
                else:
                    danger += 10
    
    return max(0, min(100, danger))
```

### 4. _reasons 增加对手预测原因

```python
def _reasons(..., opponent_danger_level: str = ""):
    # ... 现有逻辑 ...
    if opponent_danger_level:
        reasons.append(f"对手预测{opponent_danger_level}危险")
```

### 5. stable_hard_analysis.py 传参

```python
# 在 analyze_snapshot 中
opponent_prediction = infer_opponent_hand(snapshot, opponent_config)
# ...
candidates = rank_discard_candidates(
    candidates,
    StrategyModelContext(
        current_shanten=current_shanten,
        remaining_tiles=remaining_tiles,
        caishen_tile=baida,
        enemy_discards=enemy_discards,
        self_discards=self_discards,
        enemy_meld_tiles=enemy_meld_tiles,
        self_meld_tiles=self_meld_tiles,
        opponent_prediction=opponent_prediction,  # 新增
    ),
)
```

### 6. UI 红色高亮

在 `_format_strategy_analysis_html` 中：
```python
# advice_reason 中如果包含"对手预测"相关文本，用红色
advice_reason_html = escape(analysis.advice_reason)
if "对手预测" in advice_reason_html or "危险" in advice_reason_html:
    # 将相关片段用红色包裹
    advice_reason_html = advice_reason_html.replace(
        "对手预测", 
        '<span style="color:#e74c3c">对手预测</span>'
    )
```

更精确的做法：在 `_advice_reason` 中标记哪些原因是"对手预测相关"，然后 UI 根据标记渲染颜色。

**推荐方案**：
- `HardDiscardCandidate.model_reasons` 中增加对手预测原因（已有字段，直接追加）
- `_advice_reason` 中拼接原因时，对手预测相关的原因前缀加 `[预测]` 标记
- UI 中解析 `[预测]` 标记，渲染为红色

### 7. 对手预测关闭时的兼容性

当 `opponent_prediction.enabled = False` 或 `None` 时：
- `tenpai_danger_multiplier = 1.0`
- `opponent_danger_bonus = 0`
- 不生成对手预测相关原因
- 行为与修改前完全一致

## 业务规则处理
- 原 Requirement / Scenario：无（策略增强）
- 本次处理方式：不改 spec 只修代码

## 历史 BugFixSpecs 命中
- 命中文件：无
- 历史根因：无
- 本次防重蹈覆辙措施：无

## 回归测试方案
- 用例文件：`regression-tests/cases/opponent-prediction-strategy.md`
- 批量测试接口 / 命令：TBD
- 入参来源：构造 snapshot，开启/关闭对手预测
- 期望出参：
  - 开启时：危险牌评分降低，建议原因含红色标记
  - 关闭时：与修改前行为一致
- 断言规则：对比开启/关闭时的候选排序差异

## 回滚方案
还原 `game/stable_strategy_model.py`、`game/stable_hard_analysis.py`、`ui/stable_battle_panel.py` 到修改前版本。
