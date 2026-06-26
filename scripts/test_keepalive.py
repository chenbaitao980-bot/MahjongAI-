"""假设B验证：SRS 连接保活测试

连接游戏服务器，完成握手后持续发心跳，验证 srs_sessionid 是否一直有效。

用法:
    python scripts/test_keepalive.py [--sessionid HEX] [--hours 24]

如果不传 --sessionid，从 scripts/_srs_capture.json 或 remote/relay/config.yaml 读取。

测试通过标准：
  - 运行 N 小时后 connection 仍然 alive（recv 线程未退出）
  - 心跳收到服务器响应（mgid=24, sub_type=0）
  - 如果中途断线，记录断线时间点
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml

from remote.srs_spectator.client import SRSClient, HEARTBEAT_INTERVAL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_credentials(sessionid_override: str = "") -> dict:
    """Load credentials from config or capture file."""
    cred = {
        "srs_sessionid": "",
        "auth_token_12b": "",
        "handshake_blob": "",
        "userid": "newpt1084306678",
        "host": "47.96.0.227",
        "port": 7777,
    }

    # Try _srs_capture.json first (most fresh)
    cap = REPO_ROOT / "scripts" / "_srs_capture.json"
    if cap.is_file():
        rec = json.loads(cap.read_text(encoding="utf-8"))
        cred["srs_sessionid"] = rec.get("pwd", "")
        logger.info(f"[cred] loaded from _srs_capture.json: pwd={cred['srs_sessionid'][:16]}...")

    # Try relay config
    cfg_path = REPO_ROOT / "remote" / "relay" / "config.yaml"
    if cfg_path.is_file():
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        if not cred["srs_sessionid"] and cfg.get("srs_sessionid"):
            cred["srs_sessionid"] = cfg["srs_sessionid"]
        cred["auth_token_12b"] = cfg.get("auth_token_12b", "")
        cred["handshake_blob"] = cfg.get("handshake_blob", "")
        host = cfg.get("game_server_ip")
        port = cfg.get("game_server_port")
        if host:
            cred["host"] = host
        if port:
            cred["port"] = int(port)

    # CLI override
    if sessionid_override:
        cred["srs_sessionid"] = sessionid_override

    return cred


def main() -> int:
    parser = argparse.ArgumentParser(description="SRS keepalive test (Hypothesis B)")
    parser.add_argument("--sessionid", default="", help="srs_sessionid hex (16B=32hex chars)")
    parser.add_argument("--hours", type=float, default=2.0, help="run for N hours (default 2)")
    parser.add_argument("--heartbeat", type=int, default=HEARTBEAT_INTERVAL,
                        help=f"heartbeat interval seconds (default {HEARTBEAT_INTERVAL})")
    args = parser.parse_args()

    cred = load_credentials(args.sessionid)

    if not cred["srs_sessionid"]:
        print("ERROR: no srs_sessionid found.")
        print("  Option 1: run extractor with hotspot mode first (updates config.yaml)")
        print("  Option 2: pass --sessionid <32hex>")
        return 1

    if not cred["auth_token_12b"]:
        print("WARNING: auth_token_12b not found, using empty string")

    print(f"\n{'='*60}")
    print(f"SRS 保活测试 — 假设B验证")
    print(f"  服务器: {cred['host']}:{cred['port']}")
    print(f"  srs_sessionid: {cred['srs_sessionid'][:16]}...")
    print(f"  心跳间隔: {args.heartbeat}s")
    print(f"  计划运行: {args.hours}h")
    print(f"{'='*60}\n")

    # Override heartbeat interval for this test
    import remote.srs_spectator.client as _client_mod
    _client_mod.HEARTBEAT_INTERVAL = args.heartbeat

    events: list[dict] = []
    disconnect_count = [0]
    heartbeat_count = [0]

    client = SRSClient(
        host=cred["host"],
        port=cred["port"],
        auth_token=cred["auth_token_12b"],
        handshake_blob=cred["handshake_blob"],
        srs_sessionid=cred["srs_sessionid"],
    )

    def on_handshake():
        msg = f"[{elapsed()}] Handshake complete — connection alive"
        print(msg)
        events.append({"t": time.time(), "event": "handshake_done"})

    def on_disconnect():
        disconnect_count[0] += 1
        msg = f"[{elapsed()}] DISCONNECT #{disconnect_count[0]}"
        print(msg)
        events.append({"t": time.time(), "event": "disconnect", "count": disconnect_count[0]})

    def on_frame(msg_type, payload):
        # Track heartbeat responses (msgid=24, sub_type=0)
        if msg_type == 24:
            heartbeat_count[0] += 1
            if heartbeat_count[0] % 1 == 0:
                print(f"[{elapsed()}] ← RespPlusData (heartbeat ack #{heartbeat_count[0]}, {len(payload)}B)")
            events.append({"t": time.time(), "event": "heartbeat_ack", "payload_len": len(payload)})

    start_t = time.time()

    def elapsed():
        s = int(time.time() - start_t)
        return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"

    client.on_handshake_done(on_handshake)
    client.on_disconnect(on_disconnect)
    client.on_frame(on_frame)

    print(f"[{elapsed()}] Connecting to {cred['host']}:{cred['port']} ...")
    ok = client.connect()
    if not ok:
        print("ERROR: connect() failed")
        return 1

    end_t = start_t + args.hours * 3600
    report_interval = 300  # print status every 5 min
    last_report = start_t

    try:
        while time.time() < end_t:
            time.sleep(10)
            now = time.time()

            # Periodic status report
            if now - last_report >= report_interval:
                alive = client._running
                auth = client.is_authenticated
                last_hb = client._last_heartbeat_at
                hb_ago = int(now - last_hb) if last_hb > 0 else -1
                print(f"[{elapsed()}] STATUS: running={alive} auth={auth} "
                      f"heartbeats_sent={heartbeat_count[0]} "
                      f"last_hb={hb_ago}s ago disconnects={disconnect_count[0]}")
                last_report = now

            # Stop if disconnected and not reconnecting
            if not client._running:
                print(f"[{elapsed()}] Client stopped running. Disconnected.")
                break

    except KeyboardInterrupt:
        print(f"\n[{elapsed()}] Interrupted by user")

    client.disconnect()

    # Summary
    run_secs = int(time.time() - start_t)
    print(f"\n{'='*60}")
    print(f"测试结果 (运行了 {run_secs//3600}h {(run_secs%3600)//60}m {run_secs%60}s)")
    print(f"  心跳发送次数: ~{int(run_secs / args.heartbeat)}")
    print(f"  心跳确认收到: {heartbeat_count[0]}")
    print(f"  断线次数: {disconnect_count[0]}")
    alive_until = "整个测试期间" if disconnect_count[0] == 0 else f"约 {run_secs // 3600}h {(run_secs % 3600) // 60}m"
    print(f"  连接保持: {alive_until}")
    print(f"{'='*60}")

    if disconnect_count[0] == 0:
        print("\n✓ 假设B初步验证通过：连接全程保持（需要更长时间测试确认）")
        return 0
    else:
        print(f"\n✗ 假设B验证失败：断线 {disconnect_count[0]} 次，需要续期机制")
        return 1


if __name__ == "__main__":
    sys.exit(main())
