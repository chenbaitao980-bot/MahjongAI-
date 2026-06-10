# extractor 软路由常开部署指南

让 extractor 跑在软路由上常开，手机连正常 WiFi（经过软路由）即可被动抓取游戏流量、
推送到**云服务器上的 relay**。无需电脑开机、无需手机连临时热点。

```
手机(正常连 WiFi) ──▶ 软路由[extractor 常驻] ──▶ 互联网 → 游戏服务器:7777
                            │ tcpdump 被动嗅探 br-lan
                            └ 提取凭证 + 推 snapshot ──HTTP──▶ 云服务器[relay] ──/state──▶ 你/AI
```

> 前提（物理铁律）：**手机流量必须经过这台软路由**，extractor 才抓得到。
> 软路由是主路由 → 天然满足；是旁路由 → 需确认网关指向它。部署后用自检脚本验证。

---

## 0. 先在开发机打包

在本仓库根目录（有 Python 即可，Windows/Linux 都行）：

```bash
python remote/extractor/package_extractor.py
# 产出 mahjong-extractor-bundle.tar.gz
```

bundle 已含 extractor 运行所需最小模块集（**不含 cv2/numpy/PyQt**）+ 安装脚本。

把它传到路由器：

```bash
scp mahjong-extractor-bundle.tar.gz root@<路由器IP>:/tmp/
```

---

## 1. 云服务器上先把 relay 跑起来

extractor 要往云 relay 推数据，所以先部署 relay（一台有公网 IP 的云主机）：

```bash
# 云服务器上
git clone <repo> mahjong && cd mahjong            # 或只传 remote/relay/ + stable/ + game/ + battle/ + utils/
pip install fastapi uvicorn pyyaml requests
# 编辑 remote/relay/config.yaml: 设一个 api_token（记住它，后面 extractor 要填同一个）
python remote/relay/main.py --host 0.0.0.0 --port 8000
# 建议用 systemd/pm2/screen 常驻；并放行安全组 8000 端口
```

记下：`relay_url = http://<云服务器公网IP>:8000`，以及 `api_token`。

> 安全：8000 暴露公网时 api_token 即唯一凭证，务必用强随机值；
> 如可能，加 Nginx + HTTPS 或限制来源 IP。

---

## 2A. 安装到 OpenWRT / iStoreOS

```bash
# 路由器 SSH 上
cd /tmp && tar xzf mahjong-extractor-bundle.tar.gz && cd mahjong-extractor
sh install_openwrt.sh
```

脚本会：`opkg` 装 `python3-light python3-yaml python3-requests tcpdump` → 交互填
`relay_url / api_token / interface(默认 br-lan) / 安装目录` → 装 procd 服务
`/etc/init.d/mahjong-extractor` → enable + start。

常用：
```bash
/etc/init.d/mahjong-extractor status
logread -e mahjong-extractor -f
```

## 2B. 安装到 x86 Linux 软路由 / NAS / Docker 宿主

```bash
sudo tar xzf mahjong-extractor-bundle.tar.gz -C /opt && cd /opt/mahjong-extractor
sudo sh install_linux.sh
```

脚本会：`pip` 装 `requests pyyaml`（确认有 tcpdump）→ 交互填配置 → 装 systemd 服务
`mahjong-extractor.service` → enable + start。

常用：
```bash
systemctl status mahjong-extractor
journalctl -u mahjong-extractor -f
```

---

## 3. 部署后自检（重要：验证流量真的经过本机）

主/旁路由是否生效，用自检脚本确认（手机进游戏、摸打几张牌时跑）：

```bash
sh /opt/mahjong-extractor/selfcheck_capture.sh br-lan 12
#   OpenWRT: sh /root/mahjong-extractor/selfcheck_capture.sh br-lan 12
```

- **PASS**：抓到 `手机IP → 游戏服务器:7777` → 部署正确，服务可放心常驻。
- **WARN**：没抓到 → 多半 interface 选错或旁路由没生效，按脚本提示换网卡/查网关。

---

## 4. 确认数据到达云端

手机进游戏后，访问云 relay：
```
http://<云服务器IP>:8000/state?token=<api_token>
```
看到 `phase` 从 `idle` 变成牌局数据即成功。

---

## 排错速查

| 现象 | 排查 |
|------|------|
| 自检抓不到包 | interface 选错(试 br-lan/eth0/eth1) 或旁路由未生效(网关没指向本机) |
| /state 一直 idle | extractor 没抓到包(先过自检) 或没推到 relay(查日志 relay_url/api_token) |
| 推送 401 | extractor 与 relay 的 api_token 不一致 |
| python3 缺失(OpenWRT) | 精简固件无 python3，需换带 python3 的固件或用 x86 方案 |
| 抓到包但 phase 不变 | 进游戏要从“新的一局”开始，开局发牌事件需被抓到 |

> token 注册只在登录握手那一刻发生，extractor 必须在你**登录游戏时**已在抓包。
