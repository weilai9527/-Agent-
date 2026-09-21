from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from .database import all_rows, db, one


STARTABLE_STATES = {"idle", "stopped", "start_failed"}
STOPPABLE_STATES = {"active", "stop_failed"}
NONTERMINAL_STATES = {"starting", "active", "stop_requested", "stopping", "stop_failed"}


def utc_timestamp(*, after_seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=after_seconds)).strftime("%Y-%m-%d %H:%M:%S")


def _close(cursor: Any) -> int:
    try:
        return max(0, int(cursor.rowcount or 0))
    finally:
        cursor.close()


def get_rtc_session(interview_id: str) -> dict[str, Any] | None:
    return one(
        """
        SELECT id, interview_id, user_id, channel_id, candidate_user_id, agent_user_id,
               desired_state, state, current_task_id, revision, last_heartbeat_at,
               token_expires_at, next_retry_at, start_attempts, stop_attempts,
               last_request_id, last_error, created_at, updated_at, started_at, stopped_at
        FROM interview_rtc_sessions
        WHERE interview_id = ?
        """,
        (interview_id,),
    )


def ensure_rtc_session(
    *,
    interview_id: str,
    user_id: str,
    channel_id: str,
    candidate_user_id: str,
    agent_user_id: str,
) -> dict[str, Any]:
    existing = get_rtc_session(interview_id)
    if existing:
        return existing

    session_id = str(uuid4())
    try:
        with db:
            cursor = db.execute(
                """
                INSERT INTO interview_rtc_sessions (
                  id, interview_id, user_id, channel_id, candidate_user_id, agent_user_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, interview_id, user_id, channel_id, candidate_user_id, agent_user_id),
            )
            cursor.close()
    except Exception:
        # Concurrent token requests can both observe the row as missing. The
        # unique interview_id constraint decides the winner.
        existing = get_rtc_session(interview_id)
        if existing:
            return existing
        raise

    created = get_rtc_session(interview_id)
    if not created:
        raise RuntimeError("RTC session was not created")
    return created


def update_rtc_token_expiry(session_id: str, expires_at: str) -> dict[str, Any] | None:
    with db:
        cursor = db.execute(
            """
            UPDATE interview_rtc_sessions
            SET token_expires_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (expires_at, session_id),
        )
        cursor.close()
    return one("SELECT * FROM interview_rtc_sessions WHERE id = ?", (session_id,))


def claim_rtc_start(session_id: str, task_id: str) -> tuple[dict[str, Any], bool]:
    for _ in range(3):
        current = one("SELECT * FROM interview_rtc_sessions WHERE id = ?", (session_id,))
        if not current:
            raise RuntimeError("RTC session does not exist")
        if current["state"] not in STARTABLE_STATES:
            return current, False

        attempt_number = int(current.get("start_attempts") or 0) + 1
        with db:
            cursor = db.execute(
                """
                UPDATE interview_rtc_sessions
                SET desired_state = 'active', state = 'starting', current_task_id = ?,
                    revision = revision + 1, start_attempts = ?, stop_attempts = 0,
                    last_error = NULL, next_retry_at = NULL, stopped_at = NULL,
                    last_heartbeat_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND revision = ? AND state = ?
                """,
                (task_id, attempt_number, session_id, current["revision"], current["state"]),
            )
            claimed = _close(cursor) == 1
            if claimed:
                cursor = db.execute(
                    """
                    INSERT INTO rtc_agent_tasks (task_id, rtc_session_id, attempt_number, state)
                    VALUES (?, ?, ?, 'starting')
                    """,
                    (task_id, session_id, attempt_number),
                )
                cursor.close()
        if claimed:
            claimed_session = one("SELECT * FROM interview_rtc_sessions WHERE id = ?", (session_id,))
            if not claimed_session:
                raise RuntimeError("Claimed RTC session disappeared")
            return claimed_session, True

    current = one("SELECT * FROM interview_rtc_sessions WHERE id = ?", (session_id,))
    if not current:
        raise RuntimeError("RTC session does not exist")
    return current, False


