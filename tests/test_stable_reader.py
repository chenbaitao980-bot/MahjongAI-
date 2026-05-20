from __future__ import annotations

import os
import struct
import tempfile
import unittest

from game.llm_advisor import normalize_discard, validate_llm_output
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


def make_packet(payload: bytes, src_port: int = 7777, dst_port: int = 50000, seq: int | None = None):
    packet = {
        "src": f"1.1.1.1:{src_port}",
        "dst": f"2.2.2.2:{dst_port}",
        "src_port": src_port,
        "dst_port": dst_port,
        "payload": payload,
        "ts": 0,
    }
    if seq is not None:
        packet["seq"] = seq
    return packet


def make_pcap(payload: bytes, seq: int = 0) -> bytes:
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
    tcp_header[4:8] = struct.pack(">I", seq)
    tcp_header[12] = 0x50
    raw = eth + bytes(ip_header) + bytes(tcp_header) + payload
    global_header = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    packet_header = struct.pack("<IIII", 1, 0, len(raw), len(raw))
    return global_header + packet_header + raw


def make_legacy_packet(payload: bytes, src_port: int = 7777, dst_port: int = 50000):
    return {
        "src": f"1.1.1.1:{src_port}",
        "dst": f"2.2.2.2:{dst_port}",
        "src_port": src_port,
        "dst_port": dst_port,
        "payload": payload,
        "ts": 0,
    }


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
        first = proto.process_packet(make_packet(frame[:5], seq=100))
        second = proto.process_packet(make_packet(frame[5:], seq=105))
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

        kong = proto.process_packet(make_packet(make_game(0x021F, bytes.fromhex("01020304434343014300000000"))))[0].game
        self.assertEqual(kong["event"], "kong")
        self.assertEqual(kong["player"], 1)
        self.assertEqual(kong["tile_raw"], 0x43)
        self.assertEqual(kong["tile_context"], "stable")
        self.assertEqual(kong["meld_type"], "kan_open")
        self.assertEqual(kong["meld_tiles_raw"], [0x43, 0x43, 0x43, 0x43])

        pon_claim = proto.process_packet(make_packet(make_game(0x021F, bytes.fromhex("01020303434343014300000000"))))[0].game
        self.assertEqual(pon_claim["event"], "pon")
        self.assertEqual(pon_claim["player"], 1)
        self.assertEqual(pon_claim["tile_raw"], 0x43)
        self.assertEqual(pon_claim["meld_type"], "pon")
        self.assertEqual(pon_claim["meld_tiles_raw"], [0x43, 0x43, 0x43])

        meld_claim = proto.process_packet(make_packet(make_game(0x021F, bytes.fromhex("03010203171819011800000000"))))[0].game
        self.assertEqual(meld_claim["event"], "chi")
        self.assertEqual(meld_claim["player"], 3)
        self.assertEqual(meld_claim["tile_raw"], 0x18)
        self.assertEqual(meld_claim["tile_context"], "stable")
        self.assertEqual(meld_claim["meld_type"], "chi")
        self.assertEqual(meld_claim["meld_tiles_raw"], [0x17, 0x18, 0x19])

        substitute_meld = proto.process_packet(make_packet(make_game(0x021F, bytes.fromhex("01010003375339015300000000"))))[0].game
        self.assertEqual(substitute_meld["event"], "chi")
        self.assertEqual(substitute_meld["meld_tiles_raw"], [0x37, 0x53, 0x39])
        self.assertEqual(substitute_meld["meld_note"], "contains_substitute")

        invalid_meld = proto.process_packet(make_packet(make_game(0x021F, bytes.fromhex("00010103131453011400000000"))))[0].game
        self.assertEqual(invalid_meld["event"], "kong")
        self.assertEqual(invalid_meld["player"], 0)
        self.assertEqual(invalid_meld["tile_raw"], 0x14)
        self.assertNotIn("meld_type", invalid_meld)
        self.assertNotIn("meld_tiles_raw", invalid_meld)

        win = proto.process_packet(make_packet(make_game(0x0220, bytes.fromhex("010000000000000000000000004102000000003c000000"))))[0].game
        self.assertEqual(win["event"], "win")
        self.assertEqual(win["player"], 1)
        self.assertEqual(win["tile_raw"], 0x41)
        self.assertEqual(win["tile_offset"], 13)
        self.assertEqual(win["tile_context"], "stable")

    def test_optional_action_and_meld_summary_do_not_pollute_hand(self):
        proto = MJProtocol(server_port=7777)
        optional = proto.process_packet(make_packet(make_game(0x0016, bytes([0, 0x03, 0x43]))))[0].game
        self.assertEqual(optional["event"], "optional_action")
        self.assertEqual(optional["options"], ["chi", "pon", "pass"])
        self.assertEqual(optional["option_labels"], ["吃", "碰", "过"])

        body = bytes([0, 4, 5, 1, 4, 0x43, 0x43, 0x43, 3, 0x43, 0x43, 0x43, 0, 3, 0x17, 0x18, 0x19, 1, 0, 0])
        summary = proto.process_packet(make_packet(make_game(0x0216, body)))[0].game
        self.assertEqual(summary["event"], "meld_summary")
        self.assertFalse(summary["trusted"])

        with tempfile.TemporaryDirectory() as tmp:
            tracker = PacketStateTracker(MappingStore(path=os.path.join(tmp, "mappings.yaml")), local_player=0, player_count=2)
            tracker.apply(self.make_msg({
                "event": "hand_update",
                "player": 0,
                "hand_raw": [0x11, 0x12, 0x13, 0x14, 0x21, 0x22, 0x23, 0x24, 0x31, 0x32, 0x33, 0x34, 0x41],
                "hand_context": "stable",
                "source": "trusted_hand",
            }))
            before = list(tracker.snapshot()["players"][0]["hand"])
            tracker.apply(self.make_msg(summary))
            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["players"][0]["hand"], before)
            self.assertEqual(snapshot["hand_incomplete_reason"], "等待可信手牌包，忽略副露汇总包")

    def test_llm_discard_normalization_accepts_chinese_tile_names(self):
        output = {"recommended_discard": "建议打五万", "strategy_type": "平衡"}
        self.assertTrue(validate_llm_output(output, ["5m", "7p"]))
        self.assertEqual(output["recommended_discard"], "5m")
        self.assertEqual(normalize_discard("候选方案：打7p", ["5m", "7p"]), "7p")

    def test_pcap_parser_extracts_tcp_payload(self):
        parser = PcapParser()
        frame = make_game(0x021B, bytes([1, 5]))
        packets = parser.feed(make_pcap(frame))
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0]["src_port"], 7777)
        self.assertEqual(packets[0]["seq"], 0)
        self.assertEqual(packets[0]["payload"], frame)

    def test_protocol_ignores_retransmitted_payload(self):
        proto = MJProtocol(server_port=7777)
        frame = make_game(0x021B, bytes([1, 5]))

        first = proto.process_packet(make_packet(frame, seq=1000))
        second = proto.process_packet(make_packet(frame, seq=1000))

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

    def test_protocol_trims_partially_retransmitted_payload(self):
        proto = MJProtocol(server_port=7777)
        frame = make_game(0x021B, bytes([1, 5]))

        first = proto.process_packet(make_packet(frame[:5], seq=2000))
        second = proto.process_packet(make_packet(frame, seq=2000))
        third = proto.process_packet(make_packet(frame, seq=2000))

        self.assertEqual(first, [])
        self.assertEqual(len(second), 1)
        self.assertEqual(third, [])

    def test_protocol_seq_helpers_handle_wraparound(self):
        self.assertTrue(MJProtocol._seq_lt(0xFFFFFFFE, 1))
        self.assertTrue(MJProtocol._seq_le(0, 0))
        self.assertTrue(MJProtocol._seq_le(0xFFFFFFFF, 1))
        self.assertFalse(MJProtocol._seq_lt(2, 1))

    def test_protocol_without_seq_preserves_legacy_streaming(self):
        proto = MJProtocol(server_port=7777)
        frame = make_game(0x021B, bytes([1, 5]))
        first = proto.process_packet(make_legacy_packet(frame[:5]))
        second = proto.process_packet(make_legacy_packet(frame[5:]))
        self.assertEqual(first, [])
        self.assertEqual(len(second), 1)

    def test_protocol_auto_detects_frame_on_non_configured_port(self):
        proto = MJProtocol(server_port=7777, auto_detect_frames=True)
        frame = make_game(0x0216, bytes([0, 0, 13, *range(1, 14)]))

        messages = proto.process_packet(make_packet(frame, src_port=18888, dst_port=50000))

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].game["event"], "hand_update")
        self.assertEqual(messages[0].game["player"], 0)

    def test_protocol_ignores_non_configured_port_without_auto_detect(self):
        proto = MJProtocol(server_port=7777)
        frame = make_game(0x0216, bytes([0, 0, 13, *range(1, 14)]))

        messages = proto.process_packet(make_packet(frame, src_port=18888, dst_port=50000))

        self.assertEqual(messages, [])

    def test_protocol_auto_detect_ignores_non_frame_payload(self):
        proto = MJProtocol(server_port=7777, auto_detect_frames=True)

        messages = proto.process_packet(make_packet(b"not a mahjong frame", src_port=18888, dst_port=50000))

        self.assertEqual(messages, [])

    def test_protocol_appends_separated_fourteenth_hand_tile_from_tail(self):
        proto = MJProtocol(server_port=7777)

        game = proto.process_packet(
            make_packet(make_game(0x0216, bytes.fromhex("00000d31323818133152163221534133013900000000")))
        )[0].game

        self.assertEqual(game["hand_count_raw"], 13)
        self.assertEqual(game["hand_extra_raw"], 0x39)
        self.assertEqual(game["hand_tail_raw"], [0x01, 0x39, 0x00, 0x00, 0x00, 0x00])
        self.assertEqual(len(game["hand_raw"]), 14)
        self.assertEqual(game["hand_raw"][-1], 0x39)

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
                [0x51, 0x16, 0x23, 0x38, 0x38, 0x37, 0x32, 0x42, 0x53, 0x24, 0x17, 0x17, 0x35, 0x31],
            )
            self.assertCountEqual(
                tiles,
                ["1p", "6m", "7z", "7m", "7m", "3s", "4s", "2p", "5p", "7p", "8p", "8p", "2z", "5z"],
            )
            self.assertEqual(game["hand_tail_raw"], [0x01, 0x31])
            self.assertEqual(game["hand_extra_raw"], 0x31)

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
                [0x35, 0x25, 0x18, 0x25, 0x11, 0x43, 0x28, 0x22, 0x52, 0x16, 0x44, 0x51, 0x37, 0x33],
            )
            self.assertCountEqual(
                tiles,
                ["1m", "6m", "8m", "2s", "5s", "5s", "8s", "3p", "5p", "7p", "3z", "4z", "5z", "6z"],
            )
            self.assertEqual(game["hand_tail_raw"], [0x01, 0x33])
            self.assertEqual(game["hand_extra_raw"], 0x33)

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

    def test_two_player_mode_uses_next_protocol_player_as_opponent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store, local_player=0, player_count=2)

            self.assertEqual(tracker.opponent_player, 1)
            self.assertEqual(tracker.snapshot()["opponent_player"], 1)

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

    def test_snapshot_sorts_only_local_hand_for_display(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store, local_player=1)
            tracker.players[1].hand = ["5p", "1m", "7z", "2s", "1p", "3m"]
            tracker.players[1].discards = ["7z", "1m"]
            tracker.players[1].melds = [{"type": "kan_open", "tiles": ["5p", "5p", "5p", "5p"]}]
            tracker.players[3].hand = ["5p", "1m"]

            snapshot = tracker.snapshot()

            self.assertEqual(snapshot["players"][1]["hand"], ["1m", "3m", "2s", "1p", "5p", "7z"])
            self.assertEqual(snapshot["players"][1]["discards"], ["7z", "1m"])
            self.assertEqual(snapshot["players"][1]["melds"], [{"type": "kan_open", "tiles": ["5p", "5p", "5p", "5p"]}])
            self.assertEqual(snapshot["players"][3]["hand"], ["5p", "1m"])
            self.assertEqual(tracker.players[1].hand, ["5p", "1m", "7z", "2s", "1p", "3m"])
            self.assertEqual([tile.tile_id for tile in tracker.to_battle_state().self_hand], ["5p", "1m", "7z", "2s", "1p", "3m"])

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

    def test_side_player_kong_removes_claimed_opponent_discard(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store, local_player=0)
            tracker.players[2].discards = ["9s", "8m"]

            tracker.apply(
                self.make_msg(
                    {
                        "event": "kong",
                        "player": 1,
                        "tile_raw": 0x18,
                        "tile_context": "stable",
                        "source": "trusted_action",
                    }
                )
            )

            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["players"][2]["discards"], ["9s"])
            self.assertEqual(snapshot["players"][2]["melds"], [])

    def test_opponent_kong_removes_claimed_local_discard_and_adds_meld(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store, local_player=0)
            tracker.players[0].discards = ["2m"]

            tracker.apply(
                self.make_msg(
                    {
                        "event": "kong",
                        "player": 2,
                        "tile_raw": 0x12,
                        "tile_context": "stable",
                        "meld_type": "kan_open",
                        "meld_tiles_raw": [0x12, 0x12, 0x12, 0x12],
                        "source": "trusted_action",
                    }
                )
            )

            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["players"][0]["discards"], [])
            self.assertEqual(snapshot["players"][2]["melds"], [{"type": "kan_open", "tiles": ["2m", "2m", "2m", "2m"]}])
            self.assertEqual(snapshot["remaining_tiles"], 107)

    def test_invalid_mixed_meld_does_not_create_fake_open_kong(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store, local_player=0, player_count=2)
            tracker.players[1].discards = ["4m"]

            tracker.apply(
                self.make_msg(
                    {
                        "event": "kong",
                        "player": 0,
                        "tile_raw": 0x14,
                        "tile_context": "stable",
                        "source": "trusted_action",
                    }
                )
            )

            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["players"][0]["melds"], [])
            self.assertEqual(snapshot["players"][1]["discards"], [])
            self.assertEqual(snapshot["remaining_tiles"], 108)

    def test_opponent_chi_removes_claimed_local_discard_and_adds_sequence_meld(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store, local_player=0)
            tracker.players[0].discards = ["8m"]

            tracker.apply(
                self.make_msg(
                    {
                        "event": "kong",
                        "player": 2,
                        "tile_raw": 0x18,
                        "tile_context": "stable",
                        "meld_type": "chi",
                        "meld_tiles_raw": [0x17, 0x18, 0x19],
                        "source": "trusted_action",
                    }
                )
            )

            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["players"][0]["discards"], [])
            self.assertEqual(snapshot["players"][2]["melds"], [{"type": "chi", "tiles": ["7m", "8m", "9m"]}])
            self.assertEqual(snapshot["remaining_tiles"], 108)

    def test_two_player_discard_echo_draw_does_not_add_self_tile(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store, local_player=0, player_count=2)

            tracker.apply(
                self.make_msg(
                    {
                        "event": "discard",
                        "player": 1,
                        "tile_raw": 0x42,
                        "tile_context": "stable",
                        "source": "trusted_action",
                    }
                )
            )
            tracker.apply(
                self.make_msg(
                    {
                        "event": "draw",
                        "player": 0,
                        "tile_raw": 0x42,
                        "tile_context": "stable",
                        "source": "trusted_action",
                    }
                )
            )

            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["players"][1]["discards"], ["2z"])
            self.assertEqual(snapshot["players"][0]["hand"], [])
            self.assertEqual(snapshot["remaining_tiles"], 108)
            self.assertEqual(snapshot["current_turn"], "self")
            events = "\n".join(snapshot["events"])
            self.assertIn("对面打出南", events)
            self.assertNotIn("我方摸牌南", events)

    def test_two_player_opponent_chi_shows_in_opponent_melds(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store, local_player=0, player_count=2)
            tracker.players[0].discards = ["5s"]

            tracker.apply(
                self.make_msg(
                    {
                        "event": "kong",
                        "player": 1,
                        "tile_raw": 0x25,
                        "tile_context": "stable",
                        "meld_type": "chi",
                        "meld_tiles_raw": [0x23, 0x24, 0x25],
                        "source": "trusted_action",
                    }
                )
            )

            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["opponent_player"], 1)
            self.assertEqual(snapshot["players"][1]["melds"], [{"type": "chi", "tiles": ["3s", "4s", "5s"]}])
            self.assertEqual(snapshot["players"][0]["discards"], [])
            self.assertEqual(snapshot["remaining_tiles"], 108)

    def test_new_round_hand_update_resets_old_discards_and_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store, local_player=0, player_count=2)
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
            tracker.baida_tile = "7z"
            tracker.baida_trusted = True
            tracker.apply(self.make_msg({"event": "discard", "player": 0, "tile_raw": 0x11, "tile_context": "stable", "source": "trusted_action"}))
            tracker.apply(self.make_msg({"event": "discard", "player": 1, "tile_raw": 0x21, "tile_context": "stable", "source": "trusted_action"}))
            tracker.remaining_tiles = 44
            tracker.apply(self.make_msg({"event": "win", "player": 0, "source": "trusted_action"}))

            tracker.apply(
                self.make_msg(
                    {
                        "event": "hand_update",
                        "player": 0,
                        "hand_raw": [0x15, 0x14, 0x27, 0x43, 0x53, 0x18, 0x32, 0x32, 0x39, 0x19, 0x26, 0x31, 0x11],
                        "hand_context": "stable",
                        "source": "trusted_hand",
                    }
                )
            )

            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["phase"], "playing")
            self.assertEqual(snapshot["remaining_tiles"], 108)
            self.assertEqual(snapshot["players"][0]["discards"], [])
            self.assertEqual(snapshot["players"][1]["discards"], [])
            self.assertEqual(snapshot["players"][0]["melds"], [])
            self.assertEqual(snapshot["events"], ["00:00:00 我方手牌更新：13 张"])
            self.assertEqual(snapshot["baida_tile"], "7z")
            self.assertTrue(snapshot["baida_trusted"])

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

    def test_baida_update_sub_0x0218_applied(self):
        # body = 01 37 01 53 → baida 7p (0x37)
        frame = make_game(0x0218, bytes([0x01, 0x37, 0x01, 0x53]))
        proto = MJProtocol(server_port=7777)
        msgs = proto.process_packet(make_packet(frame, seq=10))
        self.assertEqual(len(msgs), 1)
        g = msgs[0].game
        self.assertEqual(g["event"], "baida_update")
        self.assertEqual(g["baida_raw"], 0x37)
        self.assertTrue(g["baida_trusted"])
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store, local_player=0, player_count=2)
            tracker.apply(msgs[0])
            self.assertEqual(tracker.baida_tile, "7p")
            self.assertTrue(tracker.baida_trusted)

    def test_chi_event_appends_meld_and_removes_discard(self):
        # 对面打出 1m (0x11) 后我方吃 1m 2m 3m
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store, local_player=0, player_count=2)
            # trusted hand for local
            tracker.apply(self.make_msg({
                "event": "hand_update",
                "player": 0,
                "hand_raw": [0x11, 0x12, 0x13, 0x21, 0x22, 0x23, 0x31, 0x32, 0x33, 0x41, 0x42, 0x43, 0x44],
                "hand_context": "stable",
                "source": "trusted_hand",
            }))
            # 对面打出 1m
            tracker.apply(self.make_msg({
                "event": "discard",
                "player": 1,
                "tile_raw": 0x11,
                "tile_context": "stable",
                "source": "trusted_action",
            }))
            # 我方吃 1m 2m 3m
            tracker.apply(self.make_msg({
                "event": "chi",
                "player": 0,
                "tile_raw": 0x11,
                "tile_context": "stable",
                "meld_type": "chi",
                "meld_tiles_raw": [0x11, 0x12, 0x13],
                "source": "trusted_action",
            }))
            snap = tracker.snapshot()
            self.assertEqual(snap["players"][0]["melds"], [{"type": "chi", "tiles": ["1m", "2m", "3m"]}])
            self.assertEqual(snap["players"][1]["discards"], [])

    def test_pon_event_appends_meld(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store, local_player=0, player_count=2)
            tracker.apply(self.make_msg({
                "event": "hand_update",
                "player": 0,
                "hand_raw": [0x11, 0x11, 0x12, 0x13, 0x21, 0x22, 0x23, 0x31, 0x32, 0x33, 0x41, 0x42, 0x43],
                "hand_context": "stable",
                "source": "trusted_hand",
            }))
            tracker.apply(self.make_msg({
                "event": "discard",
                "player": 1,
                "tile_raw": 0x11,
                "tile_context": "stable",
                "source": "trusted_action",
            }))
            tracker.apply(self.make_msg({
                "event": "pon",
                "player": 0,
                "tile_raw": 0x11,
                "tile_context": "stable",
                "meld_type": "pon",
                "meld_tiles_raw": [0x11, 0x11, 0x11],
                "source": "trusted_action",
            }))
            snap = tracker.snapshot()
            self.assertEqual(snap["players"][0]["melds"], [{"type": "pon", "tiles": ["1m", "1m", "1m"]}])
            self.assertEqual(snap["players"][1]["discards"], [])

    def test_conservative_mode_allows_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MappingStore(path=os.path.join(tmp, "mappings.yaml"))
            tracker = PacketStateTracker(store, local_player=0, player_count=2)
            tracker.apply(self.make_msg({
                "event": "hand_update",
                "player": 0,
                "hand_raw": [0x11, 0x12, 0x13, 0x14, 0x21, 0x22, 0x23, 0x24, 0x31, 0x32, 0x33, 0x34, 0x41],
                "hand_context": "stable",
                "source": "trusted_hand",
            }))
            # 没有财神，没有可信回合 → 应进入 conservative
            self.assertFalse(tracker.baida_trusted)
            self.assertEqual(tracker.analysis_mode(), "blocked")
            self.assertFalse(tracker.should_analyze())
            state = tracker.to_battle_state()
            self.assertFalse(state.is_conservative)


if __name__ == "__main__":
    unittest.main()
