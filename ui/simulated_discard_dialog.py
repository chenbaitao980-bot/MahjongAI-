from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.battle_panel import TILE_NAME_MAP


class SimulatedDiscardDialog(QDialog):
    def __init__(self, hand: list[str], recommended: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("模拟出牌")
        self.setMinimumWidth(720)
        self._selected_tile = ""
        self._buttons: list[QPushButton] = []
        self._recommended = recommended

        layout = QVBoxLayout(self)
        tip = "轮到我方出牌"
        if recommended:
            tip += f"；推荐：{TILE_NAME_MAP.get(recommended, recommended)}"
        layout.addWidget(QLabel(tip))

        hand_board = QWidget()
        grid = QGridLayout(hand_board)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        for idx, tile in enumerate(hand):
            btn = QPushButton(TILE_NAME_MAP.get(tile, tile))
            btn.setMinimumSize(58, 42)
            btn.setProperty("tile_id", tile)
            btn.clicked.connect(lambda checked=False, value=tile: self._choose(value))
            self._buttons.append(btn)
            row, col = divmod(idx, 7)
            grid.addWidget(btn, row, col)
        layout.addWidget(hand_board)
        self._refresh_button_styles()

        footer = QHBoxLayout()
        footer.addStretch()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._discard_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._discard_button.setText("出牌")
        self._discard_button.setEnabled(False)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("暂停")
        buttons.accepted.connect(self._confirm_discard)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        layout.addLayout(footer)

    def selected_tile(self) -> str:
        return self._selected_tile

    def _choose(self, tile_id: str) -> None:
        self._selected_tile = tile_id
        self._discard_button.setEnabled(True)
        self._refresh_button_styles()

    def _confirm_discard(self) -> None:
        if self._selected_tile:
            self.accept()

    def _refresh_button_styles(self) -> None:
        for btn in self._buttons:
            tile = str(btn.property("tile_id") or "")
            if tile == self._selected_tile:
                btn.setStyleSheet(
                    "QPushButton { border: 2px solid #388bfd; color: #ffffff; font-weight: 700; }"
                )
                btn.setToolTip("已选择")
            elif tile == self._recommended:
                btn.setStyleSheet(
                    "QPushButton { border: 2px solid #3fb950; color: #ffffff; font-weight: 700; }"
                )
                btn.setToolTip("当前推荐")
            else:
                btn.setStyleSheet("")
                btn.setToolTip("")
