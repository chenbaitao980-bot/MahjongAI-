# 热更覆盖 NetConf — 一次热点，永久云端读牌（不装 app / 不改手机配置 / 不 root）

## 目标

手机**连一次热点**（期间打开游戏跑一次热更检查）后，后续**无论换什么网络（WiFi/4G）**，云端（ECS）都能实时读取手牌，**直到游戏发布版本号高于我们注入的伪版本**。

铁约束（用户最终确认）：
- ❌ 不 root
- ❌ 不在手机装任何 app
- ❌ 不改手机任何系统设置（DNS / 代理 / VPN / CA 一律不动）
- ✅ 手机端唯一动作 = 连那一次热点
- ✅ 只玩**台州**（区 areaID=7109, srsGroupID=5045）；玩法=金币场 + 创建房间 1v1

## 可行性结论：成立（已反汇编实锤）

之前判"热点劫持失败/TLS 是墙"两次都被推翻。最终破解链每一环都有证据：

| 环节 | 状态 | 实锤 |
|------|------|------|
| **TLS 校验关闭** | ✅ | 热更下载器 `universe::Downloader2::_initJobCurl`（`libcocos2dlua.so` @0x8eacf0）硬编码 `CURLOPT_SSL_VERIFYPEER=0` + `CURLOPT_SSL_VERIFYHOST=0`（`mov x2, xzr`）。它用 .so 自带 libcurl+OpenSSL，**不受 `network_security_config` 约束**，无需 CA。热点自签证书即被接受 |
| **manifest 可伪造** | ✅ | `app/hotupdate/universe/hotfix/Manifest.lua` 完整性=逐文件 md5、**无密码学签名**。伪造时填我们文件的 md5，自洽通过 |
| **NetConf 可覆盖** | ✅ | `assets/res/GameHotUpdate3/Lobby/project_10001.manifest` 的 `file_list` 含 `src/app/config/NetConf.luac`；`LayerFS.lua` 可写层(DocLayer, `getWritePath()+HotFixPath`)优先级高于 APK 内置层 |
| **持久化** | ✅ | 伪造版本号设极高（如 `9.9.9.99`）→ `Manifest.versionLessThan` 判定已最新 → 永不回滚，跟手机走任意网络 |
| **不踢手机** | ✅ | 手机仍是唯一会话；ECS 只透传 + 旁路解 0x2bc0（明文），不开第二连接 |
| **NetConf 是唯一咽喉** | ✅ | `NetEngine.lua` 三个 connect 入口全走 `getTcpConnectInfoByGroupId`，无旁路硬编码 |

关键资产（已就绪）：
- XXTEA luac key=`03f1fdcbf5215b45` sign=`devaguopeifei`（重加密改过的 NetConf.luac 用）
- 真实 manifest 样本 148KB（克隆微改）
- SRS AES-CFB128 key 已破、0x2bc0 明文可被动解（`remote/srs_spectator/crypto.py` + `stable/protocol.py`）

## 架构

### 设置期（一次性，手机在热点上）
```
手机(连热点, 打开游戏触发热更检查)
  → 游戏请求 https://gxb-api.hzxuanming.com/hotfix_update?...&version=旧
  → PC 热点: ① DNS 把 gxb-api/gxb-oss.hzxuanming.com 解析到 PC
            ② 自签 TLS 应答(被 VERIFYPEER=0 接受)
            ③ 返回伪造 manifest(版本=9.9.9.99, file_list 把 NetConf.luac 的 md5/name 指向我们的文件)
  → 游戏从 file_url 下我们的 NetConf.luac → md5 自洽通过 → 写入 HotFixPath 覆盖层
  → 此后游戏每次启动加载改过的 NetConf：台州 5045 → ECS
```

### 运行期（任意网络，永久）
```
手机(任意网络) → ECS:大厅端口 ──透传──> 真大厅 47.96.101.155
                     └─ MITM 改写 RespSRSAddr.szIP → ECS（让动态游戏 SRS 也回流）
手机          → ECS:7777 ──透传──> 真游服 47.96.0.227:7777
                     └─ 旁路 0x2bc0(明文) → stable 管线 → 手牌 → noconfig relay 网页
```

## 代码组织（隔离铁律 — 建在 noconfig 模式上）

只在 **noconfig 模式（端口 8002）** 上扩展，**不碰** hotspot/vpn：

