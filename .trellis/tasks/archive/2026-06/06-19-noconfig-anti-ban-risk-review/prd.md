# noconfig 模式封号风险评估与技术优化

## Goal

全面评估 noconfig 模式的**封号风险**(被服务运营方误判为工作室/外挂),给出可落地的技术方案
优化把高风险维度降下来。MVP=报告+网络层止血。

**关键约束**:
- 同时在线最多 10+ 用户(从"个位数"升级,显著提升 R1 紧迫性)
- 用户业务 = "多用户 + 创建房间(房卡场)看牌",**不打金币场**
- ECS 必须保留(任意网络远程看牌的核心业务)
- 未来购置多台服务器,**含香港**(用户已明确)
- 06-18 软路由任务并行,本任务不依赖其落地

## What I already know

### 当前架构
- 出口 IP 单点:阿里云杭州 ECS `8.136.37.136`,所有账号共享
- 大厅(5748/5749)+ 金币场游服(5067/5167→ECS 5767/5768) 全部经 ECS tcp_proxy 中转
- tcp_proxy 是 Python user-space socket 重建,TCP 指纹由 ECS 出
- 仅旁路解 0x2bc0 推 relay,不改上行字节、不改下行字节内容
- 行为层零外挂指纹(完全旁路,玩家手动出牌)

### 业务背景澄清
- "金币场" = NetConf 里 groupId 5067/5167 的牌局,用游戏内金币对赌(涉钱)
- 用户需求 = 房卡场(走 5045 大厅)创建房间看牌,**不会进入金币场**
- 当前金币场中转是早期防御性设计,**对用户业务零价值**

### 风险地图(R1–R9)

| # | 维度 | 当前状态 | 严重度 | 治理路径 |
|---|---|---|---|---|
| **R1** | 同 IP 多账号 | ECS 单点,10+ 账号同 IP | 🔴 CRITICAL | 多 ECS 出口 + 账号分片 |
| **R2** | 数据中心 IP 段 | 阿里云杭州 IDC | 🔴 HIGH | 跨云厂分散 ASN(本任务接受 R2 作为残余风险,见 ADR) |
| **R3** | 地理跳变 | 玩家浙江本地 → IDC 杭州 | 🟡 MEDIUM | 多 ECS 选境内同区域优先,香港作为补充节点(见 SOP) |
| **R4** | TCP 指纹漂白 | user-space proxy=Linux server 指纹 | 🟡 MEDIUM | iptables DNAT 透传(C5,P2 文档化) |
| **R5** | 金币场中转 | 5067/5167 经 ECS,涉及钱局 | 🟡 MEDIUM | **删 SRS50_REMAP 对应项**(用户不打金币场,纯收益) |
| **R6** | 登录端口规律 | 5748/5749 固定 | 🟡 LOW | 跟随 R1 自然分散 |
| **R7** | DNS 劫持 | 仅一次性热更期 | 🟢 NONE | 服务端不可观测 |
| **R8** | 行为指纹 | 完全旁路 | 🟢 NONE | - |
| **R9** | NetConf md5 上报 | 客户端是否上报未坐实 | ⚪ 未知 | Frida 抓启动包验证(P2,触发条件=出现封号) |

### 已排除的方案(基于 research/ 调研)

| 方案 | 排除原因 |
|---|---|
| **住宅代理(国际厂商)** | CN 池小+sticky 撑不住游戏长 TCP;国内"住宅代理"实为 IDC/拨号被风控学习;月费 ¥1200-1700,翻 6-10 倍;触及帮信罪/非法控制计算机信息系统罪雷区。**详见 [residential-proxy-mainland.md](research/residential-proxy-mainland.md)** |
| **HK + 住宅代理组合** | 稳定性差、月费翻 4 倍、与 C5 永久冲突。仅在用户量 30+ 且已出现封号反馈才值得。**详见 [hk-vps-plus-residential-proxy.md](research/hk-vps-plus-residential-proxy.md)** |
| **请求级负载均衡** | 单账号 IP 跳变 → R3 恶化,比单 IP 更可疑 |
| **全部换香港(替代杭州)** | R3 地理跳变 + 海外 IP 双标签,综合更糟。香港只能做补充节点 |

