from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .database import all_rows, get_database_path, one


app = FastAPI(title="Multi Agent Interview Admin API")
PROJECT_DIR = Path(__file__).resolve().parents[2]
USER_BACKEND_ENV_PATH = PROJECT_DIR / "backend" / ".env"

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
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
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
            "reviewStatus": report_review_status(int(row.get("total_score") or 0)),
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
    return {"ok": True, "databasePath": get_database_path()}


@app.get("/api/admin/snapshot")
def snapshot():
    try:
        candidates = list_candidates()
        interviews = list_interviews()
        reports = list_reports()
        agents = list_agent_templates()
        return {
            "metrics": build_metrics(reports),
            "candidates": candidates,
            "interviews": interviews,
            "reports": reports,
            "agents": agents,
            "auditLogs": [],
            "settings": build_settings(),
        }
    except Exception as exc:
        raise error(500, f"管理端数据读取失败：{exc}") from exc


@app.get("/api/admin/candidates/{candidate_id}")
def candidate_detail(candidate_id: str):
    return {"candidate": get_candidate_detail(candidate_id)}


@app.get("/api/admin/interviews/{interview_id}")
def interview_detail(interview_id: str):
    return get_interview_detail(interview_id)


@app.get("/api/admin/reports/{report_id}")
def report_detail(report_id: str):
    return {"report": get_report_detail(report_id)}


@app.get("/api/admin/agents/{agent_name}")
def agent_detail(agent_name: str):
    return get_agent_detail(agent_name)


@app.patch("/api/admin/settings")
async def update_settings(request: Request):
    body = await request.json()
    allowed_fields = {
        "OPENAI_REALTIME_API_KEY": "openaiApiKey",
        "OPENAI_REALTIME_MODEL": "openaiRealtimeModel",
        "OPENAI_REALTIME_VOICE": "openaiVoice",
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
            updates[env_key] = value
    if not updates:
        raise error(400, "请至少填写一个要保存的配置。")
    write_env_values(USER_BACKEND_ENV_PATH, updates)
    for key, value in updates.items():
        os.environ[key] = value
    return {"settings": build_settings(), "message": "配置已保存到用户端后端 .env，重启用户端后端后完全生效。"}
