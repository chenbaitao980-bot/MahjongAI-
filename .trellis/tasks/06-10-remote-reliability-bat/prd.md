# remote 服务可靠性检查 + 一键测试 bat

## Goal

为上个任务交付的 `remote/`（extractor 提取本地登录凭证 + relay 云端按凭证拉取对战数据）做一次可靠性检查，并交付一个 Windows 一键 bat：自动跑测试、把日志落盘，最后明确告诉用户「在哪启动、怎么测」。

## 实际部署拓扑（用户确认 — 全本机 + 电脑模拟路由器）

```
手机登录游戏 ──Wi-Fi──▶ 电脑(Windows 移动热点/ICS 共享网络) ──▶ 互联网→游戏服务器
                              │  手机流量经过电脑网卡
                              ├─ extractor（本机）Npcap/scapy 嗅探共享网卡 → 提取凭证 → POST /register → 127.0.0.1 relay
                              └─ relay（本机 localhost:8000）用凭证 GET /state 查数据
```

* **relay 与 extractor 同机**：`relay_url` 应为 `http://127.0.0.1:8000`（当前 config 仍是占位符 `your-relay-server`，需提示用户改成 localhost）。
* **电脑必须先"变成路由器"**：开 Windows 移动热点或 ICS，手机连这个热点，游戏流量才会过电脑网卡被嗅探。
* **关键易错点**：extractor 嗅探的网卡必须是"承载手机流量的共享适配器"，不是 WAN/本地以太网口。
* 「场景B（GameClient 主动连云端）」在此全本机拓扑下基本用不到——主路径是场景A（被动嗅探 + push）。

## What I already know

* `remote/extractor/`：被动嗅探 port 7777（Windows=Npcap/scapy，Linux/软路由=tcpdump），提取 `handshake_blob`(0x0001) + `auth_token_12b`(0x0006 payload[4:16])，POST `/register` 一次，之后每次状态变化 POST `/push`。
* `remote/relay/`：FastAPI（`/register` `/push` `/state`）。extractor 在线走 push；超过 `PUSH_TIMEOUT=60s` 无 push → relay 用 `GameClient` 主动 TCP 连游戏服务器（场景B，外出打牌）。
* `test_remote.py` 已存在，13 个用例（StateStore 4 + TokenExtractor 4 + RelayAPI 5），最近一次 `logs/test_remote_20260610_075303.log` **13/13 全通过**。日志已落盘到 `logs/test_remote_<ts>.log`。
* `start.bat` 已是成熟模板（检查 Python → venv → pip → 启动），可复用其风格。
* spec：`.trellis/spec/backend/remote-access.md` 是该子系统的架构契约。

## Reliability Findings（静态审查）

| # | 严重度 | 问题 | 证据 |
|---|---|---|---|
| R1 | 🔴 高 | **凭证不持久化**：`/register` 把凭证存进内存 `_cfg`（app.py:131），relay 进程重启即丢失，场景B 失效直到 extractor 重新注册。但 spec §6 声称「重启 extractor 也不再重新注册（relay 已有存储）」——契约与实现矛盾。 | app.py:131-134；remote-access.md §6 |
| R2 | 🟡 中 | **事件循环获取脆弱**：`_ensure_game_client_running` 在 async `/state` 内用 `asyncio.get_event_loop()`（app.py:98），Py3.10+ 无运行 loop 时弃用；spec §4 也标注为已知坑。 | app.py:98-102 |
| R3 | 🟡 中 | **GameClient 启停无锁 + 访问私有 `_running`**：全局 `_game_client` 在并发 `/state` 下可能重复创建（app.py:76-99）。 | app.py:61-103 |
| R4 | 🟡 中 | **缺健康可观测性**：没有端点/脚本能一眼确认「extractor 在线?relay 收到数据?GameClient 连上?」——用户的核心诉求"只要在玩就能拿到数据"无法自检。 | 无 health 端点 |
| R5 | 🟢 低 | **test 覆盖只到本地回环**：未验证真实云端 relay 可达、游戏服务器 7777 连通、Windows 抓包依赖（Npcap/scapy）是否就绪。 | test_remote.py |

## Decisions (ADR-lite)

* **bat 范围 = 测试 + 在线诊断**（用户选）：在 `test_remote.py` 之上增加 `diagnose_remote.py`，覆盖 R4/R5 盲区。
* **可靠性问题 = 仅报告，单独建任务**（用户选）：R1/R2/R3 不在本任务修，已通过 task chip 转出独立任务。

## Requirements (final)

* [ ] 新增 `diagnose_remote.py`：本机链路诊断（适配「全本机 + 模拟路由器」拓扑）—
  ① relay `/state` 可达性（读 extractor/config.yaml 的 relay_url；占位符或非 localhost → WARN 并提示应为 127.0.0.1）
  ② Windows 抓包依赖 scapy + Npcap 驱动是否就绪
  ③ relay 依赖 fastapi/uvicorn/pyyaml 就绪
  ④ **路由器模拟自检**：枚举本机网卡，检测是否存在已启用的共享/热点适配器（IP 转发开启迹象），提示 extractor 该嗅探哪张网卡
  ⑤ 游戏服务器 `game_server_ip:7777` TCP 连通（读 relay/config.yaml；本机拓扑下为参考项）。
  日志写 `logs/diagnose_remote_<ts>.log`。
* [ ] 新增 `test_remote.bat`（一键）：检查 Python → 确保依赖 → 跑 `test_remote.py` → 跑 `diagnose_remote.py` → 结尾打印两份日志路径与 PASS/FAIL 汇总。
* [ ] 交付说明：启动位置（项目根双击 `test_remote.bat`）+ 测试方法（命令行 `python test_remote.py` / `python diagnose_remote.py`）。

## Out of Scope

* 修复 R1~R3（转独立任务）。
* 真实部署 relay 到云服务器（仅可达性验证）。
* 改动 stable/ 协议层。

## Technical Notes

* 已读：test_remote.py、remote/relay/{main,app,game_client,state_store}.py、remote/extractor/main.py、start.bat、spec/backend/remote-access.md。
* bat 可复用 start.bat 的 venv/依赖检查骨架，但入口改为 `python test_remote.py`。
