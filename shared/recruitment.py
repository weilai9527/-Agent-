"""招聘信息库与“简历 ↔ 招聘岗位”对比的共享数据层与规则引擎。

该模块被候选人后端（backend）与管理后端（admin_backend）共同引用：
- 管理后端负责招聘岗位的增删改查、Excel 导入导出与第三方同步占位；
- 候选人后端负责调用规则引擎生成对比结果，并把结果落库；
- 双方共用同一套表结构，因此建表语句集中在这里。
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4


POSTING_STATUSES = {"active", "disabled"}
MATCH_SOURCES = {"library", "pasted"}
JD_SUBMISSION_STATUSES = {"pending", "approved", "rejected"}

TEXT_LIMITS = {
    "title": 160,
    "company": 160,
    "job_category": 120,
    "city": 120,
    "graduation_year": 60,
    "employment_type": 60,
    "salary": 120,
    "education_requirement": 120,
    "experience_requirement": 120,
    "deadline": 120,
    "description": 20000,
    "requirements": 20000,
    "skills": 2000,
    "tags": 1000,
    "catalog_job_role_id": 64,
    "catalog_job_name": 160,
    "source_ref": 255,
}

# 常见岗位技能词典：键为归一化展示名，值为可用于匹配的别名。
SKILL_LEXICON: dict[str, tuple[str, ...]] = {
    "Java": ("java",),
    "JavaScript": ("javascript", "js", "es6"),
    "TypeScript": ("typescript", "ts"),
    "Python": ("python",),
    "Go": ("golang", "go语言"),
    "C++": ("c++",),
    "C#": ("c#",),
    "PHP": ("php",),
    "Rust": ("rust",),
    "Kotlin": ("kotlin",),
    "Swift": ("swift",),
    "Spring": ("spring", "springboot", "spring boot"),
    "Spring Cloud": ("spring cloud", "springcloud"),
    "MyBatis": ("mybatis",),
    "Django": ("django",),
    "Flask": ("flask",),
    "FastAPI": ("fastapi",),
    "Node.js": ("node.js", "nodejs", "node"),
    "React": ("react", "react.js"),
    "Vue": ("vue", "vue.js", "vue3"),
    "Angular": ("angular",),
    "小程序开发": ("小程序", "微信小程序"),
    "HTML/CSS": ("html", "css"),
    "MySQL": ("mysql",),
    "PostgreSQL": ("postgresql", "postgres", "pg"),
    "Oracle": ("oracle",),
    "SQL Server": ("sql server", "sqlserver"),
    "Redis": ("redis",),
    "MongoDB": ("mongodb", "mongo"),
    "Elasticsearch": ("elasticsearch", "es搜索"),
    "Kafka": ("kafka",),
    "RabbitMQ": ("rabbitmq",),
    "Docker": ("docker",),
    "Kubernetes": ("kubernetes", "k8s"),
    "Linux": ("linux", "unix"),
    "Shell": ("shell", "bash"),
    "Git": ("git",),
    "Jenkins": ("jenkins",),
    "CI/CD": ("ci/cd", "cicd", "持续集成"),
    "Nginx": ("nginx",),
    "微服务": ("微服务", "microservice"),
    "分布式系统": ("分布式", "distributed"),
    "高并发": ("高并发", "并发编程", "高可用"),
    "性能优化": ("性能优化", "性能调优"),
    "数据结构与算法": ("数据结构", "算法", "leetcode"),
    "设计模式": ("设计模式", "design pattern"),
    "软件测试": ("软件测试", "单元测试", "自动化测试"),
    "机器学习": ("机器学习", "machine learning"),
    "深度学习": ("深度学习", "deep learning"),
    "计算机视觉": ("计算机视觉", "cv算法", "图像处理"),
    "自然语言处理": ("自然语言处理", "nlp"),
    "大语言模型": ("大语言模型", "llm", "大模型"),
    "数据分析": ("数据分析", "data analysis"),
    "数据挖掘": ("数据挖掘", "data mining"),
    "SQL": ("sql",),
    "Tableau": ("tableau",),
    "Power BI": ("power bi", "powerbi"),
    "Excel": ("excel",),
    "项目管理": ("项目管理", "project management"),
    "需求分析": ("需求分析", "需求调研"),
    "产品设计": ("产品设计", "产品规划"),
    "Axure": ("axure",),
    "Figma": ("figma",),
    "UI设计": ("ui设计", "视觉设计", "交互设计"),
    "Photoshop": ("photoshop", "ps"),
    "网络安全": ("网络安全", "信息安全", "渗透测试"),
    "运维": ("运维", "系统运维"),
    "嵌入式": ("嵌入式", "单片机", "stm32"),
    "PLC": ("plc",),
    "AutoCAD": ("autocad", "cad"),
    "SolidWorks": ("solidworks",),
    "英语": ("英语", "cet-4", "cet4", "cet-6", "cet6", "四级", "六级"),
    "沟通表达": ("沟通", "表达", "汇报"),
    "团队协作": ("团队协作", "团队合作", "协作"),
    "学习能力": ("学习能力", "快速学习", "自驱"),
    "抗压能力": ("抗压", "责任心"),
}

_ASCII_ALIAS = re.compile(r"[a-z0-9+#./\- _]+")
_REQUIREMENT_SPLIT = re.compile(r"[\n\r]+|[；;。]+")
_REQUIREMENT_PREFIX = re.compile(r"^\s*(?:[-•·*●○]|\(?\d{1,2}\)?\s*[、.．)）]?)\s*")
_ASCII_TOKEN = re.compile(r"[a-z][a-z0-9+#.]{1,}")


def _id() -> str:
    return str(uuid4())


def _close(cursor: Any) -> None:
    if cursor is not None:
        cursor.close()


def _execute(db: Any, sql: str, params: tuple = ()) -> None:
    _close(db.execute(sql, params))


def _one(db: Any, sql: str, params: tuple = ()) -> dict | None:
    cursor = db.execute(sql, params)
    try:
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        cursor.close()


def _all(db: Any, sql: str, params: tuple = ()) -> list[dict]:
    cursor = db.execute(sql, params)
    try:
        return [dict(row) for row in cursor.fetchall()]
    finally:
        cursor.close()


def _schema_sql(engine: str) -> list[str]:
    if engine == "sqlite":
        entity = "TEXT"
        short = "TEXT"
        text = "TEXT"
        integer = "INTEGER"
        timestamp = "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
        timestamp_null = "TEXT"
        suffix = ""
    else:
        entity = "VARCHAR(36)"
        short = "VARCHAR(255)"
        text = "MEDIUMTEXT"
        integer = "INT"
        timestamp = "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
        timestamp_null = "DATETIME NULL"
        suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"

    return [
        f"""
        CREATE TABLE IF NOT EXISTS job_postings (
          id {entity} PRIMARY KEY,
          title {short} NOT NULL,
          company {short},
          job_category {short},
          city {short},
          graduation_year {short},
          employment_type {short},
          salary {short},
          education_requirement {short},
          experience_requirement {short},
          headcount {integer} NOT NULL DEFAULT 0,
          deadline {short},
          description {text},
          requirements {text},
          skills {text},
          tags {text},
          source {short} NOT NULL DEFAULT 'manual',
          source_ref {short},
          catalog_job_role_id {entity},
          catalog_job_name {short},
          status {short} NOT NULL DEFAULT 'active',
          published {integer} NOT NULL DEFAULT 1,
          sort_order {integer} NOT NULL DEFAULT 0,
          created_by {short},
          created_at {timestamp},
          updated_at {timestamp}
        ){suffix}
        """,
        f"""
        CREATE TABLE IF NOT EXISTS job_matches (
          id {entity} PRIMARY KEY,
          user_id {entity} NOT NULL,
          student_name {short},
          student_no {short},
          student_college {short},
          job_posting_id {entity},
          job_title {short},
          company {short},
          source {short} NOT NULL DEFAULT 'library',
          jd_text {text},
          resume_hash {short},
          match_score {integer} NOT NULL DEFAULT 0,
          result_json {text},
          provider {short},
          model {short},
          status {short} NOT NULL DEFAULT 'completed',
          error_message {text},
          created_at {timestamp},
          updated_at {timestamp}
        ){suffix}
        """,
        f"""
        CREATE TABLE IF NOT EXISTS job_jd_submissions (
          id {entity} PRIMARY KEY,
          user_id {entity},
          student_name {short},
          student_no {short},
          student_college {short},
          job_title {short},
          company {short},
          jd_text {text},
          status {short} NOT NULL DEFAULT 'pending',
          review_note {short},
          job_posting_id {entity},
          decided_by {short},
          decided_at {timestamp_null},
          created_at {timestamp},
          updated_at {timestamp}
        ){suffix}
        """,
    ]


def _table_columns(db: Any, table: str, engine: str) -> set[str]:
    if engine == "sqlite":
        return {str(row.get("name")) for row in _all(db, f"PRAGMA table_info({table})")}
    rows = _all(
        db,
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ?",
        (table,),
    )
    return {str(row.get("COLUMN_NAME") or "") for row in rows}


def ensure_recruitment_schema(db: Any, engine: str) -> None:
    for statement in _schema_sql(engine):
        _execute(db, statement)

    # 兼容升级：老库缺失的列在此补齐。
    short = "TEXT" if engine == "sqlite" else "VARCHAR(255)"
    for column in ("student_name", "student_no", "student_college"):
        if column not in _table_columns(db, "job_matches", engine):
            _execute(db, f"ALTER TABLE job_matches ADD COLUMN {column} {short}")

    indexes = [
        ("idx_job_postings_status", "job_postings", "status"),
        ("idx_job_postings_category", "job_postings", "job_category"),
        ("idx_job_postings_source_ref", "job_postings", "source, source_ref"),
        ("idx_job_matches_user", "job_matches", "user_id"),
        ("idx_job_matches_posting", "job_matches", "job_posting_id"),
        ("idx_job_matches_created", "job_matches", "created_at"),
        ("idx_jd_submissions_status", "job_jd_submissions", "status"),
        ("idx_jd_submissions_user", "job_jd_submissions", "user_id"),
    ]
    for name, table, columns in indexes:
        try:
            _execute(db, f"CREATE INDEX {name} ON {table} ({columns})")
        except Exception as exc:
            message = str(exc).lower()
            if "exist" not in message and "duplicate" not in message:
                raise


# ---------------------------------------------------------------------------
# 招聘岗位：读写
# ---------------------------------------------------------------------------

def _clean_text(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _clean_multiline(value: Any, limit: int) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return text[:limit]


def normalize_posting_payload(payload: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
    current = current or {}
    data: dict[str, Any] = {}
    for field, limit in TEXT_LIMITS.items():
        if field in {"description", "requirements"}:
            raw = payload.get(field, current.get(field)) or ""
            data[field] = _clean_multiline(raw, limit)
        else:
            raw = payload.get(field, current.get(field)) or ""
            data[field] = _clean_text(raw, limit)

    headcount_raw = payload.get("headcount", current.get("headcount", 0))
    try:
        headcount = int(headcount_raw or 0)
    except (TypeError, ValueError):
        headcount = 0
    data["headcount"] = max(0, min(100000, headcount))

    sort_raw = payload.get("sort_order", current.get("sort_order", 0))
    try:
        sort_order = int(sort_raw or 0)
    except (TypeError, ValueError):
        sort_order = 0
    data["sort_order"] = max(0, min(100000, sort_order))

    published_raw = payload.get("published", current.get("published", 1))
    data["published"] = 0 if str(published_raw).lower() in {"0", "false", "no"} else 1

    status = str(payload.get("status", current.get("status") or "active")).strip().lower()
    data["status"] = status if status in POSTING_STATUSES else "active"

    source = str(payload.get("source", current.get("source") or "manual")).strip().lower() or "manual"
    data["source"] = source[:80]
    return data


def serialize_job_posting(row: dict | None) -> dict | None:
    if not row:
        return None
    skills_text = str(row.get("skills") or "")
    tags_text = str(row.get("tags") or "")
    return {
        **row,
        "headcount": int(row.get("headcount") or 0),
        "published": bool(row.get("published")),
        "skillsText": skills_text,
        "tagsText": tags_text,
        "skillList": split_terms(skills_text),
        "tagList": split_terms(tags_text),
    }


def split_terms(value: Any, limit: int = 40) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        parts = [str(item) for item in value]
    else:
        parts = re.split(r"[,，、;；|/\n]+", str(value))
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        item = part.strip()
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result[:limit]


def list_job_postings(
    db: Any,
    *,
    keyword: str | None = None,
    status: str | None = None,
    published_only: bool = False,
    limit: int = 500,
) -> list[dict]:
    clauses: list[str] = []
    params: list[Any] = []
    if published_only:
        clauses.append("published = 1 AND status = 'active'")
    elif status:
        clauses.append("status = ?")
        params.append(status)
    if keyword:
        pattern = f"%{keyword.strip()}%"
        clauses.append("(title LIKE ? OR company LIKE ? OR job_category LIKE ? OR city LIKE ?)")
        params.extend([pattern, pattern, pattern, pattern])
    sql = "SELECT * FROM job_postings"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY sort_order ASC, updated_at DESC LIMIT ?"
    params.append(max(1, min(2000, int(limit))))
    return [serialize_job_posting(row) for row in _all(db, sql, tuple(params))]


def get_job_posting(db: Any, posting_id: str) -> dict | None:
    return serialize_job_posting(_one(db, "SELECT * FROM job_postings WHERE id = ?", (posting_id,)))


def find_job_posting_by_source_ref(db: Any, source: str, source_ref: str) -> dict | None:
    if not source_ref:
        return None
    return serialize_job_posting(
        _one(db, "SELECT * FROM job_postings WHERE source = ? AND source_ref = ?", (source, source_ref))
    )


def create_job_posting(db: Any, payload: dict[str, Any], created_by: str | None = None) -> dict:
    data = normalize_posting_payload(payload)
    if not data["title"]:
        raise ValueError("招聘岗位名称不能为空。")
    posting_id = _id()
    columns = list(data.keys())
    _execute(
        db,
        f"INSERT INTO job_postings (id, created_by, {', '.join(columns)}) "
        f"VALUES (?, ?, {', '.join('?' for _ in columns)})",
        (posting_id, _clean_text(created_by, 255) or None, *[data[column] for column in columns]),
    )
    return get_job_posting(db, posting_id) or {}


def update_job_posting(db: Any, posting_id: str, payload: dict[str, Any]) -> dict | None:
    current = _one(db, "SELECT * FROM job_postings WHERE id = ?", (posting_id,))
    if not current:
        return None
    data = normalize_posting_payload(payload, current)
    if not data["title"]:
        raise ValueError("招聘岗位名称不能为空。")
    assignments = ", ".join(f"{column} = ?" for column in data)
    _execute(
        db,
        f"UPDATE job_postings SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (*[data[column] for column in data], posting_id),
    )
    return get_job_posting(db, posting_id)


def delete_job_posting(db: Any, posting_id: str) -> bool:
    cursor = db.execute("DELETE FROM job_postings WHERE id = ?", (posting_id,))
    affected = getattr(cursor, "rowcount", 0)
    _close(cursor)
    return bool(affected)


def upsert_job_posting_by_source(
    db: Any,
    payload: dict[str, Any],
    *,
    source: str,
    source_ref: str,
    created_by: str | None = None,
) -> tuple[dict, str]:
    """按来源去重写入，返回 (岗位, 'created' | 'updated')。"""
    existing = find_job_posting_by_source_ref(db, source, source_ref)
    merged = {**(payload or {}), "source": source, "source_ref": source_ref}
    if existing:
        updated = update_job_posting(db, existing["id"], merged)
        return (updated or existing), "updated"
    return create_job_posting(db, merged, created_by), "created"


# ---------------------------------------------------------------------------
# 对比记录：读写
# ---------------------------------------------------------------------------

def serialize_job_match(row: dict | None, *, include_result: bool = True) -> dict | None:
    if not row:
        return None
    result: dict[str, Any] = {}
    if include_result:
        try:
            result = json.loads(row.get("result_json") or "{}")
        except (TypeError, ValueError):
            result = {}
    return {
        "id": row.get("id"),
        "user_id": row.get("user_id"),
        "student_name": row.get("student_name"),
        "student_no": row.get("student_no"),
        "student_college": row.get("student_college"),
        "job_posting_id": row.get("job_posting_id"),
        "job_title": row.get("job_title"),
        "company": row.get("company"),
        "source": row.get("source"),
        "resume_hash": row.get("resume_hash"),
        "match_score": int(row.get("match_score") or 0),
        "provider": row.get("provider"),
        "model": row.get("model"),
        "status": row.get("status"),
        "error_message": row.get("error_message"),
        "result": result,
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


_MATCH_SELECT = "SELECT * FROM job_matches AS m"


def create_job_match(
    db: Any,
    *,
    user_id: str,
    job_posting_id: str | None,
    job_title: str,
    company: str,
    source: str,
    jd_text: str,
    resume_hash: str,
    match_score: int,
    result: dict[str, Any],
    student_name: str = "",
    student_no: str = "",
    student_college: str = "",
    provider: str | None = None,
    model: str | None = None,
    status: str = "completed",
    error_message: str | None = None,
) -> dict:
    match_id = _id()
    _execute(
        db,
        """
        INSERT INTO job_matches (
          id, user_id, student_name, student_no, student_college,
          job_posting_id, job_title, company, source, jd_text, resume_hash,
          match_score, result_json, provider, model, status, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            match_id,
            user_id,
            _clean_text(student_name, 160),
            _clean_text(student_no, 80),
            _clean_text(student_college, 160),
            job_posting_id,
            _clean_text(job_title, 160),
            _clean_text(company, 160),
            source if source in MATCH_SOURCES else "library",
            _clean_multiline(jd_text, 20000),
            _clean_text(resume_hash, 128),
            max(0, min(100, int(match_score))),
            json.dumps(result, ensure_ascii=False),
            _clean_text(provider, 80) or None,
            _clean_text(model, 160) or None,
            status[:32],
            _clean_multiline(error_message, 2000) or None,
        ),
    )
    return get_job_match(db, match_id) or {}


