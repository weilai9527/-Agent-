"""统一封装文本供应商选择、已核准的 HTTPS 地址、请求限额与响应解析。"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from shared.env_values import first_env_value, is_placeholder_value
from shared.provider_settings import approved_endpoint, runtime_settings
from services.usage.provider_calls import ProviderAttemptFailed, current_model_request_id, provider_attempt


class KimiFollowupError(RuntimeError):
    pass


@dataclass(frozen=True)
class FollowupProvider:
    name: str
    api_key: str
    base_url: str
    model: str
    timeout: float
    temperature: float
    max_tokens: int
    retries: int | None = None


def _first_env(*names: str) -> str:
    return first_env_value(*names)


def _valid_key(value: str) -> bool:
    return bool(value and not is_placeholder_value(value))


def _provider_config(name: str, settings=None) -> FollowupProvider | None:
    settings = runtime_settings() if settings is None else settings
    normalized = name.strip().lower()
    if normalized == "kimi":
        api_key = _first_env("KIMI_API_KEY", "MOONSHOT_API_KEY")
        if not _valid_key(api_key):
            return None
        return FollowupProvider(
            name="kimi",
            api_key=api_key,
            base_url=settings.get("KIMI_BASE_URL", "https://api.moonshot.cn/v1").rstrip("/"),
            model=settings.get("KIMI_MODEL", "moonshot-v1-8k"),
            timeout=float(settings.get("KIMI_TIMEOUT", "20")),
            temperature=float(settings.get("KIMI_TEMPERATURE", "0.55")),
            max_tokens=int(settings.get("KIMI_MAX_TOKENS", "160")),
        )
    if normalized == "deepseek":
        api_key = _first_env("DEEPSEEK_API_KEY")
        if not _valid_key(api_key):
            return None
        return FollowupProvider(
            name="deepseek",
            api_key=api_key,
            base_url=settings.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            model=settings.get("DEEPSEEK_MODEL", "deepseek-chat"),
            timeout=float(settings.get("DEEPSEEK_TIMEOUT", "20")),
            temperature=float(settings.get("DEEPSEEK_TEMPERATURE", "0.55")),
            max_tokens=int(settings.get("DEEPSEEK_MAX_TOKENS", "160")),
        )
    if normalized in {"qwen", "dashscope"}:
        api_key = _first_env("QWEN_API_KEY", "DASHSCOPE_API_KEY")
        if not _valid_key(api_key):
            return None
        return FollowupProvider(
            name="qwen",
            api_key=api_key,
            base_url=settings.get("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/"),
            model=settings.get("QWEN_MODEL", "qwen-plus"),
            timeout=float(settings.get("QWEN_TIMEOUT", "20")),
            temperature=float(settings.get("QWEN_TEMPERATURE", "0.55")),
            max_tokens=int(settings.get("QWEN_MAX_TOKENS", "160")),
        )
    if normalized == "openai":
        api_key = _first_env("OPENAI_API_KEY", "OPENAI_REALTIME_API_KEY")
        if not _valid_key(api_key):
            return None
        return FollowupProvider(
            name="openai",
            api_key=api_key,
            base_url=settings.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            model=settings.get("OPENAI_FOLLOWUP_MODEL", "gpt-4o-mini"),
            timeout=float(settings.get("OPENAI_FOLLOWUP_TIMEOUT", "20")),
            temperature=float(settings.get("OPENAI_FOLLOWUP_TEMPERATURE", "0.55")),
            max_tokens=int(settings.get("OPENAI_FOLLOWUP_MAX_TOKENS", "160")),
        )
    if normalized in {"custom", "ai"}:
        api_key = _first_env("AI_API_KEY")
        if not _valid_key(api_key):
            return None
        return FollowupProvider(
            name="custom",
            api_key=api_key,
            base_url=settings.get("AI_BASE_URL", "").rstrip("/"),
            model=settings.get("AI_MODEL", ""),
            timeout=float(settings.get("AI_TIMEOUT", "20")),
            temperature=float(settings.get("AI_TEMPERATURE", "0.55")),
            max_tokens=int(settings.get("AI_MAX_TOKENS", "160")),
        )
    return None


def call_provider_json(provider: FollowupProvider, messages: list[dict[str, str]], *, transport=None) -> dict[str, Any]:
    """调用已配置的供应商，要求响应内容为一个 JSON 对象。"""
    return _extract_json_object(_call_provider_content(provider, messages, json_mode=True, transport=transport))


def _extract_json_object(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("模型未返回 JSON 对象。")
    return parsed


def _response_error_detail(response: httpx.Response) -> str:
    """仅记录供应商状态码，避免响应正文和凭据进入日志。"""
    return f"HTTP {response.status_code}"


def _call_provider_content(
    provider: FollowupProvider,
    chat_messages: list[dict[str, str]],
    *,
    json_mode: bool = False,
    transport=None,
) -> str:
    base_url = approved_endpoint(provider.name, provider.base_url)
    configured_retries = provider.retries if provider.retries is not None else int(os.environ.get("PROVIDER_HTTP_RETRIES", "2"))
    retries = max(0, min(4, configured_retries))
    trust_env = os.environ.get(f"{provider.name.upper()}_TRUST_ENV", "true").strip().lower() not in {"0", "false", "no"}
    payload = {
        "model": provider.model,
        "messages": chat_messages,
        "temperature": provider.temperature,
        "max_tokens": provider.max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    url = f"{base_url}/chat/completions"

    def post():
        headers = {"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"}
        # 该标识用于追踪调用，不能据此重试执行状态不明的 POST 请求。
        if request_id := current_model_request_id():
            headers["X-Client-Request-Id"] = request_id
        if transport is not None:
            return transport(provider, url, headers, payload)
        with httpx.Client(timeout=provider.timeout, trust_env=trust_env, follow_redirects=False) as client:
            return client.post(url, headers=headers, json=payload)

    def parse(response):
        if response.is_redirect or response.is_error:
            raise httpx.HTTPStatusError(_response_error_detail(response), request=response.request, response=response)
        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"{provider.name} 返回的消息结构无效。") from exc
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"{provider.name} 返回的消息内容无效。")
        return content.strip()

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            # 每次重试都独立经过调用上下文。评分进程在这里核对租约和预留，再决定派发或重放结果。
            return provider_attempt(provider, url, payload, attempt, post, parse)
        except (httpx.TransportError, httpx.HTTPStatusError, ProviderAttemptFailed) as exc:
            last_error = exc
            if isinstance(exc, ProviderAttemptFailed) and not exc.retryable:
                raise
            if isinstance(exc, httpx.HTTPStatusError) and not (
                exc.response.status_code == 429 or exc.response.status_code >= 500
            ):
                raise
            if attempt >= retries:
                raise
            time.sleep(0.35 * (2**attempt))

    if last_error:
        raise last_error
    raise KimiFollowupError(f"{provider.name} 请求未完成。")
