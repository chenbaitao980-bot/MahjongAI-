# noconfig 读牌链路实机诊断（2026-06-14）

手机连 PC 热点、`run_hijack.py --host-ip 192.168.137.1` 在跑，进游戏后 8002 不出手牌。
以下为当日逐层实测证据（PC 侧 + ECS 侧抓包/日志），结论是**牌局流量根本没到 ECS**。

## 链路设计（端到端）

设置期（PC 热点，做一次）:
- `run_hijack`(setup_mitm): DNS 劫持 4 个 `gxb-*.hzxuanming.com` → PC:53，自签 HTTPS:443
  下发伪 manifest + 改写后的 `NetConf.luac`（台州大厅 5045 → ECS）。

运行期（ECS 常驻 `mahjong-tcp-proxy.service`）:
- 大厅代理 5748/5749 → 透传真大厅 `47.96.101.155`，S→C 改写 `RespSRSAddr(msgid=15).szIP` → ECS IP
- 游服代理 7777 → 透传真游服 `47.96.0.227:7777`，被动旁路解 `0x2bc0` → POST `http://127.0.0.1:8002/push`
- relay 8002 (`mahjong-relay-noconfig.service`) 展示页 `GET /state?token=d4a8e1f29c6b7305e8d1f264`

## 实测证据

### 1. PC 侧 MITM 服务本身健康（已排除）
- `run_hijack` 普通权限即可绑 53/443（不是权限问题）。
- DNS 劫持生效：`nslookup gxb-oss.hzxuanming.com 192.168.137.1` → `192.168.137.1`；普通域名正常转发上游。
- 443 `/hotfix_update` 正常返回伪 version.manifest（v=9.9.9.99）。
- ⚠ 一度并存 2 个 run_hijack 实例（SO_REUSEADDR 共绑），日志割裂，需收敛单实例。
- ⚠ ICS(`SharedAccess`) 占 UDP:53，但实测 responder 照样收包应答，**不影响**，无需动注册表。

### 2. ECS 服务在跑（已排除）
- 端口 22/5748/5749/7777/8002/8003 全 OPEN。
- `mahjong-tcp-proxy.service` active，PID 60949，`--relay-push http://127.0.0.1:8002/push`。
- relay 8002 被设备 39.184.31.151 高频轮询 `/state?token=...` 全 200 OK（**展示端没问题，token/地址都对**）。

### 3. tcp-proxy 全量日志「三个从未」（关键）
`journalctl -u mahjong-tcp-proxy` 全量 grep：
- ❌ 从未解出 `0x2bc0` / `hand_trusted`
- ❌ 从未 `RespSRSAddr rewritten`
- ❌ 从未 `session key learned` / 从未 `push to relay`

历史上手机(39.184.31.151)连过 ECS 5748/5749/7777，但 **7777 每次仅 ~10s 即 disconnected**，无牌局数据。

### 4. 决定性：PC 侧抓手机流量，牌局直连真服（root cause）
手机 192.168.137.67 仍在 PC 热点上（arp 在线）。scapy 抓 8s（手机正在打牌）TCP 对端分布：

| 对端 | 包量 | 判断 |
|---|---|---|
| `36.151.17.85:443` | 1600+（最大） | 游戏主连接（443 私有协议） |
| `47.110.230.204:5708` | 中 | 疑似大厅 |
| `8.136.155.143:443` / `120.55.41.156:443` | 中 | 辅助/资源 |
| `47.96.0.227:7777` | 极少 | 真游服 |
| **`8.136.37.136`(ECS)** | **0** | **完全没连** |

## 结论（root cause）

1. **NetConf 改写未持久生效**：手机当前大厅/游服全部直连真实地址，ECS 一次未出现。
   之前 ECS 见过手机连 5748/5749，说明改写**曾生效一次但被回滚**（疑游戏重启跳过热更 / 官方配置覆盖）。
2. **tcp_proxy 上游地址族过时**：代码写死真大厅 `47.96.101.155:5748/5749`，但手机实际大厅
   `47.110.230.204:5708`，主流量在 `36.151.17.85:443`。地址/端口都对不上，需重新核对真实拓扑。
3. `RespSRSAddr` 改写从未被真机触发验证过（代码注释自承"无真机样本，仅单测"）。

