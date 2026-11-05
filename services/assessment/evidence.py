"""记录当前报告任务对应的证据版本，即使证据改动后又恢复原值也能区分。"""


def init_schema(db, engine):
    suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci" if engine == "mysql" else ""
    large_text = "MEDIUMTEXT" if engine == "mysql" else "TEXT"
    with db:
        db.execute(f"""
            CREATE TABLE IF NOT EXISTS assessment_resume_snapshots (
                interview_id CHAR(36) PRIMARY KEY,
                analysis_json {large_text},
                FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE
            ){suffix}
        """).close()
        db.execute(f"""
            CREATE TABLE IF NOT EXISTS assessment_evidence_heads (
                interview_id CHAR(36) PRIMARY KEY,
                digest CHAR(64) NOT NULL,
                revision BIGINT NOT NULL,
                FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE
            ){suffix}
        """).close()


def current_version(db, one, interview_id, digest):
    # 调用方已持有面试记录锁。即使重评后分数和证据都恢复了原值，
    # 递增的版本号也能阻止旧任务发布过期结果。
    head = one("SELECT digest,revision FROM assessment_evidence_heads WHERE interview_id=?", (interview_id,))
    if head is None:
        revision = 1
        db.execute("INSERT INTO assessment_evidence_heads (interview_id,digest,revision) VALUES (?,?,?)",
                   (interview_id, digest, revision)).close()
    elif digest != head["digest"]:
        revision = head["revision"] + 1
        db.execute("UPDATE assessment_evidence_heads SET digest=?,revision=? WHERE interview_id=?",
                   (digest, revision, interview_id)).close()
    else:
        revision = head["revision"]
    return f"{revision}-{digest}"
