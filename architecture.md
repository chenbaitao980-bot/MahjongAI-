# MahjongAI 知识图谱

> 自动生成于 2026-05-04 20:49 | 最后人工更新：2026-05-10（修复DeepSeek默认开启）

---

## 变更日志

### 2026-05-10 — 游戏状态锁 + 手牌识别按钮

#### 修改 `ui/battle_panel.py`
- 新增 `_game_in_progress: bool = False` 实例变量
- `_end_btn` 初始设为 `setEnabled(False)`（未开始游戏时不可点击）
- 新增 `set_game_started(started: bool)` 方法：更新 `_game_in_progress`，同步控制开始/结束按钮启用状态
- `set_busy()` 改为尊重 `_game_in_progress`：分析中两者均禁用；闲置时按游戏状态分别启用
- `set_busy()` 新增对 `_recognize_btn` 的禁用控制
- 我方手牌区新增"识别"按钮（在"添加"左侧），点击发射 `recognition_only_requested("manual_recognize")`

#### 修改 `ui/main_window.py`
- `_on_battle_start_requested()` 创建 session 后调用 `set_game_started(True)`
- `_on_battle_end_requested()` 关闭 session 后调用 `set_game_started(False)`

---

### 2026-05-10 — 耗时分段显示 + 进度漏斗指示器

#### 修改 `battle/state.py`
- 新增字段 `last_local_analysis_duration_ms: int = 0`，记录本地数据分析（`_compute_analysis()`）耗时
- `mark_analysis()` 和 `reset_round()` 同步初始化该字段

#### 修改 `battle/service.py`
- `_analyze()` 在 `to_payload()` 调用前后计时，写入 `state.last_local_analysis_duration_ms`
- `analyze_state_only()` 同样计时 `to_payload()`

#### 修改 `ui/battle_panel.py`
- `_build_advice_group()` 底部新增 `_progress_label`（右对齐，默认隐藏）
- `set_busy(True, message)` 时显示 `⧗ {message}`，`set_busy(False)` 时隐藏
- `_render_advice()` 耗时格式改为独立一行：`图片识别：X ms | 数据分析：Y ms | AI分析：Z ms`（只显示 >0 的项，删去"总计"）

#### 修改 `ui/main_window.py`
- 新增 `_MODE_BUSY_MSG` 字典映射 mode→提示文本
- `_start_battle_worker()` 根据 mode 传入对应文本给 `set_busy()`：
  - full → "分析中..."
  - recognition_only → "正在重新识别牌区..."
  - state_only → "正在分析对策..."

---

### 2026-05-10 — 副露手牌计数修复 + 分析触发分层优化

#### 修复 `battle/state.py` — 副露场景向听数/候选分析空结果
- `_compute_analysis()` 判断条件从 `len(hand) == 13/14` 改为 `len(hand) + meld_tile_count == 13/14`
- 解决有副露时（如1副露3张→手牌11张）落入 `return {}` 导致 candidates 为空的 bug

#### 修改 `battle/service.py` — 新增两个分析方法
- `analyze_recognition_only(state, trigger)`: 识别手牌 + 本地分析，强制跳过 DeepSeek，用于我方弃牌/副露手动编辑
- `analyze_state_only(state, trigger)`: 不做图片识别，仅用当前手牌重算本地分析，用于敌方数据变更

#### 修改 `ui/battle_panel.py` — 信号分层
- 新增信号 `recognition_only_requested(str)` 和 `state_reanalyze_requested(str)`
- 我方弃牌/副露的添加/撤销/清空操作 → emit `recognition_only_requested`（识别+本地分析）
- 敌方弃牌/副露的添加/撤销/清空操作 → emit `state_reanalyze_requested`（仅重算）

#### 修改 `ui/main_window.py` — 支持三种分析模式
- `BattleAnalysisThread` 新增 `mode` 参数（"full" / "recognition_only" / "state_only"）
- 原 `_on_battle_analysis_requested()` 逻辑抽取为 `_start_battle_worker(trigger, mode)` 公共方法
- 新增 `_on_battle_recognition_only_requested()` / `_on_battle_state_reanalyze_requested()` handler
- 连接 battle_panel 的两个新信号

