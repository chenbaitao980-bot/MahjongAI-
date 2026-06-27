#!/bin/sh
# build_ipk.sh — 手工组装 mahjong-mitm ipk（无需 OpenWrt SDK 工具链）。
#
# ipk = ar(debian-binary + control.tar.gz + data.tar.gz)。本包纯 Python + 数据文件，
# 无编译产物，故 Architecture=all，任意机器（含 Windows Git Bash）有 tar/gzip 即可打包。
#
# 用法:
#   cd interface/openwrt
#   sh build_ipk.sh [version]
#
# 产物: ./dist/mahjong-mitm_<version>_all.ipk
#
# 装到路由器:
#   scp dist/mahjong-mitm_*.ipk root@192.168.8.1:/tmp/
#   ssh root@192.168.8.1 "opkg update; opkg install python3-light python3-urllib python3-openssl; opkg install /tmp/mahjong-mitm_*.ipk"

set -e

VERSION="${1:-1.0.0}"
PKG="mahjong-mitm"
ARCH="all"

HERE="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_ROOT="$(cd "$HERE/.." && pwd)"   # interface/
BUILD="$HERE/.build"
DIST="$HERE/dist"
DATA="$BUILD/data"
CTRL="$BUILD/control"

rm -rf "$BUILD"
mkdir -p "$DATA" "$CTRL" "$DIST"

echo "[1/5] staging data tree..."
# Python 包 + assets → /usr/lib/mahjong-mitm/
PROG_DIR="$DATA/usr/lib/$PKG"
mkdir -p "$PROG_DIR/mahjong_mitm" "$PROG_DIR/assets"
cp "$RUNTIME_ROOT"/mahjong_mitm/*.py "$PROG_DIR/mahjong_mitm/"

# 构建期从 APK 提取最小资产（替代打包完整 85MB APK）
APK_PATH="$RUNTIME_ROOT/assets/game_base.apk"
if [ -f "$APK_PATH" ]; then
    python3 -c "
import zipfile, os
apk = '$APK_PATH'
out = '$PROG_DIR/assets'
with zipfile.ZipFile(apk) as z:
    netconf = z.read('assets/src/app/Config/NetConf.luac')
    with open(os.path.join(out, 'NetConf.luac'), 'wb') as f:
        f.write(netconf)
    manifest = z.read('assets/res/GameHotUpdate3/Lobby/project_10001.manifest')
    with open(os.path.join(out, 'project.manifest.json'), 'wb') as f:
        f.write(manifest)
    print(f'[extract] NetConf.luac {len(netconf)}B + project.manifest.json {len(manifest)}B')
"
else
    echo "WARNING: $APK_PATH not found; ipk will require --apk at runtime"
fi

# 配置 / init.d / nftables 规则
mkdir -p "$DATA/etc/init.d" "$DATA/etc/config" "$DATA/etc/nftables.d"
cp "$HERE/files/etc/init.d/$PKG"        "$DATA/etc/init.d/$PKG"
cp "$HERE/files/etc/config/$PKG"        "$DATA/etc/config/$PKG"
cp "$HERE/files/etc/nftables.d/99-$PKG.nft" "$DATA/etc/nftables.d/99-$PKG.nft"
chmod 755 "$DATA/etc/init.d/$PKG"

echo "[2/5] computing installed size..."
INST_SIZE=$(du -sk "$DATA" | cut -f1)

echo "[3/5] writing control..."
cat > "$CTRL/control" <<EOF
Package: $PKG
Version: $VERSION
Architecture: $ARCH
Maintainer: mahjong-ai
Section: net
Priority: optional
Depends: python3-light, python3-urllib, python3-openssl, kmod-nft-nat
Installed-Size: $INST_SIZE
Description: Setup-period hotfix MITM. Phone connects router WiFi, hotfix rewrites
 NetConf to point at ECS, then phone roams to any network. Router does not touch
 7777 game traffic afterwards.
EOF

cp "$HERE/postinst" "$CTRL/postinst"
chmod 755 "$CTRL/postinst"

# conffiles: 保护用户改过的 uci 配置不被升级覆盖
cat > "$CTRL/conffiles" <<EOF
/etc/config/$PKG
EOF

echo "[4/5] building tarballs..."
( cd "$CTRL" && tar --numeric-owner --owner=0 --group=0 -czf "$BUILD/control.tar.gz" ./* )
( cd "$DATA" && tar --numeric-owner --owner=0 --group=0 -czf "$BUILD/data.tar.gz" ./* )
echo "2.0" > "$BUILD/debian-binary"

echo "[5/5] assembling ipk (ar)..."
OUT="$DIST/${PKG}_${VERSION}_${ARCH}.ipk"
rm -f "$OUT"
( cd "$BUILD" && tar --numeric-owner --owner=0 --group=0 -czf "$OUT" ./debian-binary ./control.tar.gz ./data.tar.gz )
# opkg 接受 gzip(tar) 形式的 ipk（OpenWrt 习惯做法）；若目标 opkg 要求 ar 格式，
# 改用: ( cd "$BUILD" && ar r "$OUT" debian-binary control.tar.gz data.tar.gz )

rm -rf "$BUILD"
echo ""
echo "[DONE] $OUT  ($(du -h "$OUT" | cut -f1))"
