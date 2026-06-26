# SSH ECS — 远程服务器运维

Connect to and operate the ECS server for MahjongAI MITM service.

## Server Info

| Key | Value |
|-----|-------|
| Host | `8.136.32.137` |
| User | `root` |
| Password | `Ysydxhyz111` |
| SSH Options | `-o StrictHostKeyChecking=no -o ConnectTimeout=10` |

## Quick Connect

```bash
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 root@8.136.32.137 "<command>"
```

## Common Operations

### Service Status
```bash
ssh -o StrictHostKeyChecking=no root@8.136.32.137 "systemctl status mahjong-mitm-hotupdate --no-pager -l"
```

### Restart MITM Service
```bash
ssh -o StrictHostKeyChecking=no root@8.136.32.137 "systemctl restart mahjong-mitm-hotupdate"
```

### Check Logs (last 30 lines)
```bash
ssh -o StrictHostKeyChecking=no root@8.136.32.137 "journalctl -u mahjong-mitm-hotupdate --no-pager -n 30"
```

### Check Logs (last 5 minutes)
```bash
ssh -o StrictHostKeyChecking=no root@8.136.32.137 "journalctl -u mahjong-mitm-hotupdate --since '5 minutes ago' --no-pager"
```

### Check Network Connections
```bash
ssh -o StrictHostKeyChecking=no root@8.136.32.137 "ss -tn | head -20"
```

### Check CLOSE-WAIT Count
```bash
ssh -o StrictHostKeyChecking=no root@8.136.32.137 "ss -tn | grep CLOSE-WAIT | wc -l"
```

### Health Check via localhost
```bash
ssh -o StrictHostKeyChecking=no root@8.136.32.137 "curl -sk https://127.0.0.1/healthz"
```

### Test Scanner Reject
```bash
ssh -o StrictHostKeyChecking=no root@8.136.32.137 "curl -sk -w '%{http_code}' -o /dev/null https://127.0.0.1/.git/config"
```

### Test Normal Request
```bash
ssh -o StrictHostKeyChecking=no root@8.136.32.137 "curl -sk -w '%{http_code}' -o /dev/null 'https://127.0.0.1/hotfix_update?env=1&appid=1073&version=1.0.0.50'"
```

## File Transfer

### Upload file to ECS
```bash
scp -o StrictHostKeyChecking=no <local_path> root@8.136.32.137:<remote_path>
```

### Upload setup_mitm.py (standard path)
```bash
scp -o StrictHostKeyChecking=no remote/noconfig/hijack/setup_mitm.py root@8.136.32.137:/opt/mahjong-remote/remote/noconfig/hijack/setup_mitm.py
```

## Deploy & Restart

Full deploy flow after code change:

```bash
# 1. Upload
scp -o StrictHostKeyChecking=no remote/noconfig/hijack/setup_mitm.py root@8.136.32.137:/opt/mahjong-remote/remote/noconfig/hijack/setup_mitm.py

# 2. Restart
ssh -o StrictHostKeyChecking=no root@8.136.32.137 "systemctl restart mahjong-mitm-hotupdate"

# 3. Verify (wait 2s then check)
ssh -o StrictHostKeyChecking=no root@8.136.32.137 "sleep 2 && systemctl is-active mahjong-mitm-hotupdate && curl -sk https://127.0.0.1/healthz"
```

## Troubleshooting Checklist

| Symptom | Check Command | Expected |
|---------|--------------|----------|
| Service dead | `systemctl is-active mahjong-mitm-hotupdate` | `active` |
| Scanner DOS | `journalctl -u mahjong-mitm-hotupdate \| grep 'scanner reject' \| wc -l` | Should see reject lines, not DNS timeouts |
| CLOSE-WAIT leak | `ss -tn \| grep CLOSE-WAIT \| wc -l` | < 5 |
| DNS timeout leak | `journalctl -u mahjong-mitm-hotupdate \| grep 'resolve.*no A record' \| wc -l` | 0 (R1 fix prevents this) |
| Backlog full | `ss -tn \| awk '$2>0'` | Empty recv-q |
| Health check | `curl -sk https://127.0.0.1/healthz` | `{"status":"ok"}` |
