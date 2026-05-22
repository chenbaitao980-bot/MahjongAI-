from __future__ import annotations

from copy import deepcopy
from html import escape

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from battle.state import BattleAdvice
from game.stable_hard_analysis import StableHardAnalysis, analyze_snapshot
from game.state import ALL_TILE_IDS
from stable.hand_structure import HandStructureGroup, build_hand_structure_arrangements
from ui.battle_panel import TILE_NAME_MAP


def _is_near_bottom(view: QTextEdit, threshold_px: int = 60) -> bool:
    sb = view.verticalScrollBar()
    if sb.maximum() == 0:
        return True
    return (sb.maximum() - sb.value()) <= threshold_px


def _scroll_to_bottom(view: QTextEdit) -> None:
    sb = view.verticalScrollBar()
    sb.setValue(sb.maximum())


def _fmt_tiles(tiles: list[str]) -> str:
    if not tiles:
        return "（空）"
    return " ".join(TILE_NAME_MAP.get(t, t) for t in tiles)


def _phase_text(phase: str) -> str:
    return {
        "idle": "未开始",
        "playing": "进行中",
        "hupai": "胡牌结算",
    }.get(str(phase), "未知阶段")


def _turn_text(turn: str) -> str:
    return {
        "self": "我方出牌",
        "enemy": "对面行动",
        "none": "等待事件",
    }.get(str(turn), "等待事件")


