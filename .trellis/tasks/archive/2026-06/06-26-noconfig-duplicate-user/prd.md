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

## Requirements

- [x] 同一玩家重新登录后，管理页面只显示一个用户条目
- [x] 新登录应更新原有用户数据，而非创建新用户

## Acceptance Criteria

- [x] 同一账号退出后 10 分钟内重新登录，admin 页面用户列表仍只显示 1 个用户
- [x] 用户的手牌数据、凭证、房间信息正确关联到同一用户

## Deployment

- [x] 代码已部署到 ECS (8.136.32.137)
- [x] 服务已重启，用户列表已清空
- [x] 免密 SSH 已配置，全局技能已更新

## Technical Approach

**方案 A：user_id 改 numid（已实施）**

将 `user_id` 来源从易变的 `sessionid.hex()` 改为稳定的 `str(numid)`。`sessionid` 作为独立的 `srs_sessionid` 字段保存到 User 对象（spectator 启动需要）。

### 修改文件

| 文件 | 改动 |
|------|------|
| `tcp_proxy.py` LobbyS2CRewriter | `_user_id = str(numid)`，`_sessionid = sid.hex()`，传播给 lobby_tap + game_proxy_manager |
| `tcp_proxy.py` DynamicGameProxyManager | 加 `_sessionid`，`set_user_id(user_id, sessionid)` 传播给所有 tap |
| `tcp_proxy.py` GameTapDecoder | 加 `_sessionid`，`_push_to_relay` body 加 `srs_sessionid` |
| `tcp_proxy.py` build_game_proxy | tap.set_user_id 传 sessionid |
| `ecs_proxy.py` presence reporter | `user_id = str(numid)`，POST 加 `srs_sessionid` |
| `app.py` PushRequest | 加 `srs_sessionid: str = ""` |
| `app.py` PresenceRequest | 加 `srs_sessionid: str = ""` |
| `app.py` /push 端点 | `_auto_fill_credentials(fallback_srs_sid=req.srs_sessionid)` |
| `app.py` /presence 端点 | `_auto_fill_credentials(fallback_srs_sid=req.srs_sessionid)` |

### 数据流（修复后）

```
大厅代理 PlayerData → parse_player_data → numid(=user_id) + sessionid(=srs_sessionid)
  → LobbyS2CRewriter._user_id = str(numid)
  → 传播给 game tap
  → presence reporter POST /presence {user_id=numid, srs_sessionid=sessionid.hex}
  → GameTapDecoder._push_to_relay POST /push {user_id=numid, srs_sessionid=sessionid.hex}
  → app.py /presence & /push → UserStore.add_user(user_id=numid) → 同一 numid = 同一用户
```
