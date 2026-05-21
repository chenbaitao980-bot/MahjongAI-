from __future__ import annotations

from copy import deepcopy

from PyQt6.QtCore import pyqtSignal
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from battle.state import BattleAdvice
from game.stable_hard_analysis import StableHardAnalysis, analyze_snapshot
from game.state import ALL_TILE_IDS
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
        self._setup_ui()
        self.apply_config(config)
        self.set_running(False)

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)

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
        self._config_btn = QPushButton("API 设置")
        self._config_btn.clicked.connect(self.config_requested.emit)
        top.addWidget(self._config_btn)

        self._deepseek_checkbox = QCheckBox("开启 AI 分析")
        self._deepseek_checkbox.setChecked(True)
        top.addWidget(self._deepseek_checkbox)
        self._ai_provider_combo = QComboBox()
        self._ai_provider_combo.addItem("DeepSeek", "deepseek")
        self._ai_provider_combo.addItem("通义千问", "qianwen")
        self._ai_provider_combo.currentIndexChanged.connect(self._sync_model_placeholder)
        top.addWidget(self._ai_provider_combo)
        self._ai_model_edit = QLineEdit()
        self._ai_model_edit.setFixedWidth(150)
        top.addWidget(self._ai_model_edit)

        top.addWidget(QLabel("抓包:"))
        self._capture_mode_combo = QComboBox()
        self._capture_mode_combo.addItem("npcap (主机侧)", "npcap")
        self._capture_mode_combo.addItem("tcpdump (模拟器)", "tcpdump")
        self._capture_mode_combo.setFixedWidth(140)
        top.addWidget(self._capture_mode_combo)

        self._record_training_checkbox = QCheckBox("记录本局")
        self._record_training_checkbox.setChecked(True)
        self._record_training_checkbox.toggled.connect(self._sync_training_controls)
        top.addWidget(self._record_training_checkbox)
        self._train_enabled_checkbox = QCheckBox("加入训练")
        self._train_enabled_checkbox.setChecked(False)
        top.addWidget(self._train_enabled_checkbox)

        top.addStretch()
        root.addLayout(top)

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
        root.addWidget(status_box)

        body = QHBoxLayout()
        root.addLayout(body, 1)

        left = QVBoxLayout()
        data_box = QGroupBox("实时数据")
        data_layout = QVBoxLayout(data_box)
        self._data_view = QTextEdit()
        self._data_view.setReadOnly(True)
        self._data_view.setMinimumHeight(220)
        data_layout.addWidget(self._data_view)
        left.addWidget(data_box, 2)

        event_box = QGroupBox("事件流")
        event_layout = QVBoxLayout(event_box)
        self._event_view = QTextEdit()
        self._event_view.setReadOnly(True)
        self._event_view.setMinimumHeight(160)
        event_layout.addWidget(self._event_view)
        left.addWidget(event_box, 1)
        body.addLayout(left, 2)

        right = QVBoxLayout()
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
        self._summary_edit.setMinimumHeight(64)
        self._summary_edit.setMaximumHeight(96)
        advice_layout.addWidget(self._summary_edit, 0)
        self._hard_calc_edit = QTextEdit()
        self._hard_calc_edit.setReadOnly(True)
        self._hard_calc_edit.setMinimumHeight(420)
        advice_layout.addWidget(self._hard_calc_edit, 1)
        right.addWidget(advice_box, 1)
        body.addLayout(right, 3)

    def apply_config(self, config: dict) -> None:
        self._config = deepcopy(config)
        stable = self._config.get("stable_reader", {})
        provider = stable.get("ai_provider", "deepseek")
        idx = self._ai_provider_combo.findData(provider)
        self._ai_provider_combo.setCurrentIndex(max(0, idx))
        self._deepseek_checkbox.setChecked(bool(stable.get("deepseek_enabled", True)))
        self._ai_model_edit.setText(stable.get("ai_model", "") or self._default_model())
        self._sync_model_placeholder()
        cap_idx = self._capture_mode_combo.findData(stable.get("capture_mode", "npcap"))
        self._capture_mode_combo.setCurrentIndex(max(0, cap_idx))
        self._record_training_checkbox.setChecked(bool(stable.get("training_record_enabled", True)))
        self._train_enabled_checkbox.setChecked(bool(stable.get("training_enabled", False)))
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
            "capture_mode": str(self._capture_mode_combo.currentData() or "npcap"),
            "training_record_enabled": self._record_training_checkbox.isChecked(),
            "training_enabled": self._train_enabled_checkbox.isChecked(),
            "training_session_mode": (
                "train_enabled"
                if self._record_training_checkbox.isChecked() and self._train_enabled_checkbox.isChecked()
                else ("record_only" if self._record_training_checkbox.isChecked() else "paused")
            ),
        }

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

    def _render_hard_analysis(self, snapshot: dict) -> None:
        analysis = analyze_snapshot(snapshot)
        self._apply_hard_analysis(analysis)

    def _render_state_hard_analysis(self, state) -> None:
        if self._snapshot:
            self._render_hard_analysis(self._snapshot)

    def _apply_hard_analysis(self, analysis: StableHardAnalysis) -> None:
        self._recommended_label.setText(f"当前建议：{analysis.current_advice}")
        self._strategy_label.setText(f"当前状态：{analysis.current_status}；财神：{analysis.caishen_text}")
        self._summary_edit.setPlainText(analysis.advice_reason)
        self._hard_calc_edit.setPlainText(self._format_strategy_analysis(analysis))

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
