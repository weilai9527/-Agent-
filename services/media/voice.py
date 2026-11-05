"""在媒体服务内使用供应商凭据和权威面试提示，校验会话归属后才申请付费准入。"""
import json
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from shared.env_values import first_env_value
from services.media.qwen_realtime_tts import QwenRealtimeTtsError
from shared.service_security import require_service
from .access import owned_session
from .meter import admit
from .speech import (
    _qwen_realtime_api_key, _qwen_realtime_model, _qwen_realtime_webrtc_url,
    build_qwen_realtime_session_update, build_qwen_tts_response, media_settings,
)

router = APIRouter(prefix="/interviews/{interview_id}")
synth = require_service("media", "media.speech.synthesize")
connect = require_service("media", "media.voice.connect")


class Speech(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=20000)
    provider: Literal["standard", "realtime", "auto"] = "auto"


class Offer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sdp: str = Field(min_length=1, max_length=131072)
    type: Literal["offer"] = "offer"


def synthesize(interview_id, actor, text, provider):
    owned_session(interview_id, actor)
    if not first_env_value("DASHSCOPE_API_KEY"):
        raise HTTPException(503, {"code": "speech_disabled", "fallback": "text"})
    media_settings()
    admit(actor, "media.speech.synthesize")
    return build_qwen_tts_response(text, provider)


@router.post("/qwen/speech")
def speech(interview_id: str, body: Speech, actor=Depends(synth)):
    return synthesize(interview_id, actor, body.text, body.provider)


@router.post("/qwen/tts")
def standard(interview_id: str, body: Speech, actor=Depends(synth)):
    return synthesize(interview_id, actor, body.text, "standard")


@router.post("/qwen/realtime-tts")
def realtime(interview_id: str, body: Speech, actor=Depends(synth)):
    return synthesize(interview_id, actor, body.text, "realtime")


async def exchange(url, key, **payload):
    try:
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=30) as client:
            response = await client.post(url, headers={"Authorization": f"Bearer {key}",
                                         **payload.pop("headers", {})}, **payload)
        response.raise_for_status()
        if not response.text.strip().startswith("v=0"):
            raise ValueError("Invalid SDP answer")
        return response.text
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, {"code": "voice_offer_failed", "fallback": "text"}) from None


async def context_for_offer(interview_id, body, actor):
    ctx = await run_in_threadpool(owned_session, interview_id, actor)
    # 语音动作仅授权音频，禁止通过 SDP 协商摄像头轨道。
    lines = body.sdp.splitlines()
    if not lines or lines[0].strip() != "v=0" or not any(line.startswith("m=audio ") for line in lines):
        raise HTTPException(400, "Audio SDP offer required")
    if any(line.startswith("m=") and not line.startswith(("m=audio ", "m=application ")) for line in lines):
        raise HTTPException(403, "Audio-only session")
    return {"instructions": ctx["prompt"], "current_question": ctx["greeting"],
            "active_agent": ctx["active_agent"]}


@router.post("/realtime/sdp")
async def openai_offer(interview_id: str, body: Offer, actor=Depends(connect)):
    session = await context_for_offer(interview_id, body, actor)
    key = first_env_value("OPENAI_REALTIME_API_KEY", "OPENAI_API_KEY")
    if not key:
        raise HTTPException(503, {"code": "openai_voice_disabled", "fallback": "text"})
    settings = await run_in_threadpool(media_settings)
    config = {"type": "realtime", "model": settings.get("OPENAI_REALTIME_MODEL", "gpt-realtime-2"),
              "instructions": session["instructions"],
              "audio": {"output": {"voice": settings.get("OPENAI_REALTIME_VOICE", "marin")}}}
    await run_in_threadpool(admit, actor, "media.voice.connect")
    answer = await exchange("https://api.openai.com/v1/realtime/calls", key,
                            files={"session": (None, json.dumps(config, ensure_ascii=False)), "sdp": (None, body.sdp)})
    return PlainTextResponse(answer, media_type="application/sdp")


@router.post("/qwen/omni-webrtc/offer")
@router.post("/qwen/omni-realtime/sdp")
async def qwen_offer(interview_id: str, body: Offer, actor=Depends(connect)):
    session = await context_for_offer(interview_id, body, actor)
    key = _qwen_realtime_api_key()
    if not key:
        raise HTTPException(503, {"code": "qwen_voice_disabled", "fallback": "text"})
    try:
        settings = await run_in_threadpool(media_settings)
        model = _qwen_realtime_model(settings)
        url = _qwen_realtime_webrtc_url(model, settings)
        update = build_qwen_realtime_session_update(session, settings=settings)
    except QwenRealtimeTtsError:
        raise HTTPException(503, {"code": "qwen_voice_disabled", "fallback": "text"}) from None
    await run_in_threadpool(admit, actor, "media.voice.connect")
    answer = await exchange(url, key, content=body.sdp, headers={"Content-Type": "application/sdp"})
    return {"provider": "qwen-omni-realtime-webrtc", "model": model,
            "answer": {"type": "answer", "sdp": answer}, "session_update": update}


@router.post("/qwen/omni-webrtc/stop")
def close_direct(interview_id: str, actor=Depends(connect)):
    owned_session(interview_id, actor, active=False)
    return {"events": [{"type": "status", "message": "浏览器直连语音会话由浏览器关闭。"}]}
