"""
rst_injector.py - Forge a TCP RST to trigger the game server's grace period.

Sends a packet: IP(src=phone_ip, dst=server_ip)/TCP(sport=phone_port,
dport=server_port, flags='R', seq=phone_seq)

This causes the game server to believe the phone disconnected abnormally,
entering a grace period in which cloud_player can reconnect as "the same player".

Requires: scapy (already installed as a Npcap dependency), admin rights.
"""
from __future__ import annotations
import logging

_LOGGER = logging.getLogger("remote.extractor.rst_injector")

_GAME_SERVER_IP = "47.96.0.227"
_GAME_SERVER_PORT = 7777


def inject_rst(
    phone_ip: str,
    phone_port: int,
    phone_seq: int,
    server_ip: str = _GAME_SERVER_IP,
    server_port: int = _GAME_SERVER_PORT,
    iface=None,          # scapy NetworkInterface, or None to auto-detect
) -> bool:
    """Send a forged RST from phone_ip:phone_port to server_ip:server_port.

    Returns True on success, False if scapy is unavailable or an error occurs.
    """
    try:
        from scapy.all import sendp, IP, TCP, Ether
    except ImportError:
        _LOGGER.warning(
            "[rst_injector] scapy not available — RST injection skipped. "
            "Install scapy (pip install scapy) and Npcap to enable."
        )
        return False

    try:
        if iface is None:
            from remote.extractor.capture import find_hotspot_iface
            iface = find_hotspot_iface()

        pkt = Ether() / IP(src=phone_ip, dst=server_ip) / TCP(
            sport=phone_port,
            dport=server_port,
            flags="R",
            seq=phone_seq,
        )
        sendp(pkt, iface=iface, verbose=False)
        _LOGGER.info(
            "[rst_injector] RST sent: %s:%d -> %s:%d seq=%d",
            phone_ip, phone_port, server_ip, server_port, phone_seq,
        )
        return True
    except Exception as exc:
        _LOGGER.error("[rst_injector] Failed to send RST: %s", exc)
        return False
