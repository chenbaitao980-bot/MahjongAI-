# brainstorm: noconfig 本地 MITM 打包成 Windows exe 开箱即用

## Goal

把"无配置模式"的**本地 setup-period MITM**（PC 热点注入：DNS 劫持 + WinDivert 拦硬编码 DNS + HTTPS 443 改写 NetConf）打包成一个 **Windows exe**，复制到任意 Windows 机器即可运行、最少人工配置，作为已打包的 OpenWrt 软路由版（`apps/router_runtime/openwrt/`）的"Windows 兄弟版"。

## What I already know

* "本地部分"= `remote/noconfig/hijack/run_hijack.py` 这条链路，四个动作：
  1. DNS 响应器 (UDP:53) — 把热更域名劫持到 PC
  2. **WinDivert 拦截器** (`dns_divert.py`) — 拦游戏硬编码 DNS（119.29.29.29/223.5.5.5），是 Windows 命门
  3. HTTPS 服务 (TCP:443) — 自签证书 + 伪 manifest + 改过的 NetConf.luac
  4. 前提：PC 已开移动热点(ICS)、管理员权限、`apk/game_base.apk`、`cryptography` 生成证书
* 核心逻辑已抽成包：`apps/router_runtime/mahjong_mitm/`（setup_mitm + netconf_patch + manifest_forge，平台中立）。
* ⚠️ **关键缺口**：上个任务把 `dns_divert.py`（WinDivert）明确"不抽"（OpenWrt 用 nftables 替代）。`pc-dev/run_pc.py` 自带警告"本最小化包不含它"。**Windows exe 必须把 dns_divert 收回包内**，否则游戏走硬编码 DNS 直接绕过。
* 打包惯例已有：`mahjong_ai.spec` + `build.bat`（PyInstaller COLLECT 单文件夹、upx、console=False、datas 内嵌资源）。
* "之前打包过的软路由版本"= `apps/router_runtime/openwrt/` 的 ipk（GL.iNet Beryl AX）。

## Assumptions (temporary)

* 用户要的"任意 Windows 开箱即用"= 不需要装 Python / pip，复制 exe（或一个文件夹）即可跑。
* exe 仍需管理员权限（绑 53/443 + WinDivert 驱动）——这是硬约束，不可绕过，靠 UAC manifest 自动弹提权。
* WinDivert 驱动（pydivert 自带 WinDivert64.sys，微软交叉签名）可被 PyInstaller 收进 binaries，在任意 x64 Windows 加载。
* ECS IP 当前单点（8.136.37.136 / 47.x），多数用户不需要改。
* 用户仍接受"PyInstaller 明文可反编译"作为本轮代码保护下限（与上个任务一致），混淆/Nuitka 留后续。

## Open Questions

* (Q1 resolved 2026-06-23) UX 等级 → **选项 3 托盘全自动版**。开机自启 + 托盘常驻 + 自动开热点 + 自动注入。⚠️ 带来最大技术风险：Windows 移动热点自动化（WinRT NetworkOperatorTetheringManager）。
* (Q2 resolved 2026-06-23) 生命周期 → **常驻 + 幂等注入**。托盘常驻、热点常开、53/443/WinDivert 一直监听；任何手机连进来做热更检查就回改写后的 NetConf，**无需设备去重**（MITM 对每请求回同一份伪 NetConf 天然幂等）。承重墙 = Windows 移动热点"常开+自动拉起"（WinRT，待研究验证）。
* (Q3 resolved 2026-06-23) 配置 → **ECS IP 写死**（放成顶层常量，迁服改一处重编译）；零成本加 sidecar 兜底（旁边有 config 就读，没有用写死值）。host-ip 自动探测 192.168.137.1。
* (Q4 resolved 2026-06-23) 代码保护 → **PyInstaller 明文**。自用、不外发，不做混淆/Nuitka。

## Requirements (evolving)

* 把 `dns_divert.py`（WinDivert）补回 Windows 打包集，与 `mahjong_mitm/` 整合。
* 产出一个 PyInstaller spec + build 脚本，输出可分发的 exe（或单文件夹）。
* 内嵌 `game_base.apk`（~30MB）作为 data。
* 内嵌 `cryptography` 首次运行自动生成自签 CA。
* UAC manifest 自动提权。
* host-ip 自动探测（默认 192.168.137.1 网关），减少必填参数。

