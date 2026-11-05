"""保存评估的最新版本和已接收事件的持久回执。"""
from collections import defaultdict
from hashlib import sha256
import json

from fastapi import HTTPException


def initialize(db):
    suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin" if db.engine == "mysql" else ""
    large = "MEDIUMTEXT" if db.engine == "mysql" else "TEXT"
    indexes = (
        ("analytics_roster", "school_id,class_id,student_id"),
        ("analytics_student", "school_id,student_id"),
    )
    # MySQL 随建表创建索引，SQLite 使用独立的幂等索引语句，二者支持同一名单查询。
    inline = "".join(f", INDEX {name} ({columns})" for name, columns in indexes) if db.engine == "mysql" else ""
    tables = [
        """CREATE TABLE IF NOT EXISTS analytics_events (
            school_id VARCHAR(128) NOT NULL, event_id VARCHAR(128) NOT NULL, digest CHAR(64) NOT NULL,
            PRIMARY KEY (school_id, event_id))""",
        f"""CREATE TABLE IF NOT EXISTS analytics_attempts (
            school_id VARCHAR(128) NOT NULL, attempt_id VARCHAR(128) NOT NULL,
            student_id VARCHAR(128) NOT NULL, teacher_id VARCHAR(128) NOT NULL,
            class_id VARCHAR(128) NOT NULL, task_id VARCHAR(128) NOT NULL, job_role VARCHAR(128) NOT NULL,
            version INTEGER NOT NULL, digest CHAR(64) NOT NULL, PRIMARY KEY (school_id, attempt_id){inline})""",
        """CREATE TABLE IF NOT EXISTS analytics_attempt_context (
            school_id VARCHAR(128) NOT NULL, attempt_id VARCHAR(128) NOT NULL,
            interview_id VARCHAR(128) NOT NULL, frozen_question_count INTEGER NOT NULL,
            PRIMARY KEY (school_id, attempt_id), FOREIGN KEY (school_id, attempt_id)
            REFERENCES analytics_attempts(school_id, attempt_id))""",
        f"""CREATE TABLE IF NOT EXISTS analytics_scores (
            school_id VARCHAR(128) NOT NULL, attempt_id VARCHAR(128) NOT NULL,
            question_id VARCHAR(128) NOT NULL, dimension VARCHAR(128) NOT NULL,
            question_text TEXT NOT NULL, original_answer {large} NOT NULL, score DOUBLE NOT NULL,
            PRIMARY KEY (school_id, attempt_id, question_id, dimension),
            FOREIGN KEY (school_id, attempt_id) REFERENCES analytics_attempts(school_id, attempt_id))""",
    ]
    statements = [table + suffix for table in tables]
    if db.engine == "sqlite":
        statements.extend(f"CREATE INDEX IF NOT EXISTS {name} ON analytics_attempts ({columns})"
                          for name, columns in indexes)
    db.ensure_schema(statements)
    db.require_exact_keys("analytics")


def fingerprint(body):
    normalized = body.model_dump(exclude={"event_id"})
    normalized["questions"].sort(key=lambda q: (q["question_id"], q["dimension"]))
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return sha256(raw).hexdigest()