def complete_rtc_start(session_id: str, task_id: str, request_id: str | None) -> tuple[dict[str, Any], bool]:
    with db:
        cursor = db.execute(
            """
            UPDATE rtc_agent_tasks
            SET state = 'active', start_request_id = ?, started_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP, last_error = NULL
            WHERE task_id = ? AND rtc_session_id = ?
            """,
            (request_id, task_id, session_id),
        )
        cursor.close()
        cursor = db.execute(
            """
            UPDATE interview_rtc_sessions
            SET state = 'active', last_request_id = ?, last_error = NULL,
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                last_heartbeat_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND current_task_id = ? AND state = 'starting'
              AND desired_state = 'active'
            """,
            (request_id, session_id, task_id),
        )
        activated = _close(cursor) == 1
    current = one("SELECT * FROM interview_rtc_sessions WHERE id = ?", (session_id,))
    if not current:
        raise RuntimeError("RTC session does not exist")
    return current, activated


def fail_rtc_start(session_id: str, task_id: str, message: str) -> dict[str, Any]:
    safe_message = str(message or "RTC AI agent start failed")[:1000]
    with db:
        cursor = db.execute(
            """
            UPDATE rtc_agent_tasks
            SET state = 'start_failed', last_error = ?, updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND rtc_session_id = ?
            """,
            (safe_message, task_id, session_id),
        )
        cursor.close()
        cursor = db.execute(
            """
            UPDATE interview_rtc_sessions
            SET state = CASE WHEN desired_state = 'stopped' THEN 'stopped' ELSE 'start_failed' END,
                current_task_id = CASE WHEN desired_state = 'stopped' THEN NULL ELSE current_task_id END,
                stopped_at = CASE WHEN desired_state = 'stopped' THEN CURRENT_TIMESTAMP ELSE stopped_at END,
                last_error = ?, next_retry_at = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND current_task_id = ? AND state IN ('starting', 'stop_requested')
            """,
            (safe_message, session_id, task_id),
        )
        cursor.close()
    current = one("SELECT * FROM interview_rtc_sessions WHERE id = ?", (session_id,))
    if not current:
        raise RuntimeError("RTC session does not exist")
    return current


def defer_rtc_start_reconciliation(session_id: str, task_id: str, message: str) -> dict[str, Any]:
    safe_message = str(message or "RTC AI agent start result is unknown")[:1000]
    with db:
        cursor = db.execute(
            """
            UPDATE rtc_agent_tasks
            SET last_error = ?, updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND rtc_session_id = ? AND state = 'starting'
            """,
            (safe_message, task_id, session_id),
        )
        cursor.close()
        cursor = db.execute(
            """
            UPDATE interview_rtc_sessions
            SET last_error = ?, next_retry_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND current_task_id = ? AND state IN ('starting', 'stop_requested')
            """,
            (safe_message, utc_timestamp(after_seconds=5), session_id, task_id),
        )
        cursor.close()
    current = one("SELECT * FROM interview_rtc_sessions WHERE id = ?", (session_id,))
    if not current:
        raise RuntimeError("RTC session does not exist")
    return current


