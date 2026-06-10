#!/bin/sh
# selfcheck_capture.sh — 验证手机游戏流量是否真的经过本机(主/旁路由是否生效)
# 用法:  sh selfcheck_capture.sh [interface] [seconds]
#   例:  sh selfcheck_capture.sh br-lan 12
# 请在手机进入游戏、有摸打操作时运行。

IFACE="${1:-br-lan}"
SECS="${2:-12}"
PORT=7777

echo "============================================"
echo "  extractor 抓包自检"
echo "  interface=$IFACE  port=$PORT  duration=${SECS}s"
echo "============================================"

if ! command -v tcpdump >/dev/null 2>&1; then
    echo "[ERROR] 未找到 tcpdump，请先安装。"
    exit 1
fi

echo "请确保手机已连入本路由的网络、并正在游戏中操作..."
echo "抓包 ${SECS} 秒中..."

OUT="$(tcpdump -i "$IFACE" -n -c 200 "tcp port $PORT" 2>/dev/null &
       TPID=$!
       sleep "$SECS"
       kill $TPID 2>/dev/null
       wait $TPID 2>/dev/null)"

# 统计命中行数
N="$(printf '%s\n' "$OUT" | grep -c ".$PORT")"

echo "--------------------------------------------"
if [ "$N" -gt 0 ]; then
    echo "[PASS] 在 $IFACE 上抓到 $N 个 port-$PORT 包 —— 手机流量经过本机，部署正确。"
    echo "  样本(前5行):"
    printf '%s\n' "$OUT" | grep ".$PORT" | head -5 | sed 's/^/    /'
    echo "  -> 可放心让 extractor 服务常驻。"
    exit 0
else
    echo "[WARN] 在 $IFACE 上没抓到任何 port-$PORT 包。可能原因："
    echo "  1) interface 选错：换网卡再试 (ip link / ifconfig 看有哪些，常见 br-lan/eth0/eth1)"
    echo "  2) 旁路由没生效：手机/网关的默认路由没指向这台设备，流量没经过它"
    echo "  3) 手机当时没在游戏里产生流量：进游戏摸打几张牌再测"
    echo "  4) 游戏服务器端口/IP 变化：确认仍是 :$PORT"
    exit 1
fi
