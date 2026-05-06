"""
攻守模式判断与综合评分

根据当前局势（向听数、进张数、巡目、对手副露）决定进攻/平衡/防守模式，
并按模式对候选出牌进行综合评分。
"""

from __future__ import annotations

MODE_ATTACK = "attack"
MODE_BALANCE = "balance"
MODE_DEFENSE = "defense"

_LABEL_MAP = {
    MODE_ATTACK: "进攻",
    MODE_BALANCE: "平衡",
    MODE_DEFENSE: "防守",
}


def decide_strategy_mode(
    best_shanten: int,
    best_ukeire: int,
    turn: int,
    enemy_meld_count: int,
) -> str:
    """
    根据当前局势决定攻守模式。

    规则（来自原子笔记）：
      1. 已听牌/已胡牌 → 进攻
      2. 一向听 + 进张充足 + 前中期 → 进攻
      3. 后巡 + 高向听 → 防守
      4. 对手副露多 + 高向听 → 防守
      5. 否则 → 平衡
    """
    if best_shanten <= 0:
        return MODE_ATTACK

    if best_shanten == 1 and best_ukeire >= 16 and turn < 12:
        return MODE_ATTACK

    if turn >= 12 and best_shanten >= 2:
        return MODE_DEFENSE

    if enemy_meld_count >= 2 and best_shanten >= 2:
        return MODE_DEFENSE

    return MODE_BALANCE


def score_candidate(candidate: dict, mode: str) -> float:
    """
    按攻守模式计算候选出牌综合评分。

    candidate 必须包含：
      - shanten_after: int
      - ukeire_count: int
      - danger: int
    """
    shanten = candidate.get("shanten_after", 0)
    ukeire = candidate.get("ukeire_count", 0)
    danger = candidate.get("danger", 0)

    if mode == MODE_ATTACK:
        return -shanten * 100 + ukeire * 4 - danger * 0.8
    elif mode == MODE_DEFENSE:
        return -shanten * 60 + ukeire * 1 - danger * 3
    else:  # balance
        return -shanten * 100 + ukeire * 3 - danger * 1.5


def strategy_label(mode: str) -> str:
    """攻守模式英文转中文标签。"""
    return _LABEL_MAP.get(mode, mode)


def rank_candidates(candidates: list[dict]) -> list[dict]:
    """按综合评分降序排列候选。"""
    return sorted(candidates, key=lambda x: x.get("score", -9999), reverse=True)


if __name__ == "__main__":
    # ---- 自测 ----

    # 1. 听牌 → attack
    assert decide_strategy_mode(0, 20, 15, 3) == MODE_ATTACK

    # 2. 一向听 + 进张16 + 前巡 → attack
    assert decide_strategy_mode(1, 16, 8, 0) == MODE_ATTACK

    # 3. 一向听 + 进张不足 → balance
    assert decide_strategy_mode(1, 10, 8, 0) == MODE_BALANCE

    # 4. 后巡 + 两向听 → defense
    assert decide_strategy_mode(2, 20, 14, 0) == MODE_DEFENSE

    # 5. 对手副露多 + 高向听 → defense
    assert decide_strategy_mode(2, 20, 5, 2) == MODE_DEFENSE

    # 6. 默认 → balance（一向听但进张不足）
    assert decide_strategy_mode(1, 10, 5, 1) == MODE_BALANCE

    # 7. score_candidate 验证
    cand = {"shanten_after": 1, "ukeire_count": 14, "danger": 20}
    s_attack = score_candidate(cand, MODE_ATTACK)
    s_balance = score_candidate(cand, MODE_BALANCE)
    s_defense = score_candidate(cand, MODE_DEFENSE)
    print(f"score test: attack={s_attack:.1f}, balance={s_balance:.1f}, defense={s_defense:.1f}")
    # 进攻模式应比防守模式评分高（因为 danger 低）
    assert s_attack > s_defense

    # 8. 高危险牌在防守模式下应被大幅降权
    cand_danger = {"shanten_after": 1, "ukeire_count": 20, "danger": 80}
    s_danger_defense = score_candidate(cand_danger, MODE_DEFENSE)
    s_danger_attack = score_candidate(cand_danger, MODE_ATTACK)
    print(f"danger test: attack={s_danger_attack:.1f}, defense={s_danger_defense:.1f}")
    assert s_danger_defense < s_danger_attack

    # 9. strategy_label
    assert strategy_label(MODE_ATTACK) == "进攻"
    assert strategy_label(MODE_BALANCE) == "平衡"
    assert strategy_label(MODE_DEFENSE) == "防守"

    print("strategy.py smoke-test OK")
