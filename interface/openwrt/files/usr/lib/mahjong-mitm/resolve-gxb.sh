#!/bin/sh
# resolve-gxb.sh — 把热更域名的真实 CDN IP 解析出来，生成 nftables DNAT 规则
#                  把手机连到这些 IP:443 的流量透明重定向到本机 192.168.6.1:443。
#
# 调用：sh /usr/lib/mahjong-mitm/resolve-gxb.sh <host_ip>
#       输出: 一组 `nft add rule ...` 命令到 stdout。
#
# 为什么需要这个：
#   手机的 DNS 解析有缓存（Android 默认 ~60s 到 数分钟）。如果在我们启动 MITM
#   之前手机已经查过 gxb-* 域名，它会缓存真实 CDN IP（121.40.48.x / 43.180.x.x
#   等），直接跳过 DNS 重新查询，绕过我们的 5353 劫持。
#
#   解决：把所有指向真实 CDN IP 的 TCP 443 流量也 DNAT 到本机。游戏热更下载器
#   VERIFYPEER=0 不校验证书，SNI 仍是真实域名，我们能识别处理。

HOST_IP="${1:-192.168.6.1}"

HOSTS="gxb-api.hzxuanming.com gxb-api-tx.hzxuanming.com gxb-oss.hzxuanming.com gxb-cos.hzxuanming.com gxb-oss.imeete.com gxb-cos.imeete.com"

# 用固定公共 DNS 解析（绕过本机 dnsmasq）
RESOLVER="119.29.29.29"

# 收集所有解析出的 IPv4
ALL_IPS=""
for h in $HOSTS; do
	# busybox nslookup 输出多行：取 Address 后的 IPv4
	IPS=$(nslookup "$h" "$RESOLVER" 2>/dev/null | awk '/^Address[: ]/ && $NF ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ {print $NF}' | grep -v "^${RESOLVER}\$")
	for ip in $IPS; do
		# 跳过空/loopback/local
		case "$ip" in
			""|127.*|192.168.*|10.*|172.16.*|172.17.*|172.18.*|172.19.*|172.20.*|172.21.*|172.22.*|172.23.*|172.24.*|172.25.*|172.26.*|172.27.*|172.28.*|172.29.*|172.30.*|172.31.*)
				continue ;;
		esac
		ALL_IPS="$ALL_IPS $ip"
		echo "[resolve] $h -> $ip" >&2
	done
done

# 去重
UNIQ_IPS=$(echo "$ALL_IPS" | tr ' ' '\n' | sort -u | grep -v '^$' | tr '\n' ',' | sed 's/,$//')

if [ -z "$UNIQ_IPS" ]; then
	echo "# WARN: resolve-gxb.sh resolved no real CDN IPs" >&2
	exit 0
fi

# 输出 nft 规则到 stdout，由调用者执行
cat <<EOF
add rule inet fw4 mahjong_mitm_dns iifname { "br-lan", "wlan0", "wlan1" } ip daddr { ${UNIQ_IPS} } tcp dport 443 dnat ip to ${HOST_IP}:443 comment "mahjong-gxb-dnat"
EOF