---

### 2026-05-10 — AI建议面板中文化（出牌名 + 策略类型）

#### 修改 `game/tiles.py`
- 新增 `_TILE_DISPLAY` 映射表和 `tile_display_name(tile_id)` 函数
- 将牌ID（如"2z"、"3m"）转为中文名（"南"、"3万"）

#### 修改 `game/llm_advisor.py`
- `get_program_advice()` 返回 dict 新增 `"strategy_type"` 字段（中文：攻牌/守牌/平衡）
- reason 文本中的出牌名改用 `tile_display_name()` 显示中文，策略名改用中文标签
- `get_final_advice()` 返回 dict 同样新增 `"strategy_type"` 字段（直接沿用 LLM 的中文输出）

#### 修改 `battle/service.py`
- LLM模式和程序模式构造 `BattleAdvice` 时，`strategy_type` 字段改从 `"strategy_type"` 键读取（而非原来的 `"risk_level"`）

#### 修改 `ui/battle_panel.py`
- `_render_advice()`：推荐出牌显示前通过 `TILE_NAME_MAP` 转为中文名
- `AnalysisPanel.refresh()`：候选表格"出牌"列通过 `TILE_NAME_MAP` 转为中文名，高亮逻辑保持对比 tile_id 不变

---

### 2026-05-10 — 修复 DeepSeek 未开启仍触发分析

#### 修改 `battle/state.py`
- `BattleState.deepseek_enabled` 默认值由 `True` 改为 `False`（第51行）
- 删除 `reset_round()` 中的 `self.deepseek_enabled = True`（原第256行）
- 效果：程序启动及每轮重置时不再强制开启DeepSeek，用户选择始终被保留

---

### 2026-05-09 — 低优先级优化 L1/L2/L3

#### 修改 `game/danger.py` — 后期风险曲线指数化（L1）
- 将巡目危险加成由三档线性阶梯改为指数公式：`min(int(8 * 1.5^tier), 45)`（tier = (turn-10)//2）
- turn 10-11: +8, 12-13: +12, 14-15: +18, 16-17: +27, 18-19: +40, 20+: +45（上限）

#### 修改 `game/strategy.py` — 进张系数加权（L2）
- `score_candidate()` ukeire 系数：attack 4→5, balance 3→3.5, defense 1→1.5
- 放大两面搭子（ukeire高）vs 坎张/对子（ukeire低）评分差距约 25%

#### 修改 `battle/service.py` — 手牌去重（L3）
- `BattleService.__init__` 新增 `_last_analyzed_hand_sig` / `_last_advice_cache` 字段
- `_analyze()` 在识别手牌后比对指纹（sorted tile_id tuple），相同时直接返回缓存结果

---

### 2026-05-09 — 候选分析面板 + 对局数据详尽保存

#### 新增 `ui/battle_panel.py` — `AnalysisPanel` 类
- 在 UI 中间列底部新增 `AnalysisPanel(QGroupBox)` 部件
- 展示每次 AI 分析结果：7列表格（出牌 | 向听后 | 进张数 | 危险度 | 潜在番 | 综合分 | MC胜率）
- 推荐出牌行高亮绿色背景；标题行显示当前向听数和策略模式
- 在 `_render_advice()` 末尾自动调用 `refresh()`，每次 AI 建议更新时刷新

#### 修改 `battle/state.py` — 存储 last_analysis
- `BattleState` 新增字段 `last_analysis: dict`，存储 `_compute_analysis()` 的最新结果
- `_compute_analysis()` 在每次返回前将结果存入 `self.last_analysis`，供 UI 无额外调用即可读取
- `reset_round()` 同步清空 `last_analysis`

#### 修改 `game/session.py` — 新增分析事件持久化
- `__init__` 新增 `analysis_events.jsonl` 文件句柄
- `_init_db()` 新增 `analysis_events` SQLite 表（timestamp / trigger / hand / candidates / advice / shanten / strategy_mode / recommended_discard）
- 新增 `append_analysis_event(event: dict)` 方法：同步写 jsonl + SQLite，异常静默

