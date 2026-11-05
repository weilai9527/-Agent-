"""学校组织、班级范围和事务审计。学生、班级编号仅在校内唯一，查询、关联和迁移须同时限定学校。"""
import json
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from shared.service_security import require_service

from .staff import require_staff


from . import organization_details

SCHEMA = (
    *organization_details.SCHEMA,
    """CREATE TABLE IF NOT EXISTS org_colleges (
        school_id VARCHAR(128) NOT NULL, id VARCHAR(128) NOT NULL, name VARCHAR(160) NOT NULL,
        status VARCHAR(32) NOT NULL, PRIMARY KEY (school_id,id))""",
    """CREATE TABLE IF NOT EXISTS org_programs (
        school_id VARCHAR(128) NOT NULL, id VARCHAR(128) NOT NULL, college_id VARCHAR(128) NOT NULL,
        name VARCHAR(160) NOT NULL, status VARCHAR(32) NOT NULL, PRIMARY KEY (school_id,id),
        FOREIGN KEY (school_id,college_id) REFERENCES org_colleges(school_id,id))""",
    """CREATE TABLE IF NOT EXISTS org_classes (
        school_id VARCHAR(128) NOT NULL, id VARCHAR(128) NOT NULL, program_id VARCHAR(128) NOT NULL,
        name VARCHAR(160) NOT NULL, status VARCHAR(32) NOT NULL, PRIMARY KEY (school_id,id),
        FOREIGN KEY (school_id,program_id) REFERENCES org_programs(school_id,id))""",
    """CREATE TABLE IF NOT EXISTS org_staff_classes (
        school_id VARCHAR(128) NOT NULL, staff_id VARCHAR(128) NOT NULL, class_id VARCHAR(128) NOT NULL,
        PRIMARY KEY (school_id,staff_id,class_id),
        FOREIGN KEY (school_id,staff_id) REFERENCES identity_staff(school_id,actor_id) ON DELETE CASCADE,
        FOREIGN KEY (school_id,class_id) REFERENCES org_classes(school_id,id))""",
    """CREATE TABLE IF NOT EXISTS org_enrollments (
        school_id VARCHAR(128) NOT NULL, student_id VARCHAR(128) NOT NULL, class_id VARCHAR(128) NOT NULL,
        status VARCHAR(32) NOT NULL, PRIMARY KEY (school_id,student_id),
        FOREIGN KEY (school_id,student_id) REFERENCES identity_student_credentials(school_id,actor_id) ON DELETE CASCADE,
        FOREIGN KEY (school_id,class_id) REFERENCES org_classes(school_id,id))""",
    """CREATE TABLE IF NOT EXISTS identity_audit (
        school_id VARCHAR(128) NOT NULL, id VARCHAR(128) NOT NULL, actor_id VARCHAR(128),
        action VARCHAR(128) NOT NULL, target_id VARCHAR(255), success INTEGER NOT NULL,
        summary TEXT, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (school_id,id))""",
    """CREATE TABLE IF NOT EXISTS org_legacy_migration (
        school_id VARCHAR(128) PRIMARY KEY, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS identity_legacy_organization (
        school_id VARCHAR(128) NOT NULL, source_table VARCHAR(40) NOT NULL,
        record_id VARCHAR(128) NOT NULL, legacy_record TEXT NOT NULL,
        PRIMARY KEY (school_id,source_table,record_id))""",
    """CREATE TABLE IF NOT EXISTS org_write_lock (school_id VARCHAR(128) PRIMARY KEY)""",
)

REGISTRATION_ARCHIVE_FIELDS = {
    "id", "student_no", "user_id", "name", "college", "gender", "class_name", "counselor", "imported_by",
    "deleted_at", "created_at", "updated_at", "school_id", "class_id", "source_status", "student_status",
}
router = APIRouter()
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[^\s\x00-\x1f\x7f]+$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
CLASS_QUERY = """
    SELECT c.id AS class_id, c.name, p.id AS program_id, p.name AS program_name,
           d.id AS college_id, d.name AS college_name
    FROM org_classes c
    JOIN org_programs p ON p.school_id=c.school_id AND p.id=c.program_id
    JOIN org_colleges d ON d.school_id=p.school_id AND d.id=p.college_id
    WHERE c.school_id=? AND c.status='active' AND p.status='active' AND d.status='active'
"""


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class College(Input):
    id: Identifier
    name: Name
    status: Literal["active", "inactive"] = "active"
    details: dict[str, str | int | None] | None = Field(None, max_length=3)


