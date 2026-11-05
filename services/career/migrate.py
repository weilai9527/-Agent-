"""从明确绑定到一所学校的已停写旧库离线迁移。

在启用服务地址前运行。只读访问源库，简历可按学生续传，职业数据在单个事务内提交。
迁移只支持命令行，输出中不包含凭据和简历正文。
"""
import argparse
import json
import os
import re

from shared.service_db import ServiceDatabase

CATALOG_TABLES = (
    "catalog_versions", "catalog_colleges", "catalog_majors", "catalog_training_directions",
    "catalog_employment_directions", "catalog_job_roles", "catalog_competencies",
    "catalog_job_competencies", "catalog_role_permissions", "catalog_job_aliases",
    "catalog_job_suggestions", "catalog_job_suggestion_drafts", "catalog_import_jobs",
    "job_postings", "job_matches", "job_jd_submissions",
)


def columns(tx, engine, table):
    # 表名仅取自代码中的常量，命令行和请求参数不得提供表名。
    if engine == "sqlite":
        if tx.one("SELECT 1 AS found FROM sqlite_master WHERE type='view' AND name=? COLLATE NOCASE", (table,)):
            raise ValueError(f"Unexpected view in migration database: {table}")
        return [r["name"] for r in tx.all(f"PRAGMA table_info({table})")]
    obj = tx.one("SELECT TABLE_TYPE AS kind FROM information_schema.TABLES "
                 "WHERE BINARY TABLE_SCHEMA=BINARY DATABASE() AND BINARY TABLE_NAME=BINARY ?", (table,))
    if obj and obj["kind"] != "BASE TABLE":
        raise ValueError(f"Unexpected view in migration database: {table}")
    return [r["name"] for r in tx.all(
        "SELECT COLUMN_NAME AS name FROM information_schema.COLUMNS "
        "WHERE BINARY TABLE_SCHEMA=BINARY DATABASE() AND BINARY TABLE_NAME=BINARY ? ORDER BY ORDINAL_POSITION", (table,)
    )]


def assert_school(tx, engine, tables, school):
    if (not isinstance(school, str) or not 1 <= len(school) <= 128 or school != os.environ.get("LEGACY_SCHOOL_ID")
            or any(ch.isspace() or ord(ch) < 32 for ch in school)):
        raise ValueError("The operator must explicitly bind the legacy database to this school")
    # 逐个实体表寻找明确的学校标志。少数组织关系表使用复合主键或没有 id；
    # 查验归属不能依赖用于复制数据的 id 分页，也不能依赖源列的大小写排序规则。
    if engine == "sqlite":
        markers = tx.all("""SELECT t.name FROM sqlite_master t
            JOIN pragma_table_info(t.name) c ON lower(c.name)='school_id'
            WHERE t.type='table' AND t.name NOT GLOB 'sqlite_*'""")
        mismatch = "school_id IS NULL OR typeof(school_id)<>'text' OR school_id COLLATE BINARY<>?"
    else:
        markers = tx.all("""SELECT c.TABLE_NAME AS name FROM information_schema.COLUMNS c
            JOIN information_schema.TABLES t ON BINARY t.TABLE_SCHEMA=BINARY c.TABLE_SCHEMA
              AND BINARY t.TABLE_NAME=BINARY c.TABLE_NAME AND t.TABLE_TYPE='BASE TABLE'
            WHERE BINARY c.TABLE_SCHEMA=BINARY DATABASE() AND LOWER(c.COLUMN_NAME)='school_id'""")
        mismatch = "school_id IS NULL OR BINARY school_id<>BINARY ?"
    for marker in markers:
        table = marker["name"]
        if tables is not None and table not in tables:
            continue
        # 表名来自只读元数据；引用时转义标识符里的反引号，学校始终作为参数传入。
        quoted = "`" + table.replace("`", "``") + "`"
        if tx.one(f"SELECT 1 AS mismatch FROM {quoted} WHERE {mismatch} LIMIT 1", (school,)):
            raise ValueError(f"Mixed or unidentified tenants in {table}")


def check_owners(tx, engine, table, *, users_exist, nullable=False):
    # 旧 MySQL 外键可能忽略大小写，迁移时必须精确匹配学生标识以确认归属。
    owner = "r.user_id"
    if users_exist:
        compare = "BINARY u.id=BINARY r.user_id" if engine == "mysql" else "u.id=r.user_id COLLATE BINARY"
        condition = f"NOT EXISTS (SELECT 1 FROM users u WHERE {compare})"
    else:
        condition = "1=1"
    if nullable:
        condition += f" AND {owner} IS NOT NULL"
    if tx.one(f"SELECT 1 AS orphan FROM {table} r WHERE {condition} LIMIT 1"):
        raise ValueError(f"Cannot establish student ownership in {table}")


