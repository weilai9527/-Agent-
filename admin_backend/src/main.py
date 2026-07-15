from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .database import all_rows, db, ensure_admin_schema, get_database_path, one
from .security import (
    create_token,
    hash_password,
    hash_token,
    is_valid_email,
    normalize_email,
    sanitize_admin,
    verify_password,
)
from shared.career_catalog import (
    approve_job_suggestion_to_draft,
    catalog_tree,
    create_catalog_entity,
    create_version,
    delete_catalog_entity,
    has_permission,
    import_catalog_excel,
    list_job_suggestions,
    list_versions,
    merge_job_suggestion,
    publish_version,
    replace_job_competencies,
    review_job_suggestion,
    update_catalog_entity,
)


app = FastAPI(title="Multi Agent Interview Admin API")
PROJECT_DIR = Path(__file__).resolve().parents[2]
USER_BACKEND_ENV_PATH = PROJECT_DIR / "backend" / ".env"
ADMIN_SESSION_COOKIE = "admin_session"
ADMIN_SESSION_MAX_AGE = int(os.environ.get("ADMIN_SESSION_MAX_AGE", str(60 * 60 * 8)))
ADMIN_ROLES = {"super_admin", "operations", "reviewer"}
LOGIN_WINDOW_SECONDS = 15 * 60
MAX_LOGIN_ATTEMPTS = 8
login_attempts: dict[str, dict[str, int | float]] = {}

