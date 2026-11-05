"""学校工作台的只读汇总，分别挂载在面试与评估服务，沿用记录页的当前人员范围。"""
from collections import Counter
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from services.interview.storage import DB_ENGINE, all_rows, db, one
from services.school_records import FilterId, SCORE_BAND, _boundary, _bounds, _check_bounds, _exact, _scoped_records, _students
from shared.service_security import require_service


MAX_DIRECTORY_PAGES = 200
GENERATIONS = "'succeeded','degraded','queued','generating','failed','pending_retry','insufficient_evidence'"


async def _directory(owner, actor, college_id, class_id):
    # 游标必须单调推进。同一个学生跨批次重复会放大计数，超限或异常时整次请求失败。
    pages = []
    after = None
    filters = {k: v for k, v in (("college_id", college_id), ("class_id", class_id)) if v is not None}
    for _ in range(MAX_DIRECTORY_PAGES):
        students, more = await _students(owner, actor, **filters, after_student=after)
        ids = list(students)
        if ids != sorted(ids) or (ids and after is not None and ids[0] <= after):
            raise HTTPException(502, "身份服务的授权名单分页次序无效。")
        if students:
            pages.append(students)
            after = ids[-1]
        if not more:
            return pages
    raise HTTPException(422, "授权名单超过单次汇总上限，请选择学院或班级后重试。")


def _merge_items(current, base, params, students, limit, timestamp, *, predicate="", newest=True):
    direction = "DESC" if newest else "ASC"
    order = f" ORDER BY {timestamp} {direction}," + _exact("id") + f" {direction} LIMIT ?"
    rows = all_rows("SELECT *" + base + predicate + order, (*params, limit))
    for row in rows:
        row.pop("eligible", None)
        current.append({**row, **students[row["student_id"]]})
    # 每批先由数据库取前 K，跨批再按相同的时间和精确 ID 合并，保留全范围的前 K 条。
    current.sort(key=lambda row: (str(row[timestamp]), row["id"]), reverse=newest)
    del current[limit:]


def _interviews(result, base, params):
    groups = all_rows("""SELECT CASE WHEN status IN ('draft','running','completed') THEN status ELSE 'unknown' END
                      AS state,kind,COUNT(*) AS n""" + base + " GROUP BY state,kind", params)
    for row in groups:
        result["by_status"][row["state"]] += row["n"]
        result["by_kind"][row["kind"]] += row["n"]
        result["total"] += row["n"]
    result["completed_students"] += one("SELECT COUNT(DISTINCT " + _exact("student_id") + ") AS n" + base +
                                        " WHERE status='completed'", params)["n"]


def _reports(result, base, params):
    groups = all_rows(f"""SELECT CASE WHEN generation_status IN ({GENERATIONS})
                        THEN generation_status ELSE 'unknown' END AS gen_state,
                        CASE WHEN review_status IN ('pending','approved','rejected') THEN review_status
                        ELSE 'unknown' END AS rev_state,
                        CASE WHEN scored_answer_count IS NULL OR answer_count IS NULL THEN 'unknown_coverage'
                             WHEN scored_answer_count=0 THEN 'zero_evidence'
                             WHEN scored_answer_count<answer_count THEN 'partial_coverage' ELSE 'full' END AS coverage,
                        {SCORE_BAND} AS band,
                        COUNT(*) AS n, SUM(CASE WHEN eligible=1 THEN total_score ELSE 0 END) AS points""" +
                      base + " GROUP BY gen_state,rev_state,coverage,band", params)
    for row in groups:
        count = row["n"]
        result["total"] += count
        result["by_generation"][row["gen_state"]] += count
        result["by_review"][row["rev_state"]] += count
        if row["coverage"] in result["quality"]:
            result["quality"][row["coverage"]] += count
        if row["band"] != "excluded":
            result["eligible"] += count
            result["score_bands"][row["band"]] += count
            result["points"] += int(row["points"])


def _summarize(owner, school, pages, kind, bounds, limit):
    if owner == "interview":
        result = {"total": 0, "completed_students": 0, "by_status": Counter(),
                  "by_kind": {"training": 0, "practice": 0}, "recent": [], "running_items": [],
                  "visible_students": sum(len(page) for page in pages)}
    else:
        result = {"total": 0, "eligible": 0, "points": 0, "by_generation": Counter(), "by_review": Counter(),
                  "quality": dict.fromkeys(("pending_review","partial_coverage","zero_evidence","unknown_coverage"), 0),
                  "score_bands": dict.fromkeys(("gte90","from80","from70","below70"), 0),
                  "recent": [], "pending_items": []}

    # 授权 HTTP 查询结束后才打开本地数据库快照。所有人员批次的合计与预览共享一次读取，
    # 避免同一个请求里先看到改分前的分布，又返回改分后的待办。
    if DB_ENGINE == "mysql":
        # SET TRANSACTION 只改变接下来的一笔事务，显式覆盖部署可能使用的 READ COMMITTED。
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY").close()
    with db:
        if DB_ENGINE == "sqlite":
            db.execute("BEGIN").close()
        _check_bounds(bounds)
        for students in pages:
            base, params = _scoped_records(owner, school, students, kind, bounds, workbench=True)
            if owner == "interview":
                _interviews(result, base, params)
                _merge_items(result["recent"], base, params, students, limit, "updated_at")
                _merge_items(result["running_items"], base, params, students, limit, "updated_at",
                             predicate=" WHERE status='running'")
            else:
                _reports(result, base, params)
                _merge_items(result["recent"], base, params, students, limit, "created_at")
                _merge_items(result["pending_items"], base, params, students, limit, "created_at",
                             predicate=" WHERE review_status='pending'", newest=False)
    if owner == "interview":
        result.update(completed=result["by_status"]["completed"], running=result["by_status"]["running"])
    else:
        points = result.pop("points")
        result["average_score"] = round(points / result["eligible"], 2) if result["eligible"] else None
        result["quality"]["pending_review"] = result["by_review"]["pending"]
    return result


def record_workbench_router(owner):
    if owner not in {"assessment", "interview"}:
        raise ValueError("工作台仅支持面试与评估服务")
    router = APIRouter()
    authorize = require_service(owner, owner + ".records.read")

    @router.get("/v1/workbench")
    async def workbench(request: Request, college_id: FilterId | None = None, class_id: FilterId | None = None,
                        start_date: date | None = None, end_date: date | None = None,
                        kind: Literal["training", "practice"] | None = None,
                        limit: Annotated[int, Query(ge=1, le=20)] = 5, actor=Depends(authorize)):
        _boundary(actor, request, {"class_id", "college_id", "start_date", "end_date", "kind", "limit"})
        bounds = _bounds(start_date, end_date)
        pages = await _directory(owner, actor, college_id, class_id)
        return await run_in_threadpool(_summarize, owner, actor["school_id"], pages, kind, bounds, limit)

    return router
