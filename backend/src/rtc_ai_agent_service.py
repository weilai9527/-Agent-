from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass
from typing import Any


RTC_AI_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
AI_AGENT_REQUIRED_ENV = (
    "RTC_APP_ID",
    "RTC_AI_AGENT_TEMPLATE_ID",
    "ALIBABA_CLOUD_ACCESS_KEY_ID",
    "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
)


class RtcAiAgentConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RtcAiAgentConfiguration:
    app_id: str
    template_id: str
    access_key_id: str
    access_key_secret: str
    endpoint: str
    region_id: str
    chat_mode: int
    interrupt_mode: int
    user_inactivity_timeout: int
    source_language: str
    greeting: str


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RtcAiAgentConfigurationError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise RtcAiAgentConfigurationError(f"{name} must be between {minimum} and {maximum}")
    return value


def missing_rtc_ai_agent_configuration() -> list[str]:
    return [name for name in AI_AGENT_REQUIRED_ENV if not os.getenv(name, "").strip()]


def rtc_ai_agent_is_configured() -> bool:
    return not missing_rtc_ai_agent_configuration()


def _load_configuration() -> RtcAiAgentConfiguration:
    missing = missing_rtc_ai_agent_configuration()
    if missing:
        raise RtcAiAgentConfigurationError(f"missing configuration: {', '.join(missing)}")

    return RtcAiAgentConfiguration(
        app_id=os.environ["RTC_APP_ID"].strip(),
        template_id=os.environ["RTC_AI_AGENT_TEMPLATE_ID"].strip(),
        access_key_id=os.environ["ALIBABA_CLOUD_ACCESS_KEY_ID"].strip(),
        access_key_secret=os.environ["ALIBABA_CLOUD_ACCESS_KEY_SECRET"].strip(),
        endpoint=os.getenv("RTC_AI_AGENT_ENDPOINT", "rtc.aliyuncs.com").strip() or "rtc.aliyuncs.com",
        region_id=os.getenv("RTC_AI_AGENT_REGION_ID", "cn-hangzhou").strip() or "cn-hangzhou",
        chat_mode=_bounded_env_int("RTC_AI_AGENT_CHAT_MODE", 1, 1, 2),
        interrupt_mode=_bounded_env_int("RTC_AI_AGENT_INTERRUPT_MODE", 1, 1, 2),
        user_inactivity_timeout=_bounded_env_int("RTC_AI_AGENT_USER_INACTIVITY_TIMEOUT", 30, 5, 180),
        source_language=os.getenv("RTC_AI_AGENT_SOURCE_LANGUAGE", "zh").strip() or "zh",
        greeting=os.getenv("RTC_AI_AGENT_GREETING", "").strip(),
    )


