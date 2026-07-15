from __future__ import annotations

import os
from pathlib import Path


PLACEHOLDER_VALUES = {
    "your-api-key-here",
    "your-dashscope-api-key",
    "your-kimi-api-key-here",
    "your-deepseek-api-key-here",
    "your-mysql-password",
    "placeholder",
}


def clean_env_value(value: str | None) -> str:
    cleaned = (value or "").strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def is_placeholder_value(value: str | None) -> bool:
    cleaned = clean_env_value(value).lower()
    if not cleaned:
        return False
    return (
        cleaned in PLACEHOLDER_VALUES
        or cleaned.startswith("your-")
        or "api-key-here" in cleaned
    )


def valid_env_value(name: str, default: str = "") -> str:
    value = clean_env_value(os.environ.get(name))
    if not value or is_placeholder_value(value):
        return default
    return value


def first_env_value(*names: str) -> str:
    for name in names:
        value = valid_env_value(name)
        if value:
            return value
    return ""


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None

    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None

    return key, clean_env_value(value)


def load_env_file() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.is_file():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(raw_line)
        if not parsed:
            continue
        key, value = parsed
        os.environ.setdefault(key, value)


AI_RUNTIME_PREFIXES = (
    "AI_",
    "OPENAI_",
    "QWEN_",
    "KIMI_",
    "DEEPSEEK_",
    "DASHSCOPE_",
    "REPORT_",
    "EVALUATION_",
    "FOLLOWUP_",
    "RESUME_ANALYSIS_",
)


def reload_runtime_ai_env() -> None:
    """Reload admin-managed AI settings without replacing unrelated process env."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(raw_line)
        if not parsed:
            continue
        key, value = parsed
        if key.startswith(AI_RUNTIME_PREFIXES):
            os.environ[key] = value


def normalize_certificate_env() -> None:
    for key in ("SSL_CERT_FILE", "WEBSOCKET_CLIENT_CA_BUNDLE", "REQUESTS_CA_BUNDLE"):
        value = os.environ.get(key, "").strip()
        if value and not Path(value).is_file():
            os.environ.pop(key, None)
