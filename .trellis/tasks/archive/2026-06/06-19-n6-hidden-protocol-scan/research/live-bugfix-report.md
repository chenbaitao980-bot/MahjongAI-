# N6 Fuzzer Live Bug Fix Report

- **Date**: 2026-06-20
- **Target file**: `.trellis/tasks/06-19-n6-hidden-protocol-scan/research/n6_fuzzer.py`
- **Trigger**: First live run hung after `Send error: [Errno 32] Broken pipe` — fuzzer kept spinning on a dead socket and never aborted; in addition, every high-score hit raised `TypeError: %d format: a real number is required, not list` from a malformed logger call.

---

## §1 Bug A — `on_frame` logger format string mismatch

### Root cause

Original (lines 269–271):

```python
if cls["score"] >= 5:
    logger.warning("⭐ HIGH-SCORE HIT: mt_in=%s st_in=%s -> wire_mt=%s score=%d notes=%s",
                   last, msg_type, cls["score"], cls["notes"])
```

Format string has **5 placeholders**: `mt_in=%s`, `st_in=%s`, `wire_mt=%s`, `score=%d`, `notes=%s`.
Only **4 arguments** are supplied: `last`, `msg_type`, `cls["score"]`, `cls["notes"]`.

The Python `%`-formatter pairs them positionally:

| Placeholder | Value bound | Type | Issue |
|---|---|---|---|
| `mt_in=%s` | `last` (tuple/None) | OK | semantically wrong — `last` is `(mt, st, tpl)` from `state["last_sent"]`, not just `mt_in` |
| `st_in=%s` | `msg_type` (int) | OK | semantically wrong — `msg_type` is the *received* wire msg_type, not the sent sub_type |
| `wire_mt=%s` | `cls["score"]` (int) | OK in `%s` | wrong slot |
| `score=%d` | `cls["notes"]` (list) | **TypeError** | `%d` requires a number; got `[]` |
| `notes=%s` | (missing) | TupleIndexError if reached | shadowed by the earlier TypeError |

The console log `Arguments: (None, 1, 5, [])` confirms exactly this binding: `last=None, msg_type=1, cls["score"]=5, cls["notes"]=[]`. The list `[]` collided with `%d`, raising `TypeError`.

### Fix

```python
if cls["score"] >= 5:
    last_sent = state["last_sent"]
    logger.warning(
        "HIGH-SCORE HIT: sent=%s wire_mt=%s score=%d notes=%s",
        last_sent, msg_type, cls["score"], cls["notes"],
    )
```

- 4 placeholders ↔ 4 arguments. Balanced.
- Types match: `last_sent` (tuple/None) → `%s`, `msg_type` (int) → `%s`, `cls["score"]` (int) → `%d`, `cls["notes"]` (list) → `%s`.
- Renamed `mt_in/st_in -> wire_mt` to the unambiguous `sent=<tuple> wire_mt=<int>` so logs stay readable.
- Dropped the `⭐` emoji per project memory `feedback_bat_ascii_only` / smart-quote guidance — log channel is `logger`, not `.bat`, so it would not crash, but ASCII-only output is more portable across `journalctl`/Windows console encodings.

### Audit of other logger calls

`grep -n logger\.(warning|info|error|debug)\(` over the whole file (25 hits). Hand-checked each multi-line and single-line call against its argument list:

- All single-placeholder calls match a single argument (e.g. line 103, 249, 264 …).
- Multi-line calls verified individually:
  - line 309 (the fixed Bug A site): 4↔4, OK
  - line 418 (new B-fix log): 4↔4 (`%d %s %s %s` ↔ `consecutive_rst, mt, st, tpl`), OK
  - line 517: 4↔4, OK
- No other mismatched logger calls.

---

## §2 Bug B — Broken pipe never triggers abort (fuzzer spins on dead socket)

### §2.1 Investigation: SRSClient connection-health surface

Read `remote/srs_spectator/client.py` (lines 133–165). Key findings:

**`_send_raw` is exception-swallowing**:
```python
def _send_raw(self, data: bytes) -> None:
    if self._sock:
        try:
            self._sock.sendall(data)
        except Exception as e:
            logger.error(f"Send error: {e}")
```
It is a synchronous `sendall` (no internal queue / thread), but every send exception is **caught and logged**, never re-raised. So `client._send_raw(frame)` in the fuzzer’s try/except can never raise → the existing `consecutive_rst += 1` path is dead code on this code path. This explains why the live console log shows hundreds of `Send error: Broken pipe` entries with no abort.

**Available health signals** (no public health-check method exists):

| Signal | Where set False / dead | Notes |
|---|---|---|
| `client._running` | recv thread on peer-close (`if not data:`) or recv exception; `disconnect()` | Mid-loop, `disconnect()` is only called in `finally` after the loop, so `_running==False` mid-loop unambiguously means recv-side detected death. |
| `client._sock` | `disconnect()` only (recv loop leaves it non-None) | Useful for disconnect-already-called check. |
| `client._on_disconnect` callback | Fired from recv thread after `_recv_loop` exits | Public hook — already supported by SRSClient (see `on_disconnect()` setter at line 82). Cleanest async signal. |

There is **no** public `is_alive()` / `is_connected()` method on SRSClient.

### §2.2 Health-check implementation

A new top-level helper `connection_alive(client) -> bool` was added (see `n6_fuzzer.py` lines 168–203). It probes three signals without modifying `client.py`:

1. `client._running is False` → recv thread saw a dead connection.
2. `client._sock is None` → `disconnect()` was already called.
3. `getsockopt(SOL_SOCKET, SO_ERROR) != 0` → kernel recorded `EPIPE` / `ECONNRESET` from the swallowed `sendall`. **This is the signal that catches a freshly-RST'd socket before the recv thread notices.**

