# noconfig 重复用户排查

## Goal

排查并修复 noconfig 模式下，**同一个玩家重新登录后，管理页面出现多个重复用户**的问题。

## What I already know

- noconfig 模式使用 `UserStore` 管理多用户，以 `user_id` 为键
- `user_id` 当前来源于 **srs_sessionid 的 hex 字符串**（16 bytes → 32 字符 hex）
- 每次重新登录，游戏服务器会下发**全新的 srs_sessionid**（16 字节随机值）
- `ONLINE_TTL_SECONDS = 600`（10 分钟），旧用户在 10 分钟内不会过期
- 因此：同玩家第一次登录 → user_id="sessA_hex"；退出重登 → user_id="sessB_hex"；列表里同时存在两个用户
- `PlayerData` 解析结果中包含 `numid`（稳定的玩家数字ID，如 1084306678），每次登录不变
- `configure()` 预填了一个 `default` 用户（单用户兼容），使问题更加 confusing

## Root Cause（已确认）

**user_id 使用了每次登录变化的 `sessionid.hex()`，而非稳定的 `numid`。**

### 代码链路

1. `ecs_proxy.py:make_presence_reporter()` — presence 上报 user_id = `sid.hex()`
2. `tcp_proxy.py:LobbyS2CRewriter.__init__` — `_user_id = sid.hex()`，传播给 game tap
3. `tcp_proxy.py:GameStateTap._push_to_relay()` — push 时 user_id = `self._user_id`

sessionid 每次 Handshake 重新生成 → 每次登录都是新 user_id → UserStore 创建新用户 → 旧用户 10 分钟后才过期 → **列表重复**。

## Assumptions (temporary)

- `numid` 在同一个游戏账号下是全局唯一且稳定的
- 同一个 ECS 代理不会同时服务同一个 numid 的多个登录实例

## Open Questions

- **修复方案**：将 user_id 从 sessionid.hex 改为 numid，还是添加去重/合并逻辑？
- `default` 预填用户是否保留？（单用户兼容 vs 多用户模式的冲突）

## Requirements (evolving)

- [ ] 同一玩家重新登录后，管理页面只显示一个用户条目
- [ ] 新登录应更新原有用户数据，而非创建新用户

## Acceptance Criteria

- [ ] 同一账号退出后 10 分钟内重新登录，admin 页面用户列表仍只显示 1 个用户
- [ ] 用户的手牌数据、凭证、房间信息正确关联到同一用户

## Definition of Done

- 代码修复 + 测试验证
- 日志记录确认 user_id 稳定

## Out of Scope

- 多设备同时登录同一账号的场景（已在 GameClient 约束中排除）
- UserStore 持久化到磁盘（当前仍走内存）

## Technical Notes

### 涉及文件
- `remote/noconfig/hijack/ecs_proxy.py` — presence reporter user_id 来源
- `remote/noconfig/hijack/tcp_proxy.py` — LobbyS2CRewriter._user_id、GameStateTap._user_id
- `remote/noconfig/app.py` — configure() default 用户预填
- `remote/noconfig/user_store.py` — UserStore.add_user 去重逻辑

### PlayerData 结构（handshake.py:parse_player_data）
```
flag(1B) + areaid(4B) + numid(4B) + nick_len(1B) + nickname + url_len(1B) + protecturl + msg + sessionid(16B)
```
- `numid`: int32，稳定账号标识
- `sessionid`: bytes(16)，每次登录随机生成
- `nickname`: str，玩家昵称
