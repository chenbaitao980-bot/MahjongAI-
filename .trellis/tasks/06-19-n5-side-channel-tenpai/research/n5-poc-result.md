# N5 side-channel PoC result

Goal: from an existing offline replay record, recover the opponent (player=1)
**side-channel** -- event type / timing / frequency / body-size / counts -- and
infer the opponent's state (tenpai prob, danger tiles, melds, key tiles seen) as
a weak signal for the AI. Fully offline, zero network risk. H16 (server redacts
the opponent's 13 hand tiles to 0x3c / 0x72) is a confirmed hard wall, so N5 does
NOT try to recover the 13 tiles -- it mines what the protocol *cannot* hide.

Scripts (all run with `python`, repo root on sys.path):
- `n5_record_parser.py`   -- record -> event stream
- `n5_sidechannel.py`     -- event stream -> per-round, per-player features
- `n5_tenpai_infer.py`    -- opponent clear info -> weak tenpai/danger signal

---

## 1 record event parsing

Record format reverse-engineered and confirmed on both samples:

```
[ascii_header:32B][sub_cmd:2B LE][data_len:2B LE][body:data_len][trailer]
```

- The 32B `ascii_header` is all decimal digits: `'0000000000' + '<10-digit unix ts>' + '0112' + '00000000'`.
  The 10-digit field is a **real unix-second timestamp** -> gives per-event timing.
- Events are walked by anchoring on this all-digit header immediately before a
  known `sub_cmd`. This cleanly disambiguates the high-frequency `0x0206`
  stat_update spam (193-239 per game) without heuristic guessing.
- deal `0x0003` body offset @306 matched the documented anchor exactly.

Event histogram (player=0 self vs player=1 opponent):

| sample | events | discard (self/opp) | draw (self/opp) | meld (self/opp) | win |
|--------|--------|--------------------|------------------|------------------|-----|
| 26K    | 404    | 24 / 24            | 23 / 21          | 1 / 2            | 1   |
| 33K    | 492    | 29 / 29            | 28 / 28          | 1 / 3            | 1   |

The 26K histogram matches the task's reference figure (discard x48, draw x44,
meld x3, win x1, hand_update x3, baida x1). `player = body[0]` is reliable for
discard/draw/meld/hand_update/win.

---

## 2 opponent clear-info extraction (the core N5 value)

### opponent discard river -- REAL VALUES, in the clear (STRONG)

The server does **NOT** redact discards. Every opponent discard `0x021B`
decodes to a real tile via `stable.stable_tile_id`:

- 26K round 1 opp river (21 tiles): `3z 1z 7p 8p 6m 6p 3s 1p 4p 9p 6s 4z 9p 3p 7m 2s 2z 6p 9m 4s 9s`
- 33K round 0 opp river (17 tiles): `5z 6z 4z 8s 2z 1z 1z 8p 9p 7p 7p 2p 2p 6z 6z 2p 8p`
- 33K round 1 opp river (12 tiles): `6p 8s 2s 7m 4z 7s 6p 8m 5p 3p 6p 7s`

This alone is the full opponent discard pond -- exactly what genuine defensive
AI reads. No reconstruction needed.

### opponent melds -- REAL exposed tiles, in the clear (STRONG)

`0x021F` body `[player][..][count@3][exposed@4..][claimed]`. Exposed tiles
decode to real values:

- 26K opp: `chi 7s-8s-9s`, `chi 7m-8m-9m`
- 33K opp: `pon 6s`, `pon 9s`, `kong 6s` (all sou -> flush pressure)

So the opponent's **revealed** shape (3-9 tiles depending on melds) is fully
known. Combined with the discard river this is a large public-info surface.

### opponent draw / hand_update count -- event fires, value hidden (WEAK)

- draw `0x021A` body `[player][0x72 concealed][..]`: the drawn tile is masked
  with `0x72`, but the **draw event still fires** -> counting opponent draws =
  turn progress (26K opp draw_count=18-21, 33K=28).
- hand_update `0x0216` for player=1 carries a real `count` but masked tiles.

### inter-action timing (WEAK)

From the record's 10-digit ts, the gap between each opp draw and its discard:

- 26K round 1 gaps(s): `0 1 1 0 1 0 1 0 1 0 1 1 1 1 2 1 3 1` -> one 3s spike
- 33K round 1 gaps(s): `1 1 1 1 2 3 3 3 3` -> rising 3s deliberations late game

Record ts has 1-second granularity, so this is a coarse weak signal at best.

