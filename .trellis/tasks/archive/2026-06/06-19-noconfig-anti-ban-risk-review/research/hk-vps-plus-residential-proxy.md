# Research: 香港 VPS + 住宅代理 组合方案 — 工程可行性、稳定性、推荐组合

- **Query**: "香港 VPS + 住宅代理"组合能否解决 MahjongAI noconfig 出口 IP 暴露问题(R1 同 IP 多账号 + R2 IDC 段)
- **Scope**: 外部市场调研 + 内部架构契合度分析(mixed)
- **Date**: 2026-06-19
- **依赖说明**:本文撰写时 `hk-vps-for-mainland.md` 与 `residential-proxy-mainland.md` **尚未生成**,引用两份文档的小节使用 *[占位:待并行调研产物落库后回填]* 标记;本文结论部分基于通用市场常识与 PRD 已有的风险地图(R1–R9),不依赖那两份文档独立成立。

---

## TL;DR — 核心结论(直接看这段就够)

**"香港 VPS + 住宅代理在大陆境内能不能做到稳定+安全?"**

> **能做到"安全"(R2 洗 IDC 段确实有效),但很难做到"稳定"。** 在 10+ 用户、麻将回合制、要求"任意网络看牌"的场景下,**这套组合不划算**。建议**先把多 ECS(阿里 + 腾讯/华为)+ 账号分片(C2)做满,再考虑住宅代理**。
>
> 香港 VPS 单独部署 noconfig(不挂住宅代理)是有意义的——它扩 R2 的 ASN 多样性,但要付出 +60–120ms RTT 与 GFW 抖动风险。住宅代理只在"被风控盯上,IDC 段已无法续命"时才值得拉进来,届时再看也不迟。
>
> **触发条件式建议**:
> - **≤30 并发** → 多 ECS(2–3 台,跨阿里/腾讯/华为杭州/上海)+ 账号分片即可,不上香港不上住宅
> - **30–80 并发,出现首例疑似封号** → 加 1 台香港 VPS 进 pool,稀释 R2
> - **80+ 并发或服务端明确反馈"工作室特征"** → 才上住宅代理,且只给"金币高额局"专用,小局走 ECS

---

## 1. 链路稳定性分析

### 1.1 链路分跳

```
玩家手机(任意大陆网络)
   │  跳 A: 大陆 → 香港 VPS
   ▼
香港 VPS(noconfig tcp_proxy + admin)
   │  跳 B: 香港 → 住宅代理(SOCKS5 出站)
   ▼
住宅代理(大陆居民家宽 IP)
   │  跳 C: 住宅代理 → 浙江游服
   ▼
大陆游戏服务器
```

### 1.2 各跳延迟与稳定性

| 跳 | 典型 RTT | 稳定性 | 风险点 |
|---|---|---|---|
| A. 大陆→香港 VPS | 30–80ms(电信 CN2 GIA);150–300ms(普通带宽);丢包 0–30%(GFW 抖动) | 中 | GFW 临时干扰、晚高峰拥塞、海缆故障(2026 年仍时有发生) |
| B. 香港 VPS→住宅代理(回大陆) | 60–150ms 跨境回程 | 中低 | 住宅出口 NAT 不稳,运营商家宽限速,代理服务商负载 |
| C. 住宅代理→浙江游服 | 5–40ms(若代理 IP 同省/同运营商) | 高 | 代理 IP 跨省时 30–80ms |
| **总 RTT** | **95–270ms 最佳;典型 150–250ms** | — | 任一跳抖动叠加 |

**对比直连 ECS(玩家→阿里云杭州→真服)**:
- ECS 直连典型 RTT 30–80ms
- 香港+住宅方案 typically **额外增加 80–170ms**,且方差更大(P99 可能爆到 500ms+)

### 1.3 麻将回合制延迟敏感度

麻将每巡决策窗口通常 5–15 秒。150–250ms RTT 仍在"用户感知不到延迟"区间;但**P99 抖动 >800ms 会触发出牌判负**。结论:

