from __future__ import annotations

import os
import struct
import tempfile
import unittest

from stable.mapping import MappingStore
from stable.protocol import MJProtocol, PcapParser, ProtocolMessage, raw_key
from stable.tracker import PacketStateTracker


def make_frame(msg_type: int, payload: bytes = b"", sub_type: int = 0) -> bytes:
    return (
        bytes([0x01, 0x40])
        + struct.pack("<H", len(payload))
        + struct.pack("<H", msg_type)
        + struct.pack("<H", sub_type)
        + b"\x00\x00\x00\x00"
        + payload
    )


def make_game(sub_cmd: int, body: bytes) -> bytes:
    game_payload = struct.pack("<H", sub_cmd) + struct.pack("<H", len(body)) + body
    return make_frame(0x2BC0, game_payload)


def make_packet(payload: bytes, src_port: int = 7777, dst_port: int = 50000):
    return {
        "src": f"1.1.1.1:{src_port}",
        "dst": f"2.2.2.2:{dst_port}",
        "src_port": src_port,
        "dst_port": dst_port,
        "payload": payload,
        "ts": 0,
    }


def make_pcap(payload: bytes) -> bytes:
    eth = b"\x00" * 12 + struct.pack(">H", 0x0800)
    ip_header = bytearray(20)
    ip_header[0] = 0x45
    total_len = 20 + 20 + len(payload)
    ip_header[2:4] = struct.pack(">H", total_len)
    ip_header[8] = 64
    ip_header[9] = 6
    ip_header[12:16] = bytes([1, 1, 1, 1])
    ip_header[16:20] = bytes([2, 2, 2, 2])
    tcp_header = bytearray(20)
    tcp_header[0:2] = struct.pack(">H", 7777)
    tcp_header[2:4] = struct.pack(">H", 50000)
    tcp_header[12] = 0x50
    raw = eth + bytes(ip_header) + bytes(tcp_header) + payload
    global_header = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    packet_header = struct.pack("<IIII", 1, 0, len(raw), len(raw))
    return global_header + packet_header + raw


