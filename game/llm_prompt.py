"""
动态 Prompt 构建

根据当前局面特征（二人模式、生牌阶段等）动态构建 system prompt 和 user prompt。
"""

from __future__ import annotations

import json

from game.tiles import tile_display_name


# 核心规则模板（财神牌名用 {baida} 占位，运行时填入）
_CORE_RULES_TMPL = """【台州麻将核心规则】
1. 共136张牌，2人对局，无花牌。
2. 胡牌结构：1对将牌 + 4副牌（面子或刻子），共14张牌成型。财神（{baida}）为万能牌，可替代任意一张牌凑成牌型，但将牌必须由两张相同牌组成，不能单张财神作将。
3. 计分公式（最高100胡）：
   - 胡牌家牌点 = (10 + 基础牌点) × 2^总番数
   - 闲家牌点 = 基础牌点 × 2^总番数
4. 基础牌点计算：
   - 暗杠：2-8牌16胡，1、9及风字牌32胡
   - 明杠：2-8牌8胡，1、9及风字牌16胡
   - 暗刻：2-8牌4胡，1、9及风字牌8胡
   - 碰（明刻）：2-8牌2胡，1、9及风字牌4胡
   - 对子：门风对、红中对、发财对、白板对各计2胡
   - 胡牌家额外加：对对胡+2胡、嵌档+2胡、自摸+2胡
5. 番型加番：
   - 清一色：3番
   - 混一色：1番
   - 字牌和门风番：红中、发财和自家门风碰/杠/暗刻各计1番（未胡牌时不可用财神替代）
   - 得番数（财神相关）：手中无财神1番；财神还原（将财神当作{baida}本身使用）1番
6. 能胡不胡：同一回合中，若有人点炮且你第一次选择不胡，则该回合内再次有人点炮同一张牌时你也不能胡（自摸除外）。限制仅对该回合生效，该玩家有任何动牌（吃、碰、杠、摸牌）后即解除。
7. 能碰不碰：同一回合中，若有人打出你可碰的牌且你第一次选择不碰，则该回合内再次有人打出这张牌时你也不能碰。限制仅对该回合生效，该玩家有任何动牌（吃、碰、杠、摸牌）后即解除。
8. 一炮一响（截胡）：若某玩家打出的牌同时符合多家胡牌条件，按座位顺序下家优先截胡。2人对局时即按轮序先后判定。"""

# 包牌规则（仅四人模式时启用）
_BAOPAI_RULES = """
【包牌规则】
1. 生牌阶段包牌：进入生牌阶段后，若你打出的牌是生牌（本局无人打出过）并被其他玩家胡牌，则由你承包。
2. 清一色包牌：一家做清一色并吃上家三次或以上，若该家自摸胡牌，则上家承包；若其他家放炮胡牌，则由放炮者承包；若被抢杠胡，则由被抢杠的玩家承包。
3. 中发白生张包牌：
   a. 当胡家胡中(5z)、发(6z)、白(7z)任一张时，若放铳者打出的是中发白的生张，且该放铳者正处于差一手牌即可听牌的状态，则由放铳者承包。
   b. 若某玩家处于"一进一听"（只差一手听牌）状态，且手中有红中(5z)或发财(6z)的单张，此时打出白板(7z)导致其他玩家胡牌，则该打白板的玩家承包。（注：当东、南、西、北、中、发、白作为财神时，此规则不适用）
4. 包牌处罚：被包者本局牌点全部归零，其他玩家正常计算牌点，但本局中所有应支付的牌点均由被包者一人承担。"""

# 二人模式特殊提示
_2P_HINTS = """
【二人模式特殊提示】
- 二人模式下无包牌规则，生牌不需要过度防守。
- 生牌阶段摸到生牌胡牌可额外+1番，进攻价值提升。
- 对手只有一家，副露信息更聚焦，可根据对手花色分布推断其牌型。"""

# 本地分析数据说明
_ANALYSIS_GUIDE = """
【本地分析数据（必须优先使用）】
self.analysis 字段包含本地精确计算结果：
- shanten：当前手牌向听数（-1已胡，0已听，1一向听…）
- candidates：打出每张牌后的评估（shanten_after / ukeire_tiles / ukeire_count / danger / danger_level / potential_fan）
- top_recommendation：综合牌效最优的推荐出牌
- game_features：当前局面特征（is_2p_mode / is_sheng_phase / is_huangpai_risk / opponent_meld_count）

你必须基于这些硬数据做决策，禁止自行重新计算向听数或进张数。
优先原则：shanten_after 最小 → potential_fan 最高 → ukeire_count 最多 → danger 最低。
若 candidates 为空（手牌非14张），则根据 shanten 判断整体局势。

【蒙特卡洛模拟数据（MC统计）】
部分 candidates 附带 mc 字段，包含蒙特卡洛模拟统计结果：
- ev：期望收益（正值代表模拟中总体有利，负值代表不利）
- win_rate：模拟中自家胡牌的概率
- deal_in_rate：模拟中放铳（打出的牌被对手胡）的概率
- exhaust_rate：模拟中流局的概率
- iterations：模拟次数

MC数据用于验证本地分析的结论，特别在多个候选向听数相同时，应优先选择 ev 更高、deal_in_rate 更低的出牌。
MC数据仅供参考，不要仅凭 MC 数据推翻本地分析的牌效结论。"""

