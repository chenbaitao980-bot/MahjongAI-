"""
蒙特卡洛模拟 — 统一编排层

整合 evaluator + MC，对 Top K candidates 分别执行 N 次 MC 模拟，
统计 EV / 胜率 / 放铳率，附加到 candidates 的 mc 字段中返回。
"""

from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor

from game.evaluator import analyze_discard_candidates
from game.mc_dealer import build_wall_and_enemy_hand
from game.mc_policy import fast_discard_policy
from game.mc_scorer import score_result
from game.mc_simulator import run_single_simulation
from game.simple_state import SimpleGameState, SimpleMeld
from game.state import MeldGroup
from game.tiles import tile_to_int, int_to_tile, tiles_to_ids


def _make_policy_fn(baida_int: int | None):
    """创建一个闭包 policy_fn，适配 MC 模拟器接口。"""
    def policy_fn(hand, melds, baida, visible_counts, rng, is_self=True):
        return fast_discard_policy(hand, melds, baida, visible_counts, rng)
    return policy_fn


def _simulate_one(args: tuple) -> dict:
    """单次模拟任务（用于并行执行）。"""
    state, wall, baida_int, fixed_discard, seed, policy_fn = args
    rng = random.Random(seed)
    return run_single_simulation(state, wall, baida_int, fixed_discard, rng, policy_fn)


def _run_mc_candidate(args: tuple) -> dict:
    """
    对单个候选牌执行全部 MC 迭代，返回 mc_data 字典。
    模块级函数，可被 ThreadPoolExecutor 并行调用。
    种子策略与串行版完全相同，结果幂等。
    """
    (discard_int, sim_hand, mc_iterations,
     self_melds, self_discards_ints, enemy_discards_ints,
     enemy_melds, baida_int, remaining_tiles, policy_fn) = args

    win_count = 0
    deal_in_count = 0
    exhaust_count = 0
    total_score = 0

    for i in range(mc_iterations):
        rng = random.Random(i * 1000 + discard_int)
        wall, enemy_hand = build_wall_and_enemy_hand(
            sim_hand, self_melds, self_discards_ints,
            enemy_discards_ints, enemy_melds,
            baida_int, remaining_tiles, rng,
        )
        state = SimpleGameState()
        state.hands[0] = list(sim_hand)
        state.hands[1] = list(enemy_hand)
        state.melds[0] = [SimpleMeld(type=m.type, tiles=list(m.tiles)) for m in self_melds]
        state.melds[1] = [SimpleMeld(type=m.type, tiles=list(m.tiles)) for m in enemy_melds]

        result = run_single_simulation(state, wall, baida_int, None, rng, policy_fn)
        score = score_result(result["result"], result.get("deal_in", False))
        total_score += score
        if result["result"] == "self_win":
            win_count += 1
        elif result["result"] == "enemy_win" and result.get("deal_in", False):
            deal_in_count += 1
        else:
            exhaust_count += 1

    n = mc_iterations
    return {
        "ev": round(total_score / n, 2),
        "win_rate": round(win_count / n, 3),
        "deal_in_rate": round(deal_in_count / n, 3),
        "exhaust_rate": round(exhaust_count / n, 3),
        "iterations": n,
    }


def _build_simple_melds(melds: list[MeldGroup]) -> list[SimpleMeld]:
    """将 MeldGroup 列表转为 SimpleMeld 列表。"""
    result = []
    for m in melds:
        tile_ints = [tile_to_int(t) for t in tiles_to_ids(m.tiles)]
        result.append(SimpleMeld(type=m.meld_type, tiles=tile_ints))
    return result


