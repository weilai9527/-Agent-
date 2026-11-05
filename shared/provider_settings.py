"""模型控制服务独占配置库。推理进程通过签名 HTTP 获取本工作负载的公开字段；
供应商密钥及可访问地址名单由部署环境分别注入各自的进程。
"""
import json
import os
import re
from collections import ChainMap
from threading import Lock
from time import monotonic
from types import MappingProxyType
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from jwt.exceptions import PyJWTError

from .offline_fixture import require_offline_fixture
from .service_db import ServiceDatabase
from .service_http import service_origin
from .service_security import service_headers


# 公开字段对应运行时参数名及默认值；密钥不属于可写字段。
FIELDS = {
    "reportOpenaiModel": ("OPENAI_FOLLOWUP_MODEL", "gpt-4o-mini"),
    "reportOpenaiBaseUrl": ("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    "reportQwenModel": ("QWEN_MODEL", "qwen-plus"),
    "reportQwenBaseUrl": ("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    "reportKimiModel": ("KIMI_MODEL", "moonshot-v1-8k"),
    "reportKimiBaseUrl": ("KIMI_BASE_URL", "https://api.moonshot.cn/v1"),
    "reportDeepseekModel": ("DEEPSEEK_MODEL", "deepseek-chat"),
    "reportDeepseekBaseUrl": ("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    "reportCustomModel": ("AI_MODEL", ""),
    "reportCustomBaseUrl": ("AI_BASE_URL", ""),
    "reportProviderOrder": ("REPORT_PROVIDER_ORDER", "kimi,deepseek,qwen,openai,custom"),
    "evaluationProviderOrder": ("EVALUATION_PROVIDER_ORDER", "kimi,deepseek,qwen,openai,custom"),
    "reportTimeout": ("AI_REPORT_TIMEOUT", 60), "reportRetries": ("AI_REPORT_HTTP_RETRIES", 0),
    "reportAttempts": ("AI_REPORT_PROVIDER_ATTEMPTS", 2),
    "evaluationTimeout": ("AI_EVALUATION_TIMEOUT", 12), "evaluationRetries": ("AI_EVALUATION_HTTP_RETRIES", 0),
    "evaluationAttempts": ("AI_EVALUATION_PROVIDER_ATTEMPTS", 1),
    "openaiRealtimeModel": ("OPENAI_REALTIME_MODEL", "gpt-realtime-2"),
    "openaiVoice": ("OPENAI_REALTIME_VOICE", "marin"),
    "qwenOmniModel": ("QWEN_OMNI_REALTIME_MODEL", "qwen3.5-omni-plus-realtime"),
    "qwenOmniVoice": ("QWEN_OMNI_REALTIME_VOICE", "Tina"),
    "qwenOmniRegion": ("QWEN_OMNI_REALTIME_REGION", "beijing"),
    "qwenOmniWorkspaceId": ("QWEN_OMNI_REALTIME_WORKSPACE_ID", ""),
    "qwenOmniEndpoint": ("QWEN_OMNI_REALTIME_WEBRTC_ENDPOINT", ""),
    "qwenTtsModel": ("DASHSCOPE_TTS_MODEL", "cosyvoice-v3-flash"),
    "qwenTtsVoice": ("DASHSCOPE_TTS_VOICE", "longanyang"),
    "qwenTtsRegion": ("DASHSCOPE_TTS_REGION", "beijing"),
    "qwenTtsWorkspaceId": ("DASHSCOPE_WORKSPACE_ID", ""),
}
ENDPOINT_FIELDS = {
    "reportOpenaiBaseUrl": "openai", "reportQwenBaseUrl": "qwen", "reportKimiBaseUrl": "kimi",
    "reportDeepseekBaseUrl": "deepseek", "reportCustomBaseUrl": "custom", "qwenOmniEndpoint": "qwen_webrtc",
}
LIMITS = {"reportTimeout": (10, 180), "evaluationTimeout": (5, 180), "reportRetries": (0, 4),
          "evaluationRetries": (0, 4), "reportAttempts": (1, 5), "evaluationAttempts": (1, 5)}
PROVIDERS = {"openai", "qwen", "kimi", "deepseek", "custom"}
DDL = ("CREATE TABLE IF NOT EXISTS model_runtime_settings (setting_key VARCHAR(80) PRIMARY KEY,"
       " setting_value VARCHAR(2048) NOT NULL)")

# 此处再次限定工作负载角色。即使受信策略误授予管理网关机器读取权限，它也不能冒充推理进程。
TEXT_MODEL_FIELDS = frozenset({
    "reportOpenaiModel", "reportOpenaiBaseUrl", "reportQwenModel", "reportQwenBaseUrl",
    "reportKimiModel", "reportKimiBaseUrl", "reportDeepseekModel", "reportDeepseekBaseUrl",
    "reportCustomModel", "reportCustomBaseUrl",
})
RUNTIME_FIELDS = {
    "profile": TEXT_MODEL_FIELDS, "career": TEXT_MODEL_FIELDS,
    "interview": TEXT_MODEL_FIELDS | {"openaiRealtimeModel", "openaiVoice"},
    "assessment": TEXT_MODEL_FIELDS | LIMITS.keys() | {"reportProviderOrder", "evaluationProviderOrder"},
    "media": frozenset({"openaiRealtimeModel", "openaiVoice", "qwenOmniModel", "qwenOmniVoice",
                        "qwenOmniRegion", "qwenOmniWorkspaceId", "qwenOmniEndpoint", "qwenTtsModel",
                        "qwenTtsVoice", "qwenTtsRegion", "qwenTtsWorkspaceId"}),
}
RUNTIME_SCOPE = "providers.runtime.read"
RUNTIME_TTL = 3
_cache_lock = Lock()
_cache = None


def qwen_workspace_endpoint(provider, workspace, region):
    if region in {"beijing", "cn", "cn-beijing"}:
        zone = "cn-beijing"
    elif region in {"singapore", "intl", "international", "ap-southeast-1"}:
        zone = "ap-southeast-1"
    else:
        raise ValueError("不支持此千问地域。")
    if not workspace:
        if provider == "qwen_tts" and zone == "cn-beijing":
            return "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
        raise ValueError("缺少已授权的千问业务空间。")
    workspace = approved_workspace(workspace)
    host = f"{workspace}.{zone}.maas.aliyuncs.com"
    if provider == "qwen_tts":
        return f"wss://{host}/api-ws/v1/inference"
    return f"https://{host}/api/v1/webrtc/realtime"


def approved_endpoint(provider: str, url: str, *, scheme: str = "https") -> str:
    approved = {FIELDS[field][1] for field, key in ENDPOINT_FIELDS.items() if key == provider and FIELDS[field][1]}
    approved.update(os.environ.get(f"PROVIDER_ALLOWED_{provider.upper()}_ENDPOINTS", "").split(","))
    if provider in {"qwen_webrtc", "qwen_tts"}:
        # 部署时配置的工作空间与地域只授权一个精确地址。切换其中一项也需另行授权。
        workspace = os.environ.get("DASHSCOPE_WORKSPACE_ID", "")
        region = os.environ.get("DASHSCOPE_TTS_REGION", "beijing")
        if provider == "qwen_webrtc":
            workspace = os.environ.get("QWEN_OMNI_REALTIME_WORKSPACE_ID") or workspace
            region = os.environ.get("QWEN_OMNI_REALTIME_REGION") or region
        if workspace or provider == "qwen_tts":
            approved.add(qwen_workspace_endpoint(provider, workspace, region))
    parts = urlsplit(url)
    if (not url or url not in approved or parts.scheme != scheme or not parts.hostname
            or parts.username is not None or parts.password is not None or parts.query or parts.fragment
            or "%" in url or "\\" in url or any(c.isspace() or ord(c) < 32 for c in url)
            or any(p in (".", "..") for p in parts.path.split("/"))):
        raise ValueError("模型接入地址未获部署端 HTTPS 白名单授权。")
    return url


def approved_workspace(workspace: str) -> str:
    if workspace:
        approved = set(os.environ.get("PROVIDER_ALLOWED_QWEN_WORKSPACES", "").split(","))
        approved.update(os.environ.get(k) for k in ("DASHSCOPE_WORKSPACE_ID", "QWEN_OMNI_REALTIME_WORKSPACE_ID"))
        if workspace not in approved or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,61}[a-z0-9]|[a-z0-9]", workspace):
            raise ValueError("千问业务空间未获部署端授权。")
    return workspace


def validate_values(body):
    if not isinstance(body, dict) or not body or body.keys() - FIELDS.keys():
        raise ValueError("仅支持公开的模型参数，凭据由部署端管理。")
    updates = {}
    for field, raw in body.items():
        if type(raw) not in (str, int):
            raise ValueError("模型配置类型无效。")
        value = str(raw)
        if len(value) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("模型配置包含非法字符。")
        if field in ENDPOINT_FIELDS:
            if value or field not in {"reportCustomBaseUrl", "qwenOmniEndpoint"}:
                approved_endpoint(ENDPOINT_FIELDS[field], value)
        elif field.endswith("WorkspaceId"):
            approved_workspace(value)
        elif field.endswith("ProviderOrder"):
            names = [n.strip().lower() for n in value.split(",")]
            if len(set(names)) != len(names) or set(names) - PROVIDERS:
                raise ValueError("供应商顺序无效。")
            value = ",".join(names)
        elif field in LIMITS:
            low, high = LIMITS[field]
            if not value.isascii() or not value.isdecimal() or not low <= int(value) <= high:
                raise ValueError("模型调用限制超出范围。")
        elif field.endswith("Region"):
            if value not in {"beijing", "cn", "cn-beijing", "singapore", "intl", "international", "ap-southeast-1"}:
                raise ValueError("不支持此地域。")
        elif not re.fullmatch(r"[\w.:-][\w.:/-]{0,119}", value) and not (field == "reportCustomModel" and not value):
            raise ValueError("模型或音色名称无效。")
        updates[FIELDS[field][0]] = value
    return updates


def config_store():
    if os.environ.get("SERVICE_ID") != "providers":
        raise HTTPException(503, "只有模型控制服务可以打开配置库")
    try:
        return ServiceDatabase.from_env("providers")
    except ValueError:
        raise HTTPException(503, "模型配置库缺少有效的部署配置") from None


def stored_fields(fields):
    """只返回已保存的公开配置，不序列化所有者进程的环境变量。"""
    names = {FIELDS[field][0]: field for field in fields}
    with config_store().transaction() as tx:
        rows = tx.all("SELECT setting_key, setting_value FROM model_runtime_settings")
    return {names[r["setting_key"]]: r["setting_value"] for r in rows if r["setting_key"] in names}


def _fetch_settings(origin, caller):
    headers = service_headers("providers", actor_id=caller, actor_type="system",
                              school_id="platform", scopes=[RUNTIME_SCOPE])
    headers["Accept-Encoding"] = "identity"
    deadline = monotonic() + 4
    with httpx.Client(timeout=2, trust_env=False, follow_redirects=False) as client:
        with client.stream("GET", origin + "/internal/runtime-settings", headers=headers) as reply:
            reply.raise_for_status()
            if (reply.headers.get("content-type", "").split(";")[0].strip() != "application/json"
                    or reply.headers.get("content-encoding", "identity") != "identity"):
                raise ValueError("控制服务响应类型无效")
            data = bytearray()
            for chunk in reply.iter_bytes():
                if len(data) + len(chunk) > 65536 or monotonic() > deadline:
                    raise ValueError("控制服务响应超出大小或时间限制")
                data.extend(chunk)
    result = json.loads(data)
    if (not isinstance(result, dict) or result.get("consumer") != caller or result.get("school_id") != "platform"
            or not isinstance(result.get("settings"), dict) or result["settings"].keys() - RUNTIME_FIELDS[caller]):
        raise ValueError("控制服务响应的身份、学校或字段无效")
    # 消费者使用自己的出站白名单复核响应，配置发布权限不包含变更网络授权的权限。
    return validate_values(result["settings"]) if result["settings"] else {}


def _remote_overrides(caller):
    global _cache
    if caller not in RUNTIME_FIELDS:
        raise HTTPException(503, "该工作负载没有读取模型参数的权限")
    origin = service_origin("providers")
    key = (origin, caller, os.environ.get("SERVICE_KEY_ID"))
    with _cache_lock:
        if _cache is None or _cache[0] != key or monotonic() >= _cache[1]:
            try:
                values = MappingProxyType(_fetch_settings(origin, caller))
                _cache = (key, monotonic() + RUNTIME_TTL, values)
            except (httpx.HTTPError, PyJWTError, KeyError, TypeError, ValueError, RecursionError):
                # 短暂缓存失败以限制重试。快照失效后，不再据此授权新的模型调用。
                _cache = (key, monotonic() + 1, None)
        if _cache[2] is None:
            raise HTTPException(503, "模型控制服务不可用或拒绝访问")
        return _cache[2]


def runtime_settings():
    caller = os.environ.get("SERVICE_ID")
    if caller == "providers":
        overrides = {FIELDS[key][0]: value for key, value in stored_fields(FIELDS).items()}
    elif any(name in os.environ for name in ("PROVIDERS_SQLITE_PATH", "PROVIDERS_DB_ENGINE")) or any(
        name.startswith("PROVIDERS_MYSQL_") for name in os.environ
    ):
        raise HTTPException(503, "推理服务不得使用模型控制库的连接配置")
    elif "PROVIDERS_SERVICE_URL" in os.environ:
        overrides = _remote_overrides(caller)
    else:
        # 只有显式启用且仍绑定合成旧库的离线夹具才可直接注入参数。
        # 无身份、缺地址、服务下线和 APP_ENV=test 本身均不能授权静态回退。
        try:
            require_offline_fixture()
        except RuntimeError:
            raise HTTPException(503, "缺少模型控制服务地址") from None
        return os.environ
    return ChainMap(overrides, os.environ)


def save_public_settings(body):
    updates = validate_values(body)
    store = config_store()
    suffix = ("ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value"
              if store.engine == "sqlite" else "ON DUPLICATE KEY UPDATE setting_value=VALUES(setting_value)")
    with store.transaction(write=True) as tx:
        for key in sorted(updates):
            tx.execute("INSERT INTO model_runtime_settings(setting_key,setting_value) VALUES (?,?) " + suffix,
                       (key, updates[key]))


def public_settings():
    values = runtime_settings()
    result = {}
    for field, (key, default) in FIELDS.items():
        if field.endswith("ProviderOrder"):
            default = values.get("FOLLOWUP_PROVIDER_ORDER", default)
        if field == "qwenOmniWorkspaceId":
            default = values.get("DASHSCOPE_WORKSPACE_ID", default)
        value = values.get(key, default)
        if field in ENDPOINT_FIELDS and value:
            try:
                approved_endpoint(ENDPOINT_FIELDS[field], value)
            except ValueError:
                value = ""  # 历史非法地址可能内嵌凭据，不将其返回给管理端。
        result[field] = int(value) if field in LIMITS else value
    return result