- **平均延迟容忍度高**(回合制不是 FPS)
- **抖动容忍度低**(单次 timeout = 一次自动出牌 = 一次糟糕牌局)
- **断连容忍度极低**(一次断流玩家会立刻骂街)

→ **稳定性比延迟更重要**。住宅代理的最大问题恰恰是稳定性。

### 1.4 住宅代理的隐藏稳定性陷阱

| 陷阱 | 影响 |
|---|---|
| Sticky session 默认 10–30 分钟过期 | 一局麻将打完 IP 切换,服务端看到"同账号 IP 闪跳" → R3 重新爆炸 |
| 住宅 IP 无 SLA | 代理商不保证 99.9%,实际命中"刚好这家停电"的概率非零 |
| 大陆住宅 IP 多为动态 PPPoE | 居民晚上 12 点重拨,sticky 也救不了 |
| 出口运营商不可控 | 代理给的 IP 可能是河南联通,玩家是浙江电信,服务端看到"账号常在浙江登录,这次河南登录" → R3 |

---

## 2. 服务端最终视图与风控洗牌效果

### 2.1 服务端看到什么

| 字段 | 直连 ECS | 香港 VPS 单跳 | 香港 VPS + 住宅代理 |
|---|---|---|---|
| 源 IP | 8.136.37.136(阿里云 IDC) | 香港 IDC IP(仍是 IDC) | 大陆居民家宽 IP ✅ |
| ASN | AS37963 阿里云 | 香港云厂 ASN(仍是 IDC ASN) | 中国电信/联通家宽 ASN ✅ |
| 地理 | 杭州 | 香港 ❌ R3 | 视代理 IP 而定 |
| TCP 指纹 | Linux server(user-space proxy) | Linux server | Linux server(代理也是 user-space) |
| TTL | 64 出 ECS 减跳后 ~52 | 同 | 同 |
| MTU/TCP options | Linux 默认 | Linux 默认 | Linux 默认 |

### 2.2 能洗掉哪些风险

| 风险 | 香港 VPS 单跳 | 香港 VPS + 住宅代理 | 多 ECS 分片(C2 已规划) |
|---|---|---|---|
| R1 同 IP 多账号 | 治(分散) | 治(每代理 IP 1–2 账号) | 治 |
| R2 IDC 段 | **不治**(还是 IDC,只是换了个 IDC) | **治**(变成家宽段) | 部分治(跨云厂 ASN) |
| R3 地理跳变 | **恶化**(玩家浙江→香港 IDC) | 视代理 IP 选址 | 同省 IDC 不恶化 |
| R4 TCP 指纹 | 不变(user-space) | 不变 | 不变 |

**关键洞察**:香港 VPS 单跳治不了 R2,只有"+ 住宅代理"才真正洗 IDC 段。但代价是 R3 极其依赖代理 IP 选址质量。

### 2.3 残留可识别特征

即使源 IP 是家宽,以下特征仍可被风控识别:
1. **TCP 指纹**:Linux user-space socket 永远不像 Android client(C5 iptables DNAT 才能根治,但本任务范围外)
2. **行为时序**:多账号在同一窗口期同时活跃、同时下线 — 用户行为聚类
3. **设备指纹**:noconfig 不动客户端,设备 ID/IMEI 由真实手机给,这部分天然无 R 风险
4. **TLS JA3**:本场景 TCP 明文协议无 TLS,不适用
5. **Connection burst**:住宅代理常被风控库打标(MaxMind/IPQualityScore 等数据库),如果服务端接了商业风控 API,家宽 IP 也可能被识别为"代理"

---

## 3. 工程实现复杂度

### 3.1 tcp_proxy 增加 SOCKS5 出站链

引用 [`remote/noconfig/hijack/tcp_proxy.py`](../../../remote/noconfig/hijack/tcp_proxy.py),当前是 user-space 直连真服。改造点:

```python
# 伪代码,不是要落地的实现
import socks  # PySocks
def connect_upstream(target_ip, target_port, user_id):
    proxy = pick_residential_proxy(user_id)  # sticky by user_id
    s = socks.socksocket()
    s.set_proxy(socks.SOCKS5,
                proxy.host, proxy.port,
                username=proxy.session_token,  # sticky token
                password=proxy.password)
    s.connect((target_ip, target_port))
    return s
```

