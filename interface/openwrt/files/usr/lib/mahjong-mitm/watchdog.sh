#!/bin/sh
# mahjong-mitm watchdog: probe /healthz, restart service on N consecutive failures.
# Run via: setsid sh /usr/lib/mahjong-mitm/watchdog.sh "$tls_port" >/dev/null 2>&1 &

TLS_PORT="${1:-443}"
FAIL_COUNT=0
FAIL_THRESHOLD=3

while true; do
	sleep 30
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
done
