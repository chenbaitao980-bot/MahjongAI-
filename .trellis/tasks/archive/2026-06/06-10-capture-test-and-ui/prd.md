# 本地抓取测试 bat + 手牌展示 Web 界面

## Goal

1. 一个本地一键 bat，让用户直观测试"数据抓取效果"——跑起本地链路并打开手牌展示页，看自己的手牌实时出现。
2. 一个能在**云服务器**展示抓到的手牌的界面（relay 直接 serve 网页），先在本机测试，云端零改动即可用。

## What I already know

* `/state` 返回的 snapshot 字段够画界面：`phase` / `current_turn` / `remaining_tiles` / `baida_tile` / `drawn_tile` / `players[pid].{hand(tile_id列表,本家已排序), hand_count, discards, melds}` / `events` / `analysis_*`。
* 手牌是 **tile_id 整数(0–33)**，需转 "3m/5p/7s/1z" 或图形；`game/tiles.py` 有 `tile_from_id`，但网页侧需自带 id→字符串映射。
* relay 现有端点 `/register /push /state`（FastAPI, app.py），**没有 HTML 页面路由**，需新增 `GET /`。
* 已有 run_remote.bat(本地真实链路) + watch_state.py(CLI 轮询)。本任务的 Web 页可替代 watch 的"看"。
* 已有桌面 PyQt 面板 ui/stable_battle_panel.py，但那是桌面、非云端，不复用。

## 架构（推荐）

```
浏览器 ──GET /──▶ relay 返回 HTML 页(内嵌 JS)
浏览器 ──轮询 GET /state?token=──▶ relay 返回 snapshot JSON
JS 把 tile_id → 牌面，渲染手牌/弃牌/副露
```
云端：打开 http://云IP:8000/ ；本地：http://127.0.0.1:8000/ 。同一套代码。

## Decisions (用户已选)

* **展示范围 = 本家整桌**：手牌 + 摸牌(高亮) + 我的弃牌 + 我的副露 + 对手弃牌/副露 + 顶部 phase/剩余/百搭。
* **牌面 = CSS 画牌**：白底圆角 + 万/筒/条按色(万红/筒蓝/条绿)、字牌(东南西北白发中)，零图片资源。
* **测试 bat = 起全链路+开浏览器**：复用 run_remote 编排，本地起 relay+extractor，自动打开 http://127.0.0.1:8000/?token=… 看手牌。

## 已确认数据形态

* `players[pid].hand` 是**字符串列表**(如 ["1m","5p","7s","1z"])，界面直接解析，无需 int 映射。
* 字牌：1z东 2z南 3z西 4z北 5z白 6z发 7z中。
* melds: `{"type":..., "tiles":[字符串...]}`；discards: 字符串列表。

## Spec Conflicts

* 无硬冲突。新增 `GET /` 是对 relay 的扩展，不改 `/register /push /state` 契约。

## Out of Scope (tentative)

* AI 出牌建议展示（先只展示抓到的状态）。
* 修复 R1/R2/R3。
* 真实云端部署执行（提供代码，用户自行部署）。

## Technical Notes

* token 鉴权：网页 GET / 可不鉴权(只是壳)，但轮询 /state 需带 token；页面让用户填 token 或 URL 带 ?token=。
* tile_id→字符串映射需与 game/state.ALL_TILE_IDS 顺序一致，嵌进 JS。
* 已读 snapshot 结构(tracker.py:528)、relay app.py。
