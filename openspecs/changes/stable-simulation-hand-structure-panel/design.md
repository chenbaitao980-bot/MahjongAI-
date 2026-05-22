# 设计：stable-simulation-hand-structure-panel

## 当前状态
模拟器在 `available_response_actions()` 中用 `_is_win(responder, extra_tile=tile)` 判断响应胡牌：当对方打出某张牌时，先把该牌临时加入我方手牌，再用 `calc_shanten(...) == -1` 判断是否可胡。截图中的“当前可胡 2筒”因此大概率表示“对方打出的 2筒可点炮胡”，不是“我方摸到 2筒自摸”。

右侧策略区目前只展示硬算文本，用户需要自己从一串手牌里判断哪些已经成面子、哪些只是搭子、将或孤张，调试胡牌/听牌时不够直观。

## 方案
1. 保持胡牌核心算法不动，先在展示层解释当前响应牌来源：
   - 如果 snapshot 处于 pending response 且 `optional_actions` 包含 `hu`，UI 文案显示“响应对方打出的 X 可胡”。
   - 如果是自摸可胡，仍显示当前手牌已成胡或自摸可胡。
2. 在右侧策略建议下方增加“手牌结构”面板：
   - 使用当前 snapshot 的我方手牌和副露。
   - 先显示副露/完整面子或刻子。
   - 再用贪心分组显示顺子、刻子、对子将、两面/坎张/边张搭子、孤张。
   - 每类使用不同颜色，保证快速扫读。
3. 针对多解手牌结构补充展示策略：
   - `stable.hand_structure` 不再只返回第一种贪心拆分，而是枚举有限数量的合理分组方案。
   - UI 展示时保留多种方案，例如同一串牌里 `2条` 可以是孤张，`5条` 也可以是孤张时，两种拆分都应展示。
   - 传入当前推荐弃牌后，对方案排序：推荐弃牌处于孤张优先，其次处于边张/坎张等低质量搭子，再其次才是完整顺子、对子或刻子。
   - 该排序只影响解释展示，不反向影响硬算推荐结果。
4. 分组仅用于 UI 辅助说明，不参与真实胡牌判定或推荐排序。
5. 调整右侧面板高度比例：
   - `_summary_edit`（策略摘要）: `minimumHeight` 从 60 调小至 40，减少占用。
   - `_hand_structure_edit`（手牌结构）: `minimumHeight` 从 140 调小至 80，内容紧凑时足够展示。
   - `_hard_calc_edit`（硬算明细）: `minimumHeight` 从 520 调大至 620，确保向听、听牌列表、最佳进听打法、有效进张、候选重排等所有行都能完整展示不被截断。

## 业务规则处理
- 原 Requirement / Scenario: 稳定版模拟对局、策略建议区域、模拟吃碰杠胡事件。
- 本次处理方式: 追加 Scenario。
- 不是新增独立业务能力；属于稳定版模拟和硬算面板的可解释性增强。

## 历史 BugFixSpecs 命中
未发现 `openspecs/bugfixspecs` 目录或命中文件。

## Bug 根因分析
无。当前尚未确认胡牌算法误判；已知链路说明如下：
```text
对方出牌 -> StableSimulationGame._set_local_pending_response()
-> available_response_actions(extra_tile=对方弃牌)
-> _is_win() 临时加入响应牌
-> snapshot.optional_actions 包含 hu
-> analyze_snapshot() 输出“当前可胡 X”
-> StableBattlePanel 渲染
```

本轮用户反馈的显示问题链路：
```text
snapshot.hand -> build_hand_structure_groups()
-> 单一贪心顺子优先拆分
-> 只返回一种结构
-> _format_hand_structure_html() 只能渲染一种结构
-> 当推荐打 2条 时，UI 没有优先展示 2条 作为孤张/低质量搭子的解释方案
```

## 回归测试方案
- 用例文件: `regression-tests/cases/stable-simulation-hand-structure-panel.md`
- 命令: `python -m unittest tests.test_stable_simulator`
- 入参来源: 构造模拟器固定手牌、对方弃牌 `2p`、pending response。
- 期望出参: optional actions 含 `hu` 时，snapshot/UI 辅助数据能表达响应牌来源；手牌结构分组包含面子/搭子/对子/孤张分类；同一手牌有多种合理拆分时返回多种方案；传入推荐弃牌时优先展示该牌处于孤张或低质量搭子的方案。

## 回滚方案
删除右侧手牌结构面板及相关辅助函数；保留原策略建议渲染。
