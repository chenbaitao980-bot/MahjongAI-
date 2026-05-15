from __future__ import annotations
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSpinBox, QGroupBox, QTextEdit, QCheckBox,
)

from game.state import GameState, PHASE_PLAYING, PHASE_SHENGJIA, PHASE_HUANGPAI, PHASE_LIUJU, PHASE_HUPAI
from game.state import ALL_TILE_IDS

TILE_DISPLAY = {
    **{f"{i}m": f"{i}万" for i in range(1, 10)},
    **{f"{i}p": f"{i}筒" for i in range(1, 10)},
    **{f"{i}s": f"{i}条" for i in range(1, 10)},
    "1z": "东", "2z": "南", "3z": "西", "4z": "北",
    "5z": "中", "6z": "发", "7z": "白",
}

PHASE_TEXT = {
    PHASE_PLAYING: "游戏进行中",
    PHASE_SHENGJIA: "⚠ 生牌阶段",
    PHASE_HUANGPAI: "🔴 黄牌边缘",
    PHASE_LIUJU: "流局",
    PHASE_HUPAI: "胡牌！",
}

PHASE_COLOR = {
    PHASE_PLAYING:  "#3fb950",
    PHASE_SHENGJIA: "#d29922",
    PHASE_HUANGPAI: "#f85149",
    PHASE_LIUJU:    "#8b949e",
    PHASE_HUPAI:    "#f85149",
}


