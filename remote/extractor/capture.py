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


def is_windows():
    """判断当前是否 Windows 平台"""
    return platform.system() == "Windows"


class NpcapCaptureAdapter:
    """Windows 平台 Npcap 抓包适配器"""

    def __init__(self, port=GAME_SERVER_PORT):
        self.port = int(port)
        self._capture = NpcapCapture(server_port=self.port)
        self._proto = MJProtocol(server_port=self.port)
        self._parser = PcapParser()

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
                packet_callback(pkt)

        self._capture.sniff(on_raw_ip, port_filter=self.port)

    def stop(self):
        self._capture.stop()


class TcpdumpCaptureAdapter:
    """Linux/OpenWRT tcpdump 抓包适配器"""

    def __init__(self, port=GAME_SERVER_PORT, interface="any"):
        self.port = int(port)
        self.interface = interface
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
        return NpcapCaptureAdapter(port=port)
    else:
        return TcpdumpCaptureAdapter(port=port, interface=interface)
