from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class SimulatedActionDialog(QDialog):
    def __init__(self, actions: list[dict[str, Any]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("模拟动作")
        self._selected: dict[str, Any] = {"type": "pass", "label": "过"}

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("请选择动作"))
        row = QHBoxLayout()
        for action in actions:
            label = str(action.get("label") or action.get("type") or "")
            btn = QPushButton(label)
            btn.setMinimumSize(80, 40)
            btn.clicked.connect(lambda checked=False, value=dict(action): self._choose(value))
            row.addWidget(btn)
        layout.addLayout(row)

    def selected_action(self) -> dict[str, Any]:
        return dict(self._selected)

    def _choose(self, action: dict[str, Any]) -> None:
        self._selected = dict(action)
        self.accept()
