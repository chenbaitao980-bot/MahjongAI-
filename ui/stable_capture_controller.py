from __future__ import annotations

import json
import os
import re
import subprocess
from copy import deepcopy
from datetime import datetime

from PyQt6.QtCore import QThread, pyqtSignal

from stable.protocol import MJProtocol, NpcapCapture, PcapParser, build_tcpdump_command
from utils.paths import data_path


class StableCaptureThread(QThread):
    message_ready = pyqtSignal(object)
    status_changed = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = deepcopy(config)
        self._running = True
        self._proc = None
        self._npcap = None

    def request_stop(self) -> None:
        self._running = False
        npcap = self._npcap
        if npcap is not None:
            try:
                npcap.stop()
            except Exception:
                pass
        proc = self._proc
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass

    def run(self):
        stable_cfg = self._config.get("stable_reader", {})
        capture_mode = stable_cfg.get("capture_mode", "npcap")
        port = int(stable_cfg.get("server_port", 7777))

        if capture_mode == "npcap":
            self._run_npcap(stable_cfg, port)
        else:
            self._run_tcpdump(stable_cfg, port)

    def _open_output_files(self, stable_cfg: dict):
        out_dir = os.path.join(data_path("data"), "stable_reader")
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        raw_fp = None
        event_fp = None
        if stable_cfg.get("save_raw_pcap", True):
            raw_fp = open(os.path.join(out_dir, f"raw_{ts}.pcap"), "wb")
        if stable_cfg.get("save_events_jsonl", True):
            event_fp = open(os.path.join(out_dir, f"events_{ts}.jsonl"), "w", encoding="utf-8")
        return raw_fp, event_fp

    def _emit_messages(self, protocol: MJProtocol, pkt: dict, event_fp):
        for msg in protocol.process_packet(pkt):
            if event_fp is not None:
                event_fp.write(json.dumps(msg.to_dict(), ensure_ascii=False) + "\n")
                event_fp.flush()
            self.message_ready.emit(msg)

    def _run_npcap(self, stable_cfg: dict, port: int):
        npcap_iface = stable_cfg.get("npcap_iface", "") or None
        raw_fp, event_fp = self._open_output_files(stable_cfg)

        protocol = MJProtocol(server_port=port, auto_detect_frames=True)
        capture = NpcapCapture(server_port=port, iface=npcap_iface)
        self._npcap = capture
        self.status_changed.emit(f"starting npcap on host (auto tcp; preferred port {port})")
        try:
            def on_ip_packet(ip_bytes: bytes):
                if raw_fp is not None:
                    raw_fp.write(ip_bytes)
                    raw_fp.flush()
                pkt = PcapParser._parse_ip_tcp_static(ip_bytes)
                if pkt is not None:
                    self._emit_messages(protocol, pkt, event_fp)

            self.status_changed.emit("reading packets")
            capture.sniff(on_ip_packet, port_filter=0)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.status_changed.emit("stopped")
            capture.stop()
            self._npcap = None
            if raw_fp is not None:
                raw_fp.close()
            if event_fp is not None:
                event_fp.close()

    def _run_tcpdump(self, stable_cfg: dict, port: int):
        adb_path = stable_cfg.get("adb_path", "")
        device_serial = stable_cfg.get("device_serial", "")
        interface = stable_cfg.get("tcpdump_interface", "wlan0")
        if not adb_path:
            self.failed.emit("stable_reader.adb_path is empty")
            return
        if not device_serial:
            self.failed.emit("stable_reader.device_serial is empty")
            return

        raw_fp, event_fp = self._open_output_files(stable_cfg)

        parser = PcapParser()
        protocol = MJProtocol(server_port=port)
        cmd = build_tcpdump_command(adb_path, device_serial, interface, port)
        self.status_changed.emit(f"starting tcpdump on {device_serial}:{port}")
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            if self._proc.stdout is None:
                raise RuntimeError("tcpdump stdout is unavailable")
            self.status_changed.emit("reading packets")
            while self._running:
                chunk = self._proc.stdout.read(4096)
                if not chunk:
                    break
                if raw_fp is not None:
                    raw_fp.write(chunk)
                    raw_fp.flush()
                packets = parser.feed(chunk)
                for pkt in packets:
                    self._emit_messages(protocol, pkt, event_fp)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.status_changed.emit("stopped")
            if self._proc is not None:
                try:
                    self._proc.terminate()
                except Exception:
                    pass
                self._proc = None
            if raw_fp is not None:
                raw_fp.close()
            if event_fp is not None:
                event_fp.close()


def parse_stable_event_text(text: str) -> tuple[str, str, str]:
    body = re.sub(r"^\d{2}:\d{2}:\d{2}\s*", "", text).strip()

    for raw_actor, disp_actor in [("我方", "我方"), ("对面", "对方"), ("旁家", "旁家")]:
        if body.startswith(raw_actor):
            rest = body[len(raw_actor):]
            for kw, ev in [
                ("摸牌", "摸牌"), ("打出", "出牌"),
                ("明杠", "明杠"), ("暗杠", "暗杠"), ("补杠", "补杠"),
                ("碰", "碰牌"), ("吃", "吃牌"),
                ("手牌更新", "手牌更新"),
            ]:
                if rest.startswith(kw):
                    raw_tile = rest[len(kw):]
                    tile = re.sub(r"[：:\s]*\d+\s*张.*$", "", raw_tile).strip()
                    tile = re.sub(r"^[：:\s]+", "", tile).strip()
                    return ev, disp_actor, tile
            return rest[:12], disp_actor, ""

    if "开局发牌" in body:
        return "开局发牌", "-", ""
    if "开局标记" in body:
        return "开局标记", "-", ""
    if "财神更新" in body:
        return "财神", "-", body.replace("财神更新：", "").strip()
    if "胡牌" in body:
        return "胡牌", "-", ""
    return body[:12], "-", ""
