# 交付说明：stable-reader-ai-default-off

## 修复内容
- 稳定版抓包面板“开启 AI 分析”默认不勾选。
- 稳定版配置归一化中 `stable_reader.deepseek_enabled` 默认值改为 `false`。
- 稳定版模拟分析、抓包消息分析、映射保存后重分析这三条路径，在缺省选项缺失时也按 AI 关闭处理。
- 用户显式开启时仍保留原行为：`analysis_options()["deepseek_enabled"] == true`，后续仍会进入 `state_with_ai` 并调用 AI 链路。

## 验证
- `python -m unittest tests.test_stable_reader`
- `python -m py_compile ui/stable_battle_panel.py ui/main_window.py tests/test_stable_reader.py`
- `npx gitnexus detect-changes --scope all -r mahjong-learning`

## GitNexus 影响面
- 本轮目标符号 impact：
  - `StableBattlePanel`: LOW
  - `_ensure_battle_config_defaults`: LOW
  - `_maybe_start_stable_simulation_analysis`: LOW
  - `_on_stable_message`: LOW
  - `_on_stable_mapping_save`: LOW
- `detect-changes` 汇总风险为 critical，原因是当前工作区仍包含上一轮稳定版锁手/等待态修复和 `AGENTS.md`、`CLAUDE.md` 等既有脏改；不完全代表本轮默认关闭 AI 的局部风险。
