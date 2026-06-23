# 新服务器部署 + 账号分片（含迁移）

## Goal

将 noconfig 核心链路部署到新服务器（**华纳云 HK CN2 GIA**，不实名），
并实现**账号永久绑定服务器**的分片机制，消除多账号共享单 IP 的封号风险。
阿里云 ECS 保留不动，双跑并行验证，验证通过后账号按分片规则重新指向新机器。

> **2026-06-22 转向决定**：Vultr Tokyo（`64.176.56.70`）已验证**不可用**，转华纳云 HK。
> 原因见下「Vultr 失败记录」。bootstrap 脚本通用，换机只是 `bootstrap_new_server.py <新IP>` 一条命令。

## What I already know

### 迁移范围（核心三件套）

| 服务 | 端口 | 文件 |
|------|------|------|
| mahjong-relay-noconfig | 8002 | `remote/noconfig/main.py` |
| mahjong-tcp-proxy | 5748/5749/7777 | `remote/noconfig/hijack/tcp_proxy.py` |
| mahjong-mitm-hotupdate | 53/443 | DNS divert + manifest forge |

**不迁移**：`mahjong-extractor`、`mahjong-cloud-player`（当前不用）

### 服务器信息

| | 阿里云（保留，不动） | ~~Vultr Tokyo~~（已弃用） | 华纳云 HK（新目标） |
|--|--|--|--|
| IP | `8.136.37.136` | ~~`64.176.56.70`~~ | 待用户提供 |
| 状态 | 继续跑，完全不碰 | ❌ 部署成功但 IP 被自家 DDoS 防护黑洞，弃用 | 本任务部署目标 |
| SSH | 密码登录 | — | 密码登录 |

### Vultr 失败记录（2026-06-22，traceroute 实证根因）

部署本身**全部成功**：三件套 active、relay 8002 多次返 200、手机热更成功烤成 Vultr、DNS 劫持公网验证生效。

**真正根因 = 无 CN2，路由到不了国内真服**（不是 DDoS）：
tcp_proxy 日志 `upstream connect failed 47.96.101.155:5748 → [Errno 110] timed out` 反复刷。
从 Vultr 测：连我们**自己那台端口全开、零封锁的阿里云 ECS 8.136.37.136 都超时**，游服/大厅 47.96.x 全超时。
traceroute 定位死亡点：`东京→大阪→洛杉矶(美国!)→中国电信 202.97 国际出口→hop10+ 全 * 丢包，死在中国边界`。
即 **Vultr 标准国际线路到大陆直连 IP 不通** → 大厅代理回连真服失败 → 手机大厅加载不出来。

**次要/红鲱鱼**：后续运维狂探测触发 Vultr 自家 DDoS 防护短暂 null-route（8002/SSH 临时 0/8），
当时误判为主因，实为次要。手机大厅断线后 SRS 每 2s 自动重连的短连接风暴会加剧此防护误判（仍值得沉淀进 R4）。

**结论**：境外机做读牌代理**必须能回连国内真服**——标准国际线路（经 202.97）做不到；
**必须 CN2 GIA（AS4809）**。死亡点 202.97 正是电信普通国际出口，CN2 GIA 专门绕开它，华纳云 HK 正是为此。

### ⚠️ 华纳云 HK 验收前置（铁律）

部署 HK 后**第一步不是测手机，而是先在 HK 机上 `python3 -c "import socket;socket.create_connection(('47.96.0.227',7777),8)"`**——
HK→47.96.0.227:7777 + 47.96.101.155:5748 通了，才证明 CN2 路由能回连真服，才值得往下走手机热更；不通直接换机，不浪费后续。

### 硬编码 IP 需更新的文件

- `remote/noconfig/hijack/ecs_run.py` — `DEFAULT_ECS_IP`
- `scripts/deploy_ecs_proxy.py` / `diag_ecs.py` / `ecs_deploy_paramiko.py` — `--ecs-host` 默认值
- `scripts/restart_*.py` — 多处 hardcode
- `remote/noconfig/hijack/setup_mitm.py` — `--ecs-ip` 默认值

### 部署约束

- 远端目录：`/opt/mahjong-remote/`
- 本地脚本用 paramiko SSH + 密码弹窗
- systemd 管理服务，service 文件参考 `remote/extractor/files/mahjong-extractor.service`

## Decision

**双跑并行**：新旧两台同时跑，新账号指新服务器验证，旧账号继续用阿里云。
**SSH**：密码登录，沿用现有 paramiko 弹窗脚本。
**迁移范围**：仅核心三件套。
**账号分片**：hash 绑定，账号永久固定服务器，不做请求级轮询。

### 扩容架构

```
账号池（N个用户）
  ↓ sha256(userId) % 服务器数 → shard_map.yaml
服务器1（华纳云HK）   服务器2（Vultr SG）   服务器N（...）
  账号A/B/C             账号D/E/F             账号G/H
  relay:8002            relay:8002            relay:8002
  tcp_proxy             tcp_proxy             tcp_proxy
  mitm-hotupdate        mitm-hotupdate        mitm-hotupdate
```

**运营阈值**：每台 ≤4 个账号；超过则 bootstrap 新台 + rebalance。

## Requirements

