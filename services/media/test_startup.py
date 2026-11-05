"""启动前校验运行身份和模式，独立媒体库准备好后才能运行云端任务恢复。"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

from services.media.app import app, rtc


@pytest.mark.parametrize("settings,error", [
    ({"SERVICE_ID": "student-gateway"}, RuntimeError),
    ({"SERVICE_ID": ""}, RuntimeError),
    ({"IDENTITY_SESSION_MODE": "legacy"}, ValueError),
    ({"ASSESSMENT_STORAGE_MODE": "shared"}, ValueError),
])
def test_misconfigured_process_cannot_open_database_or_recover(tmp_path, monkeypatch, settings, error):
    db_path = tmp_path / "media.sqlite"
    configured = {"SERVICE_ID": "media", "IDENTITY_SESSION_MODE": "native", "ASSESSMENT_STORAGE_MODE": "isolated",
                  "MEDIA_DB_ENGINE": "sqlite", "MEDIA_SQLITE_PATH": str(db_path), **settings}
    for k, v in configured.items():
        monkeypatch.setenv(k, v)
    recovery = AsyncMock()
    monkeypatch.setattr(rtc, "rtc_recovery_loop", recovery)
    with pytest.raises(error), TestClient(app):
        pytest.fail("错误身份或运行模式启动了媒体服务")
    recovery.assert_not_called()
    assert not db_path.exists()


def test_native_media_starts_from_empty_store(tmp_path, monkeypatch):
    path = tmp_path / "media.sqlite"
    for k, v in {"MEDIA_DB_ENGINE": "sqlite", "MEDIA_SQLITE_PATH": str(path), "SERVICE_ID": "media",
                 "IDENTITY_SESSION_MODE": "native", "ASSESSMENT_STORAGE_MODE": "isolated"}.items():
        monkeypatch.setenv(k, v)
    recovery = AsyncMock()
    monkeypatch.setattr(rtc, "rtc_recovery_loop", recovery)
    with TestClient(app):
        assert path.exists()
    recovery.assert_awaited_once()
