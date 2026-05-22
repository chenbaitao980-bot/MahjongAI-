# Delta: stable-only-capture-module

## 与主规范关系
Same Requirement

## 命中的主规范
- Capability: `stable-reader`
- Requirement: `抓包采集` / `分析门控` / `兼容性`
- Scenario: 无独立旧 Scenario

## 变更类型
MODIFIED

## 业务冲突检查
| 维度 | 状态 |
|------|------|
| 主规范 Req 命中 | stable-reader |
| 关系判断 | Same Requirement |
| 其他 active change 撞车 | `stable-reader-hard-analysis-panel` 已处理右侧硬算面板；`stable-capture-training-data` 已处理训练记录开关。本次只收束主 UI 入口和稳定版代码边界，不重叠其未完成任务。 |
| 冲突状态 | 无冲突 |
| 是否允许 ADDED | 否；属于既有稳定版能力的展示和隔离调整 |
| 归档完整性 | 是 |

## 原规则
稳定版读取器通过 tcpdump 或 npcap 抓包，解码为结构化麻将事件并驱动策略分析；`to_battle_state()` 输出格式和 UI 接口签名保持兼容。

## 新规则
应用主界面 SHALL 默认只展示稳定版抓包/分析模块入口。

应用主界面 SHALL NOT 展示非稳定版入口，包括游戏窗口、牌面收集、区域划分、事件收集、识别运行和正式战斗。

非稳定版模块实现 MAY 保留在代码库中，但 SHALL NOT 被主界面默认构建为可见操作入口。

稳定版抓包启动、停止、消息处理和分析刷新逻辑 SHOULD 与非稳定版 UI 模块隔离，避免稳定版运行依赖旧入口展示。

稳定版抓包协议、解析、分析门控和输出格式 SHALL 保持不变。

### 主窗口行为

应用主窗口 SHALL NOT 默认启用系统置顶行为。

应用主窗口 SHALL 支持横向、纵向和角落拖拽缩放。

#### Scenario: 切换到其他软件

- WHEN 用户点击或切换到其他软件
- THEN 稳定版主窗口不得继续保持在其他软件窗口上方

#### Scenario: 调整窗口大小

- WHEN 用户拖拽窗口左右边缘
- THEN 窗口宽度应随拖拽变化
- WHEN 用户拖拽窗口角落
- THEN 窗口宽度和高度应同时随拖拽变化

### 模拟出牌模式

稳定版界面 SHALL 提供“模拟出牌”入口。模拟模式 SHALL NOT 启动抓包线程，但 SHALL 生成与稳定版抓包 snapshot 兼容的模拟局面，并复用稳定版实时数据、硬算分析、推荐出牌和对方预测展示。

#### Scenario: 启动模拟局

- WHEN 用户点击“模拟出牌”
- THEN 系统不得启动 npcap 或 tcpdump 抓包
- AND 系统 SHALL 自动创建一局模拟牌局
- AND UI SHALL 刷新稳定版实时数据、事件流、硬算分析和推荐出牌

#### Scenario: 我方出牌

- WHEN 模拟局轮到我方出牌
- THEN 系统 SHALL 弹出独立出牌框
- AND 出牌框 SHALL 只允许选择我方当前手牌中的牌
- AND 系统 SHOULD 预选或提示当前硬算推荐出牌
- WHEN 用户确认出牌
- THEN 模拟局 SHALL 将该牌写入我方弃牌并推进到电脑回合

#### Scenario: 电脑回合推进

- WHEN 模拟局进入电脑回合
- THEN 电脑 SHALL 自动摸牌并打出一张牌
- AND 对方隐藏手牌不得展示为明文
- AND 系统 SHALL 继续推进到我方摸牌/出牌回合

#### Scenario: 复用真实对战交互

- WHEN 模拟局状态变化
- THEN 稳定版面板 SHALL 使用与真实抓包相同的实时数据区、事件流、策略建议区和硬算面板更新
- AND 当我方手牌、财神、回合可信且我方有效牌为 14 张时，推荐出牌 SHALL 正常显示

### 模拟界面舒适度

稳定版主窗口 SHOULD 使用不局促的默认尺寸。策略建议区 SHOULD 优先把可用空间分配给推荐、硬算和预测文本。模拟出牌弹框 SHALL 以全手牌按钮形式展示当前手牌。

#### Scenario: 默认窗口尺寸

- WHEN 用户打开稳定版主窗口
- THEN 窗口默认宽高应足以舒适展示左右两栏稳定版内容
- AND 用户仍可自由缩放窗口

#### Scenario: 策略建议空间

- WHEN 稳定版面板显示策略建议
- THEN 策略建议区上方摘要不得占用过多空白
- AND 主要垂直空间应提供给策略建议、硬算明细和对方预测文本

#### Scenario: 全手牌出牌弹框

- WHEN 模拟局轮到我方出牌
- THEN 出牌弹框应把当前手牌以按钮网格形式全部展示
- AND 用户点击某张手牌按钮只选择该牌，不得立即确认出牌
- AND 用户点击底部“出牌”按钮后才确认出牌
- AND 推荐牌应有可识别提示

#### Scenario: 暂停查看分析

- WHEN 用户关闭模拟出牌弹框或点击“暂停”
- THEN 模拟局 SHALL 保持当前手牌、弃牌和回合不变
- AND UI SHALL 允许用户停留查看当前分析

### 模拟吃碰杠胡事件

模拟模式 SHALL 支持基础吃、碰、杠、胡事件，并将副露和胡牌结果写入与稳定版 snapshot 兼容的数据结构。

#### Scenario: 模拟胡牌

- WHEN 模拟局当前玩家手牌达到可胡状态
- THEN 系统 SHALL 记录胡牌事件
- AND 模拟局 SHALL 进入结束状态
- AND UI SHALL 在事件流和状态区显示胡牌结果

#### Scenario: 模拟碰牌

- WHEN 对方打出某牌且我方手中有两张同牌
- THEN 系统 SHALL 提供“碰”动作
- WHEN 用户选择“碰”
- THEN 系统 SHALL 从我方手牌移除两张同牌
- AND 从对方弃牌移除被碰牌
- AND 在我方副露区写入碰牌组合

#### Scenario: 模拟吃牌

- WHEN 对方打出普通数牌且我方手牌能组成顺子
- THEN 系统 SHALL 提供“吃”动作
- WHEN 用户选择“吃”
- THEN 系统 SHALL 从我方手牌移除顺子的另外两张牌
- AND 从对方弃牌移除被吃牌
- AND 在我方副露区写入吃牌组合

#### Scenario: 模拟杠牌

- WHEN 我方手牌或对方弃牌触发杠牌条件
- THEN 系统 SHALL 提供“杠”动作
- WHEN 用户选择“杠”
- THEN 系统 SHALL 写入对应杠牌副露
- AND 补摸一张牌后继续模拟回合

#### Scenario: 电脑动作

- WHEN 电脑满足基础胡、碰、杠、吃条件
- THEN 电脑 MAY 自动执行动作
- AND 对方副露区、事件流和手牌计数 SHALL 同步更新

#### Scenario: 过牌

- WHEN 用户选择“过”
- THEN 系统 SHALL 不改变当前手牌和副露
- AND 按模拟回合继续推进

## 改动明细
- 文件: `ui/main_window.py`
- 位置: `_setup_ui()` 及稳定版抓包相关逻辑
- 改前: 主界面展示七个 tab，稳定版与旧视觉/正式战斗模块混在同一窗口中。
- 改后: 主界面只展示稳定版入口；旧模块不显示；稳定版代码尽量抽离到专用模块。
