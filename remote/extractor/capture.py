"""
capture.py — 跨平台抓包适配层

Windows: 使用 NpcapCapture（scapy + npcap）
Linux/OpenWRT: 使用 tcpdump subprocess + PcapParser 流式解析
"""
import os
import platform
import subprocess
import sys
import threading

# 插入项目根目录到 sys.path，以复用 stable/ 代码
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stable.protocol import PcapParser, MJProtocol, NpcapCapture, GAME_SERVER_PORT

import logging

_LOGGER = logging.getLogger("remote.extractor.capture")

# Windows 移动热点/ICS 的固定网关；手机流量经此适配器
HOTSPOT_GATEWAY = "192.168.137.1"


def is_windows():
    """判断当前是否 Windows 平台"""
    return platform.system() == "Windows"


def _detect_vpn_interface():
    """
    Detect VPN virtual interface (WireGuard wg0 or strongSwan ipsec).
    Returns interface name if found, None otherwise.
    strongSwan uses kernel xfrm (no virtual interface), so we fall back to "any".
    """
    # WireGuard wg0 (if WG is used instead of strongSwan)
    if os.path.isdir("/sys/class/net/wg0"):
        return "wg0"
    # strongSwan/IPSec: traffic goes through kernel xfrm, visible on "any"
    try:
        result = subprocess.run(
            ["ip", "link", "show", "wg0"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, timeout=5,
        )
        if result.returncode == 0:
            return "wg0"
    except Exception:
        pass
    return None


def find_hotspot_iface(gateway=HOTSPOT_GATEWAY):
    """
    找到承载手机流量的热点/ICS 适配器（IP == gateway）。
    返回 scapy NetworkInterface 对象，找不到返回 None。
    """
    try:
        from scapy.all import get_working_ifaces
    except Exception:
        return None
    try:
        for ifc in get_working_ifaces():
            if getattr(ifc, "ip", None) == gateway:
                return ifc
    except Exception:
        return None
    return None


_GAME_SERVER_IP = "47.96.0.227"


class NpcapCaptureAdapter:
    """Windows 平台 Npcap 抓包适配器"""

    def __init__(self, port=GAME_SERVER_PORT, interface=None):
        self.port = int(port)

        # 解析抓包网卡：
        #   - 显式指定（非 "any"）→ 直接用
        #   - "any"/None → 自动选热点网卡（192.168.137.1），手机流量在此
        #   - 找不到热点 → iface=None，回退 scapy 默认网卡（并告警）
        resolved = None
        if interface and interface != "any":
            resolved = interface
            _LOGGER.info("抓包网卡（显式指定）: %s", resolved)
        else:
            hot = find_hotspot_iface()
            if hot is not None:
                resolved = hot
                _LOGGER.info("抓包网卡（自动选中热点）: %s | %s",
                             getattr(hot, "name", hot), getattr(hot, "description", ""))
            else:
                _LOGGER.warning(
                    "未找到热点网卡（IP %s）。将使用 scapy 默认网卡，"
                    "若手机流量不在该网卡上将抓不到包。请确认移动热点已开、手机已连接。",
                    HOTSPOT_GATEWAY)

        self.iface = resolved
        self._capture = NpcapCapture(server_port=self.port, iface=resolved)
        self._proto = MJProtocol(server_port=self.port)
        self._parser = PcapParser()
        self._tcp_state: dict | None = None

    def run(self, packet_callback):
        """
        阻塞运行，每收到一个有效 TCP 包调用 packet_callback(pkt_dict)
        packet_callback 接受 PcapParser 返回的包 dict
        """

        def on_raw_ip(raw_ip):
            # NpcapCapture 回调传入原始 IP 字节
            # 包装成 pcap 格式供 PcapParser._parse_ip_tcp 解析
            from stable.protocol import PcapParser as _P
            pkt = _P._parse_ip_tcp_static(raw_ip)
            if pkt is not None:
                pkt["ts"] = 0.0
                # Track TCP state: phone -> game server direction
                # pkt["dst"] is "ip:port" format, pkt["dst_port"] is int
                dst_port = pkt.get("dst_port")
                if dst_port == self.port:
                    dst_combined = pkt.get("dst", "")
                    dst_ip = dst_combined.rsplit(":", 1)[0] if ":" in dst_combined else dst_combined
                    if dst_ip == _GAME_SERVER_IP:
                        src_combined = pkt.get("src", "")
                        src_ip = src_combined.rsplit(":", 1)[0] if ":" in src_combined else src_combined
                        self._tcp_state = {
                            "phone_ip": src_ip,
                            "phone_port": pkt.get("src_port"),
                            "phone_seq": pkt.get("seq"),
                        }
                packet_callback(pkt)

        self._capture.sniff(on_raw_ip, port_filter=self.port)

    def get_tcp_state(self) -> dict | None:
        """Return the most recently observed phone->server TCP state, or None."""
        return self._tcp_state

    def stop(self):
        self._capture.stop()


class TcpdumpCaptureAdapter:
    """Linux/OpenWRT tcpdump 抓包适配器"""

    def __init__(self, port=GAME_SERVER_PORT, interface="any"):
        self.port = int(port)
        # Auto-detect VPN interface (wg0 or fallback to any)
        if interface == "any":
            interface = _detect_vpn_interface() or "any"
        self.interface = interface
        if self.interface != "any":
            _LOGGER.info("抓包网卡（auto-detect）: %s", self.interface)
        self._parser = PcapParser()
        self._proc = None
        self._stop_event = threading.Event()

    def run(self, packet_callback):
        """
        阻塞运行，启动 tcpdump subprocess，逐帧解析并调用 packet_callback(pkt_dict)
        """
        cmd = [
            "tcpdump",
            "-i", self.interface,
            "-w", "-",      # 输出到 stdout
            "-U",           # 不缓冲
            "-s", "0",      # 抓全包
            "port", str(self.port),
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            while not self._stop_event.is_set():
                chunk = self._proc.stdout.read(4096)
                if not chunk:
                    break
                pkts = self._parser.feed(chunk)
                for pkt in pkts:
                    packet_callback(pkt)
        finally:
            self._proc.kill()

    def get_tcp_state(self) -> dict | None:
        """RST injection not supported on Linux; always returns None."""
        return None

    def stop(self):
        self._stop_event.set()
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass


def create_capture(mode=None, port=GAME_SERVER_PORT, interface="any"):
    """
    工厂函数：根据 mode 或平台自动选择抓包适配器

    mode: "npcap" | "tcpdump" | None（自动检测）
    返回 NpcapCaptureAdapter 或 TcpdumpCaptureAdapter
    """
    if mode == "npcap" or (mode is None and is_windows()):
        return NpcapCaptureAdapter(port=port, interface=interface)
    else:
        return TcpdumpCaptureAdapter(port=port, interface=interface)
