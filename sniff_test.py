"""快速诊断：抓 WLAN + 热点 接口上的 TCP 流量，看是否有游戏包"""
import sys
from scapy.all import sniff, IP, TCP

seen = []

def pkt_cb(pkt):
    if IP in pkt and TCP in pkt:
        src = pkt[IP].src
        dst = pkt[IP].dst
        sp = pkt[TCP].sport
        dp = pkt[TCP].dport
        info = f"{src}:{sp} -> {dst}:{dp}"
        if info not in seen:
            seen.append(info)
            print(info)

iface = sys.argv[1] if len(sys.argv) > 1 else None
print(f"抓包接口: {iface or '默认'}, 过滤 TCP, 10秒...")
sniff(iface=iface, filter="tcp", prn=pkt_cb, timeout=10, store=False)
print(f"\n共看到 {len(seen)} 条不同 TCP 连接")
