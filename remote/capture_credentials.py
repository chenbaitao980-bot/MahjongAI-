"""
remote/capture_credentials.py — 热点 live 抓包，两阶段运行

阶段 1: 首次抓包，拿到 srs_sessionid 后上传 ECS（cloud_player 不自动启动）。
阶段 2: 持续监听 RespJoinTable（手机进局信号），每次检测到新局自动 POST
         /api/start-player 通知云端启动 cloud_player。
         此时手机已拿到 RespJoinTable 确认进局，cloud_player 再连不会阻断。

用法：
    python remote/capture_credentials.py
    python remote/capture_credentials.py --ecs-relay http://8.136.37.136:8003
"""
import argparse
import datetime
import json
import logging
import os
import subprocess
import sys
import time
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from stable.protocol import MJProtocol, GAME_SERVER_PORT
from remote.extractor.capture import NpcapCaptureAdapter
from remote.extractor.token_extractor import TokenExtractor, SRSSessionExtractor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_LOGGER = logging.getLogger("capture_credentials")

DEFAULT_OUTPUT = os.path.join(_ROOT, "data", "cloud_credentials.json")
DEFAULT_TIMEOUT = 0   # 0 = 无限运行，直到手动停止（sessionid 经长期实测永久有效）
_GAME_TRIGGER_DEBOUNCE = 30  # seconds between consecutive start-player signals


def _mask(value: str, keep: int = 4) -> str:
    if not value:
        return "(empty)"
    return "{}...({} chars)".format(value[:keep], len(value))


