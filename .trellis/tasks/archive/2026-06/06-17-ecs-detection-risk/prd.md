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

## Decision (ADR-lite)

**Context**: 边锋系运营商 + ECS 同城掩护 + 装死窗口存在，但 P0 漏洞（伪版本号上行）"对手 1 人周即可灭掉"。当前 noconfig 才上线 1 周，用户 < 10，是反检测施工的最佳窗口期。

**Decision**: 采用 **B（稳妥型）** 反检测 MVP = #1 + #2 + #5 + #6。多 IP 池（#3）等 B 跑过验证期再加，避免引入采购/运维复杂度；TCP 栈伪装（运营商不主动跑 p0f）暂不做。

**Consequences**:
- 优点：堵死 P0、备好 P1 应急工具、主动限流停在装死窗口；零采购成本
- 风险：超过 10 用户后被打概率仍会上升（无 IP 池兜底）
- 后续：用户量逼近 10 时启动多 IP 池采购评估（独立任务）

## Final Requirements

P0（必须）：
- **R1** ECS 透明代理层在 ClientInfo 上行帧改写假版本号 `2.5.10.2776` → 官方真实版本（依赖先 dump 出 ClientInfo 的 msg_type 编号）
- **R2** 实测：抓 ECS 用户 PlayerData 帧确认 `ip` 字段值（验证假设：服务端权威记录 ip = 8.136.37.136）
- **R3** 实测：从 noconfig live 流量里 dump 出 ClientInfo 上行帧的 msg_type 编号（疑 `0x000F` / `0x620C` / `0x620D`）
- **R4** 实测：用废账号做"经 ECS vs 真服直连"对照登录，确认阿里云杭州段是否已被风控

P1（应做）：
- **R5** `frida/dump_xxtea_key.js` —— hook `cocos2d::LuaStack::setXXTEAKeyAndSign`，APK 大版本更新即跑
- **R6** noconfig admin 加配置 `max_active_users ≤ 10`，超出时新用户注册返回 503 + UI 提示"已满员"

## Acceptance Criteria

- [ ] R1: 真机经 ECS 登录后，从 ECS dump 的上行 ClientInfo 帧里 version 字段为官方真实版本（不是 2.5.10.2776）
- [ ] R2: 抓到一段含 PlayerData 的 pcap，确认 ip 字段值并记录到 `research/srs-server-side-fingerprint.md`
- [ ] R3: ClientInfo msg_type 编号写入 `.trellis/spec/backend/game-protocol.md`
- [ ] R4: 对照实验报告写入 `research/idc-ip-multi-account-risk.md`，含两条结论：a) ECS 段是否秒封 b) 是否有软处置（限游戏/二次验证）
- [ ] R5: `frida/dump_xxtea_key.js` 真机跑通，输出当前版本 key（应等于 `03f1fdcbf5215b45`）
- [ ] R6: admin POST /register 第 11 个用户返回 503，UI 显示"系统已满员"

## Definition of Done

- 6 条 R 全部完成、各有验证证据
- `.trellis/spec/backend/remote-access.md` 新增 §17 "反检测约束"章节，沉淀本任务的所有运行铁律
- 所有反检测决策（包括"暂不做的"如多 IP 池、TCP 栈伪装）都有 ADR 记录

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

## Research Findings（2026-06-17 完成）

### [research/idc-ip-multi-account-risk.md](research/idc-ip-multi-account-risk.md) — 一句话结论：**中-高风险，当前装死窗口存在**

