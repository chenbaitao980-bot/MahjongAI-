# MahjongAI 项目长期记忆

## 项目架构
- `battle/` — 对战分析核心：状态管理、AI决策请求、视觉识别
- `game/` — 游戏状态与规则引擎
- `vision/` — 图像识别（HOG分类器 + 多模型视觉API）
- `utils/` — 工具函数

## 关键配置
- DeepSeek API 用于麻将策略决策（温度0.2）
- 视觉识别支持 volc/glm/qwen 三 provider，自动降级

## 台州麻将规则关键阈值（已确认）
- **生牌阶段**：剩余牌 ≤30张（约15对）时进入。生牌=本局开始后所有玩家都未打出过的牌。摸到生牌胡牌加1番。
- **黄牌**：剩余牌 ≤16张（约8对）时若仍未有人胡牌，强制流局，不计分，庄家下庄。
- `battle/state.py` 中 `to_payload()` 的 phase 判断逻辑：`"shengjia" if remaining <= 30 else "playing"`

## 台州麻将Prompt关键规则摘要
- 胡牌结构：1对将牌 + 4副牌（面子或刻子），共14张。财神（白板7z）万能，但不能单张作将。
- 计分：胡牌家=(10+基础牌点)×2^总番数；闲家=基础牌点×2^总番数
- 番型：清一色3番、混一色1番、字牌门风碰杠暗刻各1番、无财神1番、财神还原1番
- 能胡不胡/能碰不碰：同一回合内限制，该玩家动牌（吃碰杠摸）后解除
- 一炮一响（截胡）：下家优先
- 包牌三条：生牌阶段包牌、清一色包牌（吃上家三次+）、中发白生张包牌

## 蒙特卡洛模拟（05阶段）关键结论

- **`mc_dealer.py:build_wall_and_enemy_hand()`**：从136张扣除可见牌得`remaining`，拆分为`enemy_hand`（13张）和`wall`（`remaining_tiles_hint`）。防御逻辑：若`enemy_hand_size`不在[10,14]则回退13张。
- **冒烟测试验证原则**：麻将每张牌有4张，不能用`set`成员判断"是否可见"，必须用计数验证（每张牌总出现≤4，总分=136）。
- **`advisor.py:analyze_with_mc()`**：对外暴露**字符串接口**（`hand_14: list[str]`），内部转换为整数处理。调用时注意不要传整数列表。
- **性能基准**：生产环境（`mc_iterations=30, mc_top_k=3`）90次模拟耗时 ~8.5秒，达标（<10秒）。
- **单次模拟性能**：`mc_simulator.py:run_single_simulation()` 约 0.0~0.1ms/次（已优化：纯整数API、无deepcopy、max_turns=30）。
- **`mc_scorer.py:score_result()`**：接收两个参数 `(result_type, deal_in)`，自家胡+10，敌方胡（放铳）-10，敌方胡（自摸）-5，流局0。
- **`mc_simulator.py` 调用计分器的正确处理**：`score = score_result(result["result"], result.get("deal_in", False))`，自摸/放铳/流局均正确计分。
