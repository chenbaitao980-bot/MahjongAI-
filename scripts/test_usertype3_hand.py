#!/usr/bin/env python3
"""测试 usertype=3 (GLOBAL_ANONYMITY) 登录后能否收到手牌帧，且手机是否被踢。

使用方法：
  手机在线打牌时运行：
  python scripts/test_usertype3_hand.py

  或指定 usertype：
  python scripts/test_usertype3_hand.py --usertype 0
"""
import argparse
import socket
import time
import sys
import os

sys.path.insert(0, 'remote/srs_spectator')
from frame import pack_frame, read_frame_from_stream
from crypto import SRSCrypto
from player_connect import build_player_connect_raw

MSG_HAND = 0x2bc0
MSG_DRAW = 0x2be0
MSG_DISCARD = 0x2bf0
INTERESTING_MSGS = {
    MSG_HAND: '手牌(0x2bc0)',
    MSG_DRAW: '摸牌(0x2be0)',
    MSG_DISCARD: '弃牌(0x2bf0)',
    0x0006: 'PlayerData',
    0x4001: '通用帧',
}


def run(usertype: int = 3, listen_seconds: int = 60):
    print(f'=== 测试 usertype={usertype}, 监听 {listen_seconds}s ===')
    print(f'服务器: 47.96.0.227:7777')
    print(f'userid: newpt1084306678')
    print()

    crypto = SRSCrypto()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)

    try:
        sock.connect(('47.96.0.227', 7777))
        print('[1] TCP 连接成功')
    except Exception as e:
        print(f'[FAIL] TCP 连接失败: {e}')
        return

    # Step 1: EncryptVer
    ev_ct = crypto.encrypt_payload(b'\x01\x00\x00\x00')
    sock.sendall(pack_frame(1, ev_ct))
    print('[2] EncryptVer 已发送')

    # echo
    try:
        sock.recv(1024)
    except:
        pass

    # ReqKey
    sock.sendall(pack_frame(3, b''))
    print('[3] ReqKey 已发送')

    # HandshakeRsp
    buf = bytearray()
    sock.settimeout(5)
    received_hs = False
    for _ in range(20):
        try:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
            while True:
                frame, buf = read_frame_from_stream(buf)
                if frame is None:
                    break
                if frame['msg_type'] == 4:
                    hs_dec = crypto.decrypt_payload(frame['payload'])
                    key_len = hs_dec[0]
                    session_key = hs_dec[1:1+key_len]
                    crypto.set_key(session_key)
                    received_hs = True
                    print(f'[4] HandshakeRsp OK, session_key={session_key.hex()[:16]}...')
        except socket.timeout:
            pass
        if received_hs:
            break

    if not received_hs:
        print('[FAIL] 未收到 HandshakeRsp')
        sock.close()
        return

    # PlayerConnect
    identify = bytes.fromhex('303230303030303030303030')
    pc_raw = build_player_connect_raw(
        clienttype=2,
        usertype=usertype,
        areaid=7109,
        userid=b'newpt1084306678',
        pwd=b'',  # 空密码
        identify=identify,
        ver=0,
        channelid=70900,
        osver=10160,
        n_game_id=900535,
    )
    pc_ct = crypto.encrypt_payload(pc_raw)
    sock.sendall(pack_frame(5, pc_ct))
    print(f'[5] PlayerConnect(usertype={usertype}, pwd=empty) 已发送')

    # 等待 PlayerData
    sock.settimeout(10)
    buf = bytearray()
    flag = None
    frames_count = 0
    hand_frames = 0
    start = time.time()

    print(f'[6] 等待响应中... (最多 {listen_seconds}s)')
    print()

    while time.time() - start < listen_seconds:
        try:
            chunk = sock.recv(65536)
            if not chunk:
                print('[!] 连接被关闭（服务端踢线或断开）')
                break
            buf += chunk
        except socket.timeout:
            continue
        except Exception as e:
            print(f'[!] 错误: {e}')
            break

        while True:
            frame, buf = read_frame_from_stream(buf)
            if frame is None:
                break

            frames_count += 1
            mt = frame['msg_type']
            pl_raw = frame.get('payload', b'')

            try:
                pl = crypto.decrypt_payload(pl_raw) if pl_raw else b''
            except Exception:
                pl = pl_raw

            elapsed = time.time() - start
            label = INTERESTING_MSGS.get(mt, f'未知(0x{mt:04x})')

            if mt == 0x0006:  # PlayerData
                flag_val = pl[0] if pl else -1
                import struct
                if len(pl) >= 5:
                    areaid = struct.unpack_from('<I', pl, 1)[0]
                    uid = struct.unpack_from('<I', pl, 5)[0] if len(pl) >= 9 else 0
                    print(f'[{elapsed:.1f}s] PlayerData flag={flag_val}, areaid={areaid}, userid={uid}')
                else:
                    print(f'[{elapsed:.1f}s] PlayerData flag={flag_val}')
                flag = flag_val
                if flag_val != 0:
                    print(f'[!] 认证失败 flag={flag_val}, 停止')
                    sock.close()
                    return

            elif mt in (MSG_HAND, MSG_DRAW, MSG_DISCARD):
                hand_frames += 1
                print(f'[{elapsed:.1f}s] 🎯 {label} !! payload={pl[:30].hex()}')

            elif mt != 0x4001:
                print(f'[{elapsed:.1f}s] {label} payload={pl[:16].hex()}')

    elapsed_total = time.time() - start
    print()
    print(f'=== 结果 ({elapsed_total:.0f}s) ===')
    print(f'  连接持续: {elapsed_total:.1f}s')
    print(f'  总帧数: {frames_count}')
    print(f'  手牌/摸牌/弃牌帧: {hand_frames}')
    if flag is not None:
        print(f'  认证 flag: {flag}')
    sock.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--usertype', type=int, default=3)
    parser.add_argument('--seconds', type=int, default=60)
    args = parser.parse_args()
    run(args.usertype, args.seconds)