class CredentialCapture:
    def __init__(self, output_path: str, timeout: int,
                 ecs_relay: str = "", api_token: str = ""):
        self._output_path = output_path
        self._timeout = timeout
        self._ecs_relay = ecs_relay.rstrip("/") if ecs_relay else ""
        self._api_token = api_token
        self._adapter = None
        self._capture_adapter = None  # NpcapCaptureAdapter ref for RST injection

        # Phase flags
        self._creds_done = False   # Phase 1 complete
        self._stopped = False      # all done (timeout or stop)

        # Phase 2: debounce game-entry triggers
        self._last_game_trigger = 0.0

        # Extractors (Phase 1 only)
        self._token_ext = TokenExtractor(
            on_registered=self._on_credentials,
            on_room_info=self._on_room_info,
            capture_all_heads=False,
        )
        self._srs_ext = SRSSessionExtractor(
            on_sessionid=self._on_sessionid,
        )
        self._protocol = MJProtocol(server_port=GAME_SERVER_PORT)

        # Captured values
        self._room_id = None
        self._game_id = None
        self._sessionid = None
        self._identify = None
        self._handshake_blob = None
        self._auth_token_12b = None

    # ── Phase 1 callbacks ─────────────────────────────────────────

    def _on_credentials(self, handshake_blob: bytes, auth_token_12b: bytes):
        self._handshake_blob = handshake_blob
        self._auth_token_12b = auth_token_12b
        print("[OK] handshake_blob = {} bytes".format(len(handshake_blob)))
        print("[OK] auth_token_12b = {}".format(auth_token_12b.hex()))
        self._try_complete()

    def _on_room_info(self, room_id: int, game_id: int):
        self._room_id = room_id
        self._game_id = game_id
        print("[OK] room_id = {}".format(room_id))
        print("[OK] game_id = {}".format(game_id))
        self._try_complete()

    def _on_sessionid(self, sessionid: bytes):
        self._sessionid = sessionid
        self._identify = self._srs_ext.identify
        print("[OK] srs_sessionid = {}".format(sessionid.hex()))
        if self._identify:
            print("[OK] identify = {}".format(self._identify.hex()))
        self._try_complete()

    def _try_complete(self):
        if self._creds_done or self._sessionid is None:
            return
        self._save_and_enter_phase2()

    def _save_and_enter_phase2(self):
        if self._creds_done:
            return
        self._creds_done = True

        creds = {
            "srs_sessionid": self._sessionid.hex() if self._sessionid else None,
            "room_id": self._room_id,
            "game_id": self._game_id,
            "identify": self._identify.hex() if self._identify else None,
            "handshake_blob": self._handshake_blob.hex() if self._handshake_blob else None,
            "auth_token_12b": self._auth_token_12b.hex() if self._auth_token_12b else None,
            "captured_at": datetime.datetime.utcnow().isoformat() + "Z",
        }

        output_dir = os.path.dirname(os.path.abspath(self._output_path))
        if output_dir and not os.path.isdir(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        with open(self._output_path, "w", encoding="utf-8") as f:
            json.dump(creds, f, indent=2, ensure_ascii=False)

        print("")
        print("[SAVED] Credentials written to: {}".format(self._output_path))
        print("  srs_sessionid : {}".format(_mask(creds["srs_sessionid"])))
        print("  room_id       : {}".format(creds["room_id"]))
        print("")

        # Upload to ECS (server auto-starts player with fresh creds)
        if self._ecs_relay and creds.get("srs_sessionid"):
            print("[Uploading] Sending credentials to ECS: {}".format(self._ecs_relay))
            ok = self._upload_creds(creds)
            if ok:
                print("[OK] ECS credentials ready. Cloud player auto-started by relay.")

        # Auto-open browser so user can see hand tiles
        if self._ecs_relay:
            url = "{}/?token={}".format(self._ecs_relay, self._api_token)
            print("[Browser] Opening: {}".format(url))
            try:
                import subprocess as _sp
                _sp.Popen('start "" "{}"'.format(url), shell=True)
            except Exception:
                pass

        # Wait for ECS SRSPlayerClient to initialize before injecting RST.
        # /api/creds starts the player async; RST must arrive AFTER the player
        # has entered its retry loop, otherwise grace period expires before first connect.
        if self._ecs_relay and creds.get("srs_sessionid"):
            print("[Wait] Giving ECS player 3s to initialize before RST injection...")
            time.sleep(3)

        # Temporarily block phone reconnect so ECS can claim the session slot first
        phone_state = None
        if self._capture_adapter and hasattr(self._capture_adapter, "get_tcp_state"):
            phone_state = self._capture_adapter.get_tcp_state()

        blocked = False
        if phone_state:
            print("[FW] Blocking phone reconnect during dual-connect window...")
            blocked = self._block_phone_traffic(phone_state["phone_ip"])

        # Trigger grace period via TCP RST (so cloud_player can connect without manual WiFi toggle)
        print("[Next] Triggering server disconnect window via RST injection...")
        rst_ok = self._inject_rst_if_possible()
        if rst_ok:
            print("[OK] RST sent. Game will briefly stall then auto-recover.")
            if blocked:
                print("[Wait] Holding phone reconnect for 5s while ECS connects...")
                time.sleep(5)
                self._unblock_phone_traffic()
                print("[FW] Phone reconnect unblocked. Dual-connect should now be established.")
            else:
                print("[Wait] ECS dual-connect establishing, please wait...")
        else:
            if blocked:
                self._unblock_phone_traffic()
            print("[Next] Please manually switch phone WiFi from PC hotspot to own network to trigger dual-connect.")

        print("")
        print("=" * 60)
        print("[Phase 2] Watching for game entry...")
        print("  Enter a game on your phone — cloud monitoring starts automatically.")
        print("  Press Ctrl+C to stop.")
        print("=" * 60)
        print("")

    # ── Phase 2: game detection ───────────────────────────────────

    def _on_packet(self, pkt: dict):
        msgs = self._protocol.process_packet(pkt)
        for msg in msgs:
            if not self._creds_done:
                # Phase 1: extract credentials
                self._token_ext.feed(msg)
                self._srs_ext.feed(msg)
            else:
                # Phase 2: detect RespJoinTable (msg=14, S->C) = phone entered game room
                if (getattr(msg, "msg_type", None) == 14
                        and getattr(msg, "direction", None) == "S->C"):
                    now = time.time()
                    if now - self._last_game_trigger >= _GAME_TRIGGER_DEBOUNCE:
                        self._last_game_trigger = now
                        # Run trigger in background so it doesn't block packet capture
                        threading.Thread(target=self._on_game_detected,
                                         daemon=True).start()

    def _on_game_detected(self):
        print("")
        print("[GAME] Game entry detected! Starting cloud monitor...")
        self._trigger_cloud_player()

    def _trigger_cloud_player(self):
        if not self._ecs_relay:
            return
        try:
            import requests
            resp = requests.post(
                "{}/api/start-player".format(self._ecs_relay),
                json={"api_token": self._api_token},
                timeout=8,
            )
            if resp.status_code == 200:
                print("[OK] Cloud player started. Open: {}/?token={}".format(
                    self._ecs_relay, self._api_token))
            else:
                print("[WARN] start-player returned {}: {}".format(
                    resp.status_code, resp.text[:80]))
        except Exception as exc:
            print("[WARN] start-player call failed: {}".format(exc))

    def _upload_creds(self, creds: dict) -> bool:
        try:
            import requests
            payload = dict(creds)
            payload["api_token"] = self._api_token
            resp = requests.post(
                "{}/api/creds".format(self._ecs_relay),
                json=payload,
                timeout=10,
            )
            if resp.status_code == 200:
                return True
            print("[WARN] ECS upload returned {}: {}".format(resp.status_code, resp.text[:120]))
            return False
        except Exception as exc:
            print("[WARN] ECS upload failed: {}".format(exc))
            return False

    def _block_phone_traffic(self, phone_ip: str) -> bool:
        """Block phone -> game server traffic via Windows firewall (requires admin).

        NOTE: In hotspot NAT mode the PC rewrites the phone's source IP to its
        own WAN IP before forwarding, so 'localip=phone_ip' would never match the
        outbound packet.  Matching only on remoteip+remoteport is sufficient and
        correct for this scenario (the only device routing through this hotspot to
        47.96.0.227:7777 is the phone).
        """
        try:
            subprocess.run([
                "netsh", "advfirewall", "firewall", "add", "rule",
                "name=MahjongBlockPhone",
                "dir=out", "action=block",
                "remoteip=47.96.0.227", "remoteport=7777",
                "protocol=TCP", "enable=yes",
            ], check=True, capture_output=True)
            return True
        except Exception as exc:
            print("[WARN] firewall block failed: {}".format(exc))
            return False

    def _unblock_phone_traffic(self) -> None:
        """Remove the MahjongBlockPhone firewall rule (idempotent)."""
        try:
            subprocess.run([
                "netsh", "advfirewall", "firewall", "delete", "rule",
                "name=MahjongBlockPhone",
            ], capture_output=True)
        except Exception:
            pass

    def _inject_rst_if_possible(self) -> bool:
        """Attempt TCP RST injection using the most recently observed phone->server TCP state."""
        state = None
        if self._capture_adapter and hasattr(self._capture_adapter, "get_tcp_state"):
            state = self._capture_adapter.get_tcp_state()
        if not state:
            return False
        from remote.extractor.rst_injector import inject_rst
        ok = inject_rst(
            phone_ip=state["phone_ip"],
            phone_port=state["phone_port"],
            phone_seq=state["phone_seq"],
        )
        return ok

    # ── Main run loop ─────────────────────────────────────────────

    def run(self):
        print("[Waiting] Please connect your phone to the PC hotspot, then open the game...")
        if self._timeout > 0:
            print("          (running for up to {}h)".format(self._timeout // 3600))
        else:
            print("          (running indefinitely — press Ctrl+C to stop)")
        print("")

        self._adapter = NpcapCaptureAdapter(port=GAME_SERVER_PORT)
        self._capture_adapter = self._adapter  # save ref for RST injection

        def _watchdog():
            if self._timeout <= 0:
                return  # 0 = run forever
            time.sleep(self._timeout)
            if not self._stopped:
                print("")
                print("[TIMEOUT] {}s elapsed. Stopping capture.".format(self._timeout))
                self._stopped = True
                if self._adapter is not None:
                    self._adapter.stop()

        t = threading.Thread(target=_watchdog, daemon=True)
        t.start()

        try:
            self._adapter.run(self._on_packet)
        except Exception as exc:
            if not self._stopped:
                _LOGGER.error("Capture error: %s", exc)
        finally:
            self._token_ext.close()
            self._unblock_phone_traffic()  # ensure firewall rule is removed on exit

        print("[INFO] Capture stopped.")


def main():
    parser = argparse.ArgumentParser(
        description="Capture SRS sessionid + auto-trigger cloud monitoring on game entry"
    )
    parser.add_argument(
        "--output", "-o",
        default=DEFAULT_OUTPUT,
        help="Output JSON path (default: {})".format(DEFAULT_OUTPUT),
    )
    parser.add_argument(
        "--timeout", "-t",
        type=int,
        default=DEFAULT_TIMEOUT,
        help="Max seconds to run (default: {}s = 4h)".format(DEFAULT_TIMEOUT),
    )
    parser.add_argument(
        "--ecs-relay",
        default="http://8.136.37.136:8003",
        help="ECS relay URL (default: http://8.136.37.136:8003). Empty string to disable.",
    )
    parser.add_argument(
        "--api-token",
        default="cloudmode2026",
        help="API token (default: cloudmode2026)",
    )
    args = parser.parse_args()

    cap = CredentialCapture(
        output_path=args.output,
        timeout=args.timeout,
        ecs_relay=args.ecs_relay,
        api_token=args.api_token,
    )
    cap.run()


if __name__ == "__main__":
    main()