## Decision (ADR-lite)

### Context
当前 noconfig 把所有用户流量集中到一个阿里云 IDC IP。10+ 并发情况下,服务端风控引擎只需
一条 SQL 即可锁定"工作室"特征。需要既保留 ECS 中转能力(业务诉求),又分散出口指纹。
用户决定保留多服务器架构(含香港),金币场中转一并删除。

### Decision
1. **多 ECS 跨云厂分片** + 主备兜底,**绝不做请求级负载均衡**
2. **金币场中转(R5)删除** — 用户不打金币场,代码纯收益
3. **香港节点纳入支持但不强推** — 通过 spec/guides/noconfig-anti-ban.md 的运维 SOP
   明确"香港节点适用场景",避免误用

| 形态 | R1 | R3 | 选用 |
|---|---|---|---|
| 请求级 LB(轮询) | 治好 | 单账号 IP 跳变 → 更可疑 | ❌ |
| **账号分片(本方案)** | 治好 | 每账号 IP 永远固定 | ✅ |
| 主备故障切换 | 不治 | 故障时跳一次 | 兜底 |

**核心机制**:NetConf patch 时按 `userId hash mod N` 选一个 ECS IP 写入,该账号永远绑
定该 ECS。新增 ECS 触发一次 hash 重映射(每账号最多迁移一次)。

### 香港节点使用约束(写入运维 SOP)
- ✅ **适合**:账号本身海外/经常出差/有跨地区登录历史
- ❌ **不适合**:浙江实名号 + 历史 IP 全在浙江本地的玩家
- 配置:用户量 < 5 时不上香港;用户量 5-15 时,境内主、香港 1 台备(用于"出差玩家"专属分片);用户量 15+ 再考虑跨境主力

### Consequences
- ✅ R1 显著退化:从"1 IP 挂 10 个账号"变"3-4 IP 各挂 2-3 个账号",低于绝大多数风控阈值
- ✅ R2 跨云厂可治:阿里 + 腾讯/华为(同杭州区域),IP 段不再单一 ASN
- ✅ R5 完全消除(金币场退出 ECS)
- ✅ 账号视角看 IP 永远稳定(R3 不恶化)
- ✅ 代码已支持任何 IP 加入 pool,香港 VPS 可随时纳入(但 SOP 限制使用场景)
- ⚠️ 运营成本:每台 ECS 约 ¥60-100/月,本任务先做"代码支持多 ECS",台数用户后续按需买
- ⚠️ R2 残余:多 ECS 仍是 IDC 段。彻底解决需走 06-18 软路由方案(用户家宽出口),但与本业务"任意网络"冲突
- ⚠️ 故障兜底需后续做(主备健康检查),本任务范围外

## Requirements (final)

### Phase 1 必做(本任务交付)

#### C1 — R5 止血:金币场彻底退出 ECS
- 删除 [`netconf_patch.py`](remote/noconfig/hijack/netconf_patch.py) 的 `SRS50_REMAP` 里 5067/5167 两条
- 同步删除 `tcp_proxy.py` 对 5767/5768 的监听
- 金币场 100% 走真服(用户不打金币场,无业务影响)

#### C2 — NetConf patch 支持 ECS Pool
- `netconf_patch.py` 新增 CLI 参数 `--ecs-ip-pool ip1,ip2,ip3`(逗号分隔)
- 新增 `--shard-key <userid_or_phone>` 用于 hash 分桶
- 内部:`shard_index = sha256(shard_key) % len(pool)`
- 单 IP 时退化为现有行为(向后兼容)
- pool 不区分境内/境外 — 任何 IP 都接受,场景适用性由运维 SOP 控制

