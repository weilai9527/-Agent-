"""学生账号、浏览器会话及网关适配；保留迁入账号编号，所有身份操作显式限定学校。"""
import hashlib
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints

from shared.account_security import validate_new_password
from shared.account_security import (
    create_token, hash_password, hash_student_token as hash_token, is_valid_student_no, normalize_student_no,
    verify_password,
)
from shared.service_security import require_service
from .browser import check_origin, gateway_origins, reserve_login
from .permissions import legacy_school_id
from .session_proxy import client_ip, verify_proxy
from . import student_directory, student_grants
from .student_grants import STUDENT_SCOPES

router = APIRouter()
router.include_router(student_directory.router)
COOKIE = "identity_student_session"
LIFETIME = 7 * 24 * 3600
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS identity_student_credentials (
       school_id VARCHAR(128) NOT NULL, actor_id VARCHAR(128) NOT NULL,
       student_no VARCHAR(80), name VARCHAR(120) NOT NULL, password_hash VARCHAR(255) NOT NULL,
       status VARCHAR(40) NOT NULL, must_change_password INTEGER NOT NULL,
       PRIMARY KEY (school_id, actor_id), UNIQUE (school_id, student_no)
    )""",
    """CREATE TABLE IF NOT EXISTS identity_student_sessions (
       token_hash CHAR(64) PRIMARY KEY, school_id VARCHAR(128) NOT NULL,
       actor_id VARCHAR(128) NOT NULL, expires_at BIGINT NOT NULL,
       FOREIGN KEY (school_id, actor_id) REFERENCES identity_student_credentials(school_id,actor_id)
       ON DELETE CASCADE
    )""",
    *student_grants.SCHEMA,
)

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[^\s\x00-\x1f\x7f]+$")]
StudentNo = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[0-9a-zA-Z_-]{3,40}$")]
Password = Annotated[SecretStr, Field(min_length=1, max_length=256)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    school_id: Identifier
    student_no: StudentNo
    password: Password


class ChangePassword(Input):
    password: Password
    confirm_password: Password


class Resolve(Input):
    token: Annotated[SecretStr, Field(min_length=1, max_length=128)]
    action: Identifier


class ResetPassword(Input):
    temporary_password: Password


class ReplaceStudentGrants(Input):
    expected_revision: int = Field(ge=0, le=2**53 - 1, strict=True)
    scopes: list[Identifier] = Field(max_length=128)


class SetStatus(Input):
    status: Literal["normal", "disabled"]


class NewStudent(Input):
    student_no: StudentNo
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    temporary_password: Password


class StudentImport(Input):
    students: list[NewStudent] = Field(min_length=1, max_length=100)


def _context(actor_id, school_id, action):
    if action not in STUDENT_SCOPES:
        raise HTTPException(403, "Action unavailable to students")
    return {"actor_id": actor_id, "school_id": school_id, "actor_type": "student", "scopes": [action]}


def candidate_gateway_context(request: Request, scope: str):
    from .gateway import resolve_native, session_mode

    if session_mode() == "native":
        if scope not in STUDENT_SCOPES:
            raise HTTPException(403, "Action unavailable to students")
        return resolve_native(request, scope, "student")
    check_origin(request, extra_origins=gateway_origins("student"))
    token = request.cookies.get("interview_session")
    if not token or len(token) > 128:
        raise HTTPException(401, "Student session required")
    # 旧数据库模块导入时会打开连接，只能在显式旧版测试路径内加载。
    from backend.src.database import one
    from shared.security_logging import bind_actor

    school = legacy_school_id()
    # 优先读取来源库的学校列。旧单校库依赖部署绑定，禁止从请求头推断学校。
    user = one("""SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
                  WHERE s.token_hash=? AND s.expires_at>? AND u.status='normal'""",
               (hash_token(token), datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")))
    if not user:
        raise HTTPException(401, "Invalid student session")
    if "school_id" in user and user["school_id"] != school:
        raise HTTPException(403, "Student outside bound school")
    if user["must_change_password"]:
        raise HTTPException(403, "Initial password change required")
    bind_actor(request, user, "student")
    return _context(user["id"], school, scope)


def _secure_cookie():
    return os.environ.get("APP_ENV", "").strip().lower() == "production" or os.getenv("COOKIE_SECURE") == "true"


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _new_session(tx, account, response):
    token = create_token()
    tx.execute("""INSERT INTO identity_student_sessions (token_hash,school_id,actor_id,expires_at)
                  VALUES (?,?,?,?)""", (_token_hash(token), account["school_id"], account["actor_id"],
                                         int(time.time()) + LIFETIME))
    response.set_cookie(COOKIE, token, max_age=LIFETIME, httponly=True, secure=_secure_cookie(), samesite="lax", path="/")


def _account(tx, token, *, school=None, lock=False):
    if token and len(token) <= 128:
        user = tx.one("""SELECT a.* FROM identity_student_sessions s
                         JOIN identity_student_credentials a ON a.school_id=s.school_id AND a.actor_id=s.actor_id
                         WHERE s.token_hash=? AND s.expires_at>? AND a.status='normal'""" + (" FOR UPDATE" if lock else ""),
                      (_token_hash(token), int(time.time())))
        if user:
            if school and user["school_id"] != school:
                raise HTTPException(403, "Student outside bound school")
            return user
    raise HTTPException(401, "Invalid student session")


def _public(account):
    return {"user": {"id": account["actor_id"], "schoolId": account["school_id"], "actorType": "student",
                     "name": account["name"], "studentNo": account["student_no"],
                     "mustChangePassword": bool(account["must_change_password"]), "status": account["status"]}}


@router.post("/sessions/student/login", dependencies=[Depends(verify_proxy)])
def login(body: Login, request: Request, response: Response):
    check_origin(request)
    store = request.app.state.store
    if getattr(request.state, "session_school", body.school_id) != body.school_id:
        raise HTTPException(403, "Student outside bound school")
    reserve_login(store, "student", body.school_id, body.student_no, client_ip(request))
    # 密码校验和创建会话与密码轮换串行，旧密码不能在重置后创建会话。
    lock = " FOR UPDATE" if store.engine == "mysql" else ""
    with store.transaction(write=True) as tx:
        account = tx.one("SELECT * FROM identity_student_credentials WHERE school_id=? AND student_no=?" + lock,
                         (body.school_id, body.student_no))
        if not account or account["school_id"] != body.school_id or account["status"] != "normal":
            raise HTTPException(401, "Invalid credentials or disabled account")
        if not verify_password(body.password.get_secret_value(), account["password_hash"]):
            raise HTTPException(401, "Invalid credentials or disabled account")
        _new_session(tx, account, response)
        from .organization import audit
        audit(tx, account, "student.login", account["actor_id"])
        return _public(account)


@router.get("/sessions/student/me", dependencies=[Depends(verify_proxy)])
def me(request: Request):
    with request.app.state.store.transaction() as tx:
        return _public(_account(tx, request.cookies.get(COOKIE), school=getattr(request.state, "session_school", None)))


@router.post("/sessions/student/change-initial-password", dependencies=[Depends(verify_proxy)])
def change_password(body: ChangePassword, request: Request, response: Response):
    check_origin(request)
    password = body.password.get_secret_value()
    validation = validate_new_password(password, body.confirm_password.get_secret_value())
    if validation:
        raise HTTPException(400, validation)
    with request.app.state.store.transaction(write=True) as tx:
        # 锁定最新账号和会话后执行一次性改密，防止与管理员重置、停用或退出操作交错。
        account = _account(tx, request.cookies.get(COOKIE), school=getattr(request.state, "session_school", None),
                           lock=request.app.state.store.engine == "mysql")
        if not account["must_change_password"]:
            raise HTTPException(409, "Initial password has already been changed")
        if verify_password(password, account["password_hash"]):
            raise HTTPException(400, "Choose a different password")
        ids = (account["school_id"], account["actor_id"])
        changed = tx.execute("""UPDATE identity_student_credentials SET password_hash=?,must_change_password=0
                                WHERE school_id=? AND actor_id=? AND status='normal' AND must_change_password=1
                                AND password_hash=?""", (hash_password(password), *ids, account["password_hash"]))
        if changed != 1:
            raise HTTPException(409, "Credential changed concurrently")
        tx.execute("DELETE FROM identity_student_sessions WHERE school_id=? AND actor_id=?", ids)
        _new_session(tx, account, response)
        from .organization import audit
        audit(tx, account, "student.password.change", account["actor_id"])
        account["must_change_password"] = 0
        return _public(account)


@router.post("/sessions/student/logout", dependencies=[Depends(verify_proxy)])
def logout(request: Request, response: Response):
    check_origin(request)
    token = request.cookies.get(COOKIE)
    if token and len(token) <= 128:
        with request.app.state.store.transaction(write=True) as tx:
            school = getattr(request.state, "session_school", None)
            if school:
                tx.execute("DELETE FROM identity_student_sessions WHERE token_hash=? AND school_id=?", (_token_hash(token), school))
            else:
                tx.execute("DELETE FROM identity_student_sessions WHERE token_hash=?", (_token_hash(token),))
    response.delete_cookie(COOKIE, httponly=True, secure=_secure_cookie(), samesite="lax", path="/")
    return {"ok": True}


resolve_peer = require_service("identity", "identity.session.resolve")


@router.post("/internal/sessions/student/resolve")
def resolve(body: Resolve, request: Request, actor=Depends(resolve_peer)):
    if actor["actor_type"] != "system" or actor["actor_id"] != "gateway":
        raise HTTPException(403, "Session resolution requires a gateway")
    with request.app.state.store.transaction() as tx:
        account = _account(tx, body.token.get_secret_value())
        if account["school_id"] != actor["school_id"] or account["must_change_password"]:
            raise HTTPException(403, "Student outside school or initial password change required")
        _, allowed = student_grants.current(tx, (account["school_id"], account["actor_id"]))
        if body.action not in allowed:
            raise HTTPException(403, "Action not granted to this student")
        return _context(account["actor_id"], account["school_id"], body.action)


@router.get("/internal/students/me")
def internal_student(request: Request, actor=Depends(require_service("identity", "identity.student.read"))):
    """取已认证学生的当前账号状态供下游投影使用。"""
    if actor["actor_type"] != "student":
        raise HTTPException(403, "Student identity required")
    with request.app.state.store.transaction() as tx:
        row = student_directory.student_self(tx, actor)
    if not row or row["status"] != "normal" or row["must_change_password"]:
        raise HTTPException(403, "Student account unavailable")
    return {**row, "must_change_password": False}


def _require_student_manager(tx, actor, action):
    from .staff import require_staff

    staff = require_staff(tx, actor, action)
    if actor["actor_type"] != "admin" or staff["school_wide"] != 1:
        raise HTTPException(403, "Student account management requires a school-wide administrator")


@contextmanager
def _change_account(request, actor, student_id, action, *, summary=None, audit_action=None):
    from .organization import audit, lock_school

    store = request.app.state.store
    ids = (actor["school_id"], student_id)
    with store.transaction(write=True) as tx:
        lock_school(tx, store, actor["school_id"])
        _require_student_manager(tx, actor, action)
        # 先锁账号，再操作会话；登录和管理员写入保持一致的锁顺序。
        lock = " FOR UPDATE" if store.engine == "mysql" else ""
        if not tx.one("SELECT actor_id FROM identity_student_credentials WHERE school_id=? AND actor_id=?" + lock, ids):
            raise HTTPException(404, "Student account not found")
        yield tx, ids
        tx.execute("DELETE FROM identity_student_sessions WHERE school_id=? AND actor_id=?", ids)
        audit(tx, actor, audit_action or action, student_id, summary=summary)


@router.get("/v1/students/{student_id}/grants")
def read_student_grants(student_id: Identifier, request: Request,
                        actor=Depends(require_service("identity", "permissions.manage"))):
    ids = (actor["school_id"], student_id)
    with request.app.state.store.transaction() as tx:
        _require_student_manager(tx, actor, "permissions.manage")
        if not tx.one("SELECT actor_id FROM identity_student_credentials WHERE school_id=? AND actor_id=?", ids):
            raise HTTPException(404, "Student account not found")
        revision, scopes = student_grants.current(tx, ids)
        return student_grants.response(ids, revision, scopes)


@router.put("/v1/students/{student_id}/grants")
def replace_student_grants(student_id: Identifier, body: ReplaceStudentGrants, request: Request,
                           actor=Depends(require_service("identity", "permissions.manage"))):
    scopes = sorted(set(body.scopes))
    version = body.expected_revision + 1
    summary = json.dumps({"revision": version, "scopes": scopes})
    with _change_account(request, actor, student_id, "permissions.manage",
                         audit_action="student.grants.replace", summary=summary) as (tx, ids):
        if set(scopes).difference(STUDENT_SCOPES):
            raise HTTPException(422, "Invalid student action")
        current_revision, _ = student_grants.current(tx, ids)
        if current_revision != body.expected_revision:
            raise HTTPException(409, "Student grants changed; reload before editing")
        if current_revision == 0:
            tx.execute("INSERT INTO identity_student_grants (school_id,actor_id,revision,scopes) VALUES (?,?,?,?)",
                       (*ids, version, json.dumps(scopes)))
        else:
            tx.execute("UPDATE identity_student_grants SET revision=?,scopes=? WHERE school_id=? AND actor_id=?",
                       (version, json.dumps(scopes), *ids))
    return student_grants.response(ids, version, scopes)


@router.post("/v1/students/{student_id}/reset-password")
def reset_password(student_id: Identifier, body: ResetPassword, request: Request,
                   actor=Depends(require_service("identity", "student.reset"))):
    with _change_account(request, actor, student_id, "student.reset") as (tx, ids):
        password = body.temporary_password.get_secret_value()
        validation = validate_new_password(password)
        if validation:
            raise HTTPException(422, validation)
        tx.execute("""UPDATE identity_student_credentials SET password_hash=?,must_change_password=1
                      WHERE school_id=? AND actor_id=?""", (hash_password(password), *ids))
    return {"ok": True}


@router.patch("/v1/students/{student_id}/status")
def set_status(student_id: Identifier, body: SetStatus, request: Request,
               actor=Depends(require_service("identity", "student.status"))):
    with _change_account(request, actor, student_id, "student.status", summary=body.status) as (tx, ids):
        if body.status == "normal" and tx.one(
                "SELECT 1 FROM identity_registrations WHERE school_id=? AND actor_id=? AND opened=0", ids):
            raise HTTPException(409, "请通过登记名单重新开通已撤销账号。")
        tx.execute("UPDATE identity_student_credentials SET status=? WHERE school_id=? AND actor_id=?", (body.status, *ids))
    return {"ok": True}


import_peer = require_service("identity", "student.import")


@router.post("/students/import", status_code=201)
def import_students(body: StudentImport, request: Request, actor=Depends(import_peer)):
    from .organization import audit, lock_school

    school = actor["school_id"]
    result = []
    with request.app.state.store.transaction(write=True) as tx:
        lock_school(tx, request.app.state.store, actor["school_id"])
        _require_student_manager(tx, actor, "student.import")
        for row in body.students:
            password = row.temporary_password.get_secret_value()
            validation = validate_new_password(password)
            if validation:
                raise HTTPException(422, validation)
            if tx.one("SELECT actor_id FROM identity_student_credentials WHERE school_id=? AND student_no=?",
                      (school, row.student_no)):
                raise HTTPException(409, "A student number already exists")
            actor_id = str(uuid4())
            tx.execute("""INSERT INTO identity_student_credentials
                (school_id,actor_id,student_no,name,password_hash,status,must_change_password)
                VALUES (?,?,?,?,?,'normal',1)""", (school, actor_id, row.student_no, row.name, hash_password(password)))
            from .registrations import link_open_account
            link_open_account(tx, school, row.student_no, row.name, actor_id)
            audit(tx, actor, "student.import", actor_id)
            result.append({"student_no": row.student_no, "actor_id": actor_id})
    return {"students": result}


def migrate_legacy(tx, source, school_id):
    """离线复制稳定账号编号，重跑保留原生改密结果。有学校标签的来源行须与部署绑定一致；无学号的历史引用保留但不能用于登录。"""
    if school_id != legacy_school_id():
        raise ValueError("Source school differs from LEGACY_SCHOOL_ID")
    created = 0
    for account in source.all("SELECT * FROM users"):
        if "school_id" in account and account["school_id"] != school_id:
            raise ValueError("Source user outside bound school")
        number = normalize_student_no(account.get("student_no")) or None
        if number and not is_valid_student_no(number):
            raise ValueError("Invalid legacy student number")
        existing = tx.one("SELECT student_no FROM identity_student_credentials WHERE school_id=? AND actor_id=?",
                          (school_id, account["id"]))
        if existing:
            if existing["student_no"] != number:
                raise ValueError("Legacy student identity conflict")
            continue
        tx.execute("""INSERT INTO identity_student_credentials
                    (school_id,actor_id,student_no,name,password_hash,status,must_change_password)
                    VALUES (?,?,?,?,?,?,?)""", (school_id, account["id"], number, account["name"],
                    account["password_hash"], account["status"], account["must_change_password"]))
        created += 1
    return created
