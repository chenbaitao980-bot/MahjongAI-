#!/usr/bin/env python3
"""快速诊断 sessionid 有效性"""
import socket
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from remote.srs_spectator.client import SRSClient

# 从 cloud_credentials.json 读取 sessionid
import json
_cred = REPO_ROOT / "data" / "cloud_credentials.json"
if _cred.is_file():
    rec = json.loads(_cred.read_text(encoding="utf-8"))
    sessionid = rec.get("srs_sessionid", "")
    print(f"[info] 从 cloud_credentials.json 读取 sessionid: {sessionid}")
else:
    print("[error] 找不到 data/cloud_credentials.json")
    sys.exit(1)

# 使用 SRSClient 测试连接
print(f"[info] 测试连接到 47.96.0.227:7777...")

client = SRSClient(
    "47.96.0.227", 7777,
    auth_token="", handshake_blob="", srs_sessionid=sessionid,
    userid="newpt1084306678"
)

flag_result = [-1]

def on_frame(msg_type, payload):
    if msg_type == 6:  # PlayerData
        flag = payload[0] if payload else -1
        flag_result[0] = flag
        print(f"[info] 收到 PlayerData, flag={flag}")

client.on_frame(on_frame)

success = client.connect(timeout=10.0)
if success:
    print("[info] TCP 连接成功，等待认证结果...")
    import time
    time.sleep(5)  # 等待认证结果
    if flag_result[0] == 0:
        print("[info] ✅ 认证成功！sessionid 有效")
    elif flag_result[0] == 72:
        print("[info] ❌ 认证失败: flag=72 (sessionid 过期)")
    elif flag_result[0] == 41:
        print("[info] ❌ 认证失败: flag=41 (格式错误)")
    else:
        print(f"[info] ❌ 认证失败: flag={flag_result[0]}")
else:
    print("[error] TCP 连接失败")

client.disconnect()
