# SSH Remote Server Ops — 远程服务器运维模板

Connect to and operate a remote server for MahjongAI services.

> **Usage**: Replace `$HOST`, `$USER`, and paths with actual values from the project context or user-provided credentials.

## Prerequisites

Before connecting, you need:
- Server IP/hostname (`$HOST`)
- SSH user (`$USER`, typically `root` for cloud VPS)
- Authentication method (password or key)

## Quick Connect

```bash
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 $USER@$HOST "<command>"
```

## Common Operations (Template)

Replace `$HOST`, `$USER`, and service names as needed.

### Service Status
```bash
ssh -o StrictHostKeyChecking=no $USER@$HOST "systemctl status <service> --no-pager -l"
```

### Restart Service
```bash
ssh -o StrictHostKeyChecking=no $USER@$HOST "systemctl restart <service>"
```

### Check Logs (last 30 lines)
```bash
ssh -o StrictHostKeyChecking=no $USER@$HOST "journalctl -u <service> --no-pager -n 30"
```

### Check Logs (last 5 minutes)
```bash
ssh -o StrictHostKeyChecking=no $USER@$HOST "journalctl -u <service> --since '5 minutes ago' --no-pager"
```

### Check Network Connections
```bash
ssh -o StrictHostKeyChecking=no $USER@$HOST "ss -tn | head -20"
```

### Check CLOSE-WAIT Count
```bash
ssh -o StrictHostKeyChecking=no $USER@$HOST "ss -tn | grep CLOSE-WAIT | wc -l"
```

### Health Check via localhost
```bash
ssh -o StrictHostKeyChecking=no $USER@$HOST "curl -sk https://127.0.0.1/healthz"
```

### Test Scanner Reject
```bash
ssh -o StrictHostKeyChecking=no $USER@$HOST "curl -sk -w '%{http_code}' -o /dev/null https://127.0.0.1/.git/config"
```

### Test Normal Request
```bash
ssh -o StrictHostKeyChecking=no $USER@$HOST "curl -sk -w '%{http_code}' -o /dev/null 'https://127.0.0.1/hotfix_update?env=1&appid=1073&version=1.0.0.50'"
```

## File Transfer

### Upload file to remote server
```bash
scp -o StrictHostKeyChecking=no <local_path> $USER@$HOST:<remote_path>
```

### Download file from remote server
```bash
scp -o StrictHostKeyChecking=no $USER@$HOST:<remote_path> <local_path>
```

## Deploy & Restart (Template)

Full deploy flow after code change:

```bash
# 1. Upload changed files
scp -o StrictHostKeyChecking=no <local_file> $USER@$HOST:<remote_deploy_path>/<file>

# 2. Restart service
ssh -o StrictHostKeyChecking=no $USER@$HOST "systemctl restart <service>"

# 3. Verify (wait 2s then check)
ssh -o StrictHostKeyChecking=no $USER@$HOST "sleep 2 && systemctl is-active <service> && curl -sk https://127.0.0.1/healthz"
```

## Troubleshooting Checklist

| Symptom | Check Command | Expected |
|---------|--------------|----------|
| Service dead | `systemctl is-active <service>` | `active` |
| Scanner DOS | `journalctl -u <service> \| grep 'scanner reject' \| wc -l` | Should see reject lines, not DNS timeouts |
| CLOSE-WAIT leak | `ss -tn \| grep CLOSE-WAIT \| wc -l` | < 5 |
| DNS timeout leak | `journalctl -u <service> \| grep 'resolve.*no A record' \| wc -l` | 0 |
| Backlog full | `ss -tn \| awk '$2>0'` | Empty recv-q |
| Health check | `curl -sk https://127.0.0.1/healthz` | `{"status":"ok"}` |

## Project-Specific Service Names

| Service | Description |
|---------|-------------|
| `mahjong-mitm-hotupdate` | 443 + DNS 热更 MITM |
| `mahjong-tcp-proxy` | 大厅 + 金币游服 SRS 代理 |
| `mahjong-relay-noconfig` | :8002 spectator relay |
| `mahjong-relay-hotspot` | :8000 热点模式 relay |
| `mahjong-relay-vpn` | :8001 VPN 模式 relay |
| `mahjong-spectator` | :8003 SRS spectator |
| `mjx-vpn` | VPN extractor |

## Code-Sync Discipline

> **CRITICAL**: Server is read-only mirror of local git. Never edit code directly on server.

```
Local modify → git commit → deploy script → server
                              ↑
                           one-way only
```

If server code differs from local git:
1. `scp $USER@$HOST:/opt/<path>/<file> <local_path>` — pull back
2. `git diff -- <file>` — review differences
3. `git add <file> && git commit -m "sync: pull <file> from server"`
4. Re-deploy via normal script

## Typical Deploy Paths

| Component | Remote Path |
|-----------|-------------|
| MITM setup_mitm.py | `/opt/mahjong-remote/remote/noconfig/hijack/setup_mitm.py` |
| tcp_proxy.py | `/opt/mahjong-remote/remote/noconfig/hijack/tcp_proxy.py` |
| relay core | `/opt/mahjong-remote/remote/relay/` |
| APK | `/opt/mahjong-remote/apk/game_base.apk` |
| extractor (VPN) | `/opt/mahjong-extractor/` |
