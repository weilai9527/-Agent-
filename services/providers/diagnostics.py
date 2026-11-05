"""向部署允许的报告供应商发送固定的诊断问题，不读取面试、简历或学校数据。"""
import math
import os
import ssl
import time
from dataclasses import replace

import httpx

from shared.provider_settings import FIELDS, runtime_settings
from shared.text_provider import _provider_config, call_provider_json


SECRET_FLAGS = {
    "reportQwen": ("QWEN_API_KEY", "DASHSCOPE_API_KEY"),
    "reportOpenai": ("OPENAI_API_KEY", "OPENAI_REALTIME_API_KEY"),
    "reportKimi": ("KIMI_API_KEY", "MOONSHOT_API_KEY"),
    "reportDeepseek": ("DEEPSEEK_API_KEY",), "reportCustom": ("AI_API_KEY",),
    "openai": ("OPENAI_REALTIME_API_KEY", "OPENAI_API_KEY"),
    "qwenOmni": ("QWEN_OMNI_REALTIME_API_KEY", "QWEN_OMNI_API_KEY", "DASHSCOPE_API_KEY"),
    "dashscope": ("DASHSCOPE_API_KEY",),
}


def _bounded_transport(provider, url, headers, payload):
    """诊断不跟随重定向，也不允许不受控的代理、压缩或超大响应。"""
    ca = os.environ.get("SSL_CERT_FILE")
    tls = ssl.create_default_context(cafile=ca) if ca else True
    deadline = time.monotonic() + provider.timeout
    with httpx.Client(timeout=provider.timeout, trust_env=False, follow_redirects=False, verify=tls) as client:
        with client.stream("POST", url, headers={**headers, "Accept-Encoding": "identity"}, json=payload) as reply:
            reply.raise_for_status()
            data = bytearray()
            if reply.headers.get("content-encoding", "identity") != "identity":
                raise ValueError("不接受压缩的诊断结果")
            for chunk in reply.iter_bytes():
                if len(data) + len(chunk) > 65536 or time.monotonic() > deadline:
                    raise ValueError("供应商诊断响应超出大小或时间限制")
                data.extend(chunk)
            return httpx.Response(reply.status_code, request=reply.request, content=bytes(data))


def diagnose_report_providers(*, make_request=True):
    """保持部署指定的顺序；仅将已配置的供应商及诊断状态返回给平台管理员。"""
    settings = runtime_settings()
    order = settings.get("REPORT_PROVIDER_ORDER") or settings.get("FOLLOWUP_PROVIDER_ORDER",
                                                                 FIELDS["reportProviderOrder"][1])
    names = [name.strip().lower() for name in order.split(",")]
    aliases = {"dashscope": "qwen", "ai": "custom"}
    names = dict.fromkeys(aliases.get(name, name) for name in names)
    timeout = float(os.environ.get("AI_PROVIDER_HEALTH_TIMEOUT", "20"))
    if not math.isfinite(timeout) or not 0 < timeout <= 180:
        raise ValueError("供应商诊断超时必须在 0 到 180 秒之间")
    results = []
    for name in names:
        provider = _provider_config(name, settings)
        if not provider or not provider.model or not provider.base_url:
            continue
        result = {"provider": provider.name, "model": provider.model, "configured": True, "status": "not_checked"}
        results.append(result)
        if make_request:
            start = time.monotonic()
            try:
                probe = replace(provider, timeout=timeout, max_tokens=48, retries=0)
                response = call_provider_json(probe, [{"role": "system", "content": "只输出 JSON 对象。"},
                                              {"role": "user", "content": '返回 {"status":"ok"}。'}],
                                              transport=_bounded_transport)
                result["status"] = "ok" if response.get("status") == "ok" else "invalid_response"
                if result["status"] != "ok":
                    result["error"] = "供应商未返回预期的诊断结果。"
            except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError, OSError, RecursionError):
                result.update(status="error", error="供应商请求失败或响应无效。")
            result["latency_ms"] = round((time.monotonic() - start) * 1000)
    return results
