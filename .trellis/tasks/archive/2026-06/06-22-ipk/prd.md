# 软路由环境探针 ipk — 验证功能支持性

## Goal

在 `apps/router_runtime/openwrt/dist/` 下生成一个极小的 `mahjong-probe_<ver>_all.ipk`，
安装到软路由后自动探测路由器是否满足正式包（mahjong-mitm）所需的全部运行条件，
输出每项检测的 pass/fail 结论。功能代码全部抽走，只保留环境探针逻辑。

## What I already know

* 正式包依赖：`python3-light`、`python3-urllib`、`python3-openssl`、`kmod-nft-nat`
* nftables 规则通过 `fw4 reload` 加载，需要 fw4 + nftables 内核模块
* Python 需要监听 443（HTTPS MITM）和 5353（DNS 响应器）
* procd 管理服务，`/etc/init.d/` 格式
* `postinst` 调用 `openssl req` 生成自签证书
* 现有 `build_ipk.sh` 打包方式：tar(debian-binary + control.tar.gz + data.tar.gz)，无需 SDK
* 目标设备 GL.iNet Beryl AX (GL-MT3000)，OpenWrt 23.05，aarch64

## 探针检测项（初稿）

| # | 检测项 | 方法 |
|---|--------|------|
| 1 | python3 可用 & 版本 ≥ 3.8 | `python3 --version` |
| 2 | python3-openssl 可导入 | `python3 -c "import ssl"` |
| 3 | python3-urllib 可导入 | `python3 -c "import urllib.request"` |
| 4 | openssl CLI 可用 | `openssl version` |
| 5 | fw4 / nftables 可用 | `fw4 -v` 或 `nft --version` |
| 6 | 端口 443 可绑定 | `socket.bind(('0.0.0.0', 443))` |
| 7 | 端口 5353 可绑定 | `socket.bind(('0.0.0.0', 5353))` |
| 8 | procd 在运行 | `/etc/init.d/` + `USE_PROCD=1` 可用 |
| 9 | 磁盘余量 ≥ 50 MB | `df /` |
| 10 | 内存余量 ≥ 64 MB | `free` |

## Assumptions (temporary)

* 用户只需安装一次，探针跑完即可，不需要常驻
* 探针输出对象是开发者（陈柏涛），不是最终用户，日志可以是英文技术格式
* 探针结果不需要写入文件，打印到 stdout/logread 即可

## Open Questions

（全部已解决）

## Requirements

* 生成 `apps/router_runtime/openwrt/dist/mahjong-probe_1.0.0_all.ipk`
* 安装后 postinst 立即跑探针并打印每项 pass/fail，然后退出（不常驻）
* 全部 10 项通过才输出成功标记 `[PROBE] ALL SYSTEMS GO`；任一 FAIL 输出 `[PROBE] NOT READY`
* 探针脚本安装到 `/usr/bin/mahjong-probe`，可随时 SSH 重跑
* 复用现有打包逻辑，单独建 `build_probe_ipk.sh`
* 探针脚本体积极小（< 10 KB），无需 APK、无需 mahjong_mitm 包

## Acceptance Criteria

* [ ] `dist/mahjong-probe_1.0.0_all.ipk` 可在 Git Bash / Windows 用 `sh build_probe_ipk.sh` 生成
* [ ] 安装到路由器后 `logread | grep PROBE` 能看到每项 PASS/FAIL
* [ ] 全 10 项通过时末行输出 `[PROBE] ALL SYSTEMS GO`
* [ ] 任一项失败时末行输出 `[PROBE] NOT READY`
* [ ] `/usr/bin/mahjong-probe` 可 SSH 进去手动重跑

## Definition of Done

* build 脚本可在 Windows Git Bash 执行
* 探针覆盖上述 10 项检测
* 不引入任何正式业务逻辑（功能完全抽走）

## Out of Scope

* 不测试 7777 流量代理（ECS 侧）
* 不测试热更 MITM 完整链路
* 不做可视化 dashboard
* 不做常驻监控

## Decision (ADR-lite)

**Context**: 需要一个轻量 ipk 在正式部署前验证路由器环境。
**Decision**:
- 结果呈现：只打日志（logread），不开 HTTP 端口
- 成功标准：全部 10 项通过才输出 `ALL SYSTEMS GO`，任一失败输出 `NOT READY`
- 重跑方式：`/usr/bin/mahjong-probe` 留存，可随时 SSH 手动触发
**Consequences**: 最小侵入，不占端口，不常驻；重跑需 SSH 登录

## Technical Notes

* `build_ipk.sh` 参考：`apps/router_runtime/openwrt/build_ipk.sh`
* 正式包 init.d：`apps/router_runtime/openwrt/files/etc/init.d/mahjong-mitm`
* 正式包 nftables：`apps/router_runtime/openwrt/files/etc/nftables.d/99-mahjong-mitm.nft`
* 端口绑定测试需要 root（443），路由器默认 root 运行 opkg postinst，ok
* `kmod-nft-nat` 是内核模块，探针只能间接检查（`nft --version` + `lsmod | grep nft_nat`）
