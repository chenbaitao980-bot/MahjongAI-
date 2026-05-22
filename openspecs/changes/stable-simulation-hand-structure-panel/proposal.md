# stable-simulation-hand-structure-panel

## 为什么
用户在模拟对局中看到“当前可胡 2筒”时，不确定这是自摸、点炮响应，还是胡牌判断误判；同时希望把我方手牌结构理清楚，放在 UI 右侧，用不同颜色区分已成面子、搭子、将牌候选、边张/孤张，便于确认“还差什么”。

## 影响面
GitNexus impact:
- `StableBattlePanel`: LOW。直接影响 `ui/main_window.py` 引用，无执行流程扩散。
- `StableSimulationGame`: LOW。直接影响 `ui/main_window.py` 引用，无执行流程扩散。
- `stable.hand_structure.build_hand_structure_groups`: GitNexus 当前未索引到该新增文件 symbol，CLI 返回 UNKNOWN；人工定位直接调用方为 `ui/stable_battle_panel.py` 和 `tests/test_stable_simulator.py`。
- `calc_shanten`: CRITICAL。直接影响 9 个调用点、16 条流程；本 change 默认不修改该核心函数。

## 业务规范关系
- 命中的主 spec: `stable-reader`
- 关系判断: Same Requirement / 追加 Scenario
- 推荐动作: 在稳定版模拟与硬算展示能力下追加 UI 展示和解释，不新增独立能力。

## 改动范围
- `ui/stable_battle_panel.py`: 右侧策略区域增加手牌结构展示；按面子/搭子/将/边张孤张分组并着色；调整右侧面板高度比例，使硬算明细内容完整展示。
- `stable/hand_structure.py`: 将展示用单一贪心分组扩展为可返回多种合理拆分；当存在推荐弃牌时，优先展示该牌作为孤张或低质量搭子的组合。
- `stable/simulator.py`: 如现有 snapshot 缺少响应牌上下文，补充当前响应牌来源，便于 UI 文案解释“可胡 2筒”。
- `tests/test_stable_simulator.py` 或新增对应测试: 覆盖响应胡牌上下文与手牌结构数据。

## 验收
- [x] 当对方打出 `2p` 触发 `hu` 响应时，UI 能明确显示这是“响应对方 2筒可胡”，不是自摸。
- [x] 右侧能显示我方手牌结构分组，成组面子/刻子、搭子、将牌候选、边张/孤张用不同颜色区分。
- [x] 右侧面板高度比例合理：策略摘要和手牌结构面板高度适当缩小，硬算明细面板高度足够展示完整内容。
- [x] 不修改 `calc_shanten`。
- [x] 已维护本 change 的回归测试用例。
- [x] `gitnexus detect-changes --scope all -r mahjong-learning` 无异常范围外变更。
- [ ] 当同一手牌存在多种合理结构拆分时，右侧 SHALL 展示多种组合。
- [ ] 当当前推荐弃牌为 `2s` 且 `2s`/`5s` 均可作为孤张或劣势牌时，手牌结构 SHALL 优先展示 `2s` 处于孤张或劣势牌型的组合。

## Bug 修复记录
| bug_id | 现象 | 首次发现时间 | bugfix_count | 当前状态 |
|---|---|---|---:|---|
| hand-structure-single-arrangement | 手牌结构只显示一种贪心拆分，无法同时展示 `2条`、`5条` 等多种孤张可能；推荐打 `2条` 时没有优先显示 `2条` 处于劣势牌型。 | 2026-05-22 | 1 | open |
