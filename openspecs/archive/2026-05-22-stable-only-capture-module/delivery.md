# Delivery: stable-only-capture-module

## 已实施

- 主界面 `_setup_ui()` 改为只构建稳定版面板，不再展示游戏窗口、牌面收集、区域划分、事件收集、识别运行、正式战斗等旧入口。
- 新增 `ui/stable_capture_controller.py`，将 `StableCaptureThread` 和稳定版事件文本解析从 `ui/main_window.py` 抽出，稳定版抓包实现与主窗口 UI 构建进一步隔离。
- 保留旧模块文件和旧构建函数，未删除非稳定版实现，避免影响回滚和潜在依赖。
- `MainWindow._update_region_status()`、API 配置保存路径增加旧面板未构建时的保护。

## 验证

- `python -m compileall ui stable game`：通过。
- `gitnexus detect-changes --scope all -r mahjong-learning`：通过，风险级别 high；主要因为稳定版抓包线程抽离影响到抓包运行流和主窗口初始化流。
- Offscreen Qt 实例化：`MainWindow True False`，确认主窗口可创建、稳定版面板存在、正式战斗面板不再默认构建。

## 说明

- 本次未删除旧模块代码，只是不再从主界面默认显示。
- 抓包协议、解析、分析门控和稳定版输出格式未改。

## 追加交付：窗口行为优化

- 移除 `MainWindow` 的 `WindowStaysOnTopHint`，主窗口不再默认置顶。
- 主窗口改为普通窗口 flags，并保留最小化、最大化、关闭按钮。
- 主窗口设置 `setMinimumSize(720, 460)`，不使用固定尺寸。
- 状态栏启用 size grip，稳定版面板设置为横纵 `Expanding`。

## 追加验证

- `python -m compileall ui stable game`：通过。
- Offscreen Qt 实例化：`stable_panel True`、`battle_panel False`、`always_on_top False`、`min_size 720 460`、`size_grip True`。
- `gitnexus detect-changes --scope all -r mahjong-learning`：通过，风险级别 high；包含前序稳定版抽离影响流。

## 追加交付：模拟出牌

- 新增 `stable/simulator.py`，提供 2 人模拟局，输出与稳定版抓包兼容的 `snapshot()`，并可转换为 `BattleState`。
- 新增 `ui/simulated_discard_dialog.py`，轮到我方时弹出独立出牌框，从当前手牌中选择要打出的牌。
- 稳定版面板顶部新增“模拟出牌”按钮。
- `MainWindow` 接入模拟模式：启动模拟时不启动 npcap/tcpdump，停止按钮可退出模拟模式；用户出牌后电脑自动摸牌/出牌，再推进回我方回合。
- 模拟局复用现有稳定版实时数据区、事件流、硬算面板、推荐出牌和对方预测展示。

## 追加验证：模拟出牌

- `python -m compileall ui stable game tests`：通过。
- `python -m unittest tests.test_stable_simulator tests.test_stable_hard_analysis`：通过，8 个测试 OK。
- Offscreen Qt 实例化：`stable_panel True`、`simulate_btn True`、`battle_panel False`。
- `gitnexus detect-changes --scope all -r mahjong-learning`：通过，风险级别 high；主要包含前序稳定版抽离和本次 UI/模拟入口影响流。

## 追加交付：模拟界面舒适度

- 主窗口默认尺寸调整为 `1180x760`，最小尺寸调整为 `980x640`，打开后更适合稳定版左右双栏。
- 策略建议区上方摘要框压缩为最大 `96px`，硬算/策略明细框最小高度提高到 `420px`。
- 模拟出牌弹框改为全手牌按钮网格，按 7 列展示当前手牌；推荐牌用绿色边框高亮。
- 点击手牌按钮即确认出牌，取消按钮保留为“暂停”。

## 追加验证：模拟界面舒适度

- `python -m compileall ui stable game tests`：通过。
- `python -m unittest tests.test_stable_simulator tests.test_stable_hard_analysis`：通过，8 个测试 OK。
- Offscreen Qt 实例化：`window_size 1180 760`、`window_min 980 640`、`discard_buttons 15`、`summary_max 96`、`hard_min 420`。
- `gitnexus detect-changes --scope all -r mahjong-learning`：通过，风险级别 high；主要包含前序稳定版抽离影响流。

## 追加交付：模拟出牌确认

- 模拟出牌弹框改为“选牌 + 出牌”两步：点击手牌只选中并高亮，不关闭弹框、不推进局面。
- 底部新增“出牌”按钮，未选中手牌时不可用；点击后才提交所选牌。
- “暂停”或关闭弹框保持 `reject()`，MainWindow 不调用 `discard_self()`，模拟局状态不变化。

## 追加验证：模拟出牌确认

- `python -m compileall ui stable game tests`：通过。
- `python -m unittest tests.test_simulated_discard_dialog tests.test_stable_simulator tests.test_stable_hard_analysis`：通过，9 个测试 OK。
- Offscreen 弹框检查：存在手牌按钮和“出牌/暂停”按钮，“出牌”初始不可用。
- `gitnexus detect-changes --scope all -r mahjong-learning`：通过，风险级别 high；主要包含前序稳定版抽离影响流。

## 追加交付：模拟吃碰杠胡事件

- `stable/simulator.py` 新增基础胡牌检测：自摸/点炮胡会记录事件并结束模拟局。
- 新增碰、吃、明杠、暗杠合法动作判断和副露写入。
- 电脑回合支持基础自动动作，优先级为胡、杠、碰、吃、过。
- 新增 `ui/simulated_action_dialog.py`，用于我方可选动作：胡/吃/碰/杠/过。
- `MainWindow` 模拟流程接入动作弹框；我方选择吃碰杠后副露区刷新，并继续轮到我方出牌。

## 追加验证：模拟吃碰杠胡事件

- `python -m compileall ui stable game tests`：通过。
- `python -m unittest tests.test_stable_simulator tests.test_simulated_discard_dialog tests.test_stable_hard_analysis`：通过，13 个测试 OK。
- Offscreen 动作弹框实例化：可创建动作按钮。
- `gitnexus detect-changes --scope all -r mahjong-learning`：通过，风险级别 high；主要因为模拟器动作流和 MainWindow 模拟推进流变更。
