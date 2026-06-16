# 真正根因：游服代理 GameS2CDecryptor 跨连接共用旧 session key（2026-06-16 实锤）

## 现象
- 金币局首局能读牌；之后进好友房 1v1（手机重连）**完全没数据**。
- ECS mahjong-tcp-proxy(pid 114599, 14:07 启动) 日志：
  - `[game-decrypt] session key learned` **只在 14:12:33 出现一次**（金币局首连）。
  - 14:24:50 / 14:26:07 / 14:31:27 / 14:31:29 / 14:31:52 / 14:34:31 共 6+ 次 `[proxy 5767] + 223.104.166.229` 重连。
  - 14:20 之后**零成功解码**（只有用旧 key 解出的乱码 `new msg=...`）。

## 根因
`remote/noconfig/hijack/tcp_proxy.py`：
- `TcpProxy._handle_client`（行 ~609）对 `s2c_rewriter` 是**每连接调用工厂** → 大厅 `LobbyS2CRewriter` 每连接新建（正确）。
- 但 `on_bytes`（行 ~636）是**所有连接共用的单个闭包**。`build_game_proxy` / `DynamicGameProxyManager.register_orig_addr` 里 `decryptor = GameS2CDecryptor()` 与 `tap = GameTapDecoder()` **只建一次**，被所有到该端口的连接共用。
- `GameS2CDecryptor._handle_frame_raw` 学 key 有 `and not self._session_key_learned` 守卫：首局学到后锁死。手机重连新局时，新的 HandshakeRsp 携带**新 session key**，但守卫令其被忽略 → 继续用旧 key 解密 → 全乱码 → 0x2bc0 永远解不出 → 无手牌。
- 同理 `GameTapDecoder` 与 presence 的 `_player_data_fired` 等每连接状态也被跨连接污染。

## 修复方向
让游服代理**每条连接新建** decryptor + tap（+ presence 状态），与大厅 `s2c_rewriter` 工厂一致：
- 给 `TcpProxy` 增加 per-connection `on_bytes` 工厂（如 `on_conn_factory`/`on_bytes_factory`），`_handle_client` 每连接调用得到独立的 `on_bytes`，传入 `_pump`。
- `build_game_proxy` / `DynamicGameProxyManager` 改为提供工厂：每次创建新的 `GameS2CDecryptor(on_player_data=...)` + `GameTapDecoder(...)` + `_on_bytes`。
- 保持 C→S/S→C 行为不变；presence/push 不变。

## 影响范围提醒
不只好友房——金币局打**第二局**同样会因旧 key 失效而无数据。此修复是所有"第二局起读牌"的前置。修好后再：① 重抓好友房新鲜解码帧确认编码(instance vs stable) ② 补 0x022b 起手解码分支。

## 用户当前手牌（待编码确认用，注意：实时在变）
副露：3s4s5s（吃）。手牌：3m 3m 5m 9m 3s 3s 6s 4p 9p + 北 西。
（因当前游戏帧未解出，暂无法用它对编码；需修复后用新鲜帧比对。）