class StableReaderTests(unittest.TestCase):
    def make_msg(self, game: dict) -> ProtocolMessage:
        return ProtocolMessage(
            ts="2026-01-01T00:00:00.000",
            direction="S->C",
            msg_type=0x2BC0,
            type_name="game_event",
            sub_type=0,
            extra="",
            size=0,
            pay_len=0,
            game=game,
        )

    def test_protocol_reassembles_split_frames(self):
        proto = MJProtocol(server_port=7777)
        frame = make_game(0x021B, bytes([1, 5]))
        first = proto.process_packet(make_packet(frame[:5]))
        second = proto.process_packet(make_packet(frame[5:]))
        self.assertEqual(first, [])
        self.assertEqual(len(second), 1)
        game = second[0].game
        self.assertEqual(game["event"], "discard")
        self.assertEqual(game["player"], 1)
        self.assertEqual(game["tile_raw"], 5)
        self.assertEqual(game["tile_context"], "stable")

    def test_protocol_decodes_stable_field_positions(self):
        proto = MJProtocol(server_port=7777)

        deal = proto.process_packet(make_packet(make_game(0x0003, bytes.fromhex("0b0b262503020e2007121314150b020202463c3c3c3c3c3c3c"))))[0].game
        self.assertEqual(deal["event"], "deal")
        self.assertEqual(deal["source"], "untrusted_round_marker")
        self.assertFalse(deal["trusted"])
        self.assertNotIn("hand_raw", deal)
        self.assertNotIn("baida_raw", deal)
        self.assertEqual(deal["untrusted_hand_raw_candidate"], [11, 11, 38, 37, 3, 2, 14, 32, 7, 18, 19, 20, 21])
        self.assertEqual(deal["untrusted_hand_context"], "untrusted_deal")
        self.assertEqual(deal["untrusted_baida_raw_candidate"], 0x46)
        self.assertEqual(deal["untrusted_baida_context"], "untrusted_deal")

        hand_update = proto.process_packet(make_packet(make_game(0x0216, bytes.fromhex("03000d2819181924124213292643532100"))))[0].game
        self.assertEqual(hand_update["event"], "hand_update")
        self.assertEqual(hand_update["player"], 3)
        self.assertEqual(hand_update["hand_raw"], [40, 25, 24, 25, 36, 18, 66, 19, 41, 38, 67, 83, 33])
        self.assertEqual(hand_update["hand_context"], "stable")
        self.assertEqual(hand_update["hand_count_raw"], 13)
        self.assertEqual(hand_update["hand_tail_raw"], [0])
        self.assertEqual(hand_update["source"], "trusted_hand")

        concealed_draw = proto.process_packet(make_packet(make_game(0x021A, bytes.fromhex("01720e00000000"))))[0].game
        self.assertEqual(concealed_draw["event"], "draw")
        self.assertEqual(concealed_draw["player"], 1)
        self.assertNotIn("tile_raw", concealed_draw)

        visible_draw = proto.process_packet(make_packet(make_game(0x021A, bytes.fromhex("03230000000000"))))[0].game
        self.assertEqual(visible_draw["player"], 3)
        self.assertEqual(visible_draw["tile_raw"], 0x23)
        self.assertEqual(visible_draw["tile_offset"], 1)
        self.assertEqual(visible_draw["tile_context"], "stable")

        discard = proto.process_packet(make_packet(make_game(0x021B, bytes.fromhex("034300000000"))))[0].game
        self.assertEqual(discard["event"], "discard")
        self.assertEqual(discard["player"], 3)
        self.assertEqual(discard["tile_raw"], 0x43)
        self.assertEqual(discard["tile_context"], "stable")
        self.assertEqual(discard["source"], "trusted_action")

        kong = proto.process_packet(make_packet(make_game(0x021F, bytes.fromhex("01020303434343014300000000"))))[0].game
        self.assertEqual(kong["event"], "kong")
        self.assertEqual(kong["player"], 1)
        self.assertEqual(kong["tile_raw"], 0x43)
        self.assertEqual(kong["tile_context"], "stable")

        win = proto.process_packet(make_packet(make_game(0x0220, bytes.fromhex("010000000000000000000000004102000000003c000000"))))[0].game
        self.assertEqual(win["event"], "win")
        self.assertEqual(win["player"], 1)
        self.assertEqual(win["tile_raw"], 0x41)
        self.assertEqual(win["tile_offset"], 13)
        self.assertEqual(win["tile_context"], "stable")

    def test_pcap_parser_extracts_tcp_payload(self):
        parser = PcapParser()
        frame = make_game(0x021B, bytes([1, 5]))
        packets = parser.feed(make_pcap(frame))
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0]["src_port"], 7777)
        self.assertEqual(packets[0]["payload"], frame)

    def test_deal_packet_is_not_authoritative_hand_or_baida(self):
        proto = MJProtocol(server_port=7777)
        game = proto.process_packet(
            make_packet(make_game(0x0003, bytes.fromhex("0b0b262503020e2007121314150b020202463c3c3c3c3c3c3c")))
        )[0].game

        self.assertEqual(game["event"], "deal")
        self.assertEqual(game["source"], "untrusted_round_marker")
        self.assertNotIn("hand_raw", game)
        self.assertNotIn("baida_raw", game)
        self.assertEqual(game["untrusted_hand_raw_candidate"][:3], [0x0B, 0x0B, 0x26])
        self.assertEqual(game["untrusted_baida_raw_candidate"], 0x46)

    def test_1934_regression_does_not_surface_false_opening_hand(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store, local_player=1)
            proto = MJProtocol(server_port=7777)
            game = proto.process_packet(
                make_packet(make_game(0x0003, bytes.fromhex("0b0b262503020e2007121314150b020202463c3c3c3c3c3c3c")))
            )[0].game

            tracker.apply(self.make_msg(game))
            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["players"][1]["hand"], [])
            self.assertEqual(snapshot["baida_tile"], "")
            self.assertEqual(snapshot["analysis_blocked_reason"], "等待可信手牌包")

            surfaced = " ".join(snapshot["players"][1]["hand"] + [snapshot["baida_tile"]])
            for false_tile in ("3m", "1p", "3s", "1m", "9p", "9m"):
                self.assertNotIn(false_tile, surfaced)

    def test_analysis_blocked_when_only_untrusted_deal_seen(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store, local_player=1)
            tracker.apply(
                self.make_msg(
                    {
                        "event": "deal",
                        "source": "untrusted_round_marker",
                        "trusted": False,
                        "untrusted_hand_raw_candidate": list(range(1, 14)),
                        "untrusted_hand_context": "instance",
                        "untrusted_baida_raw_candidate": 109,
                        "untrusted_baida_context": "instance",
                    }
                )
            )

            self.assertFalse(tracker.should_analyze())
            self.assertEqual(tracker.analysis_blocked_reason(), "等待可信手牌包")
            self.assertEqual(tracker.to_battle_state().self_hand, [])

    def test_stable_mapping_matches_2118_opening_first_13(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            proto = MJProtocol(server_port=7777)
            game = proto.process_packet(
                make_packet(make_game(0x0216, bytes.fromhex("00000d511623383837324253241717350131")))
            )[0].game

            tiles = [store.resolve_tile(raw_key(game["hand_context"], value)) for value in game["hand_raw"]]
            self.assertEqual(
                game["hand_raw"],
                [0x51, 0x16, 0x23, 0x38, 0x38, 0x37, 0x32, 0x42, 0x53, 0x24, 0x17, 0x17, 0x35],
            )
            self.assertCountEqual(
                tiles,
                ["6m", "7z", "7m", "7m", "3s", "4s", "2p", "5p", "7p", "8p", "8p", "2z", "5z"],
            )
            self.assertEqual(game["hand_tail_raw"], [0x01, 0x31])

    def test_stable_mapping_matches_2119_opening_first_13(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            proto = MJProtocol(server_port=7777)
            game = proto.process_packet(
                make_packet(make_game(0x0216, bytes.fromhex("00000d352518251143282252164451370133")))
            )[0].game

            tiles = [store.resolve_tile(raw_key(game["hand_context"], value)) for value in game["hand_raw"]]
            self.assertEqual(
                game["hand_raw"],
                [0x35, 0x25, 0x18, 0x25, 0x11, 0x43, 0x28, 0x22, 0x52, 0x16, 0x44, 0x51, 0x37],
            )
            self.assertCountEqual(
                tiles,
                ["1m", "6m", "8m", "2s", "5s", "5s", "8s", "5p", "7p", "3z", "4z", "5z", "6z"],
            )
            self.assertEqual(game["hand_tail_raw"], [0x01, 0x33])

    def test_mapping_store_unknown_then_manual_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "mappings.yaml")
            store = MappingStore(path=path)
            key = raw_key("linear", 0x14)
            self.assertIsNone(store.resolve_tile(key))
            store.note_unknown(key, "test")
            self.assertEqual(store.unknowns()[0].raw_key, key)
            store.save_tile_mapping(key, "4p")
            self.assertEqual(store.resolve_tile(key), "4p")
            reloaded = MappingStore(path=path)
            self.assertEqual(reloaded.resolve_tile(key), "4p")

    def test_opponent_seat_is_across_from_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            self.assertEqual(PacketStateTracker(store, local_player=1).opponent_player, 3)
            self.assertEqual(PacketStateTracker(store, local_player=0).opponent_player, 2)

    def test_first_trusted_full_hand_locks_local_player(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store, local_player=1)

            tracker.apply(
                self.make_msg(
                    {
                        "event": "hand_update",
                        "player": 0,
                        "hand_raw": list(range(1, 14)),
                        "hand_context": "instance",
                        "source": "trusted_hand",
                    }
                )
            )

            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["local_player"], 0)
            self.assertEqual(snapshot["opponent_player"], 2)
            self.assertEqual(snapshot["players"][0]["hand"], ["1s", "1s", "1s", "1s", "2s", "2s", "2s", "2s", "3s", "3s", "3s", "3s", "4s"])
            self.assertTrue(snapshot["hand_trusted"])

    def test_pre_hand_win_packet_does_not_mark_round_as_finished(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store, local_player=1)
            tracker.apply(self.make_msg({"event": "deal", "source": "untrusted_round_marker", "trusted": False}))
            tracker.apply(
                self.make_msg(
                    {
                        "event": "win",
                        "player": 1,
                        "tile_raw": 65,
                        "tile_context": "instance",
                        "source": "trusted_action",
                    }
                )
            )

            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["phase"], "playing")
            self.assertEqual(snapshot["analysis_blocked_reason"], "等待可信手牌包")

    def test_four_player_packets_only_feed_two_player_snapshot_and_battle_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store, local_player=1)
            tracker.apply(self.make_msg({
                "event": "hand_update",
                "player": 1,
                "hand_raw": list(range(1, 14)),
                "hand_context": "instance",
                "source": "trusted_hand",
            }))
            tracker.apply(self.make_msg({"event": "draw", "player": 1, "tile_raw": 14, "tile_context": "instance", "source": "trusted_action"}))
            tracker.apply(self.make_msg({"event": "discard", "player": 0, "tile_raw": 21, "tile_context": "instance", "source": "trusted_action"}))
            tracker.apply(self.make_msg({"event": "discard", "player": 2, "tile_raw": 25, "tile_context": "instance", "source": "trusted_action"}))
            tracker.apply(self.make_msg({"event": "discard", "player": 3, "tile_raw": 33, "tile_context": "instance", "source": "trusted_action"}))

            snapshot = tracker.snapshot()
            self.assertEqual(set(snapshot["players"].keys()), {1, 3})
            self.assertEqual(snapshot["players"][3]["discards"], ["9s"])
            state = tracker.to_battle_state()
            self.assertEqual([t.tile_id for t in state.enemy_discards], ["9s"])
            self.assertNotIn("6s", [t.tile_id for t in state.enemy_discards])
            self.assertNotIn("7s", [t.tile_id for t in state.enemy_discards])

    def test_manual_mapping_replays_history_into_chinese_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store, local_player=1)
            tracker.apply(
                self.make_msg({"event": "discard", "player": 3, "tile_raw": 0xEE, "tile_context": "instance", "source": "trusted_action"})
            )
            self.assertEqual(store.unknowns()[0].raw_key, "instance:0xee")

            store.save_tile_mapping("instance:0xee", "3p")
            tracker.rebuild_from_history()
            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["players"][3]["discards"], ["3p"])
            event_text = "\n".join(snapshot["events"])
            self.assertIn("对面打出3筒", event_text)
            for token in ("deal", "discard", "draw", "P0", "raw", "unknown"):
                self.assertNotIn(token, event_text)

    def test_tracker_blocks_without_baida_and_analyzes_with_baida(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store)

            hand_update = self.make_msg(
                {
                    "event": "hand_update",
                    "player": 1,
                    "hand_raw": list(range(1, 14)),
                    "hand_context": "instance",
                    "source": "trusted_hand",
                },
            )
            draw = self.make_msg(
                {"event": "draw", "player": 1, "tile_raw": 14, "tile_context": "instance", "source": "trusted_action"}
            )
            tracker.apply(hand_update)
            tracker.apply(draw)
            self.assertEqual(tracker.analysis_blocked_reason(), "等待抓包解析财神")
            tracker.baida_tile = "7z"
            tracker.baida_trusted = True
            self.assertTrue(tracker.should_analyze())
            state = tracker.to_battle_state()
            self.assertEqual(len(state.self_hand), 14)
            self.assertEqual(state.baida_tile, "7z")
            self.assertEqual(state.recognition_source, "packet")

    def test_ready_packet_state_uses_packet_recognition_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store, local_player=0)
            tracker.apply(self.make_msg({
                "event": "hand_update",
                "player": 0,
                "hand_raw": list(range(1, 14)),
                "hand_context": "instance",
                "source": "trusted_hand",
            }))
            tracker.baida_tile = "7z"
            tracker.baida_trusted = True
            tracker.apply(
                self.make_msg({"event": "draw", "player": 0, "tile_raw": 14, "tile_context": "instance", "source": "trusted_action"})
            )

            self.assertEqual(tracker.analysis_blocked_reason(), "")
            self.assertTrue(tracker.should_analyze())
            self.assertEqual(tracker.to_battle_state().recognition_source, "packet")


if __name__ == "__main__":
    unittest.main()