#### C3 — 账号→ECS 映射工具
- 新增 `remote/noconfig/hijack/shard_assign.py`(纯函数库 + CLI)
- 维护 `data/noconfig/shard_map.yaml`(userId/phone → ecs_ip),便于人工干预
- 支持人工 override(对"特殊账号"分配指定 ECS,例如"该账号用户在香港")
- 给 setup_mitm 一键产出"该手机专属"的 NetConf

#### C4 — 沉淀风险评估为 spec
- 新文档 `.trellis/spec/guides/noconfig-anti-ban.md`
- 内容:
  - R1–R9 风险地图、各项可观测性与治理路径
  - 出口 IP 不能伪造的原理说明(网络层基础事实,非应用层)
  - 出口方案选型决策树(多 ECS / 香港节点 / 软路由 / 住宅代理 适用条件)
  - 运维 SOP:同时在线上限、何时该加 ECS、香港节点适用场景、新增节点流程
  - P2 触发条件:用户量 30+ / 出现疑似封号反馈
- 引用本 PRD 作为决策来源,引用 research/ 三份调研作为论据

### Phase 2 可选/后续(本任务范围外,留接口)

#### C5 — tcp_proxy 改 iptables DNAT(R4 漂白)
- 大厅 5748/5749 因要改写 RespSRSAddr 字节,**必须保留 user-space**
- 7777 游服可改为 `iptables -t nat -A PREROUTING ... -j DNAT`,旁路用 `tcpdump -i any` 嗅探解 0x2bc0
- 收益不确定:不知道服务端是否真做 TCP 指纹检测;先在 spec 记录,触发条件=出现风控反馈
- ⚠️ **与住宅代理路线永久互斥**(走 SOCKS5 必须保留 user-space)

#### C6 — ECS 健康检查 + 主备切换
- 每 ECS 暴露 `/health`,客户端(管理工具)定期探测
- 故障时把该分片账号临时切到备 ECS,产生一次性 IP 跳变(可接受)
- 留为下一个任务

#### C7 — R9 坐实
- Frida hook 客户端启动期 HTTP 上报,确认是否携带 NetConf md5
- 触发条件=出现实际封号反馈

## Acceptance Criteria

* [ ] C1: SRS50_REMAP 不再含 5067/5167;tcp_proxy 不监听 5767/5768
* [ ] C2: `netconf_patch.py --ecs-ip-pool a.b.c.d,x.y.z.w --shard-key u123` 产物中 NetConf 包含分片选中的 IP
* [ ] C2: 单 IP 模式(不传 pool)向后兼容,所有现有调用方无须改
* [ ] C3: `shard_assign.py` CLI 能查询/写入 `shard_map.yaml`,有单元测试覆盖 hash 一致性
* [ ] C3: 支持手动 override(指定账号→指定 IP),覆盖 hash 分配
* [ ] C4: spec/guides/noconfig-anti-ban.md 通过 review,被 setup_mitm.py / netconf_patch.py 顶部注释引用
* [ ] C4: spec 含香港节点适用场景判断 + IP 不可伪造原理 + 决策树
* [ ] 全部改动通过 `detect_changes()` 检查,affected processes 不超过 noconfig 相关链路

## Definition of Done

* `pytest tests/` 通过(含新增 shard_assign 单测)
* C1/C2/C3 在本地 setup_mitm 产物上肉眼校验输出 NetConf 含正确 IP
* `.trellis/spec/guides/noconfig-anti-ban.md` 落库
* 更新 [`remote-access.md`](.trellis/spec/backend/remote-access.md) "出口策略"小节
* `mitm-connection-stability-guide.md` 铁律 1 注释加一行:"ECS pool 模式下注入的 IP 仍须满足 _50[5045] 单值要求"
* 提交 commit 注释带任务号

## Out of Scope

