# Regression Cases: stable-panel-layout-optimization

## Batch Test Endpoint
- command_or_url: 人工 UI 验证（纯布局变更，无断言接口）
- auth: N/A
- env: 本地运行 main.py，进入稳定版对战面板

## Cases
| case_id | 目标 | 入参摘要 | 期望出参关键字段 | 断言 | 来源 | 状态 |
|---|---|---|---|---|---|---|
| layout-01 | 手牌结构多组合自适应高度 | 启动模拟对局，触发多种组合手牌 | 手牌结构区域展示组合1/2/3，无截断 | 目视检查 | user | pending |
| layout-02 | 硬算明细两列布局 | 正常对局产生硬算分析 | 左列展示状态类信息，右列展示建议类信息 | 目视检查 | user | pending |
| layout-03 | 候选重排全宽展示 | 正常对局产生候选重排 | 候选重排在两列下方全宽展示 | 目视检查 | user | pending |
| layout-04 | 单组合手牌结构紧凑展示 | 手牌只有一种合理拆分 | 手牌结构区域高度紧凑，不浪费空间 | 目视检查 | user | pending |

## Notes
- 纯 UI 布局变更，无业务逻辑断言接口，采用人工验证方式
- 验证要点：窗口常规大小（约 1200x800）下右侧策略区域无需滚动即可看到全部内容
