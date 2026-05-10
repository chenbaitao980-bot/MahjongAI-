"""
LLM 统一编排层

整合 evaluator + MC + LLM，提供统一的 get_final_advice() 入口。
包含输出校验、fallback 兜底、无 LLM 模式。
"""

from __future__ import annotations

import json
import re

from game.llm_client import LLMClient
from game.llm_prompt import build_system_prompt, build_user_prompt
from game.tiles import tile_display_name


def validate_llm_output(output: dict, legal_discards: list[str]) -> bool:
    """
    校验 LLM 输出是否合法。

    检查项：
    1. recommended_discard 是否为字符串
    2. recommended_discard 是否在 legal_discards 中（或为空/null）
    3. strategy_type 是否为允许值
    """
    if not isinstance(output, dict):
        return False

    discard = output.get("recommended_discard")
    if discard is not None and discard != "" and legal_discards:
        if str(discard) not in legal_discards:
            return False

    strategy_type = output.get("strategy_type", "")
    if strategy_type and strategy_type not in ("攻牌", "守牌", "平衡"):
        return False

    return True


def fallback_advice(analysis: dict) -> dict:
    """
    LLM 输出不合法时，回退到程序评分最高的候选。

    Args:
        analysis: _compute_analysis() 返回的字典

    Returns:
        dict: 统一结构的 advice
    """
    candidates = analysis.get("candidates", [])
    top = candidates[0] if candidates else {}
    top_discard = top.get("discard", "")

    return {
        "action": "discard",
        "tile": top_discard,
        "reason": f"大模型输出不合法，回退到程序推荐：打 {top_discard}。"
                  f"向听数={top.get('shanten_after')}, 进张={top.get('ukeire_count')}",
        "risk_level": "medium",
        "backup_action": None,
        "confidence": 0.5,
        "source": "program",
    }


def get_program_advice(analysis: dict) -> dict:
    """
    无 LLM 模式：直接返回 analysis 中 top candidate 的建议。

    Args:
        analysis: _compute_analysis() 返回的字典

    Returns:
        dict: 统一结构的 advice
    """
    candidates = analysis.get("candidates", [])
    top = candidates[0] if candidates else {}
    top_discard = top.get("discard", "")
    mode = analysis.get("strategy_mode", "balance")

    _MODE_CN = {"attack": "攻牌", "defense": "守牌", "balance": "平衡"}
    strategy_type_cn = _MODE_CN.get(mode, mode)

    risk_level = "low"
    danger_level = top.get("danger_level", "")
    if danger_level in ("危险", "极危险"):
        risk_level = "high"
    elif danger_level == "中等":
        risk_level = "medium"

    discard_cn = tile_display_name(top_discard) if top_discard else ""
    reason_parts = [f"程序推荐打 {discard_cn}。"]
    if top.get("shanten_after") is not None:
        reason_parts.append(f"打出后向听数={top.get('shanten_after')}。")
    if top.get("ukeire_count"):
        reason_parts.append(f"有效进张={top.get('ukeire_count')}张。")
    if top.get("potential_fan"):
        reason_parts.append(f"潜在番数={top.get('potential_fan')}。")
    reason_parts.append(f"当前策略={strategy_type_cn}。")

    return {
        "action": "discard",
        "tile": top_discard,
        "reason": " ".join(reason_parts),
        "risk_level": risk_level,
        "strategy_type": strategy_type_cn,
        "backup_action": candidates[1]["discard"] if len(candidates) > 1 else None,
        "confidence": 0.7,
        "source": "program",
    }


def _extract_json_object(text: str) -> dict:
    """从模型返回文本中提取 JSON 对象。"""
    if not isinstance(text, str):
        raise RuntimeError("模型未返回文本内容。")
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.S)
        if not match:
            raise RuntimeError(f"模型未返回可解析 JSON: {text[:200]}")
        return json.loads(match.group(0))


