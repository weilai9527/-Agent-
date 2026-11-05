"""校内职员申请追加具体操作或任课班级，由本校有权管理员审批。"""
import json
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field

from shared.service_security import require_service
from .organization import CLASS_QUERY, audit, lock_school
from .permissions import ADMIN_ONLY, STAFF_ACTIONS, TEACHER_ONLY, human_grants
from .staff import Body, Identifier, _revision, require_staff, school_manager

router = APIRouter()
SELF = "identity.permissions.self"
MANAGE = "permissions.manage"
SCHEMA = ["""CREATE TABLE IF NOT EXISTS identity_permission_requests (
    school_id VARCHAR(128) NOT NULL, id CHAR(36) NOT NULL, applicant VARCHAR(128) NOT NULL,
    request_key VARCHAR(64) NOT NULL, role VARCHAR(16) NOT NULL, base_revision CHAR(64) NOT NULL,
    actions TEXT NOT NULL, classes TEXT NOT NULL, reason TEXT NOT NULL, status VARCHAR(16) NOT NULL,
    reviewer VARCHAR(128), decision_note TEXT, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_at TIMESTAMP NULL, PRIMARY KEY(school_id,id), UNIQUE(school_id,applicant,request_key))"""]


class Application(Body):
    request_key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    actions: list[Identifier] = Field(default_factory=list, max_length=100)
    classes: list[Identifier] = Field(default_factory=list, max_length=100)
    reason: str = Field(min_length=1, max_length=1000)


class Decision(Body):
    status: Literal["approved", "rejected"]
    note: str = Field(min_length=1, max_length=1000)


def invalidate_pending(tx, school, applicant):
    # 仅凭内容摘要无法识别“授予、撤销、恢复原值”的过程。直接授权变更须在同一学校锁内使待审申请失效。
    tx.execute("""UPDATE identity_permission_requests SET status='stale', decided_at=CURRENT_TIMESTAMP
                  WHERE school_id=? AND applicant=? AND status='pending'""", (school, applicant))


def options(account):
    if account["actor_type"] == "teacher":
        excluded = ADMIN_ONLY | {"usage.read", "usage.configure"}
    else:
        excluded = TEACHER_ONLY | {"report.review"}
    if not account["school_wide"]:
        # 这些操作另需全校管理员身份；申请动作不能自行扩大管理范围或改变角色。
        excluded = excluded | {"permissions.manage", "audit.read", "student.import", "student.reset", "student.status"}
    return set(STAFF_ACTIONS) - excluded - human_grants(account["permissions"])


def check_requested(tx, school, account, actions, classes):
    if not actions and not classes:
        raise HTTPException(422, "请选择权限动作或需要负责的班级。")
    if set(actions) - options(account):
        raise HTTPException(422, "包含已授予或当前身份不可申请的权限。")
    if classes:
        if account["school_wide"]:
            raise HTTPException(422, "全校管理员无需另行申请班级范围。")
        markers = ",".join("?" for _ in classes)
        rows = tx.all(CLASS_QUERY + f" AND c.id IN ({markers})", (school, *classes))
        if {row["class_id"] for row in rows} != set(classes):
            raise HTTPException(422, "申请范围含本校以外或已停用的班级。")
        existing = tx.one(f"""SELECT class_id FROM org_staff_classes WHERE school_id=? AND staff_id=?
                              AND class_id IN ({markers}) LIMIT 1""", (school, account["actor_id"], *classes))
        if existing:
            raise HTTPException(422, "申请范围含已分配的班级。")


def view(row):
    return {**row, "actions": json.loads(row["actions"]), "classes": json.loads(row["classes"])}


@router.get("/v1/me/permission-requests")
def mine(request: Request, offset: int = Query(0, ge=0, le=1_000_000), ctx=Depends(require_service("identity", SELF))):
    with request.app.state.store.transaction() as tx:
        account = require_staff(tx, ctx, SELF)
        items = tx.all("""SELECT * FROM identity_permission_requests WHERE school_id=? AND applicant=?
                          ORDER BY created_at DESC,id DESC LIMIT 51 OFFSET ?""", (ctx["school_id"], ctx["actor_id"], offset))
        return {"school_id": ctx["school_id"], "items": [view(i) for i in items[:50]],
                "has_more": len(items) > 50, "actions": sorted(options(account)), "school_wide": bool(account["school_wide"])}