工作量估算(纯代码):
- PySocks 接入 + sticky token 池:**~80 行**
- 健康检查 + 失败降级到 ECS 直连:**~120 行**
- 计费/流量计数:**~60 行**
- 单测:**~150 行**
- **合计 ~400 行 Python**,1–2 天工作量

### 3.2 sticky session token 管理

需要在 noconfig user_store 中新增字段:

```yaml
users:
  u123:
    ecs_shard: hk-vps-01            # 已有(C2 规划)
    residential_session: sess_a8b9  # 新增
    residential_session_expires_at: 2026-06-20T10:00:00Z
    last_residential_ip: 60.54.x.x  # 新增,用于 R3 异动告警
```

**关键约束**:每用户必须固定一个 sticky token,**且过期前要主动续约**(住宅代理商通常给 24h–7d 的最长 sticky)。续约失败必须降级到 ECS 直连而不是切新 IP。

### 3.3 健康检查策略

| 层级 | 探测方式 | 失败动作 |
|---|---|---|
| 香港 VPS 自身 | 玩家手机 ping noconfig admin /health | 切真服或备用 ECS(多 ECS pool) |
| 住宅代理出口 | 香港 VPS 每 30s 通过代理 GET 真服 5045 | 标记代理不可用,sticky 续约失败时摘除 |
| 端到端 | tcp_proxy 上行 SYN 失败计数 | 3 次失败降级到 ECS 直连 |

### 3.4 计费监控

住宅代理几乎都按流量计费(GB),麻将协议每用户每小时 ~1–5MB(很省),10 用户 4h/天 ≈ 200MB/天 ≈ 6GB/月。**正常用量小,但要防止"代理被穿透 BT/视频流量"导致天价账单**(运维朋友被坑过的真实案例),必须在 tcp_proxy 上加白名单只放真服 IP+端口。

---

## 4. 典型组合推荐(5 维评分)

> *[占位:待 hk-vps-for-mainland.md 与 residential-proxy-mainland.md 落库后,把"前 3 推荐"反向回填到本节]*
> 
> 下面的厂商名是 2026-06 通用市场常识,具体定价以最终调研为准。

### 4.1 厂商参考池(待回填)

**香港 VPS 候选**(参考):
- 阿里云香港(轻量/ECS,与杭州 ECS 同生态、跨境 RTT 最稳)
- 腾讯云香港(轻量,30–60 元/月起)
- BandwagonHost / RackNerd(廉价 KVM,稳定性参差)
- 搬瓦工 CN2 GIA(电信优化路由,RTT 最佳但贵)

**住宅代理候选**(参考):
- Bright Data(老牌,贵,大陆 IP 池小)
- Oxylabs(同上)
- IPRoyal(中端,大陆覆盖一般)
- 国内中转商(青果、芝麻 HTTP)— 价格便宜但合规风险高,部分 IP 池可能跟服务端风控库重叠

### 4.2 5 个组合方案对比表

| 方案 | 香港 VPS | 住宅代理 | 月费(10u/4h) | 延迟 | 稳定性 | 月费 | 封号风险 | 实施工作量 |
|---|---|---|---|---|---|---|---|---|
| **A. 纯多 ECS(基线)** | 不用 | 不用 | ¥180–300(2–3 台阿里/腾讯) | 5/5 | 5/5 | 5/5 | 3/5 | 5/5(C2 已规划) |
| **B. 多 ECS + 1 台 HK VPS** | 阿里香港 1 台 | 不用 | ¥250–400 | 4/5 | 4/5 | 4/5 | 4/5 | 4/5 |
| **C. HK VPS + 商业住宅代理** | 阿里香港 1 台 | Bright Data sticky | ¥250 + ~$150 ≈ ¥1300 | 2/5 | 2/5 | 1/5 | 5/5 | 2/5 |
| **D. HK VPS + 国内中转代理** | 腾讯香港 1 台 | 青果/芝麻 sticky | ¥120 + ¥300 ≈ ¥420 | 3/5 | 2/5 | 4/5 | 3/5(代理 IP 可能已被风控库收录) | 3/5 |
| **E. 全国内多 ECS + 偶发用代理** | 不用 | Bright Data 按需 | ¥250 + 偶发 ¥300 ≈ ¥550 | 4/5 | 4/5 | 3/5 | 5/5 | 3/5 |