---

## 3 tenpai / danger inference

`n5_tenpai_infer.py` replays the opponent discard timeline turn by turn:

- **dangerous_tiles (STRONG)**: reuses `game/danger.py::calc_tile_danger`
  unchanged -- the SAME genuine-AI "read the discard pond + melds" routine the
  app already ships. Fed with the real opponent discards + real meld tiles +
  public visible tiles. No new heuristics invented for the danger half.
- **est_tenpai_prob (WEAK)**: a cheap public-info heuristic (turn depth + open
  meld count + single-suit flush pressure + late terminal/honor discards). It
  cannot see the 13 redacted tiles, so it is explicitly a weak estimate.

Reused `game/` modules: `game.danger.calc_tile_danger`, `game.danger.danger_level_str`,
`game.state.MeldGroup`, `game.tiles.suit_of` (and `tiles_to_ids` transitively).
None were modified.

Sample signal sequences:

- **26K round 1** (opp: 2 chi 789s/789m): tenpai climbs 28% -> 84% by turn 13 as
  the open melds + turn depth + late honor/terminal discards stack up. Danger
  ranks middle tiles (3m-7m, 3p-4p) at 30 -> 42.
- **33K round 1** (opp: 3 sou kongs): single-suit flush pressure fires
  immediately; danger ranks **sou** tiles 3s/4s/5s at 70 -> 82 (extreme) while
  off-suit tiles stay safe. tenpai 56% -> 92% by turn 12. This is the textbook
  win: the kongs are public, the suit lock is obvious, the AI is told "do NOT
  feed sou."

---

## 4 signal-strength assessment

| signal | source | strength | why |
|--------|--------|----------|-----|
| opponent discard river | `0x021B` body[1], real tile | **STRONG** | server never redacts discards; full pond available |
| opponent melds | `0x021F` exposed tiles, real | **STRONG** | chi/pon/kong tiles must be public to be valid; reveals suit lock / partial hand |
| danger-tile ranking | `game/danger.py` on above | **STRONG** | identical to shipped defensive AI; driven entirely by real public info |
| opponent draw count | `0x021A` event fires | WEAK | tile masked (0x72); only turn progress |
| opponent hand count | `0x0216` count | WEAK | size only, tiles masked |
| inter-action timing | record 10-digit ts | WEAK | 1-second granularity; noisy proxy for deliberation |
| est_tenpai_prob | public-info heuristic | WEAK | cannot see 13 redacted tiles (H16 wall); coarse estimate |

Practical AI value: the STRONG half is genuinely useful and is **not** a new
capability -- it is the standard "read the discard pond + melds" defense that
every mahjong AI already does, now confirmed reliably extractable from this
record/protocol. The WEAK half (tenpai %, timing) is a soft hint, fine to show
as a low-confidence advisory but never as ground truth.

Key verification (the N5 core claim): **opponent discards AND meld exposed tiles
ARE extractable as public real values** -- confirmed on both samples (24/24 and
29/29 discards decode, 2 + 3 melds decode to real tiles). The opponent's hidden
13 tiles remain unreachable (0x3c/0x72), as H16 predicted.

---

## 5 integration recommendation

### into `stable/tracker.py`

The tracker already converts `0x021B`/`0x021F` events into `BattleState`. N5 adds
no decoding -- it only asks the tracker to keep, per opponent:
- `opponent_discards: list[str]` (already trusted-clear from discard events)
- `opponent_melds: list[MeldGroup]` (already trusted-clear from meld events)
- `opponent_draw_count: int` (count `0x021A` for player!=self) -- new weak field
- optional `opponent_last_act_gap` if a timestamp source is available live

These map 1:1 to the existing `enemy_discards` / `enemy_melds` args of
`calc_tile_danger`, so the strong half needs zero new plumbing -- it likely
already flows. The only additions are the two weak fields.

### into `game/llm_advisor`

Inject a compact, clearly-labelled side-channel block into the prompt payload:

```
opponent_public:
  discards: [...real river...]
  melds: [chi 789s, ...]
  est_tenpai: 0.62        # WEAK / advisory only
  danger_top: [3s:82, 4s:82, 5s:82]   # STRONG (from game/danger.py)
```

Guidance for the prompt: treat `danger_top` as authoritative defense input;
treat `est_tenpai` as a low-confidence hint and never claim to know the
opponent's concealed tiles. This keeps the feature honest (matches the H16 wall)
while still upgrading defense quality.