@router.post("/v1/me/permission-requests")
def apply(body: Application, request: Request, ctx=Depends(require_service("identity", SELF))):
    store, school, applicant = request.app.state.store, ctx["school_id"], ctx["actor_id"]
    actions, classes = sorted(set(body.actions)), sorted(set(body.classes))
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(422, "请填写申请原因。")
    with store.transaction(write=True) as tx:
        lock_school(tx, store, school)
        account = require_staff(tx, ctx, SELF)
        prior = tx.one("SELECT * FROM identity_permission_requests WHERE school_id=? AND applicant=? AND request_key=?",
                       (school, applicant, body.request_key))
        if prior:
            if json.loads(prior["actions"]) != actions or json.loads(prior["classes"]) != classes or prior["reason"] != reason:
                raise HTTPException(409, "该提交标识已用于其他申请。")
            return {"id": prior["id"], "status": prior["status"]}
        check_requested(tx, school, account, actions, classes)
        if tx.one("""SELECT id FROM identity_permission_requests WHERE school_id=? AND applicant=?
                     AND status='pending' LIMIT 1""", (school, applicant)):
            raise HTTPException(409, "已有待审批申请，请先查看处理结果。")
        key = str(uuid4())
        tx.execute("""INSERT INTO identity_permission_requests
            (school_id,id,applicant,request_key,role,base_revision,actions,classes,reason,status)
            VALUES (?,?,?,?,?,?,?,?,?,'pending')""",
            (school, key, applicant, body.request_key, account["actor_type"], _revision(account),
             json.dumps(actions), json.dumps(classes), reason))
        audit(tx, ctx, "staff.permission_request.create", key)
        return {"id": key, "status": "pending"}


@router.get("/v1/permission-requests")
def queue(request: Request, status: str = "pending", offset: int = Query(0, ge=0, le=1_000_000),
          ctx=Depends(require_service("identity", MANAGE))):
    if status not in {"pending", "approved", "rejected", "stale"}:
        raise HTTPException(422, "未知申请状态。")
    with request.app.state.store.transaction() as tx:
        school_manager(tx, ctx)
        items = tx.all("""SELECT r.*,s.name AS applicant_name FROM identity_permission_requests r
                          JOIN identity_staff s ON s.school_id=r.school_id AND s.actor_id=r.applicant
                          WHERE r.school_id=? AND r.status=? ORDER BY r.created_at DESC,r.id DESC
                          LIMIT 51 OFFSET ?""", (ctx["school_id"], status, offset))
        return {"school_id": ctx["school_id"], "items": [view(i) for i in items[:50]], "has_more": len(items) > 50}


@router.post("/v1/permission-requests/{request_id}/decision")
def decide(request_id: str, body: Decision, request: Request, ctx=Depends(require_service("identity", MANAGE))):
    store, school, reviewer = request.app.state.store, ctx["school_id"], ctx["actor_id"]
    note = body.note.strip()
    if not note:
        raise HTTPException(422, "请填写审批意见。")
    with store.transaction(write=True) as tx:
        lock_school(tx, store, school)
        school_manager(tx, ctx)
        row = tx.one("SELECT * FROM identity_permission_requests WHERE school_id=? AND id=?", (school, request_id))
        if not row:
            raise HTTPException(404, "申请不存在。")
        applicant = row["applicant"]
        if reviewer == applicant:
            raise HTTPException(403, "不能审批自己的申请。")
        if row["status"] != "pending":
            if (row["status"], row["reviewer"], row["decision_note"]) == (body.status, reviewer, note):
                return {"id": request_id, "status": body.status}
            raise HTTPException(409, "申请已处理或已失效，请刷新。")
        if body.status == "approved":
            account = tx.one("""SELECT actor_id,actor_type,status,permissions,school_wide FROM identity_staff
                                WHERE school_id=? AND actor_id=?""", (school, applicant))
            if not account or account["status"] != "normal" or _revision(account) != row["base_revision"]:
                raise HTTPException(409, "申请人身份或授权已变化，需要重新申请。")
            actions, classes = json.loads(row["actions"]), json.loads(row["classes"])
            check_requested(tx, school, account, actions, classes)
            if classes:
                require_staff(tx, ctx, "organization.manage")
            # 合并原有授权，保留历史标签原值，仅由身份域解释其含义。
            grants = sorted(set(json.loads(account["permissions"])).union(actions))
            tx.execute("UPDATE identity_staff SET permissions=? WHERE school_id=? AND actor_id=?",
                       (json.dumps(grants), school, applicant))
            for class_id in classes:
                tx.execute("INSERT INTO org_staff_classes (school_id,staff_id,class_id) VALUES (?,?,?)",
                           (school, applicant, class_id))
            tx.execute("DELETE FROM identity_staff_sessions WHERE school_id=? AND actor_id=?", (school, applicant))
        tx.execute("""UPDATE identity_permission_requests SET status=?,reviewer=?,decision_note=?,decided_at=CURRENT_TIMESTAMP
                      WHERE school_id=? AND id=?""", (body.status, reviewer, note, school, request_id))
        audit(tx, ctx, "staff.permission_request." + body.status, request_id,
              summary=json.dumps({"applicant": applicant, "actions": json.loads(row["actions"]), "classes": json.loads(row["classes"])}))
        return {"id": request_id, "status": body.status}
