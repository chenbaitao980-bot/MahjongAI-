#!/bin/bash
# ============================================================================
# ECS 回归测试 + 极端稳定性测试脚本
# 测试目标: mahjong-mitm-hotupdate + mahjong-mitm-watchdog
# 运行环境: ECS 8.136.32.137
# 注意: 破坏性测试会临时中断服务，脚本自带恢复逻辑
# ============================================================================

set -u

# ─── 配置 ───────────────────────────────────────────────────────────────────
HEALTH_URL="https://127.0.0.1:443/healthz"
RELAY_URL="http://127.0.0.1:8002/mode"
HOTFIX_URL="https://127.0.0.1:443/hotfix_update?env=1&appid=1073&engine_ver=3.13&channel=10001116_astc&version=1.0.1.1782&os=Android+16"
STATE_DIR="/var/lib/mahjong-mitm-watchdog"
LOG_FILE="/var/log/mahjong-mitm-watchdog.log"
ECS_IP="8.136.32.137"

# 测试参数
PROBE_INTERVAL=30       # watchdog 探测间隔
FAIL_THRESHOLD=3        # watchdog 失败阈值
TEST_TIMEOUT=$(( PROBE_INTERVAL * FAIL_THRESHOLD + 15 ))  # 3周期 + 缓冲 = 105s

PASS=0
FAIL=0
WARN=0

# ─── 工具函数 ───────────────────────────────────────────────────────────────
log_info()  { echo "[INFO]  $*"; }
log_pass()  { echo "[PASS]  $*"; ((PASS++)); }
log_fail()  { echo "[FAIL]  $*"; ((FAIL++)); }
log_warn()  { echo "[WARN]  $*"; ((WARN++)); }

get_counter() {
    local f="$STATE_DIR/$1.counter"
    [[ -f "$f" ]] && cat "$f" || echo 0
}

get_pid() {
    pgrep -f "setup_mitm.py.*$ECS_IP" | head -1
}

get_relay_pid() {
    pgrep -f "remote/noconfig/main.py.*port 8002" | head -1
}

probe_healthz() {
    local code
    code=$(curl --max-time 5 -ksS -o /dev/null -w '%{http_code}' "$HEALTH_URL" 2>/dev/null)
    [[ "$code" == "200" ]]
}

probe_mode() {
    local code
    code=$(curl --max-time 5 -ksS -o /dev/null -w '%{http_code}' "$RELAY_URL" 2>/dev/null)
    [[ "$code" == "200" ]]
}

wait_for_service() {
    local max_wait="${1:-30}"
    local waited=0
    while (( waited < max_wait )); do
        if probe_healthz && probe_mode; then
            return 0
        fi
        sleep 2
        ((waited += 2))
    done
    return 1
}

# ─── Phase 0: 前置检查 ──────────────────────────────────────────────────────
echo ""
echo "==================================================================="
echo "Phase 0: 前置检查"
echo "==================================================================="

# 0.1 服务状态
for svc in mahjong-mitm-hotupdate mahjong-tcp-proxy mahjong-relay-noconfig mahjong-mitm-watchdog; do
    if systemctl is-active --quiet "$svc"; then
        log_pass "$svc is active"
    else
        log_fail "$svc is NOT active"
    fi
done

# 0.2 进程存在
MITM_PID=$(get_pid)
RELAY_PID=$(get_relay_pid)
if [[ -n "$MITM_PID" ]]; then
    log_pass "setup_mitm process found (pid=$MITM_PID)"
else
    log_fail "setup_mitm process NOT found"
fi
if [[ -n "$RELAY_PID" ]]; then
    log_pass "relay-noconfig process found (pid=$RELAY_PID)"
else
    log_fail "relay-noconfig process NOT found"
fi

# ─── Phase 1: 回归测试（只读，零破坏）────────────────────────────────────────
echo ""
echo "==================================================================="
echo "Phase 1: 回归测试（只读，零破坏）"
echo "==================================================================="

# 1.1 /healthz
if probe_healthz; then
    log_pass "GET /healthz → 200"
else
    log_fail "GET /healthz → NOT 200"
fi

