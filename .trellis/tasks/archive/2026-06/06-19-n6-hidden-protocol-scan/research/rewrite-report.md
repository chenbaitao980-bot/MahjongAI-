# N6 Fuzzer Rewrite Report (camouflage + calibration)

- **Date**: 2026-06-20
- **Scope**: rewrite `research/n6_fuzzer.py` to defeat the live attempt-2 hard wall
  (server FINs after ~6 consecutive unknown msg_types on a single connection).
- **Constraints honored**: this round is dry-run only (no `--live`); `client.py`
  untouched; no git commit; pure-ASCII logs (no emoji); existing correct logic
  (Dev-2 try/finally disconnect, `connection_alive()` probe, on_disconnect abort,
  dry-run default + `confirm_live()`, 6 sub_types default) preserved.

---

## §1 classifier false-positive fix

### Cause

In attempt 2 the server pushes four frames immediately after handshake —
`mt=1` (keepalive-ack), `mt=4` (HandshakeRsp), `mt=6` (PlayerData), `mt=24`
(RespPlusData; `24` is even *inside* the closed set). The old
`classify_response()` had no notion of the closed set, handshake phase, or
send-correlation, so any recv whose `wire_msg_type` differed from the
`expected_msg_type` fell into the `else` branch -> `label=translated, score=5`,
firing the HIGH-SCORE HIT logger four times on pure handshake noise (see
`live-attempt-2-console.log` lines 13/16/20/25).

### Fix

`classify_response()` now takes three extra params and forces `score=0` (with an
explanatory label) when any guard fails:

1. `handshake_done=False` -> `label=handshake-push` (recv during handshake phase
   is a server push, never a routing discovery).
2. `msg_type in skip_set` -> `label=known-protocol` (a known closed-set reply
   such as 24/RespPlusData is a normal reply, not a hidden protocol).
3. `correlated_send is None` -> `label=uncorrelated` (cannot tie the recv to an
   unknown we just sent).

Only post-handshake, not-in-closed-set, correlated recv frames reach the real
scoring path. The closed set is passed in from the already-loaded
`load_skip_set()` result (reused, not re-parsed). `on_frame` also gates the
popup-abort counter on `handshake_done` so handshake pushes never count.

A new strong signal was added: 13 consecutive small ints (`0 < b < 0x40`) in the
payload head (+4) — the suspected hand-instance-id pattern from
`stable/protocol.py` deal frames.

### Unit verification (in-conversation, no network)

```
mt=  1 known-after-hs        -> score=0 label=known-protocol   OK
mt=  4 known-after-hs        -> score=0 label=known-protocol   OK
mt=  6 known-after-hs        -> score=0 label=known-protocol   OK
mt= 24 known-after-hs        -> score=0 label=known-protocol   OK
pre-handshake unknown 9999   -> score=0 label=handshake-push   OK
uncorrelated unknown         -> score=0 label=uncorrelated     OK
real unknown 200B (post-hs)  -> score=8 label=translated       OK (>0)
zlib-magic 122B (post-hs)    -> score=13 notes=[payload-large,zlib-magic] OK
```

All four attempt-2 handshake frames now score 0; a genuine post-handshake
correlated unknown still scores > 0.

---

## §2 calibration mode `--calibrate`

### Design (Q1-Q4)

Goal: scientifically MEASURE the wall, not guess. Hard cap
`CALIBRATE_MAX_FRAMES = 50` total live frames; each step `sleep >= 0.5-1.0s`;
on FIN it stops immediately, so calibration itself cannot trigger a ban. Picks
an unknown msg_type `9991` (auto-bumped if it collides with the closed set),
sub_type `100` (the most-routed IM bus).

| Q | Phase | How it is measured |
|---|---|---|
| Q1 | `Q1-baseline` | fresh session, send 20 known keepalives 1s apart, count how many survive. `Q1_baseline_stable = survived >= 10`. Confirms a quiet known-traffic connection does NOT get dropped (isolates the wall to *unknowns*). |
| Q3 | `Q3-consecutive` | fresh session, send up to 12 consecutive unknowns (no keepalive), 1s apart; record `Q3_consecutive_to_fin` = number sent when `connection_alive()` first reports dead. Reproduces attempt-2's ~6. |
| Q2 | `Q2Q4-alternate` | fresh session, repeat `(--keepalive-every known keepalives + 1 unknown)` up to 10 rounds; record `Q2_alternation_rounds` survived. |
| Q4 | derived | `Q4_keepalive_resets = (Q2_rounds > Q3_threshold)`. If the alternation survives more unknowns than the raw consecutive threshold, the interleaved keepalive resets the server's consecutive-unknown counter. `None` (inconclusive) if Q3 never hit FIN. |

Liveness is detected with the existing `connection_alive()` probe
(`_running` flag + `_sock is None` + `SO_ERROR`) plus the `on_disconnect`
callback — no `client.py` change. Each phase uses its own fresh session so a FIN
in one phase does not contaminate the next.

### Frame budget (<= 50, safe)

