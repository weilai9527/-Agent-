from pathlib import Path
import os


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _unquote(value: str) -> str:
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def load_env() -> None:
    env_path = BACKEND_DIR / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = _unquote(value)
        if key and key not in os.environ:
            os.environ[key] = value


load_env()
