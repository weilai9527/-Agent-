"""组织说明字段由身份域持有。辅导员姓名、班级邀请码不能代替实名授权。"""
import json
from fastapi import HTTPException

FIELDS = {"org_colleges": {"code": 64}, "org_programs": {"direction": 160, "coordinator": 120, "standard_major_code": 64},
          "org_classes": {"advisor": 120, "graduation_year": 4, "invite_code": 40}}
SCHEMA = ("""CREATE TABLE IF NOT EXISTS org_unit_details (
             school_id VARCHAR(128) NOT NULL, kind VARCHAR(40) NOT NULL, unit_id VARCHAR(128) NOT NULL,
             code VARCHAR(64), metadata TEXT NOT NULL, PRIMARY KEY(school_id,kind,unit_id), UNIQUE(school_id,kind,code))""",)


def update(tx, school, table, uid, details):
    allowed = FIELDS[table]
    if set(details) - set(allowed):
        raise HTTPException(422, "组织说明包含该层级不支持的字段。")
    data = {}
    for key, raw in details.items():
        value = str(raw or "").strip()
        if len(value) > allowed[key]:
            raise HTTPException(422, "组织说明字段过长。")
        if key == "graduation_year" and value and not (value.isascii() and value.isdigit() and 2000 <= int(value) <= 2100):
            raise HTTPException(422, "毕业年份须在 2000 到 2100 之间。")
        data[key] = value.upper() if key in {"code", "invite_code"} else value
    ids = (school, table, uid)
    existing = tx.one("SELECT metadata FROM org_unit_details WHERE school_id=? AND kind=? AND unit_id=?", ids)
    # 局部修改只覆盖传入字段，缺失键保留历史值；唯一编码同时受学校和组织层级限定。
    merged = {**(json.loads(existing["metadata"]) if existing else {}), **data}
    code = merged.get("code") or merged.get("invite_code") or None
    if code and tx.one("SELECT unit_id FROM org_unit_details WHERE school_id=? AND kind=? AND code=? AND unit_id<>?",
                       (school, table, code, uid)):
        raise HTTPException(409, "本校同层级中已使用该编码。")
    encoded = json.dumps(merged, ensure_ascii=False)
    if existing:
        tx.execute("UPDATE org_unit_details SET code=?,metadata=? WHERE school_id=? AND kind=? AND unit_id=?",
                   (code, encoded, *ids))
    else:
        tx.execute("INSERT INTO org_unit_details (code,metadata,school_id,kind,unit_id) VALUES (?,?,?,?,?)",
                   (code, encoded, *ids))


def attach(tx, school, groups):
    records = {(r["kind"], r["unit_id"]): json.loads(r["metadata"]) for r in tx.all(
        "SELECT kind,unit_id,metadata FROM org_unit_details WHERE school_id=?", (school,))}
    for table, rows in groups.items():
        for row in rows:
            if fields := records.get((table, row.get("class_id") or row["id"])):
                row["details"] = fields


def backfill(tx, school):
    for table, fields in FIELDS.items():
        source = "campus_" + table.removeprefix("org_")
        rows = tx.all("""SELECT a.record_id,a.legacy_record FROM identity_legacy_organization a
                         WHERE a.school_id=? AND a.source_table=? AND NOT EXISTS (
                          SELECT 1 FROM org_unit_details d WHERE d.school_id=a.school_id
                            AND d.kind=? AND d.unit_id=a.record_id)""", (school, source, table))
        for row in rows:
            legacy = json.loads(row["legacy_record"])
            values = {key: legacy[key] for key in fields if legacy.get(key) is not None}
            update(tx, school, table, row["record_id"], values)
