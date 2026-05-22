# Delta: stable-reader-locked-hand-and-waiting-fixes

## 与主规范关系
Bug Against Spec / Same Requirement。修复 `stable-reader` 已有协议解码、分析门控和策略建议能力的漏判。

## 命中的主规范
- Capability: `stable-reader`
- Requirement: 协议解码、分析门控、策略建议区域
- Scenario: 可信手牌更新、分析门控、稳定版策略建议

## 变更类型
追加 Scenario / 不新增 capability。

## 业务冲突检查
| 维度 | 状态 |
|------|------|
| 主规范 Req 命中 | `openspecs/specs/stable-reader/spec.md` |
| 关系判断 | Bug Against Spec |
| 其他 active change 撞车 | `stable-reader-optional-action-round2-fixes` 有同链路重叠，但不覆盖锁手合法出牌、同牌摸牌回声、空 AI 响应 |
| 冲突状态 | 无冲突 |
| 是否允许 ADDED | 否；追加场景即可 |
| 归档完整性 | 待实现后验证 |

## 原规则
- 稳定版读取器必须仅从可信 `0x0216 hand_update` 的前 `count` 张解码手牌，并保留尾部字节为非手牌元数据。
- 当且仅当满足以下条件时，稳定版读取器才可触发策略分析：财神已知、当前回合为我方、我方有效手牌数为 14。
- 稳定版硬算建议必须基于可信 snapshot 输出；数据不足时明确等待。

## 新规则

### Requirement: 锁手合法出牌约束
稳定版硬算推荐 SHALL 只从当前游戏允许打出的牌生成候选。

#### Scenario: 报听或听牌锁手后只允许打新摸牌
- WHEN snapshot 表示我方已锁手或仅允许打新摸牌
- AND 当前可打集合只包含新摸牌
- THEN `recommended_discard` SHALL 属于该可打集合
- AND `candidates` SHALL NOT 包含不可点击的原手牌
- AND 若无法确认新摸牌，策略建议 SHALL 显示等待/人工确认，而不是从整手牌推荐

### Requirement: 同牌摸牌不得被弃牌回声误吞
稳定版 tracker SHALL 区分弃牌回声和真实摸牌事件。

#### Scenario: 对面打南后我方摸南
- GIVEN 对面刚打出南
- WHEN 随后抓包收到我方可信摸牌南
- THEN 我方手牌 SHALL 增加南
- AND 该摸牌事件 SHALL NOT 被 `_consume_discard_echo` 当作回声吞掉
- AND 后续有效手牌数 SHALL 参与正常分析门控

### Requirement: 空 AI 响应必须恢复等待态
稳定版 AI 分析 SHALL 将空响应视为可恢复失败或本地回退条件。

#### Scenario: DeepSeek 流式响应为空
- WHEN AI 请求结束但返回文本为空
- THEN 系统 SHALL 回退本地程序建议或显示明确错误
- AND UI SHALL 清理“正在分析/等待 AI 返回”的 busy 状态
- AND 请求日志 SHALL 记录空响应原因或 fallback 来源

#### Scenario: 新局切换时清理旧等待状态
- WHEN 收到新的可信开局或可信全量手牌包并判断为新局
- THEN 稳定版面板 SHALL 清理上一局的 pending 分析和等待文案
- AND 下一局 SHALL 基于新 snapshot 重新进入分析门控

## 改动明细
- 文件: `game/stable_hard_analysis.py`
- 位置: `_discard_candidates()` / `analyze_snapshot()`
- 改前: 候选从整手牌生成。
- 改后: 候选从合法出牌集合生成；锁手无法确认时不乱推荐。

- 文件: `stable/tracker.py`
- 位置: `_consume_discard_echo()` / draw 事件处理 / 新局 reset 链路
- 改前: 仅凭上一弃牌玩家不同且牌值相同就吞摸牌。
- 改后: 只吞明确回声，不吞真实同牌摸牌；新局清理等待状态。

- 文件: `battle/service.py` 或 `game/llm_advisor.py`
- 位置: AI 响应处理
- 改前: 空字符串可能被记录为无错误响应。
- 改后: 空响应转 fallback 或明确错误。

- 文件: `ui/main_window.py` / `ui/stable_battle_panel.py`
- 位置: 稳定版分析完成/失败/新局刷新
- 改前: 空响应或跨局可能残留等待态。
- 改后: 清理 busy/pending 并显示明确状态。
