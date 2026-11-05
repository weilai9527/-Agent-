"""独立的学校职员资料维护和密码补发。每次变更在事务内复核本校实时授权。"""
import hashlib
import json
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from shared.account_security import hash_staff_password as hash_password
from shared.service_security import require_service
from .organization import Identifier, audit, lock_school
from .permissions import ADMIN_ONLY, TEACHER_ONLY, effective_staff_grants
from .staff import Body, require_staff

PROFILE = "staff.profile.write"
RESET = "staff.password.reset"
router = APIRouter(prefix="/v1/staff")
SCHEMA = ("""CREATE TABLE IF NOT EXISTS identity_staff_password_rotation (
    school_id VARCHAR(128) NOT NULL, actor_id VARCHAR(128) NOT NULL, revision CHAR(64) NOT NULL,
    PRIMARY KEY(school_id, actor_id), FOREIGN KEY(school_id,actor_id) REFERENCES identity_staff(school_id,actor_id))""",)


class Expected(Body):
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class Rename(Expected):
    name: str = Field(min_length=1, max_length=160)


def permitted_target(tx, ctx, uid, action):
    operator = require_staff(tx, ctx, action)
    if (ctx["caller"] != "admin-gateway" or operator["actor_type"] != "admin" or not operator["school_wide"]
            or ctx["actor_id"] == uid):
        raise HTTPException(403, "仅全校管理员可办理其他受管职员的事项。")
    target = tx.one("SELECT * FROM identity_staff WHERE school_id=? AND actor_id=?", (ctx["school_id"], uid))
    if not target:
        raise HTTPException(404, "本校没有该职员。")
    valid = effective_staff_grants(target) - (ADMIN_ONLY if target["actor_type"] == "teacher" else TEACHER_ONLY)
    operator_actions = effective_staff_grants(operator) - TEACHER_ONLY
    # 接管密码等同取得目标账号全部权限。不能通过本接口接管权限管理员、学校主管、任课教师的专属权。
    if target["school_wide"] or "permissions.manage" in valid or not valid.issubset(operator_actions):
        raise HTTPException(403, "不能代管同级或持有更高权限的账号。")
    return target


def view(row):
    # 摘要绑定密码摘要和角色权限，不传回密码摘要本身；两名管理员不能基于旧页面反复补发。
    fields = (row["school_id"], row["actor_id"], row["name"], row["password_hash"], row["actor_type"],
              row["permissions"], row["status"], row["email"])
    rev = hashlib.sha256(json.dumps(fields, separators=(",", ":")).encode()).hexdigest()
    return {**{key: row[key] for key in ("actor_id", "name", "email", "status", "actor_type")}, "revision": rev}


def inspect(action):
    def read(staff_id: Identifier, request: Request, ctx=Depends(require_service("identity", action))):
        with request.app.state.store.transaction() as tx:
            return view(permitted_target(tx, ctx, staff_id, action))
    return read


router.add_api_route("/{staff_id}/profile", inspect(PROFILE), methods=["GET"], name="staff.profile.inspect")
router.add_api_route("/{staff_id}/password-reset", inspect(RESET), methods=["GET"], name="staff.reset.inspect")


def current(tx, store, ctx, uid, action, expected):
    lock_school(tx, store, ctx["school_id"])
    target = permitted_target(tx, ctx, uid, action)
    if expected != view(target)["revision"]:
        raise HTTPException(409, "职员资料或授权已变化，请重新核对。")
    return target


@router.patch("/{staff_id}/profile")
def rename(staff_id: Identifier, body: Rename, request: Request, ctx=Depends(require_service("identity", PROFILE))):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "姓名不能为空。")
    store = request.app.state.store
    with store.transaction(write=True) as tx:
        target = current(tx, store, ctx, staff_id, PROFILE, body.expected_revision)
        tx.execute("UPDATE identity_staff SET name=? WHERE school_id=? AND actor_id=?", (name, ctx["school_id"], staff_id))
        audit(tx, ctx, PROFILE, staff_id)
        return view(dict(target, name=name))


@router.post("/{staff_id}/password-reset")
def reissue(staff_id: Identifier, body: Expected, request: Request, ctx=Depends(require_service("identity", RESET))):
    store, ids = request.app.state.store, (ctx["school_id"], staff_id)
    with store.transaction(write=True) as tx:
        target = current(tx, store, ctx, staff_id, RESET, body.expected_revision)
        if target["status"] != "normal":
            raise HTTPException(409, "停用账号不能补发凭据。")
        temporary = secrets.token_urlsafe(22)
        tx.execute("UPDATE identity_staff SET password_hash=? WHERE school_id=? AND actor_id=?", (hash_password(temporary), *ids))
        tx.execute("DELETE FROM identity_staff_sessions WHERE school_id=? AND actor_id=?", ids)
        tx.execute("DELETE FROM identity_staff_password_rotation WHERE school_id=? AND actor_id=?", ids)
        tx.execute("INSERT INTO identity_staff_password_rotation(school_id,actor_id,revision) VALUES (?,?,?)",
                   (*ids, secrets.token_hex(32)))
        audit(tx, ctx, RESET, staff_id)
    return {"temporary_password": temporary}
