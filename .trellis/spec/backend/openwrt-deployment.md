# OpenWrt Deployment — python3-light Compatibility & Service Persistence

> Executable contract for the OpenWrt soft-router setup-period MITM (`interface/mahjong_mitm/` + `interface/openwrt/`).
> Reading order: this file → `.claude/skills/ops/openwrt-mitm-deploy/SKILL.md` for hands-on ops.

---

## Scenario: Run Python MITM on OpenWrt 22.03+ python3-light

### 1. Scope / Trigger

Triggered when **any** of:
- New module imports a stdlib that python3-light might strip (`logging`, `idna` codec, `ssl.create_default_context` deps, etc.)
- A new top-level `import` is added in `interface/mahjong_mitm/`
- The init.d or watchdog shell script changes
- The ipk packaging changes (tarball format, file paths, postinst)

The OpenWrt build of python3-light on GL.iNet Beryl AX (firmware 2026-04) is **partially gutted** — Python 3.11.14 binary plus a curated subset of stdlib. Anything that assumes "stdlib is available" can crash at import time, and BusyBox shell is **not** a drop-in for bash.

### 2. Signatures

#### Python entry point
```
python -m mahjong_mitm --host-ip <gateway> --ecs-ip <ip> --tls-port 443 \
                       --dns-port 5353 --dns-listen-host 0.0.0.0 \
                       --assets-dir /usr/lib/mahjong-mitm/assets
```

#### init.d service contract
```
/etc/init.d/mahjong-mitm {start|stop|restart|enable|disable}
USE_PROCD=1
START=95  STOP=10
PROG_DIR="/usr/lib/mahjong-mitm"
PYTHON="/usr/bin/python3"
```

#### Health probe contract
```
GET https://127.0.0.1:443/healthz  →  200 {"status":"ok"}
# 自签证书，wget 必须 --no-check-certificate
```

#### ipk package contract
```
mahjong-mitm_<ver>_all.ipk  (≤ 130 KB)
├── debian-binary           "2.0\n"
├── control.tar.gz          control + postinst + conffiles  (tarfile.GNU_FORMAT!)
└── data.tar.gz             /etc, /usr/lib/mahjong-mitm/    (tarfile.GNU_FORMAT!)
```

### 3. Contracts

#### Compatibility shim contract (`interface/mahjong_mitm/__init__.py`)

This file runs **before** any submodule import. It probes stdlib and installs shims unconditionally on import failure. PC paths see no behavior change — every shim is gated on `ImportError`/`LookupError`/`UnicodeError`.

| Probe | Trigger | Action |
|---|---|---|
| `import logging` raises ImportError | python3-light excludes `logging` | Inject `sys.modules["logging"]` with `_FakeLogger` (info/warning/error/exception/critical/debug all map to `print()`) |
| `"x".encode("idna")` raises | python3-light strips idna codec | `codecs.register(_idna_search)` returning ASCII codec; `socket.getfqdn = lambda n="": n or socket.gethostname()` |

#### urllib fallback contract (`setup_mitm.py::_origin_fetch`)

```
try: import requests; _HAS_REQUESTS = True
except ImportError: _HAS_REQUESTS = False

def _origin_fetch(host, path) -> (status, body, ctype):
    if _HAS_REQUESTS: use requests.Session(trust_env=False, verify=False, timeout=(3.05, ORIGIN_TIMEOUT))
    else:            use urllib.request.urlopen(req, timeout=ORIGIN_TIMEOUT, context=ssl.CERT_NONE)
```

`headers={"Host": host}` is mandatory in both paths (回源走真实 IP，靠 Host 头让上游识别业务)。

#### nftables persistence contract (`/etc/nftables.d/99-mahjong-mitm.nft`)

