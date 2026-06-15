#!/usr/bin/env python3
"""
Restart hotspot MITM and ECS deployment script.
Supports SSH password authentication via paramiko (no sshpass required).
"""

import argparse
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import paramiko


def get_ssh_password(ecs_host: str) -> str:
    """Prompt for SSH password using a simple GUI dialog."""
    try:
        import tkinter as tk
        from tkinter import simpledialog

        root = tk.Tk()
        root.withdraw()
        password = simpledialog.askstring(
            "SSH Authentication",
            f"Enter password for {ecs_host}:",
            show="*",
        )
        root.destroy()
        if password is None:
            raise RuntimeError("SSH password input cancelled by user.")
        return password
    except ImportError:
        # Fallback to console input if tkinter is not available
        import getpass

        print(f"Enter password for {ecs_host}:")
        return getpass.getpass()


def run_checked(cmd: list[str], cwd: str | None = None, stdin: str | None = None) -> None:
    """Run a command and check its exit code."""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        input=stdin.encode() if stdin else None,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


def stop_local_mitm(repo_root: Path, pid_path: Path) -> None:
    """Stop any running local MITM processes."""
    patterns = [
        r"remote[/\\]noconfig[/\\]hijack[/\\]run_hijack\.py",
        r"remote[/\\]noconfig[/\\]hijack[/\\]setup_mitm\.py",
    ]

    # Find and kill Python processes matching patterns
    if sys.platform == "win32":
        try:
            import psutil

            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                if proc.info["name"] and proc.info["name"].lower() in (
                    "python.exe",
                    "py.exe",
                ):
                    cmdline = " ".join(proc.info["cmdline"] or [])
                    for pattern in patterns:
                        if re.search(pattern, cmdline):
                            try:
                                proc.kill()
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass
        except ImportError:
            pass
    else:
        # Unix fallback
        for pattern in patterns:
            subprocess.run(
                ["pkill", "-f", pattern.replace("[/\\\\]", "/")],
                capture_output=True,
            )

    if pid_path.exists():
        pid_path.unlink(missing_ok=True)


