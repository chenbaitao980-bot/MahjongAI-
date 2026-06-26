#!/bin/sh
# build_ipk.sh — 打包环境探针 ipk（无需 OpenWrt SDK）
#
# 用法:
#   cd apps/router-probe
#   sh build_ipk.sh [version]
#
# 产物: ./dist/router-probe_<version>_all.ipk
#
# 装到路由器:
#   scp dist/router-probe_*.ipk root@192.168.8.1:/tmp/
#   ssh root@192.168.8.1 "opkg install /tmp/router-probe_*.ipk"
#   ssh root@192.168.8.1 "logread | grep PROBE"   # 看结果
#   ssh root@192.168.8.1 "probe"                   # 手动重跑

set -e

VERSION="${1:-1.0.0}"
PKG="router-probe"
ARCH="all"

HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD="$HERE/.build"
DIST="$HERE/dist"
DATA="$BUILD/data"
CTRL="$BUILD/control"

rm -rf "$BUILD"
mkdir -p "$DATA" "$CTRL" "$DIST"

echo "[1/5] staging data tree..."
mkdir -p "$DATA/usr/bin"
cp "$HERE/probe" "$DATA/usr/bin/probe"
chmod 755 "$DATA/usr/bin/probe"

echo "[2/5] computing installed size..."
INST_SIZE=$(du -sk "$DATA" | cut -f1)

echo "[3/5] writing control..."
cat > "$CTRL/control" <<EOF
Package: $PKG
Version: $VERSION
Architecture: $ARCH
Maintainer: router-probe
Section: net
Priority: optional
Depends: python3-light, python3-urllib, python3-openssl
Installed-Size: $INST_SIZE
Description: Environment readiness probe for router MITM setup.
 Checks python3, ssl, urllib, openssl CLI, fw4/nftables, port 443/5353,
 procd, disk >= 50 MB, RAM >= 64 MB.
 Run: probe  (exit 0 = ALL SYSTEMS GO)
EOF

cp "$HERE/postinst" "$CTRL/postinst"
chmod 755 "$CTRL/postinst"

echo "[4/5] building tarballs..."
( cd "$CTRL" && tar --numeric-owner --owner=0 --group=0 -czf "$BUILD/control.tar.gz" ./* )
( cd "$DATA" && tar --numeric-owner --owner=0 --group=0 -czf "$BUILD/data.tar.gz" ./* )
echo "2.0" > "$BUILD/debian-binary"

echo "[5/5] assembling ipk..."
OUT="$DIST/${PKG}_${VERSION}_${ARCH}.ipk"
rm -f "$OUT"
( cd "$BUILD" && tar --numeric-owner --owner=0 --group=0 -czf "$OUT" ./debian-binary ./control.tar.gz ./data.tar.gz )

rm -rf "$BUILD"
echo ""
echo "[DONE] $OUT  ($(du -h "$OUT" | cut -f1))"
echo ""
echo "Deploy:"
echo "  scp $OUT root@192.168.8.1:/tmp/"
echo "  ssh root@192.168.8.1 'opkg install /tmp/${PKG}_${VERSION}_${ARCH}.ipk'"
echo "  ssh root@192.168.8.1 'logread | grep PROBE'"
