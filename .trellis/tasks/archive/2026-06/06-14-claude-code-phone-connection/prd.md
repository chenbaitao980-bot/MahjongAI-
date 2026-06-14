# brainstorm: Claude Code 与手机连接

## Goal

调研开源工具，使 Claude Code（运行在 PC 上）能够与手机建立连接，实现 PC 端 AI 与手机端的交互能力。

## What I already know

* 用户使用 Claude Code 作为 AI 编程助手
* 用户希望 Claude Code 能连通手机（Android/iOS 待确认）
* 当前项目是麻将 AI 项目（MahjongAI），可能涉及手机端游戏交互
* 需要调研开源方案，不限于特定技术栈

## Assumptions (temporary)

* 目标手机可能是 Android（更开放，可编程性强）
* 连接方式可能是 USB/无线/WiFi/蓝牙
* 用途可能是：操控手机、获取手机数据、自动化手机操作

## Open Questions

* 具体使用场景是什么？（操控手机App / 传输文件 / 屏幕镜像 / 获取传感器数据 / 手机跑AI推理）
* 目标手机是 Android 还是 iOS？
* 需要实时性吗？（低延迟 vs 批量操作）
* 要不要在手机端安装 App？（ADB 无需安装 / 第三方工具需要）

## Requirements (evolving)

* 找到 2-4 个可用的开源方案
* 对比各方案的优劣势

## Acceptance Criteria (evolving)

* [ ] 产出调研报告，列出至少 2 个可行的开源方案
* [ ] 每个方案含：原理、优缺点、接入难度、适用场景
* [ ] 给出推荐方案

## Definition of Done (team quality bar)

* 调研报告写入 `research/` 目录
* PRD 更新为完整需求文档
* 用户确认方案选择

## Out of Scope (explicit)

* 暂不涉及实际代码实现
* 暂不涉及 iOS Jailbreak 方案

## Technical Notes

* 待探索