def analyze_with_mc(
    hand_14: list[str],
    self_melds: list[MeldGroup],
    baida: str | None,
    visible_tiles: dict[str, int],
    enemy_discards: list[str],
    enemy_melds: list[MeldGroup],
    self_discards: list[str],
    remaining_tiles: int,
    mc_iterations: int = 100,
    mc_top_k: int = 3,
) -> dict:
    """
    整合 evaluator + MC 分析。

    Args:
        hand_14: 自家14张手牌（字符串列表）
        self_melds: 自家副露列表
        baida: 财神牌ID（如 "7z"）
        visible_tiles: 可见牌统计字典
        enemy_discards: 对手弃牌
        enemy_melds: 对手副露
        self_discards: 自家弃牌
        remaining_tiles: 当前剩余牌墙张数
        mc_iterations: 每个候选的 MC 模拟次数
        mc_top_k: 取 evaluator 前 K 个候选做 MC

    Returns:
        与 analyze_discard_candidates 同结构，但每个 candidate 附加 mc 字段：
        {
            "strategy_mode": str,
            "candidates": [
                {
                    "discard": str,
                    "shanten_after": int,
                    ...
                    "mc": {
                        "ev": float,
                        "win_rate": float,
                        "deal_in_rate": float,
                        "exhaust_rate": float,
                        "iterations": int,
                    }
                }
            ]
        }
    """
    # 1. 调用 evaluator 获取基础候选
    eval_result = analyze_discard_candidates(
        hand_14, self_melds, baida, visible_tiles,
        enemy_discards, enemy_melds, self_discards, remaining_tiles,
    )

    candidates = eval_result.get("candidates", [])
    strategy_mode = eval_result.get("strategy_mode", "balance")

    if not candidates:
        return eval_result

    # 黄牌边界：剩余 <= 16 张时必流局，跳过 MC 模拟
    if remaining_tiles is not None and remaining_tiles <= 16:
        for c in candidates[:mc_top_k]:
            c["mc"] = {
                "ev": 0.0,
                "win_rate": 0.0,
                "deal_in_rate": 0.0,
                "exhaust_rate": 1.0,
                "iterations": 0,
                "skipped_reason": "huangpai (remaining <= 16)",
            }
        eval_result["top_recommendation"] = candidates[0]["discard"] if candidates else None
        return eval_result

    # 高向听：MC 胜率趋近于 0，evaluator 排序已足够，跳过 MC 节省时间
    best_shanten = candidates[0].get("shanten_after", 99)
    if best_shanten >= 2:
        eval_result["top_recommendation"] = candidates[0]["discard"] if candidates else None
        return eval_result

    # 向听 1：模拟价值有限，最多 10 次
    if best_shanten == 1:
        mc_iterations = min(mc_iterations, 10)

    # 2. 取 Top K 候选做 MC
    top_k = candidates[:mc_top_k]

    # 准备公共参数
    baida_int = tile_to_int(baida) if baida else None
    self_hand_ints = [tile_to_int(t) for t in hand_14]
    self_melds_simple = _build_simple_melds(self_melds)
    enemy_discards_ints = [tile_to_int(t) for t in enemy_discards]
    enemy_melds_simple = _build_simple_melds(enemy_melds) if enemy_melds else []
    self_discards_ints = [tile_to_int(t) for t in self_discards]

    # 调整手牌为13张用于模拟（去掉要打的牌）
    policy_fn = _make_policy_fn(baida_int)

    # 3. 并行对每个候选执行 MC 模拟（种子与串行版完全相同，结果幂等）
    task_args = []
    for candidate in top_k:
        discard_int = tile_to_int(candidate["discard"])
        sim_hand = list(self_hand_ints)
        sim_hand.remove(discard_int)
        task_args.append((
            discard_int, sim_hand, mc_iterations,
            self_melds_simple, self_discards_ints, enemy_discards_ints,
            enemy_melds_simple, baida_int, remaining_tiles, policy_fn,
        ))

    with ThreadPoolExecutor(max_workers=len(top_k)) as executor:
        mc_results = list(executor.map(_run_mc_candidate, task_args))

    for candidate, mc_data in zip(top_k, mc_results):
        candidate["mc"] = mc_data

    # 4. 如果有 MC 数据，按 EV 重排 candidates
    mc_candidates = [c for c in top_k if "mc" in c]
    if mc_candidates:
        mc_candidates.sort(key=lambda c: c["mc"]["ev"], reverse=True)
        # 用排序后的 mc_candidates 替换原来的 top_k 位置
        candidates[:len(mc_candidates)] = mc_candidates
        # 更新 top_recommendation
        eval_result["top_recommendation"] = candidates[0]["discard"] if candidates else None

    return eval_result


if __name__ == "__main__":
    import time

    # 构建测试数据
    hand = ["1m", "1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m", "1p", "2p", "3p", "4p"]
    self_melds = []
    baida = "7z"
    visible = {}
    for t in hand:
        visible[t] = visible.get(t, 0) + 1
    enemy_discards = ["5m", "6m", "7p"]
    for t in enemy_discards:
        visible[t] = visible.get(t, 0) + 1
    enemy_melds = []
    self_discards = ["3m", "4m"]
    for t in self_discards:
        visible[t] = visible.get(t, 0) + 1
    remaining_tiles = 80

    # 测试：完整 advisor 流程
    print("Running analyze_with_mc (10 iterations x top 3)...")
    start = time.perf_counter()
    result = analyze_with_mc(
        hand, self_melds, baida, visible,
        enemy_discards, enemy_melds, self_discards,
        remaining_tiles,
        mc_iterations=10,
        mc_top_k=3,
    )
    elapsed = time.perf_counter() - start

    print(f"耗时: {elapsed:.1f}s")
    print(f"策略模式: {result.get('strategy_mode')}")
    print(f"推荐出牌: {result.get('top_recommendation')}")

    for c in result.get("candidates", [])[:5]:
        mc = c.get("mc", {})
        print(f"  打{c['discard']}: 向听={c.get('shanten_after')}, "
              f"进张={c.get('ukeire_count')}, 危险={c.get('danger')}({c.get('danger_level')})"
              + (f", MC: EV={mc.get('ev')}, 胜率={mc.get('win_rate')}, 放铳={mc.get('deal_in_rate')}" if mc else ""))

    print("\nadvisor.py smoke-test OK")