## 待查（下一步诊断）
- [ ] NetConf「曾生效又失效」根因：手机连热点重开游戏时，热更是否触发？改写后的 NetConf.luac 是否被下载应用？（需实时抓 MITM 443 日志 + PC 抓手机 443/热更域名流量）
- [ ] 游戏真实服务器拓扑：`36.151.17.85:443`、`47.110.230.204:5708` 各是什么角色？大厅/游服/网关？
- [ ] NetConf.luac 改写内容是否完整覆盖了当前游戏用的大厅地址（patch_from_apk 用的 APK 是否与线上版本一致）。

## 决定性根因 #2：游戏硬编码公共 DNS，绕过热点 DNS 劫持（19:43 实测）

手机彻底重启游戏，单实例 MITM 日志收到的请求 = **0**（version/project/NetConf 全 0）。
PC 热点网卡 scapy 抓手机(192.168.137.67)重开 20s：

```
查 gxb-api.hzxuanming.com   → 发给 119.29.29.29(腾讯) / 223.5.5.5(阿里)
查 shiming.hzxuanming.com   → 同上
查 palmstatic.hzxuanming.com→ 同上
手机用的 DNS 服务器：119.29.29.29(24次) / 223.5.5.5(22次)
手机连 PC(192.168.137.1) 端口：无（443/53 全无）
```

**结论**：游戏客户端**写死公共 DNS（119.29.29.29 / 223.5.5.5）**，不走热点 DHCP 下发的 DNS。
`setup_mitm` 的 DNS 劫持前提（"手机用 PC 的 DNS"）**对此游戏从根本上不成立**——
这才是热更链路从未真正生效、NetConf 永远是真版的根因。之前偶发连 ECS 疑为其他遗留设置。

## 破解方向（已收敛）

手机经 PC 热点上网，发往 `119.29.29.29:53 / 223.5.5.5:53` 的 DNS 包**必经 PC 网关转发**。
在 PC 用 **WinDivert(pydivert)** 拦截转发路径上的 UDP:53：对 `gxb-*.hzxuanming.com`
伪造 A 响应指向 PC，其余放行。把劫持从"靠 DHCP 下发 DNS"升级为"网络层强制拦截"，绕不过。
（pydivert 当前未安装，需 `pip install pydivert`，需管理员/WinDivert 驱动。）

后续仍需验证：DNS 拦截通后，热更能否走完三步写入改写 NetConf，且游戏下次启动跳过热更（持久）。

## 突破 #1：WinDivert DNS 劫持成立（20:12 实测）

`remote/noconfig/hijack/dns_divert.py`（新建，pydivert/WinDivert）拦截 `udp.DstPort==53 and outbound`，
qname 命中 `HIJACK_DOMAINS`(4个 gxb-*) → 伪造 A 响应指向 PC(self_ip)，反转方向注入；其余放行。
- 本地验证：`nslookup gxb-api @119.29.29.29` → 192.168.137.1（劫持成功）；`baidu` 正常放行。
- 真机验证：手机(192.168.137.67)的 gxb-api/gxb-api-tx 查询(发往 119.29.29.29 / 223.5.5.5)全被劫持 →
  手机连 PC:443 → setup_mitm 收到 version.manifest×2 + project.manifest×1 + **NetConf.luac×1 下载成功**。
- WinDivert 驱动在本会话有管理员权限，可直接跑。注入方向 `pkt.direction=1`(INBOUND) 正确。

## 突破 #2 + 新断点：「加载网络失败」根因 = APK 版本落后（20:07 实测）

热更链路通了，但手机请求了 **91 个文件全 404**（.manifest/.png/.luac）→ 热更整体失败回滚 → 加载失败。
根因坐实：
- APK `apk/game_base.apk` 内置 `project_10001.manifest` version=**1.0.0.50**，915 条文件。
- 404 的文件 hash **不在 APK manifest 里** → 是**线上新版**的 hash。手机跑的是比 APK 新的线上热更版，
  缓存里是新版文件。`manifest_forge` 基于 APK 旧版 forge，与手机缓存差 91 个文件 →
  游戏 genDiffList 认为这 91 个要更新 → 来 PC 下载 → PC 只有 NetConf → 404。

## 正解（已验证可行）：透明回源热更 MITM，只替换 NetConf

真实 CDN 验证（停劫持后 curl）：
```
gxb-oss → 112.15.7.146 ; gxb-cos → 117.163.58.121
GET /yj/files/c9/c9b4...luac  → HTTP 200（真实CDN有）
GET /yj/files/21/2143...manifest → HTTP 200
```
**实现要点**：
1. setup_mitm 改"静态 APK forge"为"透明回源"：游戏请求的 Host+path 即真实路径（DNS 劫持后 path 不变），
   PC 用 119.29.29.29 解析该 Host 真实 IP，同 Host+path 回源真实 CDN(`--resolve`/requests, verify=False)。
