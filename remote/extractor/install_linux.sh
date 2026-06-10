#!/bin/sh
# install_linux.sh — 在 x86 Linux / NAS / Docker 宿主上安装 extractor 常驻服务(systemd)
# 在解包后的 bundle 顶层目录(mahjong-extractor/)运行：  sh install_linux.sh
set -e

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_INSTALL_DIR="/opt/mahjong-extractor"

echo "============================================"
echo "  MahjongAI extractor 安装 (Linux / systemd)"
echo "============================================"

# --- 0. root 检查 ---
if [ "$(id -u)" != "0" ]; then
    echo "[ERROR] 请用 root 运行： sudo sh install_linux.sh"
    exit 1
fi

# --- 1. python3 ---
if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] 未找到 python3，请先安装 (apt/yum/apk install python3 python3-pip)"
    exit 1
fi
echo "[1/6] python3: $(python3 --version 2>&1)"

# --- 2. 依赖 ---
echo "[2/6] 安装 python 依赖 (requests pyyaml)..."
python3 -m pip install --quiet requests pyyaml 2>/dev/null || \
    echo "    [NOTE] pip 安装失败，请确认已装 python3-requests python3-yaml"

# --- 3. tcpdump ---
if ! command -v tcpdump >/dev/null 2>&1; then
    echo "    [NOTE] 未找到 tcpdump，请安装： apt/yum/apk install tcpdump"
fi

# --- 4. 交互配置 ---
echo "[3/6] 配置 (直接回车用默认/示例值)"
printf "  云端 relay_url [http://YOUR_CLOUD_IP:8000]: "; read RELAY_URL
[ -z "$RELAY_URL" ] && RELAY_URL="http://YOUR_CLOUD_IP:8000"
printf "  api_token (须与云 relay 一致): "; read API_TOKEN
[ -z "$API_TOKEN" ] && API_TOKEN="change-me-shared-secret"
printf "  抓包网卡 interface [br-lan]: "; read IFACE
[ -z "$IFACE" ] && IFACE="br-lan"
printf "  安装目录 [$DEFAULT_INSTALL_DIR]: "; read INSTALL_DIR
[ -z "$INSTALL_DIR" ] && INSTALL_DIR="$DEFAULT_INSTALL_DIR"

# --- 5. 拷贝 + 写配置 ---
echo "[4/6] 安装到 $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"
cp -r "$SELF_DIR/." "$INSTALL_DIR/"

cat > "$INSTALL_DIR/remote/extractor/config.yaml" <<EOF
# 由 install_linux.sh 生成
relay_url: "$RELAY_URL"
api_token: "$API_TOKEN"
game_port: 7777
EOF
echo "    config.yaml 写入完成 (relay_url=$RELAY_URL, iface=$IFACE)"

# --- 6. systemd 服务 ---
echo "[5/6] 安装 systemd 服务..."
SVC=/etc/systemd/system/mahjong-extractor.service
sed -e "s#__INSTALL_DIR__#$INSTALL_DIR#g" -e "s#__IFACE__#$IFACE#g" \
    "$INSTALL_DIR/files/mahjong-extractor.service" > "$SVC"
systemctl daemon-reload
systemctl enable mahjong-extractor.service
systemctl restart mahjong-extractor.service

echo "[6/6] 完成。"
echo "--------------------------------------------"
echo "  状态:  systemctl status mahjong-extractor"
echo "  日志:  journalctl -u mahjong-extractor -f"
echo "  自检:  sh $INSTALL_DIR/selfcheck_capture.sh $IFACE"
echo "  抓不到包? 多半是 interface 选错 / 旁路由没生效，先跑自检。"
echo "--------------------------------------------"