# 1.2 /mode
if probe_mode; then
    log_pass "GET /mode → 200"
else
    log_fail "GET /mode → NOT 200"
fi

# 1.3 hotfix_update 链路完整响应
resp=$(curl --max-time 10 -ksS "$HOTFIX_URL" 2>/dev/null)
if echo "$resp" | grep -q '"manifest_url"'; then
    log_pass "GET /hotfix_update → manifest_url present"
else
    log_fail "GET /hotfix_update → manifest_url MISSING"
fi
if echo "$resp" | grep -q "8.136.32.137"; then
    log_pass "GET /hotfix_update → ECS IP injected"
else
    log_fail "GET /hotfix_update → ECS IP NOT injected"
fi

# 1.4 version 字段存在且为支配版本
version=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('version',''))" 2>/dev/null)
if [[ -n "$version" ]]; then
    log_pass "GET /hotfix_update → version=$version"
else
    log_fail "GET /hotfix_update → version MISSING"
fi

# 1.5 project.manifest 可下载（回源 + patch）
# 从 version.manifest 中提取第一个 manifest_url
manifest_url=$(echo "$resp" | python3 -c "import sys,json; u=json.load(sys.stdin).get('manifest_url',[]); print(u[0] if u else '')" 2>/dev/null)
if [[ -n "$manifest_url" ]]; then
    pm_resp=$(curl --max-time 10 -ksS "$manifest_url" 2>/dev/null)
    if echo "$pm_resp" | grep -q '"file_list"'; then
        log_pass "GET project.manifest → file_list present"
    else
        log_fail "GET project.manifest → file_list MISSING"
    fi
    if echo "$pm_resp" | grep -q "NetConf.luac"; then
        log_pass "GET project.manifest → NetConf.luac entry present"
    else
        log_fail "GET project.manifest → NetConf.luac entry MISSING"
    fi
else
    log_fail "Cannot extract manifest_url from version.manifest"
fi

# 1.6 NetConf.luac 文件可下载
if [[ -n "$pm_resp" ]]; then
    netconf_name=$(echo "$pm_resp" | python3 -c "import sys,json; d=json.load(sys.stdin).get('file_list',{}); k=[x for x in d if 'netconf' in x.lower()][0] if d else ''; print(d.get(k,{}).get('name','') if k else '')" 2>/dev/null)
    if [[ -n "$netconf_name" ]]; then
        file_url="https://127.0.0.1:443/yj/files/$netconf_name"
        nc_resp=$(curl --max-time 10 -ksS "$file_url" 2>/dev/null | wc -c)
        if (( nc_resp > 1000 )); then
            log_pass "GET NetConf.luac → ${nc_resp}B (>1KB)"
        else
            log_fail "GET NetConf.luac → ${nc_resp}B (too small)"
        fi
    else
        log_fail "Cannot extract NetConf.luac name from project.manifest"
    fi
fi

# 1.7 DNS 劫持响应（UDP 53）
python3 -c "
import socket, struct, sys
def build_query(name):
    tid = b'\\xab\\xcd'
    flags = b'\\x01\\x00'
    counts = b'\\x00\\x01\\x00\\x00\\x00\\x00\\x00\\x00'
    q = b''
    for label in name.split('.'):
        q += bytes([len(label)]) + label.encode('ascii')
    q += b'\\x00\\x00\\x01\\x00\\x01'
    return tid + flags + counts + q

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(3.0)
s.sendto(build_query('gxb-api.hzxuanming.com'), ('127.0.0.1', 53))
try:
    resp, _ = s.recvfrom(2048)
    ip = socket.inet_ntoa(resp[-4:])
    print(f'DNS gxb-api → {ip}')
    sys.exit(0 if ip == '$ECS_IP' else 1)
except socket.timeout:
    print('DNS timeout')
    sys.exit(1)
finally:
    s.close()
" 2>&1 | while read line; do
    if echo "$line" | grep -q "DNS gxb-api → $ECS_IP"; then
        log_pass "DNS hijack gxb-api.hzxuanming.com → $ECS_IP"
    elif echo "$line" | grep -q "DNS timeout"; then
        log_fail "DNS hijack timeout"
    elif echo "$line" | grep -q "DNS gxb-api"; then
        log_fail "DNS hijack wrong IP: $line"
    fi
