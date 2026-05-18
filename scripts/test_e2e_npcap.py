"""端到端测试：npcap 抓包 → IP 解析 → 协议解码。"""
import sys
import os
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stable.protocol import NpcapCapture, PcapParser, MJProtocol

PORT = 7777
capture = NpcapCapture(server_port=PORT)
protocol = MJProtocol(server_port=PORT)
packet_count = 0
msg_count = 0


def on_ip_packet(ip_bytes: bytes):
    global packet_count, msg_count
    packet_count += 1
    pkt = PcapParser._parse_ip_tcp_static(ip_bytes)
    if pkt is not None:
        msgs = protocol.process_packet(pkt)
        for m in msgs:
            msg_count += 1
            print(f"  [{m.ts}] {m.direction} {m.type_name} sub={m.sub_type:#06x} "
                  f"size={m.size}")
            if m.game:
                print(f"    game: {m.game}")
    if packet_count % 20 == 0:
        print(f"  ... {packet_count} IP包, {msg_count} 条协议消息")


print(f"端口 {PORT}, 嗅探 8 秒...")
print(f"如果游戏在对局中，应该能看到 heartbeat/game_event 消息\n")


def run():
    try:
        capture.sniff(on_ip_packet)
    except Exception as e:
        print(f"嗅探异常: {e}")


t = threading.Thread(target=run, daemon=True)
t.start()

import time
time.sleep(8)
capture.stop()
t.join(3)

print(f"\n=== 结果 ===")
print(f"IP 包: {packet_count}")
print(f"协议消息: {msg_count}")
if msg_count > 0:
    print("端到端测试通过！npcap 模式可正常解码游戏数据。")
elif packet_count > 0:
    print("捕获到 IP 包但未解码出协议消息。可能端口过滤或帧格式不匹配。")
else:
    print("未捕获到任何包。检查游戏是否在对局中、端口是否正确。")
