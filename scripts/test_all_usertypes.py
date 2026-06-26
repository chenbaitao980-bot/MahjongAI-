#!/usr/bin/env python3
"""测试所有 usertype"""
import socket
import struct
import time
import sys
sys.path.insert(0, 'remote/srs_spectator')
from frame import pack_frame, read_frame_from_stream
from crypto import SRSCrypto
from player_connect import build_player_connect_raw


def test_usertype(usertype, pwd_type='sessionid'):
    """测试指定 usertype，返回 flag 值"""
    crypto = SRSCrypto()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect(('47.96.0.227', 7777))

    # Step 1: EncryptVer + ReqKey
    ev_ct = crypto.encrypt_payload(b'\x01\x00\x00\x00')
    sock.sendall(pack_frame(1, ev_ct))

    sock.settimeout(5)
    data = sock.recv(1024)
    sock.sendall(pack_frame(3, b''))

    # 等待 HandshakeRsp
    sock.settimeout(5)
    buf = bytearray()
    received_hs = False
    while not received_hs:
        data = sock.recv(65536)
        if not data:
            break
        buf += data
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
                break

    if not received_hs:
        sock.close()
        return None

    # Step 2: PlayerConnect
    sessionid = bytes.fromhex('ae87a919015641c1b57324c6bc88556b')
    identify = bytes.fromhex('303230303030303030303030')

    if pwd_type == 'sessionid':
        pwd = sessionid
    elif pwd_type == 'identify':
        pwd = identify
    elif pwd_type == 'empty':
        pwd = b''
    else:
        pwd = pwd_type.encode() if isinstance(pwd_type, str) else pwd_type

    pc_raw = build_player_connect_raw(
        clienttype=2,
        usertype=usertype,
        areaid=7109,
        userid=b'newpt1084306678',
        pwd=pwd,
        identify=identify,
        ver=0,
        channelid=70900,
        osver=10160,
        n_game_id=900535
    )

    pc_ct = crypto.encrypt_payload(pc_raw)
    sock.sendall(pack_frame(5, pc_ct))

    # 等待 PlayerData
    sock.settimeout(10)
    buf = bytearray()
    flag = -1
    while True:
        try:
            data = sock.recv(65536)
            if not data:
                break
            buf += data
            while True:
                frame, buf = read_frame_from_stream(buf)
                if frame is None:
                    break
                if frame['msg_type'] == 6:
                    pd_dec = crypto.decrypt_payload(frame['payload'])
                    flag = pd_dec[0] if pd_dec else -1
                    break
            if flag != -1:
                break
        except socket.timeout:
            break

    sock.close()
    return flag


if __name__ == '__main__':
    # 测试所有 usertype
    usertypes = {
        0: ('USERID', 'empty'),
        1: ('PTID', 'empty'),
        2: ('NMY', 'empty'),
        3: ('GLOBAL_ANONYMITY', 'empty'),
        5: ('IDENTIFY', 'identify'),
        6: ('DEVELOPER', 'empty'),
        7: ('SESSION', 'sessionid'),
        8: ('REGISTER', 'empty'),
        9: ('PHONENUM', 'empty'),
    }

    print('=' * 60)
    print('测试所有 usertype')
    print('=' * 60)

    results = {}
    for utype, (name, pwd_type) in usertypes.items():
        print(f'\n测试 usertype={utype} ({name})...')
        try:
            flag = test_usertype(utype, pwd_type)
            results[utype] = flag
            if flag == 0:
                print(f'  ✅ flag=0 (认证成功)')
            elif flag == 41:
                print(f'  ❌ flag=41 (格式错误)')
            elif flag == 72:
                print(f'  ❌ flag=72 (令牌过期)')
            else:
                print(f'  ❌ flag={flag} (未知错误)')
        except Exception as e:
            print(f'  ⚠️ 异常: {e}')
            results[utype] = None
        time.sleep(2)  # 间隔避免被限流

    print('\n' + '=' * 60)
    print('汇总结果')
    print('=' * 60)
    for utype, flag in results.items():
        name = usertypes[utype][0]
        if flag == 0:
            status = '✅ 成功'
        elif flag is None:
            status = '⚠️ 异常'
        else:
            status = f'❌ flag={flag}'
        print(f'  usertype={utype} ({name}): {status}')

    successful = [utype for utype, flag in results.items() if flag == 0]
    if successful:
        print(f'\n🎉 成功的 usertype: {successful}')
    else:
        print('\n[FAIL] 所有 usertype 都失败')