| Chain | Hook | Priority | Purpose |
|---|---|---|---|
| `mahjong_mitm_dns` | nat prerouting | dstnat-5 | UDP/TCP 53 from LAN → :5353; runtime-appended DNAT rule for gxb-* real CDN IPs → 192.168.6.1:443 |
| `mahjong_mitm_block_doh` | filter forward | -10 | TCP 853 (DoT) reject-with-tcp-reset; public DoH IP:443 reject; IPv6 :53/853 reject |

Loaded automatically by `fw4 reload` (OpenWrt 22.03+ fw4 includes `/etc/nftables.d/*.nft`).

#### Service supervision contract

| Component | Spawn | Stop |
|---|---|---|
| Python | `procd_open_instance` (auto-respawn 3600/5/5) | `procd` SIGTERM via init.d stop |
| Watchdog | `setsid sh /usr/lib/mahjong-mitm/watchdog.sh "$tls_port" </dev/null >/dev/null 2>&1 &` | `kill $(cat /var/run/mahjong-mitm-watchdog.pid)` + busybox-compatible `ps | grep | awk | kill` 兜底 |
| gxb DNAT | `apply_gxb_dnat` 在每次 start 时跑 `resolve-gxb.sh` → 解析 6 个 gxb-* 域名 → `nft add rule` 注入 | 随服务 stop 不主动删（下次 start 时 `fw4 reload` 清空再重灌） |

### 4. Validation & Error Matrix

| Condition | Symptom | Fix |
|---|---|---|
| ipk uses `tarfile.DEFAULT_FORMAT` (PAX) | `opkg install: get_header_tar: Unknown typeflag: 0x78` | Always pass `format=tarfile.GNU_FORMAT` |
| ipk arch is `all` but `arch.conf` lacks it | `incompatible with the architectures configured` | `opkg install --force-architecture` 或手动 tar 解包 |
| __init__.py 未注册 idna shim | `LookupError: unknown encoding: idna` 在 ThreadingHTTPServer 或 urllib.request | `codecs.register(_idna_search)` |
| `socket.getfqdn` 仍走 C 层 IDN | start_https_server bind 时报 idna | 兜底 monkey-patch `socket.getfqdn = lambda n="": n or hostname()` |
| init.d 用 `fuser -k 443/tcp` 或 `lsof -ti:443` | exit 127 command not found，旧 python 没被 kill → 443 Address in use crash loop | 改用 `ps w | grep mahjong_mitm | awk '{print $1}' | xargs kill -9` |
| watchdog 用 `(...) &` 而非 setsid | `/etc/init.d/mahjong-mitm start/stop` paramiko 永远 timeout，僵尸 init shell 累积 | `setsid sh watchdog.sh "$tls_port" </dev/null >/dev/null 2>&1 &` |
| watchdog 用 heredoc 在 init.d 现场生成 | BusyBox shell 行尾解析卡死，start 永不返回 | 把 watchdog 拆成独立可执行文件 `/usr/lib/mahjong-mitm/watchdog.sh` |
| watchdog 探活用 `http://127.0.0.1:443/healthz` | 永远 fail（服务是 TLS）→ 探活计数永远涨 → 持续 restart | 用 `wget --no-check-certificate https://127.0.0.1:$tls_port/healthz` |
| 手机有 DNS 缓存的真实 CDN IP | DNS redirect 不生效（手机不查 DNS）→ MITM 拿不到请求 | `resolve-gxb.sh` 在 start 时把 gxb-* 真实 IP 加进 DNAT 链 |
| 手机开了 Private DNS (DoT 853 / DoH) | UDP 53 完全没流量，MITM 拿不到请求 | `mahjong_mitm_block_doh` 链 reject DoT/DoH |
| origin fetch 失败 fallback static | 手机 harbor 写入伪版本 9.9.9.103 → 下次跳过热更 | 修 origin fetch 根因；用户清游戏数据/重装才能恢复 |
| **冷启动 WAN 未就绪，gxb 解析失败** | **开机后 logread 无 `gxb DNAT` 消息 → 手机有 DNS 缓存时热更不触发** | **init.d 后台重试（30s×10）+ watchdog setsid 兜底** |

