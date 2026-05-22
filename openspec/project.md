# Project Baseline

## 项目目标
MahjongAI — 基于视觉识别和 AI 决策的台州麻将辅助分析工具。通过抓包捕获游戏数据，结合图像识别和蒙特卡洛模拟，为玩家提供实时策略建议。

## 技术栈
- Python 3.12
- PyQt5 / PySide6（UI）
- OpenCV + HOG（图像识别）
- DeepSeek API（AI 策略决策）
- Npcap（网络抓包）
- Frida（游戏进程注入）

## 全局约束
- 编码约束：UTF-8
- 提交约束：不主动 git commit / push，等待用户明确指令
- 变更约束：代码修改必须先走 OpenSpec change
- 查询约束：编辑已有 symbol 前优先 GitNexus impact
- 复盘约束：修 bug 前先查 openspec/bugfixspecs，归档时沉淀高频 bug 根因
- 回归约束：每个 change 维护最小回归测试用例，归档前必须批量测试通过

## 非目标
- 不做用户未要求的功能
- 不主动引入重型依赖
- 不涉及自动操作游戏（只提供分析建议）
