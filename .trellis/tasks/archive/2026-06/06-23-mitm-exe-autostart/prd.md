# MahjongMITM.exe 开机自动启动（默认开 + 可关）

## Goal

让 MahjongMITM.exe（apps/router_runtime Windows 托盘版）默认开机自动启动，开机后**静默以管理员身份**拉起（不弹 UAC、无需手点），并允许用户在托盘里关掉开机自启，关掉后重启仍不自启。

## What I already know（探查结论）

- 开机自启**底层早已实现**：`windows/win_admin.py` 的 `set_autostart`/`is_autostart_enabled` 写读 `HKCU\...\Run`，值=exe 路径（仅打包 exe 生效，源码态告警跳过）。
- 已接进托盘 UI：`tray_app.py:174-175` 有可勾选"开机自启"项，`:132-133` 是 toggle handler。
- `tray_app.main()` 启动流程：先 `is_admin()`→否则 `relaunch_as_admin()` 弹 UAC 自提权；提权后 `set_autostart(True)`（第 219 行，**每次启动强制写 True**）；再起托盘 + 全链路。
- 托盘进程运行时已是管理员（自提权过），因此运行时建/删计划任务无需第二次 UAC。

## 两个真实缺陷（本任务实质）

- **坑 A — 关不掉**：`main()` 每次启动强制 `set_autostart(True)`，用户在托盘取消勾选后，下次启动又被改回开，手动开关名存实亡。
- **坑 B — 开机弹 UAC**：`HKCU\Run` 在用户登录后**非提权**拉起，但 exe 必须管理员（绑 53/443 + WinDivert 驱动）→ 开机后立即走 `relaunch_as_admin()` 弹 UAC，要手点"是"才真正起服务，非真正"自动启动"。

## Requirements

- 默认开机自启：全新机器首次运行 exe → 自动建好开机自启项。
- 静默提权：改用**任务计划程序（Scheduled Task）+ 最高权限（highest privileges）**，登录触发，开机后不弹 UAC 直接以管理员运行。
- 可关且持久：托盘"开机自启"勾选/取消 = 建/删计划任务；取消后重启仍不自启。
- 修坑 A：去掉 `main()` 中每次强制开启的逻辑，改为"仅在用户从未设置过时默认建一次"，之后尊重用户选择不覆盖。
- 清理旧机制：清掉残留的 `HKCU\Run` 旧项，避免与计划任务双重自启；`win_admin` 的 HKCU 函数保留但启动流程不再调用。
- 源码态安全：`python -m windows` 跑不报错，仅告警跳过（与现有 `_frozen()` 约定一致）。

## Acceptance Criteria

- [ ] 全新机器首次跑 exe → 计划任务 `MahjongMITM` 自动建好（最高权限、登录触发、动作=exe 路径），重启后无 UAC 静默起服务。
- [ ] 托盘取消"开机自启" → 计划任务被删，重启不自启。
- [ ] 取消后重启再进 exe → 不被强制改回开（坑 A 不复发，"用户已设置过"被记住）。
- [ ] 残留的 `HKCU\Run\MahjongMITM` 旧项在升级后被清掉，不会双启动。
- [ ] 托盘"开机自启"勾选态 = 计划任务实际存在态（`is_autostart_enabled` 查任务而非注册表）。
- [ ] 源码态 `python -m windows` 不抛异常，仅日志告警跳过。
- [ ] 现有 12 个测试仍全绿；为 win_task 建/删/查补单测（schtasks 调用可 mock）。

## Definition of Done

- 代码实现 + 单测（win_task 建/删/查 + main 默认逻辑 + 旧项清理）。
- 现有 windows 测试套件全绿。
- README（apps/router_runtime/README.md）开机自启段落更新。
- 真机验证一次：全新登录会话重启无 UAC 起服务。

## Technical Approach

新增 `windows/win_task.py`：
- `enable_autostart()`：`schtasks /Create /TN MahjongMITM /SC ONLOGON /RL HIGHEST /TR "<exe>" /F`（已是 admin，无需 /RU 提权）。
- `disable_autostart()`：`schtasks /Delete /TN MahjongMITM /F`（不存在则吞 FileNotFound 式静默）。
- `is_autostart_enabled()`：`schtasks /Query /TN MahjongMITM` 返回码判存在。
- `_frozen()` 守卫：源码态告警跳过，与 win_admin 一致。
- `_exe_command()` 复用 `sys.executable`（frozen 才是 exe 自身）。

改 `tray_app.py`：
- `_on_toggle_autostart` 改调 `win_task` 建/删；菜单 `checked` 改调 `win_task.is_autostart_enabled`。
- `main()`：删除无条件 `win_admin.set_autostart(True)`；改为
  - 首跑（"用户从未设置过"标记不存在）→ `win_task.enable_autostart()` + 落首跑标记。
  - 顺手 `win_admin.set_autostart(False)` 清掉历史 `HKCU\Run` 残留项（迁移）。
- "用户是否设置过"标记：用 sidecar 文件（`config._app_dir()` 下，如 `.autostart_inited`）或直接以"计划任务/旧 Run 项是否存在"推断；优先 sidecar，简单可靠。

## Decision (ADR-lite)

**Context**：exe 需管理员，但 `HKCU\Run` 开机非提权 → 每次开机弹 UAC，且 `main()` 强制写 True 让关闭失效。
**Decision**：改用任务计划程序 + 最高权限做静默提权自启；默认建任务（首跑），尊重用户后续取消；迁移期清理 HKCU\Run 残留。
**Consequences**：开机零交互静默起服务；建/删任务由已提权的托盘进程执行不弹额外 UAC；引入对 `schtasks` 的依赖（Windows 自带，零新依赖）；保留 `win_admin` HKCU 函数仅用于迁移清理。

## Out of Scope

- 开机前置/无登录（开机即服务，登录前）运行 —— 仍走 ONLOGON。
- 静默无托盘后台模式。
- 图形化设置面板（仍只托盘右键菜单）。

## Spec Conflicts

无（与 `spec/guides/mitm-connection-stability-guide.md`、`spec/backend/remote-access.md` 一致，未触碰链路/协议层）。

## Technical Notes

- 关键文件：`apps/router_runtime/windows/{win_admin,tray_app,core,config}.py`、`winpack/mahjong_mitm_win.spec`（spec 已含 `uac_admin=True`，不需改）。
- ASCII 纪律：若新增 .bat 必须纯 ASCII（[[feedback_bat_ascii_only]]）；schtasks 命令行避免中文路径问题用引号包。
- 记忆关联：[[noconfig-multiuser-deployed]] 系列为同一 noconfig 体系；本任务仅 Windows 本地形态。