class Program(College):
    college_id: Identifier


class SchoolClass(College):
    program_id: Identifier
    # 省略字段保留任课关系；显式传空列表撤销该班全部任课分配。
    staff_ids: list[Identifier] | None = Field(default=None, max_length=200)


class OrganizationImport(Input):
    colleges: list[College] = Field(default_factory=list, max_length=500)
    programs: list[Program] = Field(default_factory=list, max_length=1000)
    classes: list[SchoolClass] = Field(default_factory=list, max_length=2000)


class ClassLookup(Input):
    class_ids: list[Identifier] = Field(min_length=1, max_length=500)


class RosterImport(Input):
    student_ids: list[Identifier] = Field(min_length=1, max_length=2000)
    status: Literal["active", "inactive"] = "active"


class StudentAction(Input):
    student_id: Identifier
    action: Literal["report.read", "report.review", "report.export", "score.adjust",
                    "credential.read", "credential.approve", "credential.revoke",
                    "credential.issue", "credential.reissue", "profile.student.read"]


def audit(tx, ctx, action, target_id, *, summary=None):
    tx.execute("INSERT INTO identity_audit (school_id,id,actor_id,action,target_id,success,summary) VALUES (?,?,?,?,?,1,?)",
               (ctx["school_id"], str(uuid4()), ctx["actor_id"], action, target_id, summary))


def lock_school(tx, store, school):
    # 在 MySQL 第一次一致性读取前先锁定学校，跨班转移总是基于最新的原班级。
    if store.engine == "mysql":
        tx.execute("INSERT INTO org_write_lock (school_id) VALUES (?) ON DUPLICATE KEY UPDATE school_id=school_id", (school,))


def _staff(tx, ctx):
    if ctx["actor_type"] not in {"admin", "teacher"}:
        return None
    return tx.one("""SELECT actor_type,school_wide FROM identity_staff
        WHERE school_id=? AND actor_id=? AND actor_type=? AND status='normal'""",
                  (ctx["school_id"], ctx["actor_id"], ctx["actor_type"]))


def _school_wide(staff):
    return staff is not None and staff["actor_type"] == "admin" and staff["school_wide"] == 1


def _visible_classes(tx, ctx, ids=None):
    staff = _staff(tx, ctx)
    if not staff:
        return []
    query = CLASS_QUERY
    params = [ctx["school_id"]]
    if not _school_wide(staff):
        query += """ AND EXISTS (SELECT 1 FROM org_staff_classes a WHERE a.school_id=c.school_id
                                  AND a.class_id=c.id AND a.staff_id=?)"""
        params.append(ctx["actor_id"])
    if ids is not None:
        if not ids:
            return []
        query += " AND c.id IN (" + ",".join("?" for _ in ids) + ")"
        params.extend(ids)
    return tx.all(query + " ORDER BY c.id", tuple(params))


def class_access(tx, ctx, class_id):
    """核验当前职员的班级可见性；具体动作还须单独调用 require_staff 校验。"""
    return bool(_visible_classes(tx, ctx, [class_id]))


def student_access(tx, ctx, student_id):
    """限定为学生本人、全校管理员或该班当前负责的教职工。"""
    row = tx.one("""SELECT e.class_id,e.status FROM identity_student_credentials s
        LEFT JOIN org_enrollments e ON e.school_id=s.school_id AND e.student_id=s.actor_id
        WHERE s.school_id=? AND s.actor_id=? AND s.status='normal'""", (ctx["school_id"], student_id))
    if row is None:
        return False
    if ctx["actor_type"] == "student":
        return ctx["actor_id"] == student_id
    return _school_wide(_staff(tx, ctx)) or (row["status"] == "active" and class_access(tx, ctx, row["class_id"]))


