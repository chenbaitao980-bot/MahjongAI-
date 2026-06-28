# brainstorm: 账户权限管理

## Goal

为 noconfig web 管理系统 (`http://8.136.32.137:8002/admin`) 增加多级账户权限管理。
当前：一个管理员账户可以看到所有手机用户的手牌。
目标：管理员可创建多个"登录账户"，每个登录账户只能看到被授权的手机用户。

## What I already know

**系统架构：**
- FastAPI web 应用，运行在 ECS:8002
- 当前代码在 `remote/noconfig/app.py`（16个端点）+ `remote/noconfig/user_store.py`
- 手牌展示：`remote/relay/static/index.html`（JS 轮询 `/state`）
- 用户数据全在内存中（UserStore 单例），重启丢失

**"用户"含义：**
- **手机玩家**（User）= 连热点的手机，由 `numid` 标识
- **登录账户**（Login Account）= 登录 `/admin` 的账号

**现有认证：**
- POST `/admin/login` → HMAC cookie（`mj_admin_auth`）
- 所有数据端点用共享 `api_token`

## Requirements

- [x] 管理员可查看所有手机用户的手牌（现有功能保留）
- [x] 管理员可添加/编辑/删除登录账户
- [x] 每个登录账户有自己的用户名和密码
- [x] 编辑登录账户时管理员可勾选该账户能看到哪些手机用户
- [x] 登录账户使用独立登录入口（与管理员共用登录页）
- [x] 登录账户登录后只能看到被授权的手机用户
- [x] 登录账户看不到账户管理功能

## Decisions (ADR-lite)

### D1: 持久化方式 — JSON 文件
存储为 `data/noconfig/accounts.json`
**理由**：简单、无额外依赖、易手动编辑和备份。

### D2: UI 布局 — 顶部标签页
管理员见两个 tab："👤 用户查看" + "🔑 账户管理"
登录账户只见"用户查看"
**理由**：不改变现有流程，操作直观。

### D3: 密码存储 — SHA-256 + 随机盐
**理由**：安全、纯 Python 实现、无额外依赖。

## Acceptance Criteria

- [ ] 管理员登录后能看到"账户管理"tab
- [ ] 管理员可创建一个登录账户，只分配 1 个手机用户
- [ ] 用该登录账户登录，只能看到那 1 个手机用户
- [ ] 用该登录账户登录，看不到账户管理 tab
- [ ] 重启服务后账户数据不丢失
- [ ] 管理员删除手机用户时，从相关登录账户的 allowed_user_ids 中自动移除

## Definition of Done

- [ ] 代码在 ECS 上部署并验证通过
- [ ] 配置文件和账户数据兼容现有部署

## Out of Scope

- 登录账户分角色/权限组
- 每个登录账户独立 API token
- 登录审计日志
- 密码过期/强度策略
- 登录失败锁定

## 实施方案

### 新增文件
- `remote/noconfig/account_store.py` — AccountStore 单例

### 修改文件
- `remote/noconfig/app.py` — 新增端点 + 登录逻辑 + Admin 页面

### 文件结构
```
remote/noconfig/
├── account_store.py  ★ 新增
├── app.py            ★ 修改
├── user_store.py     (不改)
├── main.py           (不改)
```

### 新增 API
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/accounts?token=` | 获取所有登录账户 |
| POST | `/api/accounts?token=` | 创建登录账户 |
| PUT | `/api/accounts/{id}?token=` | 编辑登录账户 |
| DELETE | `/api/accounts/{id}?token=` | 删除登录账户 |

### Cookie 变更
`mj_admin_auth` payload 从 `username|expires_at|hmac` 
改为 `username|role|expires_at|hmac` (role = `admin` / `account`)

### 登录流程
1. POST `/admin/login` 先匹配 config 中的管理员
2. 不匹配则查 accounts.json 中的登录账户
3. Cookie 记录 role 区分身份
4. `/admin` 页面根据 role: admin → 全部功能, account → 只看授权用户

### 边界处理
- 删除手机用户 → 自动清理各账户的 allowed_user_ids
- JSON 文件写操作加线程锁
- 文件损坏时自动初始化空数据