def request_rtc_stop(session_id: str) -> tuple[dict[str, Any], bool]:
    for _ in range(3):
        current = one("SELECT * FROM interview_rtc_sessions WHERE id = ?", (session_id,))
        if not current:
            raise RuntimeError("RTC session does not exist")
        state = current["state"]
        task_id = current.get("current_task_id")

        if state in {"stopped", "idle", "start_failed"} or not task_id:
            with db:
                cursor = db.execute(
                    """
                    UPDATE interview_rtc_sessions
                    SET desired_state = 'stopped', state = 'stopped', current_task_id = NULL,
                        revision = revision + 1, next_retry_at = NULL,
                        stopped_at = COALESCE(stopped_at, CURRENT_TIMESTAMP),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND revision = ?
                    """,
                    (session_id, current["revision"]),
                )
                changed = _close(cursor) == 1
            if changed:
                stopped = one("SELECT * FROM interview_rtc_sessions WHERE id = ?", (session_id,))
                if not stopped:
                    raise RuntimeError("RTC session does not exist")
                return stopped, False
            continue

        if state in {"stopping", "stop_requested"}:
            return current, False

        next_state = "stop_requested" if state == "starting" else "stopping"
        with db:
            cursor = db.execute(
                """
                UPDATE interview_rtc_sessions
                SET desired_state = 'stopped', state = ?, revision = revision + 1,
                    stop_attempts = stop_attempts + 1, next_retry_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND revision = ? AND current_task_id = ? AND state = ?
                """,
                (next_state, session_id, current["revision"], task_id, state),
            )
            claimed = _close(cursor) == 1
            if claimed:
                cursor = db.execute(
                    """
                    UPDATE rtc_agent_tasks
                    SET state = ?, stop_requested_at = COALESCE(stop_requested_at, CURRENT_TIMESTAMP),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE task_id = ? AND rtc_session_id = ?
                    """,
                    (next_state, task_id, session_id),
                )
                cursor.close()
        if claimed:
            claimed_session = one("SELECT * FROM interview_rtc_sessions WHERE id = ?", (session_id,))
            if not claimed_session:
                raise RuntimeError("RTC session does not exist")
            return claimed_session, next_state == "stopping"

    current = one("SELECT * FROM interview_rtc_sessions WHERE id = ?", (session_id,))
    if not current:
        raise RuntimeError("RTC session does not exist")
    return current, False


def claim_rtc_stop_retry(session_id: str) -> tuple[dict[str, Any], bool]:
    current = one("SELECT * FROM interview_rtc_sessions WHERE id = ?", (session_id,))
    if not current or current["state"] != "stop_failed" or not current.get("current_task_id"):
        if not current:
            raise RuntimeError("RTC session does not exist")
        return current, False
    with db:
        cursor = db.execute(
            """
            UPDATE interview_rtc_sessions
            SET state = 'stopping', revision = revision + 1,
                stop_attempts = stop_attempts + 1, next_retry_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND revision = ? AND state = 'stop_failed'
            """,
            (session_id, current["revision"]),
        )
        claimed = _close(cursor) == 1
    result = one("SELECT * FROM interview_rtc_sessions WHERE id = ?", (session_id,))
    if not result:
        raise RuntimeError("RTC session does not exist")
    return result, claimed


def claim_stuck_rtc_stop(session_id: str) -> tuple[dict[str, Any], bool]:
    current = one("SELECT * FROM interview_rtc_sessions WHERE id = ?", (session_id,))
    if not current or current["state"] not in {"stopping", "stop_requested"} or not current.get("current_task_id"):
        if not current:
            raise RuntimeError("RTC session does not exist")
        return current, False
    with db:
        cursor = db.execute(
            """
            UPDATE interview_rtc_sessions
            SET state = 'stopping', revision = revision + 1,
                stop_attempts = stop_attempts + 1, next_retry_at = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND revision = ? AND state = ? AND current_task_id = ?
            """,
            (
                utc_timestamp(after_seconds=60),
                session_id,
                current["revision"],
                current["state"],
                current["current_task_id"],
            ),
        )
        claimed = _close(cursor) == 1
    result = one("SELECT * FROM interview_rtc_sessions WHERE id = ?", (session_id,))
    if not result:
        raise RuntimeError("RTC session does not exist")
    return result, claimed


