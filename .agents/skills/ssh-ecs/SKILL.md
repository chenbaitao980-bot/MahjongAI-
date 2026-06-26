# SSH Remote Server Ops — MahjongAI ECS 运维

Connect to and operate the MahjongAI ECS server.

## Server Configuration (Fixed)

| Key | Value |
|-----|-------|
| Host | `8.136.32.137` |
| User | `root` |
| Auth | SSH key `~/.ssh/id_ed25519` (passwordless) |
| Project root | `/opt/mahjong-remote` |
| Services prefix | `mahjong-` |

> **Always use `-o StrictHostKeyChecking=no`** to avoid interactive prompts.

## Quick Connect (No Password)

```bash
ssh -o StrictHostKeyChecking=no root@8.136.32.137 "<command>"
```

## Server Read-Only Git Sync Discipline

> **CRITICAL**: Server is read-only mirror of local git. Never edit code directly on server.

```
Local modify → git commit → deploy via scp + ssh restart → server
                              ↑
                           one-way only
```

If server code differs from local git:
1. `scp root@8.136.32.137:/opt/mahjong-remote/<rel_path> <local_path>` — pull back
2. `git diff -- <file>` — review differences
3. `git add <file> && git commit -m "sync: pull <file> from server"`
4. Re-deploy via normal script

## File Transfer (No Password)

### Upload file to server
```bash
ssh -o StrictHostKeyChecking=no root@8.136.32.137 "cat > /opt/mahjong-remote/remote/noconfig/<file>" < <local_file>
```

### Download file from server
```bash
ssh -o StrictHostKeyChecking=no root@8.136.32.137 "cat /opt/mahjong-remote/<rel_path>" > <local_file>
```

## Service Operations

| Service | Description |
|---------|-------------|
| `mahjong-mitm-hotupdate` | 443 + DNS 热更 MITM |
| `mahjong-tcp-proxy` | 大厅 + 金币游服 SRS 代理 |
| `mahjong-relay-noconfig` | :8002 spectator relay |
| `mahjong-relay-hotspot` | :8000 热点模式 relay |
| `mahjong-relay-vpn` | :8001 VPN 模式 relay |
| `mahjong-spectator` | :8003 SRS spectator |
| `mjx-vpn` | VPN extractor |

### Status
```bash
ssh -o StrictHostKeyChecking=no root@8.136.32.137 \
  "systemctl status <service> --no-pager -l"
```

### Restart
```bash
ssh -o StrictHostKeyChecking=no root@8.136.32.137 \
  "systemctl restart <service>"
```

### Logs (last 30 lines)
```bash
ssh -o StrictHostKeyChecking=no root@8.136.32.137 \
  "journalctl -u <service> --no-pager -n 30"
```

### Logs (last 5 minutes)
```bash
ssh -o StrictHostKeyChecking=no root@8.136.32.137 \
  "journalctl -u <service> --since '5 minutes ago' --no-pager"
```

## Deploy & Restart

Full deploy flow after code change:

```bash
# 1. Upload changed files (example: tcp_proxy.py)
ssh -o StrictHostKeyChecking=no root@8.136.32.137 \
  "cat > /opt/mahjong-remote/remote/noconfig/hijack/tcp_proxy.py" < remote/noconfig/hijack/tcp_proxy.py

# 2. Restart service
ssh -o StrictHostKeyChecking=no root@8.136.32.137 \
  "systemctl restart <service>"

# 3. Verify
ssh -o StrictHostKeyChecking=no root@8.136.32.137 \
  "sleep 2 && systemctl is-active <service>"
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

## Typical Deploy Paths

| Component | Remote Path |
|-----------|-------------|
| MITM setup_mitm.py | `/opt/mahjong-remote/remote/noconfig/hijack/setup_mitm.py` |
| tcp_proxy.py | `/opt/mahjong-remote/remote/noconfig/hijack/tcp_proxy.py` |
| ecs_proxy.py | `/opt/mahjong-remote/remote/noconfig/hijack/ecs_proxy.py` |
| app.py | `/opt/mahjong-remote/remote/noconfig/app.py` |
| relay core | `/opt/mahjong-remote/remote/relay/` |
| APK | `/opt/mahjong-remote/apk/game_base.apk` |
