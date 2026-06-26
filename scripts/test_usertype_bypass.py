#!/usr/bin/env python3
"""
测试不同 usertype 登录，验证是否能绕过单连接限制。

核心发现：SRSProtocol.lua 中 USERTYPE 枚举包含多种登录方式：
  - 0: USERID (平台帐号)
  - 1: PTID (PT帐号)
  - 5: IDENTIFY (硬件码登录)
  - 7: SESSION (当前使用，已验证会踢手机)
  - 9: PHONENUM (手机+密码登录)

测试目标：找到不踢手机的 usertype。

运行方式：
    python test_usertype_bypass.py --sessionid <hex32> [--usertype 5]
"""
import socket
import struct
import time
import argparse
import sys
import os

# 设置路径
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
for p in (_ROOT, _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

# 导入 srs_spectator 模块
from remote.srs_spectator.frame import pack_frame, read_frame_from_stream, MSG_NAMES
from remote.srs_spectator.crypto import SRSCrypto


# 消息类型常量
MSG_ENCRYPT_VER = 1
MSG_HANDSHAKE_RSP = 4
MSG_PLAYER_CONNECT = 5
MSG_PLAYER_DATA = 6
MSG_REQ_PLUS_DATA = 23
MSG_RESP_PLUS_DATA = 24

# 固定 payload
ENCRYPT_VER_PLAINTEXT = b"\x01\x00\x00\x00"


def build_player_connect_custom(
    usertype: int = 7,
    userid: bytes = b"newpt1084306678",
    pwd: bytes = b"",
    identify: bytes = b"020000000000",
    areaid: int = 7109,
    ver: int = 0,
    channelid: int = 70900,
    osver: int = 10160,
    n_game_id: int = 900535,
) -> bytes:
    """Build PlayerConnect with custom usertype."""
    bos = bytearray()
    bos.append(2)   # clienttype = MOBILE
    bos.append(usertype)
    bos += struct.pack("<I", areaid)

    # userid (string)
    bos += struct.pack("<H", len(userid))
    bos += userid

    # pwd: SESSION mode = 16B raw, others = string
    if usertype == 7:
        bos += pwd[:16].ljust(16, b"\x00")
    else:
        bos += struct.pack("<H", len(pwd))
        bos += pwd

    # identify (string)
    bos += struct.pack("<H", len(identify))
    bos += identify

    bos += struct.pack("<i", ver)
    bos += struct.pack("<i", channelid)
    bos += struct.pack("<i", osver)

    # identify again
    bos += struct.pack("<H", len(identify))
    bos += identify

    bos += struct.pack("<i", n_game_id)

    return bytes(bos)


def parse_player_data(payload: bytes) -> dict:
    """Parse PlayerData response."""
    if len(payload) < 9:
        return {"error": "payload too short"}

    offset = 0
    flag = payload[offset]
    offset += 1
    areaid = struct.unpack_from("<i", payload, offset)[0]
    offset += 4
    numid = struct.unpack_from("<i", payload, offset)[0]
    offset += 4

    nick_len = struct.unpack_from("<H", payload, offset)[0]
    offset += 2
    nick_end = min(offset + nick_len, len(payload))
    nickname = payload[offset:nick_end].decode("utf-8", errors="replace")
    offset = nick_end

    if offset + 2 > len(payload):
        return {"flag": flag, "areaid": areaid, "numid": numid, "nickname": nickname}

    url_len = struct.unpack_from("<H", payload, offset)[0]
    offset += 2
    offset += url_len

    sessionid = b""
    if offset + 16 <= len(payload):
        sessionid = payload[offset:offset+16]

    return {
        "flag": flag,
        "areaid": areaid,
        "numid": numid,
        "nickname": nickname,
        "sessionid": sessionid,
    }


class TestClient:
    """测试不同 usertype 的客户端"""

    def __init__(self, sessionid_hex: str, usertype: int = 7, identify_hex: str = "020000000000"):
        self.sessionid = bytes.fromhex(sessionid_hex)
        self.usertype = usertype
        self.identify = bytes.fromhex(identify_hex)
        self.sock = None
        self.crypto = SRSCrypto()
        self.recv_buf = bytearray()
        self.running = False
        self.flag = None
        self.frames_received = 0
        self.auth_success = False

    def connect(self, timeout: float = 10.0) -> bool:
        """连接游戏服务器"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(timeout)
            self.sock.connect(("47.96.0.227", 7777))
            self.sock.settimeout(None)
            print(f"  [OK] TCP 连接成功")
        except Exception as e:
            print(f"  [FAIL] TCP 连接失败: {e}")
            return False

        self.running = True

        # Step 1: EncryptVer
        ev_ct = self.crypto.encrypt_payload(ENCRYPT_VER_PLAINTEXT)
        self._send_raw(pack_frame(MSG_ENCRYPT_VER, ev_ct))
        print(f"  -> EncryptVer 已发送")

        # 等待 HandshakeRsp
        if not self._wait_for_handshake_rsp(timeout):
            return False

        # Step 2: PlayerConnect (使用指定的 usertype)
        pc_raw = self._build_player_connect()
        pc_ct = self.crypto.encrypt_payload(pc_raw)
        self._send_raw(pack_frame(MSG_PLAYER_CONNECT, pc_ct))
        print(f"  -> PlayerConnect (usertype={self.usertype}) 已发送")

        # 等待 PlayerData
        return self._wait_for_player_data(timeout)

    def _build_player_connect(self) -> bytes:
        """构建 PlayerConnect，使用指定的 usertype"""
        if self.usertype == 7:
            pwd = self.sessionid
        elif self.usertype == 5:
            pwd = self.identify
        elif self.usertype == 9:
            pwd = b"13800138000_123456"  # 占位符
        else:
            pwd = b""

        return build_player_connect_custom(
            usertype=self.usertype,
            userid=b"newpt1084306678",
            pwd=pwd,
            identify=self.identify,
        )

    def _send_raw(self, data: bytes) -> None:
        """发送原始数据"""
        if self.sock:
            try:
                self.sock.sendall(data)
            except Exception as e:
                print(f"  [WARN] 发送失败: {e}")

    def _wait_for_handshake_rsp(self, timeout: float) -> bool:
        """等待 HandshakeRsp"""
        deadline = time.time() + timeout
        while time.time() < deadline and self.running:
            try:
                self.sock.settimeout(1.0)
                data = self.sock.recv(65536)
                if not data:
                    print(f"  [FAIL] 连接被关闭")
                    return False
                self.recv_buf += data
                frame, self.recv_buf = read_frame_from_stream(self.recv_buf)
                if frame and frame["msg_type"] == MSG_HANDSHAKE_RSP:
                    hs_dec = self.crypto.decrypt_payload(frame["payload"])
                    key_len = hs_dec[0]
                    session_key = hs_dec[1:1+key_len]
                    self.crypto.set_key(session_key)
                    print(f"  [OK] HandshakeRsp 收到，session key 已设置")
                    return True
            except socket.timeout:
                continue
            except Exception as e:
                print(f"  [FAIL] 接收错误: {e}")
                return False
        print(f"  [FAIL] 等待 HandshakeRsp 超时")
        return False

    def _wait_for_player_data(self, timeout: float) -> bool:
        """等待 PlayerData (认证结果)"""
        deadline = time.time() + timeout
        while time.time() < deadline and self.running:
            try:
                self.sock.settimeout(1.0)
                data = self.sock.recv(65536)
                if not data:
                    print(f"  [WARN] 连接被关闭（可能被踢）")
                    return False
                self.recv_buf += data
                while True:
                    frame, self.recv_buf = read_frame_from_stream(self.recv_buf)
                    if frame is None:
                        break
                    if frame["msg_type"] == MSG_PLAYER_DATA:
                        pd_dec = self.crypto.decrypt_payload(frame["payload"])
                        self.flag = pd_dec[0] if pd_dec else -1
                        result = parse_player_data(pd_dec)
                        if self.flag == 0:
                            self.auth_success = True
                            sessionid = result.get("sessionid", b"")
                            print(f"  [OK] 认证成功！flag=0, sessionid={sessionid.hex()[:16]}...")
                            # 请求 PlusData
                            self._send_raw(pack_frame(MSG_REQ_PLUS_DATA, b""))
                            return True
                        else:
                            print(f"  [FAIL] 认证失败: flag={self.flag}")
                            return False
                    elif frame["msg_type"] == MSG_RESP_PLUS_DATA:
                        print(f"  [OK] m_key 已设置，可以接收游戏帧")
            except socket.timeout:
                continue
            except Exception as e:
                print(f"  [FAIL] 接收错误: {e}")
                return False
        print(f"  [FAIL] 等待 PlayerData 超时")
        return False

    def disconnect(self):
        """断开连接"""
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None


def test_single_usertype(sessionid_hex: str, usertype: int, identify_hex: str = "020000000000"):
    """测试单个 usertype"""
    type_names = {
        0: "USERID (平台帐号)",
        1: "PTID (PT帐号)",
        2: "NMY",
        3: "GLOBAL_ANONYMITY",
        5: "IDENTIFY (硬件码)",
        6: "DEVELOPER",
        7: "SESSION (当前使用)",
        8: "REGISTER",
        9: "PHONENUM (手机+密码)",
    }
    name = type_names.get(usertype, f"UNKNOWN({usertype})")

    print(f"\n{'='*60}")
    print(f"测试 usertype={usertype} ({name})")
    print(f"{'='*60}")

    client = TestClient(sessionid_hex, usertype, identify_hex)
    try:
        success = client.connect(timeout=10.0)
        return success
    finally:
        client.disconnect()
        time.sleep(1)


def test_all_usertypes(sessionid_hex: str, identify_hex: str = "020000000000"):
    """测试所有可能的 usertype"""
    usertypes = [0, 1, 2, 3, 5, 6, 7, 8, 9]
    results = {}

    print(f"\n{'#'*60}")
    print(f"# 批量测试所有 usertype")
    print(f"# sessionid: {sessionid_hex[:16]}...")
    print(f"# identify: {identify_hex}")
    print(f"{'#'*60}")

    for utype in usertypes:
        success = test_single_usertype(sessionid_hex, utype, identify_hex)
        results[utype] = success
        time.sleep(2)  # 间隔避免被限流

    # 汇总
    print(f"\n{'='*60}")
    print("汇总结果")
    print(f"{'='*60}")
    for utype, success in results.items():
        status = "[OK] 成功" if success else "[FAIL] 失败"
        print(f"  usertype={utype}: {status}")

    # 找出最佳候选
    successful = [utype for utype, ok in results.items() if ok]
    if successful:
        print(f"\n🎉 成功的 usertype: {successful}")
        if 7 in successful:
            print("[WARN] usertype=7 也成功，说明 sessionid 未被占用或测试时手机不在线")
        if 5 in successful and 7 not in successful:
            print("🎉🎉🎉 重大发现！usertype=5 (IDENTIFY) 可以绕过单连接限制！")
    else:
        print("\n[FAIL] 所有 usertype 都失败")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="测试不同 usertype 绕过单连接限制")
    parser.add_argument("--sessionid", required=True, help="srs_sessionid (hex32)")
    parser.add_argument("--identify", default="020000000000", help="identify (hex)")
    parser.add_argument("--usertype", type=int, default=None, help="只测试指定 usertype")
    parser.add_argument("--all", action="store_true", help="测试所有 usertype")
    args = parser.parse_args()

    if args.all:
        test_all_usertypes(args.sessionid, args.identify)
    elif args.usertype is not None:
        test_single_usertype(args.sessionid, args.usertype, args.identify)
    else:
        # 默认测试 usertype=5 (IDENTIFY)
        test_single_usertype(args.sessionid, 5, args.identify)
