"""学校只读记录由面试及评估服务分别从各自专库返回。

先分批获取身份服务授权的学生；某批学生没有记录时，空页仍可能附带下一页游标。
"""
import base64
import hmac
import json
import os
from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from starlette.concurrency import run_in_threadpool

from services.interview.storage import DB_ENGINE, all_rows, one
from shared.service_http import request_json
from shared.service_security import require_service

ACTIONS = {"interview": "interview.records.read", "assessment": "report.read"}
STATES = {"interview": {"draft", "running", "completed"}, "assessment": {"pending", "approved", "rejected"}}
SHANGHAI = ZoneInfo("Asia/Shanghai")
SCORE_BAND = """CASE WHEN eligible=0 THEN 'excluded' WHEN total_score>=90 THEN 'gte90'
                     WHEN total_score>=80 THEN 'from80' WHEN total_score>=70 THEN 'from70'
                     ELSE 'below70' END"""
ID_PATTERN = r"^[^\s\x00-\x1f\x7f/%\\?#]+$"
FilterId = Annotated[str, Query(min_length=1, max_length=128, pattern=ID_PATTERN)]
RecordId = Annotated[str, Path(min_length=1, max_length=36, pattern=ID_PATTERN)]
Cursor = Annotated[str, Query(min_length=1, max_length=1024, pattern=r"^[A-Za-z0-9_-]+$")]


def _exact(column):
    return f"BINARY {column}" if DB_ENGINE == "mysql" else f"{column} COLLATE BINARY"


def _boundary(actor, request, allowed):
    if not os.environ.get("LEGACY_SCHOOL_ID"):
        raise HTTPException(503, "尚未绑定学校。")
    if actor["school_id"] != os.environ["LEGACY_SCHOOL_ID"] or actor["actor_type"] not in {"teacher", "admin"}:
        raise HTTPException(403, "无权读取此学校记录。")
    keys = request.query_params.keys()
    if set(keys) - allowed or any(len(request.query_params.getlist(key)) != 1 for key in keys):
        raise HTTPException(422, "查询参数无效。")


def _binding(owner, actor, *filters):
    data = [owner, actor["school_id"], actor["actor_id"], actor["actor_type"], *filters]
    secret = os.environ.get("SERVICE_SIGNING_KEY")
    if not secret:
        raise HTTPException(503, "服务分页密钥未配置。")
    key = hmac.digest(secret.encode(), b"school-records/cursor/v1", "sha256")
    return hmac.digest(key, json.dumps(data, ensure_ascii=False).encode(), "sha256")


def _encode(binding, student, record):
    data = json.dumps([student, record], ensure_ascii=False, separators=(",", ":")).encode()
    signed = hmac.digest(binding, data, "sha256") + data
    return base64.urlsafe_b64encode(signed).rstrip(b"=").decode()


def _decode(value, binding):
    if value is None:
        return None, None
    try:
        signed = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        tag, data = signed[:32], signed[32:]
        if not hmac.compare_digest(tag, hmac.digest(binding, data, "sha256")):
            raise ValueError
        student, record = json.loads(data)
        if (not isinstance(student, str) or not 1 <= len(student) <= 128
                or (record is not None and (not isinstance(record, str) or not 1 <= len(record) <= 36))
                or _encode(binding, student, record) != value):
            raise ValueError
    except (ValueError, TypeError, RecursionError):
        raise HTTPException(422, "分页位置与当前查询不符。") from None
    return student, record


async def _students(owner, actor, **filters):
    page = await request_json("identity", "POST", "/internal/staff/record-students", actor=actor,
                              scope="identity.records.scope", body=filters)
    expected = {k: actor[k] for k in ("actor_id", "school_id", "actor_type")}
    expected["action"] = ACTIONS[owner]
    rows = page.get("items") if isinstance(page, dict) else None
    if (not isinstance(rows, list) or len(rows) > 100
            or any(page.get(k) != v for k, v in expected.items())
            or type(page.get("has_more")) is not bool or (page["has_more"] and not rows)):
        raise HTTPException(502, "身份服务返回了无效的记录范围。")
    students = {}
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("student_id"), str)
                or not row["student_id"] or row["student_id"] in students
                or not isinstance(row.get("name"), str)
                or (filters.get("student_id") and row["student_id"] != filters["student_id"])
                or (filters.get("college_id") and row.get("college_id") != filters["college_id"])
                or (filters.get("class_id") and row.get("class_id") != filters["class_id"])):
            raise HTTPException(502, "身份服务返回了无效的学生范围。")
        students[row["student_id"]] = {k: row.get(k) for k in (
            "name", "student_no", "class_id", "class_name", "college_id", "college_name")}
    return students, page["has_more"]


