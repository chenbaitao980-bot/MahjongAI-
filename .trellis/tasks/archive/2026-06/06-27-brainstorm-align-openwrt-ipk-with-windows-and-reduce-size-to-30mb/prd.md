# brainstorm: align openwrt ipk with windows and reduce size to 30mb

## Goal

让 OpenWrt 软路由版 ipk 与 Windows 托盘版在 MITM 热更注入逻辑上保持行为一致，
同时把打出来的 `.ipk` 包从当前 **83 MB 降到约 30 MB 左右**。

## What I already know

- 当前 `interface/openwrt/dist/mahjong-mitm_*.ipk` 大小为 **83 MB**，几乎全部来自
  `interface/assets/game_base.apk`（约 85 MB）。
- Windows 托盘版 (`interface/windows/`) 与 OpenWrt ipk (`interface/openwrt/`)
  **共享同一套 Python 内核** `interface/mahjong_mitm/`：
  - `setup_mitm.py` — HTTPS MITM + DNS + manifest 回源/patch
  - `netconf_patch.py` — NetConf.luac 解密/改写/重加密
  - `manifest_forge.py` — project.manifest 克隆/改写
- 两者差异主要在平台封装：
  - Windows：托盘 UI、UAC 自提权、移动热点、WinDivert DNS 拦截、计划任务自启、
    `kill_port_conflicts`。
  - OpenWrt：procd init.d 服务、uci 配置、nftables DNS redirect、postinst 自签证书。
- 当前 `interface/mahjong_mitm/netconf_patch.py` 与 `remote/noconfig/hijack/netconf_patch.py`
  完全一致，采用 **ECS 单点降级形态**（替换真服 IP、注入 `LOCAL_TCP_LIST_50[5045]`、
  金币游服改单点 ECS）。
- `interface/mahjong_mitm/setup_mitm.py` 默认 `MANIFEST_URL_MODE_ECS`，而 Windows
  `windows/core.py` 显式传 `MANIFEST_URL_MODE_LOCAL`。
- 要从 83 MB 降到 30 MB，必须**不再打包完整 APK**，改打包构建期从 APK 提取出的
  最小资产（NetConf.luac、project.manifest 等），或运行时去指定 URL 拉取。

## Assumptions (temporary)

- “和 Windows 保持一致”主要指 MITM 注入逻辑/行为一致，而非把 Windows 的托盘/热点/
  WinDivert 功能搬到 OpenWrt。
- 30 MB 目标可以通过剥离完整 APK、只保留 patch 所需的最小资产达成。
- 构建机器（打包 ipk 时）仍能访问完整 `game_base.apk` 以做资产提取。

## Open Questions

全部已解决：
1. ✅ Path Y vs ECS 单点 → 废弃 Path Y，保持 ECS 单点（与 Windows 一致）。
2. ✅ manifest_url_mode → 改为 `LOCAL`（和 Windows 一致）。
3. ✅ 减包方案 → 预提取 assets（构建期从 APK 提取 NetConf.luac + project.manifest）。
4. ✅ watchdog → 加轻量健康检查（定时 probe /healthz，失败自动 restart）。

## Requirements (evolving)

- [x] Path Y 废弃，保持 ECS 单点降级形态（已与 Windows 一致）。
- [x] OpenWrt `manifest_url_mode` 改为 `LOCAL`（和 Windows 一致）。
- [x] 减包方案：预提取 assets（构建期从 APK 提取 NetConf.luac + project.manifest，ipk 不带完整 APK）。
- [ ] 修改 `setup_mitm.py` / `netconf_patch.py` / `manifest_forge.py` 支持从独立文件加载（无 APK 依赖）。
- [ ] 修改 `build_ipk.sh` / `Makefile`：去掉 APK，加入预提取 assets。
- [ ] 修改 `init.d`：传 `MANIFEST_URL_MODE_LOCAL`。
- [ ] 修改 `uci config`：ECS IP 统一为 `8.136.32.137`。
- [x] 加轻量 watchdog：定时 probe /healthz，失败自动 restart 服务（和 Windows watchdog 逻辑对齐）。
- [ ] 保留现有 OpenWrt 部署/使用方式（procd 服务 + uci 配置 + nftables DNS 劫持）。

## Acceptance Criteria (evolving)

- [ ] `sh interface/openwrt/build_ipk.sh` 产物 ≤ 30 MB。
- [ ] 安装后 `/etc/init.d/mahjong-mitm restart` 能正常启动 MITM 服务。
- [ ] 手机连 OpenWrt WiFi 开游戏可触发 NetConf 注入（日志出现 NetConf.luac 下发）。
- [ ] 手机切 4G 后仍能通过 ECS 读牌。

## Definition of Done

- 代码改动通过 `python -m mahjong_mitm --selftest` 与 `python -m pytest tests/`。
- OpenWrt 打包/安装流程文档更新。
- 不引入新的安全漏洞（证书生成、文件路径、命令注入等）。

## Out of Scope (explicit)

- 把 Windows 托盘 UI / 移动热点 / WinDivert 搬到 OpenWrt。
- 重写 ECS 端 tcp_proxy / relay。
- 代码混淆 / 反编译保护。

## Spec Conflicts

⚠️ **已解决** — 用户确认 Path Y 已废弃，本次任务以当前代码实际状态（ECS 单点降级形态）为准。

- **冲突规范**：`.trellis/spec/backend/remote-access.md` §17/18 仍记录 Path Y（保留真服兜底 + NetEngine patch），但代码和 Windows 实际运行形态已回滚为 ECS 单点。
- **Resolution**：用户明确"Path Y 已经是废弃了的规范，保持和 Windows 一致"。代码即 truth，spec 中的 Path Y 章节已过时，需后续单独更新 spec（不在本次任务内）。

## Technical Notes

- 当前打包脚本：`interface/openwrt/build_ipk.sh`、`interface/openwrt/Makefile`。
- 关键资产文件：
  - `assets/game_base.apk`（85 MB，大包罪魁）
  - 实际运行时仅读取其中 `assets/src/app/Config/NetConf.luac`、
    `assets/res/GameHotUpdate3/Lobby/project_10001.manifest`、
    以及可选的 `assets/src/app/hotupdate/lobby/ResChecker.luac` /
    `assets/src/app/hotupdate/lobby/ResEnsure.luac`。
- 减小体积的可行路径：
  1. 构建期从 APK 提取上述 2~4 个文件，ipk 不再带完整 APK。
  2. 修改 `netconf_patch.py` / `manifest_forge.py` 支持直接从提取后的文件/目录加载。
  3. 保持 `--apk` 参数兼容，便于 PC 开发与回退。
