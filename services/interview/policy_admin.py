"""学校面试策略由面试服务维护，创建新面试时冻结当时的配置。"""
import hashlib
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from services.interview.storage import DB_ENGINE, db, one
from services.identity.permissions import legacy_school_id
from shared.interviewer_policy import DEFAULT_POLICY, OPTIONS, load_policy, validate_policy
from shared.service_security import require_service

ACTION = "interview.policy.manage"
router = APIRouter()


def manager(actor=Depends(require_service("interview", ACTION))):
    if (actor["caller"] != "admin-gateway" or actor["actor_type"] != "admin"
            or actor["school_id"] != legacy_school_id()):
        raise HTTPException(403, "School interview policy access denied")
    return actor


def revision(policy):
    value = json.dumps(policy, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


@router.get("/api/admin/interviewer-policy")
def read_policy(actor=Depends(manager)):
    policy = load_policy(db)
    return {"policy": policy, "options": OPTIONS, "revision": revision(policy)}


@router.put("/api/admin/interviewer-policy")
def change_policy(body: dict, actor=Depends(manager)):
    try:
        policy = validate_policy(body.get("policy"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "面试官策略格式或选项无效。") from exc
    if not isinstance(body.get("expected_revision"), str):
        raise HTTPException(422, "请先读取当前策略。")
    new = revision(policy)
    # 首次修改时数据库可能只有默认值，也需要先加写锁。
    # 策略变更和对应的审计记录在同一事务中提交。
    with db:
        if DB_ENGINE == "sqlite":
            db.execute("BEGIN IMMEDIATE").close()
        conflict = ("ON DUPLICATE KEY UPDATE id=id" if DB_ENGINE == "mysql" else "ON CONFLICT(id) DO NOTHING")
        db.execute("INSERT INTO interviewer_policy(id,config) VALUES ('default',?) " + conflict,
                   (json.dumps(DEFAULT_POLICY, ensure_ascii=False),)).close()
        lock = " FOR UPDATE" if DB_ENGINE == "mysql" else ""
        row = one("SELECT config FROM interviewer_policy WHERE id='default'" + lock)
        previous = revision(validate_policy(json.loads(row["config"])))
        if new != previous:
            if body["expected_revision"] != previous:
                raise HTTPException(409, "策略已由其他管理员修改，请重新读取后再保存。")
            db.execute("UPDATE interviewer_policy SET config=? WHERE id='default'",
                       (json.dumps(policy, ensure_ascii=False),)).close()
            db.execute("""INSERT INTO interview_policy_changes
                       (id,school_id,actor_id,old_digest,new_digest) VALUES (?,?,?,?,?)""",
                       (str(uuid4()), actor["school_id"], actor["actor_id"], previous, new)).close()
    return {"policy": policy, "revision": new}
