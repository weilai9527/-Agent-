"""教学任务及其权威面试尝试绑定。"""

import hashlib
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException

from shared.runtime_mode import require_native_runtime
from shared.service_db import ServiceDatabase
from shared.service_security import require_service
from . import identity
from .models import Assignment, Completion, Repractice, Start
from .schema import initialize
from .workbench import read_staff_tasks, visible_targets


@asynccontextmanager
async def lifespan(app):
    require_native_runtime()
    app.state.db = ServiceDatabase.from_env("training")
    initialize(app.state.db)
    yield


app = FastAPI(title="Training", lifespan=lifespan)
read = require_service("training", "training.read")
assign = require_service("training", "training.assign")
start = require_service("training", "training.start")
verify = require_service("training", "training.verify")
complete = require_service("training", "training.complete")


def roles(ctx, *allowed):
    if ctx["actor_type"] not in allowed:
        raise HTTPException(403, "Role outside action scope")


def now_us():
    return time.time_ns() // 1000


def iso(us):
    return datetime.fromtimestamp(us / 1000000, timezone.utc).isoformat() if us is not None else None


def lock():
    return " FOR UPDATE" if app.state.db.engine == "mysql" else ""


def task_view(row):
    return {
        **{k: row[k] for k in ("task_id", "teacher_id", "title", "job_role", "job_id",
                               "max_attempts", "student_count", "source_attempt_id")},
        "questions": json.loads(row["questions"]), "class_ids": json.loads(row["class_ids"]),
        "deadline": iso(row["deadline_us"])
    }


ATTEMPT = """
    SELECT a.attempt_id,a.interview_id,a.attempt_no,a.status,a.created_us,a.completed_us,
           a.task_id,a.student_id,e.class_id,t.school_id,t.teacher_id,t.job_role,t.job_id,t.questions
    FROM training_attempts a
    JOIN training_tasks t ON t.task_id=a.task_id
    JOIN training_enrollments e ON e.task_id=a.task_id AND e.student_id=a.student_id
"""


def fetch_attempt(tx, ctx, column, value):
    row = tx.one(ATTEMPT + f" WHERE t.school_id=? AND a.{column}=?", (ctx["school_id"], value))
    if row is None:
        raise HTTPException(404, "Attempt unavailable")
    row["questions"] = json.loads(row["questions"])
    row["created_at"] = iso(row.pop("created_us"))
    row["completed_at"] = iso(row.pop("completed_us"))
    return row


def authorize_attempt(ctx, attempt):
    role = ctx["actor_type"]
    if role == "system" or (role == "student" and ctx["actor_id"] == attempt["student_id"]):
        return
    if role == "admin" or (role == "teacher" and ctx["actor_id"] == attempt["teacher_id"]):
        cid = attempt["class_id"]
        if attempt["student_id"] in identity.roster(ctx, [cid])[cid]:
            return
    raise HTTPException(404, "Attempt unavailable")