done

# 1.8 watchdog 日志格式验证（最近 3 条是否含 timestamp + counter）
if tail -3 "$LOG_FILE" 2>/dev/null | grep -q "counter"; then
    log_pass "watchdog log contains counter entries"
else
    log_warn "watchdog log may not contain recent counter entries (service healthy = no failures)"
fi

# ─── Phase 2: 极端稳定性测试（可控破坏 + 恢复）────────────────────────────────
echo ""
echo "==================================================================="
echo "Phase 2: 极端稳定性测试（可控破坏 + 自动恢复）"
echo "==================================================================="

# ── Test A: SIGSTOP 模拟 handler 死锁 ───────────────────────────────────────
echo ""
echo "--- Test A: SIGSTOP handler 死锁 → watchdog 恢复 (${TEST_TIMEOUT}s) ---"

MITM_PID=$(get_pid)
if [[ -z "$MITM_PID" ]]; then
    log_fail "Cannot find setup_mitm pid for SIGSTOP test"
else
    # 记录测试前的 counter
    cnt_before=$(get_counter "mahjong-mitm-hotupdate")
    log_info "Before SIGSTOP: hotupdate counter = $cnt_before, pid = $MITM_PID"

    # 冻结进程（模拟 handler thread 全死但主线程活）
    kill -STOP "$MITM_PID" 2>/dev/null
    log_info "Sent SIGSTOP to pid=$MITM_PID (frozen)"

    # 等待 watchdog 探测失败并累加 counter
    log_info "Waiting ${TEST_TIMEOUT}s for watchdog to detect and restart..."
    sleep "$TEST_TIMEOUT"

    # 检查 counter 是否累加
    cnt_after=$(get_counter "mahjong-mitm-hotupdate")
    log_info "After ${TEST_TIMEOUT}s: hotupdate counter = $cnt_after"

    # 检查是否有 restart 日志
    if journalctl -u mahjong-mitm-watchdog --since "2 minutes ago" --no-pager 2>/dev/null | grep -q "RESTART mahjong-mitm-hotupdate"; then
        log_pass "SIGSTOP → watchdog detected failure and RESTARTED hotupdate"
    elif (( cnt_after > cnt_before )); then
        log_pass "SIGSTOP → counter increased $cnt_before → $cnt_after (watchdog working)"
    else
        # 可能 systemd 已经 restart 了（counter 被 reset）
        new_pid=$(get_pid)
        if [[ "$new_pid" != "$MITM_PID" && -n "$new_pid" ]]; then
            log_pass "SIGSTOP → process restarted (pid $MITM_PID → $new_pid)"
        else
            log_fail "SIGSTOP → counter did not increase and no restart detected"
        fi
    fi

    # 恢复被 STOP 的进程（如果它还没被 systemd restart 的话）
    if kill -CONT "$MITM_PID" 2>/dev/null; then
        log_info "Sent SIGCONT to old pid=$MITM_PID"
    fi

    # 等待服务恢复
    if wait_for_service 30; then
        log_pass "Service recovered after SIGSTOP test"
    else
        log_warn "Service may need manual recovery after SIGSTOP test"
        # 强制 restart 确保恢复
        systemctl restart mahjong-mitm-hotupdate >/dev/null 2>&1
        sleep 3
        if wait_for_service 30; then
            log_pass "Service forcibly recovered"
        else
            log_fail "Service did NOT recover after forced restart"
        fi
    fi
fi

# ── Test B: 并发请求风暴（100 并发 × 50 请求）─────────────────────────────────
echo ""
echo "--- Test B: 并发请求风暴 (100 concurrent requests) ---"

MITM_PID=$(get_pid)
threads_before=$(cat /proc/$MITM_PID/status 2>/dev/null | grep Threads | awk '{print $2}')
fd_before=$(ls /proc/$MITM_PID/fd/ 2>/dev/null | wc -l)

