# MahjongAI 知识图谱

> 自动生成于 2026-05-04 20:49 | 最后人工更新：2026-05-15（语音播报出牌功能）

---

## 变更日志

### 2026-05-15 — 语音播报出牌功能

#### 新增 `utils/tts.py`
- 封装 pyttsx3 Windows TTS，模块级单例 `_engine`，懒初始化
- 启动时自动选取中文语音（微软慧慧 / 雅雅），语速设为 150（比默认 200 更清晰）
- `speak_discard(tile_chinese_name)` 在后台 daemon 线程播报 `"打X万/条/筒/字"`，不阻塞 UI 主线程
- 线程间互斥锁 `_lock` 防止并发调用导致引擎状态错误

#### 修改 `ui/battle_panel.py`
- `__init__` 新增实例变量 `_voice_enabled: bool`，从 `config["battle"]["voice_enabled"]` 读取
- `_build_advice_group()` 在 AI 开关行下方添加"语音播报出牌"复选框（默认不勾选）
- 新增 `_on_voice_toggle(checked)` 处理器：更新 `_voice_enabled`，同步写入 `_config["battle"]["voice_enabled"]`，发射 `config_save_requested` 持久化
- `_render_advice()` 在渲染推荐出牌后，若 `_voice_enabled` 且牌名非空，调用 `speak_discard(discard)`

#### 修改 `config/settings.yaml`
- `battle` 节点新增 `voice_enabled: false`（默认关闭）

#### 修改 `requirements.txt`
- 新增依赖 `pyttsx3>=2.90`

---

### 2026-05-15 — 快捷键配置持久化 + 分析按钮改名

#### 修改 `ui/battle_panel.py`
- "重试"按钮改名为**"分析"**
- 快捷键配置新增"分析"选项，默认键 `A`，触发 `reanalyze_with_ai_requested`
- `__init__` 从 `config["shortcut_keys"]` 读取已保存键位（合并到硬编码默认值）
- `_open_shortcut_config()` 保存后将键位写入 `self._config["shortcut_keys"]` 并发射 `config_save_requested` 信号
- 新增信号 `config_save_requested = pyqtSignal()`
- 快捷键配置对话框支持输入 `Space`/`空格`/空格字符均识别为空格键

#### 修改 `ui/main_window.py`
- 连接 `battle_panel.config_save_requested` → `_save_config()`，配置修改后立即写入 `config/settings.yaml`

### 2026-05-15 — 回合指示器 + 快捷键操作模块

#### 修改 `battle/state.py`
- `BattleState` 新增字段 `current_turn: str = "none"`，取值 `"self"` | `"enemy"` | `"none"`，追踪当前轮到谁出牌

#### 修改 `ui/battle_panel.py`

**回合颜色指示器：**
- `_build_center_group()` 中将 `QLabel("我方手牌区")` 改为 `self._turn_label`，保存引用
- 新增 `_update_turn_label()`：根据 `current_turn` 动态改变标签文字和颜色
  - `"self"` → 蓝色 `"我方手牌区  ● 我方回合"`
  - `"enemy"` → 红色 `"我方手牌区  ● 敌方回合"`
  - `"none"` → 默认样式
- `_add_discard()` 添加弃牌后自动切换 `current_turn`（敌方添加→我方回合，我方添加→敌方回合）
- `_render_state()` 末尾调用 `_update_turn_label()` 和 `_update_shortcut_status()`

**快捷键操作模块（`_build_shortcut_group`）：**
- 在战斗状态面板（`_build_center_group`）底部新增 `QGroupBox("快捷键操作")`
- 牌型切换按钮行：[W=万] [T=筒] [B=条] [Z=字]，当前选中高亮蓝色
- 红框牌条（`_tile_strip_container`）：根据当前牌型显示 9 个（字牌 7 个）选牌按钮；选中时按钮变黄色
- 状态标签：显示"将添加到：我方/敌方弃牌区"（与回合同步颜色）
- 快捷键说明行：显示添加/撤销/清空快捷键

**快捷键绑定（`_rebuild_shortcuts`，使用 `QShortcut`）：**
- W/T/B/Z → 切换牌型（默认，可在配置对话框修改）
- 数字 1-9 → 选中对应牌并高亮
- Enter → 将选中牌添加到当前回合的弃牌区
- U → 撤销当前回合弃牌区最后一张
- C → 清空当前回合弃牌区

**快捷键配置（`_open_shortcut_config`）：**
- 点击"配置"按钮打开 `QDialog`，可修改所有快捷键键位
- 修改后自动更新按钮文字、说明标签，并调用 `_rebuild_shortcuts()` 重建绑定

