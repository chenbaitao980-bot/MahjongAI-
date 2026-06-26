"""可行性 spike：验证 WinDivert 能否拦到手机经 PC 热点转发的 DNS 查询。
SNIFF 模式(只复制不拦截，零风险，不影响手机上网)。抓 N 秒后退出。
验证点：能看到 192.168.137.67 → 119.29.29.29/223.5.5.5 的 *.hzxuanming.com 查询。
"""
import sys, threading, time
import pydivert

PHONE = "192.168.137.67"
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 12


def parse_qname(dns: bytes) -> str:
    try:
        off = 12
        labels = []
        while dns[off] != 0:
            ln = dns[off]; off += 1
            labels.append(dns[off:off + ln].decode("ascii", "replace")); off += ln
        return ".".join(labels)
    except Exception:
        return "?"


seen = []
stop = threading.Event()
w = pydivert.WinDivert("udp.DstPort == 53", flags=pydivert.Flag.SNIFF)


all_dns = []
def loop():
    try:
        w.open()
        for pkt in w:
            if stop.is_set():
                break
            if pkt.payload:
                qname = parse_qname(pkt.payload)
                all_dns.append((pkt.src_addr, qname, pkt.dst_addr))
                if pkt.src_addr == PHONE:
                    seen.append((qname, pkt.dst_addr))
    except Exception:
        pass  # close() 时迭代会抛异常,正常退出


t = threading.Thread(target=loop, daemon=True)
t.start()
print(f"SNIFF 中 {DURATION}s（手机正常用游戏即可）...")
time.sleep(DURATION)
stop.set()
try:
    w.close()
except Exception:
    pass

print(f"\n=== WinDivert 捕获的所有 DNS 查询: {len(all_dns)} 条 ===")
print(f"=== 其中手机({PHONE}): {len(seen)} 条 ===")
hz = [(n, d) for n, d in seen if "hzxuanming" in n]
for n, d in seen[:30]:
    mark = " <<< HOTFIX" if "hzxuanming" in n else ""
    print(f"  {n}  -> {d}{mark}")
print(f"\nhzxuanming hits: {len(hz)}")
if hz:
    print("RESULT: PASS - WinDivert can intercept phone forwarded DNS, plan works")
elif all_dns:
    print("RESULT: PARTIAL - WinDivert works but no phone hzxuanming query in window (retry + reopen game)")
else:
    print("RESULT: FAIL - WinDivert captured nothing (path issue)")