# 使用后台并行 curl 模拟并发
TMPDIR=$(mktemp -d)
for i in $(seq 1 100); do
    (
        # 混合请求：healthz + hotfix_update + 扫描器路径
        case $((i % 4)) in
            0) curl -ksS -o /dev/null --max-time 5 "$HEALTH_URL" 2>/dev/null ;;
            1) curl -ksS -o /dev/null --max-time 5 "$HOTFIX_URL" 2>/dev/null ;;
            2) curl -ksS -o /dev/null --max-time 5 "https://127.0.0.1:443/.git/config" 2>/dev/null ;;
            3) curl -ksS -o /dev/null --max-time 5 "https://127.0.0.1:443/favicon.ico" 2>/dev/null ;;
        esac
    ) &
    # 每 20 个一批，避免 fork 炸弹
    if (( i % 20 == 0 )); then
        wait
    fi
done > "$TMPDIR/out.log" 2>&1
wait
rm -rf "$TMPDIR"

# 检查服务是否仍然存活
sleep 2
if probe_healthz && probe_mode; then
    log_pass "Concurrent storm → service still healthy"
else
    log_fail "Concurrent storm → service UNHEALTHY"
fi

# 检查 CLOSE-WAIT 是否累积
close_wait=$(ss -tan | grep ':443' | grep CLOSE-WAIT | wc -l)
if (( close_wait <= 2 )); then
    log_pass "Concurrent storm → CLOSE-WAIT count = $close_wait (acceptable)"
else
    log_warn "Concurrent storm → CLOSE-WAIT count = $close_wait (may accumulate)"
fi

# 检查线程/句柄是否泄漏
threads_after=$(cat /proc/$MITM_PID/status 2>/dev/null | grep Threads | awk '{print $2}')
fd_after=$(ls /proc/$MITM_PID/fd/ 2>/dev/null | wc -l)
if [[ -n "$threads_before" && -n "$threads_after" ]]; then
    if (( threads_after <= threads_before + 5 )); then
        log_pass "Thread count stable: $threads_before → $threads_after"
    else
        log_warn "Thread count grew: $threads_before → $threads_after"
    fi
fi
if [[ -n "$fd_before" && -n "$fd_after" ]]; then
    if (( fd_after <= fd_before + 10 )); then
        log_pass "FD count stable: $fd_before → $fd_after"
    else
        log_warn "FD count grew: $fd_before → $fd_after"
    fi
fi

# ── Test C: DNS 洪水测试 ─────────────────────────────────────────────────────
echo ""
echo "--- Test C: DNS flood (500 queries, mixed domains) ---"

python3 -c "
import socket, struct, sys, time

def build_query(name):
    tid = struct.pack('>H', 0xABCD)
    flags = b'\\x01\\x00'
    counts = b'\\x00\\x01\\x00\\x00\\x00\\x00\\x00\\x00'
    q = b''
    for label in name.split('.'):
        q += bytes([len(label)]) + label.encode('ascii')
    q += b'\\x00\\x00\\x01\\x00\\x01'
    return tid + flags + counts + q

domains = [
    'gxb-api.hzxuanming.com',
    'gxb-oss.hzxuanming.com',
    'www.baidu.com',
    'www.google.com',
    'example.com',
    'github.com',
    'aliyun.com',
    'tencent.com',
]

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(2.0)
ok = 0
fail = 0

for i in range(500):
    domain = domains[i % len(domains)]
    try:
        sock.sendto(build_query(domain), ('127.0.0.1', 53))
        resp, _ = sock.recvfrom(2048)
        ok += 1
    except socket.timeout:
        fail += 1
    except Exception:
        fail += 1

sock.close()
print(f'DNS flood: {ok} OK, {fail} FAIL')
sys.exit(0 if fail < 50 else 1)
" 2>&1 | while read line; do
    if echo "$line" | grep -q "DNS flood:"; then
        ok=$(echo "$line" | grep -oP '\d+(?= OK)')
        fail=$(echo "$line" | grep -oP '\d+(?= FAIL)')
        if (( fail < 50 )); then
            log_pass "DNS flood → $ok OK, $fail FAIL (acceptable)"
        else
            log_fail "DNS flood → $ok OK, $fail FAIL (too many failures)"
        fi
    fi
