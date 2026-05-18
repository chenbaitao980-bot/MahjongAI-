"""快速测试 scapy L3 嗅探是否可用。"""
import threading

from scapy.config import conf

try:
    conf.use_npcap = True
except Exception:
    pass

from scapy.all import sniff, IP, TCP

print(f"L3socket: {conf.L3socket}")
print(f"默认接口: {conf.iface}")

results = []


def test_sniff():
    print("创建 L3 socket...")
    try:
        sock = conf.L3socket(iface=conf.iface)
    except Exception as e:
        print(f"创建 L3 socket 失败: {e}")
        return

    print("开始 L3 嗅探 (3秒)...")
    try:
        sniff(
            opened_socket=sock,
            prn=lambda p: results.append(p),
            stop_filter=lambda _: False,
            timeout=3,
            store=False,
        )
        print(f"L3 嗅探完成，捕获 {len(results)} 个包")
    except Exception as e:
        print(f"L3 嗅探失败: {e}")
    finally:
        try:
            sock.close()
        except Exception:
            pass


t = threading.Thread(target=test_sniff, daemon=True)
t.start()
t.join(10)

tcp_count = 0
for pkt in results:
    if IP in pkt and TCP in pkt:
        tcp_count += 1

print(f"总计 {len(results)} 个 IP 包，其中 {tcp_count} 个 TCP 包")
if results:
    print("L3 嗅探正常工作！")
else:
    print("3秒内无包（网络空闲属正常，L3 模式已就绪）")
