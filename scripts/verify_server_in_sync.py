#!/usr/bin/env python3
"""verify_server_in_sync.py — 部署前自检：本地 vs ECS 关键文件 md5 对比。

用法：
    python scripts/verify_server_in_sync.py

发现差异时打印清单 + 建议命令（先 scp 拉回 git，再继续部署）。
返回码：0=完全一致；1=有差异；2=ssh 失败。

铁律来源：.trellis/spec/backend/remote-access.md §16
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ECS_HOST = "root@8.136.37.136"
ECS_ROOT = "/opt/mahjong-remote"
REPO_ROOT = Path(__file__).resolve().parent.parent

# 必检文件清单：所有可能被部署到 ECS 的代码。新加文件务必加进来。
TRACKED_FILES = [
    # noconfig 模式
    "remote/noconfig/app.py",
    "remote/noconfig/main.py",
    "remote/noconfig/user_store.py",
    "remote/noconfig/hijack/tcp_proxy.py",
    "remote/noconfig/hijack/ecs_proxy.py",
    "remote/noconfig/hijack/ecs_run.py",
    "remote/noconfig/hijack/setup_mitm.py",
    "remote/noconfig/hijack/run_hijack.py",
    "remote/noconfig/hijack/manifest_forge.py",
    "remote/noconfig/hijack/netconf_patch.py",
    "remote/noconfig/hijack/dns_divert.py",
    # SRS 协议层（被 noconfig/hijack 引用）
    "remote/srs_spectator/handshake.py",
    "remote/srs_spectator/crypto.py",
    "remote/srs_spectator/frame.py",
    "remote/srs_spectator/main.py",
    # relay 共享
    "remote/relay/state_store.py",
    "remote/relay/core.py",
]


def md5_local(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.md5()
    h.update(path.read_bytes())
    return h.hexdigest()


def md5_remote_batch(rel_paths: list[str]) -> dict[str, str | None]:
    """一次 ssh 拿所有文件的 md5，避免每个文件一次 ssh 太慢。"""
    cmd_parts = []
    for rel in rel_paths:
        full = f"{ECS_ROOT}/{rel}"
        cmd_parts.append(f"echo \"$(md5sum {full} 2>/dev/null | awk '{{print $1}}'):{rel}\"")
    remote_cmd = " ; ".join(cmd_parts)
    result = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=10", ECS_HOST, remote_cmd],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"[ssh-fail] {result.stderr}", file=sys.stderr)
        return {}

    out: dict[str, str | None] = {}
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        md5_str, rel = line.split(":", 1)
        md5_str = md5_str.strip()
        out[rel.strip()] = md5_str if md5_str else None
    return out


def main() -> int:
    print(f"[verify] comparing {len(TRACKED_FILES)} files: local vs {ECS_HOST}:{ECS_ROOT}/...")
    remote_md5 = md5_remote_batch(TRACKED_FILES)
    if not remote_md5:
        print("[ERROR] ssh failed — cannot verify. Aborting.", file=sys.stderr)
        return 2

    diffs: list[tuple[str, str | None, str | None]] = []
    missing_local: list[str] = []
    missing_remote: list[str] = []
    same: int = 0

    for rel in TRACKED_FILES:
        local = md5_local(REPO_ROOT / rel)
        remote = remote_md5.get(rel)
        if local is None:
            missing_local.append(rel)
            continue
        if remote is None:
            missing_remote.append(rel)
            continue
        if local == remote:
            same += 1
        else:
            diffs.append((rel, local, remote))

    print(f"[verify] in-sync: {same}/{len(TRACKED_FILES)}")
    if missing_local:
        print(f"[verify] missing local: {missing_local}")
    if missing_remote:
        print(f"[verify] missing remote: {missing_remote}")

    if not diffs:
        if not missing_local and not missing_remote:
            print("[OK] ALL IN SYNC. Safe to deploy.")
            return 0
        print("[WARN] some files only exist on one side; safe to deploy if expected.")
        return 0

    print()
    print("=" * 78)
    print("[!! DRIFT DETECTED] Server has changes not in your local git!")
    print("=" * 78)
    for rel, local, remote in diffs:
        print(f"  {rel}")
        print(f"    local md5  = {local}")
        print(f"    remote md5 = {remote}")
    print()
    print("This violates server-readonly-git-sync-discipline.")
    print("DO NOT DEPLOY. First pull server versions back into your local tree:")
    print()
    for rel, _, _ in diffs:
        print(f"  scp {ECS_HOST}:{ECS_ROOT}/{rel} {rel}")
    print()
    print(f"Then 'git diff' to inspect, 'git add' + 'git commit' to capture them,")
    print("and only THEN run restart_hotspot_mitm_and_ecs.bat.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
