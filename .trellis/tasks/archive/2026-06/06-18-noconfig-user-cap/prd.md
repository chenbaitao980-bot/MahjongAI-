> ⚠️ **SUPERSEDED BY [06-19-anti-detection-unified](../../../06-19-anti-detection-unified/prd.md)** — 2026-06-19 合并到统一反检测任务，本文件保留作历史底料。

# noconfig admin 用户上限限流（max_active_users ≤ 10）

## Goal

在 noconfig admin（`:8002`）上加 `max_active_users` 配置项，超出阈值时新用户注册返回 503 + UI 提示"系统已满员"——主动停在 ECS 同城掩护的"装死窗口"内（< 15% 被打概率）。

## Context

来自 [research/idc-ip-multi-account-risk.md](../archive/2026-06/06-17-ecs-detection-risk/research/idc-ip-multi-account-risk.md) §6 的实证基线：

| 用户量 | 1 个月被打概率 |
|---|---|
| ≤ 10 | < 15% |
| 10-50 | 30-50% |
| > 50 | **70%+** |

边锋系是 20 年棋牌运营商，"同 IP 多账号"是行业级风控标的。**最便宜的反检测就是主动不超 10**。

## Requirements

- **R1** [`remote/relay/config_noconfig.yaml`](../../../remote/relay/config_noconfig.yaml) 加 `max_active_users: 10` 配置项
- **R2** [`remote/noconfig/app.py`](../../../remote/noconfig/app.py) `POST /register` 路径：先查当前 active 用户数（含已存在但未过期的）→ ≥ max_active_users 返回 HTTP 503 + 中文 detail "系统已满员，请稍后再试"
- **R3** admin UI（[`remote/relay/static/`](../../../remote/relay/static/) 下相关页面）：
  - 顶部显示 "X / 10 用户在线"
  - 接近阈值时（≥ 8）字体变橙
  - 满员时变红
- **R4** "active" 定义：以 `presence` 表的 `last_seen` 为准（默认在线 TTL = 600s，与 [[noconfig-multiuser-deployed]] 一致）
- **R5** Admin 路径**不受限**：admin 自己仍可创建用户（绕过限流，用于运维调试）；只对外部 `/register` 调用生效

## Acceptance Criteria

- [ ] 创建第 11 个 active 用户时 `/register` 返回 503，detail 中文提示
- [ ] 用户掉线 600s+ 后槽位释放，可再注册
- [ ] admin UI 顶部显示当前用量
- [ ] 配置改成 5 → reload → 立即生效（无需重启服务）
- [ ] 单元测试覆盖：边界 9/10/11 三种状态

## Definition of Done

- 配置项注释清楚指明"反检测限流；改前先看 .trellis/spec/backend/remote-access.md §17"
- 部署遵守 [[server-readonly-git-sync-discipline]]

## Out of Scope

- 不实施"按 IP 段分流"（多 IP 池是独立任务）
- 不在此任务里搞队列 / 等位机制（满员就直接拒绝，简单粗暴）
- 不影响 `:8000` 热点 / `:8001` VPN 模式（只针对 noconfig）

## Technical Approach

1. **配置层**：[`remote/relay/config_noconfig.yaml`](../../../remote/relay/config_noconfig.yaml) 加字段，[`remote/noconfig/app.py`](../../../remote/noconfig/app.py) `configure()` 注入
2. **状态层**：[`remote/noconfig/user_store.py`](../../../remote/noconfig/user_store.py)（如已存在）加 `count_active(ttl=600)` 方法；否则在 `app.py` 内做
3. **API 层**：`/register` POST 加预检
4. **UI 层**：admin 页面加 active 计数 chip
5. **绕过开关**：admin 路径用单独 endpoint（如 `/admin/register`）走免限流逻辑

## Technical Notes

关键文件：
- [`remote/noconfig/app.py`](../../../remote/noconfig/app.py) — `/register` 入口
- [`remote/noconfig/user_store.py`](../../../remote/noconfig/user_store.py)（如存在）— 用户存储
- [`remote/relay/config_noconfig.yaml`](../../../remote/relay/config_noconfig.yaml) — 配置
- [`remote/relay/static/`](../../../remote/relay/static/) — admin UI

关联记忆：[[noconfig-multiuser-deployed]] [[server-readonly-git-sync-discipline]]

研究依据：[../archive/2026-06/06-17-ecs-detection-risk/research/idc-ip-multi-account-risk.md](../archive/2026-06/06-17-ecs-detection-risk/research/idc-ip-multi-account-risk.md) §6