@router.post("/internal/staff/authorize-student")
def authorize_student(body: StudentAction, request: Request,
                      ctx=Depends(require_service("identity", "identity.student.authorize"))):
    # 在同一快照核验权限与学籍。评估和证书服务还需核验具体训练任务的负责教师。
    if body.action == "profile.student.read" and ctx["caller"] != "profile":
        raise HTTPException(403, "仅档案服务可以核验教学档案访问")
    with request.app.state.store.transaction() as tx:
        require_staff(tx, ctx, body.action)
        if not student_access(tx, ctx, body.student_id):
            raise HTTPException(403, "Student outside current scope")
        return {"school_id": ctx["school_id"], "actor_id": ctx["actor_id"], "actor_type": ctx["actor_type"],
                "student_id": body.student_id, "action": body.action}


@router.get("/classes")
def classes(request: Request, ctx=Depends(require_service("identity", "identity.classes.read"))):
    with request.app.state.store.transaction() as tx:
        require_staff(tx, ctx, "identity.classes.read")
        return {"items": _visible_classes(tx, ctx)}


@router.get("/v1/organization")
def organization(request: Request, ctx=Depends(require_service("identity", "organization.read"))):
    school = ctx["school_id"]
    with request.app.state.store.transaction() as tx:
        require_staff(tx, ctx, "organization.read")
        groups = _visible_classes(tx, ctx)
        if _school_wide(_staff(tx, ctx)):
            colleges = tx.all("SELECT id,name FROM org_colleges WHERE school_id=? AND status='active' ORDER BY id", (school,))
            programs = tx.all("""SELECT p.id,p.name,p.college_id FROM org_programs p JOIN org_colleges c
                ON c.id=p.college_id AND c.school_id=p.school_id WHERE p.school_id=?
                AND c.status='active' AND p.status='active' ORDER BY p.id""", (school,))
        else:
            # 受限账号只能查看所管理班级的上级组织。
            colleges = list({g["college_id"]: {"id": g["college_id"], "name": g["college_name"]} for g in groups}.values())
            programs = list({g["program_id"]: {"id": g["program_id"], "name": g["program_name"],
                                               "college_id": g["college_id"]} for g in groups}.values())
        if _school_wide(_staff(tx, ctx)):
            organization_details.attach(tx, school, {"org_colleges": colleges, "org_programs": programs, "org_classes": groups})
        return {"school_id": school, "colleges": colleges, "programs": programs, "classes": groups}


@router.post("/classes/roster")
def roster(body: ClassLookup, request: Request, ctx=Depends(require_service("identity", "identity.roster.read"))):
    school = ctx["school_id"]
    with request.app.state.store.transaction() as tx:
        require_staff(tx, ctx, "identity.roster.read")
        groups = {row["class_id"]: [] for row in _visible_classes(tx, ctx, body.class_ids)}
        if len(groups) != len(body.class_ids):
            raise HTTPException(403, "Invalid or unauthorized class selection")
        placeholders = ",".join("?" for _ in groups)
        for row in tx.all(f"""SELECT e.class_id,e.student_id FROM org_enrollments e
                JOIN identity_student_credentials s ON s.school_id=e.school_id AND s.actor_id=e.student_id
                WHERE e.school_id=? AND e.status='active' AND s.status='normal'
                AND e.class_id IN ({placeholders}) ORDER BY e.student_id""", (school, *groups)):
            groups[row["class_id"]].append(row["student_id"])
        return {"classes": [{"class_id": k, "student_ids": groups[k]} for k in body.class_ids]}


PageOffset = Annotated[int, Query(ge=0, le=1_000_000)]
FilterText = Annotated[str, Query(max_length=128)]
PAGE = 50


def _page(tx, query, params, offset):
    rows = tx.all(query + " LIMIT ? OFFSET ?", (*params, PAGE + 1, offset))
    return {"items": rows[:PAGE], "has_more": len(rows) > PAGE}


@router.get("/v1/classes/{class_id}/roster")
def named_roster(class_id: Identifier, request: Request, offset: PageOffset = 0,
                 ctx=Depends(require_service("identity", "organization.read"))):
    with request.app.state.store.transaction() as tx:
        require_staff(tx, ctx, "organization.read")
        if not class_access(tx, ctx, class_id):
            raise HTTPException(403, "Class outside current scope")
        result = _page(tx, """SELECT s.actor_id,s.name,s.student_no FROM org_enrollments e
            JOIN identity_student_credentials s ON s.school_id=e.school_id AND s.actor_id=e.student_id
            WHERE e.school_id=? AND e.class_id=? AND e.status='active' AND s.status='normal'
            ORDER BY s.student_no,s.actor_id""", (ctx["school_id"], class_id), offset)
        return {"class_id": class_id, **result}


