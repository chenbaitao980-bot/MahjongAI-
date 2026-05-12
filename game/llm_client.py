"""
LLM API 客户端封装

将 DeepSeek / OpenAI 兼容接口的 HTTP 调用抽象为可复用的客户端。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable


class LLMClient:
    """
    通用 LLM HTTP 客户端。
    默认适配 DeepSeek API，也可用于其他 OpenAI 兼容接口。
    """

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        temperature: float = 0.2,
        base_url: str = "https://api.deepseek.com",
        timeout: int = 15,
    ) -> None:
        if not api_key or not api_key.strip():
            raise RuntimeError("LLM API Key 未配置。")
        self.api_key = api_key.strip()
        self.model = model.strip() or "deepseek-chat"
        self.temperature = temperature
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """
        发送对话请求，返回模型生成的原始文本。

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词（通常为 JSON 格式的牌局数据）

        Returns:
            str: 模型返回的原始文本

        Raises:
            RuntimeError: 网络错误或返回结构异常
        """
        body = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        req = urllib.request.Request(
            url=url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"网络请求失败: {exc}") from exc

        try:
            response = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"服务返回了非 JSON 内容: {raw[:300]}") from exc

        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"LLM 返回结构无法解析: {exc}") from exc

    def chat_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        """流式对话请求，每收到一段文本就调用 on_chunk，最终返回完整文本。"""
        body = {
            "model": self.model,
            "temperature": self.temperature,
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        url = f"{self.base_url}/chat/completions"
        req = urllib.request.Request(
            url=url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        accumulated = ""
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8").rstrip("\r\n")
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk_obj = json.loads(data)
                        delta = chunk_obj["choices"][0]["delta"].get("content") or ""
                        if delta:
                            accumulated += delta
                            if on_chunk is not None:
                                on_chunk(delta)
                    except (json.JSONDecodeError, KeyError, IndexError):
                        pass
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"网络请求失败: {exc}") from exc
        return accumulated


if __name__ == "__main__":
    # 仅做接口可用性验证（需要有效 API Key 才能实际调用）
    try:
        client = LLMClient(api_key="fake-key-for-test")
    except RuntimeError as exc:
        print(f"expected error without api key: {exc}")

    # 验证属性设置
    client2 = LLMClient(api_key="sk-test", model="deepseek-reasoner", temperature=0.5)
    assert client2.model == "deepseek-reasoner"
    assert client2.temperature == 0.5
    print("llm_client.py smoke-test OK")
