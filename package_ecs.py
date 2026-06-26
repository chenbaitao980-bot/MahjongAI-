#!/usr/bin/env python3
"""package_ecs.py — 打包 ECS 部署所需文件为 tar.gz"""
import tarfile, io, os, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(ROOT, "mahjong-ecs-deploy.tar.gz")

FILES = [
    "deploy_ecs.sh",
    "remote/relay/main.py",
    "remote/relay/app.py",  
    "remote/relay/state_store.py",
    "remote/relay/game_client.py",
    "remote/relay/static/index.html",
    "remote/srs_spectator/main.py",
    "remote/srs_spectator/client.py",
    "remote/srs_spectator/frame.py",
    "remote/srs_spectator/crypto.py",
    "remote/srs_spectator/handshake.py",
    "remote/srs_spectator/spectator.py",
    "remote/srs_spectator/player_connect.py",
    "stable/protocol.py",
    "stable/tracker.py",
    "stable/mapping.py",
    "battle/__init__.py",
    "battle/state.py",
    "game/__init__.py",
    "utils/__init__.py",
]

with tarfile.open(OUTPUT, "w:gz") as tar:
    for f in FILES:
        path = os.path.join(ROOT, f)
        if os.path.isfile(path):
            tar.add(path, f)
            print(f"  + {f}")
        else:
            print(f"  SKIP (not found): {f}")

print(f"\nPackage: {OUTPUT}")
print(f"Upload to ECS: scp {OUTPUT} root@<ecs-ip>:/root/")
print(f"Then run: ssh root@<ecs-ip> 'cd /root && tar xzf mahjong-ecs-deploy.tar.gz && bash deploy_ecs.sh'")