def fingerprint(body):
    canonical = json.dumps(body.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def insert_task(ctx, body, *, title, job_role, job_id, targets, questions, source=None):
    students = {}
    for cid, ids in targets.items():
        for sid in ids:
            if sid in students and students[sid] != cid:
                raise HTTPException(409, "Ambiguous enrollment across target classes")
            students[sid] = cid
    task_id = str(uuid4())
    request_id = body.request_id or str(uuid4())
    digest = fingerprint(body)
    cutoff = int(body.deadline.timestamp() * 1000000)
    args = (task_id, ctx["school_id"], ctx["actor_id"], request_id, digest, title,
            job_role, job_id, cutoff, body.max_attempts, json.dumps(questions, ensure_ascii=False),
            json.dumps(list(targets)), len(students), now_us(), source)
    insert = """INSERT INTO training_tasks (task_id,school_id,teacher_id,request_id,fingerprint,
        title,job_role,job_id,deadline_us,max_attempts,questions,class_ids,student_count,created_us,source_attempt_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    # 首次发布和重试可能并发。只有取得唯一请求号的事务才能创建冻结名单，并与任务一起提交。
    db = app.state.db
    duplicate = (" ON DUPLICATE KEY UPDATE request_id=training_tasks.request_id" if db.engine == "mysql"
                 else " ON CONFLICT(school_id,teacher_id,request_id) DO NOTHING")
    with db.transaction(write=True) as tx:
        tx.execute(insert + duplicate, args)
        row = tx.one("SELECT * FROM training_tasks WHERE school_id=? AND teacher_id=? AND request_id=?" + lock(),
                     (ctx["school_id"], ctx["actor_id"], request_id))
        if row["fingerprint"] != digest:
            raise HTTPException(409, "Request ID already used with different content")
        if row["task_id"] == task_id:
            if not students:
                raise HTTPException(422, "No enrolled students in target")
            if cutoff <= now_us():
                raise HTTPException(422, "Deadline must be in the future")
            for sid, cid in students.items():
                tx.execute("INSERT INTO training_enrollments(task_id,student_id,class_id) VALUES (?,?,?)",
                           (task_id, sid, cid))
        return task_view(row)


@app.get("/health")
def health():
    return {"status": "ok" if app.state.db.ping() else "unavailable"}


@app.get("/classes")
def classes(ctx=Depends(read)):
    roles(ctx, "teacher", "admin")
    return {"items": identity.classes(ctx)}


@app.post("/tasks")
def create_task(body: Assignment, ctx=Depends(assign)):
    roles(ctx, "teacher")
    return insert_task(ctx, body, title=body.title, job_role=body.job_role, job_id=body.job_id or body.job_role,
                       targets=identity.roster(ctx, body.class_ids),
                       questions=[q.model_dump() for q in body.questions])


@app.post("/tasks/repractice")
def repractice(body: Repractice, ctx=Depends(assign)):
    roles(ctx, "teacher")
    if ctx["caller"] != "analytics":
        raise HTTPException(403, "Scored evidence required from analytics")
    with app.state.db.transaction() as tx:
        source = fetch_attempt(tx, ctx, "attempt_id", body.source_attempt_id)
    authorize_attempt(ctx, source)
    if source["status"] != "completed":
        raise HTTPException(409, "Attempt has not completed")
    for q in source["questions"]:
        if q["question_id"] == body.question_id and q["prompt"] == body.prompt:
            break
    else:
        raise HTTPException(409, "Question does not match source attempt")
    # 源尝试固定学生和原题，原答由分析服务保管；教师无法通过复练参数更换接收人。
    return insert_task(ctx, body, title="原题复练 · " + source["job_role"], job_role=source["job_role"],
                       job_id=source["job_id"], targets={source["class_id"]: [source["student_id"]]},
                       questions=[{"question_id": body.question_id, "prompt": body.prompt}], source=body.source_attempt_id)


@app.get("/tasks")
def list_tasks(ctx=Depends(read), view: Literal["workbench"] | None = None):
    role = ctx["actor_type"]
    roles(ctx, "student", "teacher", "admin")
    db = app.state.db
    if role == "student":
        if view:
            raise HTTPException(403, "Staff workbench requires current teaching scope")
        with db.transaction() as tx:
            rows = tx.all("""SELECT t.*,e.class_id,e.used_attempts,a.attempt_id,a.interview_id,a.status,a.attempt_no
                          FROM training_enrollments e JOIN training_tasks t ON t.task_id=e.task_id
                          LEFT JOIN training_attempts a ON a.task_id=e.task_id AND a.student_id=e.student_id
                            AND a.attempt_no=e.used_attempts
                          WHERE t.school_id=? AND e.student_id=? ORDER BY t.created_us DESC""",
                          (ctx["school_id"], ctx["actor_id"]))
        items = []
        for row in rows:
            task = task_view(row)
            # 跨班任务只向学生展示其本人的冻结学籍。
            del task["student_count"]
            task.update(class_ids=[row["class_id"]], used_attempts=row["used_attempts"],
                        latest_attempt={k: row[k] for k in ("attempt_id", "interview_id", "status", "attempt_no")}
                        if row["attempt_id"] else None)
            items.append(task)
        return {"items": items}
    return read_staff_tasks(db, ctx, task_view, workbench=view == "workbench")


@app.get("/tasks/{task_id}/roster")
def task_roster(task_id: str, ctx=Depends(read)):
    roles(ctx, "teacher", "admin")
    with app.state.db.transaction() as tx:
        task = tx.one("SELECT * FROM training_tasks WHERE school_id=? AND task_id=?", (ctx["school_id"], task_id))
        if not task or (ctx["actor_type"] == "teacher" and task["teacher_id"] != ctx["actor_id"]):
            raise HTTPException(404, "Task unavailable")
    # 冻结名单记录发布时的应到学生；能否查看可识别的学生记录，仍取决于当前班级和学籍。
    visible = {c["class_id"] for c in identity.classes(ctx)}
    targets = visible_targets(json.loads(task["class_ids"]), visible)
    if not targets:
        raise HTTPException(404, "Task unavailable")
    current = {cid: set(ids) for cid, ids in identity.roster(ctx, targets).items()}
    marks = ",".join("?" for _ in targets)
    with app.state.db.transaction() as tx:
        rows = tx.all(f"""SELECT e.class_id,e.student_id,e.used_attempts,
                      (SELECT COUNT(*) FROM training_attempts a WHERE a.task_id=e.task_id
                        AND a.student_id=e.student_id AND a.status='completed') AS completed_attempts,
                      (SELECT a.interview_id FROM training_attempts a WHERE a.task_id=e.task_id
                        AND a.student_id=e.student_id AND a.status='completed'
                        ORDER BY a.attempt_no DESC LIMIT 1) AS latest_completed_interview
                      FROM training_enrollments e WHERE e.task_id=? AND e.class_id IN ({marks})
                      ORDER BY e.class_id,e.student_id""", (task_id, *targets))
    return {"items": [row for row in rows if row["class_id"] in current and row["student_id"] in current[row["class_id"]]]}


@app.post("/tasks/{task_id}/attempts")
def begin_attempt(task_id: str, body: Start, ctx=Depends(start)):
    roles(ctx, "student")
    sid = ctx["actor_id"]
    with app.state.db.transaction(write=True) as tx:
        # 先锁定名额再检查请求号与次数。同一请求复用原尝试，不同请求竞争剩余次数。
        row = tx.one("""SELECT t.deadline_us,t.max_attempts,e.used_attempts FROM training_enrollments e
                     JOIN training_tasks t ON e.task_id=t.task_id
                     WHERE e.task_id=? AND e.student_id=? AND t.school_id=?""" + lock(),
                     (task_id, sid, ctx["school_id"]))
        if row is None:
            raise HTTPException(404, "Task unavailable")
        prior = tx.one("SELECT attempt_id FROM training_attempts WHERE task_id=? AND student_id=? AND request_id=?",
                       (task_id, sid, body.request_id))
        if prior:
            return fetch_attempt(tx, ctx, "attempt_id", prior["attempt_id"])
        stamp = now_us()
        if stamp >= row["deadline_us"] or row["used_attempts"] >= row["max_attempts"]:
            raise HTTPException(409, "Deadline passed or attempt limit reached")
        aid, iid = str(uuid4()), str(uuid4())
        number = row["used_attempts"] + 1
        tx.execute("UPDATE training_enrollments SET used_attempts=? WHERE task_id=? AND student_id=?",
                   (number, task_id, sid))
        tx.execute("""INSERT INTO training_attempts(attempt_id,interview_id,task_id,student_id,request_id,
                   attempt_no,status,created_us) VALUES(?,?,?,?,?,?,'started',?)""",
                   (aid, iid, task_id, sid, body.request_id, number, stamp))
        return fetch_attempt(tx, ctx, "attempt_id", aid)


@app.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: str, ctx=Depends(verify)):
    with app.state.db.transaction() as tx:
        attempt = fetch_attempt(tx, ctx, "attempt_id", attempt_id)
    authorize_attempt(ctx, attempt)
    return attempt


@app.get("/interviews/{interview_id}/attempt")
def interview_attempt(interview_id: str, ctx=Depends(verify)):
    with app.state.db.transaction() as tx:
        attempt = fetch_attempt(tx, ctx, "interview_id", interview_id)
    authorize_attempt(ctx, attempt)
    return attempt


@app.post("/attempts/{attempt_id}/complete")
def finish_attempt(attempt_id: str, body: Completion, ctx=Depends(complete)):
    roles(ctx, "system")
    if ctx["caller"] != "interview":
        raise HTTPException(403, "Completion must come from interview")
    db = app.state.db
    with db.transaction(write=True) as tx:
        row = tx.one("""SELECT a.interview_id FROM training_attempts a JOIN training_tasks t
                     ON t.task_id=a.task_id WHERE a.attempt_id=? AND t.school_id=?""" + lock(),
                     (attempt_id, ctx["school_id"]))
        if row is None or row["interview_id"] != body.interview_id:
            raise HTTPException(404, "Attempt/interview binding unavailable")
        # 事件与结束状态共同提交。即使并发重投，同一事件也只能结束它绑定的尝试。
        duplicate = (" ON DUPLICATE KEY UPDATE event_id=training_completions.event_id" if db.engine == "mysql"
                     else " ON CONFLICT(school_id,event_id) DO NOTHING")
        tx.execute("INSERT INTO training_completions(school_id,event_id,attempt_id) VALUES(?,?,?)" + duplicate,
                   (ctx["school_id"], body.event_id, attempt_id))
        event = tx.one("SELECT attempt_id FROM training_completions WHERE school_id=? AND event_id=?" + lock(),
                       (ctx["school_id"], body.event_id))
        if event["attempt_id"] != attempt_id:
            raise HTTPException(409, "Event already bound to another attempt")
        tx.execute("UPDATE training_attempts SET status='completed',completed_us=? WHERE attempt_id=? AND status='started'",
                   (now_us(), attempt_id))
        return fetch_attempt(tx, ctx, "attempt_id", attempt_id)
