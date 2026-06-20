"""Decode the unsolicited mt=24 server-pushed frame from attempt 2.

Service pushes mt=24 (92B encrypted payload) right after handshake completes,
*before* fuzzer sends anything. Not in lua XY_ID closed set — possibly a hidden
server-only protocol carrying useful state.

Decryption: AES-CFB128 fresh-from-IV, session_key from handshake.
"""
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
try:
    from cryptography.hazmat.decrepit.ciphers.modes import CFB
except ImportError:
    from cryptography.hazmat.primitives.ciphers.modes import CFB

# attempt 2 capture
SESSION_KEY = bytes.fromhex("66a5b8c8f4b8da95adb1d0b3dc0659968d7d15b1f2cbaee7")
IV = bytes.fromhex("15ff010034ab4cd355fea122084f1307")  # standard fresh-from-IV

# from live-attempt-2-mt22-kicked.jsonl
FRAMES = {
    1:  ("4B keepalive ack",          "fa60a522"),
    4:  ("HandshakeRsp 25B",          "e306009a261b8737dff15956c5ee221bfb641066543fd542c3"),
    6:  ("PlayerData 76B",            "1cd5f4eb56a8312d27479b2fb22c8d3467d26cfd72e141bf481f5d3e9b0732856a574094cf79e6b661f78e989368ad603402b29029aef55610788dba0f77be0924f4b6a24c217df7c032c80e"),
    24: ("UNSOLICITED 92B mt=24",     "137e8a9c262a34bc5f7fe450c856fb5c5805f1d491dc655f3081c2de88c4231162e063c31b082a9905fb3a435adb68982cb11733453dfce6aab64ca7132d59798d0053028f0a322faa4d8c2e55267fe33e3c5aa7abbf9751fa974e5a"),
}

def dec(key, ct):
    return Cipher(algorithms.AES(key), CFB(IV)).decryptor().update(ct)

print("="*78)
print(f"session key: {SESSION_KEY.hex()} ({len(SESSION_KEY)*8}-bit)")
print("="*78)

for mt, (label, hex_ct) in FRAMES.items():
    ct = bytes.fromhex(hex_ct)
    pt = dec(SESSION_KEY, ct)
    print(f"\n--- mt={mt} {label} ({len(ct)}B) ---")
    print(f"  ct hex: {ct.hex()}")
    print(f"  pt hex: {pt.hex()}")
    # ASCII slice (printable runs)
    ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in pt)
    print(f"  ascii : {ascii_str}")
    # int candidates: read as <I, <H, <i pairs at offsets 0,4,8...
    if len(pt) >= 4:
        import struct
        u32_le = [struct.unpack("<I", pt[i:i+4])[0] for i in range(0, len(pt) - 3, 4)]
        print(f"  u32_le: {u32_le[:16]}{' ...' if len(u32_le) > 16 else ''}")
