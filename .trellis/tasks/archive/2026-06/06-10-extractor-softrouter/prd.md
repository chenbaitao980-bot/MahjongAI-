# extractor 软路由常开部署 (OpenWRT + x86 Linux)

## Goal

把 extractor 部署到软路由上常开运行，使手机连正常 WiFi（经过软路由）即可被动抓取游戏流量、推送到**云服务器上的 relay**——无需电脑开机、无需手机连临时热点。提供 OpenWRT 与 x86 Linux 两套安装方式 + 安装文档。

## 关键发现 / 已解决

* **依赖解耦（已提交 69769e1）**：`battle/__init__.py` 顶层 import BattleService → 连带把 cv2/numpy 拉进 extractor 链，软路由装不动。已改 PEP 562 懒加载，extractor 链 heavy deps = **NONE**，软路由可行。
* **extractor 运行时最小模块集**（实测）：
  `remote/extractor/` + `stable/{__init__,protocol,tracker,mapping}.py` + `battle/{__init__,state}.py`(不含 service.py) + `game/`(整个, 无 cv2) + `utils/{__init__,paths}.py`。
* **抓包模式**：Linux/OpenWRT 走 `TcpdumpCaptureAdapter`（tcpdump subprocess + PcapParser），非 scapy/Npcap。
* **网卡**：路由上手机流量走 LAN 桥 `br-lan`（OpenWRT）；x86 旁路由视部署而定。`--interface` 指定。

## Decisions (用户已选)

* **两套都做**：OpenWRT(opkg+procd 常驻) 与 x86 Linux(pip+systemd 常驻) 各一套安装方式 + 安装说明。
* **relay 在云服务器**：extractor config `relay_url` 指向公网 relay；附 relay 云端部署指引。
* **主/旁路由不确定**：部署后用抓包自检脚本验证"手机→47.96.0.227:7777 是否可见"。

## Requirements

* [ ] `remote/extractor/package_extractor.py`（开发机跑，跨平台）：把最小模块集打包成 `mahjong-extractor-bundle.tar.gz`，含 install 脚本与服务文件。排除 battle/service.py、vision/、ui/、.venv 等。
* [ ] `remote/extractor/install_linux.sh`：x86 Linux/Docker —— 检测 python3、pip install requests pyyaml、写 systemd unit、交互填 relay_url/api_token/interface、enable+start。
* [ ] `remote/extractor/install_openwrt.sh`：OpenWRT —— `opkg update && opkg install python3-light python3-yaml python3-requests tcpdump`、装 procd init、交互填配置、enable+start。
* [ ] `remote/extractor/files/mahjong-extractor.service`（systemd）+ `remote/extractor/files/mahjong-extractor.init`（procd）。
* [ ] `remote/extractor/selfcheck_capture.sh`：在指定 iface 上 tcpdump N 秒过滤 port 7777，报告是否看到 `手机IP → 游戏服务器:7777`，解决主/旁路由不确定。
* [ ] `remote/extractor/DEPLOY.md`：两套安装 step-by-step + 云端 relay 部署 + 自检 + 排错（抓不到包→换 iface/确认旁路由生效）。

## Acceptance Criteria

* [ ] `package_extractor.py` 产出 tar.gz，解包后目录可独立 `python -m`/`python main.py` 运行（不依赖仓库其它部分）。
* [ ] bundle 内 `python -c "import"` extractor 链不报缺模块、不拉 cv2/numpy。
* [ ] 两套 install 脚本语法正确（`bash -n` / `sh -n`），服务文件字段合法。
* [ ] selfcheck 在有/无流量两种情况下给出明确 PASS/WARN 结论。

## Out of Scope

* 修复 R1/R2/R3（独立任务）。
* 真实远程登录某台具体路由/云服务器执行安装（提供脚本+文档，用户自行在其设备执行）。
* Windows 路径（已由 run_remote.bat 覆盖）。

## Technical Notes

* extractor 入口 `remote/extractor/main.py --mode tcpdump --interface br-lan --config config.yaml`。
* config.yaml: `relay_url`(云), `api_token`(与云 relay 一致), `game_port: 7777`。
* OpenWRT 现代版(21.02+)含 Python 3.9+，3.6 兼容性担忧基本过时，目标 3.7+。
* spec: `.trellis/spec/backend/remote-access.md` §4/§5/§7。
