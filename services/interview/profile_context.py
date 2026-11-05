"""建场时冻结提示词所需的资料快照；学生资料仍由资料服务维护。"""
import json
import os

import httpx
from fastapi import HTTPException

from services.interview.storage import DB_ENGINE, db, one
from services.identity.permissions import legacy_school_id
from shared.service_http import service_origin
from shared.service_security import service_headers


def initialize():
    text_type = "MEDIUMTEXT" if DB_ENGINE == "mysql" else "TEXT"
    suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci" if DB_ENGINE=="mysql" else ""
    with db:
        db.execute(f"""CREATE TABLE IF NOT EXISTS interview_profile_context (
            interview_id CHAR(36) PRIMARY KEY, profile_version BIGINT NOT NULL,
            analysis_json {text_type} NOT NULL,
            FOREIGN KEY(interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE
        ){suffix}""").close()


def capture(user_id):
    if "PROFILE_SERVICE_URL" not in os.environ:
        return None
    school = legacy_school_id()
    url = service_origin("profile") + "/internal/interview-context"
    try:
        headers = service_headers("profile", actor_id=user_id, school_id=school,
                                  actor_type="student", scopes=["profile.snapshot.read"])
        with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
            response = client.get(url, headers=headers)
        response.raise_for_status()
        item = response.json()
        if (item["school_id"] != school or item["actor_id"] != user_id
                or type(item["version"]) is not int or item["version"] < 0
                or not isinstance(item["analysis"], dict)):
            raise ValueError("Invalid profile context")
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        raise HTTPException(503, "Cannot confirm the student's interview profile") from None
    return item


def save(interview_id, snapshot):
    if snapshot is not None:
        # 在建场事务中写入快照。版本 0 明确表示建场时没有学生资料，
        # 后续重试也不能用新资料补填。
        db.execute("INSERT INTO interview_profile_context(interview_id,profile_version,analysis_json) VALUES (?,?,?)",
                   (interview_id, snapshot["version"], json.dumps(snapshot["analysis"], ensure_ascii=False))).close()


def load(interview_id):
    row = one("SELECT profile_version,analysis_json FROM interview_profile_context WHERE interview_id=?",
              (interview_id,))
    if row:
        return {"profile_version": row["profile_version"], "analysis": json.loads(row["analysis_json"])}
    # 历史面试缺少当时的资料版本，不能用今天的简历重建。
    # 生成提示词时仍沿用原来保存的 interview_sessions.resume_context。
    return {"profile_version": None, "analysis": {}} if "PROFILE_SERVICE_URL" in os.environ else None