def _query(owner, school, *, detail=False, workbench=False):
    # 学校、学生和面试编号按精确身份匹配，避免旧库的大小写不敏感排序扩大范围。
    training_join = " LEFT JOIN interview_training_attempts t ON t.interview_id=" + _exact("i.id")
    kind = "CASE WHEN t.interview_id IS NULL THEN 'practice' ELSE 'training' END AS kind"
    cols = "i.user_id AS student_id,i.target_role,i.interview_type,i.status," + kind
    if owner == "interview":
        rid = "i.id"
        cols += ",i.id,i.created_at"
        if workbench:
            cols += ",i.updated_at"
        source = "interview_sessions i"
    else:
        rid = "r.id"
        # 旧报告没有覆盖计数，必须能在评估专库的面试投影中找到实际作答，才显示历史分值。
        legacy_answer = ("EXISTS (SELECT 1 FROM interview_messages m WHERE m.interview_id="
                         + _exact("r.interview_id") + " AND m.sender_type='candidate' AND m.message_type IN "
                         "('answer','transcript') AND TRIM(COALESCE(NULLIF(m.transcript_text,''),m.content))<>'')")
        visible = ("r.generation_status IN ('succeeded','degraded') AND r.total_score BETWEEN 0 AND 100 "
                   f"AND (r.scored_answer_count>0 OR (r.scored_answer_count IS NULL AND {legacy_answer}))")
        cols += (",r.id,r.interview_id,r.created_at,r.generation_status,r.review_status,"
                 f"r.scored_answer_count,r.answer_count,CASE WHEN {visible} THEN r.total_score END AS total_score")
        if workbench:
            # 分布和均分只接纳完整覆盖的新报告，或生成成功且未降级的有据旧报告。
            complete = ("(r.scored_answer_count=r.answer_count OR (r.scored_answer_count IS NULL "
                        "AND r.generation_status='succeeded' AND r.fallback=0))")
            cols += f",r.updated_at,CASE WHEN {visible} AND {complete} THEN 1 ELSE 0 END AS eligible"
        if detail:
            cols += ",r.summary,r.suggestions"
        source = ("interview_reports r JOIN interview_sessions i ON i.id="
                  + _exact("r.interview_id") + " AND " + _exact("r.user_id") + "=" + _exact("i.user_id"))
    query = ("SELECT " + cols + " FROM " + source + training_join + " WHERE (t.interview_id IS NULL OR ("
             + _exact("t.school_id") + "=? AND " + _exact("t.student_id") + "=" + _exact("i.user_id") + "))")
    subject = "i.user_id" if owner == "interview" else "r.user_id"
    return query, [school], _exact(subject), _exact(rid)


def _bounds(start_date, end_date):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(422, "开始日期不能晚于结束日期。")
    try:
        end = end_date + timedelta(days=1) if end_date else None
        return [int(datetime.combine(d, time.min, tzinfo=SHANGHAI).timestamp()) if d else None
                for d in (start_date, end)]
    except (ValueError, OverflowError):
        raise HTTPException(422, "日期超出支持的范围。") from None


def _check_bounds(bounds):
    # 避免 MySQL 对越界时间返回 NULL 后，将其误认为没有记录。
    if DB_ENGINE == "mysql":
        for bound in bounds:
            if bound is not None and one("SELECT FROM_UNIXTIME(?) AS cutoff", (bound,))["cutoff"] is None:
                raise HTTPException(422, "日期超出数据库支持的范围。")


def _scoped_records(owner, school, students, kind, bounds, *, workbench):
    query, params, subject, _ = _query(owner, school, workbench=workbench)
    timestamp = "i.updated_at" if owner == "interview" else "r.created_at"
    marks = ",".join("?" for _ in students)
    raw = "i.user_id" if owner == "interview" else "r.user_id"
    query += f" AND {raw} IN ({marks}) AND {subject} IN ({marks})"
    params += list(students) * 2
    if kind:
        query += " AND t.interview_id IS " + ("NOT NULL" if kind == "training" else "NULL")
    # SQLite 的 CURRENT_TIMESTAMP 为 UTC；MySQL 用当前会话时区解释数据库时间。
    # FROM_UNIXTIME 对常量转换，保留列上的时间索引。
    to_date = "FROM_UNIXTIME(?)" if DB_ENGINE == "mysql" else "datetime(?,'unixepoch')"
    for op, bound in zip((">=", "<"), bounds):
        if bound is not None:
            query += f" AND {timestamp} {op} {to_date}"
            params.append(bound)
    return " FROM (" + query + ") scoped", tuple(params)


def _records(owner, school, students, kind, after_student, after_record, limit, bounds=(None, None), state=None, score_band=None):
    _check_bounds(bounds)
    base, params = _scoped_records(owner, school, students, kind, bounds, workbench=bool(score_band))
    predicates = []
    if state:
        column = "review_status" if owner == "assessment" else "status"
        predicates.append(column + "=?")
        params += (state,)
    if score_band:
        predicates.append(SCORE_BAND + "=?")
        params += (score_band,)
    # 游标只表示位置。当前学籍、组织归属和筛选条件在读取每页时重新生效。
    subject, rid = _exact("student_id"), _exact("id")
    if after_record:
        predicates.append(f"({subject}>? OR ({subject}=? AND {rid}>?))")
        params += (after_student, after_student, after_record)
    where = (" WHERE " + " AND ".join(predicates)) if predicates else ""
    rows = all_rows("SELECT *" + base + where + f" ORDER BY {subject},{rid} LIMIT ?", (*params, limit + 1))
    if score_band:
        for row in rows:
            row.pop("eligible")
            row.pop("updated_at")
    return rows