def _compact_identifier(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", str(value or ""))


def rtc_ai_agent_user_id(interview_id: object) -> str:
    compact = _compact_identifier(interview_id)
    if not compact:
        raise ValueError("interview_id cannot be empty")
    return f"agent_{compact}"[:64]


def rtc_ai_agent_task_prefix(interview_id: object) -> str:
    compact = _compact_identifier(interview_id)
    if not compact:
        raise ValueError("interview_id cannot be empty")
    return f"task_{compact[:40]}_"


def generate_rtc_ai_agent_task_id(interview_id: object) -> str:
    return f"{rtc_ai_agent_task_prefix(interview_id)}{secrets.token_hex(8)}"[:64]


def task_belongs_to_interview(task_id: object, interview_id: object) -> bool:
    return str(task_id or "").startswith(rtc_ai_agent_task_prefix(interview_id))


def rtc_ai_agent_client_config(interview_id: object) -> dict[str, Any]:
    return {
        "enabled": rtc_ai_agent_is_configured(),
        "user_id": rtc_ai_agent_user_id(interview_id),
    }


def _validate_rtc_id(value: str, field_name: str) -> None:
    if not RTC_AI_ID_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must contain only letters, digits, underscores, or hyphens and be at most 64 characters")


def _create_client(configuration: RtcAiAgentConfiguration):
    try:
        from alibabacloud_rtc20180111.client import Client
        from alibabacloud_tea_openapi.models import Config
    except ImportError as exc:
        raise RtcAiAgentConfigurationError(
            "alibabacloud_rtc20180111 is not installed; install backend requirements"
        ) from exc

    config = Config(
        access_key_id=configuration.access_key_id,
        access_key_secret=configuration.access_key_secret,
        endpoint=configuration.endpoint,
        region_id=configuration.region_id,
        connect_timeout=10_000,
        read_timeout=20_000,
    )
    return Client(config)


def start_rtc_ai_agent(
    *,
    channel_id: str,
    candidate_user_id: str,
    agent_user_id: str,
    task_id: str,
    greeting: str | None = None,
    prompt: str | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    configuration = _load_configuration()
    _validate_rtc_id(channel_id, "channel_id")
    _validate_rtc_id(candidate_user_id, "candidate_user_id")
    _validate_rtc_id(agent_user_id, "agent_user_id")
    _validate_rtc_id(task_id, "task_id")

    from alibabacloud_rtc20180111 import models

    asr_config = models.StartAgentRequestVoiceChatConfigASRConfig(
        source_language=configuration.source_language,
    )
    effective_greeting = str(greeting).strip() if greeting is not None else configuration.greeting
    effective_prompt = str(prompt or "").strip()
    llm_config = None
    if effective_prompt:
        llm_config = models.StartAgentRequestVoiceChatConfigLLMConfig(
            # Alibaba Cloud currently limits the per-task prompt to 5,000
            # characters. Keep the most important instructions at the front in
            # the caller and enforce the provider boundary here as a safeguard.
            prompt=effective_prompt[:5000],
        )
    voice_chat_config = models.StartAgentRequestVoiceChatConfig(
        asrconfig=asr_config,
        chat_mode=configuration.chat_mode,
        interrupt_mode=configuration.interrupt_mode,
        greeting=effective_greeting[:2000] or None,
        llmconfig=llm_config,
    )
    request = models.StartAgentRequest(
        app_id=configuration.app_id,
        channel_id=channel_id,
        task_id=task_id,
        template_id=configuration.template_id,
        rtc_config=models.StartAgentRequestRtcConfig(
            user_id=agent_user_id,
            target_user_ids=[candidate_user_id],
            user_inactivity_timeout=configuration.user_inactivity_timeout,
        ),
        voice_chat_config=voice_chat_config,
    )

    response = (client or _create_client(configuration)).start_agent(request)
    request_id = getattr(getattr(response, "body", None), "request_id", None)
    return {
        "task_id": task_id,
        "agent_user_id": agent_user_id,
        "status": "starting",
        "request_id": request_id,
    }


def stop_rtc_ai_agent(
    *,
    channel_id: str,
    task_id: str,
    client: Any | None = None,
) -> dict[str, Any]:
    configuration = _load_configuration()
    _validate_rtc_id(channel_id, "channel_id")
    _validate_rtc_id(task_id, "task_id")

    from alibabacloud_rtc20180111 import models

    request = models.StopAgentRequest(
        app_id=configuration.app_id,
        channel_id=channel_id,
        task_id=task_id,
    )
    response = (client or _create_client(configuration)).stop_agent(request)
    request_id = getattr(getattr(response, "body", None), "request_id", None)
    return {
        "task_id": task_id,
        "status": "stopped",
        "request_id": request_id,
    }


def get_rtc_ai_agent(
    *,
    channel_id: str,
    task_id: str,
    client: Any | None = None,
) -> dict[str, Any]:
    configuration = _load_configuration()
    _validate_rtc_id(channel_id, "channel_id")
    _validate_rtc_id(task_id, "task_id")

    from alibabacloud_rtc20180111 import models

    request = models.GetAgentRequest(
        app_id=configuration.app_id,
        channel_id=channel_id,
        task_id=task_id,
    )
    response = (client or _create_client(configuration)).get_agent(request)
    body = getattr(response, "body", None)
    return {
        "task_id": task_id,
        "status": str(getattr(body, "status", "") or "").strip(),
        "message": str(getattr(body, "message", "") or "").strip(),
        "start_time": getattr(body, "start_time", None),
        "stop_time": getattr(body, "stop_time", None),
        "request_id": getattr(body, "request_id", None),
    }


def notify_rtc_ai_agent(
    *,
    channel_id: str,
    task_id: str,
    message: str,
    priority: int = 1,
    interruptable: bool = True,
    client: Any | None = None,
) -> dict[str, Any]:
    configuration = _load_configuration()
    _validate_rtc_id(channel_id, "channel_id")
    _validate_rtc_id(task_id, "task_id")
    normalized_message = str(message or "").strip()
    if not normalized_message:
        raise ValueError("message cannot be empty")
    if len(normalized_message) > 2000:
        raise ValueError("message must be at most 2000 characters")
    if priority not in {1, 2, 3}:
        raise ValueError("priority must be 1, 2, or 3")

    from alibabacloud_rtc20180111 import models

    request = models.NotifyAgentRequest(
        app_id=configuration.app_id,
        channel_id=channel_id,
        task_id=task_id,
        message=normalized_message,
        priority=priority,
        interruptable=interruptable,
    )
    response = (client or _create_client(configuration)).notify_agent(request)
    request_id = getattr(getattr(response, "body", None), "request_id", None)
    return {
        "task_id": task_id,
        "status": "notified",
        "request_id": request_id,
    }