def publish(db, body, attempt):
    prompts = {q.question_id: q.prompt for q in attempt.questions}
    if any(row.question_id not in prompts for row in body.questions):
        raise HTTPException(422, "Unknown question in the frozen task")
    digest = fingerprint(body)
    key = (attempt.school_id, attempt.attempt_id)
    mysql = db.engine == "mysql"
    # 写入统一按事件、尝试顺序加锁。SQLite 预占写事务；InnoDB 写入唯一键后锁读，
    # 即使首次投递时尚无投影，多个写入者也不会同时认为自己可以发布。
    keep_event = (" ON DUPLICATE KEY UPDATE digest=analytics_events.digest" if mysql else
                  " ON CONFLICT(school_id,event_id) DO NOTHING")
    keep_attempt = (" ON DUPLICATE KEY UPDATE digest=analytics_attempts.digest" if mysql else
                    " ON CONFLICT(school_id,attempt_id) DO NOTHING")
    lock = " FOR UPDATE" if mysql else ""
    with db.transaction(write=True) as tx:
        tx.execute("INSERT INTO analytics_events (school_id,event_id,digest) VALUES (?,?,?)" + keep_event,
                   (attempt.school_id, body.event_id, digest))
        receipt = tx.one("SELECT digest FROM analytics_events WHERE school_id=? AND event_id=?" + lock,
                         (attempt.school_id, body.event_id))
        if receipt["digest"] != digest:
            raise HTTPException(409, "Event id reused with different evidence")
        tx.execute("""INSERT INTO analytics_attempts
            (school_id,attempt_id,student_id,teacher_id,class_id,task_id,job_role,version,digest)
            VALUES (?,?,?,?,?,?,?,0,'')""" + keep_attempt,
                   (*key, attempt.student_id, attempt.teacher_id, attempt.class_id, attempt.task_id, attempt.job_role))
        current = tx.one("SELECT version,digest FROM analytics_attempts WHERE school_id=? AND attempt_id=?" + lock, key)
        if current["version"] == body.version and current["digest"] != digest:
            raise HTTPException(409, "Revision already published with different evidence")
        # 独立上下文表允许新旧发布端在滚动升级时共存。已核验的重投可补齐历史记录；
        # 缺少记录时不能推测题数或报告编号。
        keep_context = (" ON DUPLICATE KEY UPDATE interview_id=analytics_attempt_context.interview_id" if mysql else
                        " ON CONFLICT(school_id,attempt_id) DO NOTHING")
        tx.execute("""INSERT INTO analytics_attempt_context
                   (school_id,attempt_id,interview_id,frozen_question_count) VALUES (?,?,?,?)""" + keep_context,
                   (*key, attempt.interview_id, len(prompts)))
        applied = body.version > current["version"]
        if applied:
            tx.execute("DELETE FROM analytics_scores WHERE school_id=? AND attempt_id=?", key)
            for row in body.questions:
                tx.execute("""INSERT INTO analytics_scores
                    (school_id,attempt_id,question_id,dimension,question_text,original_answer,score)
                    VALUES (?,?,?,?,?,?,?)""", (*key, row.question_id, row.dimension, prompts[row.question_id],
                                                row.original_answer, row.score))
            tx.execute("UPDATE analytics_attempts SET version=?, digest=? WHERE school_id=? AND attempt_id=?",
                       (body.version, digest, *key))
        return {"attempt_id": attempt.attempt_id, "version": max(body.version, current["version"]), "applied": applied}


WEAK_SCORE = 60


def read(db, ctx, roster, *, task_id=None, class_id=None, job_role=None, dimension=None,
         attempt_id=None, question_id=None, weaknesses=False):
    # 查询条件只收窄数据范围。即使客户端猜中任务或尝试编号，也要检查归属和当前名单。
    predicates = ["a.school_id=?"]
    args = [ctx["school_id"]]
    if ctx["actor_type"] == "teacher":
        predicates.append("a.teacher_id=?")
        args.append(ctx["actor_id"])
    if ctx["actor_type"] == "student":
        predicates.append("a.student_id=?")
        args.append(ctx["actor_id"])
    for column, value in (("a.task_id", task_id), ("a.class_id", class_id), ("a.job_role", job_role),
                          ("s.dimension", dimension), ("a.attempt_id", attempt_id), ("s.question_id", question_id)):
        if value is not None:
            predicates.append(column + "=?")
            args.append(value)
    fields = ("a.attempt_id,a.student_id,a.class_id,a.task_id,a.job_role,a.version,"
              "s.question_id,s.dimension,s.score")
    if weaknesses:
        fields += ",c.interview_id,s.question_text,s.original_answer"
        predicates.append("s.score<?")
        args.append(WEAK_SCORE)
    else:
        fields += ",c.frozen_question_count"
    query = ("SELECT " + fields + " FROM analytics_attempts a LEFT JOIN analytics_scores s "
             "ON a.school_id=s.school_id AND a.attempt_id=s.attempt_id LEFT JOIN analytics_attempt_context c "
             "ON a.school_id=c.school_id AND a.attempt_id=c.attempt_id WHERE " + " AND ".join(predicates))
    with db.transaction() as tx:
        if ctx["actor_type"] == "student":
            return tx.all(query, tuple(args))
        result = []
        # 按小批次将授权名单传入 SQL，同时限制占位符数量并阻止读取名单外原答。
        for cid, students in roster.items():
            students = sorted(students)
            for start in range(0, len(students), 500):
                batch = students[start:start + 500]
                marks = ",".join("?" for _ in batch)
                result.extend(tx.all(query + f" AND a.class_id=? AND a.student_id IN ({marks})",
                                     (*args, cid, *batch)))
        return result