class UnknownTileDialog(QDialog):
    def __init__(self, unknown: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("补全未识别牌值")
        self._raw_key = str(unknown.get("raw_key") or "")

        layout = QVBoxLayout(self)
        title = QLabel(
            f"抓包中出现未识别牌值：{unknown.get('display_key', self._raw_key)}\n"
            f"来源：{unknown.get('note', '')}，次数：{unknown.get('count', 1)}"
        )
        title.setWordWrap(True)
        layout.addWidget(title)

        self._tile_combo = QComboBox()
        for tile_id in ALL_TILE_IDS:
            self._tile_combo.addItem(f"{TILE_NAME_MAP.get(tile_id, tile_id)} ({tile_id})", tile_id)
        layout.addWidget(self._tile_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_mapping(self) -> tuple[str, str]:
        return self._raw_key, str(self._tile_combo.currentData() or "")


class OpponentPredictionThread(QThread):
    finished_ok = pyqtSignal(object, object)
    finished_err = pyqtSignal(object, str)

    def __init__(self, signature: tuple, snapshot: dict, analysis_config: dict, parent=None):
        super().__init__(parent)
        self._signature = signature
        self._snapshot = deepcopy(snapshot)
        self._analysis_config = deepcopy(analysis_config)

    def run(self) -> None:
        try:
            analysis = analyze_snapshot(self._snapshot, self._analysis_config)
        except Exception as exc:
            self.finished_err.emit(self._signature, str(exc))
            return
        self.finished_ok.emit(self._signature, analysis)


class StableBattlePanel(QWidget):
    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    simulation_requested = pyqtSignal()
    config_requested = pyqtSignal()
    mapping_save_requested = pyqtSignal(str, str)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = deepcopy(config)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._snapshot: dict = {}
        self._notified_unknowns: set[str] = set()
        self._has_advice_rendered = False
        self._last_advice_signature: tuple | None = None
        self._prediction_worker: OpponentPredictionThread | None = None
        self._prediction_pending = False
        self._prediction_signature: tuple | None = None
        self._setup_ui()
        self.apply_config(config)
        self.set_running(False)

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)

        # ---- 顶部工具栏（精简分组） ----
        top = QHBoxLayout()
        self._start_btn = QPushButton("开始读取")
        self._start_btn.clicked.connect(self.start_requested.emit)
        top.addWidget(self._start_btn)
        self._stop_btn = QPushButton("停止")
        self._stop_btn.clicked.connect(self.stop_requested.emit)
        top.addWidget(self._stop_btn)
        self._simulate_btn = QPushButton("模拟出牌")
        self._simulate_btn.clicked.connect(self.simulation_requested.emit)
        top.addWidget(self._simulate_btn)

        # AI 设置弹框按钮
        self._ai_settings_btn = QPushButton("AI")
        self._ai_settings_btn.setToolTip("AI 分析设置")
        self._ai_settings_btn.clicked.connect(self._open_ai_settings_dialog)
        top.addWidget(self._ai_settings_btn)

        # 记录+训练弹框按钮
        self._record_training_btn = QPushButton("记录+训练")
        self._record_training_btn.setToolTip("记录本局与训练设置")
        self._record_training_btn.clicked.connect(self._open_record_training_dialog)
        top.addWidget(self._record_training_btn)

        # 预测设置弹框按钮
        self._prediction_settings_btn = QPushButton("预测")
        self._prediction_settings_btn.setToolTip("对手预测参数设置")
        self._prediction_settings_btn.clicked.connect(self._open_prediction_settings_dialog)
        top.addWidget(self._prediction_settings_btn)

        # 重新预测按钮（独立，方便快速触发）
        self._rerun_prediction_btn = QPushButton("重新预测")
        self._rerun_prediction_btn.clicked.connect(self._rerender_current_snapshot)
        top.addWidget(self._rerun_prediction_btn)

        top.addStretch()
        root.addLayout(top)

        # ---- 初始化弹框内控件（不在顶部显示） ----
        # AI 设置控件
        self._deepseek_checkbox = QCheckBox("开启 AI 分析")
        self._deepseek_checkbox.setChecked(False)
        self._ai_provider_combo = QComboBox()
        self._ai_provider_combo.addItem("DeepSeek", "deepseek")
        self._ai_provider_combo.addItem("通义千问", "qianwen")
        self._ai_provider_combo.currentIndexChanged.connect(self._sync_model_placeholder)
        self._ai_model_edit = QLineEdit()
        self._ai_model_edit.setFixedWidth(200)

        # 记录+训练控件
        self._record_training_checkbox = QCheckBox("记录本局")
        self._record_training_checkbox.setChecked(True)
        self._record_training_checkbox.toggled.connect(self._sync_training_controls)
        self._train_enabled_checkbox = QCheckBox("加入训练")
        self._train_enabled_checkbox.setChecked(False)

        # 预测设置控件
        self._opponent_prediction_checkbox = QCheckBox("对手预测")
        self._opponent_prediction_checkbox.setChecked(True)
        self._dynamic_prediction_checkbox = QCheckBox("动态分析")
        self._dynamic_prediction_checkbox.setChecked(True)
        self._particle_spin = QSpinBox()
        self._particle_spin.setRange(100, 20000)
        self._particle_spin.setSingleStep(500)
        self._particle_spin.setValue(5000)
        self._particle_spin.setFixedWidth(80)
        self._mc_spin = QSpinBox()
        self._mc_spin.setRange(100, 10000)
        self._mc_spin.setSingleStep(500)
        self._mc_spin.setValue(2000)
        self._mc_spin.setFixedWidth(80)
        self._bayes_checkbox = QCheckBox("贝叶斯")
        self._bayes_checkbox.setChecked(True)

        body = QHBoxLayout()
        root.addLayout(body, 1)

        left = QVBoxLayout()
        status_box = QGroupBox("稳定版状态")
        status_form = QFormLayout(status_box)
        self._capture_status = QLabel("idle")
        self._data_status = QLabel("--")
        self._turn_status = QLabel("--")
        self._baida_status = QLabel("--")
        self._note_status = QLabel("--")
        self._note_status.setWordWrap(True)
        status_form.addRow("抓包", self._capture_status)
        status_form.addRow("数据", self._data_status)
        status_form.addRow("回合", self._turn_status)
        status_form.addRow("财神", self._baida_status)
        status_form.addRow("备注", self._note_status)
        left.addWidget(status_box, 0)

        data_box = QGroupBox("实时数据")
        data_layout = QVBoxLayout(data_box)
        self._data_view = QTextEdit()
        self._data_view.setReadOnly(True)
        self._data_view.setMinimumHeight(180)
        data_layout.addWidget(self._data_view)
        left.addWidget(data_box, 2)

        event_box = QGroupBox("事件流")
        event_layout = QVBoxLayout(event_box)
        self._event_view = QTextEdit()
        self._event_view.setReadOnly(True)
        self._event_view.setMinimumHeight(120)
        event_layout.addWidget(self._event_view)
        left.addWidget(event_box, 1)
        body.addLayout(left, 2)

        middle = QVBoxLayout()
        advice_box = QGroupBox("策略建议")
        advice_layout = QVBoxLayout(advice_box)
        self._recommended_label = QLabel("当前推荐出牌：--")
        self._recommended_label.setWordWrap(True)
        advice_layout.addWidget(self._recommended_label)
        self._strategy_label = QLabel("策略类型：--")
        self._strategy_label.setWordWrap(True)
        advice_layout.addWidget(self._strategy_label)
        self._summary_edit = QTextEdit()
        self._summary_edit.setReadOnly(True)
        self._summary_edit.setFixedHeight(60)
        advice_layout.addWidget(self._summary_edit, 0)
        self._opponent_prediction_edit = QTextEdit()
        self._opponent_prediction_edit.setReadOnly(True)
        self._opponent_prediction_edit.setFixedHeight(240)
        advice_layout.addWidget(self._opponent_prediction_edit, 0)
        self._hand_structure_edit = QTextEdit()
        self._hand_structure_edit.setReadOnly(True)
        self._hand_structure_edit.setMinimumHeight(60)
        self._hand_structure_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        advice_layout.addWidget(self._hand_structure_edit, 0)
        middle.addWidget(advice_box, 1)
        body.addLayout(middle, 3)

        # 右侧：硬算分析（独立一列）
        right = QVBoxLayout()
        calc_box = QGroupBox("硬算分析")
        calc_layout = QVBoxLayout(calc_box)
        self._hard_calc_edit = QTextEdit()
        self._hard_calc_edit.setReadOnly(True)
        self._hard_calc_edit.setMinimumHeight(200)
        calc_layout.addWidget(self._hard_calc_edit, 1)
        self._candidates_edit = QTextEdit()
        self._candidates_edit.setReadOnly(True)
        self._candidates_edit.setMinimumHeight(200)
        calc_layout.addWidget(self._candidates_edit, 1)
        right.addWidget(calc_box, 1)
        body.addLayout(right, 2)

    def apply_config(self, config: dict) -> None:
        self._config = deepcopy(config)
        stable = self._config.get("stable_reader", {})
        provider = stable.get("ai_provider", "deepseek")
        idx = self._ai_provider_combo.findData(provider)
        self._ai_provider_combo.setCurrentIndex(max(0, idx))
        self._deepseek_checkbox.setChecked(bool(stable.get("deepseek_enabled", False)))
        self._ai_model_edit.setText(stable.get("ai_model", "") or self._default_model())
        self._sync_model_placeholder()
        # 抓包模式已移除 UI 控件，默认 npcap
        self._record_training_checkbox.setChecked(bool(stable.get("training_record_enabled", True)))
        self._train_enabled_checkbox.setChecked(bool(stable.get("training_enabled", False)))
        opponent_cfg = stable.get("opponent_prediction", {})
        if not isinstance(opponent_cfg, dict):
            opponent_cfg = {}
        self._opponent_prediction_checkbox.setChecked(bool(opponent_cfg.get("enabled", True)))
        self._dynamic_prediction_checkbox.setChecked(bool(opponent_cfg.get("dynamic_enabled", True)))
        self._particle_spin.setValue(int(opponent_cfg.get("particle_count", 5000)))
        self._mc_spin.setValue(int(opponent_cfg.get("monte_carlo_runs", 2000)))
        self._bayes_checkbox.setChecked(bool(opponent_cfg.get("bayes_enabled", True)))
        self._sync_training_controls()

    def _default_model(self) -> str:
        provider = str(self._ai_provider_combo.currentData() or "deepseek")
        fallback = {"deepseek": "deepseek-chat", "qianwen": "qwen-turbo-latest"}
        return self._config.get(provider, {}).get("model", fallback.get(provider, "")) or fallback.get(provider, "")

    def _sync_model_placeholder(self) -> None:
        self._ai_model_edit.setPlaceholderText(self._default_model())
        if not self._ai_model_edit.text().strip():
            self._ai_model_edit.setText(self._default_model())

    def _sync_training_controls(self) -> None:
        record_enabled = self._record_training_checkbox.isChecked()
        self._train_enabled_checkbox.setEnabled(record_enabled)
        if not record_enabled:
            self._train_enabled_checkbox.setChecked(False)

    def _open_ai_settings_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("AI 设置")
        layout = QFormLayout(dialog)

        deepseek_cb = QCheckBox("开启 AI 分析")
        deepseek_cb.setChecked(self._deepseek_checkbox.isChecked())
        layout.addRow(deepseek_cb)

        provider_combo = QComboBox()
        provider_combo.addItem("DeepSeek", "deepseek")
        provider_combo.addItem("通义千问", "qianwen")
        provider_combo.setCurrentIndex(self._ai_provider_combo.currentIndex())
        layout.addRow("AI Provider:", provider_combo)

        model_edit = QLineEdit()
        model_edit.setText(self._ai_model_edit.text())
        model_edit.setPlaceholderText(self._ai_model_edit.placeholderText())
        layout.addRow("模型:", model_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._deepseek_checkbox.setChecked(deepseek_cb.isChecked())
            self._ai_provider_combo.setCurrentIndex(provider_combo.currentIndex())
            self._ai_model_edit.setText(model_edit.text())
            self._sync_model_placeholder()

    def _open_record_training_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("记录+训练")
        layout = QFormLayout(dialog)

        record_cb = QCheckBox("记录本局")
        record_cb.setChecked(self._record_training_checkbox.isChecked())
        layout.addRow(record_cb)

        train_cb = QCheckBox("加入训练")
        train_cb.setChecked(self._train_enabled_checkbox.isChecked())
        train_cb.setEnabled(record_cb.isChecked())
        record_cb.toggled.connect(lambda checked: train_cb.setEnabled(checked))
        layout.addRow(train_cb)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._record_training_checkbox.setChecked(record_cb.isChecked())
            self._train_enabled_checkbox.setChecked(train_cb.isChecked())
            self._sync_training_controls()

    def _open_prediction_settings_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("预测设置")
        layout = QFormLayout(dialog)

        opp_cb = QCheckBox("对手预测")
        opp_cb.setChecked(self._opponent_prediction_checkbox.isChecked())
        layout.addRow(opp_cb)

        dyn_cb = QCheckBox("动态分析")
        dyn_cb.setChecked(self._dynamic_prediction_checkbox.isChecked())
        layout.addRow(dyn_cb)

        particle_spin = QSpinBox()
        particle_spin.setRange(100, 20000)
        particle_spin.setSingleStep(500)
        particle_spin.setValue(self._particle_spin.value())
        layout.addRow("粒子数量:", particle_spin)

        mc_spin = QSpinBox()
        mc_spin.setRange(100, 10000)
        mc_spin.setSingleStep(500)
        mc_spin.setValue(self._mc_spin.value())
        layout.addRow("MC 次数:", mc_spin)

        bayes_cb = QCheckBox("贝叶斯")
        bayes_cb.setChecked(self._bayes_checkbox.isChecked())
        layout.addRow(bayes_cb)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._opponent_prediction_checkbox.setChecked(opp_cb.isChecked())
            self._dynamic_prediction_checkbox.setChecked(dyn_cb.isChecked())
            self._particle_spin.setValue(particle_spin.value())
            self._mc_spin.setValue(mc_spin.value())
            self._bayes_checkbox.setChecked(bayes_cb.isChecked())

    def set_running(self, running: bool) -> None:
        self._start_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        self._capture_status.setText("读取中" if running else "未开始")
        if running:
            self._has_advice_rendered = False
            self._notified_unknowns.clear()

    def set_capture_status(self, text: str) -> None:
        msg = str(text or "")
        if msg == "idle":
            msg = "未开始"
        elif msg == "running":
            msg = "读取中"
        elif msg == "reading packets":
            msg = "正在读取抓包"
        elif msg == "stopped":
            msg = "已停止"
        elif msg.startswith("starting tcpdump"):
            msg = "正在启动抓包 (tcpdump)"
        elif msg.startswith("starting npcap"):
            msg = "正在启动抓包 (npcap)"
        self._capture_status.setText(msg)

    def analysis_options(self) -> dict:
        provider = str(self._ai_provider_combo.currentData() or "deepseek")
        model = self._ai_model_edit.text().strip() or self._default_model()
        return {
            "deepseek_enabled": self._deepseek_checkbox.isChecked(),
            "ai_provider": provider,
            "ai_model": model,
            "capture_mode": "npcap",  # 已移除 UI 选择，固定 npcap
            "training_record_enabled": self._record_training_checkbox.isChecked(),
            "training_enabled": self._train_enabled_checkbox.isChecked(),
            "training_session_mode": (
                "train_enabled"
                if self._record_training_checkbox.isChecked() and self._train_enabled_checkbox.isChecked()
                else ("record_only" if self._record_training_checkbox.isChecked() else "paused")
            ),
            "opponent_prediction": self._opponent_prediction_config(),
        }

    def _opponent_prediction_config(self) -> dict:
        return {
            "enabled": self._opponent_prediction_checkbox.isChecked(),
            "dynamic_enabled": self._dynamic_prediction_checkbox.isChecked(),
            "particle_count": int(self._particle_spin.value()),
            "monte_carlo_runs": int(self._mc_spin.value()),
            "bayes_enabled": self._bayes_checkbox.isChecked(),
            "top_tile_count": 8,
            "representative_hand_count": 3,
        }

    def _analysis_config(self) -> dict:
        return {"opponent_prediction": self._opponent_prediction_config()}

    def _rerender_current_snapshot(self) -> None:
        if self._snapshot:
            self._render_hard_analysis(self._snapshot, force_prediction=True)

    def _analysis_signature(self, snapshot: dict) -> tuple:
        players = snapshot.get("players", {}) if isinstance(snapshot.get("players"), dict) else {}
        local = snapshot.get("local_player")
        opponent = snapshot.get("opponent_player")
        local_player = players.get(local) or players.get(str(local)) or {}
        opponent_player = players.get(opponent) or players.get(str(opponent)) or {}
        return (
            snapshot.get("phase"),
            snapshot.get("current_turn"),
            snapshot.get("remaining_tiles"),
            snapshot.get("baida_tile"),
            tuple(local_player.get("hand", []) or []),
            tuple(local_player.get("discards", []) or []),
            tuple(opponent_player.get("discards", []) or []),
            tuple((m.get("type"), tuple(m.get("tiles", []) or [])) for m in opponent_player.get("melds", []) or []),
            opponent_player.get("hand_count", 0),
            tuple(sorted(self._opponent_prediction_config().items())),
        )

    def set_snapshot(self, snapshot: dict) -> None:
        self._snapshot = deepcopy(snapshot)
        phase = snapshot.get("phase", "--")
        local = snapshot.get("local_player", "?")
        opponent = snapshot.get("opponent_player", "?")
        turn = snapshot.get("current_turn", "none")
        remaining = snapshot.get("remaining_tiles", "--")
        blocked = snapshot.get("analysis_blocked_reason", "")
        ready = bool(snapshot.get("analysis_ready"))
        ready_text = "可分析" if ready else (blocked or "等待抓包数据")
        self._data_status.setText(f"{_phase_text(phase)}；剩余 {remaining} 张；{ready_text}")
        self._turn_status.setText(f"我方座位 {local}；对面座位 {opponent}；{_turn_text(turn)}")
        baida = snapshot.get("baida_tile") or ""
        baida_trusted = bool(snapshot.get("baida_trusted"))
        self._baida_status.setText(TILE_NAME_MAP.get(baida, baida) if baida and baida_trusted else "等待抓包解析财神")
        self._note_status.setText(str(snapshot.get("action_note") or "暂无"))

        players = snapshot.get("players", {})
        lines: list[str] = []
        for pid in [local, opponent]:
            p = players.get(pid) or players.get(str(pid))
            if not p:
                continue
            marker = "我方" if int(pid) == int(local) else "对面"
            trust_note = "\n  状态：等待可信手牌包" if int(pid) == int(local) and not snapshot.get("hand_trusted") else ""
            lines.append(
                f"{marker}（座位 {pid}）\n"
                f"  手牌（已知 {len(p.get('hand', []))} / 计数 {p.get('hand_count', 0)}）：{_fmt_tiles(p.get('hand', []))}\n"
                f"  弃牌：{_fmt_tiles(p.get('discards', []))}\n"
                f"  副露：{self._fmt_melds(p.get('melds', []))}{trust_note}"
            )
        data_was_near_bottom = _is_near_bottom(self._data_view)
        self._data_view.setPlainText("\n\n".join(lines))
        if data_was_near_bottom:
            _scroll_to_bottom(self._data_view)

        event_was_near_bottom = _is_near_bottom(self._event_view)
        self._event_view.setPlainText("\n".join(snapshot.get("events", [])[-120:]))
        if event_was_near_bottom:
            _scroll_to_bottom(self._event_view)

        unknowns = snapshot.get("unknowns", [])
        self._set_unknowns(unknowns)
        self._notify_unknowns(unknowns)
        self._render_hand_structure(snapshot)
        self._render_hard_analysis(snapshot)

    def _refresh_advice_placeholder(self, snapshot: dict) -> None:
        mode = str(snapshot.get("analysis_mode") or "")
        reason = str(snapshot.get("analysis_blocked_reason") or "").strip()
        ready = bool(snapshot.get("analysis_ready"))
        players = snapshot.get("players", {})
        local = snapshot.get("local_player")
        local_player = players.get(local) or players.get(str(local)) if isinstance(players, dict) else {}
        signature = (
            snapshot.get("current_turn"),
            tuple((local_player or {}).get("hand", [])),
            mode,
            reason,
        )
        if self._last_advice_signature != signature and (not ready or mode == "blocked"):
            self._has_advice_rendered = False
        self._last_advice_signature = signature
        if self._has_advice_rendered and ready:
            return
        if mode == "blocked":
            text = reason or "等待可信手牌包"
            self._recommended_label.setText(f"等待中：{text}")
            self._strategy_label.setText("策略类型：等待门槛")
            self._summary_edit.setPlainText(text)
        elif mode == "conservative":
            text = reason or "财神或回合信息不全"
            self._recommended_label.setText(f"等待中：{text}")
            self._strategy_label.setText("策略类型：[保守] 等待中")
        else:
            self._recommended_label.setText("当前推荐出牌：等待 AI 返回...")
            self._strategy_label.setText("策略类型：等待中")

    @staticmethod
    def _fmt_melds(melds: list[dict]) -> str:
        if not melds:
            return "（空）"
        type_map = {
            "chi": "吃",
            "pon": "碰",
            "kan_open": "明杠",
            "kan_closed": "暗杠",
            "kan_added": "补杠",
        }
        parts = []
        for meld in melds:
            tiles = _fmt_tiles(list(meld.get("tiles", [])))
            meld_type = type_map.get(str(meld.get("type", "")), "副露")
            parts.append(f"{meld_type}[{tiles}]")
        return " ".join(parts)

    def _set_unknowns(self, unknowns: list[dict]) -> None:
        return

    def _notify_unknowns(self, unknowns: list[dict]) -> None:
        fresh = [u for u in unknowns if u.get("raw_key") and u.get("raw_key") not in self._notified_unknowns]
        if not fresh:
            return
        first = fresh[0]
        for item in fresh:
            self._notified_unknowns.add(str(item.get("raw_key")))
        dialog = UnknownTileDialog(first, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            raw_key, tile_id = dialog.selected_mapping()
            if raw_key and tile_id:
                self.mapping_save_requested.emit(raw_key, tile_id)

    def _save_selected_mapping(self) -> None:
        return

    def set_busy(self, busy: bool, message: str = "") -> None:
        self._data_status.setText(message or ("正在分析" if busy else "就绪"))
        if busy:
            self._has_advice_rendered = False

    def clear_stream_buffer(self) -> None:
        return

    def append_stream_chunk(self, chunk: str) -> None:
        return

    def set_advice(self, state, advice: BattleAdvice) -> None:
        self._render_state_hard_analysis(state)
        self._note_status.setText(self._build_note_from_state(state))
        self._has_advice_rendered = True

    def _render_hard_analysis(self, snapshot: dict, force_prediction: bool = False) -> None:
        analysis = analyze_snapshot(snapshot, {"opponent_prediction": {"enabled": False}})
        self._apply_hard_analysis(analysis)
        self._start_opponent_prediction(snapshot, force=force_prediction)

    def _start_opponent_prediction(self, snapshot: dict, force: bool = False) -> None:
        config = self._analysis_config()
        opponent_config = config.get("opponent_prediction", {})
        if not opponent_config.get("enabled", True):
            return
        signature = self._analysis_signature(snapshot)
        if not force and signature == self._prediction_signature:
            return
        self._prediction_signature = signature
        if opponent_config.get("dynamic_enabled", True):
            has_value, score, reasons = self._prediction_value_result(snapshot)
            if not has_value:
                reason_text = " / ".join(reasons) if reasons else "公开信息不足"
                self._opponent_prediction_edit.setHtml(
                    '<span style="color:#8e8e93; font-size:10px;">'
                    f'动态分析：证据不足，暂不计算（评分 {score}/4）。{escape(reason_text)}'
                    '</span>'
                )
                return
        self._opponent_prediction_edit.setHtml(
            '<span style="color:#8e8e93">对手手牌预测：计算中...</span>'
        )
        if self._prediction_worker is not None and self._prediction_worker.isRunning():
            self._prediction_pending = True
            return
        self._prediction_pending = False
        worker = OpponentPredictionThread(signature, snapshot, config, self)
        self._prediction_worker = worker
        worker.finished_ok.connect(self._on_opponent_prediction_finished)
        worker.finished_err.connect(self._on_opponent_prediction_failed)
        worker.finished.connect(self._on_opponent_prediction_thread_finished)
        worker.start()

    def _on_opponent_prediction_finished(self, signature: tuple, analysis: StableHardAnalysis) -> None:
        if signature == self._prediction_signature:
            self._opponent_prediction_edit.setHtml(self._format_opponent_prediction_html(analysis))

    def _on_opponent_prediction_failed(self, signature: tuple, message: str) -> None:
        if signature == self._prediction_signature:
            self._opponent_prediction_edit.setHtml(
                f'<span style="color:#e74c3c">对手手牌预测失败：{escape(message)}</span>'
            )

    def _on_opponent_prediction_thread_finished(self) -> None:
        self._prediction_worker = None
        if self._prediction_pending and self._snapshot:
            self._prediction_pending = False
            self._start_opponent_prediction(self._snapshot, force=True)

    def _prediction_value_result(self, snapshot: dict) -> tuple[bool, int, list[str]]:
        players = snapshot.get("players", {}) if isinstance(snapshot.get("players"), dict) else {}
        opponent = snapshot.get("opponent_player")
        opponent_player = players.get(opponent) or players.get(str(opponent)) or {}
        enemy_discards = [str(tile) for tile in opponent_player.get("discards", []) if tile]
        enemy_melds = list(opponent_player.get("melds", []) or [])
        enemy_meld_tiles = [
            str(tile)
            for meld in enemy_melds
            if isinstance(meld, dict)
            for tile in (meld.get("tiles", []) or [])
            if tile
        ]
        remaining_tiles = int(snapshot.get("remaining_tiles") or 0)
        optional_actions = [str(action) for action in snapshot.get("optional_actions", []) if action]
        score = 0
        reasons: list[str] = []

        discard_count = len(enemy_discards)
        if discard_count >= 7:
            score += 2
        elif discard_count >= 4:
            score += 1
        else:
            reasons.append("对手弃牌少")

        meld_count = len(enemy_melds)
        if meld_count >= 2:
            score += 3
        elif meld_count >= 1:
            score += 2
        else:
            reasons.append("对手无副露")

        if remaining_tiles <= 24:
            score += 3
        elif remaining_tiles <= 35:
            score += 2
        elif remaining_tiles <= 50:
            score += 1
        else:
            reasons.append("牌局仍偏早")

        if str(snapshot.get("current_turn") or "") == "self":
            score += 1
        if optional_actions:
            score += 2
        if snapshot.get("baida_trusted"):
            score += 1
        else:
            reasons.append("财神未可信")
        if int(opponent_player.get("hand_count") or 0) >= 8:
            score += 1

        suit_counts: dict[str, int] = {}
        for tile in enemy_meld_tiles:
            suit = tile[-1:] if len(tile) >= 2 else ""
            if suit and suit != "z":
                suit_counts[suit] = suit_counts.get(suit, 0) + 1
        if suit_counts and max(suit_counts.values()) >= 3:
            score += 1

        if score >= 4:
            return True, score, []
        return False, score, reasons

    def _render_state_hard_analysis(self, state) -> None:
        if self._snapshot:
            self._render_hard_analysis(self._snapshot)

    def _render_hand_structure(self, snapshot: dict) -> None:
        players = snapshot.get("players", {}) if isinstance(snapshot.get("players"), dict) else {}
        local = snapshot.get("local_player")
        local_player = players.get(local) or players.get(str(local)) or {}
        hand = [str(tile) for tile in local_player.get("hand", [])]
        melds = list(local_player.get("melds", []) or [])
        response_text = self._response_context_text(snapshot)
        structure_title = "手牌结构"
        if "hu" in [str(value) for value in snapshot.get("optional_actions", []) if value]:
            action_tile = str(snapshot.get("action_tile") or "")
            if str(snapshot.get("action_source") or "") == "opponent_discard" and action_tile:
                hand = hand + [action_tile]
                structure_title = f"手牌结构（加入 {TILE_NAME_MAP.get(action_tile, action_tile)} 后）"
        analysis = analyze_snapshot(snapshot, {"opponent_prediction": {"enabled": False}})
        arrangements = build_hand_structure_arrangements(
            hand,
            melds,
            recommended_discard=analysis.recommended_discard,
            limit=3,
        )
        lines = []
        if response_text:
            lines.append(f'<div style="color:#f39c12; margin-bottom:6px;">{escape(response_text)}</div>')
        lines.append(self._format_hand_structure_arrangements_html(arrangements, structure_title))
        self._hand_structure_edit.setHtml("".join(lines))

    @staticmethod
    def _response_context_text(snapshot: dict) -> str:
        actions = [str(value) for value in snapshot.get("optional_actions", []) if value]
        tile = str(snapshot.get("action_tile") or "")
        source = str(snapshot.get("action_source") or "")
        tile_text = TILE_NAME_MAP.get(tile, tile) if tile else "当前牌"
        if "hu" in actions and source == "opponent_discard":
            return f"响应对方打出的 {tile_text} 可胡，不是自摸。"
        if "hu" in actions and source == "self_draw":
            return "当前手牌自摸可胡。"
        if actions and source == "opponent_discard":
            names = " / ".join(actions)
            return f"响应对方打出的 {tile_text}：{names}"
        return ""

    @staticmethod
    def _format_hand_structure_html(groups: list[HandStructureGroup], title: str = "手牌结构") -> str:
        if not groups:
            return f'<span style="color:#8e8e93">{escape(title)}：（空）</span>'
        colors = {
            "meld": "#58a6ff",
            "triplet": "#3fb950",
            "sequence": "#3fb950",
            "pair": "#d29922",
            "taatsu": "#a371f7",
            "edge_wait": "#ff7b72",
            "single": "#8b949e",
        }
        parts = []
        if title:
            parts.append(f'<div style="color:#c9d1d9; margin-bottom:4px;">{escape(title)}</div>')
        for group in groups:
            color = colors.get(group.kind, "#c9d1d9")
            tiles = " ".join(TILE_NAME_MAP.get(tile, tile) for tile in group.tiles)
            parts.append(
                f'<span style="display:inline-block; color:{color}; margin-right:10px;">'
                f'{escape(group.label)}[{escape(tiles)}]</span>'
            )
        return "".join(parts)

    @staticmethod
    def _format_hand_structure_arrangements_html(
        arrangements: list[list[HandStructureGroup]],
        title: str = "手牌结构",
    ) -> str:
        if not arrangements:
            return f'<span style="color:#8e8e93">{escape(title)}：（空）</span>'
        if len(arrangements) == 1:
            return StableBattlePanel._format_hand_structure_html(arrangements[0], title)

        parts = [f'<div style="color:#c9d1d9; margin-bottom:4px;">{escape(title)}（多种组合）</div>']
        for idx, groups in enumerate(arrangements, start=1):
            parts.append(
                f'<div style="margin-top:3px; line-height:1.5;"><span style="color:#8e8e93;">组合{idx}：</span>'
                f'{StableBattlePanel._format_hand_structure_html(groups, "")}</div>'
            )
        # 添加一个撑开容器高度的透明元素，确保多组合时容器能自适应
        parts.append('<div style="height:1px;"></div>')
        return "".join(parts)

    def _apply_hard_analysis(self, analysis: StableHardAnalysis) -> None:
        self._recommended_label.setText(f"当前建议：{analysis.current_advice}")
        self._strategy_label.setText(f"当前状态：{analysis.current_status}；财神：{analysis.caishen_text}")
        self._summary_edit.setPlainText(analysis.advice_reason)
        self._opponent_prediction_edit.setHtml(self._format_opponent_prediction_html(analysis))
        self._hard_calc_edit.setHtml(self._format_strategy_analysis_html(analysis))
        self._candidates_edit.setHtml(self._format_candidates_html(analysis.candidates))

    def _format_opponent_prediction_html(self, analysis: StableHardAnalysis) -> str:
        prediction = analysis.opponent_prediction
        if not prediction:
            return '<span style="color:#8e8e93; font-size:10px;">对手手牌预测：等待数据</span>'
        if not prediction.enabled:
            return '<span style="color:#8e8e93; font-size:10px;">对手手牌预测：已关闭</span>'

        def _pct(value: float) -> str:
            if 0 < value < 0.01:
                return "<1%"
            if value < 0.1:
                return f"{value * 100:.1f}%"
            return f"{value * 100:.0f}%"

        def _level_text(level: str) -> str:
            return {"high": "高", "medium": "中", "low": "低"}.get(level, level)

        def _prob_table(rows: list[tuple[str, str, str]]) -> str:
            body = "".join(
                "<tr>"
                f'<td style="padding:1px 6px 1px 2px;">{escape(name)}</td>'
                f'<td style="padding:1px 6px 1px 2px; text-align:right;">{prob}</td>'
                f'<td style="padding:1px 2px 1px 2px;">{escape(note)}</td>'
                "</tr>"
                for name, prob, note in rows
            )
            if not body:
                body = '<tr><td colspan="3" style="padding:1px 2px; color:#8e8e93;">暂无</td></tr>'
            return (
                '<table style="border-collapse:collapse; color:#c9d1d9; font-size:10px; width:100%;">'
                '<tr style="color:#8b949e;"><td>牌</td><td>概率</td><td>说明</td></tr>'
                f"{body}</table>"
            )

        danger_rows = [
            (TILE_NAME_MAP.get(item.tile, item.tile), _pct(item.probability), _level_text(item.level))
            for item in sorted(prediction.danger_tiles, key=lambda value: (-value.probability, value.tile))[:5]
        ]
        held_rows = [
            (TILE_NAME_MAP.get(item.tile, item.tile), _pct(item.probability), "可能在对手手里")
            for item in sorted(prediction.tile_probabilities, key=lambda value: (-value.probability, value.tile))[:5]
        ]
        wait_rows = [
            (TILE_NAME_MAP.get(item.tile, item.tile), _pct(item.probability), "可能听这张")
            for item in sorted(prediction.wait_probabilities, key=lambda value: (-value.probability, value.tile))[:5]
        ]
        dist = " / ".join(
            f"{escape(str(key))}:{_pct(float(value))}"
            for key, value in prediction.shanten_distribution.items()
        ) or "暂无"
        bayes = "开" if prediction.bayes_enabled else "关"

        danger_html = _prob_table(danger_rows)
        held_html = _prob_table(held_rows)
        wait_html = _prob_table(wait_rows)

        return (
            '<div style="border:1px solid #e74c3c; padding:4px; line-height:1.25; font-size:10px;">'
            '<div style="color:#ff6b57; font-weight:bold;">对手手牌预测（公开信息后验估计）</div>'
            f'<div style="color:#8e8e93;">可信度 {escape(prediction.confidence)} / '
            f'粒子 {prediction.particle_count} / MC {prediction.monte_carlo_runs} / 贝叶斯 {bayes}</div>'
            f'<div style="color:#4a90d9;">进度：听牌 {_pct(prediction.tenpai_probability)}；向听 {dist}</div>'
            '<table style="width:100%; border-collapse:collapse; margin-top:4px;">'
            '<tr style="vertical-align:top;">'
            f'<td style="width:33%; padding-right:4px;">'
            f'<div style="color:#e74c3c; font-weight:bold; margin-bottom:2px;">对我方危险牌</div>{danger_html}</td>'
            f'<td style="width:33%; padding-left:2px; padding-right:2px;">'
            f'<div style="color:#d4a017; font-weight:bold; margin-bottom:2px;">高概率持有</div>{held_html}</td>'
            f'<td style="width:33%; padding-left:4px;">'
            f'<div style="color:#a371f7; font-weight:bold; margin-bottom:2px;">可能等待</div>{wait_html}</td>'
            '</tr></table>'
            '</div>'
        )

    def _format_strategy_analysis(self, analysis: StableHardAnalysis) -> str:
        shanten = "--" if analysis.current_shanten is None else str(analysis.current_shanten)
        return "\n".join(
            [
                f"当前状态：{analysis.current_status}",
                f"财神：{analysis.caishen_text}",
                f"当前向听：{shanten}",
                f"是否听牌：{'是' if analysis.is_ting else '否'}",
                f"听牌列表：{self._fmt_waits(analysis.ting_tiles)}",
                f"最佳进听打法：{self._fmt_best_ting_discards(analysis.best_ting_discards)}",
                f"有效进张：{analysis.effective_count} 张（{_fmt_tiles(analysis.effective_tiles)}）",
                f"对方手牌可能性预测：{analysis.opponent_hand_prediction}",
                f"对方进度预测：{analysis.opponent_progress_prediction}",
                f"当前建议：{analysis.current_advice}",
                f"建议原因：{analysis.advice_reason}",
                f"强提醒：{'；'.join(analysis.strong_reminders)}",
                f"财神风险：{analysis.caishen_risk}",
                f"模型状态：{analysis.model_status}",
                f"推荐来源：{analysis.recommendation_source or '无'}",
                "候选重排：",
                self._fmt_model_candidates(analysis.candidates),
                f"数据可信度：{analysis.data_confidence}",
            ]
        )

    def _format_strategy_analysis_html(self, analysis: StableHardAnalysis) -> str:
        shanten = "--" if analysis.current_shanten is None else str(analysis.current_shanten)

        def _c(text: str, color: str) -> str:
            return f'<span style="color:{color}">{text}</span>'

        # 左列：牌局状态类
        left_lines: list[str] = []
        left_lines.append(_c(f"当前状态：{analysis.current_status}", "#4a90d9"))
        left_lines.append(_c(f"财神：{analysis.caishen_text}", "#d4a017"))
        left_lines.append(_c(f"当前向听：{shanten}", "#4a90d9"))
        left_lines.append(_c(f"是否听牌：{'是' if analysis.is_ting else '否'}", "#4a90d9"))
        left_lines.append(_c(f"听牌列表：{self._fmt_waits(analysis.ting_tiles)}", "#4a90d9"))
        left_lines.append(_c(f"最佳进听打法：{self._fmt_best_ting_discards(analysis.best_ting_discards)}", "#4a90d9"))
        left_lines.append(_c(f"有效进张：{analysis.effective_count} 张（{_fmt_tiles(analysis.effective_tiles)}）", "#4a90d9"))

        # 右列：分析建议类
        right_lines: list[str] = []
        right_lines.append(_c(f"当前建议：{analysis.current_advice}", "#2ecc71"))
        # 建议原因：如果有对手预测相关文本，用红色高亮
        advice_reason = escape(analysis.advice_reason)
        if "[预测]" in advice_reason:
            advice_reason = advice_reason.replace(
                "[预测]",
                '<span style="color:#e74c3c; font-weight:bold;">[预测]</span>'
            )
            # 将整条建议原因中的预测部分用红色包裹
            parts = advice_reason.split("；")
            colored_parts = []
            for part in parts:
                if "对手预测" in part:
                    colored_parts.append(f'<span style="color:#e74c3c">{part}</span>')
                else:
                    colored_parts.append(part)
            advice_reason = "；".join(colored_parts)
        right_lines.append(_c(f"建议原因：{advice_reason}", "#2ecc71"))

        reminders = "；".join(analysis.strong_reminders)
        reminder_color = "#e74c3c" if reminders != "无硬错误" else "#2ecc71"
        right_lines.append(_c(f"强提醒：{reminders}", reminder_color))

        caishen_risk_color = "#e74c3c" if "高" in analysis.caishen_risk else ("#f39c12" if "中" in analysis.caishen_risk else "#2ecc71")
        right_lines.append(_c(f"财神风险：{analysis.caishen_risk}", caishen_risk_color))

        # 模型状态和推荐来源暂不显示（保留代码以便后续恢复）
        # right_lines.append(_c(f"模型状态：{analysis.model_status}", "#9b59b6"))
        # right_lines.append(_c(f"推荐来源：{analysis.recommendation_source or '无'}", "#9b59b6"))

        conf_color = "#e74c3c" if "不足" in analysis.data_confidence or "等待" in analysis.data_confidence or "未知" in analysis.data_confidence else "#8e8e93"
        right_lines.append(_c(f"数据可信度：{analysis.data_confidence}", conf_color))

        # 两列布局容器（使用 HTML table，QTextEdit 不支持 flex）
        # 左列：牌局状态类 | 右列：分析建议类
        # 候选重排已独立到 _candidates_edit 展示
        left_html = "<br>".join(left_lines)
        right_html = "<br>".join(right_lines)

        parts: list[str] = []
        parts.append(
            f'<table style="width:100%; border-collapse:collapse;">'
            f'<tr>'
            f'<td style="width:50%; vertical-align:top; padding-right:8px;">{left_html}</td>'
            f'<td style="width:50%; vertical-align:top; padding-left:8px;">{right_html}</td>'
            f'</tr>'
            f'</table>'
        )

        return "<br>".join(parts)

    def _format_hard_analysis(self, analysis: StableHardAnalysis) -> str:
        shanten = "--" if analysis.current_shanten is None else str(analysis.current_shanten)
        return "\n".join(
            [
                f"当前状态：{analysis.current_status}",
                f"财神：{analysis.caishen_text}",
                f"当前向听：{shanten}",
                f"是否听牌：{'是' if analysis.is_ting else '否'}",
                f"听牌列表：{self._fmt_waits(analysis.ting_tiles)}",
                f"最佳进听打法：{self._fmt_best_ting_discards(analysis.best_ting_discards)}",
                f"有效进张：{analysis.effective_count} 张（{_fmt_tiles(analysis.effective_tiles)}）",
                f"对方手牌可能性预测：{analysis.opponent_hand_prediction}",
                f"对方进度预测：{analysis.opponent_progress_prediction}",
                f"当前建议：{analysis.current_advice}",
                f"建议原因：{analysis.advice_reason}",
                f"强提醒：{'；'.join(analysis.strong_reminders)}",
                f"财神风险：{analysis.caishen_risk}",
                f"数据可信度：{analysis.data_confidence}",
            ]
        )

    @staticmethod
    def _fmt_waits(waits: list[dict]) -> str:
        if not waits:
            return "（空）"
        parts = []
        for wait in waits:
            tile = str(wait.get("tile") or "")
            remaining = int(wait.get("remaining") or 0)
            parts.append(f"{TILE_NAME_MAP.get(tile, tile)}x{remaining}")
        return " / ".join(parts)

    def _fmt_best_ting_discards(self, candidates: list) -> str:
        if not candidates:
            return "暂无"
        parts = []
        for candidate in candidates[:4]:
            discard = TILE_NAME_MAP.get(candidate.discard, candidate.discard)
            waits = self._fmt_waits(candidate.ting_tiles)
            parts.append(f"打 {discard} -> {waits}")
        return "；".join(parts)

    @staticmethod
    def _fmt_model_candidates(candidates: list) -> str:
        if not candidates:
            return "  暂无：等待完整可信抓包数据"
        lines = []
        for idx, candidate in enumerate(candidates[:6], start=1):
            discard = TILE_NAME_MAP.get(candidate.discard, candidate.discard)
            reason = " / ".join(candidate.model_reasons[:4]) if candidate.model_reasons else "硬算候选"
            lines.append(
                f"  {idx}. 打 {discard} | 分 {candidate.model_score:.1f} | "
                f"向听 {candidate.shanten_after} | 进张 {candidate.ukeire_count} | {reason}"
            )
        return "\n".join(lines)

    @staticmethod
    def _fmt_model_candidates_html(candidates: list) -> str:
        if not candidates:
            return '<span style="color:#8e8e93">  暂无：等待完整可信抓包数据</span>'
        lines = []
        for idx, candidate in enumerate(candidates[:6], start=1):
            discard = TILE_NAME_MAP.get(candidate.discard, candidate.discard)
            reason = " / ".join(candidate.model_reasons[:4]) if candidate.model_reasons else "硬算候选"
            score_color = "#2ecc71" if candidate.model_score >= 80 else ("#f39c12" if candidate.model_score >= 50 else "#e74c3c")
            lines.append(
                f'<span style="color:#4a90d9">  {idx}. 打 {discard}</span> | '
                f'<span style="color:{score_color}">分 {candidate.model_score:.1f}</span> | '
                f'<span style="color:#4a90d9">向听 {candidate.shanten_after}</span> | '
                f'<span style="color:#4a90d9">进张 {candidate.ukeire_count}</span> | '
                f'<span style="color:#8e8e93">{reason}</span>'
            )
        return "<br>".join(lines)

    @staticmethod
    def _format_candidates_html(candidates: list) -> str:
        """独立候选重排 HTML 格式（用于右侧独立面板）。"""
        if not candidates:
            return '<div style="color:#8e8e93; font-size:10px;">候选重排：等待完整可信抓包数据</div>'
        lines: list[str] = []
        lines.append('<div style="color:#9b59b6; font-weight:bold; font-size:11px; margin-bottom:4px;">候选重排</div>')
        for idx, candidate in enumerate(candidates[:8], start=1):
            discard = TILE_NAME_MAP.get(candidate.discard, candidate.discard)
            reason = " / ".join(candidate.model_reasons[:4]) if candidate.model_reasons else "硬算候选"
            score_color = "#2ecc71" if candidate.model_score >= 80 else ("#f39c12" if candidate.model_score >= 50 else "#e74c3c")
            opponent_penalty = float(getattr(candidate, "opponent_penalty", 0.0))
            penalty_color = "#e74c3c" if opponent_penalty > 0 else "#8e8e93"
            penalty_html = f' | <span style="color:{penalty_color}">预测扣 {opponent_penalty:.1f}</span>'
            lines.append(
                f'<div style="font-size:10px; margin-bottom:2px;">'
                f'<span style="color:#4a90d9">{idx}. 打 {discard}</span> | '
                f'<span style="color:{score_color}">分 {candidate.model_score:.1f}</span> | '
                f'<span style="color:#4a90d9">向听 {candidate.shanten_after}</span> | '
                f'<span style="color:#4a90d9">进张 {candidate.ukeire_count}</span>'
                f'{penalty_html}<br>'
                f'<span style="color:#8e8e93; padding-left:12px;">{reason}</span>'
                f'</div>'
            )
        return "".join(lines)

    def _build_note_from_state(self, state) -> str:
        analysis = getattr(state, "last_analysis", {}) or {}
        shanten = analysis.get("shanten")
        waits = analysis.get("waiting_tiles") or analysis.get("ukeire_tiles") or []
        if shanten == -1:
            return "当前手牌已成胡。"
        if shanten == 0:
            if waits:
                names = " ".join(TILE_NAME_MAP.get(str(t), str(t)) for t in waits)
                return f"听牌/胡标记：可胡 {names}"
            return "听牌/胡标记：已听牌。"
        return "暂无"

    def set_error(self, message: str) -> None:
        self._summary_edit.setPlainText(message)
