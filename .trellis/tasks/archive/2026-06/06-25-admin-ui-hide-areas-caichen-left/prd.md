# 后台UI：隐藏弃牌/对手区域 + 财神左置

## Goal

修改 noconfig 后台手牌展示页面，实现：
1. Admin 页面（`/admin`）嵌入的手牌展示页隐藏"我的弃牌"和"对手区域"
2. 财神牌在手牌中始终显示在最左侧

## What I already know

- Admin 页面：`remote/noconfig/app.py` 的 `_build_admin_page()` 生成，通过 iframe 嵌入 `/static/index.html`
- 手牌展示页：`remote/relay/static/index.html`（单文件 HTML+CSS+JS）
- "我的弃牌"在 96-99 行（section class="col"），id="mydiscards"
- "对手"区域在 101-105 行（section class="col"），包含 id="oppmelds" 和 id="oppdiscards"
- 财神标记在 `render()` 函数中（175-186 行）：遍历手牌时对比 `snap.baida_tile`，匹配则加 `caishen` CSS 类
- Admin 页面通过 iframe URL 参数传递 `token` 和 `user_id`（见 app.py 889 行）
- 没有现存的 toggle/hide 机制
- 文件路径：`remote/relay/static/index.html`

## Assumptions (temporary)

- 隐藏弃牌/对手区域只在 admin 页面生效，直接访问 `/` 时仍显示全部区域
- 财神左置的排序不影响实际游戏逻辑（仅展示层排序）
- 无 spec 冲突（纯前端展示层改动，不涉及协议/部署/架构规范）

## Open Questions

- [x] **隐藏方式** → 方式 B：index.html 上加 toggle 开关，默认隐藏弃牌/对手区域
- [x] **财神排序** → 方式 A：仅把财神抽出来放最左，其他牌保持原顺序

## Requirements

1. **Toggle 隐藏弃牌/对手区域**
   - 在 index.html 上添加一个 toggle 开关（checkbox 或按钮），控制"我的弃牌"和"对手区域"的显示/隐藏
   - 默认状态：**隐藏**（admin 页面首次加载时不可见）
   - 用户可手动切换显示/隐藏
   - 状态持久化到 `localStorage`（下次访问记住用户选择）
   - 开关位置：header 栏或 banner 下方

2. **财神左置**
   - 手牌渲染时，财神牌（匹配 `baida_tile`）始终排在最左侧
   - 其他牌保持原有顺序不变
   - 财神牌的 CSS 动画效果（`caishen` 类 + `caishenGlow` 动画）保留
   - 高亮（drawn）逻辑也保留（摸到的牌继续高亮）

## Acceptance Criteria

* [x] index.html 上有可见的 toggle 开关，控制弃牌+对手区域的显隐
* [x] 默认状态为隐藏（首次访问/清除 localStorage 后）
* [x] 切换状态持久化到 localStorage，刷新页面后保持
* [x] 手牌中财神牌始终在最左侧
* [x] 财神牌以外的牌保持原始顺序
* [x] 财神牌的 CSS 动画效果保留
* [x] 摸到的牌高亮效果保留
* [x] 直接访问 `/` 时功能完全一致（toggle 默认隐藏不影响独立使用）

## Definition of Done

* 代码修改后本地测试通过
* 部署到 ECS 验证

## Technical Approach

### 1. Toggle 隐藏实现

在 `index.html` 的 `<header>` 或 banner 下方添加一个 checkbox：
```html
<label style="font-size:12px;color:var(--muted);cursor:pointer">
  <input type="checkbox" id="show-extra"> 显示弃牌/对手
</label>
```

JS 逻辑：
- 读取 `localStorage.getItem('mj_show_extra')`，无值时默认 `false`
- checkbox change 时：
  - `document.getElementById('extra-row').style.display = checked ? 'flex' : 'none'`
  - 写入 `localStorage`
- 给弃牌+对手的外层 div（`.row`）加 `id="extra-row"`

### 2. 财神左置实现

修改 `render()` 函数的手牌渲染逻辑（175-187 行）：

当前逻辑（逐张渲染，财神按出现顺序标记）：
```javascript
hand.forEach(t => {
  const isCaishen = !!(baida && String(t) === String(baida));
  handBox.appendChild(tileEl(t, { ... }));
});
```

改为：先分离财神，再拼接渲染
```javascript
const caishenTiles = hand.filter(t => baida && String(t) === String(baida));
const normalTiles = hand.filter(t => !(baida && String(t) === String(baida)));
const sortedHand = [...caishenTiles, ...normalTiles];
sortedHand.forEach(t => { ... });
```

**注意**：同一局可能出现多个财神（如红中配子），filter 保留所有财神在左侧。

## Decision (ADR-lite)

**Context**: 用户要求两个前端展示层改动：隐藏弃牌/对手区域 + 财神左置

**Decision**:
1. 隐藏方式：方式 B（toggle 开关，默认隐藏），而非方式 A（admin iframe 传参）
   - 理由：toggle 更灵活，用户可随时切换，不依赖 admin 页面嵌入方式
2. 财神排序：方式 A（仅财神左置，其他保持原序），而非方式 B（整体排序）
   - 理由：简单直接，不改变手牌原始顺序（可能隐含玩家摸牌顺序信息）

**Consequences**:
- toggle 状态在 localStorage 中，清除浏览器数据会重置为默认隐藏
- 财神左置仅影响展示，不改变后端 snapshot 数据
- 多财神场景全部排在最左

## Out of Scope

* 修改手牌数据模型或后端 snapshot 格式
* 添加其他区域（如副露）的隐藏控制
* 修改财神牌的视觉样式（仅调整位置）
* Admin iframe URL 传参方式（本次用 toggle 而非 URL 参数）

## Spec Conflicts

* 无冲突。纯前端展示层改动，不涉及 remote-access spec 中的协议/部署/架构规范。

## Technical Notes

* 文件：`remote/relay/static/index.html`（单文件 HTML+CSS+JS）
* Admin iframe URL 格式：`/static/index.html?token=<token>&user_id=<user_id>`
* 可扩展 URL 参数（如 `&hide=discards,opponent`）来控制隐藏
* 财神标记逻辑：`isCaishen = !!(baida && String(t) === String(baida))`
* 手牌渲染在 `render()` 函数 175-187 行

