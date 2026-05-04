from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

import cv2

from battle.state import BattleAdvice, BattleState, tile_from_id
from game.state import TileMatch
from utils.paths import data_path


TAIZHOU_RULES_PROMPT = """你是台州麻将实战助手。
你只根据我提供的牌局信息给出建议，不要臆造额外状态。

必须遵守这些规则约束：
1. 台州麻将使用136张牌，无花牌。
2. 胡牌结构按 1 对将 + 4 组面子/刻子 理解。
3. 剩余牌数小于等于15时进入生牌阶段，防守权重明显提高。
4. 一炮一响时按下家、对家、上家的顺序理解优先级。
5. 财神牌会影响搭子、将牌和弃牌价值判断。
6. 回答重点是当前推荐打哪张牌，以及为什么。

请只返回 JSON，对象字段固定为：
recommended_discard, reasoning_summary, risk_notes, candidate_actions
其中 candidate_actions 必须是字符串数组。
"""


VISION_PROVIDERS = {
    "glm": {
        "endpoint": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "default_model": "glm-4.6v-flash",
    },
    "qwen": {
        "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "default_model": "qwen-vl-plus-latest",
    },
}


class BattleService:
    def __init__(self, capture, layout, hand_region, tile_recognizer, config: dict):
        self._capture = capture
        self._layout = layout
        self._hand_region = hand_region
        self._tile_recognizer = tile_recognizer
        self._config = config

    def analyze_opening(self, state: BattleState) -> tuple[BattleState, BattleAdvice]:
        return self._analyze(state, "start")

    def analyze_after_action(
        self,
        state: BattleState,
        trigger_reason: str,
    ) -> tuple[BattleState, BattleAdvice]:
        return self._analyze(state, trigger_reason)

    def capture_self_hand_local(self, state: BattleState) -> tuple[list[TileMatch], str]:
        hand_strip, rois = self._capture_hand_rois(state)
        _ = hand_strip
        local_tiles = [self._tile_recognizer.match_tile(roi) for roi in rois]
        tiles = [tile_from_id(match.tile_id) for match in local_tiles if match.tile_id]
        if not tiles:
            raise RuntimeError("本地识别未得到有效手牌结果，请先完善牌面样本。")
        return tiles, "local"

    def capture_self_hand_with_vision(self, state: BattleState) -> tuple[list[TileMatch], str]:
        provider = self._get_vision_provider()
        provider_key = self._get_vision_api_key(provider)
        if not provider_key:
            raise RuntimeError(f"{provider} 图片模型 API Key 未配置，无法开启 AI 识别。")

        hand_strip, rois = self._capture_hand_rois(state)
        local_tiles = [self._tile_recognizer.match_tile(roi) for roi in rois]
        local_ids = [match.tile_id for match in local_tiles if match.tile_id]
        self._persist_picture_request(
            event_type="picture_request",
            provider=provider,
            model=self._get_vision_model(provider),
            hand_strip=hand_strip,
            local_guess=local_ids,
            response_text="",
        )
        vision_ids = self._recognize_hand_with_vision(
            provider=provider,
            api_key=provider_key,
            model=self._get_vision_model(provider),
            hand_strip=hand_strip,
            local_guess=local_ids,
        )
        if not vision_ids:
            raise RuntimeError(f"{provider} 图片模型未返回可用的手牌结果。")
        return [tile_from_id(tile_id) for tile_id in vision_ids], f"vision:{provider}"

    def capture_self_hand(self, state: BattleState) -> tuple[list[TileMatch], str]:
        if state.ai_recognition_enabled:
            return self.capture_self_hand_with_vision(state)
        return self.capture_self_hand_local(state)

    def persist_round_event(self, state: BattleState, event_type: str, detail: dict | None = None) -> None:
        payload = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event_type": event_type,
            "detail": detail or {},
            "state": state.to_payload(),
        }
        self._write_capped_json("requestdeepseek", payload)

    def _capture_hand_rois(self, state: BattleState):
        frame = self._capture.grab()
        meld_count = len(state.self_melds)
        hand_rect = self._layout.hand_region(meld_count)
        hand_strip = self._capture.grab_from_frame(frame, hand_rect)
        expected = max(1, 14 - meld_count * 3)
        rois, _slots = self._hand_region.segment_tiles_with_slots(hand_strip, expected_count=expected)
        if not rois:
            raise RuntimeError("未能从当前画面切出我方手牌区域。")
        return hand_strip, rois

    def _analyze(self, state: BattleState, trigger_reason: str) -> tuple[BattleState, BattleAdvice]:
        state.mark_analysis(trigger_reason)
        hand_tiles, source = self.capture_self_hand(state)
        state.self_hand = hand_tiles
        state.recognition_source = source

        payload = state.to_payload()
        payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
        raw_text = self._call_deepseek(payload_json, trigger_reason)
        advice_data = self._extract_json_object(raw_text)
        advice = BattleAdvice(
            recommended_discard=str(advice_data.get("recommended_discard", "")),
            reasoning_summary=str(advice_data.get("reasoning_summary", "")),
            risk_notes=str(advice_data.get("risk_notes", "")),
            candidate_actions=[
                str(item) for item in advice_data.get("candidate_actions", []) if str(item).strip()
            ],
            raw_response=raw_text,
        )
        return state, advice

    def _call_deepseek(self, payload_json: str, trigger_reason: str) -> str:
        api_key = self._config.get("deepseek", {}).get("api_key", "").strip()
        if not api_key:
            raise RuntimeError("DeepSeek API Key 未配置，请先在 API 设置里填写。")

        model = self._config.get("deepseek", {}).get("model", "deepseek-chat").strip() or "deepseek-chat"
        body = {
            "model": model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": TAIZHOU_RULES_PROMPT},
                {"role": "user", "content": payload_json},
            ],
        }

        error_message = ""
        raw_text = ""
        try:
            response = self._http_post_json(
                url="https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                body=body,
            )
            raw_text = response["choices"][0]["message"]["content"]
            return raw_text
        except (KeyError, IndexError, TypeError) as exc:
            error_message = f"DeepSeek 返回结构无法解析: {exc}"
            raise RuntimeError(error_message) from exc
        except Exception as exc:
            error_message = str(exc)
            raise
        finally:
            self._persist_deepseek_request(
                trigger_reason=trigger_reason,
                model=model,
                payload=json.loads(payload_json),
                response_text=raw_text,
                error_message=error_message,
            )

    def _recognize_hand_with_vision(
        self,
        provider: str,
        api_key: str,
        model: str,
        hand_strip,
        local_guess: list[str],
    ) -> list[str]:
        provider_conf = VISION_PROVIDERS.get(provider)
        if provider_conf is None:
            raise RuntimeError(f"不支持的视觉模型提供方: {provider}")

        ok, encoded = cv2.imencode(".png", hand_strip)
        if not ok or encoded is None:
            return []

        image_b64 = base64.b64encode(encoded.tobytes()).decode("ascii")
        prompt = (
            "这是台州麻将我方手牌区域截图。"
            "请只输出 JSON，格式为 {\"tiles\": [\"1m\", ...]}。"
            "数组顺序必须与手牌从左到右一致。"
            "牌ID只允许 1-9m, 1-9p, 1-9s, 1-7z。"
            f"本地识别候选为: {local_guess}。"
            "如果本地识别有误，请直接给出你认为正确的顺序。"
        )
        body = {
            "model": model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ],
                }
            ],
        }

        response_text = ""
        error_message = ""
        try:
            response = self._http_post_json(
                url=provider_conf["endpoint"],
                headers={"Authorization": f"Bearer {api_key}"},
                body=body,
            )
            response_text = response["choices"][0]["message"]["content"]
            parsed = self._extract_json_object(response_text)
            tiles = parsed.get("tiles", [])
            if not isinstance(tiles, list):
                return []
            return [str(tile) for tile in tiles if str(tile).strip()]
        except Exception as exc:
            error_message = str(exc)
            raise
        finally:
            self._persist_picture_request(
                event_type="picture_response",
                provider=provider,
                model=model,
                hand_strip=hand_strip,
                local_guess=local_guess,
                response_text=response_text,
                error_message=error_message,
            )

    def _persist_deepseek_request(
        self,
        trigger_reason: str,
        model: str,
        payload: dict[str, Any],
        response_text: str,
        error_message: str = "",
    ) -> None:
        record = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "trigger_reason": trigger_reason,
            "model": model,
            "payload": payload,
            "response_text": response_text,
            "error_message": error_message,
        }
        self._write_capped_json("requestdeepseek", record)

    def _persist_picture_request(
        self,
        event_type: str,
        provider: str,
        model: str,
        hand_strip,
        local_guess: list[str],
        response_text: str,
        error_message: str = "",
    ) -> None:
        picture_dir = data_path("picture")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        base_name = f"{timestamp}_{event_type}"
        image_path = os.path.join(picture_dir, f"{base_name}.png")
        cv2.imwrite(image_path, hand_strip)
        record = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event_type": event_type,
            "provider": provider,
            "model": model,
            "local_guess": local_guess,
            "image_path": image_path,
            "response_text": response_text,
            "error_message": error_message,
        }
        self._write_json_file(picture_dir, record, filename=f"{base_name}.json")
        self._prune_picture_directory(picture_dir, limit=300)

    def _write_capped_json(self, subdir: str, payload: dict[str, Any], filename: str | None = None) -> None:
        target_dir = data_path(subdir)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        output_name = filename or f"{timestamp}.json"
        self._write_json_file(target_dir, payload, output_name)
        self._prune_directory(target_dir, limit=300)

    def _write_json_file(self, directory: str, payload: dict[str, Any], filename: str) -> None:
        output_path = os.path.join(directory, filename)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _prune_directory(self, directory: str, limit: int) -> None:
        paths = [
            os.path.join(directory, name)
            for name in os.listdir(directory)
            if os.path.isfile(os.path.join(directory, name))
        ]
        paths.sort(key=lambda path: os.path.getmtime(path), reverse=True)
        for stale_path in paths[limit:]:
            try:
                os.remove(stale_path)
            except OSError:
                pass

    def _prune_picture_directory(self, directory: str, limit: int) -> None:
        json_paths = [
            os.path.join(directory, name)
            for name in os.listdir(directory)
            if name.lower().endswith(".json") and os.path.isfile(os.path.join(directory, name))
        ]
        json_paths.sort(key=lambda path: os.path.getmtime(path), reverse=True)
        for stale_json in json_paths[limit:]:
            base, _ext = os.path.splitext(stale_json)
            paired_png = base + ".png"
            for stale_path in (stale_json, paired_png):
                try:
                    if os.path.exists(stale_path):
                        os.remove(stale_path)
                except OSError:
                    pass

    def _http_post_json(self, url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            url=url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"网络请求失败: {exc}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"服务返回了非 JSON 内容: {raw[:300]}") from exc

    def _extract_json_object(self, text: str) -> dict[str, Any]:
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
                raise RuntimeError(f"模型未返回可解析 JSON: {text}")
            return json.loads(match.group(0))

    def _get_vision_provider(self) -> str:
        return self._config.get("vision", {}).get("provider", "qwen").strip() or "qwen"

    def _get_vision_model(self, provider: str) -> str:
        vision_cfg = self._config.get("vision", {})
        provider_cfg = vision_cfg.get(provider, {})
        return provider_cfg.get("model", VISION_PROVIDERS[provider]["default_model"]).strip()

    def _get_vision_api_key(self, provider: str) -> str:
        vision_cfg = self._config.get("vision", {})
        provider_cfg = vision_cfg.get(provider, {})
        return provider_cfg.get("api_key", "").strip()