### 5. Good / Base / Bad Cases

#### Good
- 路由器重启后 30~60s `wget --no-check-certificate https://127.0.0.1:443/healthz` → `{"status":"ok"}`
- 手机连 WiFi 5~10s 后 logread 出现 `[mitm] 192.168.6.211 host=gxb-oss.imeete.com → /yj/files/... (origin 200)`
- 进度条跑完后看到 `[CHAIN-PROJ] client=192.168.6.211 ... netconf_md5=<X>(const) update_url→ECS=https://8.136.32.137/...`

#### Base
- 手机连 WiFi 后只看到 DNS 命中（5353 counter > 0），但 443 入站为 0 → DoH 没拦完，或手机 DNS 缓存了
- procd crash 1~2 次后稳定（443 抢占被旧 python 占着，next-respawn 清干净）
- gxb DNAT 初始解析失败，后台重试 ~5 分钟内自动恢复 → logread 出现 `gxb DNAT applied after retry #N`

#### Bad
- procd "in a crash loop 6 crashes" 不再 respawn → init.d disable 后清残留 python 再 start
- /healthz timeout 但 python3 进程在 → 证书路径不对 / TLS 监听到 127.0.0.1 而非 0.0.0.0 → 看启动日志
- gxb DNAT 10 次重试全部失败（`all 10 retries exhausted`）→ WAN 不通或 DNS 解析器 119.29.29.29 不可达

### 6. Tests Required

| Level | What | Assertion |
|---|---|---|
| PC unit | `python -m mahjong_mitm --selftest` | 所有 [OK]，含 patch_real_project_manifest / patch_real_version_manifest |
| PC integration | `python -m mahjong_mitm` + 本地 `curl --resolve` 测 hotfix_update | 200 + version=99.99.99.9999 + manifest_url 指向 ECS |
| Router smoke (post-install) | `ps w \| grep python3 \| grep mahjong`、`netstat -tlnp \| grep -E ':(443\|5353)'`、`/healthz` | 进程在 + 端口在 + healthz=ok |
| Router smoke (post-reboot) | `ls /etc/rc.d/ \| grep mahjong`（期望 S95mahjong-mitm） + 上述三项 | 自启 + 健康 |
| Phone E2E | 清游戏数据后连 WiFi 开游戏 | logread 出现 `[mitm] ... host=gxb-oss.imeete.com` + 资源文件 origin 200 |
| nft 规则 sanity | `nft list chain inet fw4 mahjong_mitm_dns` + `mahjong_mitm_block_doh` | 两条链都在；redirect 规则在；reject 规则在 |

### 7. Wrong vs Correct

#### Wrong — watchdog 直接挂在父 shell

```sh
# /etc/init.d/mahjong-mitm start_service()
(
    while true; do
        sleep 30
        wget -q http://127.0.0.1:443/healthz || ...
    done
) &
echo $! > /var/run/mahjong-mitm-watchdog.pid
```

后果：
1. `/etc/init.d/mahjong-mitm start` 由 SSH exec_command 调用时**永不返回**（子 shell 仍占着 stdout 句柄）
2. `wget http://` 探一个 TLS 端口必然 fail → watchdog 一直 restart 服务
3. 每次 start 都累积一个僵尸 `{mahjong-mitm} /bin/sh /etc/rc.common /etc/init.d/mahjong-mitm restart` 进程

#### Correct — setsid + 独立 watchdog.sh + https 探活

```sh
# /etc/init.d/mahjong-mitm start_service()
WATCHDOG_BIN="$PROG_DIR/watchdog.sh"
[ -x "$WATCHDOG_BIN" ] && {
    setsid sh "$WATCHDOG_BIN" "$tls_port" </dev/null >/dev/null 2>&1 &
    echo $! > /var/run/mahjong-mitm-watchdog.pid
}
```

