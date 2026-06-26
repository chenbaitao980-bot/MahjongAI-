"""
test_account_kick.py — Auto experiment: does phone reconnect kick ECS?

Uses the EXISTING infrastructure:
  - capture_credentials.py logic to grab sessionid + block phone + RST
  - ECS cloud_player (on 8.136.37.136) to hold the connection
  - PC firewall only affects LOCAL traffic, ECS is on a CLOUD server

Flow:
  1. Npcap capture -> extract sessionid
  2. Upload sessionid to ECS relay (/api/creds)
  3. Block phone via firewall (ECS is on cloud, unaffected!)
  4. Wait for server timeout -> phone drops
  5. Start ECS cloud_player (/api/start-player)
  6. Wait for ECS to confirm frames
  7. Unblock phone -> phone reconnects
  8. Monitor ECS for 90s -> does phone's reconnect kick ECS?

Usage:
    python scripts/test_account_kick.py

Phone must be on PC hotspot, in a game.
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import subprocess
import sys
import time
import threading

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, ".."))
for _p in (_ROOT,):
    if _p not in sys.path:
        sys.path.insert(0, _p)

CREDS_PATH = os.path.join(_ROOT, "data", "cloud_credentials.json")
_GAME_SERVER = "47.96.0.227"
_GAME_PORT = 7777
_FW_RULE = "MahjongBlockPhone"
_ECS_RELAY = "http://8.136.37.136:8003"
_API_TOKEN = "cloudmode2026"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def _ts() -> str:
    return datetime.datetime.now().strftime("[%H:%M:%S]")


def _print(msg: str) -> None:
    print(f"{_ts()} {msg}", flush=True)


def _block_phone() -> bool:
    _unblock()
    try:
        subprocess.run([
            "netsh", "advfirewall", "firewall", "add", "rule",
            f"name={_FW_RULE}", "dir=out", "action=block",
            f"remoteip={_GAME_SERVER}", f"remoteport={_GAME_PORT}",
            "protocol=TCP", "enable=yes",
        ], check=True, capture_output=True)
        return True
    except Exception:
        return False


def _unblock() -> None:
    try:
        subprocess.run([
            "netsh", "advfirewall", "firewall", "delete", "rule",
            f"name={_FW_RULE}",
        ], capture_output=True)
    except Exception:
        pass


def _ecs_api(endpoint: str, data: dict | None = None) -> dict | None:
    """Call ECS relay API."""
    import requests
    try:
        url = f"{_ECS_RELAY}{endpoint}"
        if data:
            resp = requests.post(url, json=data, timeout=10)
        else:
            resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        _print(f"  ECS API {endpoint} returned {resp.status_code}: {resp.text[:80]}")
        return None
    except Exception as exc:
        _print(f"  ECS API {endpoint} failed: {exc}")
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-capture", action="store_true")
    parser.add_argument("--relay", default=_ECS_RELAY)
    args = parser.parse_args()
    relay = args.relay

    _print("=" * 60)
    _print("EXPERIMENT: Does phone reconnect kick ECS? (cloud)")
    _print("=" * 60)
    _print("")
    _print("  Key: ECS runs on CLOUD server, firewall only blocks phone!")
    print()

    # ── Phase 1: Get sessionid ──────────────────────────────────────
    sessionid = ""
    identify = ""

    if args.skip_capture and os.path.isfile(CREDS_PATH):
        with open(CREDS_PATH, "r", encoding="utf-8") as f:
            creds = json.load(f)
        sessionid = creds.get("srs_sessionid", "")
        identify = creds.get("identify", "")
        _print(f"  Using existing sessionid: {sessionid[:8]}...{sessionid[-4:]}")
    else:
        _print("PHASE 1: Capturing sessionid (phone on hotspot, in game)")
        print()

        from stable.protocol import MJProtocol, GAME_SERVER_PORT
        from remote.extractor.capture import NpcapCaptureAdapter
        from remote.extractor.token_extractor import SRSSessionExtractor

        protocol = MJProtocol(server_port=GAME_SERVER_PORT)
        srs_result = {}
        srs_done = threading.Event()

        def _on_sid(sid: bytes):
            srs_result["srs_sessionid"] = sid.hex()
            srs_result["identify"] = srs_ext.identify.hex() if srs_ext.identify else ""
            _print(f"  Got sessionid: {sid.hex()[:8]}...{sid.hex()[-4:]}")
            srs_done.set()

        srs_ext = SRSSessionExtractor(on_sessionid=_on_sid)

        def _on_pkt(pkt):
            for msg in protocol.process_packet(pkt):
                srs_ext.feed(msg)

        adapter = NpcapCaptureAdapter(port=GAME_SERVER_PORT)
        _print("  Npcap capture started...")
        threading.Thread(target=adapter.run, args=(_on_pkt,), daemon=True).start()

        if not srs_done.wait(timeout=120):
            adapter.stop()
            _print("  Timeout. Use --skip-capture or restart game app.")
            sys.exit(1)

        # Wait for TCP state too
        tcp_state = None
        deadline = time.monotonic() + 5
        while tcp_state is None and time.monotonic() < deadline:
            tcp_state = adapter.get_tcp_state()
            time.sleep(0.5)

        adapter.stop()
        sessionid = srs_result["srs_sessionid"]
        identify = srs_result.get("identify", "")

        # Save
        os.makedirs(os.path.dirname(CREDS_PATH), exist_ok=True)
        with open(CREDS_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "srs_sessionid": sessionid,
                "identify": identify,
                "captured_at": datetime.datetime.now(datetime.UTC).isoformat(),
            }, f, indent=2)

        # Inject RST (best effort - may not reach server due to NAT)
        if tcp_state:
            try:
                from remote.extractor.rst_injector import inject_rst
                inject_rst(
                    phone_ip=tcp_state["phone_ip"],
                    phone_port=tcp_state["phone_port"],
                    phone_seq=tcp_state["phone_seq"],
                )
                _print("  RST injected (best effort)")
            except Exception:
                pass

    if not sessionid:
        _print("[ERROR] No sessionid")
        sys.exit(1)
    print()

    # ── Phase 2: Upload creds to ECS + block phone ──────────────────
    _print("PHASE 2: Upload credentials to ECS + block phone")

    # Upload to ECS
    creds_payload = {
        "srs_sessionid": sessionid,
        "identify": identify,
        "api_token": _API_TOKEN,
        "captured_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    result = _ecs_api("/api/creds", creds_payload)
    if result:
        _print("  Credentials uploaded to ECS relay")
    else:
        _print("  [WARN] ECS upload failed, continuing anyway...")

    # Block phone (ECS is on cloud server, completely unaffected!)
    blocked = _block_phone()
    if blocked:
        _print("  Firewall: phone->server BLOCKED (ECS on cloud, unaffected)")
    else:
        _print("  [WARN] Firewall failed. Manually disconnect phone WiFi!")

    _print("  Waiting 8s for server to drop phone's connection...")
    time.sleep(8)
    print()

    # ── Phase 3: Start ECS cloud_player ──────────────────────────────
    _print("PHASE 3: Start ECS cloud_player")

    result = _ecs_api("/api/start-player", {"api_token": _API_TOKEN})
    if result:
        _print("  Cloud player started on ECS")
    else:
        _print("  [WARN] start-player failed, ECS may auto-start from /api/creds")

    _print("  Waiting 10s for ECS to connect and receive frames...")
    time.sleep(10)

    # Check ECS player status
    status = _ecs_api("/api/player-status?token=" + _API_TOKEN)
    if status:
        _print(f"  ECS player status: {json.dumps(status)}")
        if status.get("active"):
            _print("  ECS player is ACTIVE and receiving frames!")
        else:
            _print("  ECS player is NOT active yet. Waiting more...")
            time.sleep(10)
            status = _ecs_api("/api/player-status?token=" + _API_TOKEN)
            if status:
                _print(f"  ECS player status: {json.dumps(status)}")
    print()

    # ── Phase 4: Unblock phone ──────────────────────────────────────
    _print("=" * 60)
    _print("PHASE 4: Unblock phone -> phone reconnects")
    _print("=" * 60)
    _print("")
    _print("  Removing firewall. Phone should auto-reconnect now.")
    _print("  (If not, switch phone WiFi off/on or re-open game)")
    print()

    _unblock()
    _print("  Firewall REMOVED.")
    print()

    # ── Phase 5: Monitor ECS ────────────────────────────────────────
    _print("PHASE 5: Monitoring ECS for 90s... (Ctrl+C to abort)")
    _print(f"  Check browser: {relay}/?token={_API_TOKEN}")
    print()

    alive_start = time.monotonic()
    was_active = False
    last_status_sec = -1

    try:
        while True:
            elapsed = time.monotonic() - alive_start
            if elapsed >= 90:
                break

            # Poll ECS status every 5 seconds
            status_sec = int(elapsed) // 5 * 5
            if status_sec != last_status_sec and status_sec >= 0:
                last_status_sec = status_sec
                status = _ecs_api("/api/player-status?token=" + _API_TOKEN)
                if status:
                    active = status.get("active", False)
                    mode = status.get("mode", "?")
                    if active:
                        was_active = True
                        _print(f"  [{elapsed:5.0f}s] ECS ALIVE | {json.dumps(status)}")
                    else:
                        if was_active:
                            _print(f"  [{elapsed:5.0f}s] ECS KICKED! | {json.dumps(status)}")
                            break
                        else:
                            _print(f"  [{elapsed:5.0f}s] ECS inactive | {json.dumps(status)}")
                else:
                    _print(f"  [{elapsed:5.0f}s] ECS unreachable")

            time.sleep(2)
    except KeyboardInterrupt:
        print()
        _print("Aborted by user.")

    print()
    total = time.monotonic() - alive_start

    # Final status check
    final = _ecs_api("/api/player-status?token=" + _API_TOKEN)
    final_active = final.get("active", False) if final else False

    # Stop ECS player
    _ecs_api("/api/stop-player", {"api_token": _API_TOKEN})

    # ── Result ──────────────────────────────────────────────────────
    if final_active:
        _print("=" * 60)
        _print(f"RESULT: ECS SURVIVED 90s!")
        _print("=" * 60)
        _print("")
        _print("  Phone reconnected but ECS was NOT kicked!")
        _print("  -> Simple dual-connect viable!")
        _print("  -> No TCP proxy needed!")
    elif was_active:
        _print("=" * 60)
        _print(f"RESULT: ECS WAS KICKED after ~{total:.0f}s")
        _print("=" * 60)
        _print("")
        _print("  Phone's reconnect kicked ECS.")
        _print("  -> Must use TCP proxy (方案 A)")
    else:
        _print("=" * 60)
        _print("RESULT: Inconclusive (ECS never became active)")
        _print("=" * 60)
        _print("")
        _print("  ECS cloud_player may have failed to connect.")
        _print("  Check ECS logs: ssh root@8.136.37.136 'journalctl -u mjx -n 50'")

    print()
    _print("Experiment complete.")


if __name__ == "__main__":
    main()
