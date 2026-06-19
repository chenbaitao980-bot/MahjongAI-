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

  # LIVE (requires explicit --live + interactive confirmation)
  python n6_fuzzer.py ... --live
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import struct
import sys
import time
from pathlib import Path

# Project root for `from remote.srs_spectator.client import SRSClient` imports.
# Default to ECS layout; override via --project-root if running from local repo.
DEFAULT_PROJECT_ROOTS = [
    "/opt/mahjong-remote",
    str(Path(__file__).resolve().parents[3]),  # local repo root from this file
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("n6_fuzzer")

FLAG = 0x4001
HDR_LEN = 12

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


def classify_response(msg_type: int, payload: bytes, expected_msg_type: int) -> dict:
    """Return classification + score; see fuzz-strategy.md §3."""
    label = "unknown"
    score = 0
    notes: list[str] = []

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

    return {"label": label, "score": score, "notes": notes}


def confirm_live() -> bool:
    print("=" * 78)
    print("LIVE MODE: about to open network sockets and send packets to a real server.")
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


def run_live(args, msg_types: list[int], sub_types: list[int], out_path: Path):
    """Connect to server, fuzz, log responses. Requires SRSClient."""
    # Lazy import; only needed in --live mode
    for root in DEFAULT_PROJECT_ROOTS:
        if os.path.isdir(root) and root not in sys.path:
            sys.path.insert(0, root)
    if args.project_root:
        sys.path.insert(0, args.project_root)

    try:
        from remote.srs_spectator.client import SRSClient  # type: ignore
    except ImportError as e:
        logger.error("could not import SRSClient: %s", e)
        logger.error("Pass --project-root to point at the project root (containing remote/)")
        return 2

    if args.target == "lobby":
        host, port = args.host or "47.96.101.155", args.port or 5748
    elif args.target == "game":
        host, port = args.host or "47.96.0.227", args.port or 5045
    else:
        raise ValueError(f"unknown target: {args.target}")

    rate_sleep = 1.0 / max(args.rate, 0.1)

    # Counters for abort triggers
    consecutive_rst = 0
    popup_count = 0
    consecutive_silent = 0
    abort_flag = {"abort": False, "reason": ""}

    logged_responses: dict[tuple[int, int], list[dict]] = {}

    def on_frame(msg_type, payload):
        """Map response back to (msg_type, sub_type) — best-effort by recent send."""
        nonlocal popup_count
        # we cannot perfectly correlate; use last-sent (mt, st)
        last = state.get("last_sent")
        cls = classify_response(msg_type, payload, expected_msg_type=last[0] if last else -1)
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
        if msg_type == 101:
            popup_count += 1
            if popup_count >= 5:
                abort_flag["abort"] = True
                abort_flag["reason"] = "5 popup boxes — likely server abuse-block"
        if cls["score"] >= 5:
            logger.warning("⭐ HIGH-SCORE HIT: mt_in=%s st_in=%s -> wire_mt=%s score=%d notes=%s",
                           last, msg_type, cls["score"], cls["notes"])

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
            logger.warning("=== handshake done; starting fuzz ===")
        client.on_handshake_done(on_hs_done)

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
            for st in sub_types:
                if abort_flag["abort"]:
                    logger.error("ABORT: %s", abort_flag["reason"])
                    break
                for tpl in templates:
                    if abort_flag["abort"]:
                        break
                    body = build_body(tpl, askid, args.roomid)
                    # encrypt body if crypto available
                    try:
                        if client._crypto.key:
                            client._crypto.reset_cfb()
                            enc = client._crypto.encrypt_payload(body)
                        else:
                            enc = body
                    except Exception:
                        enc = body
                    frame = pack_frame_v6(mt, enc, sub_type=st, extra=args.appid)
                    state["last_sent"] = (mt, st, tpl)
                    rec = {
                        "ts": time.time(),
                        "direction": "send",
                        "msg_type": mt, "sub_type": st, "extra": args.appid,
                        "body_template": tpl,
                        "body_hex": body.hex(),
                        "wire_hex": frame.hex(),
                    }
                    with out_path.open("a", encoding="utf-8") as fp:
                        fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    try:
                        client._send_raw(frame)
                    except Exception as e:
                        logger.error("send raised: %s", e)
                        consecutive_rst += 1
                        if consecutive_rst >= 5:
                            abort_flag["abort"] = True
                            abort_flag["reason"] = "5 consecutive send failures (RST)"
                            break
                    sent += 1
                    askid += 1
                    time.sleep(rate_sleep)
                    # heartbeat injection every 100 frames
                    if sent % 100 == 0:
                        try:
                            hb_body = struct.pack("<I", 0)
                            if client._crypto.key:
                                client._crypto.reset_cfb()
                                hb_enc = client._crypto.encrypt_payload(hb_body)
                            else:
                                hb_enc = hb_body
                            hb = pack_frame_v6(306, hb_enc, sub_type=100, extra=0)
                            client._send_raw(hb)
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
        # Dev-2: always attempt to close the client on every exit path
        # (normal return, abort, Ctrl+C). Guarded so a close() failure
        # never masks the real outcome.
        if client is not None:
            try:
                client.close()
            except Exception as e:
                logger.warning("client.close() raised during cleanup: %s", e)



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

    if not args.live:
        logger.warning("=== DRY-RUN MODE === (use --live to actually send)")
        run_dry_run(args, msg_types, sub_types, out_path)
        return 0

    # LIVE MODE — require interactive confirmation
    if args.sessionid == "DRY_RUN_DUMMY_SID":
        logger.error("LIVE mode requires real --sessionid (副号 32-hex)")
        return 4
    if not confirm_live():
        logger.error("LIVE mode aborted (user did not confirm)")
        return 4
    return run_live(args, msg_types, sub_types, out_path)


if __name__ == "__main__":
    sys.exit(main())
