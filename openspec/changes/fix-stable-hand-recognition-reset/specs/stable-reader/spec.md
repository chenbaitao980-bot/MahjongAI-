# Delta: fix-stable-hand-recognition-reset

## 与主规范关系
Spec Gap / Bug Against Spec。

## 命中的主规范
- Capability: 无明确主规范
- Requirement: 无
- Scenario: 无

## 变更类型
ADDED

## 业务冲突检查
| 维度 | 状态 |
|------|------|
| 主规范 Req 命中 | 无 |
| 关系判断 | Spec Gap / Bug Against Spec |
| 其他 active change 撞车 | 未命中 `opponent-prediction-strategy`、`ui-layout-refactor` 的同一能力 |
| 冲突状态 | 无冲突 |
| 是否允许 ADDED | 是；当前缺少稳定版手牌识别状态机规范 |
| 归档完整性 | 待实现后验证 |

## 原规则
无明确主规范。现有测试要求：

- 0x0003 deal 包不得作为权威手牌或财神。
- 首个可信完整手牌包可以锁定本地玩家。
- 胡牌后新局可信手牌包应清空旧弃牌和事件。

## 新规则
### Requirement: 稳定版可信手牌包 SHALL 作为权威手牌入口
当稳定版收到 `source == trusted_hand` 且长度为 13 或 14 的 `hand_update` 时，状态机 SHALL 能将该包作为本地玩家手牌的权威来源。

#### Scenario: 首个可信手牌包接管本地玩家
- WHEN 当前尚未建立可信手牌
- AND 收到某个玩家的可信 13/14 张 `hand_update`
- THEN 状态机 SHALL 将该玩家作为本地玩家
- AND SHALL 填充该玩家手牌
- AND SHALL 标记 `hand_trusted == True`

#### Scenario: 下一局可信手牌包清空旧局状态
- WHEN 上一局存在弃牌、副露、事件或已进入结算/等待可信手牌状态
- AND 收到本地玩家新的可信 13/14 张 `hand_update`
- THEN 状态机 SHALL 清空上一局弃牌、副露、事件、回合残留和摸牌残留
- AND SHALL 保留协议映射与允许保留的财神状态
- AND SHALL 用新手牌填充当前局状态

#### Scenario: 不信任 0x0003 deal 候选手牌
- WHEN 收到 `source == untrusted_round_marker` 的 deal 包
- THEN 状态机 SHALL NOT 将候选手牌作为我方权威手牌
- AND SHALL NOT 触发分析就绪。

## 改动明细
- 文件：`stable/tracker.py`
- 位置：`PacketStateTracker._maybe_lock_local_player`、`PacketStateTracker._is_new_round_hand_update`、`PacketStateTracker._apply_game_event`
- 改前：新局清空要求上一局已 `hand_trusted`，异常等待可信手牌状态下新包可能不清空旧状态。
- 改后：可信 13/14 张本地手牌包在旧局残留/结算/等待可信状态下能作为新局入口并清空旧状态。
