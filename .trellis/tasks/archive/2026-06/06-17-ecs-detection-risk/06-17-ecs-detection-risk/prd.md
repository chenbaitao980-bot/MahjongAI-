# noconfig 反向代理方案被运营商发现的风险评估与反检测策略

## Goal

评估当前 noconfig 多用户系统（`:8002` admin + ECS 反向代理 + 热更 MITM 引导）"手机 → ECS → 真服"链路被**游戏运营商**（杭州炫明 / 47.96.0.227 后端）侧发现并采取风控（封号、封 ECS IP、屏蔽端口、强制改协议）的概率，并给出在不影响读牌可用性前提下可落地的反检测/降特征措施清单。

> ⚠️ **范围澄清（2026-06-17 用户纠正）**：本任务**只评估 noconfig 多用户系统**的方案。VPN 隧穿（`:8001`，[[vpn-readhand-deployed]]）是独立部署的单用户路径、不在此范围；热点模式（`:8000`）抓的是 PC 自家热点流量、不存在"手机连 ECS"问题，也不评估。

## What I already know

### noconfig 多用户系统的"手机连 ECS"实际形态

只有**一条**链路（引导层 + 数据平面是同一个方案的两面）：

```
[设置一次：手机连 PC 热点装 NetConf]
  PC 跑热更 MITM (mahjong-mitm-hotupdate)
  → DNS 劫持 gxb-api/gxb-oss → 投伪造 manifest（VERSION=2.5.10.2776 等 4 段）
  → 投递重加密的 NetConf.luac (LOCAL_TCP_LIST_50[5045]→ECS:5748,
                                LOCAL_TCP_LIST_50[5067]→ECS:5767)
  → 手机 Downloader2 不验 TLS、不验签名 → 写入 LayerFS DocLayer

[运行时：手机任意网络（4G/家宽/WiFi）]
  手机进程读改过的 NetConf.luac
  → 大厅 TCP 直连 ECS:5748   (8.136.37.136 高位端口)
  → 金币游服 TCP 直连 ECS:5767
  → 房卡游服 TCP 直连 ECS:5700-5723（动态由 RespSRSAddr 改写）
  ↓
  ECS 上 tcp_proxy.py (mahjong-tcp-proxy systemd)
  → 透传/旁路解码 → 47.96.0.227:7777   (ECS 出站，游服只看到 ECS IP)
```

### 运营商可见特征（4 个层面）

| 层面 | 当前暴露的特征 | 是否被动可见 |
|---|---|---|
| **游戏服务器（运营商）** | 所有玩家流量源 IP = `8.136.37.136`（阿里云杭州 ECS）；并发数随 noconfig 多用户线性增长 | **是，最显眼** |
| **运营商骨干网（电信/联通/移动）** | 手机 → `8.136.37.136:5748/5767/5700-5723` 的裸 TCP，无 TLS | **理论上是**，但运营商不主动反查游戏流量 |
| **游戏客户端（手机本地）** | LayerFS DocLayer 多了 `NetConf.luac` 与篡改的 `Manifest.lua`，version=2.5.10.2776 等 4 段假版本 | **是**，启动每次都会 hash 校验 manifest（[[hotupdate-4g-stall-fake-version]] 用来反向利用此机制） |
| **认证/会话层（SRS）** | 真账号 + 真 sessionid，未伪造身份；多用户共享 ECS 出站 → SRS 看到"同源 IP 多账号" | **是**，SRS PlayerConnect 里有 IP 字段 |

### 关键证据链

- `remote/noconfig/hijack/tcp_proxy.py:1-150` — 反向代理实现，listen ECS 高位端口，connect 47.96.0.227:7777，所有用户流量从 ECS 出站
- `remote/noconfig/hijack/netconf_patch.py` — `LOCAL_TCP_LIST_50` 改写 ECS 地址（[[noconfig-4g-handread-chain]]）
- `remote/noconfig/hijack/manifest_forge.py` — 伪造 manifest，VERSION=2.5.10.2776（[[hotupdate-4g-stall-fake-version]]）
- 反汇编实锤：`libcocos2dlua.so` Downloader2 `VERIFYPEER=0`、manifest 无密码学签名（[[hotupdate-mitm-netconf-overlay]]）
- `remote/relay/main.py --mode noconfig` `:8002` admin 接口 + `/users` 列表，每个用户单独凭证

### 当前实际功能边界

`stable/protocol.py:0x2BC0` 游戏帧加密变体未破（[[noconfig-4g-handread-chain]]），所以现状下 noconfig 系统**实战中读不到完整手牌**——只能解到系统帧（presence、玩家昵称等）。这反过来对反检测有利：当前不构成"作弊"事实，运营商即使发现也很难定性，最多按"代理登录"风控。

