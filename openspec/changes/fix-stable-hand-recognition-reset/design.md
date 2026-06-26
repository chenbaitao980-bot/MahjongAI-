# 设计：fix-stable-hand-recognition-reset

## 当前状态
稳定版协议层把 0x0216 解析为可信 `hand_update`，状态机在 `PacketStateTracker._apply_game_event` 中处理：

```text
0x0216 hand_update
  -> _is_new_round_hand_update
  -> 必要时 reset
  -> _maybe_lock_local_player
  -> _resolve_tiles
  -> players[player_id].hand / hand_count / hand_trusted
  -> snapshot / to_battle_state / UI
```

当前风险点：

- 新局判定要求 `hand_trusted == True`，如果上一局已经进入等待可信手牌包或未成功建立可信手牌，新一局可信手牌包不会触发清局。
- 新局清理依赖 `phase == hupai` 或旧局可见状态和剩余牌数条件，面对异常/缺包状态不够稳健。
- 首个可信手牌包需要可靠接管本地玩家并展示手牌，不能被旧的 `local_player` 默认值或旧状态阻断。

## 方案
1. 保持 0x0003 `deal` 为 untrusted round marker，不把它作为权威初始手牌。
2. 优化 `PacketStateTracker._is_new_round_hand_update`：
   - 可信本地 13/14 张手牌包到达时，如果已经处于胡牌阶段，继续判定为新局。
   - 如果存在上一局可见状态，且当前处于等待可信手牌或旧局已明显进行过，也允许新可信手牌包触发清局。
   - 避免把同一局中的普通 13 张/14 张手牌刷新误判为新局。
3. 保证新局 reset 后保留 history、财神状态等既有设计允许保留的字段。
4. 增加回归测试覆盖：
   - 首个可信稳定版手牌包能从默认本地玩家切换到包内玩家并识别手牌。
   - 上一局有弃牌/事件但手牌未可信时，新一局可信手牌包会清空旧状态。

## 业务规则处理
- 原 Requirement / Scenario：无明确主 spec。
- 本次处理方式：新增 change delta，修复状态机，不改变业务规则。

## 历史 BugFixSpecs 命中
- 命中文件：无。
- 历史根因：无。
- 本次防重蹈覆辙措施：用测试同时覆盖“首个可信手牌接管”和“上一局非可信状态下的新局清空”两个链路。

## Bug 根因分析
- 用户可见现象：稳定版初始手牌不显示；等待下一局时旧手牌/旧状态不清空。
- 真实失败层：状态机。
- 根本原因：新局清理和本地玩家接管都依赖过窄状态前提；异常/缺包/等待可信手牌状态下，新可信手牌包没有被当成一次新的权威局面入口。
- 不是根因的排除项：0x0003 deal 包不能直接作为权威手牌，已有回归测试要求它不暴露假开局手牌。
- 为什么前一轮没修掉：本次为首次记录。
- 防复发检查项：必须保留 untrusted deal 防假阳性测试，并新增 0x0216 trusted hand 的首包和新局清理测试。

## 回归测试方案
- 用例文件：`regression-tests/cases/fix-stable-hand-recognition-reset.md`
- 批量测试命令：`python -m unittest tests.test_stable_reader`
- 入参来源：项目已有稳定版读包单元测试构造器。
- 期望出参：snapshot 中本地手牌、phase、discards、melds、events、hand_trusted 符合预期。
- 断言规则：只断言关键状态字段，不保存完整响应体。

## 回滚方案
还原 `stable/tracker.py` 和 `tests/test_stable_reader.py` 中本 change 的修改。
