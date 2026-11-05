"""校内教职工密码、可撤销会话及逐动作授权。"""
import hashlib
import json
import os
import time
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from shared.account_security import create_token, hash_staff_password as hash_password, hash_staff_token as hash_token, is_valid_email, normalize_email, verify_password
from shared.service_security import require_service

from .browser import check_origin, reserve_login
from .session_proxy import client_ip, verify_proxy
from .permissions import ADMIN_ONLY, STAFF_ACTIONS, TEACHER_ONLY, authorize_staff, effective_staff_grants, human_grants

router = APIRouter()
COOKIE = "identity_staff_session"
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS identity_staff (
        school_id VARCHAR(128) NOT NULL, actor_id VARCHAR(128) NOT NULL, email VARCHAR(254) NOT NULL,
        password_hash VARCHAR(255) NOT NULL, name VARCHAR(160) NOT NULL,
        actor_type VARCHAR(16) NOT NULL, status VARCHAR(16) NOT NULL, permissions TEXT NOT NULL,
        school_wide INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(school_id,actor_id), UNIQUE(school_id,email))""",
    """CREATE TABLE IF NOT EXISTS identity_staff_sessions (
        token_hash CHAR(64) PRIMARY KEY, school_id VARCHAR(128) NOT NULL, actor_id VARCHAR(128) NOT NULL,
        expires_at BIGINT NOT NULL,
        FOREIGN KEY(school_id,actor_id) REFERENCES identity_staff(school_id,actor_id) ON DELETE CASCADE)""",
    """CREATE TABLE IF NOT EXISTS identity_legacy_permission_requests (
        school_id VARCHAR(128) NOT NULL, id VARCHAR(128) NOT NULL, actor_id VARCHAR(128) NOT NULL,
        legacy_record TEXT NOT NULL, PRIMARY KEY (school_id,id))""",
)
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[^\s\x00-\x1f\x7f]+$")]


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StaffLogin(Body):
    school_id: Identifier
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)
    new_password: str | None = Field(None, min_length=12, max_length=256)


class Resolve(Body):
    token: str = Field(min_length=1, max_length=128)
    action: Identifier


class GrantEdit(Body):
    permissions: list[Identifier] = Field(max_length=100)
    actor_type: Literal["teacher", "admin"]
    status: Literal["normal", "disabled"] = "normal"
    school_wide: bool = Field(default=False, strict=True)


class ReplaceGrants(GrantEdit):
    # 已有内部调用允许不提供版本；交互式修改应携带读取时的版本。
    expected_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class CreateStaff(GrantEdit):
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=12, max_length=1024)


def require_staff(tx, ctx, action):
    row = tx.one("""SELECT actor_id,actor_type,status,permissions,school_wide FROM identity_staff
                    WHERE school_id=? AND actor_id=? AND actor_type=?""",
                 (ctx["school_id"], ctx["actor_id"], ctx["actor_type"]))
    if not row:
        raise HTTPException(403, "Unknown staff identity")
    authorize_staff(row, action)
    return row


def school_manager(tx, ctx):
    row = require_staff(tx, ctx, "permissions.manage")
    if row["actor_type"] != "admin" or not row["school_wide"]:
        raise HTTPException(403, "School-wide permission administrator required")


def _session(tx, token, school=None):
    if not token or len(token) > 128:
        raise HTTPException(401, "Staff browser session required")
    query = """SELECT a.actor_id,a.school_id,a.email,a.name,a.actor_type,a.permissions,a.status,a.school_wide
               FROM identity_staff_sessions s JOIN identity_staff a
               ON a.school_id=s.school_id AND a.actor_id=s.actor_id
               WHERE s.token_hash=? AND s.expires_at>? AND a.status='normal'"""
    params = (hash_token(token), int(time.time()))
    if school is not None:
        query += " AND s.school_id=?"
        params += (school,)
    row = tx.one(query, params)
    if not row:
        raise HTTPException(401, "Staff browser session expired")
    return row


def public_account(row):
    return {k: row[k] for k in ("actor_id", "school_id", "actor_type", "email", "name")} | {
        "permissions": sorted(effective_staff_grants(row)), "school_wide": bool(row["school_wide"])}


@router.post("/sessions/staff/login", dependencies=[Depends(verify_proxy)])
def login(body: StaffLogin, request: Request, response: Response):
    check_origin(request)
    proxy_school = getattr(request.state, "session_school", None)
    if proxy_school is not None and proxy_school != body.school_id:
        raise HTTPException(403, "Account outside gateway school")
    email = normalize_email(body.email)
    store = request.app.state.store
    reserve_login(store, "staff", body.school_id, email, client_ip(request))
    with store.transaction() as tx:
        account = tx.one("SELECT * FROM identity_staff WHERE school_id=? AND email=?", (body.school_id, email))
    if not account or account["status"] != "normal" or not verify_password(body.password, account["password_hash"]):
        raise HTTPException(401, "Invalid staff credentials")
    token = create_token()
    ttl = 8 * 60 * 60
    with store.transaction(write=True) as tx:
        from .organization import audit, lock_school
        from shared.account_security import validate_new_password

        # 同一学校锁串行处理改密、补发和授权变更。临时口令校验成功后仍不能直接取得会话。
        lock_school(tx, store, body.school_id)
        ids = (body.school_id, account["actor_id"])
        latest = tx.one("SELECT * FROM identity_staff WHERE school_id=? AND actor_id=?", ids)
        if not latest or latest["status"] != "normal" or latest["password_hash"] != account["password_hash"]:
            raise HTTPException(401, "登录凭据已变化。")
        pending = tx.one("SELECT revision FROM identity_staff_password_rotation WHERE school_id=? AND actor_id=?", ids)
        if pending:
            if not body.new_password:
                raise HTTPException(428, "须先修改临时登录密码。")
            if body.new_password == body.password or validate_new_password(body.new_password):
                raise HTTPException(422, "新密码过弱或与临时密码相同。")
            tx.execute("UPDATE identity_staff SET password_hash=? WHERE school_id=? AND actor_id=?",
                       (hash_password(body.new_password), *ids))
            tx.execute("DELETE FROM identity_staff_password_rotation WHERE school_id=? AND actor_id=?", ids)
            tx.execute("DELETE FROM identity_staff_sessions WHERE school_id=? AND actor_id=?", ids)
            audit(tx, latest, "staff.password.change-required", latest["actor_id"])
        elif body.new_password is not None:
            raise HTTPException(409, "强制改密状态已变化，请重新登录。")
        tx.execute("INSERT INTO identity_staff_sessions(token_hash,school_id,actor_id,expires_at) VALUES (?,?,?,?)",
                   (hash_token(token), *ids, int(time.time())+ttl))
        account = latest
        audit(tx, account, "staff.login", account["actor_id"])
    response.set_cookie(COOKIE, token, max_age=ttl, httponly=True, samesite="lax",
                        secure=os.getenv("APP_ENV", "").lower() == "production", path="/")
    return public_account(account)


@router.get("/sessions/staff/me", dependencies=[Depends(verify_proxy)])
def me(request: Request):
    with request.app.state.store.transaction() as tx:
        return public_account(_session(tx, request.cookies.get(COOKIE), getattr(request.state, "session_school", None)))


@router.post("/sessions/staff/logout", dependencies=[Depends(verify_proxy)])
def logout(request: Request, response: Response):
    check_origin(request)
    token = request.cookies.get(COOKIE)
    if token:
        with request.app.state.store.transaction(write=True) as tx:
            proxy_school = getattr(request.state, "session_school", None)
            if proxy_school is not None:
                tx.execute("DELETE FROM identity_staff_sessions WHERE token_hash=? AND school_id=?",
                           (hash_token(token), proxy_school))
            else:
                tx.execute("DELETE FROM identity_staff_sessions WHERE token_hash=?", (hash_token(token),))
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax",
                           secure=os.getenv("APP_ENV", "").lower() == "production")
    return {"ok": True}


@router.post("/internal/sessions/staff/resolve")
def resolve(body: Resolve, request: Request, ctx=Depends(require_service("identity", "identity.session.resolve"))):
    if ctx["actor_type"] != "system" or ctx["actor_id"] != "gateway":
        raise HTTPException(403, "Browser gateway required")
    with request.app.state.store.transaction() as tx:
        row = _session(tx, body.token, ctx["school_id"])
        authorize_staff(row, body.action)
        return {k: row[k] for k in ("actor_id", "actor_type", "school_id")} | {"scopes": [body.action]}


def _grants(body):
    if set(body.permissions).difference(STAFF_ACTIONS):
        raise HTTPException(422, "Unknown permission")
    if body.actor_type == "teacher" and body.school_wide:
        raise HTTPException(422, "Teacher scope must consist of assigned classes")
    return json.dumps(sorted(set(body.permissions)))


def _revision(account):
    # 编辑期间其他管理员可能撤权；只对标准化授权状态生成摘要，避免两种数据库表示差异。
    state = (account["actor_type"], account["status"], bool(account["school_wide"]),
             sorted(human_grants(account["permissions"])))
    return hashlib.sha256(json.dumps(state).encode()).hexdigest()


@router.get("/v1/staff")
def list_staff(request: Request, q: str = Query(default="", max_length=160),
               limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
               ctx=Depends(require_service("identity", "permissions.manage"))):
    condition = "school_id=?"
    params = [ctx["school_id"]]
    if q.strip():
        term = q.strip().lower().replace("!", "!!").replace("%", "!%").replace("_", "!_")
        condition += """ AND (LOWER(name) LIKE ? ESCAPE '!' OR LOWER(email) LIKE ? ESCAPE '!'
                              OR actor_id=?)"""
        params.extend((f"%{term}%", f"%{term}%", q.strip()))
    with request.app.state.store.transaction() as tx:
        school_manager(tx, ctx)
        total = tx.one(f"SELECT COUNT(*) AS n FROM identity_staff WHERE {condition}", tuple(params))["n"]
        rows = tx.all(f"""SELECT actor_id,school_id,name,email,actor_type,status,school_wide,permissions
                          FROM identity_staff WHERE {condition} ORDER BY actor_id LIMIT ? OFFSET ?""",
                      (*params, limit, offset))
    return {"items": [public_account(row) | {"status": row["status"], "revision": _revision(row)} for row in rows],
            "total": total, "offset": offset, "limit": limit, "actions": list(STAFF_ACTIONS),
            "teacher_only": sorted(TEACHER_ONLY), "admin_only": sorted(ADMIN_ONLY)}


@router.post("/v1/staff", status_code=201)
def create_staff(body: CreateStaff, request: Request, ctx=Depends(require_service("identity", "permissions.manage"))):
    from .organization import audit, lock_school
    school, actor_id = ctx["school_id"], str(uuid4())
    email = normalize_email(body.email)
    if not is_valid_email(email):
        raise HTTPException(422, "Invalid email")
    with request.app.state.store.transaction(write=True) as tx:
        lock_school(tx, request.app.state.store, school)
        school_manager(tx, ctx)
        if tx.one("SELECT actor_id FROM identity_staff WHERE school_id=? AND email=?", (school, email)):
            raise HTTPException(409, "Email already assigned within this school")
        tx.execute("""INSERT INTO identity_staff
            (school_id,actor_id,email,name,password_hash,actor_type,status,permissions,school_wide)
            VALUES (?,?,?,?,?,?,?,?,?)""", (school, actor_id, email, body.name, hash_password(body.password),
                                          body.actor_type, body.status, _grants(body), int(body.school_wide)))
        audit(tx, ctx, "staff.create", actor_id, summary=json.dumps(body.model_dump(
            include={"actor_type", "permissions", "school_wide", "status"}), sort_keys=True))
    return {"actor_id": actor_id}


@router.put("/v1/staff/{staff_id}/grants")
def edit_grants(staff_id: str, body: ReplaceGrants, request: Request,
                ctx=Depends(require_service("identity", "permissions.manage"))):
    from .organization import audit, lock_school
    school = ctx["school_id"]
    with request.app.state.store.transaction(write=True) as tx:
        lock_school(tx, request.app.state.store, school)
        school_manager(tx, ctx)
        if staff_id == ctx["actor_id"]:
            raise HTTPException(403, "Cannot replace own grants")
        previous = tx.one("""SELECT actor_type,status,permissions,school_wide FROM identity_staff
                             WHERE school_id=? AND actor_id=?""", (school, staff_id))
        if not previous:
            raise HTTPException(404, "Staff not found")
        if body.expected_revision is not None and body.expected_revision != _revision(previous):
            raise HTTPException(409, "该账号的授权已变更，请重新读取后核对。")
        tx.execute("""UPDATE identity_staff SET actor_type=?,status=?,permissions=?,school_wide=?
                      WHERE school_id=? AND actor_id=?""",
                   (body.actor_type, body.status, _grants(body), int(body.school_wide), school, staff_id))
        tx.execute("DELETE FROM identity_staff_sessions WHERE school_id=? AND actor_id=?", (school, staff_id))
        from .permission_requests import invalidate_pending
        invalidate_pending(tx, school, staff_id)
        previous["permissions"] = sorted(human_grants(previous["permissions"]))
        audit(tx, ctx, "staff.grants.replace", staff_id,
              summary=json.dumps({"before": previous, "after": body.model_dump(exclude={"expected_revision"})}, sort_keys=True))
    return {"ok": True}


@router.get("/v1/legacy-permission-requests")
def legacy_requests(request: Request, ctx=Depends(require_service("identity", "permissions.manage"))):
    with request.app.state.store.transaction() as tx:
        school_manager(tx, ctx)
        rows = tx.all("SELECT legacy_record FROM identity_legacy_permission_requests WHERE school_id=? ORDER BY id",
                      (ctx["school_id"],))
        return {"items": [json.loads(row["legacy_record"]) for row in rows]}
