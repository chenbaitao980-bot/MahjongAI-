"""
蒙特卡洛模拟 — 单次模拟核心

最简版模拟（无吃碰杠），2人模式：
1. 自家和对手轮流摸牌、打牌
2. 摸牌后14张检查自摸胡
3. 打牌后检查对手点炮
4. 牌墙空则流局
"""

from __future__ import annotations

import random

from game.simple_state import SimpleGameState, SimpleMeld
from game.win import is_win_int


def _check_win(hand: list[int], melds: list[SimpleMeld], baida_int: int | None) -> bool:
    """纯整数版本胡牌判断。MC热循环专用。"""
    return is_win_int(hand, len(melds), baida_int)


def _check_win_with_discard(
    hand: list[int],
    melds: list[SimpleMeld],
    discard_tile: int,
    baida_int: int | None,
) -> bool:
    """判断对手是否能胡这张 discard_tile（点炮检查）。"""
    return is_win_int(hand + [discard_tile], len(melds), baida_int)


def run_single_simulation(
    init_state: SimpleGameState,
    wall: list[int],
    baida_int: int | None,
    fixed_discard: int | None,
    rng: random.Random,
    policy_fn,
    max_turns: int = 30,
) -> dict:
    """
    执行一次最简版模拟（无吃碰杠，2人模式）。

    Args:
        init_state: 初始游戏状态（含 self_hand[0], enemy_hand[1]）
        wall: 牌墙列表（会被 pop 消耗）
        baida_int: 财神整数ID（或None）
        fixed_discard: 若指定，自家第一手必须打这张牌
        rng: 随机数生成器
        policy_fn: callable(state, player, visible_counts, baida_int, rng) -> discard_tile_int
        max_turns: 最大回合数（默认30，即每人15轮）

    Returns:
        {"result": "self_win"|"enemy_win"|"exhaust", "deal_in": bool, "turns": int}
    """
    # 深拷贝状态，避免修改原始状态
    hands = [list(init_state.hands[0]), list(init_state.hands[1])]
    discards = [list(init_state.discards[0]), list(init_state.discards[1])]
    melds_0 = init_state.melds[0]
    melds_1 = init_state.melds[1]
    meld_count_0 = len(melds_0)
    meld_count_1 = len(melds_1)

    # 深拷贝 wall
    wall = list(wall)

    first_discard_done = False
    num_players = 2

    for turn_idx in range(max_turns):
        player = turn_idx % num_players

        # ---- 1. 摸牌 ----
        if not wall:
            return {"result": "exhaust", "deal_in": False, "turns": turn_idx}

        tile = wall.pop()
        hands[player].append(tile)

        # ---- 2. 自摸检查 ----
        meld_count = meld_count_0 if player == 0 else meld_count_1
        if len(hands[player]) == 14 and is_win_int(hands[player], meld_count, baida_int):
            result_type = "self_win" if player == 0 else "enemy_win"
            return {"result": result_type, "deal_in": False, "turns": turn_idx}

        # ---- 3. 选牌打出 ----
        if player == 0 and not first_discard_done and fixed_discard is not None:
            discard = fixed_discard
            first_discard_done = True
        else:
            # 快速计算可见牌计数
            visible = [0] * 34
            for p in range(num_players):
                for t in hands[p]:
                    visible[t] += 1
                for t in discards[p]:
                    visible[t] += 1
            for m in melds_0:
                for t in m.tiles:
                    visible[t] += 1
            for m in melds_1:
                for t in m.tiles:
                    visible[t] += 1

            is_self = (player == 0)
            discard = policy_fn(
                hands[player],
                melds_0 if player == 0 else melds_1,
                baida_int,
                visible,
                rng,
                is_self=is_self,
            )

        # 从手牌移除
        hands[player].remove(discard)
        discards[player].append(discard)

        # ---- 4. 点炮检查 ----
        opponent = 1 - player
        opponent_meld_count = meld_count_0 if opponent == 0 else meld_count_1
        if is_win_int(hands[opponent] + [discard], opponent_meld_count, baida_int):
            result_type = "self_win" if opponent == 0 else "enemy_win"
            return {"result": result_type, "deal_in": True, "turns": turn_idx}

    return {"result": "exhaust", "deal_in": False, "turns": max_turns}


if __name__ == "__main__":
    import time
    from game.mc_policy import fast_discard_policy
    from game.mc_scorer import score_result

    rng = random.Random(42)

    # 测试1：基本模拟
    self_hand = [0, 0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 33]  # 13张
    enemy_hand = [3, 4, 5, 6, 7, 8, 12, 13, 14, 21, 22, 23, 28]  # 13张

    state = SimpleGameState()
    state.hands[0] = list(self_hand)
    state.hands[1] = list(enemy_hand)

    # 构建简易牌墙（剩余牌）
    from game.mc_dealer import _visible_counts
    from game.state import MeldGroup

    visible = _visible_counts(self_hand, [], [], enemy_hand, [])
    wall = []
    for tile_int in range(34):
        count = max(0, 4 - visible[tile_int])
        wall.extend([tile_int] * count)

    rng.shuffle(wall)

    def policy_fn(hand, melds, baida_int, visible_counts, rng, is_self=True):
        return fast_discard_policy(hand, melds, baida_int, visible_counts, rng)

    # 固定第一手打 33（白板）
    result = run_single_simulation(state, wall, baida_int=33, fixed_discard=33, rng=rng, policy_fn=policy_fn)
    print(f"test1: result={result['result']}, deal_in={result['deal_in']}, turns={result['turns']}")
    assert result["result"] in ("self_win", "enemy_win", "exhaust")

    # 测试2：无固定出牌
    rng2 = random.Random(123)
    wall2 = list(wall)  # 重新用同一牌墙
    rng2.shuffle(wall2)
    state2 = SimpleGameState()
    state2.hands[0] = list(self_hand)
    state2.hands[1] = list(enemy_hand)
    result2 = run_single_simulation(state2, wall2, baida_int=33, fixed_discard=None, rng=rng2, policy_fn=policy_fn)
    print(f"test2: result={result2['result']}, deal_in={result2['deal_in']}, turns={result2['turns']}")

    # 测试3：性能测试
    import time as _time
    rng3 = random.Random(999)
    n_sims = 50
    start = _time.perf_counter()
    for i in range(n_sims):
        r = random.Random(i)
        w = list(wall)
        r.shuffle(w)
        s = SimpleGameState()
        s.hands[0] = list(self_hand)
        s.hands[1] = list(enemy_hand)
        run_single_simulation(s, w, baida_int=33, fixed_discard=33, rng=r, policy_fn=policy_fn)
    elapsed = _time.perf_counter() - start
    avg_ms = (elapsed / n_sims) * 1000
    print(f"test3: {n_sims}次模拟平均 {avg_ms:.1f}ms/次")

    # 测试4：score_result
    for res_type in ("self_win", "enemy_win", "exhaust"):
        score = score_result(res_type)
        print(f"  {res_type} -> score={score}")

    print("mc_simulator.py smoke-test OK")
