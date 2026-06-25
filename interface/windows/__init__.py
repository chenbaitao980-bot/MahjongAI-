"""windows — noconfig 本地 setup-period MITM 的 Windows 托盘版（开箱即用 exe 源）。

复用 `mahjong_mitm/` 平台中立内核（DNS 响应器 + HTTPS MITM + manifest/NetConf 改写），
新增 Windows 专属三件：
  - win_dns_divert.py：WinDivert 拦游戏硬编码 DNS（命门，从 remote/noconfig/hijack/dns_divert.py 收回）
  - win_hotspot.py    ：WinRT 移动热点常开（PR2）
  - tray_app.py       ：pystray 托盘编排 + UAC 自提权 + 开机自启（PR2）

core.start_all() 是托盘版与源码态共用的编排入口。
设计与决议见 .trellis/tasks/06-23-noconfig-local-exe/prd.md。
"""