@router.get("/v1/organization/roster-candidates")
def roster_candidates(request: Request, q: Annotated[str, Query(min_length=1, max_length=128)],
                      offset: PageOffset = 0, ctx=Depends(require_service("identity", "roster.import"))):
    with request.app.state.store.transaction() as tx:
        staff = require_staff(tx, ctx, "roster.import")
        require_staff(tx, ctx, "organization.read")
        query = """SELECT s.actor_id,s.name,s.student_no,e.class_id,c.name AS class_name FROM identity_student_credentials s
            LEFT JOIN org_enrollments e ON e.school_id=s.school_id AND e.student_id=s.actor_id
            LEFT JOIN org_classes c ON c.school_id=e.school_id AND c.id=e.class_id
            WHERE s.school_id=? AND s.status='normal' AND
            (instr(s.student_no,?)>0 OR instr(s.name,?)>0 OR s.actor_id=?)"""
        params = [ctx["school_id"], q.upper(), q, q]
        if not _school_wide(staff):
            # 仅全校管理员可操作尚未归班的学生。先在 SQL 中限定范围，再分页。
            query += """ AND e.status='active' AND c.status='active' AND EXISTS (
                SELECT 1 FROM org_staff_classes a JOIN org_programs p ON p.school_id=a.school_id AND p.id=c.program_id
                JOIN org_colleges d ON d.school_id=p.school_id AND d.id=p.college_id
                WHERE a.school_id=e.school_id AND a.class_id=e.class_id AND a.staff_id=?
                AND p.status='active' AND d.status='active')"""
            params.append(ctx["actor_id"])
        return _page(tx, query + " ORDER BY s.student_no,s.actor_id", params, offset)


def _assignment_editor(tx, ctx, class_id):
    staff = require_staff(tx, ctx, "organization.manage")
    if not _school_wide(staff):
        raise HTTPException(403, "Whole-school administration required")
    _parent_exists(tx, "org_classes", ctx["school_id"], class_id)


def _assigned_staff(tx, school, class_id):
    return tx.all("""SELECT s.actor_id,s.name,s.actor_type,s.status FROM org_staff_classes a
        JOIN identity_staff s ON s.school_id=a.school_id AND s.actor_id=a.staff_id
        WHERE a.school_id=? AND a.class_id=? ORDER BY s.actor_id""", (school, class_id))


@router.get("/v1/classes/{class_id}/staff")
def class_staff(class_id: Identifier, request: Request, q: FilterText = "", offset: PageOffset = 0,
                ctx=Depends(require_service("identity", "organization.manage"))):
    with request.app.state.store.transaction() as tx:
        _assignment_editor(tx, ctx, class_id)
        require_staff(tx, ctx, "organization.read")
        result = _page(tx, """SELECT actor_id,name,actor_type FROM identity_staff
            WHERE school_id=? AND status='normal' AND (instr(name,?)>0 OR actor_id=?)
            ORDER BY name,actor_id""", (ctx["school_id"], q, q), offset)
        return {"assigned": _assigned_staff(tx, ctx["school_id"], class_id), **result}


class StaffAssignment(Input):
    expected_staff_ids: list[Identifier] = Field(max_length=2000)
    staff_ids: list[Identifier] = Field(max_length=200)


@router.put("/v1/classes/{class_id}/staff")
def replace_assignment(class_id: Identifier, body: StaffAssignment, request: Request,
                       ctx=Depends(require_service("identity", "organization.manage"))):
    store, school = request.app.state.store, ctx["school_id"]
    with store.transaction(write=True) as tx:
        lock_school(tx, store, school)
        _assignment_editor(tx, ctx, class_id)
        previous = {row["actor_id"] for row in _assigned_staff(tx, school, class_id)}
        if previous != set(body.expected_staff_ids):
            raise HTTPException(409, "班级分配已变化，请刷新后重试。")
        _set_staff(tx, ctx, class_id, body.staff_ids, previous)
    return {"class_id": class_id, "staff_ids": sorted(set(body.staff_ids))}


