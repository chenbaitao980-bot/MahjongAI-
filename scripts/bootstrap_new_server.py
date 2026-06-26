"""bootstrap_new_server.py — 任意裸服务器一键部署 noconfig 三件套。

把 noconfig 核心链路（relay:8002 + tcp_proxy:5748/5749/7777 + mitm-hotupdate:53/443）
从本地代码树整套部署到一台全新服务器，写三个 systemd 服务并启动。IP 纯参数化，
将来加第 N 台直接 `bootstrap_new_server.py <新IP>`，无需改任何源码。

阿里云 ECS（8.136.37.136）完全不碰：本脚本只对 <target_ip> 操作。

用法:
    python scripts/bootstrap_new_server.py 64.176.56.70
    python scripts/bootstrap_new_server.py 64.176.56.70 --password 'xxx'
    NEW_SERVER_PASSWORD='xxx' python scripts/bootstrap_new_server.py 64.176.56.70
    python scripts/bootstrap_new_server.py 64.176.56.70 --no-apk   # 跳过 88MB APK（mitm 会缺资源）

参数:
    target_ip            SSH 目标 IP（同时作为本机对外自我广播 IP，见 --self-ip）
    --self-ip IP         写进 NetConf / 代理改写的对外 IP（默认 = target_ip，单机部署同值）
    --password PWD       root 密码（缺省读 env NEW_SERVER_PASSWORD，再缺省交互输入）
    --ssh-user USER      SSH 用户（默认 root）
    --apk PATH           game_base.apk 路径（默认 apk/game_base.apk）
    --no-apk             不上传 APK（mitm-hotupdate 将缺少资源包，仅用于快速联调）
    --no-start           只同步+写服务，不启动
    --remote-dir DIR     远端部署目录（默认 /opt/mahjong-remote）

依赖: pip install paramiko
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import tarfile
import time

try:
    import paramiko
except ImportError:
    print("[ERROR] 需要安装 paramiko: pip install paramiko")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("[ERROR] 需要安装 pyyaml: pip install pyyaml")
    sys.exit(1)

# ─── 项目根 ──────────────────────────────────────────────────────
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# 需要整树打包的目录（对齐阿里云 /opt/mahjong-remote 的结构）
PACKAGE_DIRS = ["remote", "stable", "battle", "game", "utils", "config"]
# 打包排除规则
_EXCLUDE_SUFFIX = (".pyc",)
_EXCLUDE_DIRNAME = {"__pycache__", ".git", "logs", ".pytest_cache", ".venv", "venv"}

REMOTE_DIR_DEFAULT = "/opt/mahjong-remote"
PIP_PACKAGES = ["fastapi", "uvicorn", "pyyaml", "requests", "cryptography", "pydantic"]

# relay 配置（含 api_token，tcp_proxy --api-token 必须与之一致）
_CONFIG_NOCONFIG = os.path.join(_REPO_ROOT, "remote", "relay", "config_noconfig.yaml")


# ─── systemd service 模板（IP 参数化）─────────────────────────────

def _svc_relay() -> str:
    return """[Unit]
Description=MahjongAI Relay - No-Config Mode (Port 8002)
After=network.target

[Service]
Type=simple
WorkingDirectory={rdir}
ExecStart=/usr/bin/python3 remote/noconfig/main.py --host 0.0.0.0 --port 8002
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""


def _svc_tcp_proxy() -> str:
    return """[Unit]
Description=MahjongAI TCP Proxy - Hijack Mode (Lobby + Game)
After=network.target mahjong-relay-noconfig.service

[Service]
Type=simple
WorkingDirectory={rdir}
ExecStart=/usr/bin/python3 -u remote/noconfig/hijack/tcp_proxy.py --ecs-ip {self_ip} --listen-host 0.0.0.0 --relay-push http://127.0.0.1:8002/push --api-token {api_token}
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""


def _svc_mitm() -> str:
    return """[Unit]
Description=MahjongAI Hot-Update MITM (DNS hijack + HTTPS manifest) for 4G/any-network
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={rdir}
ExecStart=/usr/bin/python3 -u remote/noconfig/hijack/setup_mitm.py --host-ip {self_ip} --dns-listen-host 0.0.0.0 --ecs-ip {self_ip} --apk {rdir}/apk/game_base.apk
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""


