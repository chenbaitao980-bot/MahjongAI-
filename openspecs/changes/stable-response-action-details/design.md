# 设计：stable-response-action-details

## 当前状态
模拟器的 `available_response_actions()` 返回动作字典，吃牌动作包含完整组合：
```text
{"type": "chi", "tile": "5p", "tiles": ["3p", "4p", "5p"], "label": "吃 3筒 4筒 5筒"}
```

但 `snapshot()` 当前只导出：
```text
optional_actions = ["chi", "chi", "chi", "pass"]
```

硬算 `_response_advice()` 因此只知道“可以吃”，不知道有几种吃法，也无法分别评估每个吃法。

## 方案
1. `StableSimulationGame.snapshot()` 保持 `optional_actions` 不变，同时新增 `optional_action_details`：
   - 每个元素保留 `type`、`tile`、`tiles`、`label`。
   - 仅保留简单 JSON 友好字段，避免泄漏运行对象。
2. `analyze_snapshot()` / `_response_advice()` 从 `optional_action_details` 中读取具体响应候选：
   - 对每个吃法按给定 `tiles` 模拟移除手牌中的另外两张牌。
   - 分别计算吃后向听和有效进张。
   - 输出最优组合，例如“建议吃 3筒 4筒 5筒”。
3. 当没有明细时保持旧逻辑兼容：
   - 仍可根据 `optional_actions` 推断一种默认吃法。
   - 真实抓包若暂时只有动作类型，不会崩。

## 业务规则处理
- 原 Requirement / Scenario: 稳定版模拟吃碰杠胡事件、策略建议区域。
- 本次处理方式: Bug Against Spec，补全同一响应建议能力。

## 历史 BugFixSpecs 命中
未发现 `openspecs/bugfixspecs` 目录或命中文件。

## Bug 根因分析
- 用户可见现象: 弹框能看到具体吃法，策略建议只显示 `chi / chi / chi / pass`，无法判断吃哪组或是否过。
- 真实失败层: snapshot 数据降维 / 硬算响应建议。
- 根本原因: `optional_actions` 只保留动作类型，丢失 `tiles` 和 `label`。
- 防复发检查项: 构造对方打 `5p` 且我方有三种吃法的局面，断言硬算建议包含具体吃牌组合。

## 回归测试方案
- 用例文件: `regression-tests/cases/stable-response-action-details.md`
- 命令: `python -m unittest tests.test_stable_simulator tests.test_stable_hard_analysis`
- 入参来源: 模拟器构造可吃 `5p` 的手牌。
- 期望出参: snapshot 有 `optional_action_details`；硬算建议包含具体吃法，不只输出类型列表。

## 回滚方案
删除 `optional_action_details` 输出和硬算明细读取逻辑；恢复 `_response_advice()` 原动作类型评估。
