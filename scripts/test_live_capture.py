"""实时测试：嗅探模拟器网络流量，识别游戏服务器端口。"""
import threading
from collections import Counter

from scapy.config import conf

try:
    conf.use_npcap = True
except Exception:
    pass

from scapy.all import sniff, IP, TCP

print(f"默认接口: {conf.iface}")
print("嗅探 5 秒所有 TCP 流量...\n")

packets = []


def do_sniff():
    try:
        sock = conf.L3socket(iface=conf.iface)
        sniff(opened_socket=sock, prn=lambda p: packets.append(p), timeout=5, store=False)
        sock.close()
    except Exception as e:
        print(f"嗅探失败: {e}")


t = threading.Thread(target=do_sniff, daemon=True)
t.start()
t.join(10)

# 统计端口和 IP
port_counter = Counter()
ip_counter = Counter()
game_ports = {7777, 5749}

for pkt in packets:
    if IP in pkt and TCP in pkt:
        src_ip = pkt[IP].src
        dst_ip = pkt[IP].dst
        sport = pkt[TCP].sport
        dport = pkt[TCP].dport
        port_counter[(src_ip, sport, dst_ip, dport)] += 1
        ip_counter[src_ip] += 1
        ip_counter[dst_ip] += 1

print(f"共捕获 {len(packets)} 个包\n")

# 显示活跃连接
print("活跃 TCP 连接 (按包数排序):")
print(f"{'源IP':>18}:{'端口':<6} -> {'目标IP':>18}:{'端口':<6} | 包数")
print("-" * 70)
for (src, sport, dst, dport), count in port_counter.most_common(20):
    marker = ""
    if sport in game_ports or dport in game_ports:
        marker = " <-- 游戏端口!"
    print(f"{src:>18}:{sport:<6} -> {dst:>18}:{dport:<6} | {count}{marker}")

# 特别标记游戏相关流量
print("\n--- 游戏端口检测 ---")
game_found = False
for (src, sport, dst, dport), count in port_counter.items():
    if sport in game_ports or dport in game_ports:
        print(f"  发现游戏流量: {src}:{sport} -> {dst}:{dport} ({count} 个包)")
        game_found = True
if not game_found:
    print("  未发现 7777/5749 端口流量")
    print("  可能原因: 游戏未在对局中 / 端口不对 / 流量走了其他网卡")