def get_final_advice(
    payload: dict,
    analysis: dict,
    api_key: str,
    model: str = "deepseek-chat",
    use_llm: bool = True,
) -> dict:
    """
    总流程：
    1. 获取 analysis（含 candidates / strategy_mode / mc 数据）
    2. 构建 LLM prompt
    3. 调用 LLM（若 use_llm=True）
    4. 校验输出（JSON 格式、recommended_discard 在 candidates 中）
    5. 不合法则 fallback 到程序推荐
    6. 返回统一结构的 advice dict

    Args:
        payload: to_payload() 返回的字典
        analysis: _compute_analysis() 返回的字典
        api_key: DeepSeek API Key
        model: 模型名称
        use_llm: 是否调用大模型

    Returns:
        dict: 统一结构的 advice
    """
    candidates = analysis.get("candidates", [])
    legal_discards = [c.get("discard", "") for c in candidates]

    if not use_llm:
        return get_program_advice(analysis)

    # candidates 为空说明手牌异常（张数不对或识别错误），无法校验 LLM 输出，直接 fallback
    if not candidates:
        advice = fallback_advice(analysis)
        advice["reason"] += " [candidates 为空，手牌异常或识别错误，跳过 LLM]"
        return advice

    # 构建 prompt
    game_features = analysis.get("game_features", {})
    system_prompt = build_system_prompt(game_features)
    user_prompt = build_user_prompt(payload, analysis)

    # 调用 LLM
    try:
        client = LLMClient(api_key=api_key, model=model)
        raw_text = client.chat(system_prompt, user_prompt)
    except Exception as exc:
        # LLM 调用失败，fallback 到程序推荐
        advice = fallback_advice(analysis)
        advice["reason"] += f" [LLM 调用失败: {exc}]"
        return advice

    # 解析输出
    try:
        llm_output = _extract_json_object(raw_text)
    except Exception as exc:
        advice = fallback_advice(analysis)
        advice["reason"] += f" [LLM 输出解析失败: {exc}]"
        advice["raw_response"] = raw_text[:500]
        return advice

    # 校验输出
    if not validate_llm_output(llm_output, legal_discards):
        advice = fallback_advice(analysis)
        advice["reason"] += " [LLM 输出未通过校验，recommended_discard 不在候选列表中]"
        advice["raw_response"] = raw_text[:500]
        return advice

    # 构造最终 advice
    discard = llm_output.get("recommended_discard") or ""
    risk_level = "medium"
    strategy_type = llm_output.get("strategy_type", "")
    if strategy_type == "守牌":
        risk_level = "high"
    elif strategy_type == "攻牌":
        risk_level = "low"

    return {
        "action": "discard" if discard else "none",
        "tile": discard,
        "reason": llm_output.get("reasoning_summary", ""),
        "risk_level": risk_level,
        "strategy_type": strategy_type,
        "backup_action": llm_output.get("candidate_actions", [None])[0],
        "confidence": 0.85,
        "source": "llm",
        "forbidden_discards": llm_output.get("forbidden_discards", []),
        "risk_notes": llm_output.get("risk_notes", ""),
        "raw_response": raw_text,
    }


if __name__ == "__main__":
    # ---- smoke tests ----

    # 1. validate_llm_output
    assert validate_llm_output({"recommended_discard": "5m"}, ["5m", "3p"]) is True
    assert validate_llm_output({"recommended_discard": "9m"}, ["5m", "3p"]) is False
    assert validate_llm_output({"recommended_discard": None}, ["5m"]) is True
    assert validate_llm_output({"strategy_type": "攻牌"}, []) is True
    assert validate_llm_output({"strategy_type": "乱写"}, []) is False
    print("test1 validate_llm_output OK")

    # 2. fallback_advice
    analysis = {
        "candidates": [
            {"discard": "5m", "shanten_after": 1, "ukeire_count": 12},
        ],
        "strategy_mode": "attack",
    }
    fb = fallback_advice(analysis)
    assert fb["tile"] == "5m"
    assert fb["source"] == "program"
    print("test2 fallback_advice OK")

    # 3. get_program_advice
    pa = get_program_advice(analysis)
    assert pa["tile"] == "5m"
    assert pa["source"] == "program"
    assert "向听数=1" in pa["reason"]
    print("test3 get_program_advice OK")

    # 4. _extract_json_object
    assert _extract_json_object('{"a": 1}')["a"] == 1
    assert _extract_json_object('```json\n{"b": 2}\n```')["b"] == 2
    try:
        _extract_json_object("no json here")
        assert False
    except RuntimeError:
        pass
    print("test4 _extract_json_object OK")

    print("llm_advisor.py smoke-test OK")
