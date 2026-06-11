# run_remote.bat 一键拉起真实抓数据链路

## Goal

在现有 `remote/`（extractor 提取本地登录凭证 + relay 按凭证拉对战数据）之上，做一个**真正一键启动**的 launcher：用户双击一个 bat，自动配好配置、开热点、起 relay、起 extractor，并打开一个实时窗口显示抓到的牌局数据——无需手动开多个终端、改配置、记 token。

与已交付的 `test_remote.bat`（测试+体检，不碰真实链路）互补：本任务交付**真实运行**链路。

## 部署拓扑（沿用上一任务结论）

全本机 + 电脑模拟路由器（Windows 移动热点/ICS，网关固定 192.168.137.1）：
```
手机登录游戏 ─Wi-Fi→ 电脑热点 → 互联网→游戏服务器
                  │ 流量过本机网卡
                  ├ extractor 嗅探(需 Npcap+管理员) → POST /register + /push
                  └ relay(127.0.0.1:8000) ← GET /state 取数据
```

## Decisions (用户已选)

* **数据呈现** = 弹窗轮询打印：新开窗口跑 `watch_state.py`，每 2s GET /state，snapshot 变化才刷新打印。
* **热点** = bat 尝试自动开（PowerShell Windows Tethering API），失败则提示手动开，并轮询等待 192.168.137.1 出现。
* **config** = 自动生成并同步：首次跑若 api_token 是占位符则随机生成，写进 relay + extractor 两个 config，并设 extractor `relay_url=http://127.0.0.1:8000`。

## Requirements (final)

* [ ] `run_remote.bat`（项目根，纯 ASCII 英文，避免 cp936 乱码）：
  1. **UAC 自提权**：非管理员则用 PowerShell `Start-Process -Verb RunAs` 重启自身（extractor 抓包需管理员）。
  2. 检查 Python / venv / 依赖（requests pyyaml fastapi uvicorn scapy）。
  3. 调 `python bootstrap_remote_config.py` 生成+同步 config，并回显使用的 api_token。
  4. **开热点**：调 PowerShell 尝试启动 Windows 移动热点；失败打印手动指引。然后轮询 `ipconfig` 直到出现 `192.168.137.1`（最多等 ~60s，超时给警告但继续）。
  5. 新窗口起 relay：`start "relay" python remote\relay\main.py`，轮询 /state 直到就绪。
  6. 新窗口起 extractor：`start "extractor" python remote\extractor\main.py`。
  7. 当前窗口（或新窗口）起 `python watch_state.py` 实时打印牌局。
  8. 退出/关闭提示。
* [ ] `bootstrap_remote_config.py`：幂等读写两个 config.yaml —— api_token 占位符→`secrets.token_hex(12)`；同步到 relay+extractor；extractor relay_url→127.0.0.1:8000；保留其它字段；stdout 打印最终 api_token（脱敏可选，但本地工具可明文方便用户复制）。
* [ ] `watch_state.py`：读 extractor/config.yaml 的 relay_url+api_token，循环 GET /state（间隔 2s），snapshot 变化才打印（带时间戳 + phase + 关键字段）；ConnectionError 优雅重试（relay 还没起来）；Ctrl+C 退出。

## Acceptance Criteria

* [ ] 干净环境双击 `run_remote.bat`：自动提权 → 配置就绪 → relay/extractor 各自起在独立窗口 → watch 窗口开始轮询。
* [ ] 未开热点时给出明确指引并等待；手机连热点登录游戏后，watch 窗口能打印出 snapshot（依赖真实抓包，验收以"链路打通、watch 正常轮询 /state 且 relay 可达"为准）。
* [ ] config 自动生成幂等：重复跑不会覆盖已生成的真 token。
* [ ] 所有 bat 为纯 ASCII；脚本对 cp936 控制台做 utf-8 reconfigure 防护（沿用上个任务模式）。

## Out of Scope

* 修复 R1/R2/R3（独立任务）。
* 自动让手机连热点（系统限制，需用户手动）。
* 改 stable/ 协议层。

## Technical Notes

* 复用 `test_remote.bat` 的 Python/venv/依赖检查骨架与 ASCII 约束。
* relay/extractor 入口：`remote/relay/main.py`（默认 0.0.0.0:8000）、`remote/extractor/main.py`（默认自动选 npcap）。
* 热点 PowerShell：`NetworkOperatorTetheringManager.CreateFromConnectionProfile(...).StartTetheringAsync()`，需活动 internet profile，async 结果用 await 包装，try/catch 回退手动。
* 已读全部 remote/ 源码（见上一任务）。spec: `.trellis/spec/backend/remote-access.md`。