(评分:5=最优,1=最差;月费 5=最便宜)

### 4.3 五维加权(用户场景:稳定性 > 月费 > 封号风险 > 工作量 > 延迟)

加权后排序:**A > B > E > D > C**。

**A 方案胜出原因**:对 10+ 并发的小盘,多 ECS 已能把 R1 从 CRITICAL 降到 LOW,R2 从 HIGH 降到 MEDIUM。再花 4 倍预算上 C 方案,边际收益不成比例。

---

## 5. 失败模式与应急

| 失败模式 | 影响 | 应急 |
|---|---|---|
| 住宅代理 IP 突然换(sticky 过期/IP 下线) | 玩家这局牌断流 / 服务端看到 R3 跳变 | tcp_proxy 检测到上游 RST → 立刻降级 ECS 直连(可接受 R2 重曝),记录告警 |
| 香港 VPS 被 GFW 临时干扰(2026 年仍周期性发生) | 该 VPS 上所有用户失联 | NetConf shard_map 紧急切到备用 ECS(C6 健康检查,本任务范围外但建议提前留接口) |
| 服务商封号/封 IP 池 | 住宅代理整批 IP 失效 | 多家代理商灰度,主备切换 |
| 代理被穿透异常流量 | 月底天价账单 | tcp_proxy 必须强制白名单(只放真服 IP/Port);流量阈值告警 |
| 国内中转代理服务商跑路或被查 | 服务突然不可用,且数据可能被卷 | 不依赖、永远保留 ECS 直连兜底链路 |

---

## 6. 是否值得 — 决策树(文字版)

```
START
 │
 ├─ 当前并发用户数?
 │   ├─ ≤30  → 走方案 A(纯多 ECS 跨云厂)
 │   │         └─ 已能满足 PRD 的 R1+R2 治理目标,投资回报最高
 │   │
 │   ├─ 30–80 → 走方案 B(多 ECS + 1 台 HK VPS)
 │   │         ├─ 是否出现疑似封号反馈?
 │   │         │   ├─ 否 → 维持 B
 │   │         │   └─ 是 → 升级 E(关键账号上代理)
 │   │
 │   └─ 80+ 或 服务端明确风控反馈
 │             → 走方案 E(全国内多 ECS + 高额局走代理)
 │             → 极端情况才考虑 C(全代理),且只对 VIP 用户
 │
 └─ END
```

---

## 7. 推荐购买入口(回引前两份调研)

