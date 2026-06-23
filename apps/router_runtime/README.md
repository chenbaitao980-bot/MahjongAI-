# mahjong-mitm — setup-period 热更 MITM（OpenWrt 路由器版）

把仓库 `remote/noconfig/hijack/` 的 **setup-period 一刀** 抽成独立、可打包到 OpenWrt
路由器的最小程序。手机连本路由器 WiFi 开游戏触发一次热更，NetConf 被改写指向 ECS；
之后手机切任意网络走 ECS，**路由器不再插手 7777 游戏流量**。

> ECS 侧（tcp_proxy / 多用户后台 / relay）单独部署，不在本包内。

## 它做什么

1. **DNS 劫持**：把游戏热更域名（gxb-* . hzxuanming.com / imeete.com）解析到本机
2. **HTTPS MITM**：自签证书（游戏 VERIFYPEER=0 不校验）+ 回源真实 manifest + 只改 NetConf 一条
3. **NetConf 改写**：XXTEA 解密 → 把台州 5045 真服 IP 换成 ECS IP → 重加密

链路逆向细节见 `.trellis/tasks/06-18-soft-router-noconfig/` 及原始任务
`06-14-srs-addr-hijack/`。

## 目录

```
mahjong_mitm/        Python 包（setup_mitm + netconf_patch + manifest_forge）
assets/game_base.apk 资源源（XXTEA key/SIGN/原始 luac 取自此；不入库）
openwrt/             ipk 打包（Makefile 留作 SDK 路径 / build_ipk.sh 手工打包）
pc-dev/run_pc.py     Windows 本地直测入口
tests/               XXTEA 往返 + 全链路离线自测
```

## 推荐硬件

**GL.iNet Beryl AX (GL-MT3000)** —— OpenWrt 23.05 官方、512MB RAM（setup-period 负载
绰绰有余）、WiFi 6 双频、口袋大小 USB-C 供电。

## 本地开发 / 测试

```bash
cd apps/router_runtime

# 离线自测（无需热点/手机，验证 manifest/NetConf 改写逻辑）
python -m mahjong_mitm --selftest
python -m pytest tests/ -v

# PC 直测（管理员，PC 已开热点、手机已连）
python pc-dev/run_pc.py --host-ip 192.168.137.1 --ecs-ip 8.136.37.136
```

> PC 上若游戏走硬编码 DNS，需用仓库原版 `remote/noconfig/hijack/run_hijack.py`
> （带 WinDivert）做完整测试；本包 PC 入口主要验证抽取后逻辑无回归。

## Windows 托盘全自动 exe（开箱即用）

OpenWrt ipk 的 Windows 兄弟版：把同一套 `mahjong_mitm/` 内核 + Windows 专属的
WinDivert/移动热点/托盘封装，打成一个**任意 Win10/11 x64 双击即用**的 exe。
代码在 `windows/` 子目录，与 ipk 共享内核（改内核两端同时受益）。

### 它做什么（双击 exe → 全自动）

1. UAC 自动提权（绑 53/443 + WinDivert 驱动 + 写 icssvc 注册表都需管理员）
2. 首跑默认设开机自启（计划任务 + 最高权限，**开机静默以管理员拉起、不弹 UAC**；仅打包 exe）。
   托盘"开机自启"可关，关掉后重启不再自启（只默认建一次，之后尊重你的选择）。旧 HKCU\Run 残留会被自动清掉。
3. 禁用移动热点"空闲自动关闭"（注册表 `icssvc\Settings\PeerlessTimeoutEnabled=0`）+ 开启移动热点
4. 起完整本地热更 MITM：HTTPS 443 + DNS 53 + WinDivert（拦游戏硬编码 DNS）
5. 热点看门狗常驻（掉了自动拉起）→ **热点常开，来一台手机连进来就注一台（幂等）**
6. 系统托盘图标显示状态（绿=运行/琥珀=热点关/红=故障），菜单可手动开关热点/切自启/退出

### 源码态先跑通（拿 exe 前，管理员终端 + PC 已开热点）

```bash
cd apps/router_runtime
pip install -e .[windows]          # pydivert + winsdk==1.0.0b10 + pystray + Pillow + cryptography
python -m windows                  # 不带托盘的全链路（自动探测 192.168.137.1 + 写死 ECS）
python -m windows.tray_app         # 完整托盘版（会自提权）
python -m pytest tests/ -v         # 纯逻辑自测（不碰 pydivert/winsdk 驱动）
```

### 打包 exe

```bash
cd apps/router_runtime
winpack\build_win.bat              # 自动装依赖 + PyInstaller
# 产物: dist/MahjongMITM/  （整个文件夹 ~175MB，含内嵌 APK 84MB + WinDivert 驱动 + winsdk）
# 分发: 压缩 dist/MahjongMITM/ 整个文件夹；目标机双击 MahjongMITM.exe（UAC 弹窗放行）
```

### 复制到别的电脑使用（开箱即用）

**这是一个 one-folder 自包含包，目标机不需要装 Python / 任何依赖。**

1. **整个文件夹一起拷**：把 `dist/MahjongMITM/`（含里面的 `_internal/`）**整个**复制过去。
   ⚠️ 只拷 `MahjongMITM.exe` 单个文件**跑不起来**——APK / WinDivert 驱动 / winsdk 都在 `_internal/` 里。
