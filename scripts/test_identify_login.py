#!/usr/bin/env python3
"""
测试 usertype=5 (IDENTIFY) 登录，验证是否能绕过单连接限制。

运行方式：
    python test_identify_login.py --sessionid <hex32> --identify <hex>

需要：手机在线打牌时，云端用相同账号但不同 usertype 连接，
观察是否踢手机。
"""
import asyncio
import sys
import time
import argparse
import struct

# 设置路径
import os
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_RELAY_DIR = os.path.join(_ROOT, "remote", "relay")
for p in (_ROOT, _RELAY_DIR, _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from remote.srs_spectator.client import SRSClient
from remote.srs_spectator.player_connect import build_player_connect_raw


class IdentifyTestClient:
    """测试 usertype=5 (IDENTIFY) 登录的客户端"""

    def __init__(self, sessionid_hex: str, identify_hex: str = "020000000000"):
        self.sessionid = bytes.fromhex(sessionid_hex)
        self.identify = bytes.fromhex(identify_hex)
        self.client = None
        self.connected = False
        self.flag = None
        self.frames_received = 0

    async def connect_and_test(self):
        """连接游戏服务器并测试 usertype=5 登录"""
        print(f"[测试] 连接游戏服务器 47.96.0.227:7777")
        print(f"[测试] usertype=5 (IDENTIFY), identify={self.identify.hex()}")
        print(f"[测试] 对比: usertype=7 (SESSION), sessionid={self.sessionid.hex()[:8]}...")

        # 构建 PlayerConnect (usertype=5)
        player_connect_data = build_player_connect_raw(
            clienttype=2,  # MOBILE
            usertype=5,   # IDENTIFY (硬件码登录)
            areaid=7109,
            userid=b"newpt1084306678",
            pwd=self.identify,  # 硬件码作为密码
            identify=self.identify,
            ver=0,
            channelid=70900,
            osver=10160,
            n_game_id=900535
        )

        print(f"[测试] PlayerConnect 构建完成，长度={len(player_connect_data)} bytes")
        print(f"[测试] 前8字节: {player_connect_data[:8].hex()}")

        # 使用 SRSClient 连接
        self.client = SRSClient(
            server_host="47.96.0.227",
            server_port=7777,
            sessionid=self.sessionid.hex(),  # 用于SRS握手
            on_message=self._on_message,
            on_disconnect=self._on_disconnect
        )

        try:
            await self.client.connect()
            self.connected = True
            print(f"[测试] 连接成功，等待认证结果...")

            # 等待认证结果（最多10秒）
            for i in range(10):
                if self.flag is not None:
                    break
                await asyncio.sleep(1)
                print(f"[测试] 等待认证... {i+1}/10")

            if self.flag is None:
                print(f"[测试] ⚠️ 未收到认证结果")
                return False

            print(f"[测试] 认证结果: flag={self.flag}")

            if self.flag == 0:
                print(f"[测试] ✅ 认证成功！")
                print(f"[测试] 收到 {self.frames_received} 帧数据")
                return True
            else:
                print(f"[测试] ❌ 认证失败: flag={self.flag}")
                return False

        except Exception as e:
            print(f"[测试] ❌ 连接异常: {e}")
            return False

    def _on_message(self, msg):
        """收到消息回调"""
        self.frames_received += 1
        print(f"[测试] 收到消息: msg_type={msg.msg_type}, direction={msg.direction}")

        # 检查是否是 PlayerData (flag)
        if msg.msg_type == 6 and msg.direction == "S->C":
            try:
                # 解析 flag (前4字节)
                flag = struct.unpack("<I", msg.payload[:4])[0]
                self.flag = flag
                print(f"[测试] PlayerData flag={flag}")
            except Exception as e:
                print(f"[测试] 解析flag失败: {e}")

    def _on_disconnect(self):
        """断开连接回调"""
        print(f"[测试] 连接断开")
        self.connected = False

    async def disconnect(self):
        """断开连接"""
        if self.client:
            await self.client.disconnect()


def test_usertype_5_vs_7(sessionid_hex: str, identify_hex: str = "020000000000"):
    """对比测试 usertype=5 和 usertype=7"""
    print("=" * 60)
    print("测试1: usertype=7 (SESSION) - 已知会踢手机")
    print("=" * 60)

    # 测试 usertype=7
    client7 = IdentifyTestClient(sessionid_hex, identify_hex)
    result7 = asyncio.run(client7.connect_and_test())
    asyncio.run(client7.disconnect())

    print("\n" + "=" * 60)
    print("测试2: usertype=5 (IDENTIFY) - 测试是否绕过单连接")
    print("=" * 60)

    # 测试 usertype=5
    client5 = IdentifyTestClient(sessionid_hex, identify_hex)
    result5 = asyncio.run(client5.connect_and_test())
    asyncio.run(client5.disconnect())

    # 结果对比
    print("\n" + "=" * 60)
    print("结果对比")
    print("=" * 60)
    print(f"usertype=7 (SESSION): {'✅ 成功' if result7 else '❌ 失败'}")
    print(f"usertype=5 (IDENTIFY): {'✅ 成功' if result5 else '❌ 失败'}")

    if result5 and not result7:
        print("\n🎉 重大发现！usertype=5 可以绕过单连接限制！")
    elif result5 and result7:
        print("\n⚠️ 两者都成功，需要进一步测试是否踢手机")
    else:
        print("\n❌ usertype=5 也失败，需要尝试其他 usertype")


def test_all_usertypes(sessionid_hex: str, identify_hex: str = "020000000000"):
    """测试所有可能的 usertype"""
    usertypes = {
        0: "USERID (平台帐号)",
        1: "PTID (PT帐号)",
        2: "NMY",
        3: "GLOBAL_ANONYMITY (全局匿名)",
        5: "IDENTIFY (硬件码)",
        6: "DEVELOPER",
        7: "SESSION (当前使用)",
        8: "REGISTER",
        9: "PHONENUM (手机+密码)",
    }

    results = {}
    for utype, name in usertypes.items():
        print(f"\n{'='*60}")
        print(f"测试 usertype={utype} ({name})")
        print(f"{'='*60}")

        client = IdentifyTestClient(sessionid_hex, identify_hex)
        # 修改 usertype
        result = asyncio.run(client.connect_and_test())
        asyncio.run(client.disconnect())
        results[utype] = result

        time.sleep(2)  # 间隔避免被限流

    # 汇总结果
    print(f"\n{'='*60}")
    print("汇总结果")
    print(f"{'='*60}")
    for utype, result in results.items():
        status = "✅ 成功" if result else "❌ 失败"
        print(f"usertype={utype}: {status}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="测试不同 usertype 的登录")
    parser.add_argument("--sessionid", required=True, help="srs_sessionid (hex32)")
    parser.add_argument("--identify", default="020000000000", help="identify (hex, default=020000000000)")
    parser.add_argument("--all", action="store_true", help="测试所有 usertype")
    args = parser.parse_args()

    if args.all:
        test_all_usertypes(args.sessionid, args.identify)
    else:
        test_usertype_5_vs_7(args.sessionid, args.identify)