#### 修改 `battle/service.py` — 触发分析事件保存
- `_analyze()` 在 `append_frame()` 之后调用 `self._session.append_analysis_event()`
- 保存字段：timestamp、trigger_reason、手牌列表、完整 analysis dict（含 candidates）、advice 摘要

### 2026-05-09 — 修复 `game/danger.py` 空文件导致分析链失效

#### 实现 `game/danger.py` — 二人模式危险度评分
- `calc_tile_danger()` 实现：基线20 + 现物/全现物判定 + 副露清一色推断 + 中张加权 + 巡目加权，clamp [0,100]
- `danger_level_str()` 将整数分数映射为"安全/较安全/中等/危险/极危险"

#### 修复 `game/llm_advisor.py`
- `validate_llm_output()` 修复：`legal_discards` 为空时不拒绝合法输出
- `get_final_advice()` candidates 为空时提前 fallback，跳过 LLM 调用

---

### 2026-05-06 — 游戏规则修复 + 庄家/门风/暗杠输入 + 生牌/黄牌阶段

#### 修复 `game/danger.py` — 生牌判断逻辑
- `calc_tile_danger()` 的 `is_sheng` 判定原仅检查对手弃牌，现改为检查 **所有玩家已见牌**（含自家弃牌 + 所有副露）
- 传入参数扩展：`enemy_discards` → `all_seen = enemy_discards + self_discards + enemy_melds`

#### 修改 `game/evaluator.py`
- `analyze_discard_candidates()` 调用 `calc_tile_danger` 时合并 `self_discards + self_meld_tiles_flat` 传入，确保生牌/熟牌判断覆盖全场

#### 修改 `game/state.py`
- 新增 `PHASE_HUANGPAI = "huangpai"` — 黄牌阶段（剩余≤16张，约8对）
- `PHASE_SHENGJIA` 注释补全："生牌阶段（剩余≤30张，约15对）"

#### 修改 `ui/capture_panel.py`
- 黄牌边缘显示：当 `remaining_tiles <= 16` 时标题追加「黄牌」红色警示

#### 修改 `battle/service.py`
- `TAIZHOU_RULES_PROMPT` 新增【可选规则】段落，覆盖单局牌点上限100胡、生牌阶段、黄牌边缘≤16张
- 明确 `num_players: 2` 注入 payload

#### 修改 `battle/state.py`
- `BattleState` 新增字段：
  - `dealer_seat: str = "self"` — 庄家位置（"self" | "enemy"）
  - `self_wind: str = "1z"` — 自家门风（"1z"东 | "2z"南）
  - `kan_closed_count: int = 0` — 暗杠次数（0~4）
- `to_payload()` 将上述字段注入 `"self"` 字典，供 LLM 判断门风番、包牌等

#### 修改 `game/simple_state.py`
- 新增 `winds: list[str]` 字段，默认 `["1z", "2z", "1z", "2z"]`，支持门风传播

#### 修改 `ui/battle_panel.py`
- `_build_center_group()` 新增三个 `QComboBox`：
  - **庄家**：自家 / 对手
  - **门风**：东(1z) / 南(2z)
  - **暗杠**：0 / 1 / 2 / 3 / 4
- 新增信号处理：` _on_dealer_changed()` / `_on_wind_changed()` / `_on_kan_closed_changed()`
- `_render_state()` 同步控件显示，摘要标签更新为 `庄家=XX | 门风=XX | 暗杠X次 | ...`

---

## 变更日志

### 2026-05-06 — 补足 01/02 阶段（状态结构 + 胡牌判断与合法出牌）

#### 修改 `game/tiles.py`
- 新增 `parse_tiles(tile_str)` — 空格分隔牌名 → 整数ID列表
- 新增 `format_tiles(tile_ids)` — 整数ID列表 → 空格分隔牌名

#### 新增 `game/simple_state.py`
- `SimpleMeld` — 简化版副露结构（type/tiles/from_player）
- `SimpleGameState` — 简化版状态（hands/discards/melds/current_player/dealer/turn）
- 与现有 `game/state.py` 的 vision-oriented 结构并存

