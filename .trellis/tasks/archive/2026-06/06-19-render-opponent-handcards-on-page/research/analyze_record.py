"""分析 a4v5 record，提取所有 0x2BC0/0x2BC1 帧并 hand-raw"""
import struct, sys

def parse_record(data):
    print(f"Record size: {len(data)} bytes")
    # The record format begins with a 16B-string offset/timestamp prefix repeated
    # but contains embedded SRS frames. Walk looking for flag=0x4001 + valid frame.
    # Actually the record format is custom — let me try walking 12B headers.
    off = 0
    cnt = 0
    found_2bc0 = []
    while off < len(data) and cnt < 5000:
        # try parse SRS frame header at offset
        if off + 12 > len(data):
            break
        hdr = data[off:off+12]
        flag, pay_len, mt, sub, extra = struct.unpack("<HHHHI", hdr)
        if flag == 0x4001 and pay_len <= 65535 and off + 12 + pay_len <= len(data):
            body = data[off+12:off+12+pay_len]
            if mt in (0x2BC0, 0x2BC1):
                if len(body) >= 4:
                    sc = int.from_bytes(body[0:2], "little")
                    dl = int.from_bytes(body[2:4], "little")
                    sub_body = body[4:4+dl] if 4+dl <= len(body) else b""
                    print(f"@{off}: 0x{mt:04x} sub_cmd=0x{sc:04x} dl={dl} body={sub_body[:48].hex()}")
                    if sc == 0x0003 and len(sub_body) >= 13:
                        h13 = list(sub_body[:13])
                        print(f"   DEAL hand[:13]={h13} has_3c={0x3c in h13}")
                    elif sc == 0x0216 and len(sub_body) >= 3:
                        pl = sub_body[0]
                        ct = sub_body[2]
                        if 0 < ct <= 20 and len(sub_body) >= 3+ct:
                            h = list(sub_body[3:3+ct])
                            print(f"   HAND_UPDATE player={pl} count={ct} hand={h} has_3c={0x3c in h}")
                    found_2bc0.append((off, mt, sc, sub_body))
            off += 12 + pay_len
            cnt += 1
        else:
            off += 1
    print(f"\nTotal 0x2BC0/2BC1 frames found: {len(found_2bc0)}")
    return found_2bc0

# Also brute-force 13-byte windows of bytes in [0x00..0x37] looking for hand
def find_hand_windows(data):
    print("\n=== Brute search 13-byte windows in [0x00..0x37] (no-3c) ===")
    found = []
    i = 0
    while i + 13 <= len(data):
        win = data[i:i+13]
        if all(0 <= b <= 0x37 for b in win) and len(set(win)) >= 8:
            found.append((i, list(win)))
            i += 13
        else:
            i += 1
    print(f"Found {len(found)} candidate hands:")
    for off, win in found[:30]:
        print(f"  @{off}: {win}")
    return found

def find_3c_runs(data):
    """3c 是隐藏占位牌；找连续 ≥7 个 0x3c 的位置"""
    print("\n=== Find 0x3c runs (hidden tile placeholder) ===")
    runs = []
    i = 0
    while i < len(data):
        if data[i] == 0x3c:
            j = i
            while j < len(data) and data[j] == 0x3c:
                j += 1
            n = j - i
            if n >= 7:
                runs.append((i, n))
            i = j
        else:
            i += 1
    for off, n in runs[:30]:
        print(f"  @{off}: {n} consecutive 0x3c, context_before={data[max(0,off-20):off].hex()} after={data[off+n:off+n+20].hex()}")
    return runs

if __name__ == "__main__":
    data = open(sys.argv[1], "rb").read()
    find_3c_runs(data)
    find_hand_windows(data)
    parse_record(data)
