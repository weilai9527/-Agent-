"""按学校保存管理员维护的学院、专业补充选项，版本号用于防止并发覆盖。"""

import json

from fastapi import HTTPException

from .store import require_profile_database


def ensure_schema(db):
    require_profile_database(db)
    # 签名中的学校标识区分大小写；MySQL 的默认字符排序不能用于租户键。
    school = "VARCHAR(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin" if db.engine == "mysql" else "TEXT"
    blob = "MEDIUMTEXT CHARACTER SET utf8mb4" if db.engine == "mysql" else "TEXT"
    db.ensure_schema([f"""CREATE TABLE IF NOT EXISTS profile_school_form_settings (
        school_id {school} PRIMARY KEY, revision BIGINT NOT NULL, colleges {blob} NOT NULL,
        updated_by VARCHAR(128), updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"""])
    db.require_exact_keys("profile-settings")


def _label(value):
    if not isinstance(value, str):
        raise ValueError("选项名称和编号必须为文本。")
    value = value.strip()
    if not 1 <= len(value) <= 160 or any(ord(ch) < 32 or 0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        raise ValueError("选项名称和编号须为一至 160 字的有效文本。")
    return value


def _option(raw, *, legacy_ids=False):
    if not isinstance(raw, dict):
        raise ValueError("学院和专业必须为对象。")
    name = _label(raw.get("name"))
    value = raw.get("id")
    if legacy_ids and type(value) is int:
        value = str(value)
    return {"id": name if value is None or value == "" else _label(value), "name": name}


def _unique(options):
    for key in ("id", "name"):
        if len({item[key] for item in options}) != len(options):
            raise ValueError("同一级的名称和编号不能重复。")


def normalize(colleges, *, manual, legacy_ids=False):
    if not isinstance(colleges, list) or len(colleges) > (200 if manual else 5000):
        raise ValueError("学院列表格式或数量不正确。")
    result = []
    for item in colleges:
        college = _option(item, legacy_ids=legacy_ids)
        majors = item.get("majors", [])
        if majors is None and (manual or legacy_ids):
            majors = []
        if not isinstance(majors, list) or len(majors) > (500 if manual else 10000):
            raise ValueError("专业列表格式或数量不正确。")
        college["majors"] = [_option(major, legacy_ids=legacy_ids) for major in majors]
        if manual:
            _unique(college["majors"])
        result.append(college)
    if manual:
        _unique(result)
    return result


def read(db, school):
    with db.transaction() as tx:
        row = tx.one("SELECT revision,colleges FROM profile_school_form_settings WHERE school_id=?", (school,))
    return {"school_id": school, "revision": row["revision"] if row else 0,
            "colleges": json.loads(row["colleges"]) if row else []}


def replace(db, school, actor, colleges, *, expected_revision=None, import_only=False):
    encoded = json.dumps(colleges, ensure_ascii=False, separators=(",", ":"))
    mysql = db.engine == "mysql"
    with db.transaction(write=True) as tx:
        # 先创建（或锁定）学校行，首个 PUT 与历史导入不会争抢同一初始版本。
        conflict = "ON DUPLICATE KEY UPDATE revision=revision" if mysql else "ON CONFLICT(school_id) DO NOTHING"
        tx.execute(f"INSERT INTO profile_school_form_settings(school_id,revision,colleges) VALUES (?,0,'[]') {conflict}", (school,))
        row = tx.one("SELECT revision,colleges FROM profile_school_form_settings WHERE school_id=?" +
                     (" FOR UPDATE" if mysql else ""), (school,))
        revision = row["revision"]
        if import_only and revision:
            return False
        if expected_revision is not None and revision != expected_revision:
            raise HTTPException(409, "学院配置已被修改，请重新载入后再保存。")
        if not revision or row["colleges"] != encoded:
            revision += 1
            tx.execute("""UPDATE profile_school_form_settings SET colleges=?,revision=?,updated_by=?,
                          updated_at=CURRENT_TIMESTAMP WHERE school_id=?""", (encoded,revision,actor,school))
    if import_only:
        return True
    return {"ok": True, "school_id": school, "revision": revision, "colleges": colleges}