#### 新增 `game/visible.py`
- `count_visible_tiles(state, my_player)` — 返回34维已见牌数组
- `count_remaining_tiles(state, my_player)` — 返回34维剩余牌数组（max(0, 4-visible)）

#### 修改 `game/win.py`
- 新增 `ENABLE_SEVEN_PAIRS = True`
- 新增 `is_standard_win(hand)` — 14张整数ID手牌标准胡牌判断（无副露无财神包装层）
- 新增 `is_seven_pairs(hand)` — 七对判断
- 新增 `is_win_simple(hand)` — 统一胡牌判断（标准 或 七对）

#### 新增 `game/actions.py`
- `get_discard_actions(hand)` — 枚举可打牌，同种牌去重
- `get_legal_actions(state, player)` — 14张能胡时含 `{"type": "hu"}` + 所有 discard

---

## 变更日志

### 2026-05-06 — 攻守转换（04 阶段）

#### 新增 `game/strategy.py`
- `decide_strategy_mode(best_shanten, best_ukeire, turn, enemy_meld_count)` → `"attack" | "balance" | "defense"`
- 规则：听牌→进攻；一向听+进张≥16+前巡→进攻；后巡+高向听→防守；对手副露≥2+高向听→防守；否则平衡
- `score_candidate(candidate, mode)` → `float` 综合评分
  - 进攻：`score = -shanten*100 + ukeire*4 - danger*0.8`
  - 平衡：`score = -shanten*100 + ukeire*3 - danger*1.5`
  - 防守：`score = -shanten*60 + ukeire*1 - danger*3`
- `rank_candidates(candidates)`：按 `score` 降序排列
- `strategy_label(mode)`：中文标签（进攻/平衡/防守）

#### 修改 `game/evaluator.py`
- `analyze_discard_candidates()` 返回结构变更：**`list[dict]` → `dict`**
  - `"strategy_mode"`: 当前攻守模式
  - `"candidates"`: 完整候选列表（含新增 `"score"` 字段）
- 内部逻辑：先按 `(shanten_after, -ukeire_count)` 排序提取最优值 → 调用 `decide_strategy_mode()` → 为每个候选计算 `score` → 按 `score` 降序重排

#### 修改 `battle/state.py`
- `_compute_analysis()` 适配 `evaluator.py` 新返回结构
- 14张手牌分析结果新增字段：
  - `"strategy_mode"`: 攻守模式
  - `"top_score"`: 最高分候选的 score 值
- `to_payload()` 自动将 strategy_mode 随 analysis 注入 LLM prompt

---

## 变更日志

### 2026-05-06 — 本地分析模块（向听数/进张/危险度）

#### 新增 `game/tiles.py`
- 牌编码辅助：0~33 整数映射（万/筒/条/字）
- `tile_to_int()` / `int_to_tile()` / `suit_of()` / `rank_of()` / `is_honor()`
- `hand_to_counts(hand, baida)`：返回 `(counts[34], baida_count)`，财神在 counts 中被清零
- `build_visible_tiles(...)`：统计所有可见牌（含自家手牌），用于计算剩余张数
- `tiles_to_ids(tiles)`：兼容 `TileMatch` 和 `str` 列表的 tile_id 提取

#### 新增 `game/win.py`
- `is_win(counts, meld_count, baida_count)`：胡牌判断（支持财神替代）
- 核心约束：**将牌必须由两张相同真实牌组成**，财神不能单独作将
- 字牌只能组刻子，不能组顺子
- `_can_form_melds()`：递归拆面子（刻子/顺子），支持 joker 补位

#### 新增 `game/shanten.py`
- `calc_shanten(counts, meld_count, baida_count)`：向听数计算
- 算法：枚举将牌 × 递归面子移除 × 搭子统计
- `_remove_groups_dfs()`：回溯所有面子组合方式
- `_count_taatsus()` / `_count_taatsus_and_pairs()`：两面/坎张/对子搭子统计
- 支持财神替代，已胡牌返回 -1

#### 新增 `game/ukeire.py`
- `calc_ukeire(hand_13, meld_count, baida, visible_tiles)`：有效进张计算
- 遍历 34 种牌模拟摸牌，计算新向听数是否降低
- 返回 `{tiles, count, current_shanten}`

