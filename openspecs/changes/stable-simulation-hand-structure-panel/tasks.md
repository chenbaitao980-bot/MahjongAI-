# 任务：stable-simulation-hand-structure-panel

## 实施
- [x] 1. 在 snapshot 或 UI 渲染层补齐响应牌来源说明，区分点炮响应与自摸。
- [x] 2. 在 `StableBattlePanel` 右侧增加手牌结构分组面板。
- [x] 3. 实现仅供展示用的手牌分组辅助函数，输出面子/刻子、搭子、将牌候选、边张或孤张。
- [x] 4. 为模拟响应胡牌来源和手牌结构分组补充最小测试。
- [ ] 5. 调整右侧面板高度比例：`_summary_edit` 和 `_hand_structure_edit` 高度调小，`_hard_calc_edit` 高度调大以完整展示内容。
- [x] 6. 扩展手牌结构展示辅助函数，支持返回多种合理分组方案。
- [x] 7. 在右侧 UI 中渲染多种手牌结构组合，并限制展示数量避免挤压硬算明细。
- [x] 8. 将当前推荐弃牌传入手牌结构展示排序，优先展示推荐牌处于孤张或低质量搭子的组合。
- [x] 9. 增加回归测试：同一手牌中 `2条`/`5条` 都可能作为孤张时，推荐打 `2条` 优先展示 `2条` 为孤张。

## 验证
- [x] 历史 BugFixSpecs 命中的防复发检查项已执行或确认无命中。
- [x] 已维护本 change 的回归测试用例。
- [x] `python -m unittest tests.test_stable_simulator`
- [x] `gitnexus detect-changes --scope all -r mahjong-learning`（已执行；当前工作区含既有 unrelated 变更，整体风险为 critical）
- [ ] 调整后的面板在窗口常规大小下能完整展示硬算明细内容，不出现截断。
- [x] 多组合手牌结构测试通过。
- [x] `gitnexus detect-changes --scope all -r mahjong-learning`（已执行；当前工作区含既有 unrelated 变更，整体风险为 critical）
