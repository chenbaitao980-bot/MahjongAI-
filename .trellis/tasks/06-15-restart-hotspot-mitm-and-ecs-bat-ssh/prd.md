# 修复 restart_hotspot_mitm_and_ecs 支持 SSH 密码交互输入

## Goal

用户运行 `restart_hotspot_mitm_and_ecs.bat` 时，脚本在进度条到 100% 后闪退。根因是 SSH 未配置免密登录，`scp`/`ssh` 命令在无 stdin 的 Hidden 窗口中失败。需要修复脚本以支持交互式密码输入。

## What I already know

* `restart_hotspot_mitm_and_ecs.bat` 调用 PowerShell 脚本 `scripts/restart_hotspot_mitm_and_ecs.ps1`
* PowerShell 脚本使用 `$ErrorActionPreference = "Stop"`，任何命令失败都会直接退出
* `Deploy-Remote` 函数中的 `scp` 和 `ssh` 命令在没有免密时会挂起等待密码输入
* bat 文件以 Hidden 窗口运行（`@echo off` + PowerShell 调用），没有 stdin 交互能力
* 用户已确认：热点已开启，进度条到 100% 后闪退（说明 tar 打包完成，scp/ssh 阶段失败）
* 远程服务器信息：`root@8.136.37.136`，密码用户会提供

## Assumptions (temporary)

* 用户希望保留 bat 文件入口，不想改成纯 PowerShell 手动执行
* 用户愿意在脚本运行时输入密码（交互式）
* 远程服务器使用标准 SSH 端口 22

## Open Questions

* 是否接受使用 `sshpass`/`plink` 等工具，还是必须用原生 OpenSSH？
* 是否需要在脚本中缓存密码（不安全）还是每次运行都输入？

## Requirements

* 修复 `restart_hotspot_mitm_and_ecs.ps1`，使其在没有 SSH 免密时支持密码交互输入
* 保持原有功能不变（热点检查、远程部署、本地 MITM 启动）
* 错误信息要可见，不能闪退

## Acceptance Criteria

* [ ] 未配置 SSH 免密时，脚本提示输入密码并继续执行
* [ ] 已配置 SSH 免密时，脚本无需输入密码直接运行
* [ ] 任何阶段失败时显示错误信息而不是闪退
* [ ] 本地 MITM 启动和验证逻辑保持不变

## Definition of Done

* 脚本在测试环境中验证通过
* 错误处理友好，不闪退

## Out of Scope

* 配置 SSH 免密（脚本只支持交互输入，不自动配置）
* 修改远程部署逻辑本身

## Technical Notes

* 文件：`scripts/restart_hotspot_mitm_and_ecs.ps1`
* 关键函数：`Deploy-Remote` 中的 `Invoke-Checked scp ...` 和 `Invoke-Checked ssh ...`
* 可能方案：使用 `plink` (PuTTY) 支持 `-pw` 参数，或用 PowerShell 的 `Read-Host` 读取密码后通过管道传递