- Q1: <= 20 keepalives
- Q3: <= 12 unknowns
- Q2/Q4: 10 rounds x (keepalive_every + 1) — with default `keepalive_every=2`
  that is up to 30, but the global `CALIBRATE_MAX_FRAMES=50` cap (checked via
  `budget_ok()` before every send) and early-FIN exit keep the real total well
  under 50. Worst case is bounded at exactly 50.

Dry-run (`--calibrate` without `--live`) prints the plan JSON only; no socket.

---

## §3 camouflage scan mode `--camouflage`

### Parameters (no hardcoded wall threshold)

| Flag | Default | Meaning |
|---|---|---|
| `--unknown-per-conn N` | 3 | max unknown frames per connection before reconnect (conservative vs attempt-2 wall ~6; operator raises this from the calibration result). |
| `--keepalive-every K` | 2 | known keepalives sent before each unknown (camouflage padding / resets the counter if Q4 confirms reset). |
| `--reconn-cooldown S` | 3.0 | seconds slept between reconnects. |
| `--max-reconns M` | 50 | hard upper bound on reconnect count (anti-runaway). |

### Reconnect loop logic

1. Build a flat queue of all `(mt, sub)` unknowns (range minus closed set x sub_types).
2. Open a fresh `SRSClient`, wait for handshake.
3. Per connection batch: while `batch < unknown_per_conn` and queue not empty and
   `connection_alive()`: send `keepalive_every` keepalives (padding), then one
   unknown (empty body), wait a ~1.5s response window, advance the queue index.
4. Gracefully `disconnect()`, `sleep(reconn_cooldown)`, reconnect, resume from the
   same queue index (no re-scanning).
5. Stop when the queue is exhausted, `--max-reconns` is hit, or abort fires
   (5 popups, or `on_disconnect`/`connection_alive` mid-batch).

`on_disconnect` here is benign (expected at each batch end) — it just marks the
session dead so the inner loop exits and we reconnect.

### Full-scan time estimate (dry-run computed)

With `--unknown-per-conn 3 --keepalive-every 2 --reconn-cooldown 3`:

| Range x sub_types | n_unknowns | reconns_needed | est_hours |
|---|---|---|---|
| `1-200 x {100,84}` (test water) | 326 | 109 | 0.44 |
| `1-5000 x 6 sub_types` (full core) | 29070 | 9690 | ~39 |

Per-connection wall-clock model: `1s handshake + unknown_per_conn x (keepalive_every x 1s + 1.5s window) + cooldown`. At default params one connection takes ~13.5s and clears 3 unknowns.

**Implication**: the full 29070-unknown core scan needs ~9690 reconnects /
~39 h at conservative params — far over the default `--max-reconns 50` (which
only clears 150 unknowns). The full scan must be chunked over many sessions/days
(per go-live checklist `<= 100k frames/day`), or `--unknown-per-conn` raised
toward the measured wall to cut reconnect count. This is exactly why calibration
must run first.

---

## §4 verification

All four required checks pass, all offline (no `--live`, no network):

1. **dry-run regression** — `--range 1-30` emits 18 records (3 unknown x 6 sub),
   exit 0, no traceback.
2. **classifier unit test** — see §1 (mt 1/4/6/24 -> 0; real unknown -> >0).
3. **calibrate/camouflage dry-run** — both print the plan JSON only; confirmed no
   socket opened (no SRSClient import attempted; exit 0).
4. **reconnect mock** — monkeypatched fake `SRSClient` that FINs after 3 unknowns:
   - 10 unknowns scanned over exactly 4 reconnects (3+3+3+1), all 10 unknown
     sends logged, queue resumed correctly across reconnects.
   - with `--max-reconns 2`: stops after 2 connections (6 unknowns), queue
     correctly reported not-exhausted.

---

## §5 go-live recommendations

1. **Run `--calibrate` first** (`--live`, <= 50 frames). Record Q1-Q4:
   - Q1 confirms a quiet connection survives (sanity).
   - Q3 gives the true consecutive-unknown FIN threshold (attempt-2 saw ~6).
   - Q4 says whether interleaved keepalives reset the counter.
2. **Set `--unknown-per-conn` from the calibration result.** Use a margin below
   the Q3 threshold (e.g. threshold 6 -> use 3-4). If Q4 says keepalives reset the
   counter, lean on `--keepalive-every` to extend per-conn yield instead of more
   reconnects.
3. **Run `--camouflage` chunked.** Do NOT attempt the full `1-5000 x 6` in one
   go (~39 h / ~9690 reconnects). Start small: `--range 1-200` water test, watch
   for HIGH-SCORE HITs and abort signals, then widen.
4. **Risk**: high-frequency reconnects are *more* conspicuous to per-account /
   per-IP anomaly detection than a single long-lived connection — a reconnect
   storm can itself trigger an IP/account flag. Recommendation: water-test
   `--range 1-200` with generous `--reconn-cooldown` (>= 3s, consider 10s+), keep
   `--max-reconns` low per session, and spread the full scan across days with the
   secondary account + separate ECS egress per the go-live checklist.