def get_job_match(db: Any, match_id: str) -> dict | None:
    return serialize_job_match(_one(db, f"{_MATCH_SELECT} WHERE m.id = ?", (match_id,)))


def find_job_match_for_user(db: Any, match_id: str, user_id: str) -> dict | None:
    return serialize_job_match(_one(db, f"{_MATCH_SELECT} WHERE m.id = ? AND m.user_id = ?", (match_id, user_id)))


def list_job_matches(
    db: Any,
    *,
    user_id: str | None = None,
    job_posting_id: str | None = None,
    keyword: str | None = None,
    limit: int = 200,
) -> list[dict]:
    clauses: list[str] = []
    params: list[Any] = []
    if user_id:
        clauses.append("m.user_id = ?")
        params.append(user_id)
    if job_posting_id:
        clauses.append("m.job_posting_id = ?")
        params.append(job_posting_id)
    if keyword:
        pattern = f"%{keyword.strip()}%"
        clauses.append("(m.job_title LIKE ? OR m.company LIKE ? OR m.student_name LIKE ? OR m.student_no LIKE ?)")
        params.extend([pattern, pattern, pattern, pattern])
    sql = _MATCH_SELECT
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY m.created_at DESC, m.id DESC LIMIT ?"
    params.append(max(1, min(1000, int(limit))))
    return [serialize_job_match(row) for row in _all(db, sql, tuple(params))]