2. `project.manifest`：回源**线上真实** manifest → 只 patch NetConf 条目(md5/size/name→PC改写版) +
   顶高 version 触发热更 + forbid_zip。这样 diff 只剩 NetConf，游戏不再请求那 91 个文件。
3. 文件下载：NetConf.luac → 改写版；其余 → 回源真实 CDN（兜底，理论上只 diff NetConf 不会触发）。
4. `version.manifest`：顶高 version 触发热更（现有逻辑基本可用）。
5. `dns_divert --phone-ip 192.168.137.67`：只劫持**手机**，放行 PC 本机查询 →
   PC 回源能正常解析真实 gxb CDN（不被自己劫持）。dns_divert 已支持 phone_ip 参数。
6. 待验证：回源后热更走完、NetConf 改写生效、手机连 ECS；再验证断热点持久性。

## 透明回源 setup_mitm 已实现（2026-06-14，代码侧）

`remote/noconfig/hijack/setup_mitm.py` 已从「静态 APK forge」改为「透明回源」：

- 新增 `_resolve_real_ip(host)`：用固定公共 DNS **119.29.29.29** 裸 UDP 查询解析真实 A 记录 IP，
  带缓存（同 host 一次）。不走系统 DNS，故不被 dns_divert 自劫持。`_parse_first_a` 解析响应首条 A。
- 新增 `_origin_fetch(host, path)`：`https://{real_ip}{path}` + `Host: {host}`，`verify=False`，8s 超时，
  返回 `(status, body, content_type)`；异常返回 `(502, b"", "")`。
- 新增 `MitmAssets.patch_real_project_manifest(real_bytes)`：对回源到的**线上真实** project.manifest
  只 patch `file_list["src/app/config/NetConf.luac"]`（md5/size/name→PC 改写版）+ 顶高 version
  + `forbid_zip=True` + 去 diff_zip/zip_url + file_url→PC。非 JSON/缺 NetConf 条目时抛异常，调用方回退静态。
- `Handler.do_GET` 路由：
  - `/hotfix_update` → 伪 version.manifest（顶高，原逻辑）。
  - `/project.manifest` → 回源真实 manifest → patch → 失败回退静态（**绝不挂请求**）。
  - NetConf 文件名 → 改写版 NetConf.luac（原逻辑）。
  - 其它所有文件 → 透明回源真实 CDN 原样返回（status/body/ctype 透传）；回源失败→404。
- `enable_origin: bool`（默认 True）开关：`--no-origin` / `_selftest` 关掉，保证本地无网自测通过。
- `--selftest` 全 PASS（含新增 `_parse_first_a` 与 `patch_real_project_manifest` 两个不联网单测；
  原 DNS 单测把 `listen_host` 显式绑 127.0.0.1 修了本机不能绑 10.0.0.1 的环境问题）。

**真机验证时盯的日志关键字**（PC 侧 setup_mitm INFO）：
- `[origin] resolved <host> -> <ip>`（回源 DNS 解析成功）
- `project.manifest (origin-patched, NB)`（回源 manifest 成功 patch；若见 `fallback static` 说明回源失败）
- `NetConf.luac (...md5=...)`（手机下载改写版 NetConf）
- 其它文件出现 `(origin 200, ...)` 而非 `404` = 回源兜底生效（理论上 diff 只剩 NetConf，不应大量出现）。

ECS 侧（验证牌局到达）：`journalctl -u mahjong-tcp-proxy` 应出现 `0x2bc0 hand_trusted` + `push to relay`。

## 真机验证 #1 失败（20:43）：回源路径错误 → 仍 91 文件

DNS 劫持 + 回源解析都成功，但热更仍失败：
```
[mitm] host=gxb-api → version.manifest (v=9.9.9.99)        # 手机连上PC,劫持生效
[origin] resolved gxb-api.hzxuanming.com -> 121.40.48.133   # 回源解析OK
project.manifest origin fetch status=404 → fallback static  # 回源404,退回APK旧版→91文件→加载失败
```
**根因**：sub-agent 实现里 version.manifest 仍是**伪造**的，其 `manifest_url` 用自编路径
`/yj/Lobby/project.manifest`；project handler 去**回源这个自编路径** → 真实 CDN 没有 → 404 →
fallback 到 APK 旧版静态 → 又 91 文件。真实 `/hotfix_update` 回源需 appid（"appid can not be nil"）。

