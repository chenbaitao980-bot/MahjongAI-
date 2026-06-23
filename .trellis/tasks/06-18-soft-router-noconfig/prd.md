# brainstorm: soft-router noconfig packaging

## Goal

把当前依赖本地电脑热点/本地服务的 MahjongAI 无配置模式，梳理为可迁移到其他软路由或旁路由上的一套方案，并评估是否能打包成“一键启动”的单软件形态，同时尽量提高代码不被第三方直接看到的门槛。

## What I already know

* 仓库已经存在“普通 WiFi / 软路由常驻 extractor”的部署路径，核心入口是 `remote/extractor/package_extractor.py`，并配套 `install_openwrt.sh`、`install_linux.sh`、`DEPLOY.md`。
* 当前仓库同时存在两条技术路线：
* `remote/extractor/*`：软路由被动抓取 `7777` 流量，提取 token 和快照，推送到云端 relay。
* `remote/noconfig/hijack/*`：热点期 DNS + HTTPS MITM 改写热更 `NetConf`，再配合 ECS 侧 `tcp_proxy.py` / `ecs_run.py` 实现“无配置”接入。
* `package_extractor.py` 已支持 `--relay-url`、`--write-relay-config`，并且已经预留 `--with-vpn` 分支，说明“迁移到别的网络承载设备”本来就在设计范围内。
* 当前 noconfig 多用户后台已经存在，入口是 `remote/noconfig/main.py` / `remote/noconfig/app.py`，并且和 `remote/relay/static/index.html` 组成管理页。
* 当前“和电脑热点效果一样”的严格含义，更接近 `remote/noconfig/hijack/run_hijack.py` 这条链路，而不只是 `extractor` 被动抓包。

## Assumptions (temporary)

* 用户说的“软路由”优先指 OpenWrt / iStoreOS / x86 Linux 软路由，而不是只限某个封闭厂商固件。
* 用户更看重“手机连上软路由后，体验和现在连电脑热点一样”，而不是单纯“能采集到数据”。
* 用户愿意接受“提高代码获取门槛”而不是“理论上绝对不可提取代码”，因为设备落到别人手里且对方有 root 权限时，纯软件方案无法做到绝对保密。
* 用户当前倾向于把“稳定一键安装软路由版”和“代码保护增强”一起做，而不是拆成两个阶段。
* 用户希望软件放到独立文件夹下，能在电脑上直接测试，再迁移/打包到软路由。
* 用户已明确选择“路由器部署包优先”，电脑直测退居第二优先级。

## Open Questions

* (resolved 2026-06-19) 路由器硬件形态 → **OpenWrt 一体机**，目标设备 GL.iNet Beryl AX (GL-MT3000)。理由见 Decision。
* (resolved 2026-06-19) NetEngine patch 是否抽 → **不抽**。grep 确认 setup_mitm.py 无任何 netengine_patch 调用；commit b9bf68c 后已用 NetConf 注入 `_50[5045]=ECS` 替代，netengine_patch.py 是死代码。
* (resolved 2026-06-19) APK 投递方式 → **内置进 ipk**（~30MB），换"一键装包即用"。
* (resolved 2026-06-19) 自签 CA → **每台 postinst 生成**（一行 openssl req），不内置同一份。

## Requirements (evolving)

* 盘点本地端当前无配置模式所需服务，并拆分哪些必须留在本地、哪些可放云端。
* 评估是否能打成单软件/单包，支持 OpenWrt 与常见 Linux 软路由。
* 评估是否能支持一键启动、开机自启、最少人工配置。
* 评估迁移后是否能做到“用户连接软路由后，效果与连接当前电脑热点一致”。
* 单独评估代码保护能力边界，区分“防普通查看”和“防拿到设备后深挖”。
* 软件应放在独立文件夹/独立工程目录中，不与现有运行目录强耦合。
* 该独立目录下的程序应支持先在 Windows 电脑本地直接测试，再生成软路由部署物。
* 路由器部署包应作为第一优先交付物，电脑直测入口作为辅助能力保留。
* 需要给出推荐购买的路由器型号/类型，并说明为什么适合本项目。

## Acceptance Criteria (evolving)

* [ ] 明确列出当前电脑热点方案的本地服务清单及职责。
* [ ] 至少给出 2 条可行架构路线，并说明推荐顺序。
* [ ] 说明每条路线在“体验一致性 / 部署复杂度 / 代码保护 / 可维护性”上的取舍。
* [ ] 说明是否适合打包成单软件、单 `ipk`、单镜像或单容器。
* [ ] 明确指出无法承诺的边界，尤其是“别人拿到软路由也看不到代码”的现实上限。
* [ ] 给出独立目录的建议结构，以及“电脑直测”和“软路由打包”的共用代码边界。
* [ ] 给出可购买的硬件建议，至少覆盖一体机、开发板软路由、x86 软路由三类中的主要选项。

## Definition of Done (team quality bar)

* 方案有 repo 证据支撑
* 外部技术选择有文档/资料支撑
* 推荐方案与风险边界写清楚
* 给出后续实现拆分建议

## Out of Scope (explicit)

* 本轮不直接改代码
* 本轮不实际构建路由固件 / 容器镜像 / `ipk`
* 本轮不处理商业授权、法务、合规条款细化

## Technical Approach

**最终决策**：只走路线 B 的最小子集——**setup-period MITM 一刀切**。手机连路由器 WiFi 完成一次热更（NetConf 改写指向 ECS）后，正常使用走 ECS，路由器不再插手 7777 流量。ECS 侧（tcp_proxy / 多用户后台）单独部署，不在本任务交付范围。

### 抽取清单（仅本地 setup-period 部分）

