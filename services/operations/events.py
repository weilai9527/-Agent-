"""诊断日志只保存受控状态和关联编号，永远不保存网络报文、自由文本或浏览器提供的身份。"""

from datetime import datetime, timezone
import hashlib
import math
import re
from uuid import UUID

RTC_EVENTS = set(
    """
ai_agent_started ai_agent_status_changed ai_agent_stopped ai_agent_stop_deferred ai_agent_notify_failed
ai_agent_stop_request_failed call_start_failed call_start_requested call_stopped connection_state_changed
data_channel_closed data_channel_error data_channel_opened ice_connection_state_changed
ice_gathering_state_changed local_offer_ready microphone_acquired remote_audio_play_failed
remote_audio_playing remote_audio_track_received remote_description_applied sdp_answer_received
session_created session_update_sent session_updated upstream_error token_issued session_heartbeat_failed
startup_stage_changed transcription_received agent_audio_state_changed remote_audio_state_changed
""".split()
)
STATES = set(
    """
new connecting connected disconnected checking completed failed closed complete gathering stable
have-local-offer have-remote-offer have-local-pranswer have-remote-pranswer opening open closing
reconnecting joined joining left idle running stopped
""".split()
)
PROVIDERS = {"qwen-omni-realtime-webrtc", "aliyun-rtc-web", "openai-realtime-webrtc"}
GATEWAYS = {"student-gateway", "admin-gateway"}


def timestamp(value):
    """将历史库时间及网关时间统一成可排序的 UTC 毫秒表示。历史 SQLite/MySQL 列按 UTC 解释。"""
    if not isinstance(value, (str, datetime)):
        raise ValueError("缺少事件时间")
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return (
        parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)
        .astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
    )


def rtc_data(data, *, from_trusted_bridge=False):
    """禁止持久化客户端的 message、metadata、SDP、原始会话号及语音识别内容。"""
    kind = data.get("event_type")
    session = data.get("session_id")
    # 原生日志在网关即匿名化，已脱敏的内部字段不再重复摘要。
    ref = data.get("session_ref") if from_trusted_bridge else None
    if not isinstance(ref, str) or not re.fullmatch(r"[0-9a-f]{24}", ref):
        ref = (
            hashlib.sha256(session.encode()).hexdigest()[:24] if isinstance(session, str) and session else ""
        )
    level = data.get("level", "info")
    if level == "warn":
        level = "warning"
    if level not in ("info", "warning", "error"):
        raise ValueError("诊断级别无效")
    return {
        "event_type": kind if isinstance(kind, str) and kind in RTC_EVENTS else "other",
        "level": level,
        "session_ref": ref,
        "provider": data.get("provider") if data.get("provider") in tuple(PROVIDERS) else "other",
        **{
            key: data.get(key) if isinstance(data.get(key), str) and data[key] in STATES else ""
            for key in (
                "connection_state",
                "ice_connection_state",
                "ice_gathering_state",
                "signaling_state",
                "data_channel_state",
            )
        },
    }


def audit_data(event, source):
    """从服务生成的审计事件投影，不传 IP、登录名、请求正文、查询串、异常堆栈和业务内容。"""
    status = event.get("status_code")
    duration = event.get("duration_ms", 0)
    kind = event.get("event_type")
    if type(status) is not int or not 100 <= status <= 599:
        raise ValueError("HTTP 状态无效")
    if not isinstance(kind, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,79}", kind):
        raise ValueError("审计动作无效")
    rid = str(event["request_id"])
    if not re.fullmatch(r"[a-fA-F0-9]{32}", rid):
        raise ValueError("请求编号无效")
    return {
        "event_id": str(UUID(str(event["event_id"]))),
        "request_id": rid,
        "service": source,
        "occurred_at": timestamp(event["occurred_at"]),
        "event_type": kind,
        "status_code": status,
        "success": event.get("success", status < 400) is True,
        "response_complete": event.get("response_complete") is True,
        "reason": "响应流未完成" if event.get("response_complete") is False else f"HTTP {status}",
        "duration_ms": round(duration, 2)
        if type(duration) in (float, int) and math.isfinite(duration) and 0 <= duration <= 86400000
        else 0,
        "actor_type": event.get("actor_type")
        if event.get("actor_type") in ("student", "admin", "teacher", "system")
        else "",
        "actor_id": str(event.get("actor_id") or "")[:128],
        "method": event.get("method")
        if event.get("method") in ("GET", "POST", "PATCH", "DELETE", "HEAD", "PUT", "OPTIONS")
        else "",
    }
