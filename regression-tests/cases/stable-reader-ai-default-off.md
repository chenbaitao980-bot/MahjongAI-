# Regression Cases: stable-reader-ai-default-off

## Batch Test Endpoint
- command_or_url: `python -m unittest tests.test_stable_reader`
- auth: none
- env: local

## Cases
| case_id | 目标 | 入参摘要 | 期望出参关键字段 | 断言 | 来源 | 状态 |
|---|---|---|---|---|---|---|
| stable-config-default-ai-off | 稳定版缺省配置不启用 AI 分析 | `{}` | `stable_reader.deepseek_enabled=false` | equals | user/spec | pass |
| stable-panel-default-ai-off | 稳定版面板未配置时默认不勾选 AI 分析 | 缺省 config 初始化 `StableBattlePanel` | `analysis_options.deepseek_enabled=false` | equals | user/spec | pass |
| stable-panel-explicit-ai-on | 用户显式打开 AI 分析后仍可调用 AI 链路 | `stable_reader.deepseek_enabled=true` | `analysis_options.deepseek_enabled=true` | equals | user/spec | pass |

## Notes
- 本 change 不禁用用户手动勾选 AI 分析。
- 本 change 不影响普通视觉版 AI 识别/DeepSeek 设置。