### R1 — 通用 bootstrap 脚本（任意新服务器一键部署）
- 新建 `scripts/bootstrap_new_server.py <IP> [--password <pwd>]`
- 步骤：SSH 连 `root@<IP>` → apt 安装 python3/pip/npcap依赖 → rsync 推 `/opt/mahjong-remote/` → 写三个 systemd service 文件 → daemon-reload + start → 验证 active
- IP 纯参数，不硬编码；将来加第三台直接 `bootstrap_new_server.py <新IP>`

### R2 — NetConf patch 支持 ECS IP Pool（来自 06-19 C2）
- `netconf_patch.py` 新增 `--ecs-ip-pool ip1,ip2` + `--shard-key <userId>`
- 内部：`shard_index = sha256(shard_key) % len(pool)`，选中对应 IP 注入 NetConf
- 单 IP 时退化为现有行为（向后兼容）

### R3 — 账号→服务器映射工具 shard_assign.py（来自 06-19 C3）
- 新建 `remote/noconfig/hijack/shard_assign.py`（纯函数库 + CLI）
- 维护 `data/noconfig/shard_map.yaml`（userId/phone → ecs_ip）
- 支持：查询绑定、新增绑定、手动 override、rebalance（重新计算全部分配）
- `setup_mitm.py` 调用时自动查 shard_map，无需每次手传 IP

### R4 — 沉淀风险评估为 spec（来自 06-19 C4）
- 新文档 `.trellis/spec/guides/noconfig-anti-ban.md`
- 内容：R1-R9 风险地图、出口方案决策树、多服务器运营 SOP、香港节点适用场景

### R6 — 部署脚本 IP 参数化
- `deploy_ecs_proxy.py` / `diag_ecs.py` / `restart_*.py` 的 `--ecs-host` 默认值改为新服务器 IP
- 旧 IP 可通过 `--ecs-host root@8.136.37.136` 显式指定（向后兼容）
- `ecs_run.py` `DEFAULT_ECS_IP` 改为新 IP，`ECS_IP` env var 保留

### R7 — 验证
- 至少一个账号在新服务器完整走通：热更下载 → 进大厅 → 建房 → 看牌显示
- 旧阿里云 ECS 上的账号不受影响

## Acceptance Criteria

- [ ] `bootstrap_new_server.py <IP>` 执行后三个服务全部 systemctl active
- [ ] `shard_assign.py add <userId> <IP>` 写入 shard_map.yaml
- [ ] `shard_assign.py query <userId>` 返回绑定 IP
- [ ] `netconf_patch.py --ecs-ip-pool a.b,x.y --shard-key u123` 注入分片选中的 IP
- [ ] 单 IP 模式（不传 pool）向后兼容，现有调用无须改
- [ ] `deploy_ecs_proxy.py`（不带参数）默认推到新服务器
- [ ] `ecs_run.py` DEFAULT_ECS_IP = 新服务器 IP
- [ ] 至少一个账号在新服务器完整看牌验证通过
- [ ] 旧阿里云 ECS 服务未受影响

## Definition of Done

- 新服务器真实账号走通热更→展示手牌全流程
- `shard_map.yaml` 有至少一条真实账号绑定记录
- 所有 `--ecs-host` 默认值 + `DEFAULT_ECS_IP` commit 更新
- `pytest tests/` 通过（含 shard_assign 单测）

## Out of Scope

- 阿里云 ECS 下线（保留不动）
- 金币场退出 ECS（用户金币场→好友房会造成 IP 跳变，比一直走 ECS 更可疑，保持现状）
- extractor / cloud-player 迁移
- VPN 模式迁移
- 主备健康检查 / 故障切换
- iptables DNAT TCP 指纹漂白（低优先级，待出现风控反馈再做）
- Frida 坐实 R9 NetConf md5 上报（触发条件=出现封号反馈）

## Implementation Plan

- **PR1**（bootstrap）: `scripts/bootstrap_new_server.py` — 通用一键部署三件套
- **PR2**（分片）: `shard_assign.py` + `netconf_patch.py --ecs-ip-pool`
- **PR3**（IP 参数化）: `ecs_run.py` DEFAULT_ECS_IP + 所有脚本 `--ecs-host` 默认值
- **PR4**（spec）: `noconfig-anti-ban.md` 风险地图 + 运营 SOP
- **PR5**（验证）: 手机端走通，记录 checklist

## Technical Notes

- 旧 ECS IP：`8.136.37.136`（阿里云杭州，保留）
- ~~Vultr Tokyo `64.176.56.70`~~：已弃用（自家 DDoS 防护黑洞 IP，见上「Vultr 失败记录」）
- 新服务器 IP：**华纳云 HK，待用户提供**（CN2 GIA，本任务部署目标）
- 硬编码文件清单：`ecs_run.py`, `deploy_ecs_proxy.py`, `diag_ecs.py`, `ecs_deploy_paramiko.py`, `restart_*.py`, `setup_mitm.py`
- systemd service 文件样本：`remote/extractor/files/mahjong-extractor.service`
- 06-19 PRD 相关条款：C2（ECS pool）+ C3（shard_assign）已合并入本任务；C1/C4/C5/C6 仍在 06-19