class CapturePanel(QWidget):
    """识别控制面板：启停 + 实时识别结果展示。"""

    start_requested = pyqtSignal(int)    # interval_ms
    stop_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._frame_count = 0
        self._seen_event_keys: set[tuple[int, str]] = set()
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)

        # ---- 控制行 ----
        ctrl = QGroupBox("识别控制")
        ctrl_layout = QHBoxLayout(ctrl)

        self._btn_start = QPushButton("▶ 开始识别")
        self._btn_start.setFixedHeight(32)
        self._btn_start.clicked.connect(self._toggle)
        ctrl_layout.addWidget(self._btn_start)

        self._hide_on_start = QCheckBox("开始后隐藏窗口")
        self._hide_on_start.setChecked(True)
        self._hide_on_start.setToolTip("勾选后，点击开始识别会自动最小化 AI 窗口，避免遮挡游戏画面")
        ctrl_layout.addWidget(self._hide_on_start)

        ctrl_layout.addWidget(QLabel("截图间隔(ms)："))
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(100, 10000)
        self._interval_spin.setValue(500)
        self._interval_spin.setSingleStep(100)
        ctrl_layout.addWidget(self._interval_spin)

        self._frame_label = QLabel("帧数：0")
        ctrl_layout.addWidget(self._frame_label)

        self._phase_label = QLabel("---")
        self._phase_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        ctrl_layout.addWidget(self._phase_label)

        ctrl_layout.addStretch()
        root.addWidget(ctrl)

        # ---- 二人对局状态展示 ----
        state_row = QHBoxLayout()

        self_box = QGroupBox("自家区域")
        self_layout = QVBoxLayout(self_box)
        self._self_hand_label = QLabel("手牌区：--")
        self._self_hand_label.setWordWrap(True)
        self._self_hand_label.setFont(QFont("Microsoft YaHei", 11))
        self_layout.addWidget(self._self_hand_label)
        self._self_meld_label = QLabel("副露区：--")
        self._self_meld_label.setWordWrap(True)
        self_layout.addWidget(self._self_meld_label)
        self._self_discard_label = QLabel("弃牌区：--")
        self._self_discard_label.setWordWrap(True)
        self_layout.addWidget(self._self_discard_label)
        state_row.addWidget(self_box, stretch=3)

        opp_box = QGroupBox("对手区域（二人模式）")
        opp_layout = QVBoxLayout(opp_box)
        self._opp_status_label = QLabel("对手：--")
        self._opp_status_label.setWordWrap(True)
        self._opp_status_label.setFont(QFont("Microsoft YaHei", 11))
        opp_layout.addWidget(self._opp_status_label)
        self._opp_meld_label = QLabel("副露区：--")
        self._opp_meld_label.setWordWrap(True)
        opp_layout.addWidget(self._opp_meld_label)
        self._opp_discard_label = QLabel("弃牌区：--")
        self._opp_discard_label.setWordWrap(True)
        opp_layout.addWidget(self._opp_discard_label)
        state_row.addWidget(opp_box, stretch=3)

        # 事件日志
        log_box = QGroupBox("事件日志")
        log_layout = QVBoxLayout(log_box)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Microsoft YaHei", 10))
        self._log.setMinimumWidth(360)
        log_layout.addWidget(self._log)
        state_row.addWidget(log_box, stretch=2)

        root.addLayout(state_row)

        # ---- 牌局状态 ----
        conf_box = QGroupBox("牌局状态")
        conf_layout = QHBoxLayout(conf_box)
        self._rt_label = QLabel("剩余：-- 张")
        self._rt_label.setFont(QFont("Arial", 11))
        conf_layout.addWidget(self._rt_label)
        self._decision_label = QLabel("可操作：--")
        self._decision_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        conf_layout.addWidget(self._decision_label)
        self._conf_label = QLabel("最低置信度：---")
        conf_layout.addWidget(self._conf_label)
        conf_layout.addStretch()
        root.addWidget(conf_box)

    # ------------------------------------------------------------------ #

    def _toggle(self):
        if not self._running:
            self._running = True
            self._frame_count = 0
            self._seen_event_keys.clear()
            self._log.clear()
            self._btn_start.setText("■ 停止识别")
            self._btn_start.setStyleSheet(
                "background: #f85149; color: #0d1117; border-color: #f85149; font-weight: bold;"
            )
            self.start_requested.emit(self._interval_spin.value())
        else:
            self._running = False
            self._btn_start.setText("▶ 开始识别")
            self._btn_start.setStyleSheet("")
            self.stop_requested.emit()

    def on_frame(self, state: GameState) -> None:
        """Pipeline 每帧回调，更新 UI。"""
        self._frame_count += 1
        self._frame_label.setText(f"帧数：{self._frame_count}")

        # 游戏阶段
        phase_text = PHASE_TEXT.get(state.game_phase, state.game_phase)
        color = PHASE_COLOR.get(state.game_phase, "#333")
        self._phase_label.setText(phase_text)
        self._phase_label.setStyleSheet(f"color: {color};")

        # 二人模式区域
        opponent = self._select_two_player_opponent(state)
        self._self_hand_label.setText(
            f"手牌区：{len(state.self_player.hand)}牌\n"
            f"{self._format_tiles(state.self_player.hand)}"
        )
        self._self_meld_label.setText(
            f"副露区：{len(state.self_player.melds)}组\n"
            f"{self._format_melds(state.self_player.melds)}"
        )
        self._self_discard_label.setText(
            f"弃牌区：{len(state.self_player.discards)}牌\n"
            f"{self._format_tiles(state.self_player.discards, with_conf=False)}"
        )

        opp_name = self._seat_name(opponent.seat)
        self._opp_status_label.setText(f"{opp_name}：手牌数 {opponent.tile_count}（推算）")
        self._opp_meld_label.setText(
            f"副露区：{len(opponent.melds)}组\n"
            f"{self._format_melds(opponent.melds)}"
        )
        self._opp_discard_label.setText(
            f"弃牌区：{len(opponent.discards)}牌\n"
            f"{self._format_tiles(opponent.discards, with_conf=False)}"
        )

        # 剩余牌数
        rt = state.remaining_tiles
        self._rt_label.setText(f"剩余：{rt if rt is not None else '--'} 张")

        # 决策按钮
        if state.decision_prompt:
            self._decision_label.setText("可操作：" + " / ".join(state.decision_prompt))
            self._decision_label.setStyleSheet("color: #c00; font-weight: bold;")
        else:
            self._decision_label.setText("可操作：--")
            self._decision_label.setStyleSheet("")

        # 事件日志
        if state.events:
            for ev in state.events:
                key = (state.frame_index, ev)
                if key in self._seen_event_keys:
                    continue
                self._seen_event_keys.add(key)
                self._log.append(self._format_event(state.frame_index, ev))

        # 置信度
        min_c = state.raw_confidence_min
        color_c = "#2d8a2d" if min_c >= 0.80 else "#b05a00" if min_c >= 0.60 else "#c00"
        self._conf_label.setText(f"最低置信度：{min_c:.3f}")
        self._conf_label.setStyleSheet(f"color: {color_c};")

    def force_stop(self):
        """外部调用：强制停止（关闭窗口时）。"""
        if self._running:
            self._toggle()

    def hide_on_start(self) -> bool:
        return self._hide_on_start.isChecked()

    # ------------------------------------------------------------------ #
    #  展示格式化                                                          #
    # ------------------------------------------------------------------ #

    def _format_tiles(self, tiles, with_conf: bool = True) -> str:
        if not tiles:
            return "（空）"
        parts = []
        for tile in tiles:
            name = TILE_DISPLAY.get(tile.tile_id, tile.tile_id) if tile.tile_id else "未识别"
            if with_conf:
                parts.append(f"{name}({tile.confidence:.2f})")
            else:
                parts.append(name)
        return "  ".join(parts)

    def _format_melds(self, melds) -> str:
        if not melds:
            return "（无）"
        parts = []
        for meld in melds:
            mtype = {
                "chi": "吃",
                "pon": "碰",
                "kan_open": "明杠",
                "kan_closed": "暗杠",
                "kan_added": "补杠",
            }.get(meld.meld_type, meld.meld_type)
            parts.append(f"{mtype}：{self._format_tiles(meld.tiles, with_conf=False)}")
        return "\n".join(parts)

    def _select_two_player_opponent(self, state: GameState):
        if not state.opponents:
            raise RuntimeError("GameState 缺少 opponents")
        return max(
            state.opponents,
            key=lambda opp: (len(opp.discards), len(opp.melds), 1 if opp.seat == "across" else 0),
        )

    def _seat_name(self, seat: str) -> str:
        return {
            "self": "自家",
            "right": "对手(右家)",
            "across": "对手",
            "left": "对手(左家)",
        }.get(seat, seat)

    def _tile_name(self, tile_id: str | None) -> str:
        if not tile_id or tile_id == "unknown":
            return "未知牌"
        return TILE_DISPLAY.get(tile_id, tile_id)

    def _format_event(self, frame_index: int, event: str) -> str:
        prefix = f"第{frame_index}帧 "
        if event == "game_start":
            return prefix + "牌局开始"
        if event == "draw":
            return prefix + "自家摸牌"
        if event == "discard":
            return prefix + "自家出牌（手牌数变化）"
        if event.startswith("self_discard:"):
            return prefix + f"自家打出{self._tile_name(event.split(':', 1)[1])}"
        if event.startswith("right_discard:") or event.startswith("across_discard:") or event.startswith("left_discard:"):
            seat, tile_id = event.split(":", 1)
            return prefix + f"{self._seat_name(seat.replace('_discard', ''))}打出{self._tile_name(tile_id)}"
        if event.startswith("decision_prompt:"):
            buttons = event.split(":", 1)[1].replace(",", " / ")
            return prefix + f"出现可操作按钮：{buttons}"
        if event == "decision_prompt_cleared":
            return prefix + "可操作按钮消失"
        if event.startswith("decision_prompt_changed:"):
            buttons = event.split(":", 1)[1].replace(",", " / ")
            return prefix + f"可操作按钮变化：{buttons}"
        if event.startswith("remaining_changed:"):
            change = event.split(":", 1)[1]
            return prefix + f"剩余牌数变化：{change}"
        if event == "shengjia_start":
            return prefix + "进入生牌阶段"
        if event == "round_end_draw":
            return prefix + "流局"
        if event == "round_end_win":
            return prefix + "胡牌结算"
        if event in {"chi", "pon", "kan_open", "kan_closed", "kan_added"}:
            return prefix + {
                "chi": "自家吃牌",
                "pon": "自家碰牌",
                "kan_open": "自家明杠",
                "kan_closed": "自家暗杠",
                "kan_added": "自家补杠",
            }[event]
        if event.startswith("opp_"):
            parts = event.split("_")
            if len(parts) >= 3:
                seat = self._seat_name(parts[1])
                action = {
                    "chi": "吃牌",
                    "pon": "碰牌",
                    "kan": "杠牌",
                    "kan_open": "明杠",
                    "kan_closed": "暗杠",
                    "kan_added": "补杠",
                }.get("_".join(parts[2:]), parts[-1])
                return prefix + f"{seat}{action}"
        return prefix + event
