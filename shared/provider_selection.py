"""根据任务、时限和重试预算，从控制服务批准的模型中选取可用供应商。"""
from dataclasses import replace

from .provider_settings import runtime_settings
from .text_provider import FollowupProvider, _provider_config


def get_task_providers(
    order_env: str,
    *,
    max_tokens_env: str,
    timeout_env: str,
    default_max_tokens: int,
    default_timeout: float | None = None,
    retries_env: str | None = None,
    default_retries: int | None = None,
) -> list[FollowupProvider]:
    """返回已配置的 OpenAI 兼容供应商，应用当前任务的调用限制。"""
    settings = runtime_settings()
    order = settings.get(order_env) or settings.get(
        "FOLLOWUP_PROVIDER_ORDER", "kimi,deepseek,qwen,openai,custom"
    )
    max_tokens = int(settings.get(max_tokens_env, str(default_max_tokens)))
    timeout_override = settings.get(timeout_env)
    retries_override = settings.get(retries_env) if retries_env else None
    providers: list[FollowupProvider] = []
    seen: set[str] = set()
    for name in order.split(","):
        normalized = name.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        provider = _provider_config(normalized, settings)
        if not provider or not provider.base_url or not provider.model:
            continue
        providers.append(
            replace(
                provider,
                max_tokens=max_tokens,
                timeout=float(timeout_override) if timeout_override else (default_timeout if default_timeout is not None else provider.timeout),
                retries=int(retries_override) if retries_override is not None else default_retries,
            )
        )
    return providers
