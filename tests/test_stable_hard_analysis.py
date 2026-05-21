from __future__ import annotations

import unittest

from game.stable_hard_analysis import analyze_snapshot


def _snapshot(hand: list[str], **overrides):
    data = {
        "phase": "playing",
        "local_player": 0,
        "opponent_player": 1,
        "current_turn": "self",
        "remaining_tiles": 80,
        "baida_tile": "7z",
        "baida_trusted": True,
        "hand_trusted": True,
        "turn_trusted": True,
        "optional_actions": [],
        "unknowns": [],
        "players": {
            0: {
                "hand": hand,
                "hand_count": len(hand),
                "discards": [],
                "melds": [],
            },
            1: {
                "hand": [],
                "hand_count": 0,
                "discards": [],
                "melds": [],
            },
        },
    }
    data.update(overrides)
    return data


class StableHardAnalysisTest(unittest.TestCase):
    def test_incomplete_data_does_not_recommend_discard(self):
        result = analyze_snapshot(
            _snapshot(
                [],
                hand_trusted=False,
                baida_tile="",
                baida_trusted=False,
                current_turn="none",
                turn_trusted=False,
            )
        )

        self.assertEqual(result.current_status, "等待手牌")
        self.assertEqual(result.caishen_text, "等待财神")
        self.assertEqual(result.current_advice, "等待完整数据")
        self.assertIn("数据不足", "；".join(result.strong_reminders))

    def test_incomplete_data_has_no_candidates(self):
        result = analyze_snapshot(
            _snapshot(
                [],
                hand_trusted=False,
                baida_tile="",
                baida_trusted=False,
                current_turn="none",
                turn_trusted=False,
            )
        )

        self.assertEqual(result.candidates, [])
        self.assertIn("等待", result.model_status)

    def test_calculates_same_snapshot_hand_for_recommendation(self):
        result = analyze_snapshot(
            _snapshot(
                [
                    "1m", "1m", "2m", "3m", "4m", "3m", "4m",
                    "5m", "4m", "5m", "6m", "6m", "7m", "9p",
                ]
            )
        )

        self.assertEqual(result.current_status, "等待出牌")
        self.assertEqual(result.caishen_text, "白")
        self.assertEqual(result.current_shanten, 0)
        self.assertTrue(result.is_ting)
        self.assertEqual(result.recommended_discard, "9p")
        self.assertGreater(result.effective_count, 0)
        self.assertTrue(any(wait["tile"] == "7m" for wait in result.ting_tiles))


    def test_enemy_turn_does_not_emit_discard_candidates(self):
        result = analyze_snapshot(_snapshot(["1m"] * 14, current_turn="enemy"))

        self.assertEqual(result.recommended_discard, "")
        self.assertEqual(result.candidates, [])
        self.assertIn("等待", result.model_status)

    def test_opponent_predictions_are_visible_estimates(self):
        result = analyze_snapshot(
            _snapshot(
                ["1m", "1m", "2m", "3m", "4m", "3m", "4m", "5m", "4m", "5m", "6m", "6m", "7m", "9p"],
                remaining_tiles=32,
                current_turn="enemy",
                players={
                    0: {
                        "hand": ["1m", "1m", "2m", "3m", "4m", "3m", "4m", "5m", "4m", "5m", "6m", "6m", "7m", "9p"],
                        "hand_count": 14,
                        "discards": ["9s", "1p"],
                        "melds": [],
                    },
                    1: {
                        "hand": [],
                        "hand_count": 7,
                        "discards": ["1m", "9m", "2p", "8p"],
                        "melds": [
                            {"type": "pon", "tiles": ["3s", "3s", "3s"]},
                            {"type": "chi", "tiles": ["4s", "5s", "6s"]},
                        ],
                    },
                },
            )
        )

        self.assertEqual(result.candidates, [])
        self.assertIn("估计", result.opponent_hand_prediction)
        self.assertIn("可能", result.opponent_hand_prediction)
        self.assertIn("估计进度", result.opponent_progress_prediction)
        self.assertIn("副露", result.opponent_progress_prediction)


if __name__ == "__main__":
    unittest.main()
