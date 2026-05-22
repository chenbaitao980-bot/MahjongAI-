# Delta: stable-reader-ai-default-off

## 与主规范关系
Same Requirement

## 命中的主规范
- Capability: `stable-reader`
- Requirement: `分析门控`
- Scenario: 无

## 变更类型
追加 Scenario

## 业务冲突检查
| 维度 | 状态 |
|------|------|
| 主规范 Req 命中 | `分析门控` |
| 关系判断 | Same Requirement |
| 其他 active change 撞车 | 无 |
| 冲突状态 | 无冲突 |
| 是否允许 ADDED | 否；属于稳定版分析门控的默认行为补充 |
| 归档完整性 | ✅ |

## 原规则
当且仅当满足以下条件时，稳定版读取器才可触发策略分析：财神已知、当前回合为我方、我方有效手牌数为 14。

## 新规则
稳定版抓包的 AI 分析默认关闭。策略分析默认使用本地程序链路；只有用户显式勾选“开启 AI 分析”或配置显式启用时，才允许进入 LLM 链路。

## 改动明细
- 文件：`ui/stable_battle_panel.py`
- 位置：稳定版 AI 分析复选框初始化与配置应用。
- 改前：缺省勾选并按 `deepseek_enabled=True` 读取。
- 改后：缺省不勾选并按 `deepseek_enabled=False` 读取。

- 文件：`ui/main_window.py`
- 位置：`_ensure_battle_config_defaults`
- 改前：缺省 `stable_reader.deepseek_enabled=True`。
- 改后：缺省 `stable_reader.deepseek_enabled=False`。
