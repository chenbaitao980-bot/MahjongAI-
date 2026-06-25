# 迁移 noconfig 服务到 172.20.133.250（华纳云 HK）

## Goal

将 noconfig 核心三件套从阿里云 ECS（8.136.37.136）迁移到新服务器（172.20.133.250，华纳云 HK CN2 GIA），
同步更新 interface/ 中写死的 ECS IP 常量，使 Windows 托盘 + OpenWrt IPK 开箱指向新机器。

## What I already know

### 迁移背景

- 此任务是 `06-22-ecs-vultr-tokyo` 的续集：Vultr Tokyo 因无 CN2 路由无法回连真服而弃用
- 新服务器 `172.20.133.250` = 华纳云 HK CN2 GIA（账号不实名）
- 阿里云 `8.136.37.136` **保留不动**，双跑并行验证

### 服务器三件套

| 服务 | 端口 | 文件 |
|------|------|------|
| mahjong-relay-noconfig | 8002 | `remote/noconfig/main.py` |
| mahjong-tcp-proxy | 5748/5749/7777 | `remote/noconfig/hijack/tcp_proxy.py` |
| mahjong-mitm-hotupdate | 53/443 | DNS divert + manifest forge |

### 部署工具（已有）

`scripts/bootstrap_new_server.py` 已支持一键部署任意新服务器：
```bash
python scripts/bootstrap_new_server.py 172.20.133.250 --password 'Ysydxhyz111'
```
其中 `--self-ip` 默认等于 `target_ip`（即 172.20.133.250），
这个值会被写进 NetConf、manifest_url 等——**如果服务器有单独的公网 IP，必须显式传 `--self-ip <公网IP>`**。

### Interface 需更新的 ECS IP 硬编码

两处写死值（sidecar `ecs.txt` 可免重编译覆盖，但 `config.py` 常量控制编译默认值）：

| 文件 | 常量 | 当前值 |
|------|------|--------|
| `interface/windows/config.py:18` | `ECS_IP` | `"8.136.37.136"` |
| `interface/mahjong_mitm/setup_mitm.py:89` | `DEFAULT_ECS_IP` | `"8.136.37.136"` |

- `ECS_IP`（windows/config.py）：Windows 托盘 exe 重编译后默认指向此 IP
- `DEFAULT_ECS_IP`（setup_mitm.py）：`--ecs-ip` 参数的默认值，写进 NetConf.luac + manifest_url
- `ecs.txt` sidecar：exe 同目录放一行 IP 即可覆盖，无需重编译（已有机制）
- OpenWrt IPK（`interface/openwrt/`）：`build_ipk.sh` + Makefile，打包时写入 NetConf，需同步 IP 后重编译

### 前置验收（已知铁律）

部署后第一步必须在 HK 机上：
```bash
python3 -c "import socket;socket.create_connection(('47.96.0.227',7777),8)"
python3 -c "import socket;socket.create_connection(('47.96.101.155',5748),8)"
```
两个都通才证明 CN2 路由可回连真服，才值得往下走手机热更。

## 已确认决策

| 项 | 决定 |
|---|---|
| 新服务器 SSH 地址 | `172.20.133.250`（私网） |
| 新服务器公网 IP（写进 NetConf，手机 4G 直连） | `8.136.32.137` |
| 旧阿里云 ECS | `8.136.37.136`，**保留不动** |
| Windows exe 更新策略 | 重编译（更新 ECS_IP 常量后跑 build_win.bat） |

## Requirements

* [ ] 在新服务器部署三件套（relay + tcp_proxy + mitm-hotupdate）
* [ ] 通过 CN2 连通性验收（47.96.0.227:7777 + 47.96.101.155:5748）
* [ ] 更新 `interface/windows/config.py:18` `ECS_IP = "8.136.32.137"`
* [ ] 更新 `interface/mahjong_mitm/setup_mitm.py:89` `DEFAULT_ECS_IP = "8.136.32.137"`
* [ ] 重编译 Windows exe（`interface/winpack/build_win.bat`）
* [ ] 重编译 OpenWrt IPK（`interface/openwrt/build_ipk.sh`）
* [ ] 双跑并行：阿里云保留，新账号先走新服务器验收

## Acceptance Criteria

* [ ] 新服务器 `curl http://172.20.133.250:8002/` 返回状态 200
* [ ] HK 机 → 47.96.0.227:7777 连通
* [ ] 手机 4G 热更完成后大厅可读牌

## Out of Scope

* 账号分片机制（已在 06-22 PRD 中，本次只完成迁移部署）
* 阿里云服务改动

## Technical Notes

* bootstrap 脚本用 paramiko SSH，无需预装 agent，密码认证直连
* 新服务器如是 Ubuntu/Debian，Python 3.9+ 应已有，pip 包会自动安装
* `interface/tests/test_netconf_patch.py:58` 测试写死 `ecs_ip = "8.136.37.136"` — 是测试专用值，不需更新（它测的是 patch 逻辑，不测 IP 值）