def pages(tx, table, projection="*"):
    # 键集分页要求游标唯一。来源表偏离历史版本的主键约束时应拒绝迁移，
    # 否则下页会跳过与上页最后一行同 id 的数据。
    if tx.one(f"SELECT 1 AS duplicate FROM {table} GROUP BY id HAVING COUNT(*)>1 LIMIT 1"):
        raise ValueError(f"Non-unique row identifier in {table}")
    if tx.one(f"SELECT 1 AS invalid FROM {table} WHERE id IS NULL OR id='' LIMIT 1"):
        raise ValueError(f"Missing row identifier in {table}")
    return _read_pages(tx, table, projection)


def _read_pages(tx, table, projection):
    last = None
    while True:
        query = f"SELECT {projection} FROM {table}"
        args = ()
        if last is not None:
            query += " WHERE id>?"
            args = (last,)
        rows = tx.all(query + " ORDER BY id LIMIT 250", args)
        if not rows:
            return
        yield rows
        last = rows[-1]["id"]


def profile_copy(source, db, school):
    from services.profile.settings_migrate import copy_from_reader
    from services.profile.store import ensure_schema, import_legacy

    imported = skipped = 0
    with source.transaction() as reader:
        tables = ("users", "profiles", "resume_forms", "resume_analyses")
        assert_school(reader, source.engine, tables, school)
        available = {t for t in tables if columns(reader, source.engine, t)}
        if not {"users", "profiles"} <= available:
            raise ValueError("Missing legacy users or profiles table")
        # 源列可能忽略大小写；已通过归属检查的记录仍须按学生的原始编号精确读取。
        owner_key = "BINARY user_id" if source.engine == "mysql" else "user_id COLLATE BINARY"
        for table in available - {"users"}:
            check_owners(reader, source.engine, table, users_exist=True)
            if reader.one(f"SELECT 1 AS duplicate FROM {table} GROUP BY {owner_key} HAVING COUNT(*)>1 LIMIT 1"):
                raise ValueError(f"Cannot establish a unique student record in {table}")
        user_pages = pages(reader, "users", "id")
        settings_result = copy_from_reader(reader, source.engine, db, school)
        ensure_schema(db)
        for rows in user_pages:
            for row in rows:
                actor = row["id"]
                profile, form, analysis = (
                    reader.one(f"SELECT * FROM {t} WHERE {owner_key}=?", (actor,)) if t in available else None
                    for t in tables[1:]
                )
                if profile or form or analysis:
                    if import_legacy(db, school, actor, profile or {}, form, analysis):
                        imported += 1
                    else:
                        skipped += 1
    result = {"imported": imported, "already_present": skipped}
    if settings_result is not None:
        result["form_settings"] = settings_result
    return result


def check_program_mappings(reader, engine, school):
    fields = columns(reader, engine, "program_job_roles")
    if not fields:
        return []
    required = {"id", "program_id", "job_role_id", "priority"}
    if not required <= set(fields) or set(fields) - required - {"created_at", "school_id"}:
        raise ValueError("不支持的旧专业岗位关联表结构")
    assert_school(reader, engine, ("program_job_roles", "campus_programs", "campus_colleges"), school)
    if reader.one("SELECT id FROM program_job_roles LIMIT 1"):
        if "id" not in columns(reader, engine, "campus_programs"):
            raise ValueError("无法确认旧关联所属专业")
        # 旧 MySQL 库可能忽略大小写，迁移时按真实标识而非显示名称对齐。
        exact = ("BINARY p.id=BINARY m.program_id" if engine == "mysql"
                 else "p.id=m.program_id COLLATE BINARY")
        if reader.one(f"SELECT 1 AS orphan FROM program_job_roles m "
                      f"WHERE NOT EXISTS (SELECT 1 FROM campus_programs p WHERE {exact}) LIMIT 1"):
            raise ValueError("无法确认旧关联所属专业")
    return [field for field in ("id", "program_id", "job_role_id", "priority", "created_at") if field in fields]


