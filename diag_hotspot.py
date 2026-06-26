"""
diag_hotspot.py — 热点网卡诊断
用途：确认 Npcap 能从热点虚拟网卡抓到手机 TCP 流量，并列出活跃端口
运行：管理员权限，python diag_hotspot.py
"""
import sys
import time
import os

_ROOT = os.path.abspath(os.path.dirname(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

HOTSPOT_GATEWAY = "192.168.137.1"
CAPTURE_SECONDS = 20

def find_hotspot_iface():
    from scapy.all import get_working_ifaces
    for ifc in get_working_ifaces():
        if getattr(ifc, "ip", None) == HOTSPOT_GATEWAY:
            return ifc
    return None

def main():
    print("=== 热点网卡 Npcap 诊断 ===")
    print(f"抓包时长: {CAPTURE_SECONDS}秒，过滤所有 TCP，不限端口\n")

    ifc = find_hotspot_iface()
    if ifc:
        print(f"[✓] 找到热点网卡: {getattr(ifc, 'name', ifc)} | {getattr(ifc, 'description', '')}")
    else:
        print(f"[✗] 未找到热点网卡 (IP {HOTSPOT_GATEWAY})，请先开启移动热点")
        sys.exit(1)

    from scapy.all import sniff as scapy_sniff
    from scapy.layers.inet import IP, TCP

    seen_ports = {}
    pkt_count = 0

    def on_pkt(pkt):
        nonlocal pkt_count
        if IP not in pkt or TCP not in pkt:
            return
        pkt_count += 1
        src = pkt[IP].src
        dst = pkt[IP].dst
        sport = pkt[TCP].sport
        dport = pkt[TCP].dport
        key = (src, dst, dport)
        if key not in seen_ports:
            seen_ports[key] = 0
            print(f"  新连接: {src}:{sport} → {dst}:{dport}")
        seen_ports[key] += 1

    print(f"\n[→] 开始监听 {CAPTURE_SECONDS}秒，请在手机上正常操作游戏...\n")
    start = time.time()
    scapy_sniff(iface=ifc, filter="tcp", prn=on_pkt,
                timeout=CAPTURE_SECONDS, store=False)

    elapsed = time.time() - start
    print(f"\n[完成] 抓包 {elapsed:.1f}秒，共 {pkt_count} 个 TCP 包")
    if not seen_ports:
        print("[!] 没有抓到任何 TCP 包。可能原因：")
        print("    1. 手机未连接到本机热点")
        print("    2. Npcap 不支持此虚拟网卡（换下方 WLAN 版本测试）")
        print("    3. 手机未在进行任何网络操作")
    else:
        print("\n活跃连接：")
        for (src, dst, dport), cnt in sorted(seen_ports.items(), key=lambda x: -x[1]):
            tag = " ← 游戏对局！" if dport == 7777 else (" ← 大厅/登录" if dport == 5700 else "")
            print(f"  {src} → {dst}:{dport}  ({cnt}包){tag}")
        if any(dport == 7777 for (_, _, dport) in seen_ports):
            print("\n[✓✓✓] 7777 端口流量已捕获！extractor 可以正常工作。")
        else:
            print("\n[!] 未见 7777 流量。请在对局进行中（摸牌/出牌时）运行此脚本。")


if __name__ == "__main__":
    main()
