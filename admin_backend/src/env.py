from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


ADMIN_BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = ADMIN_BACKEND_DIR.parent

# 历史数据夹具只能接收调用方传入的隔离配置，导入时不读取部署环境文件。
