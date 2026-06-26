"""
noconfig/test_dual_session.py — 方向 A 测试：不同 sessionid 同时在线

测试目标：验证"同一账号、不同 sessionid"能否同时连接游戏服务器，
即手机用一个 sessionid 打牌时，云端用另一个 sessionid 连接是否会被踢。

用法：
    # 测试 A1：同一 sessionid（验证单连接限制）
    python remote/noconfig/test_dual_session.py --mode same --sessionid <hex32>

    # 测试 A2：不同 sessionid（需要两个 sessionid）
    python remote/noconfig/test_dual_session.py --mode different \
        --sessionid-a <hex32> --sessionid-b <hex32>

    # 测试 A3：快速重连抢帧（方向 C）
    python remote/noconfig/test_dual_session.py --mode rapid-reconnect --sessionid <hex32>

注意：
    - 本脚本只修改 remote/noconfig/ 目录，不影响 hotspot/ 和 vpn/
    - 测试前请确保手机已连热点，extractor 正在运行
    - 测试结果会输出到控制台和日志文件
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import threading
from typing import Optional

# ── sys.path 设置 ──────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_SPECTATOR_DIR = os.path.join(_ROOT, "remote", "srs_spectator")

if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if _SPECTATOR_DIR not in sys.path:
    sys.path.insert(0, _SPECTATOR_DIR)

# 导入 SRSClient
from remote.srs_spectator.client import SRSClient

# ── 日志设置 ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_LOGGER = logging.getLogger("noconfig.test_dual_session")

# ── 常量 ────────────────────────────────────────────────────────

GAME_SERVER_HOST = "47.96.0.227"
GAME_SERVER_PORT = 7777
DEFAULT_USERID = "newpt1084306678"


# ── 测试 A1：同一 sessionid ─────────────────────────────────────

def test_same_sessionid(sessionid: str, duration: int = 60) -> dict:
    """测试同一 sessionid 能否同时维持两条连接。

    方法：
      1. 先启动连接 A（模拟手机）
      2. 5 秒后启动连接 B（模拟云端）
      3. 观察连接 A 是否被踢
      4. 观察连接 B 的 flag

    Returns:
        dict: {"connection_a_alive": bool, "connection_b_flag": int,
               "connection_a_kicked": bool, "notes": str}
    """
    _LOGGER.info("=" * 60)
    _LOGGER.info("[测试 A1] 同一 sessionid 双连接测试")
    _LOGGER.info("  sessionid: %s...", sessionid[:16])
    _LOGGER.info("  步骤: 连接A(模拟手机) → 5秒后 连接B(模拟云端) → 观察结果")
    _LOGGER.info("=" * 60)

    results = {
        "test": "A1_same_sessionid",
        "sessionid": sessionid[:16] + "...",
        "connection_a_alive": False,
        "connection_b_flag": -1,
        "connection_a_kicked": False,
        "notes": "",
    }

    # 连接 A（模拟手机）
    client_a = None
    client_b = None
    a_connected = threading.Event()
    b_connected = threading.Event()
    a_disconnected = threading.Event()
    b_flag = [-1]

    def on_a_connected():
        _LOGGER.info("[连接A] 手机端握手成功，等待 5 秒后启动云端...")
        a_connected.set()

    def on_a_disconnected():
        _LOGGER.warning("[连接A] 手机端被断开！")
        a_disconnected.set()

    def on_b_handshake_done():
        _LOGGER.info("[连接B] 云端握手成功")
        b_connected.set()

    def on_b_frame(msg_type: int, payload: bytes):
        if msg_type == 6:  # PlayerData
            _LOGGER.info("[连接B] 收到 PlayerData，flag=%d", payload[0] if payload else -1)
            b_flag[0] = payload[0] if payload else -1

    # 启动连接 A
    _LOGGER.info("[步骤 1/4] 启动连接 A（模拟手机）...")
    client_a = SRSClient(
        GAME_SERVER_HOST, GAME_SERVER_PORT,
        auth_token="", handshake_blob="", srs_sessionid=sessionid,
        userid=DEFAULT_USERID,
    )
    client_a.on_handshake_done(on_a_connected)
    client_a.on_disconnect(on_a_disconnected)

    if not client_a.connect(timeout=10.0):
        _LOGGER.error("[连接A] TCP 连接失败")
        results["notes"] = "连接A TCP失败"
        return results

    # 等待连接 A 完成握手
    if not a_connected.wait(timeout=15.0):
        _LOGGER.error("[连接A] 握手超时")
        results["notes"] = "连接A握手超时"
        client_a.disconnect()
        return results

    results["connection_a_alive"] = True
    _LOGGER.info("[步骤 2/4] 连接 A 握手成功，等待 5 秒后启动连接 B...")
    time.sleep(5.0)

    # 启动连接 B（模拟云端）
    _LOGGER.info("[步骤 3/4] 启动连接 B（模拟云端）...")
    client_b = SRSClient(
        GAME_SERVER_HOST, GAME_SERVER_PORT,
        auth_token="", handshake_blob="", srs_sessionid=sessionid,
        userid=DEFAULT_USERID,
    )
    client_b.on_handshake_done(on_b_handshake_done)
    client_b.on_frame(on_b_frame)

    if not client_b.connect(timeout=10.0):
        _LOGGER.error("[连接B] TCP 连接失败")
        results["notes"] = "连接B TCP失败"
        client_a.disconnect()
        return results

    # 等待连接 B 完成握手
    if not b_connected.wait(timeout=15.0):
        _LOGGER.error("[连接B] 握手超时")
        results["notes"] = "连接B握手超时"
        client_a.disconnect()
        client_b.disconnect()
        return results

    # 观察 10 秒
    _LOGGER.info("[步骤 4/4] 两条连接均建立，观察 10 秒...")
    time.sleep(10.0)

    # 检查结果
    results["connection_b_flag"] = b_flag[0]
    results["connection_a_kicked"] = a_disconnected.is_set()

    if a_disconnected.is_set():
        _LOGGER.warning("[结果] 连接A（手机）被踢！单连接限制确认。")
        results["notes"] = "连接A被踢，单连接限制确认"
    else:
        _LOGGER.info("[结果] 连接A（手机）仍然存活！单连接限制可能不存在。")
        results["notes"] = "连接A存活，单连接限制可能不存在"

    # 清理
    client_a.disconnect()
    client_b.disconnect()
    time.sleep(1.0)

    return results


# ── 测试 A2：不同 sessionid ────────────────────────────────────

def test_different_sessionid(sessionid_a: str, sessionid_b: str, duration: int = 60) -> dict:
    """测试不同 sessionid 能否同时维持两条连接。

    方法：
      1. 启动连接 A（sessionid_a，模拟手机）
      2. 5 秒后启动连接 B（sessionid_b，模拟云端）
      3. 观察两条连接是否共存

    Returns:
        dict: {"both_alive": bool, "a_flag": int, "b_flag": int, "notes": str}
    """
    _LOGGER.info("=" * 60)
    _LOGGER.info("[测试 A2] 不同 sessionid 双连接测试")
    _LOGGER.info("  sessionid_a: %s...", sessionid_a[:16])
    _LOGGER.info("  sessionid_b: %s...", sessionid_b[:16])
    _LOGGER.info("  步骤: 连接A(手机,sid_a) → 5秒后 连接B(云端,sid_b) → 观察共存")
    _LOGGER.info("=" * 60)

    results = {
        "test": "A2_different_sessionid",
        "sessionid_a": sessionid_a[:16] + "...",
        "sessionid_b": sessionid_b[:16] + "...",
        "both_alive": False,
        "a_flag": -1,
        "b_flag": -1,
        "notes": "",
    }

    # 连接 A
    client_a = None
    client_b = None
    a_connected = threading.Event()
    b_connected = threading.Event()
    a_disconnected = threading.Event()
    b_disconnected = threading.Event()
    a_flag = [-1]
    b_flag = [-1]

    def make_on_connected(name: str, event: threading.Event):
        def on_connected():
            _LOGGER.info(f"[{name}] 握手成功")
            event.set()
        return on_connected

    def make_on_disconnected(name: str, event: threading.Event):
        def on_disconnected():
            _LOGGER.warning(f"[{name}] 被断开！")
            event.set()
        return on_disconnected

    def make_on_frame(name: str, flag_store: list):
        def on_frame(msg_type: int, payload: bytes):
            if msg_type == 6:  # PlayerData
                flag = payload[0] if payload else -1
                _LOGGER.info(f"[{name}] 收到 PlayerData，flag={flag}")
                flag_store[0] = flag
        return on_frame

    # 启动连接 A
    _LOGGER.info("[步骤 1/4] 启动连接 A（模拟手机，sessionid_a）...")
    client_a = SRSClient(
        GAME_SERVER_HOST, GAME_SERVER_PORT,
        auth_token="", handshake_blob="", srs_sessionid=sessionid_a,
        userid=DEFAULT_USERID,
    )
    client_a.on_handshake_done(make_on_connected("连接A", a_connected))
    client_a.on_disconnect(make_on_disconnected("连接A", a_disconnected))
    client_a.on_frame(make_on_frame("连接A", a_flag))

    if not client_a.connect(timeout=10.0):
        _LOGGER.error("[连接A] TCP 连接失败")
        results["notes"] = "连接A TCP失败"
        return results

    if not a_connected.wait(timeout=15.0):
        _LOGGER.error("[连接A] 握手超时")
        results["notes"] = "连接A握手超时"
        client_a.disconnect()
        return results

    _LOGGER.info("[步骤 2/4] 连接 A 握手成功，等待 5 秒后启动连接 B...")
    time.sleep(5.0)

    # 启动连接 B
    _LOGGER.info("[步骤 3/4] 启动连接 B（模拟云端，sessionid_b）...")
    client_b = SRSClient(
        GAME_SERVER_HOST, GAME_SERVER_PORT,
        auth_token="", handshake_blob="", srs_sessionid=sessionid_b,
        userid=DEFAULT_USERID,
    )
    client_b.on_handshake_done(make_on_connected("连接B", b_connected))
    client_b.on_disconnect(make_on_disconnected("连接B", b_disconnected))
    client_b.on_frame(make_on_frame("连接B", b_flag))

    if not client_b.connect(timeout=10.0):
        _LOGGER.error("[连接B] TCP 连接失败")
        results["notes"] = "连接B TCP失败"
        client_a.disconnect()
        return results

    if not b_connected.wait(timeout=15.0):
        _LOGGER.error("[连接B] 握手超时")
        results["notes"] = "连接B握手超时"
        client_a.disconnect()
        client_b.disconnect()
        return results

    # 观察
    _LOGGER.info("[步骤 4/4] 两条连接均建立，观察 10 秒...")
    time.sleep(10.0)

    # 检查结果
    results["a_flag"] = a_flag[0]
    results["b_flag"] = b_flag[0]
    results["both_alive"] = not a_disconnected.is_set() and not b_disconnected.is_set()

    if results["both_alive"]:
        _LOGGER.info("[结果] 两条连接均存活！不同 sessionid 可以共存。")
        results["notes"] = "两条连接均存活，不同 sessionid 可以共存"
    else:
        kicked = []
        if a_disconnected.is_set():
            kicked.append("连接A")
        if b_disconnected.is_set():
            kicked.append("连接B")
        _LOGGER.warning("[结果] %s 被踢！不同 sessionid 不能共存。", ", ".join(kicked))
        results["notes"] = f"{', '.join(kicked)} 被踢，不能共存"

    # 清理
    client_a.disconnect()
    client_b.disconnect()
    time.sleep(1.0)

    return results


# ── 测试 C：快速重连抢帧 ──────────────────────────────────────

def test_rapid_reconnect(sessionid: str, reconnect_interval: float = 2.0, duration: int = 60) -> dict:
    """测试高频重连能否抢到游戏帧。

    方法：
      1. 手机正常打牌（保持在线）
      2. 云端用同一 sessionid 快速重连
      3. 统计每次连接能抢到多少帧

    Args:
        sessionid: 要测试的 sessionid
        reconnect_interval: 重连间隔（秒）
        duration: 总测试时长（秒）

    Returns:
        dict: {"total_attempts": int, "successful_connects": int, "total_frames": int,
               "avg_frames_per_connect": float, "notes": str}
    """
    _LOGGER.info("=" * 60)
    _LOGGER.info("[测试 C] 快速重连抢帧测试")
    _LOGGER.info("  sessionid: %s...", sessionid[:16])
    _LOGGER.info("  重连间隔: %.1f 秒", reconnect_interval)
    _LOGGER.info("  总时长: %d 秒", duration)
    _LOGGER.info("=" * 60)

    results = {
        "test": "C_rapid_reconnect",
        "sessionid": sessionid[:16] + "...",
        "total_attempts": 0,
        "successful_connects": 0,
        "total_frames": 0,
        "avg_frames_per_connect": 0.0,
        "notes": "",
    }

    start_time = time.time()
    frames_per_connect = []

    while time.time() - start_time < duration:
        results["total_attempts"] += 1
        attempt = results["total_attempts"]

        _LOGGER.info("[尝试 %d] 连接中...", attempt)
        client = SRSClient(
            GAME_SERVER_HOST, GAME_SERVER_PORT,
            auth_token="", handshake_blob="", srs_sessionid=sessionid,
            userid=DEFAULT_USERID,
        )

        connected = threading.Event()
        disconnected = threading.Event()
        frames_received = [0]

        def on_connected():
            connected.set()

        def on_disconnected():
            disconnected.set()

        def on_frame(msg_type: int, payload: bytes):
            if msg_type == 0x2BC0:  # 游戏事件帧
                frames_received[0] += 1

        client.on_handshake_done(on_connected)
        client.on_disconnect(on_disconnected)
        client.on_frame(on_frame)

        connect_start = time.time()
        if not client.connect(timeout=10.0):
            _LOGGER.warning("[尝试 %d] TCP 连接失败", attempt)
            time.sleep(reconnect_interval)
            continue

        # 等待握手完成
        if not connected.wait(timeout=15.0):
            _LOGGER.warning("[尝试 %d] 握手超时", attempt)
            client.disconnect()
            time.sleep(reconnect_interval)
            continue

        # 等待被踢或超时
        connect_duration = time.time() - connect_start
        if not disconnected.wait(timeout=5.0):  # 最多等 5 秒
            _LOGGER.info("[尝试 %d] 5秒内未被踢，手动断开", attempt)
            client.disconnect()

        # 记录结果
        if frames_received[0] > 0:
            results["successful_connects"] += 1
            results["total_frames"] += frames_received[0]
            frames_per_connect.append(frames_received[0])
            _LOGGER.info("[尝试 %d] 抢到 %d 帧", attempt, frames_received[0])
        else:
            _LOGGER.info("[尝试 %d] 未抢到帧", attempt)

        # 等待重连间隔
        elapsed = time.time() - connect_start
        if elapsed < reconnect_interval:
            time.sleep(reconnect_interval - elapsed)

    # 汇总
    if results["successful_connects"] > 0:
        results["avg_frames_per_connect"] = results["total_frames"] / results["successful_connects"]

    _LOGGER.info("=" * 60)
    _LOGGER.info("[测试 C 结果]")
    _LOGGER.info("  总尝试次数: %d", results["total_attempts"])
    _LOGGER.info("  成功连接数: %d", results["successful_connects"])
    _LOGGER.info("  总帧数: %d", results["total_frames"])
    _LOGGER.info("  平均每连接帧数: %.1f", results["avg_frames_per_connect"])
    _LOGGER.info("=" * 60)

    results["notes"] = f"尝试{results['total_attempts']}次，成功{results['successful_connects']}次，抢到{results['total_frames']}帧"
    return results


# ── 主入口 ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="方向 A 测试：不同 sessionid 同时在线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 测试 A1：同一 sessionid（验证单连接限制）
  python remote/noconfig/test_dual_session.py --mode same --sessionid a269e12a1ca5442db00ec625a0d0e619

  # 测试 A2：不同 sessionid（需要两个 sessionid）
  python remote/noconfig/test_dual_session.py --mode different \\
      --sessionid-a a269e12a1ca5442db00ec625a0d0e619 \\
      --sessionid-b b37f8d2e5c8a1f4e9d0b6a3c7e1f8d2

  # 测试 C：快速重连抢帧
  python remote/noconfig/test_dual_session.py --mode rapid-reconnect --sessionid a269e12a1ca5442db00ec625a0d0e619
        """,
    )
    parser.add_argument("--mode", choices=["same", "different", "rapid-reconnect"], required=True,
                        help="测试模式: same=同一sessionid, different=不同sessionid, rapid-reconnect=快速重连")
    parser.add_argument("--sessionid", default="", help="sessionid (hex, 32 chars)")
    parser.add_argument("--sessionid-a", default="", help="sessionid A (hex, 32 chars)")
    parser.add_argument("--sessionid-b", default="", help="sessionid B (hex, 32 chars)")
    parser.add_argument("--duration", type=int, default=60, help="测试时长（秒，默认60）")
    parser.add_argument("--reconnect-interval", type=float, default=2.0, help="重连间隔（秒，默认2.0）")
    args = parser.parse_args()

    print("=" * 60)
    print("方向 A 测试：不同 sessionid 同时在线")
    print("=" * 60)
    print()

    if args.mode == "same":
        if not args.sessionid or len(args.sessionid) != 32:
            print("[错误] --sessionid 必须提供 32 位 hex 字符串")
            sys.exit(1)
        results = test_same_sessionid(args.sessionid, args.duration)

    elif args.mode == "different":
        if not args.sessionid_a or len(args.sessionid_a) != 32:
            print("[错误] --sessionid-a 必须提供 32 位 hex 字符串")
            sys.exit(1)
        if not args.sessionid_b or len(args.sessionid_b) != 32:
            print("[错误] --sessionid-b 必须提供 32 位 hex 字符串")
            sys.exit(1)
        results = test_different_sessionid(args.sessionid_a, args.sessionid_b, args.duration)

    elif args.mode == "rapid-reconnect":
        if not args.sessionid or len(args.sessionid) != 32:
            print("[错误] --sessionid 必须提供 32 位 hex 字符串")
            sys.exit(1)
        results = test_rapid_reconnect(args.sessionid, args.reconnect_interval, args.duration)

    # 输出结果
    print()
    print("=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    for key, value in results.items():
        print(f"  {key}: {value}")
    print("=" * 60)


if __name__ == "__main__":
    main()