**新增实例变量：**
- `_shortcut_suit`: 当前选中牌型 (`m`/`p`/`s`/`z`)
- `_shortcut_selected`: 当前选中牌号 (1-9) 或 None
- `_suit_btns`: 牌型按钮字典
- `_tile_strip_btns`: 牌条按钮列表
- `_shortcut_keys`: 快捷键配置字典
- `_active_shortcuts`: 活跃 `QShortcut` 列表（用于重建时销毁）

---

### 2026-05-11 — MC并行化 + UI交互简化 + 性能优化 + 动态财神Prompt

#### 修改 `game/advisor.py` — MC性能优化：向听跳过 + 并行执行

- **向听≥2时完全跳过MC**：候选向听数≥2时win_rate≈0，跳过MC直接返回evaluator排序结果，节省约6.7秒
- **向听=1时限制10次**：`mc_iterations = min(mc_iterations, 10)`
- **ThreadPoolExecutor并行**：将串行 `for candidate in top_k` 循环改为 `ThreadPoolExecutor(max_workers=len(top_k))` 并行执行各候选的MC模拟
- **新增模块级函数 `_run_mc_candidate(args)`**：单候选全部迭代的封装，可被executor.map调用；种子策略与串行版完全相同，结果幂等

#### 修改 `battle/state.py` — 减少MC默认参数

- `_compute_analysis()` 中 `mc_iterations=30 → 10`，`mc_top_k=3 → 2`
- `deepseek_enabled: bool = False → True`（DeepSeek默认开启）

#### 修改 `battle/service.py` — 识别专用模式 + 扩展缓存键

- `analyze_recognition_only()` 新增 `trigger_reason == "manual_recognize"` 分支：仅做 `capture_self_hand()`，跳过 `to_payload()` 和MC分析，`last_local_analysis_duration_ms = 0`
- 新增 `_last_state_sig: tuple | None = None` 实例变量（区别于原 `_last_analyzed_hand_sig` 避免类型冲突）
- `analyze_state_with_ai()` 的缓存键扩展为完整局面签名：`(sorted_hand, enemy_discards, self_discards, enemy_melds_tuple, remaining_tiles, baida_tile)`，数据未变时直接复用上次payload，跳过重算

#### 修改 `ui/battle_panel.py` — UI交互全面改造

**添加按钮去掉自动分析触发：**
- `_add_discard()`：删除 `state_reanalyze_requested.emit("enemy_discard_added")` 和 `recognition_only_requested.emit("self_discard_added")` 两行emit
- `_add_meld()`：删除 `state_reanalyze_requested.emit("enemy_meld_changed")` 和 `recognition_only_requested.emit("self_meld_changed")` 两行emit
- 分析只在点击"重试"时触发

**手牌点击增加删除选项：**
- `_rebuild_hand_tile_buttons()` 中 btn.clicked 从连接 `_on_tile_correction_click` 改为 `_on_hand_tile_btn_click`
- 新增 `_on_hand_tile_btn_click(tile_index, tile_id)`：弹出 QMenu（纠正 / 删除）
- 新增 `_delete_hand_tile_at(tile_index)`：从 `state.self_hand` pop指定牌，重建按钮，记录日志

**弃牌区从QLabel重构为QPushButton网格：**
- `_build_player_group()` 中弃牌显示区改为 `QGridLayout` 容器（`_self_discard_layout` / `_enemy_discard_layout`）
- `_render_state()` 改为调用 `_rebuild_discard_buttons(discards, is_enemy, layout)` 而非 `setText()`
- 新增类常量 `_DISCARD_COLS = 6`
- 新增 `_rebuild_discard_buttons(discards, is_enemy, layout)`：按6列网格渲染每张弃牌为QPushButton
- 新增 `_on_discard_tile_click(tile_index, is_enemy)`：弹出 QMenu（删除）

**副露区点击增加删除选项：**
- `_rebuild_meld_buttons()` 中 btn.clicked 改为连接 `_on_meld_btn_click`
- 新增 `_on_meld_btn_click(meld_index, is_enemy, meld)`：弹出 QMenu（修改 / 删除）；"修改"调用原 `_on_meld_correction_click`；"删除"直接弹出自家或对手副露

**AI建议文本中文化：**
- 新增辅助函数 `_replace_tile_codes(text: str) -> str`：用正则 `r'[1-9][mpsz]'` 替换所有牌码为中文名
- `_render_advice()` 中 reasoning_summary、risk_notes、forbidden_discards、candidate_actions 均通过 `_replace_tile_codes()` 过滤后显示

**MC胜率Bug修复：**
- `AnalysisPanel.refresh()` 中 `c.get("mc_win_rate")` 修正为 `c.get("mc", {}).get("win_rate")`（MC数据存放在嵌套的`mc`字段内）