SERVICES = {
    "mahjong-relay-noconfig": _svc_relay,
    "mahjong-tcp-proxy": _svc_tcp_proxy,
    "mahjong-mitm-hotupdate": _svc_mitm,
}


# ─── 工具函数 ────────────────────────────────────────────────────

def _tar_filter(ti: tarfile.TarInfo):
    base = os.path.basename(ti.name)
    parts = ti.name.split("/")
    if any(p in _EXCLUDE_DIRNAME for p in parts):
        return None
    if base.endswith(_EXCLUDE_SUFFIX):
        return None
    return ti


def build_tarball() -> bytes:
    """把 PACKAGE_DIRS 打成 tar.gz（内存），arcname 为相对路径。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for d in PACKAGE_DIRS:
            local = os.path.join(_REPO_ROOT, d)
            if not os.path.isdir(local):
                print(f"[WARN] 跳过不存在目录: {d}")
                continue
            tar.add(local, arcname=d, filter=_tar_filter)
    return buf.getvalue()


def ssh_exec(client: "paramiko.SSHClient", cmd: str, echo: bool = True) -> tuple[int, str, str]:
    if echo:
        print(f"$ {cmd}")
    _, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.strip())
    if err.strip():
        print(f"[stderr] {err.strip()}")
    return code, out, err


def sftp_put_bytes(sftp: "paramiko.SFTPClient", data: bytes, remote: str) -> None:
    with sftp.open(remote, "wb") as f:
        f.write(data)
    print(f"[OK] 上传 {len(data)} bytes -> {remote}")


# ─── 主流程 ──────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="任意裸服务器一键部署 noconfig 三件套",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("target_ip", help="SSH 目标服务器 IP")
    ap.add_argument("--self-ip", default=None, help="对外广播 IP（默认 = target_ip）")
    ap.add_argument("--password", default=None, help="root 密码（缺省读 env NEW_SERVER_PASSWORD）")
    ap.add_argument("--ssh-user", default="root")
    ap.add_argument("--apk", default=os.path.join(_REPO_ROOT, "apk", "game_base.apk"))
    ap.add_argument("--no-apk", action="store_true")
    ap.add_argument("--no-start", action="store_true")
    ap.add_argument("--remote-dir", default=REMOTE_DIR_DEFAULT)
    args = ap.parse_args()

    target_ip = args.target_ip
    self_ip = args.self_ip or target_ip
    rdir = args.remote_dir.rstrip("/")

    # 密码
    password = args.password or os.environ.get("NEW_SERVER_PASSWORD")
    if not password:
        import getpass
        password = getpass.getpass(f"输入 {args.ssh_user}@{target_ip} 密码: ")

    # api_token（与 relay 配置保持一致）
    if not os.path.isfile(_CONFIG_NOCONFIG):
        print(f"[ERROR] 找不到 {_CONFIG_NOCONFIG}")
        sys.exit(1)
    with open(_CONFIG_NOCONFIG, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    api_token = cfg.get("api_token", "")
    if not api_token:
        print("[ERROR] config_noconfig.yaml 缺少 api_token")
        sys.exit(1)

    # APK 检查
    upload_apk = not args.no_apk
    if upload_apk and not os.path.isfile(args.apk):
        print(f"[ERROR] 找不到 APK: {args.apk}（用 --no-apk 跳过，但 mitm 会缺资源）")
        sys.exit(1)

    print("=" * 60)
    print(f"  目标服务器 : {args.ssh_user}@{target_ip}")
    print(f"  对外 IP    : {self_ip}")
    print(f"  远端目录   : {rdir}")
    print(f"  api_token  : {api_token[:6]}...（{len(api_token)} 字符）")
    print(f"  APK        : {'上传 ' + args.apk if upload_apk else '跳过'}")
    print("=" * 60)

    # 打包
    print("\n=== 打包本地代码树 ===")
    tarball = build_tarball()
    print(f"[OK] tar.gz 大小 {len(tarball) // 1024} KB（{', '.join(PACKAGE_DIRS)}）")

    # 连接
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"\n=== 连接 {args.ssh_user}@{target_ip} ===")
    try:
        client.connect(target_ip, username=args.ssh_user, password=password, timeout=30)
    except Exception as e:
        print(f"[ERROR] SSH 连接失败: {e}")
        sys.exit(1)
    sftp = client.open_sftp()

    # 1. 系统依赖
    print("\n=== 安装系统依赖 ===")
    ssh_exec(client, "command -v python3 >/dev/null || (apt-get update && apt-get install -y python3)")
    ssh_exec(client, "command -v pip3 >/dev/null || (apt-get update && apt-get install -y python3-pip)")
    code, _, _ = ssh_exec(client, "pip3 install --quiet --no-input " + " ".join(PIP_PACKAGES))
    if code != 0:
        print("[WARN] pip3 安装返回非 0，尝试 --break-system-packages")
        ssh_exec(client, "pip3 install --quiet --no-input --break-system-packages " + " ".join(PIP_PACKAGES))

    # 2. 推送代码
    print("\n=== 推送代码 ===")
    ssh_exec(client, f"mkdir -p {rdir}")
    sftp_put_bytes(sftp, tarball, "/tmp/mahjong-bootstrap.tar.gz")
    ssh_exec(client, f"tar -xzf /tmp/mahjong-bootstrap.tar.gz -C {rdir} && rm -f /tmp/mahjong-bootstrap.tar.gz")

    # 3. APK
    if upload_apk:
        print("\n=== 上传 APK（88MB，稍候）===")
        ssh_exec(client, f"mkdir -p {rdir}/apk")
        remote_apk = f"{rdir}/apk/game_base.apk"
        t0 = time.time()
        sftp.put(args.apk, remote_apk)
        print(f"[OK] APK 上传完成 {os.path.getsize(args.apk)}B，用时 {time.time() - t0:.1f}s")

    # 4. 写 systemd 服务
    print("\n=== 写 systemd 服务 ===")
    for name, tmpl in SERVICES.items():
        content = tmpl().format(rdir=rdir, self_ip=self_ip, api_token=api_token)
        remote_unit = f"/etc/systemd/system/{name}.service"
        sftp_put_bytes(sftp, content.encode("utf-8"), remote_unit)
    ssh_exec(client, "systemctl daemon-reload")
    ssh_exec(client, "systemctl enable " + " ".join(SERVICES.keys()) + " 2>&1 | tail -1")

    # 5. 启动 + 验证
    if not args.no_start:
        print("\n=== 启动服务 ===")
        ssh_exec(client, "systemctl restart " + " ".join(SERVICES.keys()))
        time.sleep(3)
        code, out, _ = ssh_exec(client, "systemctl is-active " + " ".join(SERVICES.keys()))
        active = out.split()
        all_ok = len(active) == len(SERVICES) and all(s == "active" for s in active)
        if all_ok:
            print("[OK] 三件套全部 active")
        else:
            print("[ERROR] 部分服务未激活，dump 最近日志：")
            for name in SERVICES:
                ssh_exec(client, f"systemctl is-active {name} >/dev/null || journalctl -u {name} -n 15 --no-pager")
        # 端口检查
        ssh_exec(client, "ss -tlnp 2>/dev/null | grep -E ':5748|:5749|:7777|:8002|:443' || netstat -tlnp 2>/dev/null | grep -E '5748|5749|7777|8002|443'")

    sftp.close()
    client.close()

    print("\n" + "=" * 60)
    print("[OK] 部署完成")
    print("后续手动步骤（请用户自行确认）：")
    print(f"  1. Vultr 防火墙放行入站: TCP 5748/5749/7777/8002/443, UDP 53")
    print(f"  2. 让测试手机指向新机: 手机 DNS 设为 {self_ip}（或 PC 热点 dns_divert 指 {self_ip}）")
    print(f"  3. 手机重新走一次热更（NetConf 会被改写指向 {self_ip}），完成后任意网络读牌")
    print(f"  4. 验证读牌页: http://{self_ip}:8002/state?token={api_token}")
    print(f"  阿里云 8.136.37.136 完全未受影响。")
    print("=" * 60)


if __name__ == "__main__":
    main()
