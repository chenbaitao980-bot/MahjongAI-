# Directory Structure

> How backend code is organized in this project.

---

## Overview

<!--
Document your project's backend directory structure here.

Questions to answer:
- How are modules/packages organized?
- Where does business logic live?
- Where are API endpoints defined?
- How are utilities and helpers organized?
-->

(To be filled by the team)

---

## Directory Layout

```
MahjongAI/
├── remote/                         # 云端远程访问子项目
│   ├── hotspot/                    # 热点模式（独立包，已稳定）
│   │   ├── __init__.py
│   │   ├── app.py                  # FastAPI app（仅热点路由），configure()
│   │   └── main.py                 # 入口，default port 8000
│   ├── vpn/                        # VPN模式（独立包）
│   │   ├── __init__.py
│   │   ├── app.py                  # FastAPI app + /vpn-setup /ca.crt /mahjong-vpn.p12
│   │   └── main.py                 # 入口，default port 8001
│   ├── noconfig/                   # 无配置模式（独立包）
│   │   ├── __init__.py
│   │   ├── app.py                  # FastAPI app + spectator 子进程管理
│   │   └── main.py                 # 入口，default port 8002
│   ├── relay/                      # 多模式兼容入口（勿删）
│   │   ├── main.py                 # --mode hotspot/vpn/noconfig/--all
│   │   ├── core.py                 # RelayApp 类（--all 子进程用）
│   │   ├── app.py                  # 旧混合 app（向后兼容，不再主用）
│   │   ├── state_store.py          # StateStore（三模式共用）
│   │   ├── decoder.py              # 游戏数据解码
│   │   ├── game_client.py          # GameClient（已知不可行，保留）
│   │   └── static/                 # 前端静态文件
│   ├── srs_spectator/              # SRS旁观协议（不含 relay 逻辑）
│   │   ├── main.py                 # spectator 服务入口（由 noconfig 子进程启动）
│   │   ├── client.py               # SRS TCP 客户端
│   │   ├── handshake.py            # SRS 握手流程
│   │   └── ...
│   └── extractor/                  # 抓包工具
│       ├── main.py                 # extractor 入口
│       ├── capture.py              # npcap/tcpdump 捕获
│       ├── uploader.py             # POST /push 上传
│       └── vpn/                    # VPN 配置辅助
├── battle/                         # 牌局分析
├── game/                           # 游戏逻辑（shanten/ukeire/LLM）
├── stable/                         # 稳定模式（npcap本地）
├── ui/                             # PyQt6 界面
├── vision/                         # 视觉识别
└── main.py                         # 本地 app 入口
```

---

## Module Organization

**`remote/` 子项目规则**（详见 `spec/backend/remote-access.md` 模块化章节）：

- 新模式 = 新独立包（`remote/<mode>/`），不往现有包塞逻辑
- 每个包有自己的 `app.py`（FastAPI）+ `main.py`（uvicorn 入口）
- `state_store.py` 和 `decoder.py` 放在 `remote/relay/`，所有模式共享

**本地 app 规则**：
- 界面层 → `ui/`；AI 分析层 → `game/`；视觉 → `vision/`；数据包解析 → `stable/`

---

## Naming Conventions

| 类型 | 规范 | 示例 |
|------|------|------|
| 模块包 | 小写，无下划线 | `remote/hotspot/`, `remote/vpn/` |
| Python 文件 | snake_case | `state_store.py`, `hand_region_module.py` |
| 类名 | PascalCase | `RelayApp`, `StateStore`, `PacketStateTracker` |
| 全局私有变量 | `_snake_case` | `_cfg`, `_state_store` |
| 日志 logger | `"remote.<module>.<file>"` | `"remote.hotspot.app"` |
| 配置文件 | `config_<mode>.yaml` | `config_hotspot.yaml`, `config_vpn.yaml` |

---

## Examples

- **正确的模式独立包**：`remote/hotspot/app.py` — 热点专属路由 + `configure()` 注入模式
- **正确的多模式兼容**：`remote/relay/main.py` — `--all` 多进程启动
- **共享组件**：`remote/relay/state_store.py` — 三模式 import，不复制