def assert_hotspot_ip(host_ip: str) -> None:
    """Check if the hotspot IP is present."""
    if sys.platform == "win32":
        import subprocess

        result = subprocess.run(
            ["powershell", "-Command", f"Get-NetIPAddress -AddressFamily IPv4 | Where-Object {{ $_.IPAddress -eq '{host_ip}' }}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(f"Hotspot IP {host_ip} is not present. Open the Windows hotspot first.")
    else:
        # Unix fallback - just check if IP is configured
        result = subprocess.run(["ip", "addr"], capture_output=True, text=True)
        if host_ip not in result.stdout:
            raise RuntimeError(f"Hotspot IP {host_ip} is not present.")


def deploy_remote(
    repo_root: Path,
    tar_path: Path,
    ecs_host: str,
    ecs_ip: str,
    bump_version: str,
    ssh_password: str,
) -> None:
    """Deploy to remote ECS via SSH/SCP using paramiko."""
    # Parse ECS host (format: user@host)
    if "@" in ecs_host:
        username, hostname = ecs_host.split("@", 1)
    else:
        username = "root"
        hostname = ecs_host

    # Create tar archive
    print("Creating tar archive...")
    with tarfile.open(tar_path, "w") as tar:
        for item in [
            "remote/noconfig/hijack",
            "remote/relay",
            "apk/game_base.apk",
        ]:
            item_path = repo_root / item
            if item_path.exists():
                tar.add(item_path, arcname=item)
            else:
                print(f"Warning: {item_path} not found, skipping")

    # Upload via SCP using paramiko
    print(f"Uploading to {ecs_host}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(hostname, username=username, password=ssh_password, timeout=30)

        # Upload tar file
        sftp = ssh.open_sftp()
        remote_tar_path = "/tmp/hijack-update.tar"
        sftp.put(str(tar_path), remote_tar_path)
        sftp.close()

        # Execute remote deployment script
        remote_script = f"""set -e
rm -rf /tmp/hijack-update
mkdir -p /tmp/hijack-update
cd /tmp/hijack-update
tar -xf /tmp/hijack-update.tar
cp -r remote/noconfig/hijack/* /opt/mahjong-remote/remote/noconfig/hijack/
cp -r remote/relay/* /opt/mahjong-remote/remote/relay/
mkdir -p /opt/mahjong-remote/apk
cp apk/game_base.apk /opt/mahjong-remote/apk/game_base.apk
systemctl restart mahjong-mitm-hotupdate mahjong-tcp-proxy mahjong-relay-noconfig
sleep 2
systemctl is-active mahjong-mitm-hotupdate mahjong-tcp-proxy mahjong-relay-noconfig
python3 - <<'PY'
import json, urllib.request, ssl, hashlib
from urllib.parse import urlsplit
ctx = ssl._create_unverified_context()
req = urllib.request.Request(
    'https://127.0.0.1/hotfix_update?env=1&appid=1073&engine_ver=3.13&channel=10001116_astc&version=1.0.0.59',
    headers={{'Host': 'gxb-api.hzxuanming.com'}},
)
vm = json.loads(urllib.request.urlopen(req, context=ctx, timeout=10).read().decode())
assert vm['version'] == '{bump_version}', vm
parts = urlsplit(vm['manifest_url'][0])
local_url = 'https://127.0.0.1' + parts.path + (('?' + parts.query) if parts.query else '')
req = urllib.request.Request(local_url, headers={{'Host': parts.hostname}})
pm = json.loads(urllib.request.urlopen(req, context=ctx, timeout=10).read().decode())
fl = pm['file_list']
assert sorted(fl.keys()) == sorted([
    'src/app/config/NetConf.luac',
    'src/app/hotupdate/lobby/ResEnsure.luac',
    'src/app/hotupdate/lobby/ResChecker.luac',
]) or sorted(fl.keys()) == sorted([
    'src/app/Config/NetConf.luac',
    'src/app/hotupdate/lobby/ResEnsure.luac',
    'src/app/hotupdate/lobby/ResChecker.luac',
]), fl.keys()
rc = fl['src/app/hotupdate/lobby/ResChecker.luac']
req = urllib.request.Request(
    'https://127.0.0.1/yj/files/' + rc['name'],
    headers={{'Host': 'gxb-oss.hzxuanming.com'}},
)
body = urllib.request.urlopen(req, context=ctx, timeout=10).read()
assert hashlib.md5(body).hexdigest() == rc['md5'], rc
print('REMOTE_OK', vm['version'], rc['md5'], len(body), local_url)
PY
"""

        print("Executing remote deployment...")
        stdin, stdout, stderr = ssh.exec_command(remote_script)
        exit_code = stdout.channel.recv_exit_status()
        output = stdout.read().decode()
        error = stderr.read().decode()

        if exit_code != 0:
            raise RuntimeError(f"Remote deployment failed:\n{error}\n{output}")

        print(output.strip())

    finally:
        ssh.close()


def start_local_mitm(
    repo_root: Path,
    python_exe: str,
    host_ip: str,
    ecs_ip: str,
    bump_version: str,
    no_divert: bool,
    logs_dir: Path,
    out_log: Path,
    err_log: Path,
    pid_path: Path,
) -> None:
    """Start local MITM process."""
    stop_local_mitm(repo_root, pid_path)

    if out_log.exists():
        out_log.unlink()
    if err_log.exists():
        err_log.unlink()

    args = [
        python_exe,
        "remote/noconfig/hijack/run_hijack.py",
        "--host-ip", host_ip,
        "--ecs-ip", ecs_ip,
        "--bump-version", bump_version,
    ]
    if no_divert:
        args.append("--no-divert")

    print("Starting local MITM...")
    proc = subprocess.Popen(
        args,
        cwd=str(repo_root),
        stdout=open(out_log, "w"),
        stderr=open(err_log, "w"),
    )

    pid_path.write_text(str(proc.pid))

    # Wait for MITM to start
    deadline = time.time() + 30
    while time.time() < deadline:
        time.sleep(0.7)
        if proc.poll() is not None:
            stderr_content = err_log.read_text() if err_log.exists() else ""
            raise RuntimeError(f"Local MITM exited early. {stderr_content}")
        if out_log.exists() and "MITM" in out_log.read_text():
            break

    # Verify local MITM
    verify_script = f"""
import json, ssl, urllib.request
from urllib.parse import urlsplit
ctx = ssl._create_unverified_context()
req = urllib.request.Request(
    'https://127.0.0.1/hotfix_update?env=1&appid=1073&engine_ver=3.13&channel=10001116_astc&version=1.0.0.59',
    headers={{'Host': 'gxb-api.hzxuanming.com'}},
)
vm = json.loads(urllib.request.urlopen(req, context=ctx, timeout=10).read().decode())
assert vm['version'] == '{bump_version}', vm
parts = urlsplit(vm['manifest_url'][0])
local_url = 'https://127.0.0.1' + parts.path + (('?' + parts.query) if parts.query else '')
req = urllib.request.Request(local_url, headers={{'Host': parts.hostname}})
pm = json.loads(urllib.request.urlopen(req, context=ctx, timeout=10).read().decode())
keys = sorted(pm['file_list'].keys())
assert keys in (
    ['src/app/Config/NetConf.luac', 'src/app/hotupdate/lobby/ResChecker.luac', 'src/app/hotupdate/lobby/ResEnsure.luac'],
    ['src/app/config/NetConf.luac', 'src/app/hotupdate/lobby/ResChecker.luac', 'src/app/hotupdate/lobby/ResEnsure.luac'],
), keys
print('LOCAL_OK', vm['version'], local_url, len(keys))
"""

    result = subprocess.run(
        [python_exe, "-"],
        input=verify_script,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Local MITM verification failed:\n{result.stderr}")

    print(result.stdout.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="Restart hotspot MITM and ECS deployment")
    parser.add_argument("--host-ip", default="192.168.137.1", help="Hotspot IP address")
    parser.add_argument("--ecs-host", default="root@8.136.37.136", help="ECS host (user@host)")
    parser.add_argument("--ecs-ip", default="8.136.37.136", help="ECS IP address")
    parser.add_argument("--bump-version", default="9.9.9.103", help="Bump version")
    parser.add_argument("--python-exe", default="python", help="Python executable")
    parser.add_argument("--no-divert", action="store_true", help="No divert mode")
    args = parser.parse_args()

    repo_root = Path(__file__).parent.parent.resolve()
    logs_dir = repo_root / "logs"
    logs_dir.mkdir(exist_ok=True)

    tar_path = repo_root / "hijack-update.tar"
    pid_path = logs_dir / "hotspot_mitm.pid"
    out_log = logs_dir / "hotspot_mitm_bg.out.log"
    err_log = logs_dir / "hotspot_mitm_bg.err.log"

    # Get SSH password via GUI prompt
    ssh_password = get_ssh_password(args.ecs_host)

    try:
        # Check hotspot IP
        assert_hotspot_ip(args.host_ip)

        # Deploy to remote
        deploy_remote(
            repo_root,
            tar_path,
            args.ecs_host,
            args.ecs_ip,
            args.bump_version,
            ssh_password,
        )

        # Start local MITM
        start_local_mitm(
            repo_root,
            args.python_exe,
            args.host_ip,
            args.ecs_ip,
            args.bump_version,
            args.no_divert,
            logs_dir,
            out_log,
            err_log,
            pid_path,
        )

        print("=" * 60)
        print("READY Local hotspot MITM is running in background.")
        print(f"  Local log:  {out_log}")
        print(f"  Local err:  {err_log}")
        print(f"  Local pid:  {pid_path}")
        print(f"  Remote host: {args.ecs_host}")
        print(f"  Version:    {args.bump_version}")
        print("=" * 60)

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
