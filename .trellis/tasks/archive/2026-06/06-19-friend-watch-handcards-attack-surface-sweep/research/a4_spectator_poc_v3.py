"""PoC v3: 测 ReqFriendTableList(431) — 服务端真的能根据好友关系返回 game_roomid 吗？

这条无需 SEEGAME 流程，是普通玩家连接就能调的协议。
如果不能拿到 → 朋友肯定不只是用 ReqFriendTableList 探测。
如果能拿到 → 至少证明"昵称/numid → 实时房间ID"通路存在。
"""
from __future__ import annotations

import logging
import os
import struct
import sys
import time
from pathlib import Path

ECS_ROOT = "/opt/mahjong-remote"
if ECS_ROOT not in sys.path:
    sys.path.insert(0, ECS_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("a4v3")

GAME_HOST = "47.96.0.227"
GAME_PORT = 7777


# 可疑端口：431 是 IMProtocol，processid=100 可能要求另一种 framing
# 但 srs_spectator/frame.py 的 pack_frame 假设了 SRS 协议格式（0x4001 + msg_type + 0 + 0）
# 这跟 IM 协议（processid=100）大概率不兼容
# 简化：直接发 0x2BC1 (REQ to game) 不可能，目标是 lobby
# 所以这个 PoC 不能直接复用 srs_spectator client，因为 SRS 7777 是 game server
# IM 协议要走另一个端口（lobby 侧）
# noconfig 的 tcp_proxy 已经透明转发 lobby 端口（5045 等）
# 所以这条不是 SRS 7777 能调的

# 暂停 v3：换个验证路径
print("v3 终止：ReqFriendTableList 走 lobby (5045)，不在 7777 SRS 上")
print("正确的下一步是：")
print("  1) 直接看 stable 解码器解 0x2BC0 时遇到的 player 字段都是哪些值（已知 player=1 =你）")
print("  2) 看长一点时间窗里有没有 player=0/2/3 的 hand_update 帧（如果有就是真值）")
