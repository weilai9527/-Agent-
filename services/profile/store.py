"""按学校和学生锁定归属行，为简历写入、分析提交和离线导入排序。"""

import hashlib
import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import HTTPException

from services.profile.analysis import build_local_resume_analysis, resume_analysis_source_text
from .fields import FORM_FIELDS, PROFILE_LIMITS, profile_fields


def require_profile_database(db):
    # 在任何 DDL 前用只读事务检查目标结构。旧单体库可能同时残留少量服务表，
    # 不能只靠某张 profile 表存在就判定是独立库。
    owned = {"profile_owners", "profile_versions", "profile_analysis_runs", "profile_school_form_settings",
             "profile_access_audit"}
    sql = ("SELECT name,type AS kind FROM sqlite_master WHERE type IN ('table','view') AND name NOT GLOB 'sqlite_*'"
           if db.engine == "sqlite" else
           "SELECT TABLE_NAME AS name,TABLE_TYPE AS kind FROM information_schema.TABLES "
           "WHERE BINARY TABLE_SCHEMA=BINARY DATABASE()")
    table_type = "table" if db.engine == "sqlite" else "BASE TABLE"
    with db.transaction() as tx:
        # 同名视图也不能代替本域表，尤其不可沿用跨库的 MySQL 定义者权限。
        if any(row["name"] not in owned or row["kind"] != table_type for row in tx.all(sql)):
            raise ValueError("简历服务必须使用空库或已有的独立简历库，请检查部署或迁移目标。")