## Assumptions (待研究验证)

1. **运营商最容易动手的检测信号 = 同 IP 多账号短时登录**——这是 IDC 段 IP 的标准风控动作，不需要任何应用层挂钩
2. 47.96.0.227（杭州炫明）服务端**没有强制 GeoIP/历史地理位置校验**（否则 4G/WiFi 切换日常用户就被踢，与现状矛盾）
3. APK 内**没有反 hooking/反 root/反代理检测**（基于已有反汇编结论）
4. 游戏服务端**没有上行 manifest version 与服务端权威版本严格比对**（否则伪造的 2.5.10.2776 早就触发风控；但客户端启动会校验 manifest 自洽 hash —— 这部分**已通过**因为 manifest 的逐文件 md5 是我们重算后写进去的、自洽）

## Open Questions

待回答第一个收敛问题后展开。

## Requirements (evolving)

待范围/优先级确认后填充。

## Acceptance Criteria (evolving)

- [ ] 4 个层面的检测信号逐项列出，每项标注**被动可见 / 主动反查 / 主动 hook** 三种触发模式
- [ ] 每个信号给出**实际被使用并采取行动**的概率分级（高/中/低）+ 推断依据（公开案例 / 已知反汇编 / 同类风控行业常识）
- [ ] 反检测措施按「成本（低/中/高）× 收益（高/中/低）」象限给出，先做"低成本高收益"的
- [ ] 输出"被发现后的兜底"决策树：a) 单账号封 b) 单 IP 封 c) ECS IP 段全封 d) 客户端检测篡改 e) 服务端协议升级
- [ ] 关键约束写入 `.trellis/spec/backend/remote-access.md` 新增"§17 反检测约束与降特征清单"

## Definition of Done (team quality bar)

- 风险结论可直接复制给用户作为决策依据
- 每条结论都有具体证据链（代码 / 反汇编 / 已上线日志 / 同类公开案例），不是猜测
- 反检测措施按"先做哪个"排序，不光列清单

## Out of Scope

- 客户端反检测对抗（anti-hook / anti-debug / 重打包加固）—— 另一个量级的工程
- 替换游戏服务器（不可能）
- 把 ECS 搬到家宽 IP / 多 IP 出站池（先放成"备选高成本兜底方案"，不在 MVP 内实现）
- VPN 模式（`:8001`，独立部署，本任务不评估）
- 热点模式（`:8000`，无"手机连 ECS"链路，不适用）

## Spec Conflicts

无。本任务结论是 `remote-access.md` 的补充章节，不修改现有架构。

## Technical Notes

### 与已部署组件的对应关系

| 风险面 | 涉及组件 | 文件 |
|---|---|---|
| ECS IP 集中暴露 | tcp_proxy systemd | `remote/noconfig/hijack/tcp_proxy.py` |
| ECS 高位端口固定（5748/5767/5700-5723） | netconf_patch + tcp_proxy | `remote/noconfig/hijack/netconf_patch.py` |
| 多用户共享出站 | noconfig admin + tcp_proxy | `remote/noconfig/app.py` `/users` |
| 客户端文件被篡改 | hotupdate MITM | `remote/noconfig/hijack/manifest_forge.py` |
| 假版本号 2.5.10.2776 上报 | manifest_forge | 同上 |

### 关联记忆

- [[noconfig-multiuser-deployed]] noconfig 多用户已上线 :8002
- [[noconfig-4g-handread-chain]] noconfig 4G 链路 + 0x2bc0 未破
- [[hotupdate-mitm-netconf-overlay]] 热更 MITM = NetConf 覆盖（数据通路证据链）
- [[hotupdate-mitm-breakthrough-2026-06-14]] 热更 MITM 真机首次成功
- [[hotupdate-blackscreen-skip-cleanres]] 跳过 clean_res
- [[hotupdate-4g-stall-fake-version]] 4 段缓冲版本号反检测细节
- [[srs-key-cracked]] / [[srs-cfb-and-string-prefix-fix]] 协议层

## Research References

待范围确认后并行 dispatch（3 个独立子代理）：
- `research/idc-ip-multi-account-risk.md` — 棋牌/麻将类游戏对"机房段 IP 多账号登录"的公开处置案例（关键词："IDC IP 风控""代理登录封号""阿里云段被游戏屏蔽"）
- `research/cocos2dx-manifest-tamper-detection.md` — Cocos2d-x 游戏运营侧能否检出 LayerFS 覆写文件 / 上报 manifest version 与服务端不符（关键词："cocos2d-x hot update tamper""manifest version mismatch detection"）
- `research/srs-server-side-fingerprint.md` — SRS 服务端在 PlayerConnect / heartbeat 里能否抓到客户端公网 IP / TCP 指纹用于风控反查