def _detail(owner, school, record_id, student):
    query, params, subject, rid = _query(owner, school, detail=True)
    return one(query + f" AND {rid}=? AND {subject}=?", (*params, record_id, student))


def _turns(record_id, after, limit):
    # 历史转写可能共用排序号，再按记录标识排序才能稳定翻页。
    query = """SELECT id,order_index,message_type,
        CASE WHEN message_type='transcript' THEN COALESCE(NULLIF(transcript_text,''),content) ELSE content END AS content
        FROM interview_messages WHERE
        message_type IN ('question','follow_up','answer','transcript') AND """ + _exact("interview_id") + "=?"
    params = [record_id]
    order, mid = after
    if order is not None:
        if not order.isascii() or not order.removeprefix("-").isdigit() or len(order) > 11 or mid is None:
            raise HTTPException(422, "问答分页位置无效。")
        query += " AND (order_index>? OR (order_index=? AND " + _exact("id") + ">?))"
        params.extend((int(order), int(order), mid))
    return all_rows(query + " ORDER BY order_index," + _exact("id") + " LIMIT ?", (*params, limit + 1))


def school_record_router(owner):
    from services.record_workbench import record_workbench_router

    router = APIRouter()
    router.include_router(record_workbench_router(owner))
    authorize = require_service(owner, owner + ".records.read")

    @router.get("/v1/records")
    async def records(request: Request, limit: Annotated[int, Query(ge=1, le=50)] = 25,
                      cursor: Cursor | None = None, student_id: FilterId | None = None,
                      class_id: FilterId | None = None, college_id: FilterId | None = None,
                      class_name: Annotated[str, Query(min_length=1, max_length=160)] | None = None,
                      q: Annotated[str, Query(min_length=1, max_length=128)] | None = None,
                      kind: Literal["practice", "training"] | None = None,
                      start_date: date | None = None, end_date: date | None = None,
                      state: Literal["draft", "running", "completed", "pending", "approved", "rejected"] | None = None,
                      score_band: Literal["gte90", "from80", "from70", "below70"] | None = None,
                      actor=Depends(authorize)):
        _boundary(actor, request, {"limit", "cursor", "student_id", "class_id", "college_id", "class_name",
                                   "q", "kind", "start_date", "end_date", "state", "score_band"})
        if (state and state not in STATES[owner]) or (score_band and owner != "assessment"):
            raise HTTPException(422, "当前记录类型不支持该筛选。")
        bounds = _bounds(start_date, end_date)
        # 无新增筛选时继续接受升级前签发的游标；任何新增筛选都进入签名。
        extra = (college_id, *bounds, state, score_band)
        binding = _binding(owner, actor, student_id, class_id, class_name, q, kind,
                           *(extra if any(v is not None for v in extra) else ()))
        start, last = _decode(cursor, binding)
        students, more = await _students(owner, actor, student_id=student_id, class_id=class_id,
                                         college_id=college_id, class_name=class_name, q=q,
                                         after_student=start, include_start=last is not None)
        rows = []
        if students:
            rows = await run_in_threadpool(_records, owner, actor["school_id"], students, kind, start, last, limit,
                                          bounds, state, score_band)
        items = [{**row, **students[row["student_id"]]} for row in rows[:limit]]
        next_cursor = None
        if len(rows) > limit:
            next_cursor = _encode(binding, items[-1]["student_id"], items[-1]["id"])
        elif more:
            next_cursor = _encode(binding, next(reversed(students)), None)
        return {"items": items, "next_cursor": next_cursor}

    @router.get("/v1/records/{record_id}")
    async def record(record_id: RecordId, request: Request, cursor: Cursor | None = None,
                     actor=Depends(authorize)):
        _boundary(actor, request, {"cursor"} if owner == "interview" else set())
        table = "interview_sessions" if owner == "interview" else "interview_reports"
        identity = await run_in_threadpool(one, f"SELECT id,user_id FROM {table} WHERE id=?", (record_id,))
        # 记录缺失时仍校验当前人员的读取权限，但无需返回名册或转写内容。
        if not identity or identity["id"] != record_id:
            await _students(owner, actor, check_only=True)
            raise HTTPException(404, "记录不存在或不在可见范围。")
        student = identity["user_id"]
        students, _ = await _students(owner, actor, student_id=student)
        if student not in students:
            raise HTTPException(404, "记录不存在或不在可见范围。")
        row = await run_in_threadpool(_detail, owner, actor["school_id"], record_id, student)
        if not row:
            raise HTTPException(404, "记录不存在或不在可见范围。")
        result = {**row, **students[student]}
        if owner == "interview":
            binding = _binding(owner, actor, "turns", student, record_id)
            turns = await run_in_threadpool(_turns, record_id, _decode(cursor, binding), 20)
            result["turns"] = turns[:20]
            result["next_cursor"] = (_encode(binding, str(turns[19]["order_index"]), turns[19]["id"])
                                     if len(turns) > 20 else None)
        return result

    return router