#### 新增 `game/danger.py`
- `calc_tile_danger(tile, enemy_discards, enemy_melds, self_discards, remaining_tiles, turn)`：危险度评分（0~100）
- 规则：现物 -20、已见张数修正、字牌生张 +15、中张 +15、巡目加成、对手副露数 >=2 +10、生牌阶段生张 +25
- `danger_level_str(score)`：安全/较安全/中等/危险/极危险

#### 新增 `game/evaluator.py`
- `analyze_discard_candidates(hand_14, melds, baida, visible_tiles, enemy_discards, enemy_melds, self_discards, remaining_tiles)`
- 枚举手牌中每种不重复的候选出牌，计算打出后的向听数、进张数、危险度
- 排序：**shanten_after ASC → ukeire_count DESC**
- 返回最多按排序后的完整候选列表（调用方取前5）

#### 修改 `battle/state.py`
- **`BattleState`** 新增 `_compute_analysis()`：
  - 13张手牌 → 仅返回 `{"shanten": X, "candidates": [], "top_recommendation": None}`
  - 14张手牌 → 调用 `analyze_discard_candidates()`，返回前5候选 + top_recommendation
  - 其他张数 → 返回 `{}`
  - **全程 try/except 包裹**，异常安静返回 `{}`，不阻断主流程
- **`to_payload()`**：`"self"` 字典内新增 `"analysis": self._compute_analysis()`

#### 修改 `battle/service.py`
- `TAIZHOU_RULES_PROMPT` 在【最优策略框架】前插入【本地分析数据】段落：
  - 要求 LLM **必须优先使用** `self.analysis` 中的硬数据
  - 明确禁止 LLM 自行重新计算向听数或进张数
  - 给出决策优先级：`shanten_after 最小 → ukeire_count 最多 → danger 最低`

---

### 2026-05-05 — UI 交互 + 识别精度改进 + Bug 修复

#### `ui/battle_panel.py`
- **`MeldSelectionDialog.__init__`**：新增 `existing_meld` 可选参数，打开时自动预填充副露类型和各牌
- **`BattlePanel`**：新增信号 `meld_correction_requested = pyqtSignal(int, str)`（flat_tile_index, correct_tile_id）
- **`_build_player_group()`**：副露区从静态 `QLabel` 改为 `QWidget + QHBoxLayout`，副露渲染为可点击 `QPushButton`
- **新增 `_rebuild_meld_buttons(melds, is_enemy, layout)`**：将每组副露渲染为按钮，点击触发编辑
- **新增 `_on_meld_correction_click(meld_index, is_enemy, current_meld)`**：预填充编辑对话框，保存修正，emit 训练信号，设置 `self_melds_locked = True`
- **`_add_meld` / `_undo_meld`**：自我方操作时设 `self_melds_locked = True`
- **`_clear_melds`**：清空我方副露时重置 `self_melds_locked = False`
- **新增 `set_training_in_progress()`**：将训练状态 label 设为橙色"⏳ 正在训练中..."
- **`set_train_success_message()`**：更新为绿色，接受时间戳格式完成消息
- **`_train_success_label`** 移至战斗状态组框正下方（中央列），替代原先在 AI 建议组外被遮挡的位置
- **`_on_tile_correction_click()`**：无论是否改牌，始终 emit `tile_correction_requested`（点击确认即强化训练样本）

#### `battle/state.py`
- **`BattleState`** 新增字段 `self_melds_locked: bool = False`：标记用户已手动修正副露，阻止识别覆盖
- **`reset_round()`**：增加 `self.self_melds_locked = False`

#### `battle/service.py`
- **`BattleService.__init__`** 新增 `_last_meld_rois: list[np.ndarray]`：存储最近一次成功识别的副露每张牌 ROI（按 meld0_tile0, meld0_tile1 … 排列）
- **`_detect_self_melds()`**：识别成功时保存 `self._last_meld_rois = list(prepared_meld_rois)`
- **副露锁逻辑（`_analyze` 内）**：
  - `detected_melds` 非空 + 未锁定 → 正常更新
  - `detected_melds` 为空 + 已锁定 → **自动解锁**并清空（防止旧局副露使 hand_region 计算偏移导致识别失败）
  - `detected_melds` 非空 + 已锁定 → 保留手动修正，仅 lock 住牌值