def copy_program_mappings(reader, tx, fields):
    # 旧版迁移可能已有职业目录回执。补迁也必须写入空关联表，不能覆盖切换后的人工配置。
    if (tx.one("SELECT id FROM program_job_roles LIMIT 1")
            or tx.one("SELECT program_id FROM career_program_job_state LIMIT 1")):
        raise ValueError("专业岗位关联目标表已使用，无法安全补迁")
    names = ",".join(fields)
    count = 0
    for batch in pages(reader, "program_job_roles", names):
        for row in batch:
            if any(not isinstance(row[k], str) or not 1 <= len(row[k]) <= 128 or
                   any(c.isspace() or ord(c) < 32 for c in row[k]) for k in ("id", "program_id", "job_role_id")):
                raise ValueError("旧专业岗位关联包含无效标识")
            if row["priority"] not in ("recommended", "optional"):
                raise ValueError("旧专业岗位推荐程度无效")
            tx.execute(f"INSERT INTO program_job_roles ({names}) VALUES ({','.join('?' for _ in fields)})",
                       tuple(row[field] for field in fields))
            count += 1
    tx.execute("INSERT INTO career_program_job_state(program_id,revision) SELECT DISTINCT program_id,1 FROM program_job_roles")
    return count


def career_copy(source, db, school):
    from services.career.store import ensure_school, transaction

    counts = {}
    with source.transaction() as reader:
        assert_school(reader, source.engine, None, school)
        source_columns = {t: columns(reader, source.engine, t) for t in CATALOG_TABLES}
        if not any(source_columns.values()):
            raise ValueError("No legacy career tables found")
        users_exist = bool(columns(reader, source.engine, "users"))
        for table in ("job_matches", "job_jd_submissions"):
            if source_columns[table]:
                check_owners(reader, source.engine, table, users_exist=users_exist, nullable=table == "job_jd_submissions")
        mapping_fields = check_program_mappings(reader, source.engine, school)
        ensure_school(school, seed=False)
        db.ensure_schema(["CREATE TABLE IF NOT EXISTS career_legacy_copy "
                          "(id INTEGER PRIMARY KEY, counts_json TEXT NOT NULL)"])
        with transaction(school, write=True) as destination:
            tx = destination.tx
            receipt = tx.one("SELECT counts_json FROM career_legacy_copy WHERE id=1")
            if receipt:
                prior = json.loads(receipt["counts_json"])
                if not mapping_fields or "program_job_roles" in prior:
                    return {"already_imported": prior}
                count = copy_program_mappings(reader, tx, mapping_fields)
                combined = {**prior, "program_job_roles": count}
                tx.execute("UPDATE career_legacy_copy SET counts_json=? WHERE id=1", (json.dumps(combined),))
                return {"already_imported": prior, "imported": {"program_job_roles": count}}
            for table in CATALOG_TABLES:
                if tx.one(f"SELECT id FROM {table} LIMIT 1"):
                    raise ValueError(f"Destination table {table} must be empty before first import")
                fields = [c for c in source_columns[table] if c != "school_id"]
                if not fields:
                    continue
                if not set(fields) <= set(columns(tx, db.engine, table)) or not all(
                        re.fullmatch("[a-z][a-z0-9_]*", c) for c in fields):
                    raise ValueError(f"Unsupported source schema for {table}")
                names = ",".join(f"`{key}`" for key in fields)
                insert = f"INSERT INTO {table} ({names}) VALUES ({','.join('?' for _ in fields)})"
                counts[table] = 0
                for batch in pages(reader, table, names):
                    for r in batch:
                        tx.execute(insert, tuple(r[c] for c in fields))
                    counts[table] += len(batch)
            if mapping_fields:
                counts["program_job_roles"] = copy_program_mappings(reader, tx, mapping_fields)
            tx.execute("INSERT INTO career_legacy_copy (id, counts_json) VALUES (1,?)", (json.dumps(counts),))
    return {"imported": counts}


def migrate(service, school):
    from services.career.store import school_store

    source = ServiceDatabase.from_env("legacy_source")
    db = school_store(school) if service == "career" else ServiceDatabase.from_env("profile")
    if source.engine == "sqlite":
        if not source._path.is_file():
            raise ValueError("Legacy source must be an existing SQLite file")
        if db.engine == "sqlite" and (source._path.resolve() == db._path.resolve()
                                     or db._path.exists() and source._path.samefile(db._path)):
            raise ValueError("Destination must be a separate database")
    elif db.engine == "mysql" and all(source._mysql_options[k] == db._mysql_options[k]
                                      for k in ("host", "port", "database")):
        raise ValueError("Destination must be a separate database")
    if service == "profile-settings":
        # 管理端与候选端使用不同旧库时，可先从管理端快照单独复制设置。
        from services.profile.settings_migrate import copy_from_reader
        with source.transaction() as reader:
            status = copy_from_reader(reader, source.engine, db, school)
        return {"form_settings": status or "empty"}
    return (career_copy if service == "career" else profile_copy)(source, db, school)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=["profile", "profile-settings", "career"])
    parser.add_argument("--school", required=True)
    args = parser.parse_args()
    print(json.dumps(migrate(args.service, args.school), ensure_ascii=False))
