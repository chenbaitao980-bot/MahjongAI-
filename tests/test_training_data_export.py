from __future__ import annotations

import os
import tempfile
import unittest

from stable.mapping import MappingStore
from stable.protocol import ProtocolMessage, SOURCE_TRUSTED_ACTION, SOURCE_TRUSTED_HAND
from stable.training_data import export_training_samples


def _msg(game: dict, ts: str = "2026-01-01T00:00:00.000") -> ProtocolMessage:
    return ProtocolMessage(
        ts=ts,
        direction="S->C",
        msg_type=0x2BC0,
        type_name="game_event",
        sub_type=0,
        extra="",
        size=0,
        pay_len=0,
        game=game,
    )


class TrainingDataExportTest(unittest.TestCase):
    def test_exports_trainable_local_discard_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            messages = [
                _msg(
                    {
                        "event": "baida_update",
                        "baida_raw": 0x53,
                        "baida_context": "stable",
                        "baida_trusted": True,
                        "source": SOURCE_TRUSTED_ACTION,
                    }
                ),
                _msg(
                    {
                        "event": "hand_update",
                        "player": 0,
                        "hand_raw": [
                            0x11,
                            0x11,
                            0x12,
                            0x13,
                            0x14,
                            0x13,
                            0x14,
                            0x15,
                            0x14,
                            0x15,
                            0x16,
                            0x16,
                            0x17,
                            0x39,
                        ],
                        "hand_context": "stable",
                        "source": SOURCE_TRUSTED_HAND,
                    }
                ),
                _msg(
                    {
                        "event": "discard",
                        "player": 0,
                        "tile_raw": 0x39,
                        "tile_context": "stable",
                        "source": SOURCE_TRUSTED_ACTION,
                    }
                ),
            ]

            samples, stats = export_training_samples(
                messages,
                mapping_store=store,
                local_player=0,
                player_count=2,
                source_path="events_test.jsonl",
                train_enabled=True,
            )

            self.assertEqual(stats.messages, 3)
            self.assertEqual(stats.trainable, 1)
            self.assertEqual(stats.blocked, 0)
            self.assertEqual(len(samples), 1)
            sample = samples[0]
            self.assertTrue(sample["is_trainable"])
            self.assertEqual(sample["label"], {"action": "discard", "tile": "9p"})
            self.assertTrue(sample["is_label_eligible"])
            self.assertEqual(sample["actual_action"]["tile"], "9p")
            self.assertEqual(sample["learning"]["session_mode"], "train_enabled")
            self.assertEqual(sample["state"]["current_turn"], "self")
            self.assertEqual(sample["hard_analysis"]["recommended_discard"], "9p")
            self.assertTrue(sample["hard_analysis"]["candidates"])

    def test_record_only_keeps_label_but_does_not_mark_trainable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            messages = [
                _msg(
                    {
                        "event": "baida_update",
                        "baida_raw": 0x53,
                        "baida_context": "stable",
                        "baida_trusted": True,
                        "source": SOURCE_TRUSTED_ACTION,
                    }
                ),
                _msg(
                    {
                        "event": "hand_update",
                        "player": 0,
                        "hand_raw": [
                            0x11,
                            0x11,
                            0x12,
                            0x13,
                            0x14,
                            0x13,
                            0x14,
                            0x15,
                            0x14,
                            0x15,
                            0x16,
                            0x16,
                            0x17,
                            0x39,
                        ],
                        "hand_context": "stable",
                        "source": SOURCE_TRUSTED_HAND,
                    }
                ),
                _msg(
                    {
                        "event": "discard",
                        "player": 0,
                        "tile_raw": 0x39,
                        "tile_context": "stable",
                        "source": SOURCE_TRUSTED_ACTION,
                    }
                ),
            ]

            samples, stats = export_training_samples(
                messages,
                mapping_store=store,
                local_player=0,
                player_count=2,
            )

            self.assertEqual(stats.trainable, 0)
            self.assertEqual(stats.blocked, 1)
            self.assertEqual(len(samples), 1)
            self.assertTrue(samples[0]["is_label_eligible"])
            self.assertFalse(samples[0]["is_trainable"])
            self.assertEqual(samples[0]["label"], {"action": "discard", "tile": "9p"})
            self.assertEqual(samples[0]["blocked_reason"], "training_disabled")
            self.assertEqual(samples[0]["learning"]["session_mode"], "record_only")

    def test_record_disabled_writes_no_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            messages = [
                _msg(
                    {
                        "event": "discard",
                        "player": 0,
                        "tile_raw": 0x39,
                        "tile_context": "stable",
                        "source": SOURCE_TRUSTED_ACTION,
                    }
                )
            ]

            samples, stats = export_training_samples(
                messages,
                mapping_store=store,
                local_player=0,
                player_count=2,
                record_enabled=False,
            )

            self.assertEqual(stats.messages, 1)
            self.assertEqual(stats.samples, 0)
            self.assertEqual(stats.trainable, 0)
            self.assertEqual(stats.blocked, 0)
            self.assertEqual(samples, [])

    def test_blocks_label_when_baida_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            messages = [
                _msg(
                    {
                        "event": "hand_update",
                        "player": 0,
                        "hand_raw": [
                            0x11,
                            0x11,
                            0x12,
                            0x13,
                            0x14,
                            0x13,
                            0x14,
                            0x15,
                            0x14,
                            0x15,
                            0x16,
                            0x16,
                            0x17,
                            0x39,
                        ],
                        "hand_context": "stable",
                        "source": SOURCE_TRUSTED_HAND,
                    }
                ),
                _msg(
                    {
                        "event": "discard",
                        "player": 0,
                        "tile_raw": 0x39,
                        "tile_context": "stable",
                        "source": SOURCE_TRUSTED_ACTION,
                    }
                ),
            ]

            samples, stats = export_training_samples(
                messages,
                mapping_store=store,
                local_player=0,
                player_count=2,
                include_blocked=True,
            )

            self.assertEqual(stats.trainable, 0)
            self.assertEqual(stats.blocked, 1)
            self.assertEqual(len(samples), 1)
            self.assertFalse(samples[0]["is_trainable"])
            self.assertIsNone(samples[0]["label"])
            self.assertEqual(samples[0]["blocked_reason"], "baida_not_trusted")

    def test_blocks_label_when_actual_discard_mapping_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            messages = [
                _msg(
                    {
                        "event": "baida_update",
                        "baida_raw": 0x53,
                        "baida_context": "stable",
                        "baida_trusted": True,
                        "source": SOURCE_TRUSTED_ACTION,
                    }
                ),
                _msg(
                    {
                        "event": "hand_update",
                        "player": 0,
                        "hand_raw": [
                            0x11,
                            0x11,
                            0x12,
                            0x13,
                            0x14,
                            0x13,
                            0x14,
                            0x15,
                            0x14,
                            0x15,
                            0x16,
                            0x16,
                            0x17,
                            0x39,
                        ],
                        "hand_context": "stable",
                        "source": SOURCE_TRUSTED_HAND,
                    }
                ),
                _msg(
                    {
                        "event": "discard",
                        "player": 0,
                        "tile_raw": 0xEE,
                        "tile_context": "stable",
                        "source": SOURCE_TRUSTED_ACTION,
                    }
                ),
            ]

            samples, stats = export_training_samples(
                messages,
                mapping_store=store,
                local_player=0,
                player_count=2,
                include_blocked=True,
            )

            self.assertEqual(stats.trainable, 0)
            self.assertEqual(stats.blocked, 1)
            self.assertFalse(samples[0]["is_trainable"])
            self.assertEqual(samples[0]["blocked_reason"], "actual_discard_unknown_mapping")
            self.assertEqual(store.unknowns()[0].raw_key, "stable:0xee")

    def test_ignores_opponent_discard_as_training_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            messages = [
                _msg(
                    {
                        "event": "baida_update",
                        "baida_raw": 0x53,
                        "baida_context": "stable",
                        "baida_trusted": True,
                        "source": SOURCE_TRUSTED_ACTION,
                    }
                ),
                _msg(
                    {
                        "event": "hand_update",
                        "player": 0,
                        "hand_raw": [
                            0x11,
                            0x11,
                            0x12,
                            0x13,
                            0x14,
                            0x13,
                            0x14,
                            0x15,
                            0x14,
                            0x15,
                            0x16,
                            0x16,
                            0x17,
                            0x39,
                        ],
                        "hand_context": "stable",
                        "source": SOURCE_TRUSTED_HAND,
                    }
                ),
                _msg(
                    {
                        "event": "discard",
                        "player": 1,
                        "tile_raw": 0x39,
                        "tile_context": "stable",
                        "source": SOURCE_TRUSTED_ACTION,
                    }
                ),
            ]

            samples, stats = export_training_samples(
                messages,
                mapping_store=store,
                local_player=0,
                player_count=2,
            )

            self.assertEqual(stats.trainable, 0)
            self.assertEqual(stats.blocked, 0)
            self.assertEqual(samples, [])


if __name__ == "__main__":
    unittest.main()
