"""阿里云语音面试。多个工作进程共享同一场面试的任务记录，按版本号争取执行权。"""
import asyncio
from importlib.util import find_spec
import logging
import os
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from starlette.concurrency import run_in_threadpool

from services.media.rtc_ai_agent_service import (
    RtcAiAgentConfigurationError, generate_rtc_ai_agent_task_id, get_rtc_ai_agent,
    notify_rtc_ai_agent, rtc_ai_agent_is_configured, start_rtc_ai_agent, stop_rtc_ai_agent,
)
from services.media.rtc_token_service import generate_rtc_token, normalize_rtc_user_name
from shared.service_security import require_service
from . import rtc_store as store
from .access import owned_session
from .meter import admit

router = APIRouter(prefix="/interviews/{interview_id}/rtc")
initialize = store.initialize
log = logging.getLogger(__name__)


def setting(name, default, low, high):
    return max(low, min(high, int(os.environ.get(name, default))))


def agent_enabled():
    return rtc_ai_agent_is_configured() and find_spec("alibabacloud_rtc20180111") is not None


def request_budget():
    # 进程可能在调用 StartAgent 前后退出。启动请求仍可能在途，须等足连接和读取期限再查远端任务。
    connect = setting("RTC_AI_AGENT_CONNECT_TIMEOUT_MS", 10_000, 1000, 120_000)
    read = setting("RTC_AI_AGENT_READ_TIMEOUT_MS", 60_000, 5000, 180_000)
    return max(setting("RTC_SESSION_START_TIMEOUT_SECONDS", 45, 15, 300), (connect + read) // 1000 + 30)


def heartbeat_timeout():
    return setting("RTC_SESSION_HEARTBEAT_TIMEOUT_SECONDS", 60, 20, 600)


def now():
    return int(time.time())


def public(row):
    if row is None:
        return None
    result = {key: row[key] for key in ("id", "interview_id", "channel_id", "candidate_user_id",
              "agent_user_id", "state", "task_id", "revision", "last_error")}
    for key in ("last_heartbeat_at", "token_expires_at", "started_at", "stopped_at"):
        result[key] = datetime.fromtimestamp(row[key], timezone.utc).isoformat() if row[key] else None
    result["desired_state"] = "active" if row["state"] in ("starting", "active") else "stopped"
    result["heartbeat_interval_seconds"] = setting("RTC_SESSION_HEARTBEAT_INTERVAL_SECONDS", 15, 5, 60)
    return result


def provider_missing(exc):
    # 查询和停止接口可能通过错误码或厂商消息表明该任务已不存在。
    description = " ".join(str(getattr(exc, key, "")) for key in ("code", "message", "data"))
    return any(marker in (str(exc) + description).lower().replace("_", "")
               for marker in ("tasknotfound", "tasknotexist", "task does not exist", "invalidtaskid"))


def stopped(snapshot):
    return store.update(snapshot, state="stopped", task_id=None, stopped_at=now(),
                        recover_at=None, last_error=None)


def dispatch_stop(claim):
    """先提交停止意图，再访问厂商；若本进程退出，其他进程可在租约到期后重试。"""
    try:
        stop_rtc_ai_agent(channel_id=claim["channel_id"], task_id=claim["task_id"])
    except Exception as exc:
        if not provider_missing(exc):
            delay = min(300, 5 * 2 ** min(6, claim["stop_attempts"] - 1))
            return (store.update(claim, state="stop_failed", recover_at=now() + delay,
                                 last_error="RTC stop pending retry") or store.get(claim["id"]))
    return stopped(claim) or store.get(claim["id"])


def claim_stop(row):
    return store.update(row, state="stopping", stop_attempts=row["stop_attempts"] + 1,
                        recover_at=now() + request_budget())


def request_stop(row, expected):
    # 未传任务号时固定入口处看到的任务。重试条件更新时，旧请求不能停止刚刚重启的新任务。
    if row and expected is None:
        expected = row["task_id"]
    for _ in range(8):
        if not row or row["task_id"] != expected:
            return row, False
        state = row["state"]
        if state in {"stop_requested", "stopping", "stopped"}:
            return row, False
        if state == "starting":
            # 启动尚未返回，先保留停止意图，由启动回执或恢复进程完成停机。
            result = store.update(row, state="stop_requested")
        elif state in {"active", "stop_failed"}:
            claim = claim_stop(row)
            if claim:
                return dispatch_stop(claim), True
            result = None
        else:
            result = stopped(row)
        if result:
            return result, False
        row = store.get(row["id"])
    raise HTTPException(409, "RTC state changed; retry stop")


def acknowledge_start(row):
    """启动应答只对原任务有效，同时处理调用期间收到的停止请求。"""
    task_id = row["task_id"]
    for _ in range(8):
        if row["task_id"] != task_id or row["state"] not in {"starting", "stop_requested"}:
            return row
        if row["state"] == "stop_requested":
            claim = claim_stop(row)
            if claim:
                return dispatch_stop(claim)
        else:
            result = store.update(row, state="active", recover_at=now() + heartbeat_timeout(),
                                  last_heartbeat_at=now(), started_at=now(), last_error=None)
            if result:
                return result
        row = store.get(row["id"])
    return row  # 后续按库中期限恢复。


def fail_start(row, reason, ambiguous=False):
    task_id = row["task_id"]
    for _ in range(8):
        if row["task_id"] != task_id or row["state"] not in {"starting", "stop_requested"}:
            return
        if ambiguous:
            result = store.update(row, last_error=reason, recover_at=now() + 5)
        elif row["state"] == "stop_requested":
            result = stopped(row)
        else:
            result = store.update(row, state="start_failed", last_error=reason, recover_at=None)
        if result:
            return
        row = store.get(row["id"])


@router.post("/token")
def issue_token(interview_id: str, actor=Depends(require_service("media", "media.rtc.token"))):
    context = owned_session(interview_id, actor)
    row = store.session(context, create=True)
    try:
        token = generate_rtc_token(row["channel_id"], row["candidate_user_id"])
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(503, {"code": "rtc_token_unavailable", "fallback": "text"}) from exc
    admit(actor, "rtc.token")
    row = store.set_token_expiry(row["id"], token["timestamp"])
    return {**token, "user_name": normalize_rtc_user_name(context["user_name"]),
            "ai_agent": {"enabled": agent_enabled(), "user_id": row["agent_user_id"]},
            "rtc_session": public(row)}


@router.get("/session")
def read_session(interview_id: str, actor=Depends(require_service("media", "media.rtc.read"))):
    return {"rtc_session": public(store.session(owned_session(interview_id, actor, active=False)))}


@router.post("/session/heartbeat")
def heartbeat(interview_id: str, actor=Depends(require_service("media", "media.rtc.heartbeat"))):
    context = owned_session(interview_id, actor)
    row = store.session(context)
    if not row:
        raise HTTPException(409, "当前面试还没有 RTC 会话。")
    if row["state"] == "active" and row["role_id"] == context["role_id"]:
        row = store.update(row, recover_at=now() + heartbeat_timeout(), last_heartbeat_at=now()) or store.get(row["id"])
    return {"rtc_session": public(row)}


def start_result(row, context, duplicate):
    return {"task_id": row["task_id"], "agent_user_id": row["agent_user_id"], "status": row["state"],
            "current_question_id": context["question_id"], "idempotent": duplicate, "rtc_session": public(row)}


@router.post("/agent/start")
def start(interview_id: str, actor=Depends(require_service("media", "media.rtc.start"))):
    context = owned_session(interview_id, actor)
    if not all(context.get(field) for field in ("question_id", "role_id", "prompt", "greeting")):
        raise HTTPException(409, "请先载入当前面试官和题目。")
    row = store.session(context, create=True)
    for _ in range(8):
        # 读取任务后重新核对权威轮次。迟到的换角色请求只能停止此次核对前看见的任务。
        context = owned_session(interview_id, actor)
        if row["state"] in {"starting", "active"}:
            if row["role_id"] == context["role_id"]:
                return start_result(row, context, True)
            # 浏览器可能在提交换轮后关闭。服务端负责停止上一角色的任务。
            row, _ = request_stop(row, row["task_id"])
            continue
        if row["state"] in {"stop_requested", "stopping", "stop_failed"}:
            raise HTTPException(409, "上一条 RTC 智能体任务仍在停止，请稍后重试。")
        task_id = generate_rtc_ai_agent_task_id(row["id"])
        claim = store.update(row, state="starting", task_id=task_id, role_id=context["role_id"],
                             stop_attempts=0, recover_at=now() + request_budget(), stopped_at=None,
                             started_at=None, last_heartbeat_at=now(), last_error=None)
        if claim:
            break
        row = store.get(row["id"])
    else:
        raise HTTPException(409, "RTC state changed; retry start")

    try:
        if not agent_enabled():
            raise RtcAiAgentConfigurationError("RTC agent unavailable")
        admit(actor, "rtc.start")
        fresh = owned_session(interview_id, actor)
        if (fresh["role_id"], fresh["question_id"]) != (context["role_id"], context["question_id"]):
            raise HTTPException(409, "语音轮次已变更，请重新连接当前面试官。")
        result = start_rtc_ai_agent(channel_id=claim["channel_id"], task_id=task_id,
                                    candidate_user_id=claim["candidate_user_id"], agent_user_id=claim["agent_user_id"],
                                    greeting=fresh["greeting"], prompt=fresh["prompt"])
    except HTTPException:
        fail_start(claim, "RTC admission rejected")
        raise
    except (RtcAiAgentConfigurationError, ImportError) as exc:
        fail_start(claim, "RTC provider unavailable")
        raise HTTPException(503, {"code": "rtc_agent_unavailable", "fallback": "text"}) from exc
    except Exception as exc:
        data = getattr(exc, "data", None)
        code = str(data.get("statusCode", "")) if isinstance(data, dict) else ""
        rejected = isinstance(exc, (ValueError, TypeError)) or (code.isdigit() and 400 <= int(code) < 500 and code != "408")
        fail_start(claim, "RTC start rejected" if rejected else "RTC start awaiting reconciliation", not rejected)
        raise HTTPException(502, "语音服务拒绝启动。" if rejected else "RTC AI 智能体启动结果待确认，服务端正在自动核对。") from exc
    row = acknowledge_start(claim)
    if row["task_id"] and row["task_id"] != task_id:
        raise HTTPException(409, "语音轮次已变更。")
    return {**result, **start_result(row, fresh, False)}


@router.post("/agent/stop")
def stop(interview_id: str, response: Response, payload: dict | None = None,
         actor=Depends(require_service("media", "media.rtc.stop"))):
    row = store.session(owned_session(interview_id, actor, active=False))
    expected = (payload or {}).get("expected_task_id")
    row, dispatched = request_stop(row, expected)
    status = row["state"] if row and (not expected or row["task_id"] == expected) else "stopped"
    if status != "stopped":
        response.status_code = 202
    return {"status": status, "task_id": row and row["task_id"], "idempotent": not dispatched, "rtc_session": public(row)}


@router.post("/agent/notify")
def notify(interview_id: str, payload: dict, actor=Depends(require_service("media", "media.rtc.notify"))):
    context = owned_session(interview_id, actor)
    row = store.session(context)
    if not row or row["state"] != "active" or row["role_id"] != context["role_id"]:
        raise HTTPException(409, "当前轮次没有运行中的语音任务。")
    if not context["question_id"] or payload.get("message_id") != context["question_id"]:
        raise HTTPException(409, "只能播报当前面试轮次已保存的题目。")
    if not agent_enabled():
        raise HTTPException(503, {"code": "rtc_agent_unavailable", "fallback": "text"})
    # 主动播报会新增一次云端语音操作，复用现有频道也须确认学校的媒体准入额度。
    admit(actor, "rtc.notify")
    fresh = owned_session(interview_id, actor)
    current = store.session(fresh)
    if (fresh["question_id"] != context["question_id"] or fresh["role_id"] != context["role_id"]
            or not current or current["state"] != "active" or current["task_id"] != row["task_id"]):
        raise HTTPException(409, "语音任务或题目已变化，请重新载入。")
    try:
        return notify_rtc_ai_agent(channel_id=row["channel_id"], task_id=row["task_id"],
                                   message=context["greeting"][:2000])
    except (RtcAiAgentConfigurationError, ImportError) as exc:
        raise HTTPException(503, {"code": "rtc_agent_unavailable", "fallback": "text"}) from exc
    except Exception as exc:
        raise HTTPException(502, "阿里云 RTC AI 智能体播报失败。") from exc


@router.post("/caption/validate")
def validate_caption(interview_id: str, payload: dict, actor=Depends(require_service("media", "media.rtc.caption"))):
    # 这里校验字幕所属的云任务和轮次。面试服务提交回答时仍须在事务内核对题号。
    context = owned_session(interview_id, actor)
    row = store.session(context)
    if (not row or row["state"] != "active" or not context["question_id"]
            or row["task_id"] != payload.get("task_id") or row["role_id"] != context["role_id"]
            or context["question_id"] != payload.get("question_id")):
        raise HTTPException(409, "字幕不属于当前语音任务和题目。")
    return {"task_id": row["task_id"], "role_id": row["role_id"], "question_id": context["question_id"]}


def reconcile_rtc_sessions_once():
    handled = 0
    for row in store.due():
        try:
            state = row["state"]
            if state in {"active", "stop_failed", "stopping"}:
                claim = claim_stop(row)
                if claim:
                    dispatch_stop(claim)
                    handled += 1
                continue
            if state not in {"starting", "stop_requested"}:
                continue
            # 每次只允许一个进程查询超时任务。厂商离线或进程崩溃后，由下一次到期租约接管。
            claim = store.update(row, recover_at=now() + request_budget())
            if not claim:
                continue
            try:
                remote = get_rtc_ai_agent(channel_id=claim["channel_id"], task_id=claim["task_id"])
                status = str(remote["status"]).strip().lower()
            except Exception as exc:
                if not provider_missing(exc):
                    raise
                status = "missing"
            if status in {"active", "running", "started", "starting", "success", "succeeded"}:
                acknowledge_start(claim)
            elif status in {"missing", "stopped", "finished", "completed", "failed", "error"}:
                fail_start(claim, "Remote RTC task is " + status)
            handled += 1
        except Exception as exc:
            # 日志仅记录本地任务号和异常类型，避免泄露厂商回包或凭据。
            log.warning("RTC recovery deferred for %s (%s)", row["id"], type(exc).__name__)
    return handled


async def rtc_recovery_loop():
    while True:
        try:
            await run_in_threadpool(reconcile_rtc_sessions_once)
        except Exception as exc:
            log.warning("RTC recovery pass unavailable (%s)", type(exc).__name__)
        await asyncio.sleep(setting("RTC_SESSION_RECOVERY_INTERVAL_SECONDS", 20, 5, 300))