## 正解（据 hotfix-download-verify.md §0/§3/§5）

热更三 manifest：local(游戏本地,已热更到线上新版) / version(update_url GET) / project(version 的 manifest_url GET)。
`genDiffList` 用 **我们 serve 的 project** 比 **游戏 local(线上新版)**。要只 diff 出 NetConf，
我们 serve 的 project.manifest 必须 = 游戏 local(线上新版) + 只改 NetConf。真实线上 project.manifest
的位置 = **真实 version.manifest 的 manifest_url**。所以：

1. **version.manifest 必须回源真实**（透传游戏原始 raw path+query，自带 appid，无需预知）→
   拿真实 version.manifest → 改 `version`=顶高 + `project_md5`="" (清空跳校验,因我们要 patch) +
   **保留真实 `manifest_url`/`file_url`** → 返回。同时**记下真实 manifest_url**（存 MitmAssets）。
2. **project.manifest 请求识别**：当游戏请求的 path == 记下的真实 manifest_url 的 path 时 = project 请求 →
   回源真实该 path → patch NetConf 一条 + forbid_zip + 去 zip → 返回。**不再用自编 PATH_PROJECT**。
3. NetConf 文件名 → 改写版；其余文件 → 回源真实 CDN。
4. ⚠ 真机验证时盯日志里的**真实 manifest_url host**：若不在 dns_divert 劫持的 4 个 gxb 内，
   游戏会直连真实 CDN 拿 project（绕过 PC，不 patch）→ 需把该 host 加入 dns_divert 劫持列表。

## 重大障碍：线上 NetConf 格式变更，现有改写逻辑失效（21:30）

突破了热更回源全链路后，挖到真实结构：
- 真实 update_url（APK manifest）：`gxb-api.hzxuanming.com/hotfix_update?env=1&appid=1073&engine_ver=3.13&channel=10001116&version=1.0.0.59`
- 用**低 version** 请求真实 /hotfix_update → 真实 version.manifest：
  - `manifest_url`=`gxb-oss/gxb-cos.hzxuanming.com/yj/manifests/1073/3.13/10001116/project-1.0.1.1776.manifest`（host 已劫持✓）
  - `version`=**1.0.1.1776**（线上最新；APK 才 1.0.0.50）、`project_md5`=a9aa1650...、`zip_url`=306MB 整包
  - ⚠ setup_mitm 回源透传游戏 version(=本地最新) → 服务器"无更新"无 manifest_url；须**回源时降 version**才拿到完整响应
- 真实线上 project-1.0.1.1776.manifest：6138 条，NetConf key=**`src/app/Config/NetConf.luac`（大写 Config！）**
  线上 NetConf：name=`d1/d1544d...luac` md5=2a17057c size=**13858**（APK 版 13485，不同版本）
- **致命**：下载线上 NetConf 解密 → 原始头 `\x89 77 88 89 82 02 11 36...` **不以 SIGN(devaguopeifei) 开头**，
  `unwrap_luac`(XXTEA) 出**乱码**、源码内**无任何 IP**(无 5045/47.96/47.110)。
  → 线上版 NetConf 封装/加密格式已变，`netconf_patch` 的 SIGN+XXTEA 逻辑**完全失效**，
  无法解密改写大厅地址。整个「改 NetConf 大厅地址→ECS」核心环节在当前线上版**走不通**。

### 已确认可用的部分（保留价值）
- WinDivert DNS 硬编码劫持（dns_divert.py）：完全可用。
- 热更回源链路（setup_mitm 回源真实 version/project.manifest，降 version 拿 manifest_url，去 zip）：
  逻辑已基本成型，差「线上 NetConf 改写」这一环。

### 待决策方向
- A. 逆向线上 NetConf 1.0.1.1776 新封装格式（新 SIGN/key/压缩？），工作量不确定。
- B. 降级「连热点读牌」：放弃改 NetConf，PC 用 WinDivert 直接重定向手机大厅 TCP(47.110.230.204:5708)→ECS，
     或 PC 直接嗅探手机 7777 牌局流量本地解码。仅连热点时有效，但绕开 NetConf 格式难题。
- C. 暂停存档。

## 复用入口
- PC 抓手机流量：scapy，热点网卡 IP=192.168.137.1，filter `host 192.168.137.67 and tcp`。
- ECS 登录：paramiko，root@8.136.37.136。后台抓包勿用 `nohup ... &`（SSH channel 关闭即被杀），需 `setsid` 或 `systemd-run`。