def _set_staff(tx, ctx, class_id, staff_ids, previous=None):
    school = ctx["school_id"]
    if previous is None:
        previous = {r["actor_id"] for r in _assigned_staff(tx, school, class_id)}
    desired = set(staff_ids)
    from .permission_requests import invalidate_pending
    for changed_id in previous ^ desired:
        invalidate_pending(tx, school, changed_id)
    for staff_id in sorted(previous - desired):
        tx.execute("DELETE FROM org_staff_classes WHERE school_id=? AND class_id=? AND staff_id=?",
                   (school, class_id, staff_id))
        audit(tx, ctx, "organization.class.staff.remove", class_id, summary=staff_id)
    for staff_id in sorted(desired - previous):
        if not tx.one("SELECT actor_id FROM identity_staff WHERE school_id=? AND actor_id=? AND status='normal'",
                      (school, staff_id)):
            raise HTTPException(422, "Unknown or disabled staff member")
        tx.execute("INSERT INTO org_staff_classes (school_id,staff_id,class_id) VALUES (?,?,?)",
                   (school, staff_id, class_id))
        audit(tx, ctx, "organization.class.staff.add", class_id, summary=staff_id)


def _upsert_node(tx, school, table, node, parent=None):
    if node.details is not None:
        organization_details.update(tx, school, table, node.id, node.details)
    # 表名和外键列只取模块内部常量，学校编号始终用绑定参数。
    if node.status == "inactive":
        # 禁止停用仍有在用下级、任课或学籍关系的节点。先调整归属，避免恢复节点时自动恢复旧授权。
        checks = {
            "org_colleges": ("SELECT 1 FROM org_programs WHERE school_id=? AND college_id=? AND status='active'",),
            "org_programs": ("SELECT 1 FROM org_classes WHERE school_id=? AND program_id=? AND status='active'",),
            "org_classes": ("SELECT 1 FROM org_staff_classes WHERE school_id=? AND class_id=?",
                            "SELECT 1 FROM org_enrollments WHERE school_id=? AND class_id=? AND status='active'"),
        }
        if any(tx.one(sql + " LIMIT 1", (school, node.id)) for sql in checks[table]):
            raise HTTPException(409, "节点仍有关联的下级、任课教师或在读学生，请先调整后停用。")
    old = tx.one(f"SELECT * FROM {table} WHERE school_id=? AND id=?", (school, node.id))
    if old:
        if parent and old[parent] != getattr(node, parent):
            raise HTTPException(409, "Existing organization node has a different parent")
        tx.execute(f"UPDATE {table} SET name=?,status=? WHERE school_id=? AND id=?",
                   (node.name, node.status, school, node.id))
    else:
        cols = ", " + parent if parent else ""
        extra = (getattr(node, parent),) if parent else ()
        tx.execute(f"INSERT INTO {table} (school_id,id,name,status{cols}) VALUES (?,?,?,?{',?' if parent else ''})",
                   (school, node.id, node.name, node.status, *extra))


def _parent_exists(tx, table, school, parent_id):
    if not tx.one(f"SELECT id FROM {table} WHERE school_id=? AND id=? AND status='active'", (school, parent_id)):
        raise HTTPException(422, "Organization parent does not exist in this school")


@router.post("/v1/organization/import")
def import_organization(body: OrganizationImport, request: Request,
                        ctx=Depends(require_service("identity", "organization.manage"))):
    school = ctx["school_id"]
    store = request.app.state.store
    with store.transaction(write=True) as tx:
        lock_school(tx, store, school)
        require_staff(tx, ctx, "organization.manage")
        if not _school_wide(_staff(tx, ctx)):
            raise HTTPException(403, "Whole-school administration required")
        for nodes in (body.colleges, body.programs, body.classes):
            if len({n.id for n in nodes}) != len(nodes):
                raise HTTPException(422, "Duplicate organization node")
        for node in body.colleges:
            _upsert_node(tx, school, "org_colleges", node)
        for program in body.programs:
            _parent_exists(tx, "org_colleges", school, program.college_id)
            _upsert_node(tx, school, "org_programs", program, "college_id")
        for group in body.classes:
            _parent_exists(tx, "org_programs", school, group.program_id)
            _upsert_node(tx, school, "org_classes", group, "program_id")
            if group.staff_ids is not None:
                _set_staff(tx, ctx, group.id, group.staff_ids)
            audit(tx, ctx, "organization.import.class", group.id)
        audit(tx, ctx, "organization.import", school)
        return {"colleges": len(body.colleges), "programs": len(body.programs), "classes": len(body.classes)}


