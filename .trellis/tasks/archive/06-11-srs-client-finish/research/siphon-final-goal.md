# 最终目标(已证明可行):手机端 Siphon — 任意网络、云端展示手牌

> 用户目标:连一次(设置一次)→ 之后**任意网络** → 云端展示**我自己的手牌** → 手机**正常玩、不踢线**。
> 本方案 = 唯一同时满足"任意网络 + 手机正常玩 + 看自己手牌"的架构,且**解码已用真实 pcap 证明**。

## 一、为什么是这条路(排除法,全有证据)
- 旁观读手牌：**死**(用户肉眼确认旁观只见牌背,服务器不发隐藏手牌)。
- 云端独立连/重连读手牌：会**踢手机**(同账号同桌单连接=接管语义)。
- 本地服务器(PC)嗅探推送：**只在热点上有效**,离开热点 PC 失明 → 做不到"任意网络"。
- ∴ 手牌是**会话私有**的 → 只能**在手机本人这条会话内部读**。手机自己读、自己推 = 任意网络。

## 二、已证明的事实(本轮)
1. **0x2bc0 游戏帧在 47.96.0.227:7777 连接上**(pcap 实证),含手牌。
2. **stable 解码器能从中还原完整手牌**:`data/phone_full.pcap` 回放 → 座位0手牌
   `3m6m7m 1s2s7s 1p1p5p9p 1z1z2z6z`(14张)。`hand_trusted=True`。
3. **手机进程内 recv hook 能读到该连接的明文帧**(hook_hand.js live 抓到入向帧;
   游戏帧明文、无需解密)。
4. **gadget 已内置于重打包 APK**(无需 root,listen 模式可 attach)。

## 三、架构
```
手机(任意网络,原生玩,不踢线):
  游戏进程(重打包APK + gadget[改 script 模式])
    └─ siphon.js(gadget 自动加载):
        - hook libc recv/read/recvfrom
        - 抓游戏服连接(fd 上出现 0x4001 帧头 → sticky 标记,全抓)的入向帧
        - 批量 HTTP POST 到云端 relay(走手机自己的网络)
云端 ECS relay:
    POST /ingest 收原始帧
      → MJProtocol 重组 + PacketStateTracker 解码(复用 stable)
      → BattleState(手牌/弃牌/相公)
      → 网页展示(复用 relay index.html / battle 视图)
用户任意设备打开网页看手牌。
```

## 四、复用 vs 新建
**复用(~80%)**：重打包gadget APK、stable 解码器(MJProtocol/PacketStateTracker/MappingStore)、relay 服务+网页、ECS 部署。
**新建**：
1. `siphon.js` = hook_hand.js + 批量 HTTP POST(Frida Socket/NativeFunction 发 HTTP)。
2. gadget 自治：on-device config 改 `{"interaction":{"type":"script","path":".../siphon.js"}}`(或重打包内嵌),游戏启动即加载,脱离 PC。
3. relay `POST /ingest`：收帧 → 喂解码器 → 存 BattleState(把 extractor 的解码逻辑搬进 relay 的 ingest 路径)。
4. local_player 判定:trusted-hand 帧是发给本人的 → 解码器已能认"我的手牌"(SOURCE_TRUSTED_HAND)。

## 五、实现步骤(里程碑)
- M1 **live 验证手牌捕获**:hook_hand.js(sticky game-fd 版)在**活跃牌局**抓到 0x2bc0 帧 → 本机喂 stable 解码器 → 打印手牌。证"live 也能拿到"。
- M2 **siphon.js 自推**:hook 内 HTTP POST 帧到 relay(先 PC relay 测,再 ECS)。
- M3 **relay /ingest 解码+网页**:云端收帧→解码→网页显示手牌。
- M4 **gadget 自治**:script 模式自动加载 siphon.js,拔掉 PC,手机换任意网络验证云端仍更新。
- M5 **稳健性**:断线重连、批量节流、字段裁剪、隐私(只传必要帧)。

## 六、当前卡点 / 风险
- live 抓手牌帧未跑通(只到心跳)——因当时无活跃牌局,非未知;M1 解决。
- gadget teardown:full 在 PC 断开时杀游戏 → 自治(script模式)后无 PC 断开,不触发。
- gadget script 模式的 config 落点(APK 内置 vs /data/local/tmp)需在真机确认。
- MappingStore 对本游戏的 byte→tile 映射:stable 是"primary reliable path",已支持本游戏。
