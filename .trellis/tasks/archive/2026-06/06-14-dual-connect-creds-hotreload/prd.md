# test_dual_connect 凭证自动热加载

## Goal

`test_dual_connect.py` 当前依赖 `data/cloud_credentials.json` 中已有的新鲜 sessionid。
每次 sessionid 过期（flag=72）都需要手动重跑 `grab_credentials.bat`，然后再跑脚本，操作繁琐。

目标：脚本能**自动监听凭证文件的变化**，一旦 relay-hotspot/extractor 更新了
`cloud_credentials.json`，立刻重载并重试连接，无需用户手动介入。

## 方案

**方案A — `--watch` 模式**（选定方案）

`test_dual_connect.py` 增加可选行为：

1. 启动时读一次凭证（行为不变）
2. 若当前凭证已过期（flag=72），进入 **watch 模式**：
   - 每 2s 检查 `cloud_credentials.json` 的 mtime
   - 一旦文件更新，重载 sessionid，立刻重试
   - 打印提示：`[等待新凭证] 请让手机连接 PC 热点并进入游戏...`
3. 若凭证有效（flag=0 正常连接），正常双连循环

不增加 CLI 参数 —— 行为完全自动：每次连接收到 flag=72 就切换到 watch 等新凭证。

## 触发条件

- `flag=72` 时切换到 watch 模式
- 凭证文件 mtime 变化 → 重载 → 重试

## 不改变的部分

- 双连循环逻辑不变
- `SRSPlayerClient` 不变
- `cloud_credentials.json` 格式不变

## 验收

1. sessionid 过期时，终端打印"等待新凭证"提示
2. extractor 更新凭证文件后，脚本自动重载并重试（无需 Ctrl+C 重启）
3. 正常凭证下行为与改前完全一致