def complete_rtc_stop(session_id: str, task_id: str, request_id: str | None) -> dict[str, Any]:
    with db:
        cursor = db.execute(
            """
            UPDATE rtc_agent_tasks
            SET state = 'stopped', stop_request_id = ?, stopped_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP, last_error = NULL
            WHERE task_id = ? AND rtc_session_id = ?
            """,
            (request_id, task_id, session_id),
        )
        cursor.close()
        cursor = db.execute(
            """
            UPDATE interview_rtc_sessions
            SET desired_state = 'stopped', state = 'stopped', current_task_id = NULL,
                revision = revision + 1, last_request_id = ?, last_error = NULL,
                next_retry_at = NULL, stopped_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND current_task_id = ?
            """,
            (request_id, session_id, task_id),
        )
        cursor.close()
    current = one("SELECT * FROM interview_rtc_sessions WHERE id = ?", (session_id,))
    if not current:
        raise RuntimeError("RTC session does not exist")
    return current


def fail_rtc_stop(session_id: str, task_id: str, message: str) -> dict[str, Any]:
    safe_message = str(message or "RTC AI agent stop failed")[:1000]
    current = one("SELECT stop_attempts FROM interview_rtc_sessions WHERE id = ?", (session_id,)) or {}
    retry_seconds = min(300, max(5, 5 * (2 ** min(int(current.get("stop_attempts") or 1) - 1, 6))))
    with db:
        cursor = db.execute(
            """
            UPDATE rtc_agent_tasks
            SET state = 'stop_failed', last_error = ?, updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND rtc_session_id = ?
            """,
            (safe_message, task_id, session_id),
        )
        cursor.close()
        cursor = db.execute(
            """
            UPDATE interview_rtc_sessions
            SET desired_state = 'stopped', state = 'stop_failed', last_error = ?,
                next_retry_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND current_task_id = ?
            """,
            (safe_message, utc_timestamp(after_seconds=retry_seconds), session_id, task_id),
        )
        cursor.close()
    result = one("SELECT * FROM interview_rtc_sessions WHERE id = ?", (session_id,))
    if not result:
        raise RuntimeError("RTC session does not exist")
    return result


def heartbeat_rtc_session(session_id: str) -> dict[str, Any]:
    with db:
        cursor = db.execute(
            """
            UPDATE interview_rtc_sessions
            SET last_heartbeat_at = CURRENT_TIMESTAMP
            WHERE id = ? AND desired_state = 'active' AND state IN ('starting', 'active')
            """,
            (session_id,),
        )
        cursor.close()
    current = one("SELECT * FROM interview_rtc_sessions WHERE id = ?", (session_id,))
    if not current:
        raise RuntimeError("RTC session does not exist")
    return current


def list_rtc_recovery_candidates(limit: int = 100) -> list[dict[str, Any]]:
    return all_rows(
        """
        SELECT rtc.*, interviews.status AS interview_status
        FROM interview_rtc_sessions AS rtc
        JOIN interview_sessions AS interviews ON interviews.id = rtc.interview_id
        WHERE rtc.state IN ('starting', 'active', 'stop_requested', 'stopping', 'stop_failed')
        ORDER BY rtc.updated_at ASC
        LIMIT ?
        """,
        (max(1, min(int(limit), 500)),),
    )


def mark_rtc_active_from_recovery(session_id: str, task_id: str, request_id: str | None = None) -> dict[str, Any]:
    with db:
        cursor = db.execute(
            """
            UPDATE interview_rtc_sessions
            SET state = 'active', last_request_id = COALESCE(?, last_request_id),
                last_error = NULL, started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND current_task_id = ? AND desired_state = 'active'
              AND state = 'starting'
            """,
            (request_id, session_id, task_id),
        )
        cursor.close()
        cursor = db.execute(
            """
            UPDATE rtc_agent_tasks
            SET state = 'active', start_request_id = COALESCE(?, start_request_id),
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP), updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND rtc_session_id = ?
            """,
            (request_id, task_id, session_id),
        )
        cursor.close()
    result = one("SELECT * FROM interview_rtc_sessions WHERE id = ?", (session_id,))
    if not result:
        raise RuntimeError("RTC session does not exist")
    return result