# 最优策略框架
_STRATEGY_FRAMEWORK = """
【最优策略框架（按优先级排序）】
A. 向听优先：优先计算当前手牌向听数（shanten），向听越少越优先推进。向听数为0即已听牌，应全力争取胡牌。
B. 价值最大化：在听牌时评估待牌张数 × 番型价值 × 基础牌点加成，选择期望得分最高的听法。注意1、9及风字牌的基础牌点翻倍。无论怎么计算，单局牌点上限为100胡，超过也按100胡计。
C. 风险控制：
   - 剩余牌≤30张时（生牌阶段）：优先打对手已出过的"熟牌"，保留安全牌。
   - 剩余牌≤16张时（黄牌边缘）：极度保守，只打绝对安全的牌。
   - 若对手已打出多张某花色，谨慎再打该花色生牌。
D. 财神运用：财神优先填补高番型（如清一色3番、混一色1番）的缺口，而非凑普通将牌或顺子。注意财神还原（将财神当作白板本身使用）可额外加1番。

【决策流程】
1. 计算当前向听数和最优听牌方案。
2. 判断当前阶段（普通/生牌≤30张/黄牌边缘≤16张）。
3. 评估对手危险度（对手已出牌、碰杠情况、是否在做清一色）。
4. 综合攻守权重输出建议：向听数≤1时偏攻牌，生牌阶段偏守牌，其余情况平衡。

【输出要求】
只返回以下JSON，不要任何解释：
{
  "recommended_discard": "推荐打出的牌（如5m），自摸时填null",
  "strategy_type": "攻牌或守牌或平衡",
  "reasoning_summary": "简明理由，说明向听数、期望胡法和基础牌点估算",
  "risk_notes": "风险说明，如对手危险牌、包牌风险、生牌风险（无风险则留空）",
  "forbidden_discards": ["绝对不能打的牌列表，如已听牌不能打的搭子牌、生牌阶段的生牌等"],
  "candidate_actions": ["候选方案1：如打X保清一色", "候选方案2：如打Y换普通胡"]
}
strategy_type 只允许三个值之一：攻牌、守牌、平衡

【可选规则（游戏房间内可能勾选）】
以下规则取决于当前对局房间设置，若已勾选则生效：
- 无生牌阶段：勾选后无15对（≤30张）阶段，也没有生牌加番和生牌阶段包牌。
- 不死包：勾选后生牌阶段若手上全是生牌则打出生牌被胡可以不包；清一色相关包牌豁免。
- 对对胡4胡：勾选后对对胡由+2胡变为+4胡。
- 撩搭子包牌：勾选后满足撩搭子条件时可以不包。
当前默认按上述规则全部未勾选处理，若实际情况不同请在输入中说明。"""


def build_system_prompt(game_features: dict | None = None) -> str:
    """
    根据游戏特征动态构建 system prompt。

    Args:
        game_features: 包含 is_2p_mode / is_sheng_phase / no_baopai / baida_tile 等特征的字典

    Returns:
        str: 完整的 system prompt
    """
    game_features = game_features or {}
    is_2p = game_features.get("is_2p_mode", True)

    # 财神牌显示名（7z→"白板(7z)"，其他如"2万(2m)"）
    baida_id = game_features.get("baida_tile") or "7z"
    baida = "白板(7z)" if baida_id == "7z" else f"{tile_display_name(baida_id)}({baida_id})"
    core_rules = _CORE_RULES_TMPL.format(baida=baida)

    parts = ["你是台州麻将2人对战专家AI，只根据我提供的真实牌局数据给出最优决策。"]
    parts.append(core_rules)

    if is_2p:
        parts.append(_2P_HINTS)
    else:
        parts.append(_BAOPAI_RULES)

    parts.append(_ANALYSIS_GUIDE)
    parts.append(_STRATEGY_FRAMEWORK)

    return "\n".join(parts)


def build_user_prompt(payload: dict, analysis: dict | None = None) -> str:
    """
    将 to_payload 输出 + analysis 转为 user prompt。

    Args:
        payload: to_payload() 返回的字典
        analysis: _compute_analysis() 返回的字典（可选）

    Returns:
        str: JSON 格式的 user prompt
    """
    prompt_data = dict(payload)
    if analysis:
        # 将 analysis 注入 self 节点，确保大模型能看到
        if "self" in prompt_data and isinstance(prompt_data["self"], dict):
            prompt_data["self"]["analysis"] = analysis
        else:
            prompt_data["analysis"] = analysis

    return json.dumps(prompt_data, ensure_ascii=False)


if __name__ == "__main__":
    # ---- smoke tests ----

    # 1. 二人模式 system prompt 构建
    sys_2p = build_system_prompt({"is_2p_mode": True})
    assert "无包牌" in sys_2p
    assert "生牌不需要过度防守" in sys_2p
    assert "【包牌规则】" not in sys_2p  # 四人模式的完整包牌规则不应出现
    print("test1: 2p system prompt length:", len(sys_2p))

    # 2. 四人模式 system prompt 构建
    sys_4p = build_system_prompt({"is_2p_mode": False})
    assert "【包牌规则】" in sys_4p
    assert "二人模式特殊提示" not in sys_4p
    print("test2: 4p system prompt length:", len(sys_4p))

    # 3. user prompt 构建
    payload = {
        "phase": "playing",
        "self": {"hand": ["1m", "2m"]},
    }
    analysis = {"shanten": 2, "candidates": []}
    user = build_user_prompt(payload, analysis)
    parsed = json.loads(user)
    assert parsed["self"]["analysis"]["shanten"] == 2
    print("test3: user prompt parsed OK")

    print("llm_prompt.py smoke-test OK")
