"""
蒙特卡洛模拟简化计分

计分规则：
- 自家胡牌（自摸或点炮）：+10
- 自家生牌胡牌（摸到生牌胡牌）：+12（生牌阶段额外+1番的收益体现）
- 敌方胡牌：-5
- 敌方放铳胡牌：-10
- 流局（牌墙抽空）：0
"""

from __future__ import annotations

SCORE_SELF_WIN = 10
SCORE_SELF_SHENG_WIN = 12  # 生牌胡牌加分
SCORE_ENEMY_WIN = -5
SCORE_DEAL_IN = -10
SCORE_EXHAUST = 0


def score_result(result_type: str, deal_in: bool = False, is_sheng_win: bool = False) -> int:
    """
    根据模拟结果类型返回简化分数。

    Args:
        result_type: "self_win" | "enemy_win" | "exhaust"
        deal_in: 是否为放铳导致的敌方胡牌（由我方打出的牌被胡）
        is_sheng_win: 是否为摸到生牌后的胡牌（生牌阶段额外+1番）

    Returns:
        int: 分数
    """
    if result_type == "self_win":
        return SCORE_SELF_SHENG_WIN if is_sheng_win else SCORE_SELF_WIN
    if result_type == "enemy_win":
        return SCORE_DEAL_IN if deal_in else SCORE_ENEMY_WIN
    return SCORE_EXHAUST


if __name__ == "__main__":
    assert score_result("self_win") == 10
    assert score_result("self_win", is_sheng_win=True) == 12
    assert score_result("enemy_win") == -5
    assert score_result("enemy_win", deal_in=True) == -10
    assert score_result("exhaust") == 0
    print("mc_scorer.py smoke-test OK")