def ensure_schema(db):
    require_profile_database(db)
    # 签名中的学校和学生编号在 MySQL 也须区分大小写。
    key = "VARCHAR(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin" if db.engine == "mysql" else "TEXT"
    blob = "MEDIUMTEXT" if db.engine == "mysql" else "TEXT"
    db.ensure_schema([
        f"""CREATE TABLE IF NOT EXISTS profile_access_audit (
            id VARCHAR(36) PRIMARY KEY, school_id {key} NOT NULL, actor_id {key} NOT NULL,
            actor_type VARCHAR(16) NOT NULL, student_id {key} NOT NULL, version BIGINT,
            result VARCHAR(16) NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        f"""CREATE TABLE IF NOT EXISTS profile_owners (
            school_id {key} NOT NULL, actor_id {key} NOT NULL, version INTEGER NOT NULL,
            analysis {blob}, PRIMARY KEY(school_id, actor_id))""",
        f"""CREATE TABLE IF NOT EXISTS profile_versions (
            school_id {key} NOT NULL, actor_id {key} NOT NULL, version INTEGER NOT NULL,
            source VARCHAR(16) NOT NULL, created_at VARCHAR(40) NOT NULL,
            profile {blob} NOT NULL, form {blob} NOT NULL,
            PRIMARY KEY(school_id, actor_id, version),
            FOREIGN KEY(school_id, actor_id) REFERENCES profile_owners(school_id, actor_id))""",
        f"""CREATE TABLE IF NOT EXISTS profile_analysis_runs (
            school_id {key} NOT NULL, actor_id {key} NOT NULL,
            claim_id VARCHAR(36) NOT NULL, version INTEGER NOT NULL, policy_key CHAR(64) NOT NULL,
            expires_at BIGINT NOT NULL, PRIMARY KEY(school_id, actor_id),
            FOREIGN KEY(school_id, actor_id) REFERENCES profile_owners(school_id, actor_id))""",
    ])
    db.require_exact_keys("profile")


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def source_hash(profile):
    # 复用旧版哈希命名和材料选择规则，以便识别可用的历史分析。
    source = "direction-ai-v5-catalog-match\n" + resume_analysis_source_text(profile)
    return hashlib.sha256(source.encode()).hexdigest()


def blank(owner):
    school, actor = owner
    return {**dict.fromkeys(PROFILE_LIMITS), "id": str(uuid5(NAMESPACE_URL, encode([school, actor]))),
            "user_id": actor, "resume_filename": None, "created_at": None, "updated_at": None}


OWNER = "school_id=? AND actor_id=?"


@contextmanager
def locked(db, owner):
    with db.transaction(write=True) as tx:
        on_duplicate = ("ON DUPLICATE KEY UPDATE version=version" if db.engine == "mysql" else
                        "ON CONFLICT(school_id,actor_id) DO NOTHING")
        tx.execute(f"INSERT INTO profile_owners(school_id, actor_id, version) VALUES (?,?,0) {on_duplicate}", owner)
        suffix = " FOR UPDATE" if db.engine == "mysql" else ""
        row = tx.one(f"SELECT version,analysis FROM profile_owners WHERE {OWNER}{suffix}", owner)
        yield tx, row


def snapshot(tx, owner, version=None):
    sql = f"SELECT version,source,created_at,profile,form FROM profile_versions WHERE {OWNER}"
    if version is None:
        row = tx.one(sql + " ORDER BY version DESC LIMIT 1", owner)
    else:
        row = tx.one(sql + " AND version=?", (*owner, version))
    if row:
        row["profile"] = json.loads(row["profile"])
        row["form"] = json.loads(row["form"])
    return row


def append(tx, owner, version, source, profile, form):
    timestamp = now()
    tx.execute("""INSERT INTO profile_versions (school_id,actor_id,version,source,created_at,profile,form)
                  VALUES (?,?,?,?,?,?,?)""", (*owner, version, source, timestamp, encode(profile), encode(form)))
    tx.execute(f"UPDATE profile_owners SET version=? WHERE {OWNER}", (version, *owner))


def save(db, owner, source, updates, form=None):
    with locked(db, owner) as (tx, row):
        current = snapshot(tx, owner, row["version"]) or {"profile": blank(owner), "form": {}}
        if source == "profile":
            updates = profile_fields(updates, current["profile"])
        profile = {**current["profile"], **updates}
        new_form = current["form"] if form is None else form
        if row["version"] and current["profile"] == profile and current["form"] == new_form:
            return {"profile": profile, "version": row["version"]}
        profile["updated_at"] = now()
        profile["created_at"] = profile["created_at"] or profile["updated_at"]
        version = row["version"] + 1
        append(tx, owner, version, source, profile, new_form)
        return {"profile": profile, "version": version}


def import_legacy(db, school_id, actor_id, profile, form=None, resume_analysis=None):
    """导入已核验所属学校的学生资料，已有服务端版本时跳过。"""
    if not all(isinstance(k, str) and 0 < len(k) <= 128 and not any(c.isspace() or ord(c)<32 for c in k)
               for k in (school_id, actor_id)):
        raise ValueError("A school and actor are required")
    for item in (profile, form, resume_analysis):
        if item is not None and (not isinstance(item, dict) or item.get("user_id", actor_id) != actor_id
                                 or item.get("school_id", school_id) != school_id):
            raise ValueError("Mismatched legacy owner")
    owner = school_id, actor_id
    fields = blank(owner)
    fields.update({k: v for k, v in (profile or {}).items() if k in fields})
    legacy_form = {k: v for k, v in (form or {}).items() if k in FORM_FIELDS}
    with locked(db, owner) as (tx, row):
        if row["version"]:
            return False
        append(tx, owner, 1, "import", fields, legacy_form)
        if resume_analysis:
            analysis = {k: v for k, v in resume_analysis.items() if k in {
                "id","user_id","source_hash","analysis","provider","status","error_message","created_at","updated_at"
            }}
            analysis["user_id"] = actor_id
            if "analysis" not in analysis and resume_analysis.get("analysis_json"):
                analysis["analysis"] = json.loads(resume_analysis["analysis_json"])
            if not isinstance(analysis.get("analysis"), dict):
                raise ValueError("Malformed legacy analysis")
            # 部分旧库在模型结果旁保存策略指纹，将其随首个版本导入。
            analysis["analysis"] = dict(analysis["analysis"])
            analysis["analysis"].pop("_private_model_policy", None)
            analysis["profile_version"] = 1
            tx.execute(f"UPDATE profile_owners SET analysis=? WHERE {OWNER}", (encode(analysis), *owner))
        return True


def public_analysis(result):
    return {key: value for key, value in result.items() if key != "_policy"} if result else None


def current_for_snapshot(result, current):
    # 未记录版本号的旧分析仍按来源哈希校验。
    return bool(result and current and result.get("source_hash") == source_hash(current["profile"])
                and result.get("profile_version", current["version"]) == current["version"])


def policy_key(plan):
    # 响应中仅保留可公开的分析字段，策略比较使用指纹。
    return hashlib.sha256(plan.cache_key.encode()).hexdigest()


def matches_policy(result, plan):
    # 未带策略指纹的历史结果可用于本地默认模式，显式指定外部模型需重新分析。
    if "_policy" not in result:
        return plan.provider == "local"
    return result["_policy"] == policy_key(plan)


def analysis_state(db, owner):
    from . import model_policy

    with db.transaction() as tx:
        current = snapshot(tx, owner)
        digest = source_hash(current["profile"] if current else {})
        row = tx.one(f"SELECT analysis FROM profile_owners WHERE {OWNER}", owner)
        result = json.loads(row["analysis"]) if row and row["analysis"] else None
    stale = bool(result and not current_for_snapshot(result, current))
    if result and not stale:
        # 即使配置服务不可用也允许学生查看历史结果，重新生成时才返回配置错误。
        try:
            stale = not matches_policy(result, model_policy.select_model(owner[0], "profile"))
        except HTTPException:
            stale = True
    return {"resume_analysis": public_analysis(result), "current_source_hash": digest, "stale": stale}


def analyze(db, owner, force):
    from . import model_policy

    plan = model_policy.select_model(owner[0], "profile")
    key = policy_key(plan)
    claim = str(uuid4())
    with locked(db, owner) as (tx, row):
        version = row["version"]
        current = snapshot(tx, owner, version)
        if not current or not resume_analysis_source_text(current["profile"]):
            raise HTTPException(400, "请先填写简历文本、项目经历或技能标签。")
        profile = current["profile"]
        old = json.loads(row["analysis"]) if row["analysis"] else {}
        # 回退结果可在 GET 中展示，再次请求生成时允许重试已授权的模型。
        if (not force and current_for_snapshot(old, current) and matches_policy(old, plan)
                and ("_policy" not in old or old.get("provider") == plan.provider)):
            return public_analysis(old)
        active = tx.one(f"SELECT * FROM profile_analysis_runs WHERE {OWNER}", owner)
        if active and active["expires_at"] > int(time.time()) and (
                active["version"], active["policy_key"]) == (version, key):
            raise HTTPException(409, "该版本简历正在分析，请稍后重试。")
        # 任务异常退出最多占用五分钟；新简历版本或策略可立即替换旧任务。
        tx.execute(f"DELETE FROM profile_analysis_runs WHERE {OWNER}", owner)
        tx.execute("""INSERT INTO profile_analysis_runs
            (school_id,actor_id,claim_id,version,policy_key,expires_at) VALUES (?,?,?,?,?,?)""",
            (*owner, claim, version, key, int(time.time()) + 300))

    try:
        # 按学校及任务选择模型并构造最小化的出站数据，网络调用期间不持数据库锁。
        generated = model_policy.analyze_profile(plan, profile)
        provider = generated.get("provider")
        if (not isinstance(generated.get("analysis"), dict) or provider not in {plan.provider, "local"}
                or (provider != plan.provider and not generated.get("fallback"))):
            raise HTTPException(502, "简历分析服务返回的结果无效。")
        if policy_key(model_policy.select_model(owner[0], "profile")) != key:
            raise HTTPException(409, "分析期间模型策略已更新，请重新生成。")
        with locked(db, owner) as (tx, row):
            active = tx.one(f"SELECT claim_id FROM profile_analysis_runs WHERE {OWNER}", owner)
            if row["version"] != version or not active or active["claim_id"] != claim:
                raise HTTPException(409, "分析期间简历或模型策略已更新，请重新生成。")
            stamp = now()
            result = {
                "id": old.get("id") or str(uuid4()), "user_id": owner[1], "profile_version": version,
                "source_hash": source_hash(profile), "analysis": generated["analysis"],
                "provider": generated["provider"], "model": generated.get("model"),
                "fallback": bool(generated.get("fallback")), "status": "analyzed",
                "error_message": None, "created_at": old.get("created_at") or stamp,
                "updated_at": stamp, "_policy": key,
            }
            tx.execute(f"UPDATE profile_owners SET analysis=? WHERE {OWNER}", (encode(result), *owner))
            tx.execute(f"DELETE FROM profile_analysis_runs WHERE {OWNER} AND claim_id=?", (*owner, claim))
            return public_analysis(result)
    except Exception:
        # 仅释放本次任务持有的记录，避免旧任务删除新任务的预约。
        with locked(db, owner) as (tx, _):
            tx.execute(f"DELETE FROM profile_analysis_runs WHERE {OWNER} AND claim_id=?", (*owner, claim))
        raise