done

# DNS 洪水后服务健康检查
sleep 1
if probe_healthz && probe_mode; then
    log_pass "DNS flood → service still healthy"
else
    log_fail "DNS flood → service UNHEALTHY"
fi

# ── Test D: relay-noconfig /mode 独立监督 ───────────────────────────────────
echo ""
echo "--- Test D: relay-noconfig /mode failure → watchdog restart ---"

RELAY_PID=$(get_relay_pid)
if [[ -z "$RELAY_PID" ]]; then
    log_fail "Cannot find relay-noconfig pid for test"
else
    cnt_before=$(get_counter "mahjong-relay-noconfig")
    log_info "Before SIGSTOP relay: counter = $cnt_before, pid = $RELAY_PID"

    kill -STOP "$RELAY_PID" 2>/dev/null
    log_info "Sent SIGSTOP to relay-noconfig pid=$RELAY_PID"

    sleep "$TEST_TIMEOUT"

    cnt_after=$(get_counter "mahjong-relay-noconfig")
    log_info "After ${TEST_TIMEOUT}s: relay-noconfig counter = $cnt_after"

    # 检查是否触发 restart
    if journalctl -u mahjong-mitm-watchdog --since "2 minutes ago" --no-pager 2>/dev/null | grep -q "RESTART mahjong-relay-noconfig"; then
        log_pass "SIGSTOP relay → watchdog detected and RESTARTED relay-noconfig"
    elif (( cnt_after > cnt_before )); then
        log_pass "SIGSTOP relay → counter increased $cnt_before → $cnt_after"
    else
        new_pid=$(get_relay_pid)
        if [[ "$new_pid" != "$RELAY_PID" && -n "$new_pid" ]]; then
            log_pass "SIGSTOP relay → process restarted (pid $RELAY_PID → $new_pid)"
        else
            log_fail "SIGSTOP relay → no counter increase or restart detected"
        fi
    fi

    kill -CONT "$RELAY_PID" 2>/dev/null

    if wait_for_service 30; then
        log_pass "Service recovered after relay SIGSTOP test"
    else
        systemctl restart mahjong-relay-noconfig >/dev/null 2>&1
        sleep 3
        if wait_for_service 30; then
            log_pass "Service forcibly recovered after relay test"
        else
            log_fail "Service did NOT recover after relay forced restart"
        fi
    fi
fi

# ─── Phase 3: 最终回归验证 ──────────────────────────────────────────────────
echo ""
echo "==================================================================="
echo "Phase 3: 最终回归验证"
echo "==================================================================="

# 确保所有服务都恢复
for svc in mahjong-mitm-hotupdate mahjong-tcp-proxy mahjong-relay-noconfig mahjong-mitm-watchdog; do
    if systemctl is-active --quiet "$svc"; then
        log_pass "$svc active (final check)"
    else
        log_fail "$svc NOT active (final check)"
        systemctl restart "$svc" >/dev/null 2>&1
    fi
done

# 最终健康检查
if probe_healthz; then
    log_pass "Final /healthz → 200"
else
    log_fail "Final /healthz → NOT 200"
fi
if probe_mode; then
    log_pass "Final /mode → 200"
else
    log_fail "Final /mode → NOT 200"
fi

# 热更链路最终验证
resp=$(curl --max-time 10 -ksS "$HOTFIX_URL" 2>/dev/null)
if echo "$resp" | grep -q '"manifest_url"'; then
    log_pass "Final hotfix_update → manifest_url present"
else
    log_fail "Final hotfix_update → manifest_url MISSING"
fi

# ─── 汇总 ───────────────────────────────────────────────────────────────────
echo ""
echo "==================================================================="
echo "                         测试汇总"
echo "==================================================================="
echo "  PASS: $PASS"
echo "  FAIL: $FAIL"
echo "  WARN: $WARN"
echo "==================================================================="

if (( FAIL == 0 )); then
    echo "  结果: ALL PASS ✅"
    exit 0
else
    echo "  结果: $FAIL failure(s) detected ❌"
    exit 1
fi
