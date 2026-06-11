#!/bin/sh
# install_openwrt.sh — 在 OpenWRT / iStoreOS 上安装 extractor 常驻服务(procd)
# 在解包后的 bundle 顶层目录(mahjong-extractor/)运行：  sh install_openwrt.sh
set -e

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_INSTALL_DIR="/root/mahjong-extractor"

echo "============================================"
echo "  MahjongAI extractor 安装 (OpenWRT / procd)"
echo "============================================"

# --- 1. 依赖 (opkg) ---
echo "[1/6] 安装依赖 (python3-light python3-yaml python3-requests tcpdump)..."
opkg update >/dev/null 2>&1 || echo "    [NOTE] opkg update 失败，继续(可能已有源缓存)"
for pkg in python3-light python3-yaml python3-requests tcpdump; do
    if opkg list-installed | grep -q "^$pkg "; then
        echo "    已装: $pkg"
    else
        opkg install "$pkg" || echo "    [WARN] 安装 $pkg 失败，请手动确认"
    fi
done

if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] python3 不可用。OpenWRT 较老或精简固件可能无 python3，安装中止。"
    exit 1
fi
echo "    python3: $(python3 --version 2>&1)"

# --- 2. 交互配置 ---
echo "[2/6] 配置 (直接回车用默认/示例值)"
if [ -z "$RELAY_URL" ]; then
    printf "  云端 relay_url [http://YOUR_CLOUD_IP:8000]: "; read RELAY_URL
fi
[ -z "$RELAY_URL" ] && RELAY_URL="http://YOUR_CLOUD_IP:8000"
if [ -z "$API_TOKEN" ]; then
    printf "  api_token (须与云 relay 一致): "; read API_TOKEN
fi
[ -z "$API_TOKEN" ] && API_TOKEN="change-me-shared-secret"
if [ -z "$IFACE" ]; then
    printf "  抓包网卡 interface [br-lan]: "; read IFACE
fi
[ -z "$IFACE" ] && IFACE="br-lan"
if [ -z "$INSTALL_DIR" ]; then
    printf "  安装目录 [$DEFAULT_INSTALL_DIR]: "; read INSTALL_DIR
fi
[ -z "$INSTALL_DIR" ] && INSTALL_DIR="$DEFAULT_INSTALL_DIR"

# --- 3. 拷贝 + 写配置 ---
echo "[3/6] 安装到 $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"
cp -r "$SELF_DIR/." "$INSTALL_DIR/"

cat > "$INSTALL_DIR/remote/extractor/config.yaml" <<EOF
# 由 install_openwrt.sh 生成
relay_url: "$RELAY_URL"
api_token: "$API_TOKEN"
game_port: 7777
EOF
echo "    config.yaml 写入完成 (relay_url=$RELAY_URL, iface=$IFACE)"

# --- 4. procd init ---
echo "[4/6] 安装 procd 服务 /etc/init.d/mahjong-extractor ..."
INIT=/etc/init.d/mahjong-extractor
sed -e "s#__INSTALL_DIR__#$INSTALL_DIR#g" -e "s#__IFACE__#$IFACE#g" \
    "$INSTALL_DIR/files/mahjong-extractor.init" > "$INIT"
chmod +x "$INIT"

# --- 5. 启用 + 启动 ---
echo "[5/6] 启用并启动..."
"$INIT" enable
"$INIT" restart

echo "[6/6] 完成。"
echo "--------------------------------------------"
echo "  状态:  $INIT status   (或 ps | grep run.py)"
echo "  日志:  logread -e mahjong-extractor -f"
echo "  自检:  sh $INSTALL_DIR/selfcheck_capture.sh $IFACE"
echo "  抓不到包? 多半 interface 选错(试 br-lan / eth0) 或旁路由没生效，先跑自检。"
echo "--------------------------------------------"
