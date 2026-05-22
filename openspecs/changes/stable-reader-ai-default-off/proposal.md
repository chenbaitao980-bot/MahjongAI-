# stable-reader-ai-default-off

## 为什么
当前稳定版抓包暂时不需要大模型介入，但稳定版面板默认勾选“开启 AI 分析”，配置默认值也会把 `stable_reader.deepseek_enabled` 补成 `true`。这会导致抓包分析默认进入 LLM 链路，增加等待、网络依赖和不必要的请求。

## 影响面
- `StableBattlePanel`: LOW。直接影响 `ui/main_window.py` 导入和实例化稳定版面板。
- `_ensure_battle_config_defaults`: LOW。直接影响 `MainWindow.__init__` 和 `_open_api_config_dialog` 配置归一化。

## 业务规范关系
- 命中的主 spec：`openspecs/specs/stable-reader/spec.md`
- 关系判断：Same Requirement
- 推荐动作：追加 Scenario

## 改动范围
- `ui/stable_battle_panel.py`: 稳定版“开启 AI 分析”控件默认不勾选；缺省配置读取时默认 false。
- `ui/main_window.py`: 稳定版配置归一化中 `stable_reader.deepseek_enabled` 默认 false。
- `tests/`: 增加稳定版 AI 默认关闭的最小回归测试。

## 验收
- [ ] 新配置未设置 `stable_reader.deepseek_enabled` 时，稳定版面板默认不勾选“开启 AI 分析”。
- [ ] `_ensure_battle_config_defaults({})` 产出的稳定版配置默认 `deepseek_enabled == False`。
- [ ] 已维护 `regression-tests/cases/stable-reader-ai-default-off.md`。
- [ ] `gitnexus detect-changes` 无异常范围外变更。

## Bug 修复记录
无。