## Acceptance Criteria (evolving)

* [ ] exe 在一台**未装 Python** 的 Windows 上双击可运行（自动提权）。
* [ ] WinDivert 驱动随 exe 加载成功，能拦到硬编码 DNS。
* [ ] 手机连该 PC 热点开游戏 → 热更触发 → NetConf 被改写指向 ECS（与现 run_hijack 等效）。
* [ ] 明确"开箱即用"的边界：哪些仍需人工（开热点 / 改 ECS IP）。

## Definition of Done

* 方案有 repo 证据支撑
* WinDivert+PyInstaller 打包可行性有资料/实测支撑
* UX 等级、配置方式、代码保护边界写清楚
* 给出实现拆分建议（spec / 目录 / build 脚本）

## Out of Scope (explicit)

* 本轮不复刻 ECS 侧（tcp_proxy / 多用户后台 / relay）。
* 本轮不改 OpenWrt ipk 路径。
* 本轮不承诺"绝对不可反编译"。

## Spec Conflicts

* （Auto-Context 待扫描 `.trellis/spec/**` 后补；如无冲突删除本节）

## Technical Approach

**形态**：PyInstaller 单文件夹（COLLECT，沿用 `mahjong_ai.spec` 惯例）+ UAC manifest 自动提权 + 系统托盘常驻 + 开机自启（注册表 Run 或启动文件夹）。

**复用而非重造**：核心 MITM 逻辑直接复用已存在的 `apps/router_runtime/mahjong_mitm/`（setup_mitm + netconf_patch + manifest_forge，平台中立）。Windows exe 作为该工程的 `windows/` 子目录，**不另起炉灶**，保持 MITM 内核单一真相源。

**目录（建议）**：
```
apps/router_runtime/
├── mahjong_mitm/         ← 已存在，复用（平台中立 MITM 内核）
├── windows/              ← 本任务新增
│   ├── win_hotspot.py    ← WinRT 移动热点：开/关/常开(PeerlessTimeoutEnabled=0)/看门狗
│   ├── win_dns_divert.py ← 从 remote/noconfig/hijack/dns_divert.py 收回（WinDivert 命门）
│   ├── tray_app.py       ← 托盘 + 编排（开机自启、自动开热点、起 53/443/divert、状态图标）
│   └── __main__.py       ← `python -m windows` 开发入口
├── packaging/
│   ├── mahjong_mitm_win.spec  ← PyInstaller spec（含 WinDivert binaries + APK data + UAC admin）
│   └── build_win.bat          ← 一键打包（纯 ASCII，见 [[feedback_bat_ascii_only]]）
└── assets/game_base.apk  ← 已存在，内嵌进 exe
```

**ECS IP**：写死 **`8.136.37.136`（阿里云，= mahjong_mitm 现有 `DEFAULT_ECS_IP`）**，放成 `windows/` 顶层常量；启动时若同目录有 `ecs.txt` 则覆盖（无副作用兜底）。华纳云 HK 迁服完成后改此常量重编译即可（sidecar 可免重编译）。

**托盘 UI**：`pystray` + `Pillow`（轻量、专做托盘，打包体积远小于复用主项目 PyQt6）。

**承重墙裁决**（详见 research 内联，本轮不另起子代理）：
- 移动热点：WinRT `NetworkOperatorTetheringManager`，`PeerlessTimeoutEnabled=0` 根治空闲关闭 + 看门狗兜底。WiFi-over-WiFi 单网卡可行。弃用 `netsh hostednetwork`。
- WinDivert：pydivert 自带微软签名驱动，PyInstaller `binaries` 收 dll/sys 即可。

## Decision (ADR-lite)

**Context**: 已有 OpenWrt ipk 版（`apps/router_runtime/openwrt/`）；用户要其 Windows exe 兄弟版，任意 Windows 开箱即用、托盘常驻、热点常开、来一台手机注一台。

