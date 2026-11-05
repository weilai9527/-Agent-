"""从当前服务进程读取已注入的配置，忽略空白和部署示例中的占位值。"""
import os


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
