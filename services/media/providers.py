"""按学校、学生、面试和题目授权，向部署指定的视频、录制与回放适配器发起请求。"""

import os
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response
from starlette.concurrency import run_in_threadpool

from shared.service_http import request_json, service_origin
from shared.service_security import require_service
from .access import owned_session
from .meter import admit
from .rtc_store import candidate_user_id, channel_id

router = APIRouter(prefix="/interviews/{interview_id}/media")
PROVIDER = "media_provider"
VIDEO = "media.video.publish"
START = "media.recording.start"
STOP = "media.recording.stop"
PLAY = "media.playback.read"
PATHS = {VIDEO: "/v1/video/token", START: "/v1/recording/start",
         STOP: "/v1/recording/stop", PLAY: "/v1/playback"}
GRANT_SECONDS = 120


def _enabled(action):
    actions = {s.strip() for s in os.getenv("MEDIA_PROVIDER_ACTIONS", "").split(",")}
    # 可单独关闭新录制。允许开录前必须保证有停录权限。
    enabled = action in actions and (action != START or STOP in actions)
    problem = {"code": "media_provider_disabled", "operation": action, "fallback": "text",
               "error": "该媒体操作未配置有权限的提供商，可继续文字面试。"}
    if not enabled:
        raise HTTPException(503, problem)
    try:
        service_origin(PROVIDER)
    except HTTPException as exc:
        raise HTTPException(503, problem) from exc


def _field(data, name, limit):
    value = data.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > limit or not value.isprintable():
        raise HTTPException(502, "Invalid media provider response")
    return value


def _validate_result(action, binding, data, deadline):
    # 厂商按完整归属找到素材。切题后的停录、回放仍须绑定原题，网关仅转发校验过的字段。
    if not isinstance(data, dict) or data.get("binding") != binding:
        raise HTTPException(502, "Media provider returned a different resource or permission")
    if action in {START, STOP}:
        states = {"recording", "processing", "ready"} if action == START else {"processing", "ready"}
        state = data.get("state")
        if not isinstance(state, str) or state not in states:
            raise HTTPException(502, "Media provider did not confirm the recording state")
        return {"recording_id": _field(data, "recording_id", 256), "state": state,
                "question_id": binding["question_id"]}

    expires = data.get("expires_at")
    if type(expires) is not int or not int(time.time()) < expires <= deadline:
        raise HTTPException(502, "Invalid media provider grant expiration")
    if action == VIDEO:
        return {"token": _field(data, "token", 8192), "app_id": _field(data, "app_id", 128),
                "channel_id": binding["channel_id"], "user_id": binding["user_id"], "expires_at": expires}

    url = _field(data, "url", 8192)
    try:
        parts = urlsplit(url)
        _ = parts.port
        valid = (parts.scheme == "https" and parts.hostname and parts.username is None and
                 parts.password is None and not parts.fragment and "\\" not in url and " " not in url)
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(502, "Invalid media provider playback URL")
    return {"url": url, "expires_at": expires, "question_id": binding["question_id"],
            "recording_id": _field(data, "recording_id", 256)}


async def _dispatch(action, actor, interview_id, question_id=None):
    session = await run_in_threadpool(owned_session, interview_id, actor, active=action in {VIDEO, START})
    if action == START and question_id != session.get("question_id"):
        raise HTTPException(409, "Recording must start on the current question")
    _enabled(action)
    ids = actor["school_id"], actor["actor_id"], interview_id
    binding = {"school_id": ids[0], "actor_id": ids[1], "interview_id": interview_id,
               "channel_id": channel_id(*ids), "user_id": candidate_user_id(*ids),
               "question_id": question_id, "scope": action}
    # 每次新增媒体操作计一个准入单位；停录是清理操作，额度用尽或面试已结束时也可执行。
    if action != STOP:
        await run_in_threadpool(admit, actor, action)
    deadline = int(time.time()) + GRANT_SECONDS
    body = {"binding": binding}
    if action in {VIDEO, PLAY}:
        body["max_expires_at"] = deadline
    try:
        data = await request_json(PROVIDER, "POST", PATHS[action], actor=actor, scope=action, body=body)
    except HTTPException as exc:
        # 诊断正文可能含签名链接或凭证，不转发给浏览器。
        if exc.status_code >= 500:
            raise HTTPException(exc.status_code, {"code": "media_provider_unavailable", "operation": action,
                                                 "fallback": "text", "error": "媒体提供商暂不可用。"}) from None
        raise HTTPException(exc.status_code, "媒体提供商拒绝了该请求。") from None
    return _validate_result(action, binding, data, deadline)


@router.post("/video/token")
async def video_token(interview_id: str, response: Response, actor=Depends(require_service("media", VIDEO))):
    response.headers["Cache-Control"] = "private, no-store"
    return await _dispatch(VIDEO, actor, interview_id)


@router.post("/questions/{question_id}/recording/start")
async def start(interview_id: str, question_id: str, actor=Depends(require_service("media", START))):
    return await _dispatch(START, actor, interview_id, question_id)


@router.post("/questions/{question_id}/recording/stop")
async def stop(interview_id: str, question_id: str, actor=Depends(require_service("media", STOP))):
    return await _dispatch(STOP, actor, interview_id, question_id)


@router.post("/questions/{question_id}/playback")
async def playback(interview_id: str, question_id: str, response: Response, actor=Depends(require_service("media", PLAY))):
    response.headers["Cache-Control"] = "private, no-store"
    return await _dispatch(PLAY, actor, interview_id, question_id)
