"""从实际面试中的 Agent 实例汇总使用次数；策略摘要和逐场使用明细分别授权。"""

import os
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from services.interview.storage import DB_ENGINE, all_rows
from shared.service_security import require_service
from shared.service_http import request_json

router = APIRouter()
ACTION = "interview.templates.read"


def _exact(column):
    return "BINARY " + column if DB_ENGINE == "mysql" else column + " COLLATE BINARY"


def read_batch(students, name, recent):
    """学校独占面试库；特定教师的 SQL 始终附带本次授权返回的学生编号。"""
    conditions = []
    args = []
    if students is not None:
        if not students:
            return [], []
        conditions.append(_exact("i.user_id") + " IN (" + ",".join("?" for _ in students) + ")")
        args.extend(students)
    if name:
        conditions.append(_exact("a.agent_name") + "=?")
        args.append(name)
    source = (
        " FROM interview_agents a JOIN interview_sessions i ON "
        + _exact("a.interview_id")
        + "="
        + _exact("i.id")
    )
    if conditions:
        source += " WHERE " + " AND ".join(conditions)
    # 统计只在已授权的学生集合内聚合。大班分批查询后再相加，不能先截断每批的榜单。
    cols = ["a.agent_name", "a.agent_type", "a.agent_role"]
    if name:
        cols.append("a.strategy")
    fields = ",".join(cols)
    # 名称等展示文本可能使用语言排序；GROUP BY 对齐 SELECT 表达式，兼容 MySQL ONLY_FULL_GROUP_BY。
    stats = all_rows("SELECT " + fields + ",COUNT(*) AS n" + source + " GROUP BY " + fields, tuple(args))
    uses = (
        all_rows(
            "SELECT i.id AS interview_id,i.user_id,i.target_role,a.status,a.updated_at,a.id AS instance_id"
            + source
            + " ORDER BY a.updated_at DESC,a.id DESC LIMIT 20",
            tuple(args),
        )
        if recent
        else []
    )
    return stats, uses


async def current_scope(actor, mode, **filters):
    scope = await request_json(
        "identity",
        "POST",
        "/internal/staff/record-students",
        actor=actor,
        scope="identity.records.scope",
        body={"purpose": mode, **filters},
    )
    if (
        not isinstance(scope, dict)
        or scope.get("action") != ACTION
        or scope.get("purpose") != mode
        or any(scope.get(k) != actor[k] for k in ("school_id", "actor_id", "actor_type"))
        or not isinstance(scope.get("items"), list)
        or type(scope.get("whole")) is not bool
        or type(scope.get("has_more")) is not bool
        or len(scope["items"]) > 100
        or (scope.get("whole") and (scope["items"] or scope["has_more"] or any(filters.values())))
        or any(
            not isinstance(row, dict)
            or not isinstance(row.get("student_id"), str)
            or not isinstance(row.get("name"), str)
            for row in scope["items"]
        )
    ):
        raise HTTPException(502, "身份范围与本次查询不符")
    return scope


@router.get("/v1/agent-templates")
async def templates(
    name: str = Query("", max_length=160),
    recent: bool = False,
    student_q: str = Query("", max_length=128),
    class_id: str = Query("", max_length=128),
    actor=Depends(require_service("interview", ACTION)),
):
    if (
        actor["caller"] != "admin-gateway"
        or actor["actor_type"] not in {"teacher", "admin"}
        or actor["school_id"] != os.environ.get("LEGACY_SCHOOL_ID")
    ):
        raise HTTPException(403, "不能查询此学校的面试官")
    if recent and not name:
        raise HTTPException(422, "请先选择面试官")
    mode = "template_usage" if recent else "templates"
    after = None
    groups, uses = Counter(), []
    while True:
        scope = await current_scope(
            actor, mode, q=student_q or None, class_id=class_id or None, after_student=after
        )
        students = {item["student_id"]: item["name"] for item in scope["items"]}
        stats, batch = await run_in_threadpool(
            read_batch, None if scope["whole"] else tuple(students), name, recent
        )
        for row in stats:
            groups[
                (
                    row["agent_name"] or "",
                    row["agent_type"] or "",
                    row["agent_role"] or "",
                    row.get("strategy") or "",
                )
            ] += row["n"]
        uses.extend({**row, "candidate": students.get(row["user_id"], row["user_id"])} for row in batch)
        uses = sorted(uses, key=lambda row: (str(row["updated_at"]), row["instance_id"]), reverse=True)[:20]
        if scope["whole"] or not scope["has_more"]:
            break
        next_id = max(students, default="")
        if not next_id or after is not None and next_id <= after:
            raise HTTPException(502, "身份目录游标无效")
        after = next_id
    if recent and scope["whole"] and uses:
        # 全校汇总无需传输整张名册，仅为实际可展示的最多 20 条使用记录解析当前姓名。
        visible = await current_scope(actor, mode, student_ids=sorted({r["user_id"] for r in uses}))
        names = {r["student_id"]: r["name"] for r in visible["items"]}
        uses = [{**r, "candidate": names[r["user_id"]]} for r in uses if r["user_id"] in names]
    items = [
        {"name": n, "type": t, "focus": r, "strategy": strategy, "usageCount": count}
        for (n, t, r, strategy), count in sorted(groups.items(), key=lambda item: (-item[1], item[0]))[:20]
    ]
    if name and not items:
        raise HTTPException(404, "当前可见范围内没有此模板")
    return {"items": items, "recentUsage": uses}
