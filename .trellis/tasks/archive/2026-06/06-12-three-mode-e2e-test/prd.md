# 三模式端到端测试（热点 + VPN + 无配置）

## Goal

验证云端 relay 三模式架构（hotspot:8000 / vpn:8001 / noconfig:8002 + spectator:8003）的端到端数据链路，每种模式各自从手机打牌到云端 `/state` 返回数据，逐一闭环。

## What I already know

* relay 三模式架构代码已就绪（`main.py --mode hotspot/vpn/noconfig`，`core.py` RelayApp）
* 端口分配已修复无冲突：8000(hotspot) / 8001(vpn) / 8002(noconfig relay) / 8003(spectator)
* spectator 子进程生命周期管理已实现（auto-start + 健康检查 + 重启限制 max=5）
* extractor 支持多目标推送（`relay_urls` 列表）
* `config_noconfig.yaml` 已有 handshake_blob + auth_token_12b，但 **srs_sessionid 为空**
* 热点模式之前已跑通过（场景A），VPN 模式 strongSwan 已在云服务器部署过

## Assumptions (temporary)

* 测试顺序：热点 → VPN → 无配置（后者依赖前者提取的凭证）
* 云服务器 ECS 已有基础环境（Python、strongSwan）
* 手机已安装游戏且能正常打牌

## Open Questions

* srs_sessionid 有效期多久？跨局是否有效？（影响无配置模式的可用时长）
* VPN 模式测试是否在云服务器上进行？（本地 Windows 无法跑 strongSwan + tcpdump）

## Requirements

### 模式1：热点模式 (hotspot:8000)

* [ ] PC 开移动热点，手机连热点
* [ ] 启动 `relay --mode hotspot` (8000) + `extractor --mode npcap`
* [ ] 手机打一局牌，extractor 自动提取凭证并注册到 relay
* [ ] `GET /state?token=...` 返回实时牌局数据（phase ≠ idle）
* [ ] 凭证持久化到 `config_hotspot.yaml`

### 模式2：VPN 模式 (vpn:8001)

* [ ] 云服务器 strongSwan + relay(8001) + extractor(tcpdump -i any) 已部署
* [ ] 手机配置 IPSec IKEv2 VPN，连上后打牌
* [ ] 云端 extractor 嗅探 VPN 接口流量，POST /push 到 relay:8001
* [ ] `GET /state?token=...` 返回实时牌局数据
* [ ] 凭证持久化到 `config_vpn.yaml`

### 模式3：无配置模式 (noconfig:8002)

* [ ] 前置：通过模式1或2已提取 srs_sessionid 并注册到 relay
* [ ] 启动 `relay --mode noconfig` (8002)，spectator 子进程自动启动（端口 8003）
* [ ] spectator 用 srs_sessionid 直连游戏服务器，完成握手
* [ ] `POST /register-room` 通知 spectator 旁观指定房间
* [ ] spectator 推送回放数据到 relay:8002
* [ ] `GET /state?token=...` 返回旁观数据

### 跨模式验证

* [ ] `python remote/relay/main.py --all` 三模式同时启动无端口冲突
* [ ] extractor 多目标推送：同时推送到 hotspot:8000 + vpn:8001

## Acceptance Criteria

* [ ] 热点模式：手机连热点打牌 → `/state` 返回实时数据
* [ ] VPN 模式：手机连 VPN 打牌 → `/state` 返回实时数据
* [ ] 无配置模式：spectator 直连游戏服务器 → `/state` 返回旁观数据
* [ ] `--all` 启动三模式无冲突

## Definition of Done

* 每种模式有测试步骤文档（含启动命令、验证方法、排查指南）
* 发现的 bug 已修复并提交
* spec 更新（如端口映射、部署拓扑等新发现）

## Out of Scope

* Docker 化（后续任务）
* 自动化 CI 测试（需真实手机 + 游戏，无法 CI）
* 移动端 App 开发

## Technical Notes

* 端口映射：hotspot=8000, vpn=8001, noconfig=8002, spectator=8003
* extractor config: `relay_urls` 支持列表，向后兼容 `relay_url`
* noconfig 模式 spectator auto-start 在 uvicorn startup event 触发
* VPN 需要 UDP 500 + 4500 安全组放行
* Npcap 需管理员权限安装（Windows 热点模式）