| 文件 | 来源 | 行数 | 说明 |
|---|---|---|---|
| setup_mitm.py | remote/noconfig/hijack/ | 1296 | DNS responder + HTTPS server + manifest 改写主体 |
| netconf_patch.py | 同上 | 525 | XXTEA 解密改 IP，纯离线 |
| manifest_forge.py | 同上 | 334 | manifest 克隆+伪造 |
| game_base.apk | apk/ | ~30MB | 资源源（XXTEA key/SIGN/原始 luac 取自此） |

**不抽**：dns_divert.py（Windows 专属，OpenWrt 用 nftables 替代）、netengine_patch.py（已废弃，commit b9bf68c 后由 NetConf 注入 `_50[5045]=ECS` 替代）、run_hijack.py（重写双模入口）、tcp_proxy / ecs_proxy / ecs_run / app.py / main.py（ECS 侧）。

### 目录结构

```
apps/router_runtime/                 ← 独立工程目录（PRD 第 80 行规划）
├── README.md
├── pyproject.toml                   ← 最小 Python 依赖
├── mahjong_mitm/                    ← Python 包
│   ├── __init__.py
│   ├── __main__.py                  ← `python -m mahjong_mitm` 入口
│   ├── setup_mitm.py
│   ├── netconf_patch.py
│   └── manifest_forge.py
├── assets/
│   └── game_base.apk                ← 内置 APK
├── openwrt/                         ← OpenWrt ipk 打包
│   ├── Makefile                     ← OpenWrt SDK 标准 Makefile
│   ├── files/
│   │   ├── etc/init.d/mahjong-mitm  ← procd 启动脚本
│   │   ├── etc/config/mahjong-mitm  ← uci 配置（ECS IP / 域名）
│   │   └── etc/nftables.d/99-mahjong-mitm.nft  ← DNS 劫持 + 端口重定向
│   ├── postinst                     ← 装包后 openssl 生成自签 CA
│   └── build_ipk.sh                 ← 一键打包
├── pc-dev/                          ← Windows 直测入口（第二优先级）
│   └── run_pc.py                    ← 等同现 run_hijack.py，需管理员
└── tests/
    └── test_netconf_patch.py        ← XXTEA 往返自测
```

### Windows → OpenWrt 关键替换

| Windows 原方案 | OpenWrt 替换 |
|---|---|
| dns_divert.py (WinDivert 拦截硬编码 119.29.29.29/223.5.5.5) | nftables `redirect` 规则把 LAN 段所有 53 流量强制本机响应 |
| Python 内置 DNS responder | 沿用 setup_mitm.py 自带（不改） |
| `python.exe` + 管理员防火墙 | `procd init.d` 服务 + nftables |
| PC 热点（ICS 共享） | OpenWrt 自带 hostapd/dnsmasq |
| 手动放证书 | postinst 自动 `openssl req` 生成自签 CA（游戏 VERIFYPEER=0 不校验） |

### 交付优先级

* 第一：`apps/router_runtime/openwrt/build_ipk.sh` 输出 `mahjong-mitm_<ver>_aarch64_cortex-a53.ipk`
* 第二：`apps/router_runtime/pc-dev/run_pc.py` 在 Windows 上 `python -m mahjong_mitm` 直跑

## Decision (ADR-lite)

**Context**: 用户既要"像现在电脑热点一样的无配置体验"，又想迁移到软路由，还希望代码不可见；2026-06-19 重新定位为"只做 setup-period 那一刀"，不复刻 ECS。

**Decision** (2026-06-19)：
1. **硬件**：OpenWrt 一体机，目标设备 GL.iNet Beryl AX (GL-MT3000)。理由——512MB RAM 余量充足、WiFi 6 双频、官方 OpenWrt 23.05、~¥400 价位允许批量分发。
2. **架构**：路线 B 最小子集。setup-period MITM 留路由器；7777 流量代理 / 多用户后台 / relay 留 ECS。
3. **交付**：单 ipk 包，APK 内置（~30MB），postinst 时 openssl 生成每台独立自签 CA。
4. **形态**：独立目录 `apps/router_runtime/`，pc-dev + openwrt 双模共用 `mahjong_mitm/` 包。

**Consequences**:

* ✅ 路由器只跑 setup-period（mitmproxy 闲置时内存 <100MB），Beryl AX 512MB 余量极宽裕
* ✅ 一台路由器装包即用，体验等同当前 PC 热点
* ✅ ECS 故障与路由器解耦——ECS 挂了用户重新连热点重做一次热更即可恢复
* ⚠️ 代码保护本轮不上混淆/编译/设备绑定（PRD 第 21 行已声明无法承诺绝对不可提取），ipk 内 .py 源码可直接读；后续可加 PyInstaller/Nuitka 阶段
* ⚠️ APK 内置 ipk 体积 ~30MB，OpenWrt 1MB/s 下载约 30s 装包时间

## Research References

* [`research/router-migration-options.md`](research/router-migration-options.md) - 仓库现状与软路由迁移路线对比
* [`research/code-protection-and-packaging.md`](research/code-protection-and-packaging.md) - 打包、编译、混淆与代码保护边界

## Technical Notes

* Repo anchors:
* `remote/extractor/package_extractor.py`
* `remote/extractor/install_openwrt.sh`
* `remote/extractor/install_linux.sh`
* `remote/extractor/vpn/README.md`
* `remote/noconfig/hijack/run_hijack.py`
* `remote/noconfig/hijack/setup_mitm.py`
* `remote/noconfig/hijack/ecs_run.py`
* `remote/noconfig/app.py`
* External references to compare packaging/protection and VPN behavior are recorded in `research/`.
