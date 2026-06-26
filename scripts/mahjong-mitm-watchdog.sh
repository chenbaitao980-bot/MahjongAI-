#!/bin/bash
# mahjong-mitm-watchdog.sh — 监督 ECS 上 mahjong-* 服务，防止"进程死锁但还活着"。
#
# 为什么需要（2026-06-26 沉淀）：
#   systemd 的 Restart=always 只能捕获**进程崩溃/退出**。setup_mitm 用
#   ThreadingHTTPServer + daemon thread + 主线程 threading.Event().wait()，
#   一旦 HTTP handler thread 全挂（死锁、CPU 100% 循环、handler 同步阻塞
#   等）但主线程不退出，systemd 完全无感 → 服务实际不可用却不会被重启。
#   06-26 修复的 CLOSE-WAIT 累积只是这类场景之一。
#
# 策略：
#   - 每 30s 探测 https://127.0.0.1:443/healthz + http://127.0.0.1:8002/mode
#   - 任一健康检查失败则记录 + 单独 systemctl restart
#   - 连续 3 次失败同一服务则升级为"两服务全 restart"（hotupdate + tcp_proxy）
#   - 用 .failure_counter 文件做状态持久化（脚本不写 state file 就无法跨重启感知）
#   - 自身被 systemd 监督（Restart=always），shell 死循环风险被兜底
#
# 部署：/usr/local/bin/mahjong-mitm-watchdog.sh
# 配套：scripts/mahjong-mitm-watchdog.service (Type=simple Restart=always)

set -u  # 不用 -e：探测失败是预期路径，不能让脚本退出

# ─── 可调参数（环境变量可覆盖，便于故障注入测试）────────────────
: "${HEALTH_URL:=https://127.0.0.1:443/healthz}"
: "${RELAY_URL:=http://127.0.0.1:8002/mode}"
: "${PROBE_INTERVAL:=30}"            # 探测间隔（秒）
: "${FAIL_THRESHOLD:=3}"             # 连续失败次数阈值 → 升级为两服务重启
: "${COOLDOWN_SECONDS:=300}"         # 同一服务两次 restart 最小间隔（5 分钟）
: "${STATE_DIR:=/var/lib/mahjong-mitm-watchdog}"
: "${LOG_FILE:=/var/log/mahjong-mitm-watchdog.log}"
: "${SYSTEMCTL_CMD:=systemctl}"      # 测试时可指向 mock 脚本（不真 restart）

WATCH_SERVICES=(
    "mahjong-mitm-hotupdate"
    "mahjong-tcp-proxy"
    "mahjong-relay-noconfig"
)
# /healthz 失败时同时 restart 的服务对（hotupdate 是健康检查被探测的目标，
# tcp_proxy 共享同一进程空间内 ifdown/网络/资源问题，关联性强）
CO_RESTART_PAIR=("mahjong-mitm-hotupdate" "mahjong-tcp-proxy")

# ─── 初始化 ─────────────────────────────────────────────────────
mkdir -p "$STATE_DIR" 2>/dev/null || STATE_DIR="/tmp/mahjong-mitm-watchdog"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || LOG_FILE="/tmp/mahjong-mitm-watchdog.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE" >&2
}

# 读 / 写 / 清除 服务的失败计数与上次 restart 时间戳
# 状态文件: $STATE_DIR/$svc.counter（int 失败次数）
#         $STATE_DIR/$svc.last_restart（int epoch seconds）
get_counter() {
    local svc="$1"
    local f="$STATE_DIR/$svc.counter"
    [[ -f "$f" ]] && cat "$f" || echo 0
}

set_counter() {
    local svc="$1" val="$2"
    echo "$val" > "$STATE_DIR/$svc.counter"
}

get_last_restart() {
    local svc="$1"
    local f="$STATE_DIR/$svc.last_restart"
    [[ -f "$f" ]] && cat "$f" || echo 0
}

set_last_restart() {
    local svc="$1" ts="$2"
    echo "$ts" > "$STATE_DIR/$svc.last_restart"
}

# ─── 健康探测 ───────────────────────────────────────────────────
# 探测一个 URL，返回 0=ok / 1=fail
#
# 检查 HTTP 状态码而非 curl 退出码，因为：
#   - Windows MSYS 上 curl -o /dev/null 即使 200 也可能返回非零("client
#     returned ERROR on write of N bytes")，用 -w "%{http_code}" 取真实状态
#   - 语义更对:"服务是否返回 2xx" 而不是 "curl 是否成功"
#   - 跨平台一致(Windows / Linux / macOS 都正确)
probe_url() {
    local url="$1"
    local code
    code=$(curl --max-time 5 -ksS -o /dev/null -w '%{http_code}' "$url" 2>/dev/null)
    [[ "$code" =~ ^[23] ]]
}

probe_all_health() {
    local fail=0
    probe_url "$HEALTH_URL" || fail=$((fail + 1))
    probe_url "$RELAY_URL"  || fail=$((fail + 1))
    echo "$fail"
}

# 重启服务（带冷却保护）
restart_service() {
    local svc="$1"
    local now
    now=$(date +%s)
    local last
    last=$(get_last_restart "$svc")
    local since=$((now - last))
    if (( since < COOLDOWN_SECONDS )); then
        log "SKIP restart $svc: cooldown $since s < $COOLDOWN_SECONDS s"
        return 1
    fi
    log "RESTART $svc (cooldown ok, since last = ${since}s)"
    "$SYSTEMCTL_CMD" restart "$svc"
    local rc=$?
    set_last_restart "$svc" "$now"
    set_counter "$svc" 0
    return $rc
}

# ─── 主循环 ─────────────────────────────────────────────────────
log "watchdog started: HEALTH=$HEALTH_URL RELAY=$RELAY_URL interval=${PROBE_INTERVAL}s threshold=$FAIL_THRESHOLD"

while true; do
    sleep "$PROBE_INTERVAL"

    # 1) 三个 unit 自身 active 状态（systemd 自身的健康）
    for svc in "${WATCH_SERVICES[@]}"; do
        if ! "$SYSTEMCTL_CMD" is-active --quiet "$svc" 2>/dev/null; then
            log "ALERT $svc not active: $("$SYSTEMCTL_CMD" is-active "$svc" 2>&1)"
            restart_service "$svc" || true
        fi
        # 注意：active 状态下**不**重置 counter —— counter 由下方 health probe
        # 决定成功/累加，避免「主线程活但 handler thread 全死」场景下 counter
        # 被 is-active 路径重置导致永不触发 restart（2026-06-26 4G 卡校验真因）。
    done

    # 2) /healthz + /mode 健康探测（捕获"进程活但不响应"）
    fails=$(probe_all_health)
    if (( fails == 0 )); then
        # 探测全部成功 → 重置所有 counter（只有成功才算"恢复"）
        for svc in "${CO_RESTART_PAIR[@]}"; do
            set_counter "$svc" 0
        done
        continue
    fi

    log "HEALTH probe failed: $fails/2 endpoints down"

    # 累加 hotupdate / tcp_proxy 的失败计数（noconfig 只看 /mode 自己管自己）
    for svc in "${CO_RESTART_PAIR[@]}"; do
        cnt=$(get_counter "$svc")
        cnt=$((cnt + 1))
        set_counter "$svc" "$cnt"
        log "  $svc fail counter = $cnt"

        if (( cnt >= FAIL_THRESHOLD )); then
            restart_service "$svc" || true
        fi
    done
done
