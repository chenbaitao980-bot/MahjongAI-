# brainstorm: 一键启动 bat 脚本

## Goal

在项目根目录放置一个 Windows `.bat` 脚本，用户双击即可一键启动 MahjongAI 应用（包含环境检查、依赖安装、启动 main.py），无需手动打开终端输入命令。

## What I already know

* 项目入口是 `main.py`，启动后是一个 PyQt6 GUI 应用（台州麻将AI视觉识别层）
* 依赖在 `requirements.txt` 中（PyQt6, opencv-python, mss, pyyaml, numpy, pyinstaller, keyboard, pyttsx3, scapy, openpyxl）
* 已有 `build.bat` 用于 PyInstaller 打包（构建 exe），不是启动脚本
* `main.py` 在开发模式下运行，依赖 config/settings.yaml、templates/ 等资源目录
* 项目是纯 Python 项目，Windows 环境
* `utils/paths.py` 中 `data_path()` 在开发模式下以 `utils/` 的父目录为 base，`resource_path()` 同理

## Assumptions (temporary)

* 用户已安装 Python 3.x
* 用户可能没有创建虚拟环境，脚本需处理 venv 创建/激活
* 脚本应检查并自动安装依赖

## Open Questions

* 是否需要自动创建虚拟环境？还是假设用户已有 venv？
* 是否需要包含 ADB/Frida 相关的环境检查（remote/ 模块）？
* 是否需要启动前检查模板文件、config 是否存在？

## Requirements (evolving)

* 根目录下放置一个 `.bat` 脚本，双击即可启动应用
* 脚本自动处理：环境检查 → 依赖安装 → 启动 main.py
* 启动失败时给出清晰的错误提示（如 Python 未安装、依赖缺失等）

## Acceptance Criteria (evolving)

* [ ] 双击 bat 脚本能成功启动 MahjongAI GUI 窗口
* [ ] 缺少依赖时自动安装（或给出清晰指引）
* [ ] Python 未安装时给出明确提示
* [ ] 脚本在项目根目录下，命名直观（如 `start.bat` 或 `run.bat`）

## Definition of Done (team quality bar)

* 脚本可正常运行，无语法错误
* 错误场景有友好的中文提示
* 与现有 `build.bat` 风格一致

## Out of Scope (explicit)

* 不包含 PyInstaller 打包功能（已有 build.bat）
* 不处理 Linux/macOS 平台（仅 Windows）

## Spec Conflicts

* 无冲突

## Technical Notes

* 项目根目录: `e:\claude\project\MahjongAI\MahjongAI\`
* 入口: `main.py`
* 已有 bat 脚本: `build.bat`（打包用）
* `data_path()` 开发模式下以 `utils/` 父目录（即项目根）为 base
