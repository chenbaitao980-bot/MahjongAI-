# 修bug：白板被识别成红中

## 问题描述

前端手牌展示页面上，白板 (7z) 显示为"中"，红中 (5z) 显示为"白"——两个字牌的中文显示互换了。

## 根因

`remote/relay/static/index.html:104` 的 JavaScript 字牌映射 `HONOR` 写反了：

```js
// 错误（修复前）：
const HONOR = {1:'东',2:'南',3:'西',4:'北',5:'白',6:'发',7:'中'};

// 正确（修复后）：
const HONOR = {1:'东',2:'南',3:'西',4:'北',5:'中',6:'发',7:'白'};
```

Python 后端所有位置的映射都是正确的（`5z=中, 6z=发, 7z=白`），只有这一个前端页面的 `HONOR` 对象把 5 和 7 的值颠倒了。

## 修复

- 文件：`remote/relay/static/index.html`
- 改动：`HONOR` 对象第 5 和第 7 条目的值互换
- 部署：scp 到 ECS `/opt/mahjong-remote/remote/relay/static/index.html`
- 无需重启服务（静态文件），刷新浏览器即生效

## 验证

已在 ECS 上 grep 确认 `HONOR` 映射正确：`5:'中', 7:'白'`。
