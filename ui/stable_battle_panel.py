from __future__ import annotations

import html
from copy import deepcopy

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from battle.state import BattleAdvice
from game.state import ALL_TILE_IDS
from ui.battle_panel import AnalysisPanel, TILE_NAME_MAP


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


class StableBattlePanel(QWidget):
    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    config_requested = pyqtSignal()
    mapping_save_requested = pyqtSignal(str, str)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = deepcopy(config)
        self._snapshot: dict = {}
        self._notified_unknowns: set[str] = set()
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

        top.addStretch()
        root.addLayout(top)

        status_box = QGroupBox("稳定版状态")
        status_form = QFormLayout(status_box)
        self._capture_status = QLabel("idle")
        self._data_status = QLabel("--")
        self._turn_status = QLabel("--")
        self._baida_status = QLabel("--")
        status_form.addRow("抓包", self._capture_status)
        status_form.addRow("数据", self._data_status)
        status_form.addRow("回合", self._turn_status)
        status_form.addRow("财神", self._baida_status)
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
        body.addLayout(left, 3)

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
        self._summary_edit.setMinimumHeight(110)
        advice_layout.addWidget(self._summary_edit)
        self._analysis_panel = AnalysisPanel()
        advice_layout.addWidget(self._analysis_panel)
        right.addWidget(advice_box, 2)

        mapping_box = QGroupBox("未知映射修正")
        mapping_layout = QVBoxLayout(mapping_box)
        self._mapping_table = QTableWidget(0, 3)
        self._mapping_table.setHorizontalHeaderLabels(["原始牌值", "次数", "来源"])
        self._mapping_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._mapping_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        mapping_layout.addWidget(self._mapping_table)
        map_row = QHBoxLayout()
        self._mapping_tile_combo = QComboBox()
        for tile_id in ALL_TILE_IDS:
            self._mapping_tile_combo.addItem(f"{TILE_NAME_MAP.get(tile_id, tile_id)} ({tile_id})", tile_id)
        map_row.addWidget(self._mapping_tile_combo, 1)
        self._mapping_save_btn = QPushButton("保存映射")
        self._mapping_save_btn.clicked.connect(self._save_selected_mapping)
        map_row.addWidget(self._mapping_save_btn)
        mapping_layout.addLayout(map_row)
        right.addWidget(mapping_box, 1)
        body.addLayout(right, 2)

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

    def _default_model(self) -> str:
        provider = str(self._ai_provider_combo.currentData() or "deepseek")
        fallback = {"deepseek": "deepseek-chat", "qianwen": "qwen-turbo-latest"}
        return self._config.get(provider, {}).get("model", fallback.get(provider, "")) or fallback.get(provider, "")

    def _sync_model_placeholder(self) -> None:
        self._ai_model_edit.setPlaceholderText(self._default_model())
        if not self._ai_model_edit.text().strip():
            self._ai_model_edit.setText(self._default_model())

    def set_running(self, running: bool) -> None:
        self._start_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        self._capture_status.setText("读取中" if running else "未开始")

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
        self._data_status.setText(f"{_phase_text(phase)}｜剩余 {remaining} 张｜{ready_text}")
        self._turn_status.setText(f"我方座位 {local}｜对面座位 {opponent}｜{_turn_text(turn)}")
        baida = snapshot.get("baida_tile") or ""
        baida_trusted = bool(snapshot.get("baida_trusted"))
        self._baida_status.setText(TILE_NAME_MAP.get(baida, baida) if baida and baida_trusted else "等待抓包解析财神")

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
        self._data_view.setPlainText("\n\n".join(lines))
        self._event_view.setPlainText("\n".join(snapshot.get("events", [])[-120:]))
        unknowns = snapshot.get("unknowns", [])
        self._set_unknowns(unknowns)
        self._notify_unknowns(unknowns)

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
        self._mapping_table.setRowCount(len(unknowns))
        for row, item in enumerate(unknowns):
            values = [
                item.get("display_key", item.get("raw_key", "")),
                str(item.get("count", "")),
                item.get("note", ""),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, item.get("raw_key", ""))
                self._mapping_table.setItem(row, col, cell)
        self._mapping_table.resizeColumnsToContents()

    def _notify_unknowns(self, unknowns: list[dict]) -> None:
        fresh = [u for u in unknowns if u.get("raw_key") and u.get("raw_key") not in self._notified_unknowns]
        if not fresh:
            return
        first = fresh[0]
        for item in fresh:
            self._notified_unknowns.add(str(item.get("raw_key")))
        QMessageBox.information(
            self,
            "发现未识别牌值",
            f"抓包中出现未识别牌值：{first.get('display_key', first.get('raw_key', ''))}\n\n"
            "请在「未知映射修正」里选择对应牌面，然后点击「保存映射」。",
        )

    def _save_selected_mapping(self) -> None:
        row = self._mapping_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选中一条未识别牌值。")
            return
        item = self._mapping_table.item(row, 0)
        if item is None:
            QMessageBox.information(self, "提示", "当前选中行没有可保存的牌值。")
            return
        raw_key = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        tile_id = str(self._mapping_tile_combo.currentData() or "")
        if raw_key and tile_id:
            self.mapping_save_requested.emit(raw_key, tile_id)
        else:
            QMessageBox.information(self, "提示", "请选择有效牌面后再保存映射。")

    def set_busy(self, busy: bool, message: str = "") -> None:
        self._data_status.setText(message or ("正在分析" if busy else "就绪"))

    def clear_stream_buffer(self) -> None:
        self._summary_edit.clear()
        self._recommended_label.setText("当前推荐出牌：AI 生成中...")

    def append_stream_chunk(self, chunk: str) -> None:
        self._summary_edit.setPlainText(self._summary_edit.toPlainText() + chunk)

    def set_advice(self, state, advice: BattleAdvice) -> None:
        discard_id = advice.recommended_discard or ""
        discard = TILE_NAME_MAP.get(discard_id, discard_id) if discard_id else "--"
        self._recommended_label.setText(f"当前推荐出牌：{discard}")
        self._strategy_label.setText(f"策略类型：{advice.strategy_type or '--'}")
        parts = []
        if advice.reasoning_summary:
            parts.append(f"<p>{html.escape(advice.reasoning_summary)}</p>")
        if advice.risk_notes:
            parts.append(f"<p style='color:#d29922'>{html.escape(advice.risk_notes)}</p>")
        if advice.forbidden_discards:
            parts.append(f"<p style='color:#f85149'>禁止出牌：{html.escape(' '.join(advice.forbidden_discards))}</p>")
        self._summary_edit.setHtml("".join(parts))
        self._analysis_panel.refresh(state.last_analysis, advice.recommended_discard)

    def set_error(self, message: str) -> None:
        self._summary_edit.setPlainText(message)
