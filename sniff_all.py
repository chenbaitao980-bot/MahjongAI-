"""在所有接口上捕获 TCP 流量，找出游戏包走哪里"""
import sys
from scapy.all import sniff, IP, TCP, get_working_ifaces

ifaces = [i.name for i in get_working_ifaces()]
print("监听接口:", ifaces)

seen = {}  # (src_ip, dst_ip, dst_port) -> iface

def pkt_cb(pkt):
    if IP in pkt and TCP in pkt:
        dst_port = pkt[TCP].dport
        src_port = pkt[TCP].sport
        src = pkt[IP].src
        dst = pkt[IP].dst
        # 找有意思的端口（排除 443/80/常见）
        if dst_port not in (443, 80, 53, 8080, 8443) and src_port not in (443, 80, 53):
            key = f"{src} -> {dst}:{dst_port}"
            if key not in seen:
                seen[key] = True
                print(f"  {key}")

print("抓包 15秒，过滤 TCP（排除 443/80）...")
sniff(iface=ifaces, filter="tcp", prn=pkt_cb, timeout=15, store=False)
print(f"\n共 {len(seen)} 条")
