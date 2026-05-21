from __future__ import annotations

import unittest

from PyQt6.QtWidgets import QApplication, QDialog, QPushButton

from ui.simulated_discard_dialog import SimulatedDiscardDialog


_APP = QApplication.instance() or QApplication([])


class SimulatedDiscardDialogTest(unittest.TestCase):
    def test_selecting_tile_does_not_accept_until_confirmed(self):
        dialog = SimulatedDiscardDialog(["1m", "2m", "3m"], "2m")
        buttons = [
            btn for btn in dialog.findChildren(QPushButton)
            if btn.property("tile_id")
        ]

        self.assertEqual(dialog.result(), 0)
        self.assertEqual(dialog.selected_tile(), "")
        buttons[0].click()

        self.assertEqual(dialog.result(), 0)
        self.assertEqual(dialog.selected_tile(), "1m")
        ok_buttons = [
            btn for btn in dialog.findChildren(QPushButton)
            if btn.text() == "出牌"
        ]
        self.assertEqual(len(ok_buttons), 1)
        self.assertTrue(ok_buttons[0].isEnabled())

        ok_buttons[0].click()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)


if __name__ == "__main__":
    unittest.main()
