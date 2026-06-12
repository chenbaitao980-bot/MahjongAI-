#!/bin/bash
# MahjongAI Remote - ECS 三模式一键部署脚本
# 三种模式独立端口部署：热点(8000) / VPN(8001) / 无配置(8002) + spectator(8003)
#
# 用法: scp deploy_ecs.sh root@8.136.37.136:/tmp/ && ssh root@8.136.37.136 'bash /tmp/deploy_ecs.sh'
#
# 上传到阿里云 ECS 后以 root 运行

set -e

echo "=========================================="
echo "  MahjongAI Remote ECS 三模式部署"
echo "  热点(8000) / VPN(8001) / 无配置(8002) / spectator(8003)"
echo "=========================================="
echo ""

INSTALL_DIR="/opt/mahjong-remote"
ECS_IP=$(hostname -I | awk '{print $1}')
echo "  ECS IP: $ECS_IP"
echo ""

# ─── 1. Install system dependencies ─────────────────────────────────
echo "[1/7] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv tcpdump strongswan strongswan-pki libcharon-extra-plugins 2>/dev/null || \
yum install -y -q python3 python3-pip tcpdump strongswan 2>/dev/null || true
echo "   Done."
echo ""

# ─── 2. Create install directory ─────────────────────────────────
echo "[2/7] Creating $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
# 仅复制必要文件（避免复制 .git, .venv 等）
for dir in remote stable game config; do
    if [ -d "$dir" ]; then
        mkdir -p "$INSTALL_DIR/$dir"
        cp -r "$dir"/* "$INSTALL_DIR/$dir/" 2>/dev/null || true
    fi
done
# 复制顶层文件
for f in deploy_ecs.sh e2e_test.py; do
    [ -f "$f" ] && cp "$f" "$INSTALL_DIR/" 2>/dev/null || true
done
cd "$INSTALL_DIR"
echo "   Done."
echo ""

# ─── 3. Install Python deps ──────────────────────────────────
echo "[3/7] Installing Python packages..."
pip3 install fastapi uvicorn pyyaml requests cryptography scapy -q 2>/dev/null || \
python3 -m pip install fastapi uvicorn pyyaml requests cryptography scapy -q 2>/dev/null || true
echo "   Done."
echo ""

# ─── 4. Generate API tokens & configs ───────────────────────
echo "[4/7] Generating config files..."

HOTSPOT_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(12))")
VPN_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(12))")
NOCONFIG_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(12))")

# 热点模式配置 (Port 8000)
cat > remote/relay/config_hotspot.yaml << EOF
mode: hotspot
port: 8000
api_token: $HOTSPOT_TOKEN
game_server_ip: 47.96.0.227
game_server_port: 7777
handshake_blob: ''
auth_token_12b: ''
srs_sessionid: ''
push_timeout: 10
spectator_url: ''
EOF

# VPN模式配置 (Port 8001)
cat > remote/relay/config_vpn.yaml << EOF
mode: vpn
port: 8001
api_token: $VPN_TOKEN
game_server_ip: 47.96.0.227
game_server_port: 7777
handshake_blob: ''
auth_token_12b: ''
srs_sessionid: ''
push_timeout: 10
spectator_url: ''
EOF

# 无配置模式配置 (Port 8002)
cat > remote/relay/config_noconfig.yaml << EOF
mode: noconfig
port: 8002
api_token: $NOCONFIG_TOKEN
game_server_ip: 47.96.0.227
game_server_port: 7777
handshake_blob: ''
auth_token_12b: ''
srs_sessionid: ''
userid: newpt1084306678
push_timeout: 5
spectator_url: http://localhost:8003
EOF

# VPN模式 extractor 配置 (ECS本地抓包)
cat > remote/extractor/config_vpn_ecs.yaml << EOF
relay_url: http://127.0.0.1:8001
api_token: $VPN_TOKEN
game_port: 7777
vpn_interface: ipsec0
EOF

# 热点模式 extractor 配置 (ECS上接收外部推送)
cat > remote/extractor/config.yaml << EOF
relay_url: http://127.0.0.1:8000
api_token: $HOTSPOT_TOKEN
game_port: 7777
spectator_forensic_all_heads: true
EOF

echo ""
echo "  生成的 API Tokens (请保存!):"
echo "    热点模式 (8000): $HOTSPOT_TOKEN"
echo "    VPN模式  (8001): $VPN_TOKEN"
echo "    无配置   (8002): $NOCONFIG_TOKEN"
echo ""

# ─── 5. Create systemd services ────────────────────────────
echo "[5/7] Creating systemd services..."

# 热点模式 relay
cat > /etc/systemd/system/mahjong-relay-hotspot.service << SERVICE
[Unit]
Description=MahjongAI Relay - Hotspot Mode (Port 8000)
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 remote/relay/main.py --mode hotspot --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

# VPN模式 relay
cat > /etc/systemd/system/mahjong-relay-vpn.service << SERVICE
[Unit]
Description=MahjongAI Relay - VPN Mode (Port 8001)
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 remote/relay/main.py --mode vpn --host 0.0.0.0 --port 8001
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

# 无配置模式 relay
cat > /etc/systemd/system/mahjong-relay-noconfig.service << SERVICE
[Unit]
Description=MahjongAI Relay - No-Config Mode (Port 8002)
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 remote/relay/main.py --mode noconfig --host 0.0.0.0 --port 8002
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

# SRS Spectator（无配置模式专用）
cat > /etc/systemd/system/mahjong-spectator.service << SERVICE
[Unit]
Description=MahjongAI SRS Spectator Service (Port 8003)
After=network.target mahjong-relay-noconfig.service

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 -m remote.srs_spectator.main
Environment=RELAY_URL=http://127.0.0.1:8002
Environment=BIND_PORT=8003
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

# VPN模式 extractor（ECS本地抓VPN接口流量）
cat > /etc/systemd/system/mahjong-extractor-vpn.service << SERVICE
[Unit]
Description=MahjongAI Extractor - VPN Mode (tcpdump on ipsec0)
After=network.target mahjong-relay-vpn.service

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 remote/extractor/main.py --mode tcpdump --interface ipsec0 --config remote/extractor/config_vpn_ecs.yaml
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable mahjong-relay-hotspot mahjong-relay-vpn mahjong-relay-noconfig mahjong-spectator mahjong-extractor-vpn 2>/dev/null || true

echo "   Done."
echo ""

# ─── 6. Configure strongSwan VPN ───────────────────────────
echo "[6/7] Configuring strongSwan VPN (IPSec IKEv2)..."

# 仅在 strongSwan 未配置时执行
if [ ! -f /etc/ipsec.d/cacerts/ca.crt ] || [ ! -s /etc/ipsec.d/cacerts/ca.crt ]; then
    echo "   生成 CA 和服务器证书..."

    # 生成 CA
    ipsec pki --gen --type rsa --size 4096 --outform pem > /tmp/ca.key 2>/dev/null
    ipsec pki --self --ca --lifetime 3650 --in /tmp/ca.key --type rsa \
        --dn "C=CN, O=MahjongAI, CN=Mahjong CA" --outform pem > /tmp/ca.crt 2>/dev/null

    # 生成服务器证书
    ipsec pki --gen --type rsa --size 2048 --outform pem > /tmp/server.key 2>/dev/null
    ipsec pki --pub --in /tmp/server.key --type rsa | \
        ipsec pki --issue --lifetime 3650 --cacert /tmp/ca.crt --cakey /tmp/ca.key \
        --dn "C=CN, O=MahjongAI, CN=$ECS_IP" \
        --san "$ECS_IP" --flag serverAuth --flag ikeIntermediate --outform pem > /tmp/server.crt 2>/dev/null

    # 安装证书
    cp /tmp/ca.crt /etc/ipsec.d/cacerts/
    cp /tmp/server.crt /etc/ipsec.d/certs/
    cp /tmp/server.key /etc/ipsec.d/private/

    # 生成客户端证书 (PKCS12)
    ipsec pki --gen --type rsa --size 2048 --outform pem > /tmp/client.key 2>/dev/null
    ipsec pki --pub --in /tmp/client.key --type rsa | \
        ipsec pki --issue --lifetime 3650 --cacert /tmp/ca.crt --cakey /tmp/ca.key \
        --dn "C=CN, O=MahjongAI, CN=phone@mahjong" \
        --san "phone@mahjong" --outform pem > /tmp/client.crt 2>/dev/null

    openssl pkcs12 -export -inkey /tmp/client.key -in /tmp/client.crt \
        -certfile /tmp/ca.crt -passout pass:mahjong -out /tmp/mahjong-vpn.p12 2>/dev/null

    # 配置 ipsec.conf
    cat > /etc/ipsec.conf << IPSEC
config setup
    charondebug="ike 2, knl 2, cfg 2"

conn mahjong-vpn
    keyexchange=ikev2
    ike=aes256-sha256-modp2048!
    esp=aes256-sha256-modp2048!
    left=$ECS_IP
    leftcert=server.crt
    leftsendcert=always
    leftsubnet=0.0.0.0/0
    right=%any
    rightauth=eap-tls
    rightsourceip=10.10.0.0/24
    rightdns=8.8.8.8,8.8.4.4
    eap_identity=%identity
    auto=add
IPSEC

    # ipsec.secrets
    cat > /etc/ipsec.secrets << SECRETS
: RSA server.key
SECRETS

    chmod 600 /etc/ipsec.secrets

    # 启用 IP 转发
    echo 1 > /proc/sys/net/ipv4/ip_forward
    echo "net.ipv4.ip_forward = 1" >> /etc/sysctl.conf

    # NAT 规则
    iptables -t nat -A POSTROUTING -s 10.10.0.0/24 -o eth0 -j MASQUERADE 2>/dev/null || true

    # 重启 strongSwan
    ipsec restart 2>/dev/null || systemctl restart strongswan 2>/dev/null || true

    echo "   strongSwan VPN 已配置."
    echo "   客户端证书: /tmp/mahjong-vpn.p12 (密码: mahjong)"
    echo "   CA 证书: /etc/ipsec.d/cacerts/ca.crt"
else
    echo "   strongSwan 已配置, 跳过."
fi
echo ""

# ─── 7. Start services ───────────────────────────────────────
echo "[7/7] Starting services..."
systemctl start mahjong-relay-hotspot 2>/dev/null || echo "   [WARN] relay-hotspot 启动失败"
systemctl start mahjong-relay-vpn 2>/dev/null || echo "   [WARN] relay-vpn 启动失败"
systemctl start mahjong-relay-noconfig 2>/dev/null || echo "   [WARN] relay-noconfig 启动失败"
# spectator 由 noconfig relay 自动管理，不单独启动
# mahjong-extractor-vpn 需要VPN连接后才启动

echo ""
echo "=========================================="
echo "  部署完成!"
echo "=========================================="
echo ""
echo "  服务端口:"
echo "    热点模式 relay:  http://$ECS_IP:8000"
echo "    VPN模式 relay:   http://$ECS_IP:8001"
echo "    无配置 relay:    http://$ECS_IP:8002"
echo "    SRS spectator:   http://$ECS_IP:8003"
echo ""
echo "  API Tokens (请保存!):"
echo "    热点模式: $HOTSPOT_TOKEN"
echo "    VPN模式:  $VPN_TOKEN"
echo "    无配置:   $NOCONFIG_TOKEN"
echo ""
echo "  systemd 服务:"
echo "    systemctl status mahjong-relay-hotspot"
echo "    systemctl status mahjong-relay-vpn"
echo "    systemctl status mahjong-relay-noconfig"
echo "    systemctl status mahjong-spectator"
echo "    systemctl status mahjong-extractor-vpn"
echo ""
echo "  查询状态:"
echo "    curl http://$ECS_IP:8000/state?token=$HOTSPOT_TOKEN"
echo "    curl http://$ECS_IP:8001/state?token=$VPN_TOKEN"
echo "    curl http://$ECS_IP:8002/state?token=$NOCONFIG_TOKEN"
echo ""
echo "  VPN extractor (手机连VPN后启动):"
echo "    systemctl start mahjong-extractor-vpn"
echo ""
echo "  安全组需放行端口:"
echo "    TCP: 8000, 8001, 8002, 8003"
echo "    UDP: 500, 4500 (IPSec VPN)"
echo ""

# 保存 tokens 到文件，方便后续使用
cat > "$INSTALL_DIR/.deploy-tokens" << TOKENS
HOTSPOT_TOKEN=$HOTSPOT_TOKEN
VPN_TOKEN=$VPN_TOKEN
NOCONFIG_TOKEN=$NOCONFIG_TOKEN
ECS_IP=$ECS_IP
TOKENS
chmod 600 "$INSTALL_DIR/.deploy-tokens"
echo "  Tokens 已保存到: $INSTALL_DIR/.deploy-tokens"
echo ""
