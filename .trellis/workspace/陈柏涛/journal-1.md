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
