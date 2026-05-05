# MahjongAI 知识图谱

> 自动生成于 2026-05-04 20:49 | 最后人工更新：2026-05-05

---

## 变更日志

### 2026-05-05 — UI 交互 + 识别精度改进

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

---

## 统计概览

- **Python 文件**: 41
- **类数量**: 43
- **函数数量**: 141
- **依赖关系**: 182

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
| `battle\state.py` | 2 | 4 | 4KB |
| `game\state.py` | 6 | 0 | 4KB |

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