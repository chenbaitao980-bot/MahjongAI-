#!/usr/bin/env python3
"""build_ipk.py — 跨平台 ipk 打包脚本（替代 build_ipk.sh）。

用法:
    cd interface/openwrt
    python3 build_ipk.py [version]

产物: ./dist/mahjong-mitm_<version>_all.ipk
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile


def main() -> None:
    version = sys.argv[1] if len(sys.argv) > 1 else "1.0.2"
    pkg = "mahjong-mitm"
    arch = "all"

    here = os.path.dirname(os.path.abspath(__file__))
    runtime_root = os.path.dirname(here)  # interface/
    build = os.path.join(here, ".build")
    dist_dir = os.path.join(here, "dist")
    data = os.path.join(build, "data")
    ctrl = os.path.join(build, "control")

    # 清理并重建
    if os.path.isdir(build):
        shutil.rmtree(build)
    os.makedirs(data, exist_ok=True)
    os.makedirs(ctrl, exist_ok=True)
    os.makedirs(dist_dir, exist_ok=True)

    print("[1/5] staging data tree...")
    prog_dir = os.path.join(data, "usr", "lib", pkg)
    os.makedirs(os.path.join(prog_dir, "mahjong_mitm"), exist_ok=True)
    os.makedirs(os.path.join(prog_dir, "assets"), exist_ok=True)

    # Python 包
    for fname in os.listdir(os.path.join(runtime_root, "mahjong_mitm")):
        if fname.endswith(".py"):
            shutil.copy(
                os.path.join(runtime_root, "mahjong_mitm", fname),
                os.path.join(prog_dir, "mahjong_mitm", fname),
            )

    # watchdog.sh (用 setsid 派生的健康检查脚本)
    watchdog_src = os.path.join(here, "files", "usr", "lib", "mahjong-mitm", "watchdog.sh")
    if os.path.isfile(watchdog_src):
        dst = os.path.join(prog_dir, "watchdog.sh")
        shutil.copy(watchdog_src, dst)
        os.chmod(dst, 0o755)

    # resolve-gxb.sh (解析 gxb-* 真实 CDN IP + 生成 DNAT 规则)
    resolve_src = os.path.join(here, "files", "usr", "lib", "mahjong-mitm", "resolve-gxb.sh")
    if os.path.isfile(resolve_src):
        dst = os.path.join(prog_dir, "resolve-gxb.sh")
        shutil.copy(resolve_src, dst)
        os.chmod(dst, 0o755)

    # 构建期从 APK 提取最小资产
    apk_path = os.path.join(runtime_root, "assets", "game_base.apk")
    if os.path.isfile(apk_path):
        with zipfile.ZipFile(apk_path) as z:
            netconf = z.read("assets/src/app/Config/NetConf.luac")
            manifest = z.read("assets/res/GameHotUpdate3/Lobby/project_10001.manifest")
        with open(os.path.join(prog_dir, "assets", "NetConf.luac"), "wb") as f:
            f.write(netconf)
        with open(os.path.join(prog_dir, "assets", "project.manifest.json"), "wb") as f:
            f.write(manifest)
        print(f"    [extract] NetConf.luac {len(netconf)}B + project.manifest.json {len(manifest)}B")
    else:
        print(f"    WARNING: {apk_path} not found; ipk will require --apk at runtime")

    # 配置 / init.d / nftables
    os.makedirs(os.path.join(data, "etc", "init.d"), exist_ok=True)
    os.makedirs(os.path.join(data, "etc", "config"), exist_ok=True)
    os.makedirs(os.path.join(data, "etc", "nftables.d"), exist_ok=True)
    shutil.copy(
        os.path.join(here, "files", "etc", "init.d", pkg),
        os.path.join(data, "etc", "init.d", pkg),
    )
    shutil.copy(
        os.path.join(here, "files", "etc", "config", pkg),
        os.path.join(data, "etc", "config", pkg),
    )
    shutil.copy(
        os.path.join(here, "files", "etc", "nftables.d", f"99-{pkg}.nft"),
        os.path.join(data, "etc", "nftables.d", f"99-{pkg}.nft"),
    )

    print("[2/5] computing installed size...")
    inst_size = sum(
        os.path.getsize(os.path.join(dirpath, fname))
        for dirpath, _, fnames in os.walk(data)
        for fname in fnames
    ) // 1024

    print("[3/5] writing control...")
    control_content = f"""Package: {pkg}
Version: {version}
Architecture: {arch}
Maintainer: mahjong-ai
Section: net
Priority: optional
Depends: python3-light, python3-urllib, python3-openssl, kmod-nft-nat
Installed-Size: {inst_size}
Description: Setup-period hotfix MITM. Phone connects router WiFi, hotfix rewrites
 NetConf to point at ECS, then phone roams to any network. Router does not touch
 7777 game traffic afterwards.
"""
    with open(os.path.join(ctrl, "control"), "w", encoding="utf-8") as f:
        f.write(control_content)

    shutil.copy(os.path.join(here, "postinst"), os.path.join(ctrl, "postinst"))

    with open(os.path.join(ctrl, "conffiles"), "w", encoding="utf-8") as f:
        f.write(f"/etc/config/{pkg}\n")

    print("[4/5] building tarballs...")
    control_tgz = os.path.join(build, "control.tar.gz")
    data_tgz = os.path.join(build, "data.tar.gz")
    # GNU_FORMAT 避免 PAX 扩展头（typeflag='x'），OpenWrt BusyBox tar 不认识
    with tarfile.open(control_tgz, "w:gz", format=tarfile.GNU_FORMAT) as tf:
        for fname in os.listdir(ctrl):
            tf.add(os.path.join(ctrl, fname), arcname=fname)
    with tarfile.open(data_tgz, "w:gz", format=tarfile.GNU_FORMAT) as tf:
        for root, _, fnames in os.walk(data):
            for fname in fnames:
                full = os.path.join(root, fname)
                arcname = os.path.relpath(full, data)
                tf.add(full, arcname=arcname)

    debian_binary = os.path.join(build, "debian-binary")
    with open(debian_binary, "w") as f:
        f.write("2.0\n")

    print("[5/5] assembling ipk...")
    out = os.path.join(dist_dir, f"{pkg}_{version}_{arch}.ipk")
    if os.path.exists(out):
        os.remove(out)

    # opkg 接受 gzip(tar) 形式的 ipk
    with tarfile.open(out, "w:gz", format=tarfile.GNU_FORMAT) as tf:
        tf.add(debian_binary, arcname="debian-binary")
        tf.add(control_tgz, arcname="control.tar.gz")
        tf.add(data_tgz, arcname="data.tar.gz")

    shutil.rmtree(build)
    size = os.path.getsize(out)
    print(f"\n[DONE] {out}  ({size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
