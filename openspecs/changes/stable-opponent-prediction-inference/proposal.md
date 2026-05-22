# stable-opponent-prediction-inference

## 为什么

稳定版策略面板当前只有启发式的对手手牌/进度文字，不能量化对手听牌范围、隐藏手牌概率和危险牌概率。用户希望在截图红框位置展示“对手手牌预测”，并且实际抓包和模拟出牌走同一套逻辑。同时需要在顶部动态配置粒子数、蒙特卡洛后验次数，并允许加入贝叶斯网络推断对方听牌范围。

## 影响面

- 命中主能力：`stable-reader`
- 预计涉及模块：
  - `game/stable_hard_analysis.py`：接入对手预测结果到稳定版硬分析输出
  - 新增 `game/opponent_inference.py` 或同等模块：统一对手隐藏手牌/听牌范围推断
  - `ui/stable_battle_panel.py`：顶部配置控件和红框预测区域渲染
  - `stable/tracker.py`、`stable/simulator.py`：保持 snapshot 结构兼容，确保抓包/模拟共享输入
  - `config/settings.yaml`、`ui/main_window.py`：配置读取、保存和传递
  - `tests/`：覆盖抓包 snapshot 与模拟 snapshot 共用推断逻辑
- GitNexus impact：实施前必须对将要编辑的函数/类逐一执行 impact，并在 HIGH/CRITICAL 时暂停告知用户。

## 业务规范关系

- 命中的主 spec：`openspecs/specs/stable-reader/spec.md`
- 关系判断：Same Requirement / 追加 Scenario
- 推荐动作：MODIFIED。该需求扩展稳定版抓包读取器的策略分析展示，不新增独立业务能力。

## 改动范围

- 新增统一对手预测引擎，输入只接受公开 `snapshot` 信息。
- 贝叶斯网络用于融合弃牌、副露、动作、局势阶段等证据，输出听牌范围和危险牌概率。
- 粒子/蒙特卡洛后验用于近似对手隐藏手牌分布。
- 模拟模式展示预测时不得读取真实对手手牌，只能使用与抓包一致的公开信息。
- 顶部控制条新增动态配置：预测开关、粒子数、MC 次数、贝叶斯开关、重新预测按钮。
- 红框位置展示结构化预测结果：可信度、样本数、听牌概率、向听分布、高概率持有、可能等待、危险牌、代表组合。

## 验收

- [ ] 抓包模式和模拟模式调用同一套对手预测入口。
- [ ] 模拟模式预测展示不读取真实对手手牌。
- [ ] 顶部可以动态配置粒子数和 MC 次数，并能触发重新预测。
- [ ] 贝叶斯网络可开启/关闭，关闭后仍能显示粒子/MC 后验结果。
- [ ] 红框位置展示结构化预测，且 UI 不阻塞。
- [ ] 已维护 `regression-tests/cases/stable-opponent-prediction-inference.md`。
- [ ] 归档前批量测试接口调用成功。
- [ ] 批量测试返回参数符合期望。
- [ ] `gitnexus detect-changes` 无异常范围外变更。

## Bug 修复记录

无。
