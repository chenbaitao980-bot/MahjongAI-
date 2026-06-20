"""N5 side-channel feature extractor.

Splits the record event stream into rounds (anchored by deal/round_start) and,
per round, builds time-ordered side-channel features for player=0 (self) and
player=1 (opponent):

  - discard sequence  -> opponent discards are FULLY in the clear (real tiles,
                         server does NOT redact discards). STRONG signal.
  - meld events       -> opponent chi/pon expose REAL tiles. STRONG signal.
  - draw count        -> opponent draws are concealed (0x72) but the EVENT fires;
                         counting them = turn progress. WEAK signal.
  - hand_update count -> opponent hand size over time (13 -> meld shrinks etc).
                         WEAK signal.
  - inter-action gap  -> seconds between an opponent draw and its discard, from
                         the record's 10-digit timestamp. Long gap => the player
                         likely deliberating a key decision / near tenpai edge.
                         WEAK signal (record ts has 1s granularity).

Pure offline. Reuses n5_record_parser only.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from n5_record_parser import RecordEvent, parse_file  # noqa: E402

ROUND_START_SUBS = {0x0003, 0x0004}
SELF = 0
OPPONENT = 1


@dataclass
class PlayerFeatures:
    player: int
    discards: list[str] = field(default_factory=list)        # real tiles (clear)
    discard_raw: list[int] = field(default_factory=list)
    melds: list[dict[str, Any]] = field(default_factory=list)  # {type, tiles}
    draw_count: int = 0
    hand_counts: list[int] = field(default_factory=list)
    # per-action timestamps for gap analysis
    draw_ts: list[int] = field(default_factory=list)
    discard_ts: list[int] = field(default_factory=list)


@dataclass
class RoundFeatures:
    index: int
    start_seq: int
    self_feat: PlayerFeatures
    opp_feat: PlayerFeatures
    event_count: int = 0

    def opponent_act_gaps(self) -> list[int]:
        """Seconds between each opponent draw and the next opponent discard."""
        gaps: list[int] = []
        opp = self.opp_feat
        di = 0
        for dts in opp.draw_ts:
            while di < len(opp.discard_ts) and opp.discard_ts[di] < dts:
                di += 1
            if di < len(opp.discard_ts):
                gaps.append(opp.discard_ts[di] - dts)
                di += 1
        return gaps


def _classify_meld(exposed_tiles: list[str | None]) -> dict[str, Any]:
    tiles = [t for t in exposed_tiles if t]
    if not tiles:
        return {"type": "unknown", "tiles": []}
    # kong: 4 identical
    if len(tiles) >= 4 and len(set(tiles[:4])) == 1:
        return {"type": "kong", "tiles": tiles[:4]}
    # pon: 3 identical
    if len(tiles) >= 3 and len(set(tiles[:3])) == 1:
        return {"type": "pon", "tiles": tiles[:3]}
    # chi: 3 sequential same-suit
    suited = [t for t in tiles[:3] if t and t[-1] in ("m", "p", "s")]
    if len(suited) == 3 and len({t[-1] for t in suited}) == 1:
        ranks = sorted(int(t[:-1]) for t in suited)
        if ranks[1] == ranks[0] + 1 and ranks[2] == ranks[1] + 1:
            return {"type": "chi", "tiles": suited}
    return {"type": "meld", "tiles": tiles[:3]}


def split_rounds(events: list[RecordEvent]) -> list[list[RecordEvent]]:
    """Split events into rounds. A round runs from the first actor event after
    a deal/round_start block up to (and including) a win, or the next deal."""
    rounds: list[list[RecordEvent]] = []
    cur: list[RecordEvent] = []
    seen_action = False
    for e in events:
        if e.sub_cmd in ROUND_START_SUBS:
            if seen_action and cur:
                rounds.append(cur)
                cur = []
                seen_action = False
            cur.append(e)
            continue
        cur.append(e)
        if e.sub_cmd in (0x021A, 0x021B, 0x021F):
            seen_action = True
        if e.sub_cmd == 0x0220 and seen_action:  # win closes the round
            rounds.append(cur)
            cur = []
            seen_action = False
    if cur and seen_action:
        rounds.append(cur)
    return rounds


def extract_round(index: int, events: list[RecordEvent]) -> RoundFeatures:
    feats = {SELF: PlayerFeatures(SELF), OPPONENT: PlayerFeatures(OPPONENT)}
    start_seq = events[0].seq if events else -1
    for e in events:
        p = e.player
        if e.sub_cmd == 0x021B and p in feats:  # discard
            raw = e.body[1] if len(e.body) >= 2 else 0
            tile = e.tile_or_count.get("tile")
            feats[p].discard_raw.append(raw)
            if tile:
                feats[p].discards.append(tile)
            feats[p].discard_ts.append(e.ts)
        elif e.sub_cmd == 0x021A and p in feats:  # draw
            feats[p].draw_count += 1
            feats[p].draw_ts.append(e.ts)
        elif e.sub_cmd == 0x021F and p in feats:  # meld
            exposed = e.tile_or_count.get("exposed_tiles", [])
            feats[p].melds.append(_classify_meld(exposed))
        elif e.sub_cmd == 0x0216 and p in feats:  # hand_update
            cnt = e.tile_or_count.get("count")
            if cnt is not None:
                feats[p].hand_counts.append(int(cnt))
    return RoundFeatures(
        index=index,
        start_seq=start_seq,
        self_feat=feats[SELF],
        opp_feat=feats[OPPONENT],
        event_count=len(events),
    )


def extract_file(path: str) -> list[RoundFeatures]:
    events = parse_file(path)
    rounds = split_rounds(events)
    return [extract_round(i, r) for i, r in enumerate(rounds)]


def _dump_round(rf: RoundFeatures) -> None:
    opp = rf.opp_feat
    me = rf.self_feat
    print(f"-- round {rf.index} (events={rf.event_count}, start_seq={rf.start_seq}) --")
    print(f"   OPP   discards({len(opp.discards)}): {opp.discards}")
    print(f"   OPP   melds: {opp.melds}")
    print(f"   OPP   draw_count={opp.draw_count}  hand_counts={opp.hand_counts}")
    print(f"   OPP   act_gaps(s): {rf.opponent_act_gaps()}")
    print(f"   SELF  discards({len(me.discards)}): {me.discards}")
    print(f"   SELF  melds: {me.melds}")


def _main(argv: list[str]) -> None:
    if len(argv) < 2:
        print("usage: python n5_sidechannel.py <record.bin>")
        return
    rounds = extract_file(argv[1])
    print(f"== {len(rounds)} round(s) extracted ==\n")
    for rf in rounds:
        _dump_round(rf)
        print()


if __name__ == "__main__":
    _main(sys.argv)
