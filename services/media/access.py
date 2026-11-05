"""保存面试服务提供的当前轮次，学生媒体操作按学校和已绑定的所有者授权。"""
import hashlib
import json
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from shared.service_db import ServiceDatabase
from shared.service_security import require_service

router = APIRouter()
MAX_CONTEXT_AGE = 60


def store():
    return ServiceDatabase.from_env("media")


def initialize():
    db = store()
    engine = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin" if db.engine == "mysql" else ""
    db.ensure_schema(["""CREATE TABLE IF NOT EXISTS media_interview_context (
        resource_key CHAR(64) PRIMARY KEY, actor_id VARCHAR(128) NOT NULL,
        status VARCHAR(16) NOT NULL, question_order BIGINT NOT NULL,
        refreshed_at BIGINT NOT NULL, snapshot MEDIUMTEXT NOT NULL
    )""" + engine])
    db.require_exact_keys("media-context")


class Context(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["draft", "running", "completed"]
    role_id: str = Field(max_length=128)
    question_id: str = Field(max_length=128)
    question_order: int = Field(ge=0)
    prompt: str = Field(max_length=5000)
    greeting: str = Field(max_length=20000)
    user_name: str = Field(max_length=128)
    # 角色和提示词由面试服务提供；浏览器仅能提交 SDP 等操作参数。
    active_agent: str = Field(default="", max_length=256)


def resource_key(interview_id, actor):
    if actor["actor_type"] != "student":
        raise HTTPException(403, "Student session required")
    return hashlib.sha256(json.dumps([actor["school_id"], interview_id]).encode()).hexdigest()


@router.put("/interviews/{interview_id}/context")
def sync(interview_id: str, body: Context, actor=Depends(require_service("media", "media.context.sync"))):
    key = resource_key(interview_id, actor)
    db = store()
    payload = body.model_dump()
    if body.status == "completed":
        # 面试结束后，回放只需要归属信息，清除语音提示中的私人内容。
        payload.update(prompt="", greeting="", active_agent="", user_name="")
    snapshot = json.dumps(payload, ensure_ascii=False)
    values = (key, actor["actor_id"], body.status, body.question_order, int(time.time()), snapshot)
    with db.transaction(write=True) as tx:
        # 首次建立绑定时由数据库锁串行处理，同一面试不能被并发同步给两位学生。
        conflict = ("ON DUPLICATE KEY UPDATE resource_key=resource_key" if db.engine == "mysql"
                    else "ON CONFLICT(resource_key) DO NOTHING")
        tx.execute("INSERT INTO media_interview_context VALUES (?,?,?,?,?,?) " + conflict, values)
        row = tx.one("SELECT * FROM media_interview_context WHERE resource_key=?", (key,))
        if row["actor_id"] != actor["actor_id"]:
            raise HTTPException(404, "Interview not found")
        if ((row["status"] == "completed" and body.status != "completed")
                or (row["status"] == "running" and body.status == "draft")):
            raise HTTPException(409, "Superseded interview state")
        previous_id = json.loads(row["snapshot"])["question_id"]
        replaced_same_order = (row["question_order"] == body.question_order and previous_id
                               and previous_id != body.question_id)
        if body.status != "completed" and (replaced_same_order or row["question_order"] > body.question_order):
            raise HTTPException(409, "Superseded interview round")
        tx.execute("""UPDATE media_interview_context SET status=?,question_order=?,refreshed_at=?,snapshot=?
                      WHERE resource_key=?""", (*values[2:], key))
    return {"status": body.status, "question_id": body.question_id}


def owned_session(interview_id, actor, *, active=True):
    key = resource_key(interview_id, actor)
    with store().transaction() as tx:
        row = tx.one("SELECT * FROM media_interview_context WHERE resource_key=?", (key,))
    if row is None or row["actor_id"] != actor["actor_id"]:
        raise HTTPException(404, "Interview not found")
    if active and (row["status"] == "completed" or int(time.time()) - row["refreshed_at"] >= MAX_CONTEXT_AGE):
        raise HTTPException(409, "Interview has ended or requires a fresh round snapshot")
    return {**json.loads(row["snapshot"]), "school_id": actor["school_id"],
            "actor_id": actor["actor_id"], "interview_id": interview_id}
