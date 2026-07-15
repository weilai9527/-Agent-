from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
import time
from typing import Any

import httpx

from .env import load_env_file, valid_env_value

load_env_file()

from .kimi_followup import call_provider_json, get_task_providers


def _credential_source(provider_name: str) -> str:
    candidates = {
        "qwen": ("QWEN_API_KEY", "DASHSCOPE_API_KEY"),
        "openai": ("OPENAI_API_KEY", "OPENAI_REALTIME_API_KEY"),
        "kimi": ("KIMI_API_KEY", "MOONSHOT_API_KEY"),
        "deepseek": ("DEEPSEEK_API_KEY",),
        "custom": ("AI_API_KEY",),
    }
    for name in candidates.get(provider_name, ()):
        if valid_env_value(name):
            return name
    return "unknown"


def diagnose_report_providers(*, make_request: bool = True) -> list[dict[str, Any]]:
    """Return sanitized report-provider diagnostics without exposing API keys."""
    providers = get_task_providers(
        "REPORT_PROVIDER_ORDER",
        max_tokens_env="AI_REPORT_MAX_TOKENS",
        timeout_env="AI_REPORT_TIMEOUT",
        default_max_tokens=2600,
        default_timeout=60,
        retries_env="AI_REPORT_HTTP_RETRIES",
        default_retries=1,
    )
    results: list[dict[str, Any]] = []
    probe_timeout = float(os.environ.get("AI_PROVIDER_HEALTH_TIMEOUT", "20"))

    for provider in providers:
        result: dict[str, Any] = {
            "provider": provider.name,
            "model": provider.model,
            "base_url": provider.base_url,
            "credential_source": _credential_source(provider.name),
            "configured": True,
            "status": "not_checked",
        }
        if not make_request:
            results.append(result)
            continue

        started = time.perf_counter()
        probe = replace(provider, timeout=probe_timeout, max_tokens=48, retries=0)
        try:
            payload = call_provider_json(
                probe,
                [
                    {"role": "system", "content": "只输出 JSON 对象。"},
                    {"role": "user", "content": '返回 {"status":"ok"}。'},
                ],
            )
            result["status"] = "ok" if payload.get("status") == "ok" else "invalid_response"
            if result["status"] != "ok":
                result["error"] = "供应商返回了 JSON，但未通过健康检查。"
        except (httpx.HTTPError, json.JSONDecodeError, ValueError, IndexError, KeyError) as exc:
            result["status"] = "error"
            result["error"] = str(exc)[:1000]
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)
        results.append(result)

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="检查报告 AI 供应商配置和连通性（不会输出 API Key）。")
    parser.add_argument("--config-only", action="store_true", help="只检查配置，不发送模型请求。")
    args = parser.parse_args()
    results = diagnose_report_providers(make_request=not args.config_only)
    print(json.dumps({"providers": results}, ensure_ascii=False, indent=2))
    if not results:
        return 2
    if args.config_only:
        return 0
    return 0 if any(item.get("status") == "ok" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
