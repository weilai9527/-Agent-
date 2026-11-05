"""学校登记名单与账号发放。用户标识稳定保留，名单归档与撤销登录权限分别操作。"""
import json
import secrets
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field, ValidationError

from shared.account_security import hash_password, is_valid_student_no, normalize_student_no
from shared.service_security import require_service
from .organization import CLASS_QUERY, REGISTRATION_ARCHIVE_FIELDS, Input, audit, lock_school
from .registration_workbook import export_rows, read_rows
from .staff import require_staff

router = APIRouter(prefix="/v1/registrations")
SCHEMA = ("""CREATE TABLE IF NOT EXISTS identity_registrations (
    school_id VARCHAR(128) NOT NULL, student_no VARCHAR(80) NOT NULL, name VARCHAR(120) NOT NULL,
    college VARCHAR(160) NOT NULL, class_name VARCHAR(160) NOT NULL, class_id VARCHAR(128) NOT NULL,
    gender VARCHAR(20) NOT NULL, counselor VARCHAR(120) NOT NULL, source_status VARCHAR(80) NOT NULL,
    student_status VARCHAR(80) NOT NULL, actor_id VARCHAR(128), opened INTEGER NOT NULL,
    archived INTEGER NOT NULL, revision INTEGER NOT NULL, PRIMARY KEY(school_id,student_no),
    UNIQUE(school_id,actor_id))""",
    """CREATE TABLE IF NOT EXISTS identity_registration_backfill (
    school_id VARCHAR(128) PRIMARY KEY, completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
DATA = ("name", "college", "class_name", "class_id", "gender", "counselor", "source_status", "student_status")
READ = "registration.read"
EXPORT = "registration.export"
IMPORT = "registration.import"
ISSUE = "registration.issue"
STATUS = "registration.status"
RESET = "registration.reissue"
ACTIONS = (READ, EXPORT, IMPORT, ISSUE, STATUS, RESET)


class Row(Input):
    student_no: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    college: str = Field("", max_length=160)
    class_name: str = Field("", max_length=160)
    class_id: str = Field("", max_length=128)
    gender: str = Field("", max_length=20)
    counselor: str = Field("", max_length=120)
    source_status: str = Field("", max_length=80)
    student_status: str = Field("", max_length=80)


class Rows(Input):
    rows: list[Row] = Field(min_length=1, max_length=4999)


class Workbook(Input):
    filename: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=983040)


class Selected(Input):
    student_no: str = Field(min_length=1, max_length=80)
    revision: int = Field(ge=1, strict=True)


class Batch(Input):
    items: list[Selected] = Field(min_length=1, max_length=100)
    reason: Literal["凭据遗失", "发放失败"] | None = None


def manager(tx, ctx, action):
    staff = require_staff(tx, ctx, action)
    if ctx["caller"] != "admin-gateway" or staff["actor_type"] != "admin" or not staff["school_wide"]:
        raise HTTPException(403, "需要本校全校管理范围和相应的登记权限。")


def disabled(row):
    text = (row["source_status"] + " " + row["student_status"]).lower()
    return any(word in text for word in ("禁用", "停用", "冻结", "注销", "退学", "无效", "disabled", "inactive"))


def merge_row(tx, school, row):
    number = normalize_student_no(row.student_no)
    cols = row.model_fields_set.intersection(DATA)
    if not is_valid_student_no(number) or not row.name.strip():
        raise HTTPException(422, "学号格式错误或姓名为空。")
    keys = (school, number)
    old = tx.one("SELECT * FROM identity_registrations WHERE school_id=? AND student_no=?", keys)
    if old:
        # 部分列增量导入，缺列保留原值；归档名单只有显式恢复操作才能重新启用。
        changed = [col for col in DATA if col in cols and old[col] != getattr(row, col).strip()]
        if changed:
            tx.execute("UPDATE identity_registrations SET " + ",".join(col+"=?" for col in changed) +
                       ",revision=revision+1 WHERE school_id=? AND student_no=?",
                       (*[getattr(row, col).strip() for col in changed], *keys))
        return "updated" if changed else "unchanged"
    account = tx.one("SELECT actor_id FROM identity_student_credentials WHERE school_id=? AND student_no=?", keys)
    fields = [getattr(row, col).strip() for col in DATA]
    tx.execute("""INSERT INTO identity_registrations (school_id,student_no,name,college,class_name,class_id,gender,
               counselor,source_status,student_status,actor_id,opened,archived,revision)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,1)""",
               (*keys, *fields, account["actor_id"] if account else None, int(bool(account))))
    return "created"


def save_rows(rows, request, ctx):
    seen = set()
    result = {"created": 0, "updated": 0, "unchanged": 0}
    store = request.app.state.store
    with store.transaction(write=True) as tx:
        lock_school(tx, store, ctx["school_id"])
        manager(tx, ctx, IMPORT)
        for row in rows:
            number = normalize_student_no(row.student_no)
            if number in seen:
                raise HTTPException(422, "文件内有重复学号，未写入本批名单。")
            seen.add(number)
            result[merge_row(tx, ctx["school_id"], row)] += 1
        audit(tx, ctx, IMPORT, ctx["school_id"], summary=json.dumps(result))
    return result


@router.post("/import")
def import_json(body: Rows, request: Request, ctx=Depends(require_service("identity", IMPORT))):
    return save_rows(body.rows, request, ctx)


@router.post("/import-xlsx")
def import_xlsx(body: Workbook, request: Request, ctx=Depends(require_service("identity", IMPORT))):
    # 先确认学校的实时授权，再花费资源解压；写入前在数据库事务中重新鉴权。
    with request.app.state.store.transaction() as tx:
        manager(tx, ctx, IMPORT)
    try:
        rows = Rows(rows=read_rows(body.filename, body.content)).rows
    except ValidationError:
        raise HTTPException(422, "登记行内容或长度超出限制。") from None
    return save_rows(rows, request, ctx)


State = Literal["all", "pending", "opened", "archived"]


def query_rows(tx, school, q, counselor, state, offset, limit):
    sql = """ FROM identity_registrations r LEFT JOIN identity_student_credentials a
        ON a.school_id=r.school_id AND a.actor_id=r.actor_id WHERE r.school_id=?"""
    args = [school]
    if state == "archived":
        sql += " AND r.archived=1"
    else:
        sql += " AND r.archived=0"
        if state != "all":
            sql += " AND r.opened=?"
            args.append(int(state == "opened"))
    if q:
        sql += " AND (instr(r.name,?)>0 OR instr(r.student_no,?)>0 OR instr(r.class_name,?)>0 OR instr(r.college,?)>0)"
        args.extend([q, normalize_student_no(q), q, q])
    if counselor:
        sql += " AND r.counselor=?"
        args.append(counselor)
    total = tx.one("SELECT COUNT(*) AS n"+sql, tuple(args))["n"]
    items = tx.all("SELECT r.*,a.status AS login_status,a.must_change_password"+sql+
                   " ORDER BY r.student_no LIMIT ? OFFSET ?", (*args, limit, offset))
    for row in items:
        row["state"] = "已归档" if row["archived"] else ("已开通" if row["opened"] else "待开通")
    return {"items": items, "total": total}


@router.get("")
def list_registrations(request: Request, q: str = Query("", max_length=160), counselor: str = Query("", max_length=120),
                       state: State = "all", offset: int = Query(0, ge=0), ctx=Depends(require_service("identity", READ))):
    with request.app.state.store.transaction() as tx:
        manager(tx, ctx, READ)
        return query_rows(tx, ctx["school_id"], q.strip(), counselor.strip(), state, offset, 50)


@router.get("/export")
def download(request: Request, q: str = Query("", max_length=160), counselor: str = Query("", max_length=120),
             state: State = "all", ctx=Depends(require_service("identity", EXPORT))):
    store = request.app.state.store
    with store.transaction(write=True) as tx:
        lock_school(tx, store, ctx["school_id"])
        manager(tx, ctx, EXPORT)
        page = query_rows(tx, ctx["school_id"], q.strip(), counselor.strip(), state, 0, 5000)
        if page["total"] > 4999:
            raise HTTPException(413, "请按辅导员或班级筛选后分批导出。")
        audit(tx, ctx, "registration.export", ctx["school_id"], summary=str(page["total"]))
    return export_rows(page["items"])


def placement(tx, school, row, actor_id):
    # 班级名称可能跨学院重复。只有本校唯一的有效班级，才可产生正式学籍关系。
    if not row["class_id"] and not row["class_name"]:
        return
    sql = CLASS_QUERY
    args = [school]
    if row["class_id"]:
        sql += " AND c.id=?"
        args.append(row["class_id"])
    else:
        sql += " AND c.name=?"
        args.append(row["class_name"])
    if row["college"]:
        sql += " AND d.name=?"
        args.append(row["college"])
    found = tx.all(sql+" LIMIT 2", tuple(args))
    if len(found) != 1:
        raise HTTPException(409, "班级缺失、已停用或重名，请先维护组织并填写班级编号。")
    key = (school, actor_id)
    if tx.one("SELECT student_id FROM org_enrollments WHERE school_id=? AND student_id=?", key):
        tx.execute("UPDATE org_enrollments SET class_id=?,status='active' WHERE school_id=? AND student_id=?",
                   (found[0]["class_id"], *key))
    else:
        tx.execute("INSERT INTO org_enrollments VALUES (?,?,?,'active')", (*key, found[0]["class_id"]))


def change_one(tx, ctx, row, op, store):
    school, number = ctx["school_id"], row["student_no"]
    actor_id = row["actor_id"]
    key = (school, number)
    if op in {"archive", "restore"}:
        if bool(row["archived"]) == (op == "archive"):
            raise HTTPException(409, "名单状态已变化。")
        tx.execute("UPDATE identity_registrations SET archived=?,revision=revision+1 WHERE school_id=? AND student_no=?",
                   (int(op == "archive"), *key))
        return
    if row["archived"]:
        raise HTTPException(409, "请先恢复归档的名单。")
    lock = " FOR UPDATE" if store.engine == "mysql" else ""
    account = tx.one("SELECT actor_id,status FROM identity_student_credentials WHERE school_id=? AND student_no=?"+lock, key)
    if account and account["actor_id"] != actor_id:
        raise HTTPException(409, "学号已由其他账号持有，请核对名册。")
    if op == "apply":
        if not row["opened"] or not account:
            raise HTTPException(409, "请先开通学生账号。")
        tx.execute("UPDATE identity_student_credentials SET name=? WHERE school_id=? AND actor_id=?",
                   (row["name"], school, actor_id))
        if disabled(row):
            tx.execute("UPDATE identity_student_credentials SET status='disabled' WHERE school_id=? AND actor_id=?", (school, actor_id))
            tx.execute("DELETE FROM identity_student_sessions WHERE school_id=? AND actor_id=?", (school, actor_id))
        if row["class_name"] or row["class_id"]:
            manager(tx, ctx, "roster.import")
            placement(tx, school, row, actor_id)
        # 导入名册仅形成待应用的数据。此操作不能用文件中的“正常”字段恢复管理员停用的账号。
        tx.execute("UPDATE identity_registrations SET revision=revision+1 WHERE school_id=? AND student_no=?", key)
        return
    if op == "revoke":
        if not row["opened"] or not account:
            raise HTTPException(409, "该登记尚未开通。")
        tx.execute("UPDATE identity_student_credentials SET status='registration_revoked' WHERE school_id=? AND actor_id=?",
                   (school, actor_id))
        tx.execute("DELETE FROM identity_student_sessions WHERE school_id=? AND actor_id=?", (school, actor_id))
        tx.execute("UPDATE identity_registrations SET opened=0,revision=revision+1 WHERE school_id=? AND student_no=?", key)
        return
    if disabled(row):
        raise HTTPException(409, "学籍状态禁止开通或补发密码。")
    if actor_id and not account:
        raise HTTPException(409, "关联的学生账号缺失，请先核对名册。")
    if op == "issue" and account and account["status"] != "registration_revoked":
        raise HTTPException(409, "当前账号并非名单撤销状态，请核对账号管理记录。")
    if op == "issue" and row["opened"]:
        raise HTTPException(409, "该登记已开通，补发密码需单独授权。")
    if op == "reissue" and (not row["opened"] or not account or account["status"] != "normal"):
        raise HTTPException(409, "只有在用账号可以补发密码。")
    password = secrets.token_urlsafe(18)
    if account:
        tx.execute("""UPDATE identity_student_credentials SET password_hash=?,status='normal',must_change_password=1
                   WHERE school_id=? AND actor_id=?""", (hash_password(password), school, actor_id))
        tx.execute("DELETE FROM identity_student_sessions WHERE school_id=? AND actor_id=?", (school, actor_id))
    else:
        actor_id = str(uuid4())
        tx.execute("""INSERT INTO identity_student_credentials
                   (school_id,actor_id,student_no,name,password_hash,status,must_change_password)
                   VALUES (?,?,?,?,?,'normal',1)""", (school, actor_id, number, row["name"], hash_password(password)))
    if op == "issue" and (row["class_name"] or row["class_id"]):
        manager(tx, ctx, "roster.import")
        placement(tx, school, row, actor_id)
    tx.execute("""UPDATE identity_registrations SET opened=1,actor_id=?,revision=revision+1
               WHERE school_id=? AND student_no=?""", (actor_id, *key))
    # 明文只在此响应中供打印。首次改密、重置及主动撤销均使旧凭据失效。
    return {"student_no": number, "name": row["name"], "temporary_password": password}


def operation(action, op):
    def change(body: Batch, request: Request, ctx=Depends(require_service("identity", action))):
        store = request.app.state.store
        handout = []
        with store.transaction(write=True) as tx:
            lock_school(tx, store, ctx["school_id"])
            manager(tx, ctx, action)
            if op == "reissue" and not body.reason:
                raise HTTPException(422, "请注明补发原因。")
            for item in body.items:
                row = tx.one("SELECT * FROM identity_registrations WHERE school_id=? AND student_no=?",
                             (ctx["school_id"], normalize_student_no(item.student_no)))
                if not row:
                    raise HTTPException(404, "本校名单中没有该学生。")
                if row["revision"] != item.revision:
                    raise HTTPException(409, "名单已变更，请刷新并核对后操作。")
                creds = change_one(tx, ctx, row, op, store)
                if creds:
                    handout.append(creds)
                audit(tx, ctx, "registration."+op, row["student_no"], summary=body.reason if op == "reissue" else None)
        return {"changed": len(body.items), "handout": handout}
    return change


ROUTES = (("issue", ISSUE), ("reissue", RESET), ("revoke", STATUS), ("apply", STATUS), ("archive", STATUS), ("restore", STATUS))
for path, scope in ROUTES:
    router.add_api_route("/"+path, operation(scope, path), methods=["POST"], name="registration."+path)


def source_metadata(snapshot, engine):
    # 仅从旧账号读取学籍字段，不将初始密码、加密口令或会话带入身份域。
    if engine == "sqlite":
        columns = {row["name"] for row in snapshot.all("PRAGMA table_info(users)")}
    else:
        columns = {row["col"] for row in snapshot.all("""SELECT COLUMN_NAME AS col FROM INFORMATION_SCHEMA.COLUMNS
                                                       WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='users'""")}
    mapping = {key: key for key in ("college", "gender", "class_name", "counselor", "student_status")}
    mapping["source_account_status"] = "source_status"
    selected = [key+" AS "+dest for key, dest in mapping.items() if key in columns]
    rows = snapshot.all("SELECT " + ",".join(["id", *selected]) + " FROM users")
    return {r.pop("id"): r for r in rows}


def backfill(tx, school, snapshot, engine):
    """在切换事务中导入旧登记存档；同一学校只执行一次，重跑不会复活已撤销账号。"""
    if tx.one("SELECT school_id FROM identity_registration_backfill WHERE school_id=?", (school,)):
        return
    metadata = source_metadata(snapshot, engine)
    accounts = {r["actor_id"]: r for r in tx.all("""SELECT actor_id,student_no,name FROM identity_student_credentials
                                                   WHERE school_id=? AND student_no IS NOT NULL""", (school,))}
    for entry in tx.all("""SELECT record_id,legacy_record FROM identity_legacy_organization
                        WHERE school_id=? AND source_table='student_registrations'""", (school,)):
        old = json.loads(entry["legacy_record"])
        safe = {key: value for key, value in old.items() if key in REGISTRATION_ARCHIVE_FIELDS}
        if safe != old:
            # 兼容此前未经列白名单的存档；修剪的是目标影子副本，不写入离线来源库。
            tx.execute("""UPDATE identity_legacy_organization SET legacy_record=?
                       WHERE school_id=? AND source_table='student_registrations' AND record_id=?""",
                       (json.dumps(safe, ensure_ascii=False, default=str), school, entry["record_id"]))
        linked = accounts.get(old.get("user_id"), {})
        number = normalize_student_no(old.get("student_no") or linked.get("student_no"))
        if not number:
            # 极早期的无学号且无账号行仅保留原始存档，不猜测账号归属。
            continue
        if old.get("user_id") and (not linked or linked["student_no"] != number):
            raise ValueError("历史账号和登记学号冲突，请先核对快照。")
        row = Row(student_no=number, name=old.get("name") or linked.get("name") or number,
                  **{col: old.get(col) or metadata.get(linked.get("actor_id"), {}).get(col) or ""
                     for col in DATA if col != "name"})
        if tx.one("SELECT student_no FROM identity_registrations WHERE school_id=? AND student_no=?", (school, number)):
            continue
        merge_row(tx, school, row)
        if old.get("deleted_at"):
            tx.execute("UPDATE identity_registrations SET archived=1 WHERE school_id=? AND student_no=?", (school, number))
    for account in accounts.values():
        number = account["student_no"]
        if tx.one("SELECT student_no FROM identity_registrations WHERE school_id=? AND student_no=?", (school, number)):
            link_open_account(tx, school, number, account["name"], account["actor_id"])
        else:
            details = {k:v for k,v in metadata.get(account["actor_id"], {}).items() if v}
            merge_row(tx, school, Row(student_no=number, name=account["name"], **details))
    tx.execute("INSERT INTO identity_registration_backfill(school_id) VALUES (?)", (school,))


def link_open_account(tx, school, number, name, actor_id):
    """只同步真实新开户结果；导入旧存量时不得覆盖已经变更的登记状态。"""
    row = tx.one("SELECT actor_id,archived,source_status,student_status FROM identity_registrations WHERE school_id=? AND student_no=?",
                 (school, number))
    if not row:
        merge_row(tx, school, Row(student_no=number, name=name))
    elif not row["actor_id"]:
        if row["archived"] or disabled(row):
            raise HTTPException(409, "已归档或学籍受限的名单不能直接开通账号。")
        tx.execute("""UPDATE identity_registrations SET opened=1,actor_id=?,revision=revision+1
                   WHERE school_id=? AND student_no=?""", (actor_id, school, number))
    elif row["actor_id"] != actor_id:
        raise HTTPException(409, "该学号已关联另一身份。")
