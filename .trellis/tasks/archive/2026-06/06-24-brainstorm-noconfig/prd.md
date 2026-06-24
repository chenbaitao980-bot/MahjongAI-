# brainstorm: noconfig 后台手牌显示改为麻将图形

## Goal

将 `/admin` 后台页面中手牌展示区的中文文字牌（如"1条"）替换为真实麻将图形，外观参考浙江游戏大厅风格，让玩家能直观识别每张牌。

## What I already know

* 手牌展示逻辑在 `remote/relay/static/index.html` 中的 `tileEl()` 函数（line 124–134）
* 目前渲染方式：白色矩形 div + 数字 + 花色汉字（万/筒/条），字牌直接显示汉字（东/南/西/北/中/发/白）
* 管理页 `/admin` 通过 `<iframe>` 加载该 HTML，URL 含 `token` + `user_id` 参数
* 项目内无现有麻将图片资源（仅有调试截图、视频帧）
* Unicode 标准包含 34 张麻将 emoji（U+1F000~U+1F021），可零资源渲染
* 牌的内部编码：`"3m"` / `"5p"` / `"7s"` / `"1z"`（1z-7z = 东南西北中发白）

## Assumptions (temporary)

* 只改 `index.html` 一个文件，不动后端
* 需要兼容深色背景（当前 --bg: #0f1115）
* 不需要翻牌动画等复杂交互

## Open Questions

* **渲染方式**：三种方案优劣见下方，选哪个？

## Requirements (evolving)

* 所有 34 种牌（1-9m/p/s + 1-7z）显示为图形而非中文文字
* 保留现有的摸牌高亮（.drawn 黄框）和财神红框（.caishen）效果
* 背面牌（.back）保持不变

## Acceptance Criteria (evolving)

* [x] 手牌区每张牌显示对应图形，不再显示纯文字
* [x] 弃牌区（small 尺寸）同样显示图形（`.tile.small` 缩放 img）
* [x] 副露区同样显示图形（`renderMelds` 复用 `tileEl`）
* [x] 现有高亮效果（摸牌 .drawn / 财神 .caishen）正常显示

## Decision (ADR-lite)

**Context**: 用户否决了 SVG 方案（"太low了"），提供了一套 AI 生成的麻将 PNG 图案。
**Decision**: 采用方案 C 变体——本地 PNG 图片集（非 CDN），34 张图 (1-9m/p/s + 1-7z) 缩放到 80×107 透明底，放 `remote/relay/static/tiles/`，随 relay 静态目录一起部署到 ECS，无外网依赖。`tileEl()` 用相对路径 `tiles/Xs.png` 兼容预览(/tiles)与生产(/static/tiles) iframe 两种挂载。
**Consequences**: 视觉最逼真；体积约 300KB（34 图）随服务分发；新增牌面只需替换 PNG。部署脚本 `ecs_deploy_paramiko.py` 增 `CODE_DIRS` 整目录同步能力（可复用）。

## Done

* commit `afbd210` 本地提交（index.html + 34 PNG + 部署脚本）
* 部署到 ECS 8.136.37.136，3 服务 all active
* 生产验证：index.html=200 含 tiles/ 引用；1m.png/7z.png=200；旧 SVG 代码残留=0

## Definition of Done

* 修改 `remote/relay/static/index.html`
* 本地启动后台服务验证显示效果
* 无 JS 报错

## Out of Scope (explicit)

* 不修改后端
* 不添加翻牌动画
* 不改变牌的尺寸规格（40×56px / 30×42px small）

## Technical Notes

* 修改范围：仅 `remote/relay/static/index.html`
* `tileEl()` 是核心渲染函数，替换其 innerHTML 拼接逻辑即可
* CSS `.tile` 类已定义好外形（圆角白底矩形 + 阴影）

## Research Notes

### 三种可行渲染方案

**方案 A：Unicode 麻将 Emoji** (推荐，最简单)

* 直接用 Unicode emoji 替代 num+suit 文字，如 `🀇`=1m, `🀐`=1s, `🀙`=1p, `🀀`=东
* Pros：零资源、代码改动最小（只改 `tileEl()` 内容）、可离线使用
* Cons：emoji 外观依赖系统字体（Windows/Android/iOS 效果各异），有些平台渲染成彩色表情而非麻将风格

**方案 B：SVG 内联绘制**

* 用 JS 生成 SVG，按照麻将图案规则（条=竹竿、筒=圆圈、万=汉字）逐张绘制
* Pros：外观完全可控、无需网络/图片资源、可精确还原任何风格
* Cons：实现复杂（需 SVG 图案 for 每种花色），开发量大

**方案 C：CDN 图片集**（最逼真）

* 从开源麻将图片集（如 `mjpai`、`mahjong-sprite` 或 GitHub 上的 PNG 集）按需加载
* Pros：最接近"浙江游戏大厅"真实外观，视觉最丰富
* Cons：依赖外网 CDN（ECS 服务器+手机需能访问），需确定一个可用 CDN

