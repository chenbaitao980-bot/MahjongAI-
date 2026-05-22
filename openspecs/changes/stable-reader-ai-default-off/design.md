# 设计：stable-reader-ai-default-off

## 当前状态
稳定版抓包面板在 `_setup_ui()` 中直接执行 `_deepseek_checkbox.setChecked(True)`，并且 `apply_config()` 使用 `stable.get("deepseek_enabled", True)`。同时 `ui/main_window.py::_ensure_battle_config_defaults()` 会将缺省稳定版配置补成 `deepseek_enabled=True`。

实际效果是：即使用户只是启动稳定版抓包，默认也会进入 `state_with_ai` 模式，触发 LLM 请求。

## 方案
只调整稳定版抓包的默认值：
- UI 控件初始勾选状态改为 false。
- `apply_config()` 缺省读取改为 false。
- 配置归一化 `stable_reader.deepseek_enabled` 缺省改为 false。

如果用户已有配置显式写了 `deepseek_enabled: true`，本次不强制覆盖，仍尊重用户配置。

## 业务规则处理
- 原 Requirement / Scenario：`stable-reader` 的“分析门控”要求满足财神已知、当前回合为我方、我方有效手牌数为 14 时才可触发策略分析。
- 本次处理方式：追加 Scenario，明确“策略分析默认走本地程序链路，AI 分析需用户显式开启”。

## 历史 BugFixSpecs 命中
- 命中文件：无
- 历史根因：无
- 本次防重蹈覆辙措施：验证默认配置和面板默认态均为关闭，且不影响用户显式开启。

## Bug 根因分析
无。

## 回归测试方案
- 用例文件：`regression-tests/cases/stable-reader-ai-default-off.md`
- 批量测试接口 / 命令：`python -m unittest tests.test_stable_reader`
- 入参来源：构造缺省配置。
- 期望出参：`stable_reader.deepseek_enabled == False`，稳定版面板默认选项 `deepseek_enabled == False`。
- 断言规则：equals。

## 回滚方案
将稳定版 `deepseek_enabled` 的三个缺省值恢复为 true。