2. **先放到固定位置再首次运行**：比如 `C:\MahjongMITM\`。首次运行会把"开机自启"计划任务指到 exe 当前路径，
   先放好再跑，免得之后移动文件夹导致自启失效（移动后重新双击一次会按新路径重建）。
3. 双击 `MahjongMITM.exe` → UAC 点"是" → 首次 SmartScreen 提示则"更多信息 → 仍要运行"。
4. 等约 4~10s 托盘图标转绿 → 手机连这台电脑的热点开游戏即被注入。

**目标机硬性要求**（不满足会失败）：

| 要求 | 说明 |
|---|---|
| Win10/11 **x64** | 与构建架构一致（本包是 64 位） |
| **有 WiFi 网卡且支持移动热点** | 台式机若只有有线、无无线网卡，**开不了 WiFi 热点** |
| **PC 本身要能上网** | 热点要共享上游（有线或另一路 WiFi）；MITM 透明回源也需要外网 |
| 管理员权限 | exe 自带 UAC 提权，点"是"即可 |

> WinDivert 驱动是微软交叉签名的，目标机**免手动装驱动**。换 ECS 服务器：exe 同目录放
> `ecs.txt`（单行新 IP）即可，无需在目标机重新打包。

> 跨架构提醒：本包只能在 **x64** Windows 跑。ARM 版 Windows 需在 ARM 机上重新 `build_win.bat`。

### 配置（写死 + 旁路兜底）

- **ECS IP 写死** `8.136.37.136`（阿里云）在 `mahjong_mitm/setup_mitm.py::DEFAULT_ECS_IP`。
  迁服改此处重编译即可。
- 免重编译换服：exe 同目录放 `ecs.txt`（单行写新 IP）即覆盖（`windows/config.py` sidecar 兜底）。
- 热点网关恒为 `192.168.137.1`（Windows ICS 硬编码），无需配置。
- 运行日志落 exe 同目录 `mahjong_mitm.log`。

### 真机验证清单（exe 双击后逐项确认）

- [ ] UAC 弹窗 → 放行后托盘出现图标 + console 黑窗常驻（启动后约 4~10s 图标才转绿：要等热点网关 192.168.137.1 就绪再绑 DNS，期间红/琥珀正常）
- [ ] 移动热点自动开启（设置 → 移动热点 显示已开），无设备连接 >5 分钟仍不掉
- [ ] 手机连该热点 → 开游戏 → `mahjong_mitm.log` 出现 `[divert] 新手机上线` + `NetConf.luac`
- [ ] 手机切 4G/其他网络后能连 ECS 读牌
- [ ] 关机重启 → exe 随系统自启、热点自动恢复

> ⚠️ `console=True`（v1 保留黑窗便于排障）。真机验证稳定后可在 `winpack/mahjong_mitm_win.spec`
> 把 `console` 改 `False` 重打包，得到纯托盘无窗口版。

### Windows 边界

- exe 为 PyInstaller 明文打包，`pyinstxtractor` 可反编译（自用，本轮不做混淆/Nuitka）。
- exe 未签名 → 首次运行 SmartScreen 可能提示"更多信息 → 仍要运行"（自用可忽略）。
- WinDivert64.sys 是微软交叉签名驱动，stock Win10/11 x64 免手动装。

## 打包到路由器

### 构建 ipk（任意机器，有 tar/gzip 即可，无需 SDK）

```bash
cd apps/router_runtime/openwrt
sh build_ipk.sh 1.0.0
# 产物: dist/mahjong-mitm_1.0.0_all.ipk
```

### 装到路由器

```bash
scp dist/mahjong-mitm_1.0.0_all.ipk root@192.168.8.1:/tmp/

ssh root@192.168.8.1
opkg update
opkg install python3-light python3-urllib python3-openssl kmod-nft-nat
opkg install /tmp/mahjong-mitm_1.0.0_all.ipk
# postinst 自动: 生成自签证书 + enable + start
```

### 配置

编辑 `/etc/config/mahjong-mitm`：

```
option host_ip '192.168.8.1'       # 本路由器 LAN 网关 IP（手机看到的网关）
option ecs_ip  '8.136.37.136'      # ECS 公网 IP
```

改完 `/etc/init.d/mahjong-mitm restart`。

### 用法

1. 手机连本路由器 WiFi
2. 打开游戏，等热更检查完成（日志出现 `[mitm] ... NetConf.luac` 即成功）
3. 手机切任意网络（4G/其他 WiFi），以后都连 ECS
4. **setup 完成后停掉服务恢复正常 DNS**：`/etc/init.d/mahjong-mitm stop`

## 依赖

| 依赖 | 用途 | 装法 |
|---|---|---|
| python3-light | 运行时 | opkg |
| python3-urllib + requests | 透明回源真实 CDN | opkg / pip |
| python3-openssl | TLS server | opkg |
| kmod-nft-nat | DNS redirect 规则 | opkg |
| openssl(CLI) | postinst 生成自签证书 | OpenWrt 自带 |

> 证书由 postinst 用 openssl 预生成，故运行时**不需要** Python `cryptography`。

## 边界（诚实声明）

- 本包 ipk 内是明文 `.py` 源码，拿到路由器 + root 可直接读。代码保护（PyInstaller/
  Nuitka/混淆/设备绑定）是后续阶段，本轮不做。见 task PRD 的 Decision。
- nftables 规则会劫持 LAN 上**所有**设备的 53。setup-period 临时用，用完 stop。
