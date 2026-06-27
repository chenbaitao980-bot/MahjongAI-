#!/bin/sh
# mahjong-mitm watchdog: probe /healthz, restart service on N consecutive failures.
# Also retries gxb DNAT rules (init.d's apply_gxb_dnat may fail if WAN not ready at boot).
# Run via: setsid sh /usr/lib/mahjong-mitm/watchdog.sh "$tls_port" "$host_ip" >/dev/null 2>&1 &

TLS_PORT="${1:-443}"
HOST_IP="${2:-192.168.6.1}"
FAIL_COUNT=0
FAIL_THRESHOLD=3

# gxb DNAT retry state
GXB_DNAT_APPLIED=0
GXB_RETRIES=0
GXB_MAX_RETRIES=10

_apply_gxb_dnat() {
	# Check if rules already exist
	nft list chain inet fw4 mahjong_mitm_dns 2>/dev/null | grep -q 'mahjong-gxb-dnat' && return 0

	local resolver="/usr/lib/mahjong-mitm/resolve-gxb.sh"
	[ -x "$resolver" ] || return 0

	sh "$resolver" "$HOST_IP" 2>/tmp/mahjong-gxb-resolve.log >/tmp/mahjong-gxb-rules.nft
	if grep -q '^add rule' /tmp/mahjong-gxb-rules.nft 2>/dev/null; then
		nft -f /tmp/mahjong-gxb-rules.nft 2>>/tmp/mahjong-gxb-resolve.log || true
		logger -t mahjong-mitm "watchdog: gxb DNAT rules applied"
		return 0
	fi
	return 1
}

ITER=0
while true; do
	sleep 30
	ITER=$((ITER + 1))

	# --- Health probe (every cycle) ---
	BODY=$(wget --no-check-certificate -q -O- --timeout=5 "https://127.0.0.1:$TLS_PORT/healthz" 2>/dev/null | head -c 40)
	if echo "$BODY" | grep -q '"status":"ok"'; then
		FAIL_COUNT=0
	else
		FAIL_COUNT=$((FAIL_COUNT + 1))
		logger -t mahjong-mitm "watchdog: health probe failed ($FAIL_COUNT/$FAIL_THRESHOLD)"
		if [ "$FAIL_COUNT" -ge "$FAIL_THRESHOLD" ]; then
			logger -t mahjong-mitm "watchdog: threshold reached, restarting service"
			/etc/init.d/mahjong-mitm restart
			FAIL_COUNT=0
		fi
	fi

	# --- gxb DNAT retry (every ~2 min, not applied yet, retries left) ---
	if [ "$GXB_DNAT_APPLIED" -eq 0 ] && [ "$GXB_RETRIES" -lt "$GXB_MAX_RETRIES" ] && [ $((ITER % 4)) -eq 0 ]; then
		GXB_RETRIES=$((GXB_RETRIES + 1))
		if _apply_gxb_dnat; then
			GXB_DNAT_APPLIED=1
		else
			logger -t mahjong-mitm "watchdog: gxb DNAT retry $GXB_RETRIES/$GXB_MAX_RETRIES"
		fi
	fi
done
