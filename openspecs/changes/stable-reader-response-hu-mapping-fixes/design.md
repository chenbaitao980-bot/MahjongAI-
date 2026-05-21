# 设计：stable-reader-response-hu-mapping-fixes

## 当前状态

预检发现：

- `stable/protocol.py::_extract_optional_action()` 已能从 `0x0016 action_notify` 生成 `optional_action`，但当前硬算模块 `_can_recommend()` 在 `optional_actions` 非空时直接阻断出牌建议，最终 UI 显示等待态。
- `game/stable_hard_analysis.py::analyze_snapshot()` 只面向“我方 14 张等待出牌”的场景生成 `recommended_discard`，缺少“等待响应”场景下的吃/碰/杠/胡/过建议。
- `stable_tile_id()` 与 `MappingStore._builtin_tile("stable:*")` 理论上支持 `0x19 -> 9m`、`0x53 -> 7z`，因此九万/白未识别更可能来自错误 context、事件字段未带 context，或当晚特殊 raw_key 未进入稳定映射。
- 已胡/可胡状态没有作为硬优先级压过出牌候选，UI 可能保留上一轮“建议打五条”。

## 数据链路

```text
可选动作：
0x0016 action_notify
-> stable/protocol.py options/tile_raw/tile_context
-> stable/tracker.py optional_actions
-> PacketStateTracker.snapshot()
-> game/stable_hard_analysis.analyze_snapshot()
-> ui/stable_battle_panel.py 策略建议

牌值识别：
raw packet tile byte
-> raw_key(context, value)
-> stable.mapping.MappingStore.resolve_tile()
-> tracker snapshot hand/discards/melds/unknowns

胡牌优先级：
0x0016 options contains hu 或 0x0220 win
-> tracker snapshot optional_actions/phase/recent event
-> hard analysis suppresses discard candidates
-> UI overwrites stale discard advice
```

## 方案

### 1. 响应型硬建议

在 `game/stable_hard_analysis.py` 增加 optional action 分支：

- `hu`：直接建议胡，`recommended_discard=""`，`candidates=[]`。
- `kong` / `pon` / `chi`：构造响应建议。
  - 若手牌、财神、关联牌足够，评估响应后向听/听牌风险。
  - 若数据不足，输出“建议过/人工确认”，理由写明缺少关联弃牌、手牌或财神。
- `pass`：始终作为备选。

### 2. 已胡/可胡压过出牌

增加硬门槛：

- `phase == "hupai"` 或 snapshot 表示最近可信事件为 `win` 时，禁止生成出牌候选。
- `optional_actions` 包含 `hu` 时，禁止进入 `_discard_candidates()`。
- UI 渲染硬算结果时，用胡牌/响应建议覆盖旧出牌文本。

### 3. 九万/白未识别回归

先用当晚 `events_20260521_185429.jsonl` 锁定 19:03:33 与 19:04:57 附近 unknown raw_key：

- 如果 raw_key 为 `stable:0x19` 或 `stable:0x53` 却未解析，修 `MappingStore._builtin_tile()` 或 `stable_tile_id()`。
- 如果 raw_key 是 `linear:*` / `instance:*` / `nibble:*`，回溯对应事件，修正 `*_context` 为 `stable` 或补该 context 的合法映射。
- 新增单测覆盖 `9m` 与 `7z`。

## 回滚方案

回滚本 change 涉及的 `stable/`、`game/`、`ui/` 与测试文件改动即可；不会改变存量抓包文件或用户手动 mapping。

## 验证

- `python -m unittest tests.test_stable_reader tests.test_stable_hard_analysis`
- 回放 `data/stable_reader/events_20260521_185429.jsonl`，检查 19:03:33、19:04:57、19:05:24-19:05:29。
- `python -m compileall stable game ui tests`
- `gitnexus detect-changes --scope all -r mahjong-learning`
