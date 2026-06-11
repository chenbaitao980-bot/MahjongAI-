#!/bin/bash
# install_vpn.sh — Install and configure strongSwan IKEv2 VPN server
#
# Supports: Debian/Ubuntu, OpenWRT, Alpine
# After install, run vpn_configure.py to generate phone config.
#
# Env vars:
#   GAME_SERVER_IP   — game IP for split tunnel (default: 47.96.0.227)
set -euo pipefail

GAME_IP="${GAME_SERVER_IP:-47.96.0.227}"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'

log()  { echo -e "${GREEN}[ok]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

detect_os() {
    if [ -f /etc/openwrt_release ]; then
        echo "openwrt"
    elif [ -f /etc/alpine-release ]; then
        echo "alpine"
    elif grep -qi "ubuntu\|debian" /etc/os-release 2>/dev/null; then
        echo "debian"
    else
        echo "unknown"
    fi
}

OS=$(detect_os)
log "Detected OS: $OS"
log "Split tunnel target: $GAME_IP/32"

# ─── Install strongSwan ───────────────────────────────────────
case "$OS" in
    debian)
        log "Installing strongSwan (apt)..."
        apt-get update -qq
        apt-get install -y -qq strongswan strongswan-pki iptables libcharon-extra-plugins
        ;;
    alpine)
        log "Installing strongSwan (apk)..."
        apk add --no-cache strongswan iptables
        ;;
    openwrt)
        log "Installing strongSwan (opkg)..."
        opkg update
        opkg install strongswan-full iptables
        ;;
    *)
        err "Unsupported OS. Manual install required."
        ;;
esac

# ─── Enable IP forwarding ─────────────────────────────────────
log "Enabling IPv4 forwarding..."
sysctl -w net.ipv4.ip_forward=1

# Persist across reboots
if [ "$OS" = "debian" ] || [ "$OS" = "alpine" ]; then
    sed -i 's/^#net.ipv4.ip_forward=1/net.ipv4.ip_forward=1/' /etc/sysctl.conf 2>/dev/null || true
    if ! grep -q "^net.ipv4.ip_forward=1" /etc/sysctl.conf; then
        echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
    fi
fi

# ─── iptables NAT for VPN subnet ──────────────────────────────
log "Setting up iptables NAT for VPN subnet 10.99.0.0/24..."
DEFAULT_IFACE=$(ip route get 8.8.8.8 | awk '{print $5; exit}')
log "  Default interface: $DEFAULT_IFACE"

iptables -t nat -C POSTROUTING -s 10.99.0.0/24 -o "$DEFAULT_IFACE" -j MASQUERADE 2>/dev/null || \
iptables -t nat -A POSTROUTING -s 10.99.0.0/24 -o "$DEFAULT_IFACE" -j MASQUERADE

iptables -C FORWARD -s 10.99.0.0/24 -j ACCEPT 2>/dev/null || \
iptables -A FORWARD -s 10.99.0.0/24 -j ACCEPT

iptables -C FORWARD -d 10.99.0.0/24 -j ACCEPT 2>/dev/null || \
iptables -A FORWARD -d 10.99.0.0/24 -j ACCEPT

# Persist iptables
case "$OS" in
    debian|alpine)
        if command -v netfilter-persistent &>/dev/null; then
            netfilter-persistent save
        elif [ -d /etc/iptables ]; then
            iptables-save > /etc/iptables/rules.v4
        fi
        ;;
esac

log "iptables NAT configured"

# ─── Firewall ─────────────────────────────────────────────────
log "Opening UDP ports 500, 4500 (IKEv2)..."
if command -v ufw &>/dev/null; then
    ufw allow 500/udp
    ufw allow 4500/udp
elif command -v firewall-cmd &>/dev/null; then
    firewall-cmd --add-port=500/udp --permanent
    firewall-cmd --add-port=4500/udp --permanent
    firewall-cmd --reload
fi

echo ""
log "=== strongSwan installed ==="
log "Next: run vpn_configure.py to generate server + phone config"
log "      python vpn_configure.py --server-ip <public_ip> --output-dir ."
