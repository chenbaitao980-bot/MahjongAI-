# 设计：stable-packet-reader

## 现状

`BattlePanel` 与 `BattleService` 当前围绕视觉手牌识别、人工战况编辑和既有策略引擎构建。策略引擎已经可以通过 `analyze_state_only()` 与 `analyze_state_with_ai()` 在不依赖图像识别的前提下分析 `BattleState`。

## 方案

- 保持原战斗页签不变。
- 新增稳定版页签，负责抓包与抓包状态展示。
- 使用 `StableCaptureThread` 运行 `adb exec-out` + tcpdump，将字节流输入 `PcapParser` 与 `MJProtocol`。
- 使用 `PacketStateTracker` 将协议消息转换为 `BattleState`。
- 使用 `MappingStore` 组合内置牌值映射与用户保存修正。
- 复用 `BattleAnalysisThread` 的 `state_only` 或 `state_with_ai` 模式，确保稳定版分析不会调用截图识别。

## 数据规则

- 内置 linear 映射：`1-9 -> 1m-9m`，`11-19 -> 1p-9p`，`21-29 -> 1s-9s`，`31-37 -> 1z-7z`。
- 内置 nibble 映射：高 nibble `0/1/2/3` 映射到 `m/p/s/z`。
- 可信实时包使用内置 stable 映射：
  - `0x11-0x19 -> 1m-9m`
  - `0x21-0x29 -> 1s-9s`
  - `0x31-0x39 -> 1p-9p`
  - `0x41-0x44 -> 1z-4z`（东南西北）
  - `0x51-0x53 -> 5z-7z`（中发白）
- 未知牌值只记录与展示，不进行猜测。
- 财神必须来自协议字段；在该字段未被可靠解码前，分析保持阻塞。
- `0x0003 deal` 为不可信事件，仅作开局标记；其中候选手牌/财神字节仅用于调试。
- `0x0216 hand_update` 作为可信手牌更新，仅消费 offset 3 之后前 `count` 字节；尾部字节视为元数据。
- 带 `0x72` 标记的 `0x021A draw` 视为暗抓，不得产出可见牌值。

## 回放与回归

- 离线回放同时支持 `.pcap` 与保存的 `events_*.jsonl`。
- 对保存事件回放时，优先使用当前解析器重解码 `raw_hex`，避免协议修复后旧解码字段失效。

## 回滚

本变更为增量式。移除稳定版页签相关 import/build 调用以及 `stable/` 包即可恢复原有行为。
