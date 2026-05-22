# 设计：stable-reader-locked-hand-and-waiting-fixes

## 当前状态
稳定版硬算推荐使用 `analyze_snapshot()` 生成候选，`_discard_candidates()` 直接遍历整手牌：

```text
snapshot -> analyze_snapshot -> _can_recommend -> _discard_candidates(hand)
```

该路径没有携带“锁手后合法出牌集合”。tracker 侧对弃牌回声的判断只记录 `(discard_player, discard_tile)`，当另一家随后真实摸到同一张牌时会被误吞。AI 分析侧在流式返回空字符串时，上层请求日志可出现 `response_text=""` 且 `error_message=""`，UI 已进入 busy/等待文案但没有足够明确的恢复策略。

## 方案
1. **合法出牌集合**
   - 在 snapshot/analysis 中引入最小合法出牌信息，例如 `legal_discards` 或 `drawn_tile`/`locked_hand`。
   - `_discard_candidates()` 接受可选 `legal_discards`，先与当前 hand 求交集，再生成候选。
   - 若锁手但合法集合为空或新摸牌无法确认，则不输出整手牌候选，显示“等待可打牌/锁手需人工确认”。
   - LLM 校验仍只允许从程序候选中选择。

2. **同牌摸牌不误吞**
   - `_last_discard_echo` 增加上下文/时序证据，或只消费已知的“弃牌回显包”模式。
   - 对真实 `draw` 事件，即使牌值等于上一张对方弃牌，也不得默认吞掉；至少要求事件来源、玩家、raw 结构或短时间重复证据满足回显特征。
   - 12:44:18 场景中我方 `draw tile_raw=66` 必须加入手牌。

3. **空 AI 响应和等待态恢复**
   - 空 `response_text` 视为可恢复失败，不写成“成功但无建议”。
   - 优先回退 `get_program_advice()`；若本地候选也不可用，则设置明确错误/等待原因。
   - 新局可信手牌包、分析失败、空响应结束时，清理 `_stable_pending_state` / busy 文案，避免跨局残留。

## 业务规则处理
- 原 Requirement: 稳定版读取器协议解码、分析门控、策略建议区域。
- 本次处理方式: 追加 Scenario，Bug Against Spec。
- 不新增独立 capability。

## 历史 BugFixSpecs 命中
- 命中文件: 无 `openspecs/bugfixspecs` 目录命中。
- 历史根因: 无。
- 本次防重蹈措施: 测试同时覆盖推荐候选、tracker 增量状态、AI 空响应三条链路，避免只补 UI 文案。

## Bug 根因分析
- 用户可见现象: 推荐无法点击的牌；同牌摸牌后手牌少牌；杠后/下一把仍等待数据。
- 真实失败层:
  - 推荐层: 候选集未受游戏合法动作约束。
  - 状态层: 回声去重假设过宽，误吞真实摸牌。
  - UI/API 层: 空 AI 响应没有转换为失败或本地回退。
- 根本原因: 硬算、抓包状态机、UI 等待态各自有局部假设，但没有把“游戏动作合法性”和“事件可信恢复”作为跨层约束。
- 不是根因的排除项:
  - 不是截图识别误差导致 12:44:18 少南；该时间点来自抓包 `draw tile_raw=66`。
  - 不是 npcap 完全卡死；12:51:43 后仍有对方摸牌、弃牌、我方摸牌事件进入请求日志。
- 防复发检查项:
  - 候选推荐必须从合法集合生成。
  - 同牌先弃后摸必须可保留真实摸牌。
  - AI 空响应必须结束等待态并可回退。

## 回归测试方案
- 用例文件: `regression-tests/cases/stable-reader-locked-hand-and-waiting-fixes.md`
- 批量测试命令: `python -m unittest tests.test_stable_hard_analysis tests.test_stable_reader`
- 入参来源: 构造 snapshot、复用 2026-05-22 抓包事件片段或最小 ProtocolMessage。
- 期望出参:
  - 锁手合法集合只含新摸牌时，`recommended_discard` 等于新摸牌或为空，不得为原手牌。
  - 对面弃南后我方摸南，local hand 包含南。
  - 空 AI 响应后 UI/service 返回本地 fallback 或明确失败状态，不保持忙碌等待。
- 断言规则: 只断言关键状态字段、推荐牌、手牌计数和错误/回退标记。

## 回滚方案
还原本 change 涉及的 `game/stable_hard_analysis.py`、`stable/tracker.py`、AI 回退/UI 状态处理和对应测试。
