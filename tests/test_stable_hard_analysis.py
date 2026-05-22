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
        self.assertTrue(any(wait["tile"] == "8m" for wait in result.ting_tiles))


    def test_enemy_turn_does_not_emit_discard_candidates(self):
        result = analyze_snapshot(_snapshot(["1m"] * 14, current_turn="enemy"))

        self.assertEqual(result.recommended_discard, "")
        self.assertEqual(result.candidates, [])
        self.assertIn("等待", result.model_status)

    def test_optional_hu_preempts_discard_recommendation(self):
        result = analyze_snapshot(
            _snapshot(
                ["1m", "1m", "2m", "3m", "4m", "3m", "4m", "5m", "4m", "5m", "6m", "6m", "7m"],
                current_turn="none",
                optional_actions=["hu", "pass"],
                action_tile="7m",
            )
        )

        self.assertEqual(result.current_advice, "建议胡")
        self.assertEqual(result.recommended_discard, "")
        self.assertEqual(result.candidates, [])
        self.assertEqual(result.model_status, "response_action")

    def test_infers_peng_response_from_last_opponent_discard(self):
        result = analyze_snapshot(
            _snapshot(
                ["5m", "5m", "1p", "2p", "3p", "4s", "5s", "6s", "1z", "1z", "2z", "3z", "4z"],
                current_turn="none",
                players={
                    0: {
                        "hand": ["5m", "5m", "1p", "2p", "3p", "4s", "5s", "6s", "1z", "1z", "2z", "3z", "4z"],
                        "hand_count": 13,
                        "discards": [],
                        "melds": [],
                    },
                    1: {
                        "hand": [],
                        "hand_count": 0,
                        "discards": ["5m"],
                        "melds": [],
                    },
                },
            )
        )

        self.assertTrue(result.current_advice.startswith("建议碰") or result.current_advice == "建议过")
        self.assertEqual(result.recommended_discard, "")
        self.assertEqual(result.candidates, [])
        self.assertEqual(result.model_status, "response_action")

    def test_hupai_phase_clears_discard_recommendation(self):
        result = analyze_snapshot(
            _snapshot(
                ["1m", "1m", "2m", "3m", "4m", "3m", "4m", "5m", "4m", "5m", "6m", "6m", "7m", "9p"],
                phase="hupai",
            )
        )

        self.assertEqual(result.current_advice, "胡牌结算")
        self.assertEqual(result.recommended_discard, "")
        self.assertEqual(result.candidates, [])
        self.assertEqual(result.model_status, "finished")

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

    def test_fourteen_tile_zero_shanten_without_waits_is_not_displayed_as_ting(self):
        result = analyze_snapshot(
            _snapshot(
                ["2p", "3p", "5p", "7p", "1s", "2s", "4s", "5s", "6s", "7s", "7s", "5p", "6p", "7p"],
                baida_tile="3z",
                players={
                    0: {
                        "hand": ["2p", "3p", "5p", "7p", "1s", "2s", "4s", "5s", "6s", "7s", "7s", "5p", "6p", "7p"],
                        "hand_count": 14,
                        "discards": [],
                        "melds": [],
                    },
                    1: {
                        "hand": [],
                        "hand_count": 13,
                        "discards": ["9m", "5z", "8p", "1p", "9s", "7p", "9s", "1z"],
                        "melds": [],
                    },
                },
            )
        )

        self.assertEqual(result.current_shanten, 0)
        self.assertFalse(result.is_ting)
        self.assertEqual(result.ting_tiles, [])
        self.assertEqual(result.recommended_discard, "1s")
        self.assertNotIn("退听", "；".join(result.strong_reminders + [result.advice_reason]))
        self.assertEqual(result.candidates[0].discard, "1s")
        self.assertGreater(result.candidates[0].model_features["shape_value"], result.candidates[1].model_features["shape_value"])

    def test_edge_tile_cleanup_prefers_one_pin_over_four_pin(self):
        result = analyze_snapshot(
            _snapshot(
                ["2m", "8m", "8m", "3s", "3s", "4s", "1p", "3p", "4p", "6p", "6p"],
                baida_tile="2m",
                players={
                    0: {
                        "hand": ["2m", "8m", "8m", "3s", "3s", "4s", "1p", "3p", "4p", "6p", "6p"],
                        "hand_count": 11,
                        "discards": [],
                        "melds": [{"type": "pon", "tiles": ["5z", "5z", "5z"]}],
                    },
                    1: {
                        "hand": [],
                        "hand_count": 13,
                        "discards": ["4z", "9s", "9s", "8s", "5s", "1z", "4s", "4m"],
                        "melds": [],
                    },
                },
            )
        )

        self.assertEqual(result.current_shanten, 1)
        self.assertEqual(result.recommended_discard, "1p")
        candidate_order = [candidate.discard for candidate in result.candidates]
        self.assertLess(candidate_order.index("1p"), candidate_order.index("4p"))

    def test_response_chi_advice_names_specific_meld(self):
        hand = ["3p", "4p", "5p", "6p", "7p", "1s", "2s", "3s", "7s", "7s", "1z", "1z", "4z"]
        result = analyze_snapshot(
            _snapshot(
                hand,
                baida_tile="2m",
                current_turn="self",
                optional_actions=["chi", "chi", "chi", "pass"],
                action_tile="5p",
                action_source="opponent_discard",
                optional_action_details=[
                    {"type": "chi", "tile": "5p", "tiles": ["3p", "4p", "5p"], "label": "吃 3筒 4筒 5筒"},
                    {"type": "chi", "tile": "5p", "tiles": ["4p", "5p", "6p"], "label": "吃 4筒 5筒 6筒"},
                    {"type": "chi", "tile": "5p", "tiles": ["5p", "6p", "7p"], "label": "吃 5筒 6筒 7筒"},
                    {"type": "pass", "tile": "5p", "label": "过"},
                ],
                players={
                    0: {
                        "hand": hand,
                        "hand_count": 13,
                        "discards": [],
                        "melds": [],
                    },
                    1: {
                        "hand": [],
                        "hand_count": 13,
                        "discards": ["5p"],
                        "melds": [],
                    },
                },
            )
        )

        combined = result.current_advice + "；" + result.advice_reason
        self.assertIn("建议吃", result.current_advice)
        self.assertIn("筒", combined)
        self.assertIn("过为备选", result.advice_reason)
        self.assertNotIn("chi / chi / chi / pass", combined)


if __name__ == "__main__":
    unittest.main()
