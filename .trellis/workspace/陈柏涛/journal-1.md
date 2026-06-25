# Journal - 陈柏涛 (Part 1)

> AI development session journal
> Started: 2026-06-09

---



## Session 1: Remote game data access: extractor + relay implementation

**Date**: 2026-06-10
**Task**: Remote game data access: extractor + relay implementation
**Branch**: `master`

### Summary

Implemented dual-mode remote game data access system. extractor/ (Python 3.6-compatible) runs on Windows (Npcap) or OpenWRT soft router (tcpdump), auto-extracts binary auth tokens from game traffic and pushes live snapshots to cloud relay. relay/ is a FastAPI service with /register /push /state endpoints; falls back to active GameClient mode (scenario B) when extractor is offline for 60+ seconds. Added test_remote.py for one-click local testing (13 tests, 3 suites: StateStore/TokenExtractor unit + Relay API integration via subprocess). Documented game wire protocol and remote access architecture in .trellis/spec.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `f222577` | (see git log) |
| `5777553` | (see git log) |
| `2051279` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 2: 远程读牌可行性调查 + 抓包诊断/握手修复

**Date**: 2026-06-11
**Task**: 远程读牌可行性调查 + 抓包诊断/握手修复
**Branch**: `master`

### Summary

调查'手机不连热点也能远程读牌'是否可行。结论：不可行——实时数据只在手机和游戏服务器两处，远程要读必须让流量经过可控点(改手机路由/本地抓包)。反编译游戏客户端(Cocos2d-x Lua, XXTEA已全解)证实场景B(relay自连服务器)死于native加密的SRS认证(per-session key服务端下发+存native+腾讯反作弊)，game_client.py为死代码。顺带:修复token_extractor握手选包bug(取0x000F后的0x0001)，给relay/extractor加文件日志+双向取证日志，确认游戏数据帧0x2BC0为明文。APK逆向产物移至项目根apk_research/(gitignore)。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `7a02300` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 3: 三模式E2E测试：热点+VPN验证通过，relay自动token redirect

**Date**: 2026-06-13
**Task**: 三模式E2E测试：热点+VPN验证通过，relay自动token redirect
**Branch**: `master`

### Summary

完成热点模式和VPN模式真机E2E测试。修复relay首页自动token redirect(core.py)、bat自动打开ECS网页、VPN extractor部署路径(/opt/mahjong-extractor)和tcpdump接口(any非ipsec0)三个关键坑。沉淀spec：core.py是路由实体不是app.py。无配置模式待下一任务研究。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `e02e23b` | (see git log) |
| `ea3149d` | (see git log) |
| `8ca0d87` | (see git log) |
| `39cf2bc` | (see git log) |
| `9ea6947` | (see git log) |
| `8b71043` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 4: SRS 保活误判排除 + 自动重连实现

**Date**: 2026-06-13
**Task**: SRS 保活误判排除 + 自动重连实现
**Branch**: `master`

### Summary

证伪 msgid=3 心跳假设（它是握手步骤，发了立即被踢）；实测服务端 idle timeout=120s；srs_sessionid 跨连接复用 4h+ 有效；实现 on_disconnect→2s→reconnect 自动重连替代心跳；修复 SRSSessionExtractor _session_key 不重置 bug；更新 remote-access spec。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `e82f123` | (see git log) |
| `009247f` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 5: PC 热点 RST 注入全自动双连

**Date**: 2026-06-14
**Task**: PC 热点 RST 注入全自动双连
**Branch**: `master`

### Summary

复现朋友软路由效果：Npcap 捕捉手机→游服 TCP 四元组（phone_ip/port/seq），Scapy 发送伪造 RST 触发游服 grace period，ECS cloud_player continuous 模式在窗口内连入建立持久双连；/api/creds 改为自动启动 player，无需手动操作

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `4c19c2a` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 6: 防火墙封锁手机重连 — 为 ECS 双连让路

**Date**: 2026-06-14
**Task**: 防火墙封锁手机重连 — 为 ECS 双连让路
**Branch**: `master`

### Summary

发现 ECS flag=0 后 1s 被踢根因：手机 TCP 立刻重连与 ECS 争 session 槽。方案：RST 注入前先加 Windows 防火墙出站规则封锁 phone→47.96.0.227:7777，5s 后解封。check 修复关键 bug：localip=phone_ip 在热点 NAT 场景无效，改为只匹配 remoteip/remoteport。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `2883e6f` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 7: 修bug：前端白板/红中显示颠倒

**Date**: 2026-06-16
**Task**: 修bug：前端白板/红中显示颠倒
**Branch**: `master`

### Summary

remote/relay/static/index.html 的 JavaScript HONOR 映射 5 和 7 的值写反了，白板(7z)显示为'中'，红中(5z)显示为'白'。一字符修复，已部署到 ECS。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `442c899` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 8: noconfig 本地 MITM 打包成 Windows 托盘 exe

**Date**: 2026-06-23
**Task**: noconfig 本地 MITM 打包成 Windows 托盘 exe
**Branch**: `master`

### Summary

把 noconfig setup-period MITM 做成任意 Win10/11 x64 复制即用的托盘 exe，复用 mahjong_mitm 内核。新增 windows/(win_dns_divert 收回 WinDivert + win_hotspot WinRT 热点常开 + win_admin UAC自提权/自启 + tray_app pystray 编排 + core 共用入口 + config ECS写死8.136.37.136+sidecar) 与 winpack/(PyInstaller spec uac_admin+WinDivert+内嵌APK + 纯ASCII build_win.bat)。真机修复两暗坑：winsdk b10 IAsyncOperation 须包协程再 asyncio.run；热点网关192.168.137.1在StartTethering成功后约4s才可绑须轮询等就绪。托盘常驻+热点常开(PeerlessTimeoutEnabled=0)+来一台手机注一台(幂等)。测试12/12，手机注入真机验证通过。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `3a6aba8` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 9: 迁移 noconfig 服务到华纳云 HK 8.136.32.137

**Date**: 2026-06-25
**Task**: 迁移 noconfig 服务到华纳云 HK 8.136.32.137
**Branch**: `master`

### Summary

bootstrap 三件套到新服务器 8.136.32.137（私网 172.20.133.250），CN2 验收通过；更新 interface ECS IP 常量并重编译 Windows exe + OpenWrt IPK

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `40cdfc3` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 10: noconfig 迁移华纳云 HK + 443 冲突排查

**Date**: 2026-06-25
**Task**: noconfig 迁移华纳云 HK + 443 冲突排查
**Branch**: `master`

### Summary

ECS 从阿里云旧服迁移到华纳云 HK（8.136.32.137），三服务全部部署到位；排查出旧 python.exe 残留进程抢占 443 导致热更写入旧 NetConf、手机始终连旧服的根因；发现需要在 Windows exe 和 OpenWrt ipk 启动时自动清理 443 端口冲突。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `40cdfc3` | (see git log) |
| `bdec012` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