# ---------------------------------------------------------------------------
# 学生粘贴 JD：读写（管理端审核后入库）
# ---------------------------------------------------------------------------

def serialize_jd_submission(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "id": row.get("id"),
        "user_id": row.get("user_id"),
        "student_name": row.get("student_name"),
        "student_no": row.get("student_no"),
        "student_college": row.get("student_college"),
        "job_title": row.get("job_title"),
        "company": row.get("company"),
        "jd_text": row.get("jd_text") or "",
        "status": row.get("status") or "pending",
        "review_note": row.get("review_note"),
        "job_posting_id": row.get("job_posting_id"),
        "decided_by": row.get("decided_by"),
        "decided_at": row.get("decided_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def create_jd_submission(
    db: Any,
    *,
    job_title: str,
    company: str = "",
    jd_text: str = "",
    user_id: str | None = None,
    student_name: str = "",
    student_no: str = "",
    student_college: str = "",
    status: str = "pending",
) -> dict:
    submission_id = _id()
    _execute(
        db,
        """
        INSERT INTO job_jd_submissions (
          id, user_id, student_name, student_no, student_college,
          job_title, company, jd_text, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            submission_id,
            _clean_text(user_id, 64) or None,
            _clean_text(student_name, 160),
            _clean_text(student_no, 80),
            _clean_text(student_college, 160),
            _clean_text(job_title, 160) or "自定义岗位",
            _clean_text(company, 160),
            _clean_multiline(jd_text, 20000),
            status if status in JD_SUBMISSION_STATUSES else "pending",
        ),
    )
    return get_jd_submission(db, submission_id) or {}


def get_jd_submission(db: Any, submission_id: str) -> dict | None:
    return serialize_jd_submission(
        _one(db, "SELECT * FROM job_jd_submissions WHERE id = ?", (submission_id,))
    )


def find_pending_jd_submission(db: Any, user_id: str, job_title: str, company: str) -> dict | None:
    """同一学生对同一岗位的待审核记录只保留一条，避免重复提交。"""
    return serialize_jd_submission(
        _one(
            db,
            "SELECT * FROM job_jd_submissions "
            "WHERE user_id = ? AND job_title = ? AND company = ? AND status = 'pending' "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (user_id, _clean_text(job_title, 160) or "自定义岗位", _clean_text(company, 160)),
        )
    )


def list_jd_submissions(
    db: Any,
    *,
    keyword: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[dict]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if keyword:
        pattern = f"%{keyword.strip()}%"
        clauses.append(
            "(job_title LIKE ? OR company LIKE ? OR student_name LIKE ? OR student_no LIKE ? OR jd_text LIKE ?)"
        )
        params.extend([pattern] * 5)
    sql = "SELECT * FROM job_jd_submissions"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(max(1, min(1000, int(limit))))
    return [serialize_jd_submission(row) for row in _all(db, sql, tuple(params))]


def update_jd_submission(
    db: Any,
    submission_id: str,
    payload: dict[str, Any],
    *,
    decided_by: str | None = None,
) -> dict | None:
    current = _one(db, "SELECT * FROM job_jd_submissions WHERE id = ?", (submission_id,))
    if not current:
        return None
    job_title = _clean_text(payload.get("job_title", current.get("job_title")), 160) or "自定义岗位"
    company = _clean_text(payload.get("company", current.get("company")), 160)
    jd_text = _clean_multiline(payload.get("jd_text", current.get("jd_text")), 20000)
    review_note = _clean_text(payload.get("review_note", current.get("review_note")), 255)
    status = str(payload.get("status", current.get("status") or "pending")).strip().lower()
    if status not in JD_SUBMISSION_STATUSES:
        status = current.get("status") or "pending"
    _execute(
        db,
        "UPDATE job_jd_submissions SET job_title = ?, company = ?, jd_text = ?, review_note = ?, "
        "status = ?, decided_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (
            job_title,
            company,
            jd_text,
            review_note,
            status,
            _clean_text(decided_by, 255) or None,
            submission_id,
        ),
    )
    return get_jd_submission(db, submission_id)


def mark_jd_submission_approved(
    db: Any,
    submission_id: str,
    posting_id: str,
    *,
    decided_by: str | None = None,
) -> dict | None:
    _execute(
        db,
        "UPDATE job_jd_submissions SET status = 'approved', job_posting_id = ?, review_note = NULL, "
        "decided_by = ?, decided_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (posting_id, _clean_text(decided_by, 255) or None, submission_id),
    )
    return get_jd_submission(db, submission_id)


def delete_jd_submission(db: Any, submission_id: str) -> bool:
    cursor = db.execute("DELETE FROM job_jd_submissions WHERE id = ?", (submission_id,))
    affected = getattr(cursor, "rowcount", 0)
    _close(cursor)
    return bool(affected)


# ---------------------------------------------------------------------------
# 规则对比引擎
# ---------------------------------------------------------------------------

def _normalize(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).lower()


def _contains_alias(text: str, alias: str) -> bool:
    alias = alias.lower()
    if not alias:
        return False
    if _ASCII_ALIAS.fullmatch(alias):
        pattern = rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"
        return re.search(pattern, text) is not None
    return alias in text


def extract_skills(text: Any) -> list[str]:
    normalized = _normalize(text)
    if not normalized:
        return []
    found: list[str] = []
    for canonical, aliases in SKILL_LEXICON.items():
        if any(_contains_alias(normalized, alias) for alias in aliases):
            found.append(canonical)
    return found


def canonical_skill(term: Any) -> str | None:
    """把岗位/简历里的技能词归一到词典展示名；词典外的词原样保留。"""
    cleaned = str(term or "").strip()
    if len(cleaned) < 2:
        return None
    normalized = _normalize(cleaned)
    for canonical, aliases in SKILL_LEXICON.items():
        if any(_contains_alias(normalized, alias) for alias in aliases):
            return canonical
    return cleaned


def skill_set(text: Any, explicit: Any = "") -> set[str]:
    skills = set(extract_skills(text))
    for term in split_terms(explicit):
        canonical = canonical_skill(term)
        if canonical:
            skills.add(canonical)
    return skills


def split_requirement_items(text: Any, limit: int = 40) -> list[str]:
    if not text:
        return []
    items: list[str] = []
    seen: set[str] = set()
    for part in _REQUIREMENT_SPLIT.split(str(text)):
        item = _REQUIREMENT_PREFIX.sub("", str(part)).strip()
        if len(item) < 4:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items[:limit]


def _posting_text(posting: dict[str, Any]) -> str:
    parts = [
        posting.get("title"),
        posting.get("job_category"),
        posting.get("description"),
        posting.get("requirements"),
        posting.get("skillsText") or posting.get("skills"),
    ]
    return "\n".join(str(part) for part in parts if part)


def _evidence_snippet(resume_text: str, skill: str) -> str:
    for alias in SKILL_LEXICON.get(skill, (skill,)):
        index = resume_text.lower().find(alias)
        if index >= 0:
            start = max(0, index - 24)
            return resume_text[start:index + len(alias) + 24].replace("\n", " ").strip()
    return ""


def _title_alignment(posting: dict[str, Any], resume_text: str, target_role: str) -> float:
    title = str(posting.get("title") or "")
    tokens = [token for token in _ASCII_TOKEN.findall(_normalize(title)) if len(token) >= 2]
    tokens.extend(skill for skill in extract_skills(title))
    if target_role and _contains_alias(_normalize(resume_text), _normalize(target_role)):
        return 1.0
    if not tokens:
        return 0.6
    haystack = _normalize(f"{resume_text} {target_role}")
    hits = sum(1 for token in tokens if _contains_alias(haystack, token))
    return min(1.0, hits / len(tokens))


def score_resume_against_posting(
    *,
    resume_text: str,
    resume_skills: str = "",
    target_role: str = "",
    posting: dict[str, Any],
) -> dict[str, Any]:
    """用可解释的规则给“简历 ↔ 招聘岗位”打分。

    评分权重：技能覆盖 45%、任职要求逐条满足度 35%、岗位方向一致性 20%。
    结果不依赖大模型，保证在任何环境下都有稳定输出。
    """
    resume_source = f"{resume_text}\n{resume_skills}"
    resume_normalized = _normalize(resume_source)
    resume_skill_set = skill_set(resume_source, resume_skills)

    posting_text = _posting_text(posting)
    posting_skill_set = skill_set(posting_text, posting.get("skillsText") or posting.get("skills"))

    requirement_source = str(posting.get("requirements") or "").strip() or str(posting.get("description") or "")
    requirement_items = split_requirement_items(requirement_source)

    matrices: list[dict[str, Any]] = []
    satisfied = 0.0
    for item in requirement_items:
        item_normalized = _normalize(item)
        item_skills = [skill for skill in extract_skills(item)]
        item_skills.extend(
            skill for skill in posting_skill_set
            if _contains_alias(item_normalized, skill.lower()) and skill not in item_skills
        )
        if item_skills:
            hits = [skill for skill in item_skills if skill in resume_skill_set]
            if len(hits) == len(item_skills):
                status = "satisfied"
                satisfied += 1
            elif hits:
                status = "partial"
                satisfied += 0.5
            else:
                status = "missing"
            evidence = _evidence_snippet(resume_source, hits[0]) if hits else ""
        else:
            overlap = _token_overlap(item_normalized, resume_normalized)
            if overlap >= 0.6:
                status, satisfied = "satisfied", satisfied + 1
            elif overlap >= 0.3:
                status, satisfied = "partial", satisfied + 0.5
            else:
                status = "missing"
            evidence = item[:40] if status != "missing" else ""
            hits = []
        matrices.append({
            "requirement": item,
            "status": status,
            "keywords": item_skills,
            "matched": hits,
            "evidence": evidence,
        })

    requirement_rate = (satisfied / len(requirement_items)) if requirement_items else 0.6

    matched_skills = sorted(posting_skill_set & resume_skill_set, key=lambda item: item)
    missing_skills = sorted(posting_skill_set - resume_skill_set, key=lambda item: item)
    if posting_skill_set:
        skill_rate = len(matched_skills) / len(posting_skill_set)
    else:
        skill_rate = 0.6

    title_rate = _title_alignment(posting, resume_source, target_role)

    raw_score = 100 * (0.45 * skill_rate + 0.35 * requirement_rate + 0.2 * title_rate)
    match_score = int(max(5, min(98, round(raw_score))))

    missing_requirements = [item["requirement"] for item in matrices if item["status"] == "missing"][:3]
    matched_requirements = [item["requirement"] for item in matrices if item["status"] == "satisfied"][:3]

    strengths: list[str] = []
    if matched_skills:
        strengths.append(f"简历已覆盖岗位要求中的 {len(matched_skills)} 项技能：{'、'.join(matched_skills[:6])}。")
    if matched_requirements:
        strengths.append(f"有 {sum(1 for item in matrices if item['status'] == 'satisfied')} 条任职要求可直接用现有经历证明。")
    if title_rate >= 0.6:
        strengths.append("求职方向与该岗位名称的契合度较高，面试时可直接围绕目标岗位展开。")
    if not strengths:
        strengths.append("简历与岗位存在一定交集，建议补充与岗位强相关的项目细节后再投递。")

    gaps: list[str] = []
    if missing_skills:
        gaps.append(f"岗位要求但简历未体现的技能：{'、'.join(missing_skills[:6])}。")
    if missing_requirements:
        gaps.append("待补强的任职要求：" + "；".join(missing_requirements))
    if not gaps:
        gaps.append("未发现明显缺口，建议把已有经历量化成结果指标以增强说服力。")

    suggestions: list[str] = []
    for skill in missing_skills[:3]:
        suggestions.append(f"补充一条使用 {skill} 完成具体任务的项目描述，并写明产出或指标。")
    if missing_requirements:
        suggestions.append("针对“" + missing_requirements[0][:30] + "”补充可验证的经历或课程实践。")
    suggestions.append("把简历中的职责描述改写为“动作 + 技术 + 结果”，与岗位关键词保持一致。")
    suggestions = list(dict.fromkeys(suggestions))[:5]

    interview_focus = (missing_skills[:3] or [skill for skill in matched_skills[:3]]) or [str(posting.get("title") or "目标岗位")]

    return {
        "matchScore": match_score,
        "scoreLabel": "岗位匹配度",
        "summary": (
            f"简历与「{posting.get('title') or '该岗位'}」的规则匹配度为 {match_score}/100，"
            f"技能覆盖 {len(matched_skills)}/{len(posting_skill_set) or 0} 项，"
            f"任职要求命中 {sum(1 for item in matrices if item['status'] == 'satisfied')}/{len(requirement_items)} 条。"
        ),
        "dimensions": [
            {"label": "技能覆盖", "score": int(round(skill_rate * 100)), "weight": "45%"},
            {"label": "任职要求满足度", "score": int(round(requirement_rate * 100)), "weight": "35%"},
            {"label": "岗位方向一致性", "score": int(round(title_rate * 100)), "weight": "20%"},
        ],
        "matchedSkills": matched_skills,
        "missingSkills": missing_skills,
        "matrices": matrices,
        "strengths": strengths,
        "gaps": gaps,
        "suggestions": suggestions,
        "interviewFocus": interview_focus,
        "partialCount": sum(1 for item in matrices if item["status"] == "partial"),
    }


def _token_overlap(left: str, right: str) -> float:
    tokens = {token for token in re.split(r"[^0-9a-z\u4e00-\u9fa5]+", left) if len(token) >= 2}
    if not tokens:
        return 0.0
    hits = sum(1 for token in tokens if token in right)
    return hits / len(tokens)