* 实际购置第二台 ECS 或香港 VPS(用户后续自行决定,代码已支持)
* iptables DNAT 改造(C5,P2 文档化)
* 主备健康检查 / 故障切换(C6,下个任务)
* Frida 坐实 R9(C7,触发条件=出现封号反馈)
* 06-18 软路由 ipk 打包(并行任务)
* 住宅代理接入(已 research 排除)
* 多机房 ECS 间数据同步(每账号永远绑定同 ECS,无须同步)

## Spec Conflicts

* 无

## Technical Notes

### 涉及文件
- 改: [`remote/noconfig/hijack/netconf_patch.py`](remote/noconfig/hijack/netconf_patch.py) (C1+C2)
- 改: [`remote/noconfig/hijack/tcp_proxy.py`](remote/noconfig/hijack/tcp_proxy.py) (C1)
- 改: [`remote/noconfig/hijack/setup_mitm.py`](remote/noconfig/hijack/setup_mitm.py) (调用方接 ecs-ip-pool)
- 新: `remote/noconfig/hijack/shard_assign.py` (C3)
- 新: `data/noconfig/shard_map.yaml`(产物,git ignore)
- 新: `.trellis/spec/guides/noconfig-anti-ban.md` (C4)
- 改: [`.trellis/spec/backend/remote-access.md`](.trellis/spec/backend/remote-access.md) (出口策略小节)
- 改: [`.trellis/spec/guides/mitm-connection-stability-guide.md`](.trellis/spec/guides/mitm-connection-stability-guide.md) (铁律 1 一行)

### 关键约束(继承自 spec/guides/mitm-connection-stability-guide.md)
- 铁律 1:`LOCAL_TCP_LIST_50[5045]` 必须只含 ECS 单值(分片选中的那个 ECS),不能含真服
- 铁律 2:NetConf 内容变化必须 bump build 偏移
- 铁律 3:DNS responder 仍绑 0.0.0.0(本任务不动)

### 多 ECS 部署后续编排提示
- 每台 ECS 独立部署 noconfig + tcp_proxy + admin(端口都 8002),独立 user_store
- 玩家在 admin 看牌时,后台用 shard_map 反查"该用户绑定哪台 ECS",iframe 直接指向对应 ECS:8002 的 watch 页
- 跨 ECS 的 admin 列表合并由前端聚合(后端不联动),复杂度低

### 香港 VPS 选购参考
见 [research/hk-vps-for-mainland.md](research/hk-vps-for-mainland.md):
- **腾讯云轻量香港**(¥24/月起)— 入门低门槛、支持支付宝
- **搬瓦工 CN2 GIA-E HK** — 高价值通道,GFW 紧张期更稳
- **阿里云国际版 HK** — 企业级备选,贵但稳
- **避雷**:Vultr/Linode HK 普通 BGP(GFW 紧张期不可用)

## Research References

* [research/hk-vps-for-mainland.md](research/hk-vps-for-mainland.md) — 换 HK 出口大概率比阿里云杭州更糟(R3+海外 IP 标签),HK 只适合补充节点
* [research/residential-proxy-mainland.md](research/residential-proxy-mainland.md) — 住宅代理路线在 CN 技术勉强能、合规不能(踩帮信罪/非法控制雷区),已排除
* [research/hk-vps-plus-residential-proxy.md](research/hk-vps-plus-residential-proxy.md) — HK+住宅代理组合稳定性差、月费翻 4 倍,仅 30+ 用户且已封号才值得

## Implementation Plan (small PRs)

* **PR1**(C1): 删金币场中转 — 1 个 commit,改 2 个文件,加单测
* **PR2**(C2+C3): NetConf ECS pool + shard_assign 工具 — 1 个 commit,加 3 个文件,带单测
* **PR3**(C4): noconfig-anti-ban.md spec + 关联 spec 更新 — 1 个 commit,纯文档(含香港选购参考、IP 不可伪造原理、决策树)