```sh
# /usr/lib/mahjong-mitm/watchdog.sh
#!/bin/sh
TLS_PORT="${1:-443}"
while true; do
    sleep 30
    BODY=$(wget --no-check-certificate -q -O- --timeout=5 \
                "https://127.0.0.1:$TLS_PORT/healthz" 2>/dev/null | head -c 40)
    echo "$BODY" | grep -q '"status":"ok"' || ...
done
```

效果：
1. `setsid` 把 watchdog 移到独立 session，父 init.d 立刻退出 → SSH exec_command 正常返回
2. `</dev/null >/dev/null 2>&1` 切断所有标准句柄，channel 不会被卡住
3. https + 自签证书探对（200 ok），不再误判服务挂掉
4. 探活只在**失败**时 logger（成功不刷屏）

---

### Convention: PC/OpenWrt 双模兼容写法

**What**: 所有跨平台运行的 Python 模块顶层，必须保证 import 期在 python3-light 上不爆炸。

**Why**: python3-light 把若干常用 stdlib 剥了（`logging` / `idna` / `requests`），普通的 `import` 会让整个进程 ImportError 退出，procd 看不到任何应用级日志只看到 exit code，调试极痛。

**Example**:

```python
# interface/mahjong_mitm/__init__.py — 包入口，提前装 shim
try:
    import logging  # noqa: F401
except ImportError:
    # ...inject sys.modules["logging"] with _FakeLogger
try:
    "x".encode("idna")
except (LookupError, UnicodeError):
    # ...codecs.register(_idna_search) + socket.getfqdn 兜底

# interface/mahjong_mitm/setup_mitm.py
try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False
```

**Don't**: 把 shim 写在 `setup_mitm.py` 顶部。子模块 `from .netconf_patch import ...` 在 setup_mitm import 之前已经走完 → netconf_patch 的 `import logging` 提前爆炸。Shim 必须在**包 `__init__.py`** 里以保证最早执行。

### Convention: BusyBox 兼容的 shell 写法

**What**: 所有 init.d / 部署脚本必须只用 BusyBox 自带工具。

**Why**: OpenWrt 默认 BusyBox 不带 `pkill` / `fuser` / `lsof` / `timeout` / `xargs -I`，写惯了 bash 的脚本到路由器上一半命令报 `command not found`。

**Example**:

```sh
# ✅ busybox-safe: kill all matching processes
for pid in $(ps w | grep -E 'mahjong_mitm|python3' | grep -v grep | awk '{print $1}'); do
    kill -9 "$pid" 2>/dev/null
done

# ❌ Don't:
pkill -f mahjong_mitm     # pkill 没装
fuser -k 443/tcp          # fuser 没装
lsof -ti:443 | xargs kill # 都没装
timeout 5 some_cmd        # timeout applet 默认不在
```

### Don't: Heredoc 生成 watchdog 脚本

```sh
# ❌ start_service() 里现场生成 watchdog
cat > "$WATCHDOG_SCRIPT" <<EOF
#!/bin/sh
HTTP_BODY=\$(wget --no-check-certificate -q -O- --timeout=5 ...)
...
EOF
setsid sh "$WATCHDOG_SCRIPT" &
```

**Why it's bad**: BusyBox shell 解析 heredoc 含 `\$(...)` 时会触发某种行尾解析卡死，整个 `/etc/init.d/mahjong-mitm start` 永不返回（已实测）。

**Instead**: watchdog 作为独立可执行文件 `/usr/lib/mahjong-mitm/watchdog.sh` 由 ipk 安装，`build_ipk.py` 负责 chmod +x 打包。init.d 只 `setsid sh watchdog.sh "$tls_port"`。

### Common Mistake: 用 fallback static 应对 origin fetch 失败

**Symptom**: 第一次试热更没报错但手机只下了一两个文件就停了；之后再连 WiFi MITM 收不到任何请求。

