from __future__ import annotations

import unittest

from stable.simulator import StableSimulationGame


class StableSimulationGameTest(unittest.TestCase):
    def test_start_round_emits_analysis_ready_snapshot(self):
        sim = StableSimulationGame(seed=1)
        snap = sim.snapshot()

        self.assertEqual(snap["phase"], "playing")
        self.assertEqual(snap["current_turn"], "self")
        self.assertTrue(snap["hand_trusted"])
        self.assertTrue(snap["baida_trusted"])
        self.assertTrue(snap["turn_trusted"])
        self.assertTrue(snap["analysis_ready"])
        self.assertEqual(len(snap["players"][0]["hand"]), 14)
        self.assertEqual(snap["players"][1]["hand"], [])
        self.assertEqual(snap["players"][1]["hand_count"], 13)

    def test_discard_and_opponent_advance_returns_to_self_turn(self):
        sim = StableSimulationGame(seed=2)
        first = sim.snapshot()
        discard = first["players"][0]["hand"][0]

        sim.discard_self(discard)
        after_discard = sim.snapshot()
        self.assertEqual(after_discard["current_turn"], "enemy")
        self.assertIn(discard, after_discard["players"][0]["discards"])
        self.assertFalse(after_discard["analysis_ready"])

        sim.advance_opponent()
        after_enemy = sim.snapshot()
        self.assertEqual(after_enemy["current_turn"], "self")
        self.assertGreaterEqual(len(after_enemy["players"][1]["discards"]), 1)
        self.assertEqual(after_enemy["players"][1]["hand"], [])

        if sim.pending_response:
            sim.apply_response_action({"type": "pass"})
        after_pass = sim.snapshot()
        self.assertEqual(after_pass["current_turn"], "self")
        self.assertTrue(after_pass["analysis_ready"])
        self.assertEqual(len(after_pass["players"][0]["hand"]), 14)

    def test_to_battle_state_matches_snapshot(self):
        sim = StableSimulationGame(seed=3)
        state = sim.to_battle_state()

        self.assertEqual(state.recognition_source, "simulation")
        self.assertEqual(state.current_turn, "self")
        self.assertEqual(state.baida_tile, sim.snapshot()["baida_tile"])
        self.assertEqual(len(state.self_hand), 14)

    def test_response_pon_writes_meld_and_removes_discard(self):
        sim = StableSimulationGame(seed=4)
        sim.players[0].hand = ["1m", "1m", "2m", "3m"]
        sim.players[1].discards = ["1m"]
        sim.pending_response = {
            "responder": 0,
            "discarder": 1,
            "tile": "1m",
            "actions": sim.available_response_actions(0, 1, "1m"),
        }

        sim.apply_response_action({"type": "pon", "tile": "1m"})
        snap = sim.snapshot()

        self.assertEqual(snap["players"][0]["melds"], [{"type": "pon", "tiles": ["1m", "1m", "1m"]}])
        self.assertEqual(snap["players"][1]["discards"], [])
        self.assertEqual(sim.current_turn, "self")

    def test_response_chi_writes_meld_and_removes_discard(self):
        sim = StableSimulationGame(seed=5)
        sim.players[0].hand = ["2m", "3m", "7p"]
        sim.players[1].discards = ["1m"]
        sim.pending_response = {
            "responder": 0,
            "discarder": 1,
            "tile": "1m",
            "actions": sim.available_response_actions(0, 1, "1m"),
        }

        sim.apply_response_action({"type": "chi", "tile": "1m", "tiles": ["1m", "2m", "3m"]})
        snap = sim.snapshot()

        self.assertEqual(snap["players"][0]["melds"], [{"type": "chi", "tiles": ["1m", "2m", "3m"]}])
        self.assertNotIn("2m", snap["players"][0]["hand"])
        self.assertNotIn("3m", snap["players"][0]["hand"])
        self.assertEqual(snap["players"][1]["discards"], [])

    def test_closed_kong_draws_replacement_and_writes_meld(self):
        sim = StableSimulationGame(seed=6)
        sim.players[0].hand = ["5p", "5p", "5p", "5p", "1m", "2m", "3m"]
        before_wall = sim.remaining_tiles

        sim.apply_self_action({"type": "kan_closed", "tile": "5p"})
        snap = sim.snapshot()

        self.assertEqual(snap["players"][0]["melds"], [{"type": "kan_closed", "tiles": ["5p", "5p", "5p", "5p"]}])
        self.assertEqual(sim.remaining_tiles, before_wall - 1)
        self.assertEqual(sim.current_turn, "self")

    def test_win_action_finishes_round(self):
        sim = StableSimulationGame(seed=7)
        sim.players[0].hand = [
            "1m", "1m", "1m", "2m", "3m", "4m", "5m",
            "6m", "7m", "2p", "3p", "4p", "5z",
        ]
        sim.players[1].discards = ["5z"]
        actions = sim.available_response_actions(0, 1, "5z")

        self.assertTrue(any(a["type"] == "hu" for a in actions))
        sim.pending_response = {"responder": 0, "discarder": 1, "tile": "5z", "actions": actions}
        sim.apply_response_action({"type": "hu", "tile": "5z"})

        self.assertEqual(sim.phase, "finished")
        self.assertEqual(sim.current_turn, "none")


if __name__ == "__main__":
    unittest.main()
