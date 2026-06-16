# 多用户场景：无配置模式支持多用户管理与手牌展示

## Goal

将当前无配置模式（noconfig）从单用户扩展为多用户场景，支持：
1. 多用户同时使用
2. 后台管理页面配置多个用户，支持按用户名搜索
3. 选中用户后展示该用户当前手牌

## What I already know

### 当前架构

**Noconfig 模式**是四种远程读牌模式之一（端口 8002），利用 SRS 旁观协议直连游戏服务器，手机无需任何配置。

**关键发现：**
- `remote/noconfig/user_store.py` **已经实现了完整的多用户数据模型**（`User` 类 + `UserStore` 单例），包含：
  - 用户 CRUD（add/remove/get/search）
  - 每个用户独立的 `StateStore` 和 spectator 进程
  - 按名称搜索用户（`search_users`）
  - 在线状态判断
- 但 `remote/noconfig/app.py` **仍然是单用户实现**，直接使用全局 `_state_store`，没有使用 `UserStore`
- 现有手牌展示 UI 在 `remote/relay/static/index.html`，也是单用户的

### 需要做的改动

1. **改造 `app.py`**：将单用户端点改为多用户，使用 `UserStore` 管理多个用户
2. **新增 `/admin` 页面**：用户列表 + 搜索 + 选中展示手牌
3. **改造 `index.html`**：支持通过 `?user_id=` 参数展示指定用户的手牌

## Assumptions (temporary)

* 用户数据通过 `/register` 端点注册（extractor 推送凭证时自动创建用户）
* 后台管理页面是纯 HTML/CSS/JS（与现有 UI 风格一致）
* 不需要额外的用户认证（已有 `api_token` 鉴权）

## Open Questions

1. **用户标识**：多用户场景下，extractor 推送数据时如何区分不同用户？当前 `/push` 端点没有 `user_id` 参数
2. **用户创建方式**：用户是自动创建（extractor 推送时）还是手动在管理页面添加？
3. ** spectator 进程**：每个用户是否需要独立的 spectator 进程？还是共享一个？

## Requirements (evolving)

* 支持多用户场景
* 后台管理页面可配置/查看多个用户
* 支持按用户名搜索用户
* 选中用户后展示该用户手牌

## Acceptance Criteria (evolving)

* [ ] 多用户配置功能可用
* [ ] 用户搜索功能可用
* [ ] 选中用户后正确展示手牌
* [ ] 向后兼容单用户模式

## Definition of Done

* Tests added/updated (unit/integration where appropriate)
* Lint / typecheck / CI green
* Docs/notes updated if behavior changes
* Rollout/rollback considered if risky

## Out of Scope (explicit)

* TBD

## Technical Notes

- `remote/noconfig/user_store.py` — 已有多用户数据模型
- `remote/noconfig/app.py` — 当前单用户 FastAPI 端点
- `remote/relay/static/index.html` — 当前单用户手牌展示 UI