It returns True only if all three look healthy. Wrapped in `(OSError, AttributeError)` so a half-closed socket that fails `getsockopt` is also treated as dead.

The helper is invoked at two points in `run_live`:

- **Outer loop head** (`for mt in msg_types:`, line 369–374): if dead, set abort_flag + `break`. Prevents iterating thousands of msg_types against a dead socket.
- **Right after each `_send_raw(frame)`** (line 416–428): if `connection_alive(client)` is False, increment `consecutive_rst`, log with `(consecutive_rst, mt, st, tpl)`, abort at 5. If alive, **reset** `consecutive_rst = 0` so a single transient blip doesn’t cause a slow-burn false-positive.

In addition, `client.on_disconnect(...)` is now wired up (line 335–340) to flip `abort_flag` from the recv thread the moment the connection drops. This is the primary async signal; the `connection_alive` probe is the synchronous backstop in case the recv thread lags.

### §2.3 Backstop: send-failure counter

The existing `try: client._send_raw(frame) except Exception` block is preserved (lines 410–414) — if a future SRSClient build does propagate exceptions, they still increment `consecutive_rst`. The new post-send `connection_alive()` check is the **active** path on the current SRSClient, where `_send_raw` swallows. Both paths feed the same `consecutive_rst` counter and the same 5-failure abort threshold.

A successful send (alive after) resets `consecutive_rst = 0`, so fuzzing through 5000 healthy sends does not falsely abort.

---

## §3 Verification

### §3.1 Dry-run regression (no network)

```
python n6_fuzzer.py --target lobby \
  --sessionid 0123456789abcdef0123456789abcdef --userid x \
  --range 1-50 \
  --skip-known .../xyid_closed_set.json \
  --out /tmp/_n6_regression.jsonl
```

Result: 50 IDs - 33 known in [1,50] = 17 unknown × 6 sub_types = **102 records**. JSONL well-formed. No traceback.

### §3.2 Bug A static check

`grep -n 'logger\.(warning|info|error|debug)\('` lists 25 calls. Each manually paired against its arguments. All placeholder counts and types now match. The fixed line 309–312 was specifically inspected.

### §3.3 Bug B static check + simulation

**Static**: confirmed `connection_alive()` helper present, called at outer loop head and post-send. `consecutive_rst` increment + 5-threshold abort path wired. `client.on_disconnect(...)` registration present.

**Simulation** (separate test harness, not committed): replaced `SRSClient` with a `FakeClient` that:
- completes handshake on connect
- has real `socketpair` for `getsockopt`
- after 3 sends, kills the peer half (closes `_b`) and flips `_running = False` — exactly mimicking the kernel state after a real Broken pipe RST
- `_send_raw` swallows like the real SRSClient

Run with `range(1000, 1020)` × `[100]` = 20 intended sends, kill_after=3:

```
=== handshake done; starting fuzz ===
send to dead connection detected (consecutive_rst=1) mt=1002 st=100 tpl=empty
connection dead at loop head (mt=1003) — aborting
=== fuzz finished sent=3 abort={'abort': True, 'reason': 'connection lost (peer RST/broken pipe)'} ===
ret=3
sent_records=3
=== PASS: connection death triggered abort early ===
```

Only 3 sends were issued before abort (3 healthy + immediate detection on the 3rd which triggered the kill). `ret=3` is the abort exit code. The fuzzer broke out of all three nested loops correctly. **Bug B is fixed.**

**Healthy-run no-false-positive simulation**: a `HealthyClient` that never RSTs ran through 10 msg_types × 1 sub_type = 10 sends, returned `ret=0`, `sent_records=10`, no abort. So the new health check does not produce false positives.

### §3.4 Ctrl+C cleanup (Dev-2 sanity)

The pre-existing `try/except KeyboardInterrupt: ... finally: client.disconnect()` block was untouched and still guards `disconnect()` against any cleanup-time exception. Ctrl+C path remains intact.

---

## §4 GO / NO-GO for re-running live

**GO.**

- Bug A fixed: format string and arguments are balanced and type-correct. High-score hits will log cleanly without `TypeError`.
- Bug B fixed: a peer RST / broken pipe is now detected within at most 1 outer-loop iteration (~6 sends across 6 sub_types) via the `connection_alive()` probe; `on_disconnect` callback is the secondary async signal; `consecutive_rst` reaches 5 and aborts cleanly with `ret=3`. Fuzzer no longer spins on a dead socket emitting Broken pipe forever.
- No false-positive abort observed in healthy-run simulation.
- `client.py` was **not modified** (per task constraint — investigation only).
- Dry-run regression passes; the `--live` path was not exercised in this report.

Recommended next live invocation: same CLI as the failed run, but expect prompt abort if the connection drops mid-fuzz instead of silent spin. Watch the console for `HIGH-SCORE HIT:` (clean format) and `connection dead at loop head` / `send to dead connection detected` (the new abort breadcrumbs).

---

## Files modified

- `.trellis/tasks/06-19-n6-hidden-protocol-scan/research/n6_fuzzer.py`
  - Added `import socket`
  - Added `connection_alive()` helper (lines 168–203)
  - Bug A: rewrote the `cls["score"] >= 5` logger.warning (lines 307–312)
  - Bug B: registered `client.on_disconnect(...)` callback (lines 333–340)
  - Bug B: added `connection_alive` check at outer loop head (lines 369–374)
  - Bug B: added post-send `connection_alive` probe + reset-on-success (lines 416–432)

## Files created

- `.trellis/tasks/06-19-n6-hidden-protocol-scan/research/live-bugfix-report.md` (this file)
