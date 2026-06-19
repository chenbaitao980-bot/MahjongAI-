"""ECS-side wire-format probe.

Sniff lobby flows on iface (any), grab TCP packets to/from 47.96.101.155:5748,
reassemble TCP byte streams per direction per connection, walk the SRS 12B framer:
    flag(2) pay_len(2) msg_type(2) sub_type(2) extra(4)

For every frame, print: ts dir msg_type pay_len sub_type extra payload[:32].

Usage:
    python3 wire_probe.py --listen-secs 60 \
        --filter-host 47.96.101.155 --filter-port 5748

依赖：tcpdump（用于实时捕包），无 scapy 也能跑。
"""
from __future__ import annotations

import argparse
import logging
import os
import struct
import subprocess
import sys
import time
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("wire_probe")


# Pure-Python pcap parser (libpcap savefile format) — handles linux SLL/SLL2/Ethernet
def parse_pcap_packets(path: str):
    with open(path, "rb") as f:
        gh = f.read(24)
        if len(gh) < 24:
            return
        magic, ver_maj, ver_min, _, _, snaplen, linktype = struct.unpack("<IHHIIII", gh)
        # nanosecond? swap-order? we assume native LE produced by tcpdump on x86
        while True:
            ph = f.read(16)
            if len(ph) < 16:
                return
            ts_sec, ts_usec, incl_len, orig_len = struct.unpack("<IIII", ph)
            data = f.read(incl_len)
            if len(data) < incl_len:
                return
            # Strip linktype-specific framing
            if linktype == 1:  # ETHERNET
                if len(data) < 14:
                    continue
                eth_type = struct.unpack(">H", data[12:14])[0]
                if eth_type != 0x0800:
                    continue
                ip_data = data[14:]
            elif linktype == 113:  # LINUX_SLL
                if len(data) < 16:
                    continue
                eth_type = struct.unpack(">H", data[14:16])[0]
                if eth_type != 0x0800:
                    continue
                ip_data = data[16:]
            elif linktype == 276:  # LINUX_SLL2
                if len(data) < 20:
                    continue
                eth_type = struct.unpack(">H", data[0:2])[0]
                if eth_type != 0x0800:
                    continue
                ip_data = data[20:]
            elif linktype == 101:  # RAW IP
                ip_data = data
            else:
                continue
            yield ts_sec + ts_usec / 1e6, ip_data


def parse_ip_tcp(ip_data: bytes):
    if len(ip_data) < 20:
        return None
    vihl = ip_data[0]
    ver = vihl >> 4
    if ver != 4:
        return None
    ihl = (vihl & 0x0F) * 4
    proto = ip_data[9]
    if proto != 6:
        return None
    src_ip = ".".join(str(b) for b in ip_data[12:16])
    dst_ip = ".".join(str(b) for b in ip_data[16:20])
    tcp_data = ip_data[ihl:]
    if len(tcp_data) < 20:
        return None
    sport, dport = struct.unpack(">HH", tcp_data[0:4])
    seq, ack = struct.unpack(">II", tcp_data[4:12])
    data_off = (tcp_data[12] >> 4) * 4
    flags = tcp_data[13]
    payload = tcp_data[data_off:]
    return {
        "src_ip": src_ip, "dst_ip": dst_ip,
        "sport": sport, "dport": dport,
        "seq": seq, "ack": ack, "flags": flags,
        "payload": payload,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--listen-secs", type=int, default=60)
    p.add_argument("--filter-host", default="47.96.101.155")
    p.add_argument("--filter-port", type=int, default=5748)
    p.add_argument("--iface", default="any")
    p.add_argument("--pcap", default="/tmp/wire_probe.pcap")
    args = p.parse_args()

    bpf = f"host {args.filter_host} and port {args.filter_port}"
    logger.info("starting tcpdump iface=%s filter=%r → %s for %ds",
                args.iface, bpf, args.pcap, args.listen_secs)

    proc = subprocess.Popen(
        ["tcpdump", "-i", args.iface, "-w", args.pcap, "-s", "65535", "-U", bpf],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        time.sleep(args.listen_secs)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
        # surface any tcpdump warnings
        try:
            stderr = proc.stderr.read().decode(errors="replace")
            if stderr.strip():
                logger.info("tcpdump stderr: %s", stderr.strip()[-500:])
        except Exception:
            pass

    # Reassemble TCP streams per (src_ip, sport, dst_ip, dport)
    streams: dict[tuple, dict] = {}  # key → {"buf": bytearray, "next_seq": int}
    for ts, ip_data in parse_pcap_packets(args.pcap):
        info = parse_ip_tcp(ip_data)
        if not info:
            continue
        if not info["payload"]:
            continue
        key = (info["src_ip"], info["sport"], info["dst_ip"], info["dport"])
        st = streams.setdefault(key, {"buf": bytearray(), "next_seq": None})
        # naive append (no out-of-order handling)
        if st["next_seq"] is None:
            st["next_seq"] = info["seq"]
        if info["seq"] == st["next_seq"]:
            st["buf"].extend(info["payload"])
            st["next_seq"] = (info["seq"] + len(info["payload"])) & 0xFFFFFFFF
        elif info["seq"] > st["next_seq"]:
            # 跳过 gap，记下来
            gap = info["seq"] - st["next_seq"]
            logger.debug("gap %d on %s", gap, key)
            st["buf"].extend(info["payload"])
            st["next_seq"] = (info["seq"] + len(info["payload"])) & 0xFFFFFFFF
        # 已收到的旧包跳过

    # Walk frame headers
    HDR = 12
    frame_count_by_dir = defaultdict(int)
    msg_type_freq = defaultdict(int)
    print("\n=== WIRE FRAMES ===")
    print("dir       msg_type sub_type extra      pay_len payload_head")
    for key, st in streams.items():
        src_ip, sport, dst_ip, dport = key
        # 方向：到 47.96.101.155:5748 = C->S，反之 S->C
        direction = "C->S" if (dst_ip == args.filter_host and dport == args.filter_port) else "S->C"
        buf = bytes(st["buf"])
        offset = 0
        while offset + HDR <= len(buf):
            try:
                flag, pay_len, mt, sub, extra = struct.unpack(
                    "<HHHHI", buf[offset:offset + HDR])
            except Exception:
                break
            if flag != 0x4001 or pay_len > 65535:
                # 重新同步：跳 1 字节
                offset += 1
                continue
            if offset + HDR + pay_len > len(buf):
                break
            payload = buf[offset + HDR:offset + HDR + pay_len]
            frame_count_by_dir[direction] += 1
            msg_type_freq[(direction, mt)] += 1
            # 只打印 IMProtocol 范围 + handshake + 关键消息
            if mt in (3000, 3001, 3002, 3003) or (
                400 <= mt <= 480 or mt in (301, 302, 303, 304, 305, 306, 307,
                                            1, 3, 4, 5, 6, 14, 0x2BC0, 0x2BC1)):
                print(f"{direction}  {mt:>5} {sub:>5}  0x{extra:08x}  {pay_len:>5}  {payload[:32].hex()}")
            offset += HDR + pay_len

    print("\n=== SUMMARY ===")
    for d, c in frame_count_by_dir.items():
        print(f"{d}: {c} frames")
    print("\nTop msg_type by direction:")
    for (d, mt), c in sorted(msg_type_freq.items(), key=lambda x: -x[1])[:30]:
        print(f"  {d} msg={mt} count={c}")


if __name__ == "__main__":
    sys.exit(main() or 0)
