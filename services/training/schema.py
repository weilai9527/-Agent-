def initialize(db):
    # 二进制排序规则确保账号标识与网关签名完全一致。使用 InnoDB 锁定学籍，并原子提交尝试和次数。
    suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin" if db.engine == "mysql" else ""
    longtext = "MEDIUMTEXT" if db.engine == "mysql" else "TEXT"
    statements = [
        f"""CREATE TABLE IF NOT EXISTS training_tasks (
            task_id VARCHAR(36) PRIMARY KEY, school_id VARCHAR(128) NOT NULL,
            teacher_id VARCHAR(128) NOT NULL, request_id VARCHAR(128) NOT NULL,
            fingerprint CHAR(64) NOT NULL, title VARCHAR(160) NOT NULL,
            job_role VARCHAR(128) NOT NULL, job_id VARCHAR(128) NOT NULL,
            deadline_us BIGINT NOT NULL, max_attempts INTEGER NOT NULL,
            questions {longtext} NOT NULL, class_ids TEXT NOT NULL,
            student_count INTEGER NOT NULL, created_us BIGINT NOT NULL,
            source_attempt_id VARCHAR(36), UNIQUE(school_id, teacher_id, request_id)
        )""",
        """CREATE TABLE IF NOT EXISTS training_enrollments (
            task_id VARCHAR(36) NOT NULL, student_id VARCHAR(128) NOT NULL,
            class_id VARCHAR(128) NOT NULL, used_attempts INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(task_id, student_id),
            FOREIGN KEY(task_id) REFERENCES training_tasks(task_id)
        )""",
        """CREATE TABLE IF NOT EXISTS training_attempts (
            attempt_id VARCHAR(36) PRIMARY KEY, interview_id VARCHAR(36) NOT NULL UNIQUE,
            task_id VARCHAR(36) NOT NULL, student_id VARCHAR(128) NOT NULL,
            request_id VARCHAR(128) NOT NULL, attempt_no INTEGER NOT NULL,
            status VARCHAR(16) NOT NULL, created_us BIGINT NOT NULL, completed_us BIGINT,
            UNIQUE(task_id, student_id, request_id), UNIQUE(task_id, student_id, attempt_no),
            FOREIGN KEY(task_id,student_id) REFERENCES training_enrollments(task_id,student_id)
        )""",
        """CREATE TABLE IF NOT EXISTS training_completions (
            school_id VARCHAR(128) NOT NULL, event_id VARCHAR(128) NOT NULL,
            attempt_id VARCHAR(36) NOT NULL, PRIMARY KEY(school_id,event_id),
            FOREIGN KEY(attempt_id) REFERENCES training_attempts(attempt_id)
        )"""
    ]
    db.ensure_schema(s + suffix for s in statements)
    db.require_exact_keys("training")