def metrics(rows, coverage):
    attempts = set()
    scores = defaultdict(list)
    for row in rows:
        attempts.add(row["attempt_id"])
        if row["question_id"] is not None:
            scores[(row["attempt_id"], row["question_id"])].append(row["score"])
    # 多个维度先汇总到原题，每道题对综合均分的权重相同。
    means = [sum(vals) / len(vals) for vals in scores.values()]
    return {"attempts": len(attempts), "scored_attempts": len({aid for aid, _ in scores}),
            "valid_attempts": sum(coverage[aid] == "full" for aid in attempts),
            "insufficient_attempts": sum(coverage[aid] == "partial" for aid in attempts),
            "unknown_coverage_attempts": sum(coverage[aid] == "unknown" for aid in attempts),
            "completed_questions": len(means),
            "average_score": round(sum(means) / len(means), 2) if means else None}


def attempt_coverage(rows):
    expected = {}
    scored = defaultdict(set)
    for row in rows:
        aid = row["attempt_id"]
        expected[aid] = row["frozen_question_count"]
        if row["question_id"] is not None:
            scored[aid].add(row["question_id"])
    coverage = {}
    for aid, count in expected.items():
        if count is None:
            coverage[aid] = "unknown"
        else:
            coverage[aid] = "full" if len(scored[aid]) == count else "partial"
    return coverage


def class_weaknesses(rows):
    groups = defaultdict(list)
    for row in rows:
        if row["dimension"] is not None:
            groups[(row["class_id"], row["dimension"])].append(row)
    result = []
    for (cid, dimension), observations in sorted(groups.items()):
        weak = [row for row in observations if row["score"] < WEAK_SCORE]
        if weak:
            # 同一尝试、原题和维度的分数唯一，分母包括同群体里该维度达标的题次。
            result.append({"class_id": cid, "dimension": dimension, "weak_questions": len(weak),
                           "scored_questions": len(observations),
                           "affected_students": len({r["student_id"] for r in weak}),
                           "average_score": round(sum(r["score"] for r in observations) / len(observations), 2)})
    return result


def summary(rows, dimension=None):
    # 先用全维度数据判定整份任务的覆盖，再按所选维度筛选参与汇总的尝试和题分。
    coverage = attempt_coverage(rows)
    if dimension is not None:
        rows = [row for row in rows if row["dimension"] == dimension]
    result = metrics(rows, coverage)
    result["class_weaknesses"] = class_weaknesses(rows)
    for name, field in (("by_task", "task_id"), ("by_class", "class_id"),
                        ("by_job", "job_role"), ("by_dimension", "dimension")):
        groups = defaultdict(list)
        for row in rows:
            if row[field] is not None:
                groups[row[field]].append(row)
        result[name] = [{"key": key, **metrics(groups[key], coverage)} for key in sorted(groups)]
    return result
