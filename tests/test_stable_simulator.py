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
        self.assertTrue(after_enemy["analysis_ready"])
        self.assertEqual(len(after_enemy["players"][0]["hand"]), 14)
        self.assertGreaterEqual(len(after_enemy["players"][1]["discards"]), 1)
        self.assertEqual(after_enemy["players"][1]["hand"], [])

    def test_to_battle_state_matches_snapshot(self):
        sim = StableSimulationGame(seed=3)
        state = sim.to_battle_state()

        self.assertEqual(state.recognition_source, "simulation")
        self.assertEqual(state.current_turn, "self")
        self.assertEqual(state.baida_tile, sim.snapshot()["baida_tile"])
        self.assertEqual(len(state.self_hand), 14)


if __name__ == "__main__":
    unittest.main()