allowed_origins = [
    origin.strip()
    for origin in os.environ.get(
        "ADMIN_FRONTEND_ORIGIN",
        "http://127.0.0.1:5174,http://127.0.0.1:5175,http://127.0.0.1:5176,"
        "http://localhost:5174,http://localhost:5175,http://localhost:5176",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


def error(status_code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": message})


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        return JSONResponse(status_code=exc.status_code, content={"error": detail["error"]})
    return JSONResponse(status_code=exc.status_code, content={"error": str(detail)})


def utc_after(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S")


def request_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def validate_admin_origin(request: Request) -> None:
    origin = (request.headers.get("origin") or "").strip()
    if origin and origin not in allowed_origins:
        raise error(403, "管理端请求来源不受信任。")


def find_admin_by_session(request: Request) -> dict | None:
    token = request.cookies.get(ADMIN_SESSION_COOKIE)
    if not token:
        return None
    return one(
        """
        SELECT users.id, users.email, users.name, users.role, users.status, users.last_login_at
        FROM admin_sessions AS sessions
        JOIN admin_users AS users ON users.id = sessions.admin_user_id
        WHERE sessions.token_hash = ?
          AND sessions.expires_at > ?
          AND users.status = 'normal'
        """,
        (hash_token(token), utc_after(0)),
    )


def require_admin(request: Request) -> dict:
    admin = find_admin_by_session(request)
    if not admin:
        raise error(401, "管理员登录已失效，请重新登录。")
    return admin


def require_roles(*roles: str):
    allowed = set(roles)

    def dependency(admin: dict = Depends(require_admin)) -> dict:
        if admin.get("role") not in allowed:
            raise error(403, "当前管理员没有执行该操作的权限。")
        return admin

    return dependency


def require_catalog_permission(permission: str):
    def dependency(admin: dict = Depends(require_admin)) -> dict:
        if not has_permission(db, str(admin.get("role") or ""), permission):
            raise error(403, "当前管理员没有执行该目录操作的权限。")
        return admin

    return dependency


def create_admin_session(response: Response, request: Request, admin_user_id: str) -> None:
    token = create_token()
    db.execute(
        """
        INSERT INTO admin_sessions (id, admin_user_id, token_hash, expires_at, user_agent, ip_address)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid4()),
            admin_user_id,
            hash_token(token),
            utc_after(ADMIN_SESSION_MAX_AGE),
            request.headers.get("user-agent"),
            request_ip(request),
        ),
    )
    db.commit()
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        token,
        httponly=True,
        secure=os.environ.get("ADMIN_COOKIE_SECURE", "false").lower() == "true",
        samesite="lax",
        path="/",
        max_age=ADMIN_SESSION_MAX_AGE,
    )


def clear_admin_session(response: Response) -> None:
    response.delete_cookie(
        ADMIN_SESSION_COOKIE,
        httponly=True,
        secure=os.environ.get("ADMIN_COOKIE_SECURE", "false").lower() == "true",
        samesite="lax",
        path="/",
    )


def record_audit(
    request: Request,
    admin: dict | None,
    action: str,
    *,
    target_type: str = "system",
    target_id: str = "",
    summary: str = "",
    success: bool = True,
) -> None:
    db.execute(
        """
        INSERT INTO admin_audit_logs (
          id, admin_user_id, actor_email, action, target_type, target_id,
          summary, ip_address, user_agent, success
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid4()),
            admin.get("id") if admin else None,
            admin.get("email") if admin else None,
            action,
            target_type,
            target_id or None,
            summary[:1000],
            request_ip(request),
            request.headers.get("user-agent"),
            1 if success else 0,
        ),
    )
    db.commit()


def login_attempt_key(request: Request, email: str) -> str:
    return f"{request_ip(request)}:{email}"


def is_login_limited(request: Request, email: str) -> bool:
    key = login_attempt_key(request, email)
    record = login_attempts.get(key)
    if not record:
        return False
    if float(record["reset_at"]) <= time.time():
        login_attempts.pop(key, None)
        return False
    return int(record["count"]) >= MAX_LOGIN_ATTEMPTS


def record_failed_login(request: Request, email: str) -> None:
    key = login_attempt_key(request, email)
    now = time.time()
    record = login_attempts.get(key)
    if not record or float(record["reset_at"]) <= now:
        login_attempts[key] = {"count": 1, "reset_at": now + LOGIN_WINDOW_SECONDS}
    else:
        record["count"] = int(record["count"]) + 1


def clear_failed_logins(request: Request, email: str) -> None:
    login_attempts.pop(login_attempt_key(request, email), None)


def bootstrap_admin_from_env() -> None:
    email = normalize_email(os.environ.get("ADMIN_BOOTSTRAP_EMAIL"))
    password = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD", "")
    name = os.environ.get("ADMIN_BOOTSTRAP_NAME", "系统管理员").strip() or "系统管理员"
    role = os.environ.get("ADMIN_BOOTSTRAP_ROLE", "super_admin").strip()
    if not email and not password:
        return
    if not is_valid_email(email) or len(password) < 12 or role not in ADMIN_ROLES:
        raise RuntimeError("管理员初始化配置无效：邮箱需有效、密码至少 12 位且角色必须合法。")
    existing = one("SELECT id FROM admin_users WHERE email = ?", (email,))
    if existing:
        return
    db.execute(
        """
        INSERT INTO admin_users (id, email, password_hash, name, role, status)
        VALUES (?, ?, ?, ?, ?, 'normal')
        """,
        (str(uuid4()), email, hash_password(password), name[:80], role),
    )
    db.commit()


def list_audit_logs(limit: int = 50) -> list[dict[str, Any]]:
    rows = all_rows(
        """
        SELECT id, actor_email, action, target_type, target_id, summary, success, created_at
        FROM admin_audit_logs
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (max(1, min(limit, 100)),),
    )
    return [
        {
            "id": row["id"],
            "actor": row.get("actor_email") or "系统",
            "action": row["action"],
            "target": f"{row.get('target_type') or 'system'}:{row.get('target_id') or '-'}",
            "summary": row.get("summary") or "",
            "success": bool(row.get("success")),
            "time": str(row.get("created_at") or "-"),
        }
        for row in rows
    ]


def list_admin_accounts() -> list[dict[str, Any]]:
    users = all_rows(
        """
        SELECT id, email, name, role, status, created_at, updated_at, last_login_at
        FROM admin_users ORDER BY created_at ASC
        """
    )
    return [sanitize_admin(user) | {"created_at": str(user.get("created_at") or "-")} for user in users]


ensure_admin_schema()
bootstrap_admin_from_env()


def count_value(sql: str, params: tuple = ()) -> int:
    row = one(sql, params) or {}
    return int(row.get("count") or 0)


def avg_value(sql: str, params: tuple = ()) -> float:
    row = one(sql, params) or {}
    return round(float(row.get("value") or 0), 1)


def status_label(value: str | None) -> str:
    return {"draft": "草稿", "running": "进行中", "completed": "已完成", "normal": "正常"}.get(value or "", value or "-")


def report_review_status(score: int) -> str:
    if score < 70:
        return "需要复核"
    if score < 80:
        return "待抽检"
    return "已复核"


def recommendation_label(value: str | None) -> str:
    return {
        "strong_pass": "强烈建议录用",
        "pass": "建议录用",
        "next_round": "进入下一轮",
        "hold": "暂缓",
        "reject": "不建议通过",
    }.get(value or "", value or "-")


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


PLACEHOLDER_VALUES = {
    "your-api-key-here",
    "your-dashscope-api-key",
    "your-kimi-api-key-here",
    "your-deepseek-api-key-here",
    "placeholder",
}


def is_placeholder_secret(value: str | None) -> bool:
    cleaned = (value or "").strip().lower()
    if not cleaned:
        return False
    return (
        cleaned in PLACEHOLDER_VALUES
        or cleaned.startswith("your-")
        or "api-key-here" in cleaned
    )


def configured_secret(env_values: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = (env_values.get(key) or os.environ.get(key, "")).strip()
        if value and not is_placeholder_secret(value):
            return value
    return ""


def write_env_values(path: Path, updates: dict[str, str]) -> None:
    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    next_lines: list[str] = []
    for raw_line in existing_lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            next_lines.append(raw_line)
            continue
        key, _value = raw_line.split("=", 1)
        key = key.strip()
        if key in updates:
            next_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            next_lines.append(raw_line)
    for key, value in updates.items():
        if key not in seen:
            next_lines.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(next_lines).rstrip() + "\n", encoding="utf-8")


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "已配置"
    return f"{value[:4]}...{value[-4:]}"


def build_settings() -> dict[str, Any]:
    backend_env = read_env_file(USER_BACKEND_ENV_PATH)
    openai_key = configured_secret(backend_env, "OPENAI_REALTIME_API_KEY", "OPENAI_API_KEY")
    report_openai_key = configured_secret(backend_env, "OPENAI_API_KEY")
    report_qwen_key = configured_secret(backend_env, "QWEN_API_KEY")
    dashscope_key = configured_secret(backend_env, "DASHSCOPE_API_KEY")
    qwen_omni_key = configured_secret(
        backend_env,
        "QWEN_OMNI_REALTIME_API_KEY",
        "QWEN_OMNI_API_KEY",
        "DASHSCOPE_API_KEY",
    )
    return {
        "openaiRealtimeModel": backend_env.get("OPENAI_REALTIME_MODEL") or os.environ.get("OPENAI_REALTIME_MODEL", "gpt-realtime-2"),
        "openaiVoice": backend_env.get("OPENAI_REALTIME_VOICE") or os.environ.get("OPENAI_REALTIME_VOICE", "marin"),
        "qwenTtsModel": backend_env.get("DASHSCOPE_TTS_MODEL") or os.environ.get("DASHSCOPE_TTS_MODEL", "cosyvoice-v3-flash"),
        "qwenTtsVoice": backend_env.get("DASHSCOPE_TTS_VOICE") or os.environ.get("DASHSCOPE_TTS_VOICE", "longanyang"),
        "qwenTtsRegion": backend_env.get("DASHSCOPE_TTS_REGION") or os.environ.get("DASHSCOPE_TTS_REGION", "beijing"),
        "qwenTtsWorkspaceId": backend_env.get("DASHSCOPE_WORKSPACE_ID") or os.environ.get("DASHSCOPE_WORKSPACE_ID", ""),
        "qwenOmniModel": backend_env.get("QWEN_OMNI_REALTIME_MODEL") or os.environ.get("QWEN_OMNI_REALTIME_MODEL", "qwen3.5-omni-plus-realtime"),
        "qwenOmniVoice": backend_env.get("QWEN_OMNI_REALTIME_VOICE") or os.environ.get("QWEN_OMNI_REALTIME_VOICE", "Tina"),
        "qwenOmniRegion": backend_env.get("QWEN_OMNI_REALTIME_REGION") or os.environ.get("QWEN_OMNI_REALTIME_REGION", "beijing"),
        "qwenOmniWorkspaceId": backend_env.get("QWEN_OMNI_REALTIME_WORKSPACE_ID") or backend_env.get("DASHSCOPE_WORKSPACE_ID") or os.environ.get("QWEN_OMNI_REALTIME_WORKSPACE_ID") or os.environ.get("DASHSCOPE_WORKSPACE_ID", ""),
        "qwenOmniEndpoint": backend_env.get("QWEN_OMNI_REALTIME_WEBRTC_ENDPOINT") or os.environ.get("QWEN_OMNI_REALTIME_WEBRTC_ENDPOINT", ""),
        "reviewRule": "低于 70 分自动进入复核",
        "openaiApiKeyConfigured": bool(openai_key and openai_key != "your-api-key-here"),
        "openaiApiKeyMasked": mask_secret(openai_key),
        "reportOpenaiApiKeyConfigured": bool(report_openai_key),
        "reportOpenaiApiKeyMasked": mask_secret(report_openai_key),
        "reportOpenaiModel": backend_env.get("OPENAI_FOLLOWUP_MODEL") or os.environ.get("OPENAI_FOLLOWUP_MODEL", "gpt-4o-mini"),
        "reportQwenApiKeyConfigured": bool(report_qwen_key),
        "reportQwenApiKeyMasked": mask_secret(report_qwen_key),
        "reportQwenModel": backend_env.get("QWEN_MODEL") or os.environ.get("QWEN_MODEL", "qwen-plus"),
        "reportProviderOrder": backend_env.get("REPORT_PROVIDER_ORDER") or os.environ.get("REPORT_PROVIDER_ORDER", "openai,qwen"),
        "reportTimeout": int(backend_env.get("AI_REPORT_TIMEOUT") or os.environ.get("AI_REPORT_TIMEOUT", "60")),
        "reportRetries": int(backend_env.get("AI_REPORT_HTTP_RETRIES") or os.environ.get("AI_REPORT_HTTP_RETRIES", "1")),
        "dashscopeApiKeyConfigured": bool(dashscope_key),
        "dashscopeApiKeyMasked": mask_secret(dashscope_key),
        "qwenOmniApiKeyConfigured": bool(qwen_omni_key),
        "qwenOmniApiKeyMasked": mask_secret(qwen_omni_key),
        "envPath": str(USER_BACKEND_ENV_PATH),
    }


def list_candidates() -> list[dict[str, Any]]:
    rows = all_rows(
        """
        SELECT users.id, users.email, users.name, users.status, users.created_at, users.last_login_at,
               profiles.target_role,
               COALESCE(interview_counts.interviews, 0) AS interviews,
               COALESCE(report_scores.average_score, 0) AS average_score
        FROM users
        LEFT JOIN profiles ON profiles.user_id = users.id
        LEFT JOIN (
          SELECT user_id, COUNT(*) AS interviews
          FROM interview_sessions
          GROUP BY user_id
        ) AS interview_counts ON interview_counts.user_id = users.id
        LEFT JOIN (
          SELECT user_id, AVG(total_score) AS average_score
          FROM interview_reports
          GROUP BY user_id
        ) AS report_scores ON report_scores.user_id = users.id
        ORDER BY users.updated_at DESC, users.created_at DESC
        LIMIT 50
        """
    )
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "role": row.get("target_role") or "未填写",
            "status": status_label(row.get("status")),
            "interviews": int(row.get("interviews") or 0),
            "averageScore": round(float(row.get("average_score") or 0), 1),
            "lastLogin": str(row.get("last_login_at") or "-"),
        }
        for row in rows
    ]


def get_candidate_detail(candidate_id: str) -> dict[str, Any]:
    row = one(
        """
        SELECT users.id, users.email, users.name, users.status, users.created_at, users.updated_at,
               users.last_login_at, profiles.nickname, profiles.target_role, profiles.experience_level,
               profiles.company_type, profiles.target_city, profiles.expected_salary,
               profiles.years_of_experience, profiles.education_level, profiles.skills,
               profiles.project_keywords, profiles.resume_text, profiles.project_experience,
               profiles.portfolio_links
        FROM users
        LEFT JOIN profiles ON profiles.user_id = users.id
        WHERE users.id = ?
        """,
        (candidate_id,),
    )
    if not row:
        raise error(404, "用户不存在。")
    return row


def list_interviews() -> list[dict[str, Any]]:
    rows = all_rows(
        """
        SELECT interviews.id, interviews.target_role, interviews.interview_type, interviews.status,
               interviews.updated_at, users.name AS candidate,
               COALESCE(agent_counts.agent_count, 0) AS agent_count,
               COALESCE(message_counts.message_count, 0) AS message_count
        FROM interview_sessions AS interviews
        JOIN users ON users.id = interviews.user_id
        LEFT JOIN (
          SELECT interview_id, COUNT(*) AS agent_count
          FROM interview_agents
          GROUP BY interview_id
        ) AS agent_counts ON agent_counts.interview_id = interviews.id
        LEFT JOIN (
          SELECT interview_id, COUNT(*) AS message_count
          FROM interview_messages
          GROUP BY interview_id
        ) AS message_counts ON message_counts.interview_id = interviews.id
        ORDER BY interviews.updated_at DESC, interviews.created_at DESC
        LIMIT 50
        """
    )
    return [
        {
            "id": row["id"],
            "candidate": row["candidate"],
            "role": row.get("target_role") or "-",
            "type": row.get("interview_type") or "综合模拟",
            "status": status_label(row.get("status")),
            "agents": f"{int(row.get('agent_count') or 0)}/3",
            "messages": int(row.get("message_count") or 0),
            "updatedAt": str(row.get("updated_at") or "-"),
        }
        for row in rows
    ]


def get_interview_detail(interview_id: str) -> dict[str, Any]:
    interview = one(
        """
        SELECT interviews.*, users.name AS candidate, users.email AS candidate_email
        FROM interview_sessions AS interviews
        JOIN users ON users.id = interviews.user_id
        WHERE interviews.id = ?
        """,
        (interview_id,),
    )
    if not interview:
        raise error(404, "面试不存在。")
    agents = all_rows(
        """
        SELECT id, agent_name, agent_type, agent_role, strategy, order_index, status, created_at, updated_at
        FROM interview_agents
        WHERE interview_id = ?
        ORDER BY order_index ASC, created_at ASC
        """,
        (interview_id,),
    )
    messages = all_rows(
        """
        SELECT messages.id, messages.sender_type, messages.message_type, messages.content,
               messages.transcript_text, messages.order_index, messages.created_at,
               agents.agent_name, agents.agent_type
        FROM interview_messages AS messages
        LEFT JOIN interview_agents AS agents ON agents.id = messages.agent_id
        WHERE messages.interview_id = ?
        ORDER BY messages.order_index ASC, messages.created_at ASC
        LIMIT 80
        """,
        (interview_id,),
    )
    return {"interview": interview, "agents": agents, "messages": messages}


def list_reports() -> list[dict[str, Any]]:
    rows = all_rows(
        """
        SELECT reports.id, reports.total_score, reports.grade, reports.pass_recommendation,
               reports.review_status, reports.provider, reports.model, reports.fallback,
               reports.created_at, users.name AS candidate, interviews.target_role
        FROM interview_reports AS reports
        JOIN users ON users.id = reports.user_id
        JOIN interview_sessions AS interviews ON interviews.id = reports.interview_id
        ORDER BY reports.updated_at DESC, reports.created_at DESC
        LIMIT 50
        """
    )
    return [
        {
            "id": row["id"],
            "candidate": row["candidate"],
            "role": row.get("target_role") or "-",
            "score": int(row.get("total_score") or 0),
            "grade": row.get("grade") or "-",
            "recommendation": recommendation_label(row.get("pass_recommendation")),
            "reviewStatus": {"approved": "已复核", "rejected": "复核未通过", "pending": "待复核"}.get(row.get("review_status"), "待复核"),
            "provider": row.get("provider") or "local",
            "model": row.get("model") or "rules-v1",
            "fallback": bool(row.get("fallback")),
            "createdAt": str(row.get("created_at") or "-"),
        }
        for row in rows
    ]


def get_report_detail(report_id: str) -> dict[str, Any]:
    report = one(
        """
        SELECT reports.*, users.name AS candidate, users.email AS candidate_email,
               interviews.target_role, interviews.interview_type, interviews.difficulty
        FROM interview_reports AS reports
        JOIN users ON users.id = reports.user_id
        JOIN interview_sessions AS interviews ON interviews.id = reports.interview_id
        WHERE reports.id = ?
        """,
        (report_id,),
    )
    if not report:
        raise error(404, "报告不存在。")
    return report


def list_agent_templates() -> list[dict[str, Any]]:
    rows = all_rows(
        """
        SELECT agent_name, agent_type, agent_role, COUNT(*) AS usage_count
        FROM interview_agents
        GROUP BY agent_name, agent_type, agent_role
        ORDER BY usage_count DESC, agent_name ASC
        LIMIT 20
        """
    )
    return [
        {
            "name": row.get("agent_name") or "-",
            "type": row.get("agent_type") or "-",
            "status": "启用",
            "focus": row.get("agent_role") or "-",
            "usageCount": int(row.get("usage_count") or 0),
        }
        for row in rows
    ]


def get_agent_detail(agent_name: str) -> dict[str, Any]:
    row = one(
        """
        SELECT agent_name, agent_type, agent_role, strategy, COUNT(*) AS usage_count
        FROM interview_agents
        WHERE agent_name = ?
        GROUP BY agent_name, agent_type, agent_role, strategy
        ORDER BY usage_count DESC
        LIMIT 1
        """,
        (agent_name,),
    )
    if not row:
        raise error(404, "Agent 不存在。")
    recent = all_rows(
        """
        SELECT agents.interview_id, agents.status, agents.updated_at,
               interviews.target_role, users.name AS candidate
        FROM interview_agents AS agents
        JOIN interview_sessions AS interviews ON interviews.id = agents.interview_id
        JOIN users ON users.id = interviews.user_id
        WHERE agents.agent_name = ?
        ORDER BY agents.updated_at DESC
        LIMIT 20
        """,
        (agent_name,),
    )
    return {"agent": row, "recentUsage": recent}


def build_metrics(reports: list[dict[str, Any]]) -> list[dict[str, str]]:
    users = count_value("SELECT COUNT(*) AS count FROM users")
    interviews = count_value("SELECT COUNT(*) AS count FROM interview_sessions")
    completed = count_value("SELECT COUNT(*) AS count FROM interview_sessions WHERE status = ?", ("completed",))
    report_count = count_value("SELECT COUNT(*) AS count FROM interview_reports")
    average_score = avg_value("SELECT AVG(total_score) AS value FROM interview_reports")
    review_count = len([report for report in reports if report["reviewStatus"] != "已复核"])
    completion_rate = round(completed / interviews * 100) if interviews else 0
    return [
        {"label": "注册用户", "value": f"{users:,}", "note": "来自 users", "tone": "blue"},
        {"label": "面试任务", "value": f"{interviews:,}", "note": f"完成率 {completion_rate}%", "tone": "green"},
        {"label": "报告生成", "value": f"{report_count:,}", "note": f"平均分 {average_score}", "tone": "amber"},
        {"label": "待复核", "value": f"{review_count:,}", "note": "按分数规则计算", "tone": "red"},
    ]


@app.get("/api/admin/health")
def health():
    return {"ok": True, "authRequired": True, "databasePath": get_database_path()}


@app.get("/api/admin/catalog/versions")
def admin_catalog_versions(_admin: dict = Depends(require_catalog_permission("read"))):
    return {"versions": list_versions(db, include_drafts=True)}


@app.post("/api/admin/catalog/versions", status_code=201)
async def admin_create_catalog_version(request: Request, admin: dict = Depends(require_catalog_permission("write"))):
    validate_admin_origin(request)
    try:
        version = create_version(db, await request.json(), admin.get("id"))
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    record_audit(request, admin, "catalog.version.create", target_type="catalog_version", target_id=version["id"], summary=version["code"])
    return {"version": version}


@app.get("/api/admin/catalog/tree")
def admin_catalog_tree(version: str | None = None, _admin: dict = Depends(require_catalog_permission("read"))):
    result = catalog_tree(db, version_code=version, include_disabled=True, include_drafts=True)
    if not result:
        raise error(404, "职业能力目录版本不存在。")
    return result


@app.post("/api/admin/catalog/versions/{version_id}/entities/{entity_type}", status_code=201)
async def admin_create_catalog_entity(
    request: Request,
    version_id: str,
    entity_type: str,
    admin: dict = Depends(require_catalog_permission("write")),
):
    validate_admin_origin(request)
    try:
        item = create_catalog_entity(db, version_id, entity_type, await request.json())
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    record_audit(
        request,
        admin,
        f"catalog.{entity_type}.create",
        target_type=entity_type,
        target_id=item["id"],
        summary=item.get("name") or item.get("code"),
    )
    return {"item": item}


@app.patch("/api/admin/catalog/versions/{version_id}/entities/{entity_type}/{entity_id}")
async def admin_update_catalog_entity(
    request: Request,
    version_id: str,
    entity_type: str,
    entity_id: str,
    admin: dict = Depends(require_catalog_permission("write")),
):
    validate_admin_origin(request)
    try:
        item = update_catalog_entity(db, version_id, entity_type, entity_id, await request.json())
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    if not item:
        raise error(404, "目录数据不存在。")
    record_audit(
        request,
        admin,
        f"catalog.{entity_type}.update",
        target_type=entity_type,
        target_id=entity_id,
        summary=item.get("name") or item.get("code"),
    )
    return {"item": item}


@app.delete("/api/admin/catalog/versions/{version_id}/entities/{entity_type}/{entity_id}")
def admin_delete_catalog_entity(
    request: Request,
    version_id: str,
    entity_type: str,
    entity_id: str,
    admin: dict = Depends(require_catalog_permission("write")),
):
    validate_admin_origin(request)
    try:
        deleted = delete_catalog_entity(db, version_id, entity_type, entity_id)
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    if not deleted:
        raise error(404, "目录数据不存在。")
    record_audit(request, admin, f"catalog.{entity_type}.delete", target_type=entity_type, target_id=entity_id)
    return {"ok": True}


@app.put("/api/admin/catalog/versions/{version_id}/jobs/{job_role_id}/competencies")
async def admin_replace_job_competencies(
    request: Request,
    version_id: str,
    job_role_id: str,
    admin: dict = Depends(require_catalog_permission("write")),
):
    validate_admin_origin(request)
    body = await request.json()
    items = body.get("competencies")
    if not isinstance(items, list):
        raise error(400, "岗位能力配置必须是数组。")
    try:
        competencies = replace_job_competencies(db, version_id, job_role_id, items)
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    record_audit(
        request,
        admin,
        "catalog.job.competencies.replace",
        target_type="job_role",
        target_id=job_role_id,
        summary=f"{len(competencies)} 项能力要求",
    )
    return {"competencies": competencies}


@app.post("/api/admin/catalog/versions/{version_id}/publish")
def admin_publish_catalog_version(request: Request, version_id: str, admin: dict = Depends(require_catalog_permission("publish"))):
    validate_admin_origin(request)
    try:
        version = publish_version(db, version_id, admin.get("id"))
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    if not version:
        raise error(404, "职业能力目录版本不存在。")
    record_audit(request, admin, "catalog.version.publish", target_type="catalog_version", target_id=version_id, summary=version["code"])
    return {"version": version}


@app.post("/api/admin/catalog/versions/{version_id}/imports", status_code=201)
async def admin_import_catalog(
    request: Request,
    version_id: str,
    file: UploadFile = File(...),
    mode: str = "merge",
    admin: dict = Depends(require_catalog_permission("import")),
):
    validate_admin_origin(request)
    filename = (file.filename or "catalog.xlsx").strip()
    if not filename.lower().endswith(".xlsx"):
        raise error(400, "目录导入仅支持 .xlsx 文件。")
    content = await file.read()
    if not content or len(content) > 10 * 1024 * 1024:
        raise error(400, "Excel 文件不能为空且不能超过 10MB。")
    try:
        job = import_catalog_excel(db, version_id, filename, content, mode, admin.get("id"))
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    record_audit(request, admin, "catalog.excel.import", target_type="catalog_version", target_id=version_id, summary=f"{filename}，{job['imported_rows']} 行")
    return {"import_job": job}


@app.get("/api/admin/catalog/job-suggestions")
def admin_job_suggestions(status: str | None = None, _admin: dict = Depends(require_catalog_permission("read"))):
    if status and status not in {"pending", "approved", "rejected", "merged"}:
        raise error(400, "岗位建议状态不正确。")
    return {"suggestions": list_job_suggestions(db, status)}


@app.post("/api/admin/catalog/job-suggestions/{suggestion_id}/review")
async def admin_review_job_suggestion(
    request: Request,
    suggestion_id: str,
    admin: dict = Depends(require_catalog_permission("write")),
):
    validate_admin_origin(request)
    body = await request.json()
    status = str(body.get("status") or "").strip()
    try:
        suggestion = review_job_suggestion(db, suggestion_id, status, admin.get("id"), body.get("note"))
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    if not suggestion:
        raise error(404, "岗位建议不存在。")
    record_audit(request, admin, f"catalog.suggestion.{status}", target_type="job_suggestion", target_id=suggestion_id, summary=suggestion["suggested_name"])
    return {"suggestion": suggestion}


@app.post("/api/admin/catalog/job-suggestions/{suggestion_id}/merge")
async def admin_merge_job_suggestion(
    request: Request,
    suggestion_id: str,
    admin: dict = Depends(require_catalog_permission("write")),
):
    validate_admin_origin(request)
    body = await request.json()
    job_role_id = str(body.get("job_role_id") or "").strip()
    if not job_role_id:
        raise error(400, "请选择需要合并到的正式岗位。")
    try:
        suggestion = merge_job_suggestion(db, suggestion_id, job_role_id, admin.get("id"))
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    if not suggestion:
        raise error(404, "岗位建议不存在。")
    record_audit(request, admin, "catalog.suggestion.merge", target_type="job_suggestion", target_id=suggestion_id, summary=suggestion["suggested_name"])
    return {"suggestion": suggestion}


@app.post("/api/admin/catalog/job-suggestions/{suggestion_id}/approve-to-draft", status_code=201)
async def admin_approve_job_suggestion_to_draft(
    request: Request,
    suggestion_id: str,
    admin: dict = Depends(require_catalog_permission("write")),
):
    validate_admin_origin(request)
    body = await request.json()
    version_id = str(body.get("version_id") or "").strip()
    if not version_id:
        raise error(400, "请选择需要写入的目录草稿。")
    try:
        result = approve_job_suggestion_to_draft(db, suggestion_id, version_id, body, admin.get("id"))
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    if not result:
        raise error(404, "岗位建议不存在。")
    record_audit(
        request,
        admin,
        "catalog.suggestion.approve_to_draft",
        target_type="job_suggestion",
        target_id=suggestion_id,
        summary=f"{result['suggestion']['suggested_name']} → {result['job_role']['code']}",
    )
    return result


@app.post("/api/admin/auth/login")
async def admin_login(request: Request, response: Response):
    validate_admin_origin(request)
    body = await request.json()
    email = normalize_email(body.get("email"))
    password = str(body.get("password") or "")
    if not is_valid_email(email) or not password:
        raise error(400, "请输入有效的管理员邮箱和密码。")
    if is_login_limited(request, email):
        raise error(429, "登录尝试过于频繁，请稍后再试。")
    admin = one(
        """
        SELECT id, email, password_hash, name, role, status, last_login_at
        FROM admin_users WHERE email = ?
        """,
        (email,),
    )
    if not admin or admin.get("status") != "normal" or not verify_password(password, admin.get("password_hash") or ""):
        record_failed_login(request, email)
        record_audit(
            request,
            {"email": email},
            "admin.login_failed",
            target_type="admin_user",
            target_id=email,
            summary="管理员登录失败",
            success=False,
        )
        raise error(401, "管理员邮箱或密码不正确。")
    clear_failed_logins(request, email)
    db.execute("UPDATE admin_users SET last_login_at = CURRENT_TIMESTAMP WHERE id = ?", (admin["id"],))
    db.commit()
    create_admin_session(response, request, admin["id"])
    current_admin = one(
        "SELECT id, email, name, role, status, last_login_at FROM admin_users WHERE id = ?",
        (admin["id"],),
    )
    record_audit(request, current_admin, "admin.login", target_type="admin_user", target_id=admin["id"], summary="管理员登录成功")
    return {"admin": sanitize_admin(current_admin)}


@app.get("/api/admin/auth/me")
def admin_me(admin: dict = Depends(require_admin)):
    return {"admin": sanitize_admin(admin)}


@app.post("/api/admin/auth/logout")
def admin_logout(request: Request, response: Response, admin: dict = Depends(require_admin)):
    validate_admin_origin(request)
    token = request.cookies.get(ADMIN_SESSION_COOKIE)
    if token:
        db.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (hash_token(token),))
        db.commit()
    record_audit(request, admin, "admin.logout", target_type="admin_user", target_id=admin["id"], summary="管理员退出登录")
    clear_admin_session(response)
    return {"ok": True}


@app.get("/api/admin/snapshot")
def snapshot(admin: dict = Depends(require_admin)):
    try:
        reports = list_reports()
        role = admin.get("role")
        can_operate = role in {"super_admin", "operations"}
        is_super_admin = role == "super_admin"
        return {
            "metrics": build_metrics(reports),
            "candidates": list_candidates() if can_operate else [],
            "interviews": list_interviews() if can_operate else [],
            "reports": reports,
            "agents": list_agent_templates() if can_operate else [],
            "auditLogs": list_audit_logs(30) if is_super_admin else [],
            "adminUsers": list_admin_accounts() if is_super_admin else [],
            "settings": build_settings() if is_super_admin else {},
            "permissions": {
                "canViewCandidates": can_operate,
                "canViewInterviews": can_operate,
                "canViewReports": True,
                "canViewAgents": can_operate,
                "canManageSettings": is_super_admin,
                "canViewAudit": is_super_admin,
                "canViewCatalog": has_permission(db, str(role or ""), "read"),
                "canWriteCatalog": has_permission(db, str(role or ""), "write"),
                "canImportCatalog": has_permission(db, str(role or ""), "import"),
                "canPublishCatalog": has_permission(db, str(role or ""), "publish"),
            },
            "admin": sanitize_admin(admin),
        }
    except Exception as exc:
        raise error(500, f"管理端数据读取失败：{exc}") from exc


@app.get("/api/admin/candidates/{candidate_id}")
def candidate_detail(request: Request, candidate_id: str, admin: dict = Depends(require_roles("super_admin", "operations"))):
    result = {"candidate": get_candidate_detail(candidate_id)}
    record_audit(request, admin, "candidate.view", target_type="candidate", target_id=candidate_id, summary="查看候选人详情")
    return result


@app.get("/api/admin/interviews/{interview_id}")
def interview_detail(request: Request, interview_id: str, admin: dict = Depends(require_roles("super_admin", "operations"))):
    result = get_interview_detail(interview_id)
    record_audit(request, admin, "interview.view", target_type="interview", target_id=interview_id, summary="查看面试详情")
    return result


@app.get("/api/admin/reports/{report_id}")
def report_detail(request: Request, report_id: str, admin: dict = Depends(require_roles("super_admin", "operations", "reviewer"))):
    result = {"report": get_report_detail(report_id)}
    record_audit(request, admin, "report.view", target_type="report", target_id=report_id, summary="查看面试报告")
    return result


@app.patch("/api/admin/reports/{report_id}/review")
async def review_report(request: Request, report_id: str, admin: dict = Depends(require_roles("super_admin", "reviewer"))):
    validate_admin_origin(request)
    body = await request.json()
    status = str(body.get("status") or "").strip()
    if status not in {"approved", "rejected", "pending"}:
        raise error(400, "复核状态必须是 approved、rejected 或 pending。")
    if not one("SELECT id FROM interview_reports WHERE id = ?", (report_id,)):
        raise error(404, "报告不存在。")
    db.execute(
        """UPDATE interview_reports
           SET review_status = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP,
               updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (status, admin["id"], report_id),
    )
    db.commit()
    record_audit(
        request,
        admin,
        "report.review",
        target_type="report",
        target_id=report_id,
        summary=f"报告复核状态更新为 {status}",
    )
    return {"report": get_report_detail(report_id)}


@app.get("/api/admin/agents/{agent_name}")
def agent_detail(agent_name: str, _admin: dict = Depends(require_roles("super_admin", "operations"))):
    return get_agent_detail(agent_name)


@app.get("/api/admin/users")
def list_admin_users(_admin: dict = Depends(require_roles("super_admin"))):
    return {"admins": list_admin_accounts()}


@app.post("/api/admin/users", status_code=201)
async def create_admin_user(request: Request, admin: dict = Depends(require_roles("super_admin"))):
    validate_admin_origin(request)
    body = await request.json()
    email = normalize_email(body.get("email"))
    password = str(body.get("password") or "")
    name = str(body.get("name") or "").strip()
    role = str(body.get("role") or "reviewer").strip()
    if not is_valid_email(email) or len(password) < 12 or not name or len(name) > 80 or role not in ADMIN_ROLES:
        raise error(400, "管理员邮箱、姓名、角色或密码不符合要求；密码至少 12 位。")
    if one("SELECT id FROM admin_users WHERE email = ?", (email,)):
        raise error(409, "该管理员邮箱已经存在。")
    admin_id = str(uuid4())
    db.execute(
        "INSERT INTO admin_users (id, email, password_hash, name, role, status) VALUES (?, ?, ?, ?, ?, 'normal')",
        (admin_id, email, hash_password(password), name, role),
    )
    db.commit()
    record_audit(request, admin, "admin_user.create", target_type="admin_user", target_id=admin_id, summary=f"创建管理员 {email}，角色 {role}")
    created = one("SELECT id, email, name, role, status, last_login_at FROM admin_users WHERE id = ?", (admin_id,))
    return {"admin": sanitize_admin(created)}


@app.patch("/api/admin/users/{admin_id}")
async def update_admin_user(request: Request, admin_id: str, admin: dict = Depends(require_roles("super_admin"))):
    validate_admin_origin(request)
    target = one("SELECT id, email, name, role, status FROM admin_users WHERE id = ?", (admin_id,))
    if not target:
        raise error(404, "管理员不存在。")
    body = await request.json()
    role = str(body.get("role") or target["role"]).strip()
    status = str(body.get("status") or target["status"]).strip()
    name = str(body.get("name") or target["name"]).strip()
    if role not in ADMIN_ROLES or status not in {"normal", "disabled"} or not name or len(name) > 80:
        raise error(400, "管理员姓名、角色或状态不合法。")
    if admin_id == admin["id"] and status != "normal":
        raise error(400, "不能禁用当前登录的管理员账号。")
    db.execute("UPDATE admin_users SET name = ?, role = ?, status = ? WHERE id = ?", (name, role, status, admin_id))
    if status == "disabled":
        db.execute("DELETE FROM admin_sessions WHERE admin_user_id = ?", (admin_id,))
    db.commit()
    record_audit(request, admin, "admin_user.update", target_type="admin_user", target_id=admin_id, summary=f"更新管理员 {target['email']}：role={role}, status={status}")
    updated = one("SELECT id, email, name, role, status, last_login_at FROM admin_users WHERE id = ?", (admin_id,))
    return {"admin": sanitize_admin(updated)}


@app.patch("/api/admin/settings")
async def update_settings(request: Request, admin: dict = Depends(require_roles("super_admin"))):
    validate_admin_origin(request)
    body = await request.json()
    allowed_fields = {
        "OPENAI_REALTIME_API_KEY": "openaiApiKey",
        "OPENAI_REALTIME_MODEL": "openaiRealtimeModel",
        "OPENAI_REALTIME_VOICE": "openaiVoice",
        "OPENAI_API_KEY": "reportOpenaiApiKey",
        "OPENAI_FOLLOWUP_MODEL": "reportOpenaiModel",
        "QWEN_API_KEY": "reportQwenApiKey",
        "QWEN_MODEL": "reportQwenModel",
        "REPORT_PROVIDER_ORDER": "reportProviderOrder",
        "AI_REPORT_TIMEOUT": "reportTimeout",
        "AI_REPORT_HTTP_RETRIES": "reportRetries",
        "DASHSCOPE_API_KEY": "dashscopeApiKey",
        "DASHSCOPE_TTS_MODEL": "qwenTtsModel",
        "DASHSCOPE_TTS_VOICE": "qwenTtsVoice",
        "DASHSCOPE_TTS_REGION": "qwenTtsRegion",
        "DASHSCOPE_WORKSPACE_ID": "qwenTtsWorkspaceId",
        "QWEN_OMNI_REALTIME_MODEL": "qwenOmniModel",
        "QWEN_OMNI_REALTIME_VOICE": "qwenOmniVoice",
        "QWEN_OMNI_REALTIME_REGION": "qwenOmniRegion",
        "QWEN_OMNI_REALTIME_WORKSPACE_ID": "qwenOmniWorkspaceId",
        "QWEN_OMNI_REALTIME_WEBRTC_ENDPOINT": "qwenOmniEndpoint",
    }
    updates: dict[str, str] = {}
    for env_key, body_key in allowed_fields.items():
        value = str(body.get(body_key) or "").strip()
        if value:
            if any(character in value for character in ("\r", "\n", "\0")):
                raise error(400, f"配置项 {body_key} 包含非法字符。")
            updates[env_key] = value
    for key in ("OPENAI_API_KEY", "QWEN_API_KEY"):
        if key in updates and (len(updates[key]) > 4096 or is_placeholder_secret(updates[key])):
            raise error(400, "报告 API Key 格式无效，请填写真实密钥。")
    for key in ("OPENAI_FOLLOWUP_MODEL", "QWEN_MODEL"):
        if key in updates and (len(updates[key]) > 120 or not all(character.isalnum() or character in "-._:/" for character in updates[key])):
            raise error(400, "报告模型名称格式无效。")
    if "REPORT_PROVIDER_ORDER" in updates:
        providers = [item.strip().lower() for item in updates["REPORT_PROVIDER_ORDER"].split(",") if item.strip()]
        allowed_providers = {"openai", "qwen", "kimi", "deepseek", "custom"}
        if not providers or len(providers) != len(set(providers)) or any(item not in allowed_providers for item in providers):
            raise error(400, "报告供应商顺序无效。")
        updates["REPORT_PROVIDER_ORDER"] = ",".join(providers)
    for key, minimum, maximum in (("AI_REPORT_TIMEOUT", 10, 180), ("AI_REPORT_HTTP_RETRIES", 0, 4)):
        if key not in updates:
            continue
        try:
            number = int(updates[key])
        except ValueError as exc:
            raise error(400, "报告超时和重试次数必须是整数。") from exc
        if number < minimum or number > maximum:
            raise error(400, f"配置项 {key} 必须在 {minimum}-{maximum} 之间。")
        updates[key] = str(number)
    if not updates:
        raise error(400, "请至少填写一个要保存的配置。")
    write_env_values(USER_BACKEND_ENV_PATH, updates)
    for key, value in updates.items():
        os.environ[key] = value
    record_audit(
        request,
        admin,
        "settings.update",
        target_type="system_settings",
        target_id="ai-providers",
        summary="更新配置项：" + ", ".join(sorted(updates)),
    )
    return {"settings": build_settings(), "message": "配置已保存。复盘报告文本模型会在下一次请求时热加载；实时语音配置需重启用户端后端。"}


@app.post("/api/admin/settings/report-providers/test")
def test_report_providers(request: Request, admin: dict = Depends(require_roles("super_admin"))):
    validate_admin_origin(request)
    from backend.src.provider_diagnostics import diagnose_report_providers

    results = diagnose_report_providers(make_request=True)
    record_audit(
        request,
        admin,
        "settings.report_providers.test",
        target_type="system_settings",
        target_id="report-providers",
        summary="测试复盘报告供应商：" + ", ".join(f"{item['provider']}={item['status']}" for item in results),
    )
    return {
        "providers": results,
        "ok": any(item.get("status") == "ok" for item in results),
    }