| 发现 | 关键事实 |
|---|---|
| **运营商身份实锤** | hzxuanming.com 备案主体 = 杭州轩铭网络科技；与边锋 `gameabc.com` / `sanguosha.com` 共用电信许可证号 **浙B2-20090273**；根页源码用 bianfeng.com 仙龙九平台。**对手是边锋系，不是小厂**。20 年棋牌运营 + 每日发封号名单 |
| **行业基线** | 腾讯云科普 + 网易易盾官方均确认"同 IP 多账号 = 工作室特征 = 制裁"；易盾明面阈值 50 角色/天 |
| **ECS 同城掩护** | 真服 `47.96.0.227` 与我们 `8.136.37.136` 同属阿里云杭州 **AS37963**，比海外/跨厂反代命中信号弱 1-2 档 |
| **时间窗口** | ≤ 10 用户/1 月：< 15% 被打；10-50 用户/3 月：30-50%；> 50 用户/6 月：**70%+** |
| **处置形态预测** | 永封账号 + 清积分 + 同 IP/设备团伙连坐；**封 IP 段在棋牌业较罕见**（怕误伤）；最致命的是**客户端层升级 NetConf 校验** |

### [research/cocos2dx-manifest-tamper-detection.md](research/cocos2dx-manifest-tamper-detection.md) — 一句话结论：**伪造 manifest 引擎层永久安全；但伪 version 上行是 P0**

| 发现 | 关键事实 |
|---|---|
| **引擎层无签名** | `AssetsManagerEx.cpp:78` `_verifyCallback(nullptr)` 默认初始化、`:1103` `if (_verifyCallback != nullptr)` 才校验；`Manifest.cpp` 全文 zero hit on `sign\|RSA\|HMAC\|public.*key`。**Cocos2d-x 引擎层永久信任 manifest，只要 md5 自洽就放行** |
| **🚨 P0 风险** | 假版本号 `2.5.10.2776` 通过 `ClientInfo`（`Module.lua:1006`）上行；服务端只要加 1 个 `client_manifest_version` 字段 + 白名单 SQL（**1 人 1 周成本**），整套 4G 链路 100% 失效 |
| **P0 应对** | ECS 中转里**预埋"上行登录包改写客户端 version 为官方真实版本"** —— 零停机激活 |
| **P1 风险** | NetConf XXTEA key `03f1fdcbf5215b45` —— 大版本 APK 可能换 |
| **P1 应对** | Frida hook `cocos2d::LuaStack::setXXTEAKeyAndSign` 自动 dump key 成一行脚本存 `frida/`，APK 更新即跑 |

### [research/srs-server-side-fingerprint.md](research/srs-server-side-fingerprint.md) — 一句话结论：**服务端 5 个 IP 画像字段实锤；硬件指纹无暴露**

| 发现 | 关键事实 |
|---|---|
| **🚨 IP 画像字段实锤** | PlayerData 服务端权威字段含 `iparea / sp / lastip / lastiparea / lastsp`（来源：`apk_research/decrypted-lua/app/Protocols/SRSProtocol.lua:19-110`）。**服务端有意识用 IP 做账号画像，不是猜测** |
| **硬件指纹未暴露（好消息）** | PlayerConnect 字段：`clienttype/usertype/areaid/userid/pwd/identify(UDID+MAC)/ver/channelid/osver/nGameID`。**没有** IMEI/Android ID/广告 ID/分辨率/运营商；`identify` 透传，每用户真机原值，看起来不像批量伪造 |
| **ClientInfo 假版本号** | 假版本会上行（msg_type 待 dump 确认，疑 `0x000F` 或 `0x620C/D`）—— 与 P0 同一根因 |
| **TCP 栈 p0f 指纹** | 理论可行（ECS Linux vs 真机 ARM 区分度高），但运营商不主动跑 p0f；事故复盘可能查 |
| **重连指纹** | `RECONNECT_DELAY=2.0` 仅影响 cloud_player 旁观路径，noconfig 主路径走 `tcp_proxy.py` 透传，重连节奏由真机决定 |

### 实测项（caveats）

- 实抓一段 ECS noconfig 用户的 PlayerData 日志确认 `ip == 8.136.37.136`
- 抓 ClientInfo 上行帧 dump 找出 msg_type 编号
- 用废账号做"经 ECS vs 直连"对照实验确认 IDC 段是否已被风控