#### `ui/main_window.py`
- **训练开始**：`_start_hog_training()` 后追加 `self._battle_panel.set_training_in_progress()`
- **训练完成**：移除 `QMessageBox.information` 弹窗；改为内联时间戳消息（`set_train_success_message`）
- **新增 `_on_battle_meld_correction(flat_tile_index, correct_tile_id)`**：从 `_last_meld_rois` 取 ROI → 保存到 `tile_samples_cleaned` → 触发后台重训 HOG
- **连接** `meld_correction_requested` 信号到 `_on_battle_meld_correction`

#### `vision/recognizer.py`
- **`_crop_tile_face()`**：改用形态学 `MORPH_CLOSE`（核大小约牌宽 12%）填充字符笔划空洞 → `connectedComponentsWithStats` 取最大白色连通域 → 更精确 bounding box；原 bounding-box 逻辑作降级策略；策略 B（暗色牌面）同步改造

#### `vision/hog_classifier.py`
- **`extract_hog()`**：CLAHE `clipLimit` 2.0 → 3.0，增强万字牌低对比度区域的笔划特征

#### `vision/hand_region_module.py`
- **Bug 修复**：`_segment_tiles()` 调用 `self._segment_tiles_by_white_components()` 但方法缺失，导致 `AttributeError`。根因：从 `RecognitionPipeline` 重构提取 `HandRegionModule` 时该方法被遗漏
- **新增 `_segment_tiles_by_white_components(self, strip, expected_count, frame_index, debug_dir)`**：从 `pipeline.py:1511-1577` 搬运，调整签名匹配调用处 4 参数。逻辑：HSV 白色/暗色牌面检测 → 连通域聚类 → 按牌面宽高比 0.70 切分宽块 → 返回 `(rois, slots)`

#### `vision/pipeline.py`
- **副露溢出修复**：`segment_tiles_with_slots` 返回后插入 Y 方向高度校验后处理，取 ROI 高度中位数为基准，阈值 0.75，从左侧逐个删除高度过低的副露溢入 ROI（仅 `meld_side=left` 时生效），第 240-264 行

---

## 统计概览

- **Python 文件**: 47
- **类数量**: 43
- **函数数量**: 159
- **依赖关系**: 200+

## 模块拓扑

| 文件 | 类 | 函数 | 大小 |
|------|----|------|------|
| `vision\pipeline.py` | 1 | 0 | 78KB |
| `ui\main_window.py` | 5 | 6 | 78KB |
| `battle\service.py` | 1 | 0 | 61KB |
| `vision\recognizer.py` | 4 | 1 | 54KB |
| `ui\battle_panel.py` | 5 | 1 | 41KB |
| `vision\hand_region_module.py` | 1 | 2 | 29KB |
| `ui\calibration.py` | 7 | 0 | 23KB |
| `game\session.py` | 1 | 0 | 23KB |
| `ui\collection_panels.py` | 2 | 5 | 23KB |
| `vision\discard_tile_cropper.py` | 0 | 15 | 19KB |
| `extract_templates_v2.py` | 0 | 15 | 15KB |
| `backfill_session_db.py` | 0 | 4 | 13KB |
| `ui\capture_panel.py` | 1 | 0 | 12KB |
| `scripts\clean_tile_samples.py` | 0 | 10 | 12KB |
| `extract_templates.py` | 0 | 13 | 11KB |
| `extract_templates_final.py` | 0 | 12 | 11KB |
| `vision\hog_classifier.py` | 1 | 2 | 10KB |
| `ui\calibration_canvas.py` | 1 | 1 | 10KB |
| `extract_templates_v3.py` | 0 | 12 | 10KB |
| `scripts\extract_samples_from_media.py` | 0 | 5 | 10KB |
| `extract_templates_seed.py` | 0 | 10 | 9KB |
| `scripts\generate_knowledge_graph.py` | 0 | 7 | 9KB |
| `vision\discard_recognizer.py` | 1 | 1 | 8KB |
| `scripts\refresh_templates.py` | 0 | 4 | 7KB |
| `scripts\collect_tile_samples.py` | 0 | 4 | 7KB |
| `ui\region_selector.py` | 1 | 0 | 7KB |
| `vision\layout.py` | 2 | 0 | 7KB |
| `debug_recognition.py` | 0 | 2 | 6KB |
| `battle\state.py` | 2 | 5 | 5KB |
| `game\state.py` | 6 | 0 | 4KB |
| `game\tiles.py` | 0 | 8 | 3KB |
| `game\win.py` | 0 | 2 | 3KB |
| `game\shanten.py` | 0 | 4 | 4KB |
| `game\ukeire.py` | 0 | 1 | 2KB |
| `game\actions.py` | 0 | 2 | 2KB |
| `game\danger.py` | 0 | 2 | 2KB |
| `game\evaluator.py` | 0 | 1 | 3KB |
| `game\simple_state.py` | 2 | 0 | 1KB |
| `game\strategy.py` | 0 | 3 | 2KB |
| `game\visible.py` | 0 | 2 | 2KB |

