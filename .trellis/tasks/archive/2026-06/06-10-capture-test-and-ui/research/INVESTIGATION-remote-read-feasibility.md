# 调查结论：手机离开热点后能否远程读取牌局数据

日期：2026-06-11　任务：06-10-capture-test-and-ui

## 起点问题
现状（场景A）：手机连 PC 热点 → extractor 被动嗅探 7777 流量 → relay 展示手牌，**可用**。
诉求：手机**不连热点**、用任意网络时，远程仍能拿到牌局数据（理想是"连一次就永久"）。

## 结论（一句话）
**做不到"手机零改动 + 不走 PC + 远程实时拿数据"——这是路由/信息论限制，不是代码或加密能解的。** 实时牌局数据只存在于「手机」和「游戏服务器」两处，远程要拿到，数据必须流经一个你能控制的点。

## 关键证据链
1. **网络物理**：手机用流量时，手机↔服务器的信道不经过 PC，远程无从嗅探。要读，必须让流量经过采集点（改手机路由：热点/VPN/代理）或在手机本地抓包（改手机）。
2. **场景B（relay 自己连服务器）= 协议层不可行**：
   - 抓包确认 7777 登录是 SRS 协议：`0x0004 handshake_rsp`(服务端 nonce) → `0x0005 PlayerConnect`(认证请求) → `0x0006 PlayerData`(返回 16B sessionid)。
   - 反编译游戏客户端（Cocos2d-x Lua，XXTEA 加密的 Lua 源码，已全解）证实：0x0005 在 Lua 里只拼**明文结构体**（含每次登录现换的 sessionid + 设备码），**整帧加密在 native（libcocos2dlua.so，OpenSSL）内完成，密钥 m_key 由服务端认证后动态下发、只存 native 内存，Lua 不碰**。
   - 因此 relay 既不能重放（sessionid/帧序号每次变 + 防重放），也不能用 Python/Lua 复现（加密算法+key 在 native + 动态下发）。
   - `game_client.py` 现有的"0x000F×2 + 0x0001 + 等 0x0006"认证模型是基于过期 pcap 的错误猜测，从未真正通过认证。**game_client.py 实为死代码。**
3. **anti-cheat**：APK 含 `libsgcore.so`（腾讯反作弊）。复现 native 认证 = 逆向并绕过商业反作弊、向第三方服务器伪造客户端身份——已明确不实现。

## 顺带确认的事实
- 游戏**数据帧 0x2BC0 是明文**（`stable/protocol.py:_decode_game_event` 无需密钥直接解）。所以读牌从不卡在"解密"，只卡在"字节到不到远程"。
- 提取 handshake 的 bug 已修：真握手是 0x000F 之后的 0x0001(sub_type=0x047b)，旧逻辑误抓了前面的 4 字节杂包（`token_extractor.py`）。

## 可行（不越界）的方向，留待后续
- **场景A 保持连热点**：本来就好用。
- **手机本地抓包**（PCAPdroid 免 root / root tcpdump）转发到云 relay → 任意网络可读（但需在手机装东西）。
- **VPN 隧穿**（Always-on，把流量隧回 PC，被动嗅探）→ 唯一能"任意网络"且不碰认证的正路（需一次性配置 + PC/relay 公网可达）。
- **复盘导向**：游戏若有官方"回放/牌谱"，复盘时再用官方功能回看 + 本地采集；复盘不需要实时。
- 现有 `game/session.py` 已落库每局，可优先打磨**事后复盘/回放**体验。

## 产物位置
- 反编译全量 Lua、native .so、详细认证逆向报告（含密钥）：**项目根 `apk_research/`（已 gitignore，不进库）**。
- 抓包诊断日志：`remote/relay/relay.log`、`remote/extractor/extractor.log`（gitignore）。