@router.post("/v1/classes/{class_id}/roster/import")
def import_roster(class_id: Identifier, body: RosterImport, request: Request,
                  ctx=Depends(require_service("identity", "roster.import"))):
    store = request.app.state.store
    school = ctx["school_id"]
    with store.transaction(write=True) as tx:
        lock_school(tx, store, school)
        require_staff(tx, ctx, "roster.import")
        if not class_access(tx, ctx, class_id):
            raise HTTPException(403, "Class outside current scope")
        whole_school = _school_wide(_staff(tx, ctx))
        for student_id in sorted(set(body.student_ids)):
            if not tx.one("SELECT actor_id FROM identity_student_credentials WHERE school_id=? AND actor_id=? AND status='normal'",
                          (school, student_id)):
                raise HTTPException(403, "Student outside current scope")
            current = tx.one("SELECT class_id,status FROM org_enrollments WHERE school_id=? AND student_id=?", (school, student_id))
            # 受限教师不能用猜测的学生编号领取未归班学生，或从其他教师班级转移学生。
            if not whole_school and (not current or current["status"] != "active" or not class_access(tx, ctx, current["class_id"])):
                raise HTTPException(403, "Student outside current scope")
            if current:
                tx.execute("UPDATE org_enrollments SET class_id=?,status=? WHERE school_id=? AND student_id=?",
                           (class_id, body.status, school, student_id))
            else:
                tx.execute("INSERT INTO org_enrollments (school_id,student_id,class_id,status) VALUES (?,?,?,?)",
                           (school, student_id, class_id, body.status))
            audit(tx, ctx, "roster.import.student", student_id, summary=json.dumps(
                {"previous_class_id": current["class_id"] if current else None, "class_id": class_id, "status": body.status}))
        audit(tx, ctx, "roster.import", class_id)
        return {"class_id": class_id, "count": len(set(body.student_ids))}


@router.get("/v1/audit")
def list_audit(request: Request, limit: Annotated[int, Query(ge=1, le=500)] = 100,
               before: Identifier | None = None, action: Identifier | None = None,
               actor_id: Identifier | None = None, ctx=Depends(require_service("identity", "audit.read"))):
    school = ctx["school_id"]
    with request.app.state.store.transaction() as tx:
        require_staff(tx, ctx, "audit.read")
        if not _school_wide(_staff(tx, ctx)):
            raise HTTPException(403, "Whole-school administration required")
        condition, params = "school_id=?", [school]
        if action:
            condition += " AND action=?"
            params.append(action)
        if actor_id:
            condition += " AND actor_id=?"
            params.append(actor_id)
        if before:
            cursor = tx.one("SELECT created_at FROM identity_audit WHERE school_id=? AND id=?", (school, before))
            if not cursor:
                raise HTTPException(400, "Invalid audit cursor")
            # 使用固定排序的游标，新写入的审计记录不会挤掉尚未读取的旧记录。
            condition += " AND (created_at < ? OR (created_at = ? AND id < ?))"
            params.extend((cursor["created_at"], cursor["created_at"], before))
        rows = tx.all(f"""SELECT id,actor_id,action,target_id,success,summary,created_at
                FROM identity_audit WHERE {condition} ORDER BY created_at DESC,id DESC LIMIT ?""", (*params, limit + 1))
        return {"items": rows[:limit], "next": rows[limit-1]["id"] if len(rows) > limit else None,
                "school_id": school}


def _legacy_rows(source, table, school_id):
    # 旧库按学校绑定；若历史行本身也有学校标识，两者必须完全一致。
    for row in source.all(f"SELECT * FROM {table}"):
        if row.get("school_id", school_id) != school_id:
            raise ValueError(f"Source {table} contains a row outside the bound school")
        yield row