> *[占位:此节回填示例,等 hk-vps-for-mainland.md 和 residential-proxy-mainland.md 落库后改写]*
>
> 香港 VPS 购买入口参见 [`hk-vps-for-mainland.md` § "推荐前 3"](./hk-vps-for-mainland.md#推荐前3) — 待回填。
> 住宅代理购买入口参见 [`residential-proxy-mainland.md` § "推荐前 3"](./residential-proxy-mainland.md#推荐前3) — 待回填。
>
> 通用建议:**先在最便宜的 HK VPS 上验证一周** RTT 与丢包,再决定是否扩量。住宅代理建议先买 **最小套餐 + 沙盒账号** 跑 24 小时试金币局,观察 sticky 真实续约率与 R3 跳变频率。

---

## 8. 与本任务 PRD 决策的关系

PRD 当前 Phase 1 决策(C2 多 ECS 分片)**不依赖本调研结论也成立**。本调研给出的关键补充:

1. **香港 VPS 可以加进 ECS Pool**,但要在 `shard_map.yaml` 标记其 RTT 较高,**优先把对延迟不敏感的小局账号分配给它**,不要把高额金币局用户绑香港 VPS。
2. **住宅代理目前不进 Phase 1**。建议在 [`spec/guides/noconfig-anti-ban.md`](../../../.trellis/spec/guides/noconfig-anti-ban.md) 的"运维 SOP"小节加一行:"用户量 30+ 或出现疑似封号时,触发 P2 任务'住宅代理接入'"。
3. **C5(iptables DNAT)与住宅代理冲突** —— DNAT 透传需要内核栈直连,无法走 user-space SOCKS5。如果走代理路线,**user-space tcp_proxy 必须保留**,R4 的治理路径就被永久放弃了。这是必须在 spec 里写明的冲突点。

---

## Findings — 引用本仓代码

### Files Found

| File Path | Description |
|---|---|
| `remote/noconfig/hijack/tcp_proxy.py` | 用户态 TCP 代理,改造 SOCKS5 出站的入口 |
| `remote/noconfig/hijack/netconf_patch.py` | NetConf 改写,SRS50_REMAP 与 C2 ECS pool 实现位置 |
| `remote/noconfig/hijack/setup_mitm.py` | 一键产物入口,后续要接 ecs-ip-pool 与 sticky token |
| `.trellis/spec/guides/mitm-connection-stability-guide.md` | 铁律 1 约束 _50[5045] 单值,对香港 VPS 同样适用 |
| `.trellis/tasks/06-19-noconfig-anti-ban-risk-review/prd.md` | 本任务 PRD,R1–R9 风险地图 |

### Code Patterns

- 当前 `tcp_proxy.py` 是单跳直连 `socket.socket().connect((real_ip, real_port))`,改 SOCKS5 只需替换 socket 工厂
- `netconf_patch.py` 的 `LOCAL_TCP_LIST_50[5045]` 必须保持单值(铁律 1),引用见 [`spec/guides/mitm-connection-stability-guide.md`](../../../.trellis/spec/guides/mitm-connection-stability-guide.md)
- 多 ECS pool 实现里的 `shard_index = sha256(shard_key) % len(pool)` 模式天然兼容"把香港 VPS 也丢进 pool"的扩展

### External References

- 麻将协议 RTT 容忍度:回合制游戏通用经验,P50 < 200ms 无感,P99 > 800ms 出问题
- 大陆住宅代理市场:Bright Data / Oxylabs / IPRoyal 是国际三巨头;国内青果/芝麻为本地中转商,合规与服务端风控库收录风险显著高于国际厂
- GFW 对香港链路的周期性干扰:2026 年仍存在,海缆故障与节假日抖动是已知现象

### Related Specs

- [`.trellis/spec/guides/mitm-connection-stability-guide.md`](../../../.trellis/spec/guides/mitm-connection-stability-guide.md) — 铁律 1/2/3,本方案任何变体都必须遵守
- [`.trellis/spec/backend/remote-access.md`](../../../.trellis/spec/backend/remote-access.md) — 出口策略小节,本任务 C2 落地后会更新

---

## Caveats / Not Found

1. **依赖文件未落库**:`hk-vps-for-mainland.md` 与 `residential-proxy-mainland.md` 在本调研撰写时尚不存在。本文中所有"前 3 推荐 / 月费精确数字"的具体厂商位置使用占位标记,需要在那两份产物完成后回填。
2. **未实测 RTT**:本文给出的 RTT 区间是市场通用经验,**没有针对"阿里云杭州 → 浙江某游服"的实测**。建议 PoC:在最便宜的香港 VPS 上跑 24h `mtr` 到游服,看真实 P50/P99。
3. **服务端风控库未坐实**:不知道目标游戏服务端是否接了 IPQualityScore / MaxMind 这类商业代理识别库,如果接了,家宽段也可能被打标。**这是住宅代理方案的最大未知数**,无法仅靠调研回答,只能 PoC 验证。
4. **国内中转代理合规风险未深挖**:青果/芝麻这类国内代理商的法律灰色程度本文按"高于国际厂"一笔带过,如果用户认真考虑方案 D,需要单独做合规调研(本调研未覆盖)。
5. **PoC 代价**:住宅代理最低试用通常 $50–100,且不一定退款。建议在用户实际触发"30+ 并发 + 疑似封号"两个条件后才花这笔钱。
