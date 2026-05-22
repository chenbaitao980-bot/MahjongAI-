from __future__ import annotations

import unittest
from unittest.mock import patch

from battle.state import BattleState, tile_from_id
from game.llm_advisor import get_final_advice


class EmptyClient:
    def __init__(self, *args, **kwargs):
        pass

    def chat(self, *args, **kwargs) -> str:
        return ""

    def chat_stream(self, *args, **kwargs) -> str:
        return ""


class AiFallbackTests(unittest.TestCase):
    def test_empty_llm_response_falls_back_to_program_advice(self):
        analysis = {
            "candidates": [
                {"discard": "9p", "shanten_after": 0, "ukeire_count": 8},
            ],
            "strategy_mode": "attack",
            "game_features": {},
        }
        payload = {"rules": {"baida_tile": "7z"}, "is_conservative": False}

        with patch("game.llm_advisor.LLMClient", EmptyClient):
            advice = get_final_advice(
                payload=payload,
                analysis=analysis,
                api_key="sk-test",
                model="deepseek-chat",
                use_llm=True,
            )

        self.assertEqual(advice["tile"], "9p")
        self.assertEqual(advice["source"], "program")
        self.assertIn("LLM 返回空内容", advice["reason"])
        self.assertEqual(advice["raw_response"], "[empty-response-fallback]")

    def test_battle_state_filters_ting_drawn_tile_candidates(self):
        state = BattleState(ai_recognition_enabled=False)
        state.baida_tile = "7z"
        state.remaining_tiles = 80
        state.current_turn = "self"
        state.drawn_tile = "1m"
        state.self_hand = [
            tile_from_id(tile)
            for tile in [
                "1m", "1m", "2m", "3m", "4m", "3m", "4m",
                "5m", "4m", "5m", "6m", "6m", "7m", "9p",
            ]
        ]

        analysis = state.to_payload()["self"]["analysis"]

        self.assertEqual(analysis["shanten"], 0)
        self.assertEqual(analysis["top_recommendation"], "1m")
        self.assertEqual([candidate["discard"] for candidate in analysis["candidates"]], ["1m"])


if __name__ == "__main__":
    unittest.main()
