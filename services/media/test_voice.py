"""在隔离传输中验证 SDP 和语音响应，无需调用付费供应商。"""
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from services.media import access, speech, voice

SCOPE = {"actor_id": "candidate", "school_id": "school", "actor_type": "student"}
OFFER = "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n"
PREFIX = "/interviews/example/"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_ENGINE", "sqlite")
    monkeypatch.setenv("MEDIA_SQLITE_PATH", str(tmp_path / "voice.sqlite"))
    monkeypatch.setattr(speech, "runtime_settings", lambda: {})
    access.initialize()
    access.sync("example", access.Context(status="running", user_name="candidate", active_agent="architect",
                question_id="q", role_id="role", question_order=1, prompt="trusted prompt", greeting="真实题目"), SCOPE)
    app = FastAPI()
    app.include_router(voice.router)
    app.dependency_overrides[voice.connect] = lambda: SCOPE
    app.dependency_overrides[voice.synth] = lambda: SCOPE
    return TestClient(app)


def test_audio_grant_cannot_submit_video_offer_and_disabled_provider_is_free(client, monkeypatch):
    admit = Mock()
    monkeypatch.setattr(voice, "admit", admit)
    monkeypatch.setattr(voice, "first_env_value", lambda *names: "")
    video = client.post(PREFIX + "realtime/sdp", json={"sdp": OFFER + "m=video 9 RTP/AVP 32\r\n"})
    assert video.status_code == 403
    disabled = client.post(PREFIX + "realtime/sdp", json={"sdp": OFFER})
    assert disabled.status_code == 503 and disabled.json()["detail"]["fallback"] == "text"
    assert client.post("/interviews/another/qwen/speech", json={"text": "朗读"}).status_code == 404
    admit.assert_not_called()


def test_qwen_sdp_uses_authoritative_prompt_and_provider_answer(client, monkeypatch):
    monkeypatch.setenv("QWEN_OMNI_REALTIME_API_KEY", "fixture")
    monkeypatch.setattr(voice, "_qwen_realtime_webrtc_url", lambda model, settings: "https://example.test/rtc")
    exchange = AsyncMock(return_value="v=0\r\ns=answer\r\n")
    admit = Mock()
    monkeypatch.setattr(voice, "exchange", exchange)
    monkeypatch.setattr(voice, "admit", admit)
    result = client.post(PREFIX + "qwen/omni-webrtc/offer", json={"sdp": OFFER})
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["answer"]["sdp"] == exchange.return_value
    assert "真实题目" in data["session_update"]["session"]["instructions"]
    assert exchange.call_args.kwargs["content"] == OFFER
    admit.assert_called_once()


def test_streams_first_packet_and_falls_back_to_standard(client, monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture")
    monkeypatch.setattr(voice, "admit", Mock())
    monkeypatch.setattr(speech, "stream_qwen_realtime_tts", Mock(side_effect=speech.QwenRealtimeTtsError("fixture")))
    monkeypatch.setattr(speech, "stream_qwen_tts", lambda text: iter([b"audio-", b"packets"]))
    result = client.post(PREFIX + "qwen/speech", json={"text": "朗读", "provider": "auto"})
    assert result.content == b"audio-packets"
    assert result.headers["X-Qwen-TTS-Fallback-From"] == "realtime"
    assert result.headers["X-Qwen-TTS-Provider"] == "standard"

def test_config_outage_stops_speech_before_admission(client, monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture")
    monkeypatch.setattr(speech, "runtime_settings", Mock(side_effect=HTTPException(503, "控制面离线")))
    admit = Mock()
    synth = Mock()
    monkeypatch.setattr(voice, "admit", admit)
    monkeypatch.setattr(voice, "build_qwen_tts_response", synth)
    result = client.post(PREFIX + "qwen/speech", json={"text": "朗读"})
    assert result.status_code == 503 and result.json()["detail"]["fallback"] == "text"
    admit.assert_not_called()
    synth.assert_not_called()


def test_explicit_realtime_failure_does_not_switch_provider(client, monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture")
    monkeypatch.setattr(voice, "admit", Mock())
    monkeypatch.setattr(speech, "stream_qwen_realtime_tts", Mock(side_effect=speech.QwenRealtimeTtsError("离线")))
    standard = Mock()
    monkeypatch.setattr(speech, "stream_qwen_tts", standard)
    result = client.post(PREFIX + "qwen/realtime-tts", json={"text": "朗读"})
    assert result.status_code == 503 and result.json()["detail"]["fallback"] == "text"
    standard.assert_not_called()
