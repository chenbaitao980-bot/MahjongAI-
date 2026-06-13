# SRS pcap 解密验证 —— 负结果（2026-06-11）

## 抓包样本盘点（`data/`）
| 文件 | 大小 | 内容 |
|------|------|------|
| `phone_7777.pcap` | 65KB | **SRS 加密握手 C→S 全程**（EncryptVer/ReqKey/PlayerConnect + 业务流），s2c=0（只抓到出向）|
| `phone_srs.pcap` | 54MB | SRS 大流量抓包 |
| `phone_full.pcap` | 161MB | 全量 |
| `srs_capture.pcap` / `_any.pcap` | 1–7KB | 0x000F init 起手的连接（疑似明文 game 协议那套）|

## phone_7777.pcap 帧解析（C→S，连到 47.96.0.227:7777）
帧头 `0x4001 | paylen(u16) | msgtype(u16) | subtype(u16) | extra(u32)` 解析成立。序列：
```
id=1  len4   EncryptVer   payload = fa60a522   ← 与 handshake.py ENCRYPT_VER_PAYLOAD 完全一致
id=3  len0   ReqKey       空
id=5  len80  PlayerConnect 密文 840fec8a9082f102d9dbd4b3c2e4ae88...（80B）
id=23 len0   ReqPlayerPlusData
id=24 len12  ×很多        业务帧（每条12B，疑似加密）
id=11201 ...              游戏事件主流（大量，6/13/16B 居多）
```
**结论**：SRS 握手序列 EncryptVer(1)→ReqKey(3)→PlayerConnect(5)→ReqPlusData(23) **确实在线缆上真实存在**（之前 spectator 研究说"Lua 里不存在"——它们是 native 层的，但 wire 上是真的）。

## 解密尝试（PlayerConnect msgid=5, 80B 密文）
- 预期明文：build_player_connect 结构应 `02 07`(clienttype=2,usertype=7) 开头；若走 transformStr(hex-before-AES) 则解出应是 ascii-hex `0207...`。
- **已确认** key32 `f362120513e389ff2311d73601231007 05a210007acc023c3901da2ecb12448b` 与 IV `15ff010034ab4cd355fea122084f1307` 真实存在于 `libcocos2dlua.so`（key @0x11f660c, IV @0x11f662c, IV 紧跟 key 之后 32B 偏移 → 印证 key 是 32B）。
- **全矩阵无命中**：模式{CFB128,CFB8,CTR,OFB,CBC,ECB} × key{32,前24,前16,后24,后16} × IV{默认,全零} × {独立解, 先吃EncryptVer连续流}，均未解出 `02 07` 或 ascii-hex `0207`，也没有任何组合产出"全 ascii-hex"输出。

## 推断 & 下一步
静态 key/IV 没错，但**运行时 encrypt 的实际用法还差一层**未逆。候选未知点：
1. 每条消息 IV 是否重置/派生（不是固定默认 IV）——CFB 的 IV/num 跨消息状态。
2. key 是否在 setAesKey/encrypt 里被再加工（hash/transformStr 作用到 key 而非 data）。
3. transformStr(hex) 的确切位置（对 key？对 data？前/后）。
4. 首帧是否根本不走 AES（如 RC4，研究提到 identify 用 RC4）。
5. PlayerConnect 真实明文布局可能与 handshake.py 的猜测不同（oracle 需换更可靠的，如解出后找内嵌的 0x4001 子帧/可读 identify 字符串）。

**oracle 已就位**：`data/phone_7777.pcap` 的 PlayerConnect 密文 `840fec8a...`（80B）+ 后续 id=24/11201 业务帧。下一轮反逆 `Encryption::encrypt` 调用点的 IV/key/transform 实际数据流，用这条密文当判据即可闭环。
