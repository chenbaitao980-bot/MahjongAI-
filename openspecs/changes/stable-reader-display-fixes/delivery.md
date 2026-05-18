# 交付记录：稳定版抓包显示修复

## 已完成

- `game/tiles.py` 新增 `tile_sort_key(tile_id)`，我方手牌显示按万、条、筒、字排序。
- `stable/protocol.py` 提取 TCP `seq`，`MJProtocol` 维护每条 TCP 流的 `stream_next_seq`，跳过完整重传并裁剪部分重叠 payload。
- `stable/protocol.py` 增加 `auto_detect_frames`，npcap 可在非配置端口上自动识别麻将协议帧。
- `stable/protocol.py` 对 `0x0216 hand_update` 的包尾 `[0x01, tile]` 做可信补牌，修复二人模式最右侧分离手牌缺位。
- `stable/protocol.py::NpcapCapture.sniff` 支持 `port_filter=0` 抓全 TCP。
- `ui/main_window.py::_run_npcap` 改为抓全 TCP，并启用麻将帧自动探测；如果仍只收到心跳/非牌局包，会提示检查网络接口或等待业务包。
- `stable/protocol.py` 为副露包补充 `meld_type` 和 `meld_tiles_raw`，优先从 stable 牌位提取被吃碰杠拿走的牌，避免把控制字节误识别成牌。
- `stable/tracker.py` 在副露发生时从其他可见玩家弃牌区移除被拿走的一张牌，避免幽灵弃牌残留。
- 已按用户要求移除视觉兜底路线；当前实现是纯抓包。

## 修改文件

- `game/tiles.py`
- `stable/protocol.py`
- `stable/tracker.py`
- `tests/test_stable_reader.py`
- `ui/main_window.py`
- `openspecs/changes/stable-reader-display-fixes/tasks.md`
- `openspecs/changes/stable-reader-display-fixes/delivery.md`

## 验证结果

- 通过：`python -m py_compile stable\protocol.py stable\tracker.py ui\main_window.py tests\test_stable_reader.py`。
- 通过：`python -m unittest tests.test_stable_reader`，28 个测试通过。
- 通过：`python -m unittest discover tests`，28 个测试通过。

## 剩余风险

- 如果选错 npcap 网络接口，即使抓全 TCP 也仍可能只看到心跳包；这时需要切换到实际承载模拟器网络流量的接口。
- tcpdump 模式按用户反馈暂不处理，后续有需要再单独验证。