## 核心类

- **battle\service.py** → `BattleService`
- **battle\state.py** → `BattleAdvice`
- **battle\state.py** → `BattleState`
- **game\session.py** → `GameSession`
- **game\state.py** → `TileMatch`
- **game\state.py** → `RegionObservation`
- **game\state.py** → `MeldGroup`
- **game\state.py** → `PlayerState`
- **game\state.py** → `OpponentState`

## 依赖关系（Top 30）

- `backfill_session_db.py` → `battle\state.py`
- `backfill_session_db.py` → `game\session.py`
- `backfill_session_db.py` → `game\state.py`
- `battle\__init__.py` → `battle\service.py`
- `battle\__init__.py` → `battle\state.py`
- `battle\__init__.py` → `game\state.py`
- `battle\service.py` → `battle\__init__.py`
- `battle\service.py` → `battle\state.py`
- `battle\service.py` → `game\__init__.py`
- `battle\service.py` → `game\session.py`
- `battle\service.py` → `game\state.py`
- `battle\service.py` → `ui\__init__.py`
- `battle\service.py` → `utils\__init__.py`
- `battle\service.py` → `utils\paths.py`
- `battle\service.py` → `vision\__init__.py`
- `battle\service.py` → `vision\capture.py`
- `battle\service.py` → `vision\hand_region_module.py`
- `battle\service.py` → `vision\hog_classifier.py`
- `battle\service.py` → `vision\layout.py`
- `battle\service.py` → `vision\recognizer.py`
- `battle\state.py` → `game\state.py`
- `debug_recognition.py` → `game\session.py`
- `debug_recognition.py` → `utils\paths.py`
- `debug_recognition.py` → `vision\capture.py`
- `debug_recognition.py` → `vision\layout.py`
- `debug_recognition.py` → `vision\pipeline.py`
- `debug_recognition.py` → `vision\recognizer.py`
- `diagnose_region.py` → `vision\layout.py`
- `diagnose_region.py` → `vision\pipeline.py`
- `game\session.py` → `battle\__init__.py`
- `battle\state.py` → `game\tiles.py`
- `battle\state.py` → `game\shanten.py`
- `battle\state.py` → `game\evaluator.py`
- `game\evaluator.py` → `game\tiles.py`
- `game\evaluator.py` → `game\ukeire.py`
- `game\evaluator.py` → `game\danger.py`
- `game\evaluator.py` → `game\strategy.py`
- `game\strategy.py` → `game\danger.py`
- `game\ukeire.py` → `game\tiles.py`
- `game\ukeire.py` → `game\shanten.py`
- `game\shanten.py` → `game\tiles.py`
- `game\win.py` → `game\tiles.py`
- `game\actions.py` → `game\simple_state.py`
- `game\actions.py` → `game\win.py`
- `game\danger.py` → `game\tiles.py`
- `game\danger.py` → `game\state.py`
- `game\visible.py` → `game\simple_state.py`
- `game\win.py` → `game\tiles.py`