def _archive(tx, school, table, record_id, row):
    # 保留原专业方向、辅导员、导入人与审计元数据。归档数据不作为在线授权依据。
    tx.execute("""INSERT INTO identity_legacy_organization
                  (school_id,source_table,record_id,legacy_record) VALUES (?,?,?,?)""",
               (school, table, record_id, json.dumps(row, default=str, ensure_ascii=False)))


def migrate_legacy(tx, source, school_id):
    """在身份迁移事务内导入已核验的单校快照。历史学院和专业授权展开为当时存在的班级，辅导员姓名不等于任课关系，重跑不能恢复已撤销权限。"""
    if tx.one("SELECT school_id FROM org_legacy_migration WHERE school_id=?", (school_id,)):
        return
    for table, old, parent in (("org_colleges", "campus_colleges", ""), ("org_programs", "campus_programs", ",college_id"),
                               ("org_classes", "campus_classes", ",program_id")):
        cols = "id,name,status" + parent
        for row in _legacy_rows(source, old, school_id):
            values = tuple(row[col] for col in cols.split(","))
            tx.execute(f"INSERT INTO {table} (school_id,{cols}) VALUES (" + ",".join("?" for _ in range(1+len(values))) + ")",
                       (school_id, *values))
            _archive(tx, school_id, old, row["id"], row)
    # 仅为实际迁入的学生建立学籍。旧标识不能把已删除或不可用的账号加入有效名单。
    for row in _legacy_rows(source, "student_registrations", school_id):
        # 归档白名单防止自定义的旧登记表附带明文临时密码或身份令牌。
        _archive(tx, school_id, "student_registrations", row["id"],
                 {k:v for k,v in row.items() if k in REGISTRATION_ARCHIVE_FIELDS})
    for row in _legacy_rows(source, "student_enrollments", school_id):
        _archive(tx, school_id, "student_enrollments", row["user_id"], row)
        if row["class_id"] is None:
            continue
        tx.execute("""INSERT INTO org_enrollments (school_id,student_id,class_id,status)
                   SELECT school_id,actor_id,?,? FROM identity_student_credentials WHERE school_id=? AND actor_id=?""",
                   (row["class_id"], row["status"], school_id, row["user_id"]))
    groups = tx.all("""SELECT c.id class_id,p.id program_id,p.college_id FROM org_classes c
                       JOIN org_programs p ON p.id=c.program_id AND p.school_id=c.school_id WHERE c.school_id=?""", (school_id,))
    # 只读来源库可能没有范围字段。缺失授权按空处理，不对来源库执行结构升级。
    for member in source.all("SELECT * FROM admin_users"):
        if not tx.one("SELECT actor_id FROM identity_staff WHERE school_id=? AND actor_id=?", (school_id, member["id"])):
            continue
        try:
            entries = json.loads(member.get("student_scope") or "[]")
        except (TypeError, ValueError):
            continue
        if not isinstance(entries, list):
            continue
        # 包含未知范围键的授权整条舍弃，避免拼错班级字段后被扩大为全院权限。
        entries = [e for e in entries if isinstance(e, dict)
                   and not (e.keys() - {"college", "program", "class"})
                   and isinstance(e.get("college"), str) and e["college"].strip()]
        for group in groups:
            if any(e["college"] == group["college_id"]
                   and e.get("program", "") in ("", group["program_id"])
                   and e.get("class", "") in ("", group["class_id"]) for e in entries):
                tx.execute("INSERT INTO org_staff_classes (school_id,staff_id,class_id) VALUES (?,?,?)",
                           (school_id, member["id"], group["class_id"]))
    for log in _legacy_rows(source, "admin_audit_logs", school_id):
        _archive(tx, school_id, "admin_audit_logs", log["id"], log)
        tx.execute("""INSERT INTO identity_audit (school_id,id,actor_id,action,target_id,success,summary,created_at)
                      VALUES (?,?,?,?,?,?,?,?)""",
                   (school_id, log["id"], log["admin_user_id"], log["action"], log["target_id"], log["success"],
                    log["summary"], log["created_at"]))
    tx.execute("INSERT INTO org_legacy_migration (school_id) VALUES (?)", (school_id,))