**Cause**: origin fetch 失败时 MITM 回 fallback static (`assets.version_manifest` 内含 `version=9.9.9.103`)。手机的 HotFixManager `_updateLocalManifest` 把这个伪 version 写进 harbor → 下次启动游戏 `versionLessThan(local=9.9.9.103, server=*)` 判定已最新 → 跳过整个热更流程 → MITM 看不到请求。

**Fix**: 修 origin fetch 失败的根因（多数是 idna 编码错或 ssl 证书校验）。

**Prevention**: PC 端 selftest 必须能跑通 `--selftest`；服务启动后用 `curl -k --resolve gxb-oss.hzxuanming.com:443:192.168.6.1 https://gxb-oss.hzxuanming.com/hotfix_update?env=1&appid=1073&version=1.0.0.50` 自测，期望 200 + 真实 manifest_url（非伪 99.99.99.9999）。

### Gotcha: Android Private DNS 三层绕过

> **Warning**: 普通 OpenWrt `redirect to :5353` 只拦 UDP/TCP 53。Android 系统级 Private DNS 用 DoT (TCP 853) 或 DoH (HTTPS 443 到 dns.google / cloudflare-dns.com)，三层全在 5353 之外。
>
> 三层都得堵：
> 1. UDP/TCP 53 → redirect to :5353（命中普通 DNS + 硬编码 8.8.8.8 之类）
> 2. TCP/UDP 853 → reject with tcp reset（强迫 Private DNS 回退 UDP 53）
> 3. 公共 DoH IP:443 → reject（堵 dns.google / 1.1.1.1 / 9.9.9.9 / 223.5.5.5 等）
> 4. IPv6 :53/:853 → reject（堵手机走 IPv6 优先）

### Gotcha: 手机 DNS 缓存绕过 DNS 劫持

> **Warning**: Android 默认缓存 DNS 解析 60s ~ 数分钟，部分浏览器/游戏可能更长。如果手机在 MITM 部署之前已经查过 gxb-* 域名，会缓存真实 CDN IP（121.40.x.x / 43.180.x.x / 220.185.x.x 等），下次直接用 IP 连接**跳过 DNS 查询**，5353 拦不到。
>
> 解决：`apply_gxb_dnat` 在服务启动时通过 `resolve-gxb.sh` 主动解析 6 个 gxb-* 域名，把它们解析到的所有真实 IP 加进 `mahjong_mitm_dns` 链的 DNAT 规则（任何 LAN → 真实 IP:443 → 192.168.6.1:443）。游戏 `VERIFYPEER=0` 不校验证书，TLS 握手照样成功，SNI 头告诉我们目标域名。

---

## 重启自启验证 checklist

执行 `reboot` 后等 30~60s 路由器回来，全部应该自动恢复：

- [ ] `ls /etc/rc.d/ | grep mahjong` → 期望 `S95mahjong-mitm` 存在（procd auto-start）
- [ ] `ps w | grep python3 | grep mahjong | grep -v grep` → 1 个进程
- [ ] `ps w | grep watchdog.sh | grep -v grep` → 1 个 watchdog
- [ ] `netstat -tlnp 2>/dev/null | grep -E ':(443|5353)\s'` → 443 + 5353 都 listen
- [ ] `wget --no-check-certificate -q -O- https://127.0.0.1:443/healthz` → `{"status":"ok"}`
- [ ] `nft list chain inet fw4 mahjong_mitm_dns` → DNS redirect + DNAT rules 都在
- [ ] `nft list chain inet fw4 mahjong_mitm_dns | grep mahjong-gxb-dnat` → gxb DNAT 规则存在（29+ CDN IPs）
- [ ] `nft list chain inet fw4 mahjong_mitm_block_doh` → DoT/DoH/IPv6 reject 都在
- [ ] `cat /tmp/mahjong-gxb-resolve.log` → 6 个域名解析成功，IPs 非空
- [ ] `ls /etc/mahjong-mitm/` → mitm_cert.pem + mitm_key.pem 存在（postinst 持久化）

任何一项 fail → 看 `logread | grep mahjong-mitm | tail -30`。
