# brainstorm: mark 财神 in noconfig hand

## Goal

在无配置模式的实时手牌页面中，为财神牌增加明显的视觉标记，帮助用户快速识别当前手牌中的财神。

## What I already know

* 用户希望“无配置模式的手牌里面的财神”带有特别标记。
* 用户指定的视觉效果是“卡牌外面渲染一个红色醒目的框框”。
* 当前手牌页面由 [remote/relay/static/index.html](E:/claude/project/MahjongAI/MahjongAI/remote/relay/static/index.html) 渲染。
* 页面当前已经展示 `snap.baida_tile`，说明前端已经能拿到财神牌值，无需新增后端接口字段。
* 无配置管理页通过 iframe 加载同一份手牌静态页，因此修改该静态页后，无配置模式会直接受益。

## Assumptions (temporary)

* 本次只标记“我的手牌”区域中与 `snap.baida_tile` 相同的牌。
* 本次不改对手区域、副露区、弃牌区的财神表现。
* 如果当前没有可信的 `baida_tile`，则不显示红框。

## Open Questions

* 暂无阻塞问题，按最小可用范围实现。

## Requirements (evolving)

* 在无配置模式手牌展示页中，当前手牌里的财神牌需要有显眼的红色外框。
* 红框应绘制在卡牌外侧，不能遮挡牌面数字和花色。
* 摸到的牌原有高亮效果不能被财神红框破坏。

## Acceptance Criteria (evolving)

* [ ] 当 `hand` 中某张牌与 `baida_tile` 相等时，该牌显示明显红色外框。
* [ ] 非财神牌视觉表现保持不变。
* [ ] 若财神牌恰好也是摸牌，摸牌高亮与财神红框可同时存在。
* [ ] 无 `baida_tile` 或手牌为空时，页面不报错。

## Definition of Done (team quality bar)

* Tests added/updated when practical for this change
* Relevant validation completed for the touched UI
* Docs/notes updated if behavior changes materially

## Out of Scope (explicit)

* 修改协议解析或状态快照结构
* 新增后台开关或配置项
* 为副露、弃牌、对手手牌增加财神特殊样式

## Technical Notes

* 关键文件：`remote/relay/static/index.html`
* 当前手牌由 `render()` 中的 `hand.forEach(...)` 渲染，已有 `drawn` 样式可参考叠加策略。
* 相关规范：`.trellis/spec/backend/remote-access.md`、`.trellis/spec/backend/directory-structure.md`