#### 修改 `game/llm_prompt.py` — 动态财神牌描述

- 添加 `from game.tiles import tile_display_name`
- 将 `_CORE_RULES` 改名为 `_CORE_RULES_TMPL`，正文中两处"白板(7z)"替换为 `{baida}` 占位符
- `build_system_prompt(game_features)` 新增逻辑：从 `game_features["baida_tile"]` 读取财神牌ID，`"7z"` → `"白板(7z)"`，其他 → `"{中文名}({id})"` 格式；`core_rules = _CORE_RULES_TMPL.format(baida=baida)` 动态填入

#### 修改 `game/llm_advisor.py` — 财神牌注入system prompt

- `get_final_advice()` 中从 `payload.get("rules", {}).get("baida_tile")` 提取财神牌ID
- 注入 `game_features["baida_tile"]` 后再调用 `build_system_prompt(game_features)`，确保AI收到正确的财神牌描述

---

### 2026-05-11 — 修复：添加/识别操作后 DeepSeek 勾选框被错误清除

#### 修复 `battle/service.py` — `analyze_recognition_only()`
- **根本原因**：方法内 `state.deepseek_enabled = False` 用于跳过 AI 调用，但该 state 对象最终被 `set_state()` 写回 UI，导致 DeepSeek 勾选框被清除
- **修复**：执行前保存 `original_deepseek = state.deepseek_enabled`，执行后恢复 `result_state.deepseek_enabled = original_deepseek`，UI 状态不再受影响

---

### 2026-05-11 — 重试按钮：跳过图片识别，直接重跑本地分析 + AI

#### 新增 `battle/service.py` — `analyze_state_with_ai()`
- 新增方法：不做截图/识别，直接用当前 `state.self_hand` 重跑 `to_payload()` + DeepSeek/program 分析
- `last_recognition_duration_ms = 0`，其余逻辑与 `_analyze()` AI 分支完全一致（含 `_persist_deepseek_request`）

#### 修改 `ui/main_window.py`
- `BattleAnalysisThread.run()` 新增 `state_with_ai` 分支 → 调用 `service.analyze_state_with_ai()`
- `_MODE_BUSY_MSG` 新增 `"state_with_ai": "正在重新分析（跳过识别）..."`
- 新增 slot `_on_battle_reanalyze_with_ai_requested()` → `_start_battle_worker(mode="state_with_ai")`
- 连接 `battle_panel.reanalyze_with_ai_requested` 信号

#### 修改 `ui/battle_panel.py`
- 新增信号 `reanalyze_with_ai_requested = pyqtSignal(str)`（重试：不识别，重跑本地+AI）
- "重试"按钮从 `analysis_requested.emit("retry")` 改为 `reanalyze_with_ai_requested.emit("retry")`

---

### 2026-05-10 — 结束游戏弹出胜负确认对话框

#### 修改 `ui/main_window.py`
- 新增静态方法 `_ask_game_result()`：弹出 QMessageBox，三个按钮：赢了 / 输了 / 跳过不记录
- 返回字符串 `"win"` / `"lose"` / `"unknown"`
- `_on_battle_end_requested()` 在处理数据前先弹框，结果写入 `persist_round_event` 的 `detail.result` 字段

---

### 2026-05-10 — 弃牌/副露编辑自动更新剩余张数

#### 修改 `ui/battle_panel.py`
- 新增辅助方法 `_adjust_remaining(delta: int)`：更新 `state.remaining_tiles`（≥0）并同步 `_remaining_spin`（blockSignals）
- 新增静态方法 `_is_kan(meld_type: str)`：判断是否杠型副露
- `_add_discard()` / `_undo_discard()`：弃牌添加 -1，撤销 +1
- `_clear_discards()`：按清空张数 +n
- `_add_meld()`：仅杠型 -1（岭上牌），吃碰不变
- `_undo_meld()`：仅杠型 +1
- `_clear_melds()`：按清空副露中杠的数量 +n

---

### 2026-05-10 — 修复：手动识别被旧局副露锁污染导致切牌错误

#### 修复 `battle/service.py` — `analyze_recognition_only()`
- 当 `trigger_reason == "manual_recognize"` 时，识别前强制设 `state.self_melds_locked = False`
- 根本原因：`_capture_hand_rois()` 逻辑中，当 `detected_melds=[]` + `self_melds_locked=True` + 手牌区有牌时，不会清除旧副露，导致 `effective_melds` 沿用上一局的副露 → `hand_region(1)` 偏移 → 切牌位置错误
- 解锁后，视觉系统重新检测当前局副露状态（无副露则 `state.self_melds = []`），手牌区域回到正确位置

---

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
| `utils\tts.py` | 0 | 2 | 1KB |
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