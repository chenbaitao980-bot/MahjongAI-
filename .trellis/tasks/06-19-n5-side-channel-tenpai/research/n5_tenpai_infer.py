"""N5 tenpai / danger inference PoC.

Consumes the opponent's CLEAR side-channel (discards + exposed meld tiles) and,
turn by turn, emits a weak-signal estimate:

  - est_tenpai_prob : a cheap heuristic from public info only (turn depth,
                      meld count, late-game honor/terminal discards). This is a
                      WEAK estimate -- we deliberately do NOT claim precision.
  - dangerous_tiles : reuses game.danger.calc_tile_danger (the SAME genuine-AI
                      "read the discard pond" routine) to rank which of our
                      candidate tiles are dangerous to feed the opponent.

The danger half is STRONG (driven by real opponent discards/melds). The tenpai
half is WEAK (public info cannot see the 13 redacted tiles -- H16 hard wall).

Pure offline. Reuses game.danger / game.state / game.tiles + n5_sidechannel.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from game.danger import calc_tile_danger, danger_level_str  # noqa: E402
from game.state import MeldGroup  # noqa: E402
from game.tiles import suit_of  # noqa: E402
from n5_sidechannel import RoundFeatures, extract_file  # noqa: E402

ALL_TILES = (
    [f"{r}m" for r in range(1, 10)]
    + [f"{r}p" for r in range(1, 10)]
    + [f"{r}s" for r in range(1, 10)]
    + [f"{r}z" for r in range(1, 8)]
)


@dataclass
class TurnSignal:
    turn: int
    opponent_discards: list[str]
    opponent_melds: list[str]
    est_tenpai_prob: float
    tenpai_reasons: list[str]
    dangerous_tiles: list[tuple[str, int]]  # (tile, danger)


def _estimate_tenpai_prob(turn: int, melds: list[dict[str, Any]],
                          discards: list[str]) -> tuple[float, list[str]]:
    """Public-info-only weak tenpai estimate. Returns (prob, reasons)."""
    prob = 0.05
    reasons: list[str] = []

    # turn depth: deeper turn -> more likely tenpai
    if turn >= 6:
        prob += min(0.06 * (turn - 5), 0.45)
        reasons.append(f"turn>={turn} depth")

    # melds: each open meld is a committed step toward a hand
    if melds:
        prob += 0.12 * len(melds)
        reasons.append(f"{len(melds)} open meld(s)")
        # all melds same suit -> flush pressure, higher tenpai pressure
        suits = {t[-1] for m in melds for t in m.get("tiles", []) if t[-1] != "z"}
        if len(suits) == 1 and len(melds) >= 2:
            prob += 0.15
            reasons.append("single-suit melds (flush pressure)")

    # late-game honor/terminal discards signal a settled shape
    if turn >= 8 and discards:
        late = discards[-4:]
        terminal_honor = sum(
            1 for t in late
            if t[-1] == "z" or (t[-1] != "z" and t[:-1] in ("1", "9"))
        )
        if terminal_honor >= 2:
            prob += 0.10
            reasons.append("late terminal/honor discards (settled shape)")

    return min(prob, 0.92), reasons


def _build_melds(meld_dicts: list[dict[str, Any]]) -> list[MeldGroup]:
    out: list[MeldGroup] = []
    for m in meld_dicts:
        mt = m.get("type", "meld")
        mt = "peng" if mt == "pon" else mt  # danger.py treats any meld via tiles
        out.append(MeldGroup(meld_type=mt, tiles=list(m.get("tiles", []))))
    return out


def infer_round(rf: RoundFeatures, top_k: int = 8) -> list[TurnSignal]:
    """Replay the opponent discard timeline; emit a weak signal per opp discard."""
    opp = rf.opp_feat
    signals: list[TurnSignal] = []

    # opponent discards are time-ordered; treat each as one turn tick
    seen_discards: list[str] = []
    meld_tiles_flat = [t for m in opp.melds for t in m.get("tiles", [])]

    for turn, tile in enumerate(opp.discards, start=1):
        seen_discards.append(tile)
        melds = _build_melds(opp.melds)
        prob, reasons = _estimate_tenpai_prob(turn, opp.melds, seen_discards)

        # self_visible = everything publicly seen (both rivers + opp melds)
        self_visible = list(seen_discards) + meld_tiles_flat + list(rf.self_feat.discards[:turn])
        remaining = max(0, 70 - turn * 2)

        danger_ranked: list[tuple[str, int]] = []
        for cand in ALL_TILES:
            d = calc_tile_danger(
                tile=cand,
                enemy_discards=seen_discards,
                enemy_melds=melds,
                self_visible=self_visible,
                remaining_tiles=remaining,
                turn=turn,
            )
            danger_ranked.append((cand, d))
        danger_ranked.sort(key=lambda x: x[1], reverse=True)

        signals.append(
            TurnSignal(
                turn=turn,
                opponent_discards=list(seen_discards),
                opponent_melds=[f"{m['type']}:{'-'.join(m['tiles'])}" for m in opp.melds],
                est_tenpai_prob=round(prob, 3),
                tenpai_reasons=reasons,
                dangerous_tiles=danger_ranked[:top_k],
            )
        )
    return signals


def _dump_round(rf: RoundFeatures, signals: list[TurnSignal]) -> None:
    print(f"-- round {rf.index}: {len(signals)} opponent-turn signal(s) --")
    for s in signals:
        top = ", ".join(f"{t}({d})" for t, d in s.dangerous_tiles[:5])
        prob_pct = int(s.est_tenpai_prob * 100)
        print(f"   turn {s.turn:2d} | tenpai~{prob_pct:3d}% | last_disc={s.opponent_discards[-1]:>3s}"
              f" | melds={s.opponent_melds}")
        print(f"            danger-top5: {top}")
        if s.tenpai_reasons:
            print(f"            why: {'; '.join(s.tenpai_reasons)}")


def _main(argv: list[str]) -> None:
    if len(argv) < 2:
        print("usage: python n5_tenpai_infer.py <record.bin>")
        return
    rounds = extract_file(argv[1])
    print(f"== {len(rounds)} round(s) ==\n")
    for rf in rounds:
        signals = infer_round(rf)
        _dump_round(rf, signals)
        print()


if __name__ == "__main__":
    _main(sys.argv)
