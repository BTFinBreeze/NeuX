"""LLM Service - DeepSeek API integration with streaming support."""

from __future__ import annotations

import json
import os
from collections.abc import Generator
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()


class LLMService:
    """DeepSeek chat completion service with streaming."""

    def __init__(self) -> None:
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str | Generator[str, None, None]:
        """Send chat completion request. Returns string or generator based on stream flag."""
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        if not self.api_key:
            raise ValueError("API Key 未配置，请检查 .env 文件中的 DEEPSEEK_API_KEY")

        if stream:
            return self._stream_chat(url, headers, payload)
        return self._sync_chat(url, headers, payload)

    def _sync_chat(self, url: str, headers: dict, payload: dict) -> str:
        with httpx.Client(timeout=120.0) as client:
            try:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                self._handle_http_error(e)
            data = response.json()
            return data["choices"][0]["message"]["content"]

    def _stream_chat(
        self, url: str, headers: dict, payload: dict
    ) -> Generator[str, None, None]:
        with httpx.Client(timeout=120.0) as client:
            with client.stream("POST", url, headers=headers, json=payload) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    self._handle_http_error(e)
                for line in response.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    def _handle_http_error(self, error: httpx.HTTPStatusError) -> None:
        status_code = error.response.status_code
        if status_code == 400:
            try:
                detail = error.response.json().get("error", {}).get("message", "")
            except Exception:
                detail = str(error)
            raise ValueError(
                f"请求参数错误。\n\n"
                f"服务端错误：{detail}\n\n"
                f"请检查 .env 文件中的 DEEPSEEK_MODEL 是否为有效模型。\n"
                f"当前配置：{self.model}"
            )
        elif status_code == 401:
            raise ValueError(
                "API Key 无效或未提供。\n\n"
                "请检查 .env 文件中的 DEEPSEEK_API_KEY 是否正确配置。\n"
                "获取地址：https://platform.deepseek.com/api_keys"
            )
        elif status_code == 402:
            raise ValueError(
                "账户余额不足或计费未开通。\n\n"
                "请登录 DeepSeek 平台查看账户余额：\n"
                "https://platform.deepseek.com/billing\n\n"
                "解决方法：\n"
                "1. 在平台完成充值或开通计费\n"
                "2. 使用其他有余额的 API Key"
            )
        elif status_code == 429:
            raise ValueError(
                "请求过于频繁，已被限流。\n\n"
                "请稍后再试，或检查是否超出 API 调用频率限制。"
            )
        else:
            try:
                detail = error.response.json().get("error", {}).get("message", "")
            except Exception:
                detail = str(error)
            raise ValueError(f"API 请求失败 (HTTP {status_code})：{detail}")