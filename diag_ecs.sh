#!/bin/bash
# ECS 热更 MITM 一键诊断脚本
# 用法：chmod +x diag_ecs.sh && ./diag_ecs.sh
# 把完整输出贴给 Claude

echo "========== 1. 服务状态 =========="
sudo systemctl status mahjong-mitm-hotupdate --no-pager 2>/dev/null | head -15

echo ""
echo "========== 2. 进程线程状态 =========="
PID=$(pgrep -f "setup_mitm.py" | head -1)
if [ -n "$PID" ]; then
    echo "PID=$PID"
    cat /proc/$PID/status 2>/dev/null | grep -E "Threads|State|Name"
else
    echo "setup_mitm.py NOT RUNNING"
fi

echo ""
echo "========== 3. 监听端口 =========="
sudo ss -tlnp | grep -E ":(443|53|8002)"

echo ""
echo "========== 4. 本机自测 127.0.0.1:443 =========="
curl -k --connect-timeout 5 "https://127.0.0.1/hotfix_update?env=1&appid=1073&engine_ver=3.13&channel=10001116&version=1.0.0.0" 2>&1 | head -5

echo ""
echo "========== 5. 防火墙规则 =========="
sudo iptables -L INPUT -n --line-numbers 2>/dev/null | grep -E "443|dpt:443" || echo "no iptables 443 rules"
sudo ufw status 2>/dev/null | head -5 || echo "ufw not installed"

echo ""
echo "========== 6. 最近 1 小时日志（过滤掉扫描器噪音） =========="
sudo journalctl -u mahjong-mitm-hotupdate --since "1 hour ago" --no-pager 2>/dev/null | grep -vE "no A record|origin failed|nmap|favicon|sitemap|.git/config|HNAP1|ReportServer|evox" | tail -30

echo ""
echo "========== 7. 线程堆栈（卡在哪里） =========="
if [ -n "$PID" ]; then
    sudo cat /proc/$PID/task/*/stack 2>/dev/null | head -40
else
    echo "no PID, skip stack"
fi

echo ""
echo "========== 8. 内存/CPU =========="
if [ -n "$PID" ]; then
    ps -p $PID -o pid,pcpu,pmem,etime,comm 2>/dev/null
fi

echo ""
echo "========== 9. 网络连接状态 =========="
sudo ss -tnp | grep -E ":443" | head -20

echo ""
echo "========== DONE =========="
