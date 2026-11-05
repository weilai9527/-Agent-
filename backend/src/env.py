from __future__ import annotations

import os
from pathlib import Path


from shared.env_values import PLACEHOLDER_VALUES, clean_env_value, first_env_value, is_placeholder_value, valid_env_value


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
    # 各服务进程只使用为本服务注入的凭据。加载兼容处理函数时也不能读取相邻项目的环境配置。
    from shared.offline_fixture import offline_fixture_enabled
    if offline_fixture_enabled() or os.environ.get("SERVICE_ID") or os.environ.get("APP_ENV") == "test":
        return
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.is_file():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(raw_line)
        if not parsed:
            continue
        key, value = parsed
        os.environ.setdefault(key, value)


def normalize_certificate_env() -> None:
    for key in ("SSL_CERT_FILE", "WEBSOCKET_CLIENT_CA_BUNDLE", "REQUESTS_CA_BUNDLE"):
        value = os.environ.get(key, "").strip()
        if value and not Path(value).is_file():
            os.environ.pop(key, None)
