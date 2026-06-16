# PRD: 破解 0x2bc0 游戏帧解密 — noconfig 4G 读牌最后一环

## 一句话

4G/热点 noconfig 链路已**全部打通**（手机大厅→ECS、金币游服→ECS、会话密钥已学到、系统帧已正确解密），**唯一剩下**：游服 0x2bc0 游戏数据帧的加密变体没破解出来，导致解不出手牌 hand_raw。破解它 = 网页/relay 实时显示手牌。

## 现状（2026-06-16，全部已验证）

链路逐环状态（ECS `journalctl -u mahjong-tcp-proxy`）：

- ✅ `[proxy 5748] + <4G手机IP>` — 手机大厅连进 ECS（靠 NetConf 注入 `LOCAL_TCP_LIST_50[5045]=ECS`）
- ✅ `[lobby] session key learned` + `[lobby] RespSRSAddr rewritten` — 大厅密钥 + 游服地址改写
- ✅ `[proxy 5767] + <IP> → srs-zj.tt2kj.com:7777` — **金币游服**连进 ECS（靠 `_50[5067]→ECS:5767` 改写 + ECS 固定代理）
- ✅ `[game-decrypt] session key learned (32B) KEYHEX=...` — 游服会话密钥学到
- ✅ **系统帧解对**：`new msg=0x0006 ... plain_head=...4c4f4c4c4150...`（ASCII "LOLLAPALOOZA"）、`0x0018` 解出 "newpt1084306678" → 密钥对、AES-CFB128 对、fresh-from-IV 对
- ❌ **0x2bc0 解不出**：`MJ 0x2bc0 decoded: hand_raw=None`，解密后 sub_cmd 乱码

## 核心问题：0x2bc0 用了不同的加密变体

- **系统帧**（0x0006/0x0018，msg_type<0x100）：**fresh-from-IV** 每帧从固定 IV 解密 → 正确。
- **游戏帧 0x2bc0**（msg_type≥0x2000）：fresh-from-IV ✗、连续 CFB 流 ✗ 都解不出。
- 已加 dump 日志：`[game-decrypt][dbg] 0x2bc0 flag=.. sub=.. extra=.. ENC=<原始密文hex>` + `KEYHEX=<会话密钥>`（在 `tcp_proxy.py` GameS2CDecryptor）。

**待验证的假设**（按优先级）：
1. **帧头 `extra`(4字节) 当 IV/nonce/counter**：系统帧 extra=0（fresh-from-IV），游戏帧 extra=序号 → 用 `IV XOR extra` 或 `extra` 拼 IV 解密。先对比 dump 里系统帧 vs 0x2bc0 的 extra 值。
2. **独立连续流**：游戏帧是与系统帧分开的一条连续 CFB 流（系统帧不消耗其 keystream）。
3. **hex transform**：`crypto.py:transform_and_encrypt`（hex编码+AES），用 `decrypt_and_untransform` 解。
4. **不同密钥/段**。

## 怎么破解（操作步骤）

1. 手机 4G 进金币局打牌，ECS 抓样本：
   ```bash
   ssh root@8.136.37.136
   journalctl -u mahjong-tcp-proxy --since '5 min ago' | grep -E 'KEYHEX|0x2bc0.*ENC|new msg'
   ```
2. 拿到 `KEYHEX`（会话密钥）+ 多个 0x2bc0 的 `ENC`（原始密文）+ `extra` 值 + 系统帧 extra 值。
3. **离线写小脚本**用 `cryptography` AES-CFB128 + `SRS_IV`(crypto.py:`15ff010034ab4cd355fea122084f1307`) 对 ENC 试上述 4 种解法，判定标准 = 解出 `payload[0:2]`=sub_cmd∈{0x0003 发牌, 0x0216 hand_update, 0x0016 action} 且 `data_len`(payload[2:4]) 合理（≤payload长度）。
4. 命中后改 `tcp_proxy.py:GameS2CDecryptor._handle_frame_raw` 对 0x2bc0 用正确解法，验证 `[game] 0x2bc0 hand_trusted: hand=[...]` + `push to relay OK`。

## 关键文件

- `remote/noconfig/hijack/tcp_proxy.py` — `GameS2CDecryptor`（解密器，改这里）、`build_game_proxy`（金币代理）、`SRS50_REMAP`(在 netconf_patch)
- `remote/srs_spectator/crypto.py` — `SRSCrypto`（AES-CFB128、IV、transform 变体）
- `stable/protocol.py` — `MJProtocol._decode_game_event`（0x2bc0→hand_raw 解析，**明文输入下已正确，勿动**）
- `.trellis/spec/backend/remote-access.md` §16 — 全链路契约 + 诊断表（**接手必读**）

## 验证标准

- [ ] 离线脚本对样本 ENC 解出合理 sub_cmd（0x0003/0x0216）
- [ ] tcp_proxy 改完，4G 金币局日志出现 `0x2bc0 hand_trusted: hand=[13张牌]`
- [ ] `http://8.136.37.136:8002/?token=d4a8e1f29c6b7305e8d1f264` 网页实时显示手牌
- [ ] 友尽/房卡局同样出牌（房卡游服走 5700-5723 动态代理）

## Out of Scope

- 不改 `stable/protocol.py` 解析逻辑（明文输入已对）
- 不改 VPN/热点模式（它们处理明文，与此无关）

## 善后（破解成功后）

- 移除 `tcp_proxy.py` 里的 `[dbg]` 诊断日志（ENC/KEYHEX 含敏感数据，量大）
- commit 全部改动（netconf_patch/tcp_proxy/setup_mitm/relay app.py/tests/scripts）
- 归档本任务 + `06-15-mitm-0x2bc0`
