"""ecs_deploy_paramiko.py — 使用 Python paramiko 库通过密码连接 ECS 并部署代码。

用法:
    python scripts/ecs_deploy_paramiko.py            # 同步代码并重启服务
    python scripts/ecs_deploy_paramiko.py --apk      # 同时上传 APK

依赖:
    pip install paramiko
"""
import argparse
import os
import sys
import stat

try:
    import paramiko
except ImportError:
    print("[ERROR] 需要安装 paramiko: pip install paramiko")
    sys.exit(1)

ECS_IP = "8.136.37.136"
ECS_USER = "root"
# 密码从环境变量 ECS_PASSWORD 或命令行参数获取，不硬编码
REMOTE_DIR = "/opt/mahjong-remote"

CODE_FILES = [
    ("remote/noconfig/hijack/tcp_proxy.py", "remote/noconfig/hijack"),
    ("remote/noconfig/hijack/setup_mitm.py", "remote/noconfig/hijack"),
    ("remote/noconfig/hijack/manifest_forge.py", "remote/noconfig/hijack"),
    ("remote/noconfig/hijack/netconf_patch.py", "remote/noconfig/hijack"),
    ("remote/noconfig/hijack/dns_divert.py", "remote/noconfig/hijack"),
    ("remote/noconfig/hijack/run_hijack.py", "remote/noconfig/hijack"),
    ("remote/srs_spectator/crypto.py", "remote/srs_spectator"),
    ("remote/srs_spectator/frame.py", "remote/srs_spectator"),
    ("remote/srs_spectator/handshake.py", "remote/srs_spectator"),
    ("remote/relay/static/index.html", "remote/relay/static"),
]
# 整目录上传：(本地目录, 远程子目录)
CODE_DIRS = [
    ("remote/relay/static/tiles", "remote/relay/static/tiles"),
]
APK_LOCAL = "apk/game_base.apk"
APK_REMOTE = f"{REMOTE_DIR}/apk/game_base.apk"

SERVICES = [
    "mahjong-tcp-proxy",
    "mahjong-relay-noconfig",
    "mahjong-mitm-hotupdate",
]


def ssh_exec(client: paramiko.SSHClient, cmd: str) -> tuple[int, str, str]:
    """执行 SSH 命令，返回 (exit_code, stdout, stderr)。"""
    print(f"$ ssh {cmd}")
    _, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode("utf-8")
    err = stderr.read().decode("utf-8")
    code = stdout.channel.recv_exit_status()
    if out:
        print(out.strip())
    if err:
        print(f"[stderr] {err.strip()}")
    return code, out, err


def sftp_upload(sftp: paramiko.SFTPClient, local: str, remote: str) -> None:
    """通过 SFTP 上传文件。"""
    print(f"$ upload {local} -> {remote}")

    # 确保远程目录存在
    remote_dir = os.path.dirname(remote)
    try:
        sftp.stat(remote_dir)
    except FileNotFoundError:
        # 递归创建目录
        dirs_to_create = []
        current = remote_dir
        while current and current != "/":
            try:
                sftp.stat(current)
                break
            except FileNotFoundError:
                dirs_to_create.append(current)
                current = os.path.dirname(current)
        for d in reversed(dirs_to_create):
            sftp.mkdir(d)

    sftp.put(local, remote)
    print(f"[OK] uploaded {os.path.getsize(local)}B -> {remote}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apk", action="store_true", help="同时上传 88MB APK")
    ap.add_argument("--no-restart", action="store_true", help="只同步，不重启服务")
    ap.add_argument("--password", default=None, help="ECS 密码")
    args = ap.parse_args()

    # 获取密码
    password = args.password or os.environ.get("ECS_PASSWORD")
    if not password:
        import getpass
        password = getpass.getpass(f"输入 ECS ({ECS_IP}) root 密码: ")

    # 检查本地文件
    for local, _ in CODE_FILES:
        if not os.path.exists(local):
            print(f"[ERROR] 找不到 {local}（请在项目根目录运行）")
            sys.exit(1)

    # 连接 ECS
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"[connect] {ECS_USER}@{ECS_IP}...")
    try:
        client.connect(ECS_IP, username=ECS_USER, password=password, timeout=30)
    except Exception as e:
        print(f"[ERROR] SSH 连接失败: {e}")
        sys.exit(1)

    sftp = client.open_sftp()

    # 1. 同步代码
    print("\n=== 同步代码 ===")
    for local, subdir in CODE_FILES:
        remote_path = f"{REMOTE_DIR}/{subdir}/{os.path.basename(local)}"
        sftp_upload(sftp, local, remote_path)

    # 1b. 同步整目录（如麻将牌图片）
    for local_dir, remote_subdir in CODE_DIRS:
        if not os.path.isdir(local_dir):
            print(f"[WARN] 跳过不存在的目录 {local_dir}")
            continue
        print(f"\n=== 同步目录 {local_dir} ===")
        for fname in sorted(os.listdir(local_dir)):
            lpath = os.path.join(local_dir, fname)
            if not os.path.isfile(lpath):
                continue
            sftp_upload(sftp, lpath, f"{REMOTE_DIR}/{remote_subdir}/{fname}")

    # 2. APK（可选）
    if args.apk:
        if not os.path.exists(APK_LOCAL):
            print(f"[ERROR] 找不到 {APK_LOCAL}")
            sys.exit(1)
        print("\n=== 上传 APK ===")
        sftp_upload(sftp, APK_LOCAL, APK_REMOTE)

    # 3. 重启服务
    if not args.no_restart:
        print("\n=== 重启服务 ===")
        restart_cmd = "systemctl daemon-reload && systemctl restart " + " ".join(SERVICES)
        code, _, _ = ssh_exec(client, restart_cmd)
        if code != 0:
            print("[ERROR] 重启服务失败")
            sys.exit(1)

        check_cmd = "sleep 2 && systemctl is-active --quiet " + " ".join(SERVICES) + " && echo 'all active'"
        code, out, _ = ssh_exec(client, check_cmd)
        if code != 0 or "active" not in out:
            print("[ERROR] 服务未激活")
            sys.exit(1)

        # 显示服务状态
        status_cmd = "systemctl status " + " ".join(SERVICES[:2]) + " --no-pager | head -20"
        ssh_exec(client, status_cmd)

    sftp.close()
    client.close()

    print("\n[OK] 部署完成")
    print("提醒:")
    print("  - 安全组需放行 TCP 443 + UDP 53")
    print("  - 手机 DNS 设为 8.136.37.136")
    print("  - 或使用 PC 热点 + dns_divert 劫持")


if __name__ == "__main__":
    main()