```
remote/
├── noconfig/                       ← 在这条线上扩展
│   ├── app.py / main.py            ← 现有，仅【新增】端点/路由，不改现有端点
│   └── hijack/                     ← 新增子包（本任务全部新增代码落点）
│       ├── __init__.py
│       ├── setup_mitm.py           ← 设置期: DNS 伪应答 + 自签 TLS + 伪造 manifest 服务 + 投递改过的 NetConf.luac
│       ├── netconf_patch.py        ← 解 XXTEA → 改 LOCAL_TCP_LIST[5045]→ECS → 重加密 luac (key=03f1fdcbf5215b45)
│       ├── manifest_forge.py       ← 克隆真实 manifest, bump 版本, 替换 NetConf.luac 条目 md5/name
│       └── tcp_proxy.py            ← 运行期: ECS 双代理(大厅透传+RespSRSAddr改写, 7777透传+0x2bc0旁路)
├── vpn/        ← 不动
├── hotspot/    ← 不动
├── relay/core.py ← 不改现有端点(可新增)
└── cloud_player.py ← 不改现有接口
```

复用（import，不改源码）：`stable/protocol.py`、`stable/tracker.py`、`stable/mapping.py`、`remote/srs_spectator/crypto.py`、`remote/srs_spectator/frame.py`、`remote/relay/state_store.py`、`remote/extractor/capture.py`（抓包参考）。

## 里程碑

- **M0 原型验证（先做，决定 go/no-go）**
  - [ ] 实测：手机连热点、DNS 指 PC、自签 TLS，游戏热更检查是否接受自签证书并 GET manifest（确认 VERIFYPEER=0 在真机生效，且 version-manifest 也走 Downloader2 而非验证型 un.Http）
  - [ ] 实测：伪造 manifest（bump 版本 + 单文件 diff）能否被 `HotFixProcessor` 接受并只下 NetConf.luac
- **M1 NetConf 投递闭环**：netconf_patch + manifest_forge + setup_mitm 串起来，手机热更后 `srslist`/连接日志显示连 ECS
- **M2 ECS 双代理**：tcp_proxy 大厅透传 + RespSRSAddr 改写（变长：`47.96.0.227`=11B、ECS IP 长度不同，需调 readString 前缀 + SRS 帧长 + CFB 重加密）+ 7777 透传 + 0x2bc0 旁路解码
- **M3 接 noconfig relay**：解出的 BattleState 进 StateStore → 现有网页展示
- **M4 持久化与稳健**：伪版本号顶高、断线重连、ECS 高可用提示

## 技术风险

1. **manifest GET 的客户端**：文件下载确定走 Downloader2(验证关)；version-manifest 若走 `un.Http` 且其验证证书 → 需另解。**M0 必须实测**
2. **真服热更回滚**：日后官方推版本 > 9.9.9.99 会覆盖我们的 NetConf → 需重连一次热点。可接受（=APK 更新前有效，符合用户预期）
3. **RespSRSAddr 变长改写**：IP 长度不等 → 必须改 readString 长度前缀 + SRS 帧长头 + CFB 流重加密（key 已破，可做）
4. **ECS 宕机**：手机连不上 ECS 会连不上游戏 → 运行期 ECS 必须高可用；设置期失败不影响手机原有玩法
5. **热更触发时机**：需手机在热点上启动游戏跑到热更检查（启动/登录流程自动触发）

## 验收标准

- [ ] 手机连一次热点 + 开游戏跑热更后，`getWritePath()/HotFixPath` 下出现改过的 NetConf.luac，台州连接指向 ECS
- [ ] 手机**断开热点切 4G**，重开游戏仍连 ECS（不依赖热点）
- [ ] ECS noconfig relay(:8002) 页面实时显示台州金币场/创建房 1v1 的完整手牌，逐摸逐打更新
- [ ] 手机正常打牌无卡顿、不掉线
- [ ] 手机全程**未装 app、未改任何系统设置、未 root**
- [ ] hotspot 模式(:8000) 功能不受影响
- [ ] vpn 模式(:8001) 功能不受影响
- [ ] noconfig 模式(:8002) 现有端点行为不变（仅新增）
- [ ] cloud_player.py CLI 现有参数行为不变

## Out of Scope

- 台州以外的区 / 非金币场非创建房玩法
- 官方热更回滚后的自动重注入（手动重连热点即可）
- Linux/OpenWrt 移植
- 修改 vpn/ hotspot/ 任何代码、修改 settings.yaml 主配置