**Decision** (2026-06-23):
1. 形态 = 托盘全自动 exe（PyInstaller 单文件夹 + UAC admin + 开机自启）。
2. 生命周期 = 常驻 + 幂等注入，热点常开（`PeerlessTimeoutEnabled=0` + 看门狗），无需设备去重。
3. ECS IP 写死（顶层常量 + sidecar 兜底）。
4. 代码保护 = PyInstaller 明文（自用）。
5. 复用 `mahjong_mitm/` 内核，新增 `windows/` 子目录；WinDivert（`dns_divert`）收回包内。

**Consequences**:
* ✅ 与 OpenWrt 版共享 MITM 内核，逻辑改一处两端受益
* ✅ 任意未装 Python 的 Win10/11 x64 复制即跑
* ⚠️ 热点空闲自动关闭靠注册表根治，需管理员（已具备）
* ⚠️ exe 未签名 → SmartScreen 提示（自用可忽略）
* ⚠️ ECS 迁服后 IP 变动需改常量重编译（sidecar 兜底可免）
* ⚠️ 与 spec `remote-access.md:187` 黄金规则有张力（noconfig 改 `remote/noconfig/`），但 `apps/router_runtime/` 独立打包先例已存在，沿用

## Spec Conflicts

* **Tension（非硬冲突）**: [`remote-access.md:187`](.trellis/spec/backend/remote-access.md) "noconfig 专属改 `remote/noconfig/`" vs 本任务落 `apps/router_runtime/windows/`。**Resolution**: 沿用上个任务 `apps/router_runtime/` 独立打包先例（PRD 已声明独立工程目录），仅复用 `dns_divert.py` 源逻辑、不改 `remote/noconfig/` 运行目录。

## Implementation Status (2026-06-23)

**全部三个 PR 已实现并验证**（落 `apps/router_runtime/windows/` + `winpack/`）：

- **PR1 骨架** ✅ `windows/{__init__,config,win_dns_divert,core,__main__}.py`；dns_divert 从 `remote/noconfig/hijack/` 收回；`python -m windows` 源码态入口；复用内核未碰坏（`mahjong_mitm --selftest` ALL PASS）。
- **PR2 热点+托盘** ✅ `windows/{win_hotspot,win_admin,tray_app}.py`；WinRT `NetworkOperatorTetheringManager` 开/关/`PeerlessTimeoutEnabled=0`/看门狗；UAC 自提权 + 开机自启；pystray 托盘 + 状态色 + 文件日志。**承重墙真机验证**：winsdk WinRT 类导入✓、上游 profile(以太网)✓、tethering manager 创建✓、max_client=8✓。
- **PR3 打包** ✅ `winpack/{tray_entry.py,mahjong_mitm_win.spec,build_win.bat}`；PyInstaller 实跑出 `dist/MahjongMITM/`（~175MB）；WinDivert64.dll+sys、winsdk networkoperators/connectivity、pystray._win32、内嵌 APK 全部确认进 bundle；无真实缺失模块。

测试：`tests/{test_win_dns_divert,test_win_admin}.py` + 既有内核测试，**12/12 pass**。

**未做（真机交互手测，需用户在目标 Windows 上完成）**：双击 exe → UAC → 热点真开 → 手机连 → 注入 → 4G 读牌 → 重启自启。清单见 `apps/router_runtime/README.md` "真机验证清单"。运行 UAC 提权托盘会扰动本机网络，无法在开发环境 headless 验。

依赖：`pip install -e .[windows]`（pyproject 已加 windows extra：pydivert/pystray/Pillow/winsdk==1.0.0b10/cryptography）。

## Technical Notes

* Repo anchors:
  * `remote/noconfig/hijack/run_hijack.py` / `dns_divert.py` / `setup_mitm.py`
  * `apps/router_runtime/mahjong_mitm/`、`apps/router_runtime/pc-dev/run_pc.py`
  * `mahjong_ai.spec`、`build.bat`
* 相关记忆：[[hotupdate-mitm-netconf-overlay]]、[[hotupdate-mitm-breakthrough-2026-06-14]]、[[noconfig-4g-handread-chain]]
