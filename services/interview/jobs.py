"""与面试业务共用事务的持久化任务队列。

任务入队复用提交回合或结束面试时的数据库连接和事务。
迁移、领取、续约、重试和发布各自使用独立事务。
调用外部模型期间不持有数据库锁。
"""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
from uuid import uuid4


JOB_KINDS = ("score", "report", "train_complete", "analytics", "project", "media_close")


@dataclass(frozen=True)
class RetryJob:
    """发布回调可用此返回值保存已完成的部分，并安排下一次重试。"""
    delay_seconds: int | None = None


class JobQueue:
    def __init__(self, db, engine):
        if engine not in ("sqlite", "mysql"):
            raise ValueError("expected sqlite or mysql")
        self.db = db
        self.mysql = engine == "mysql"
        # 不同主机上的工作进程都以数据库时钟判断租约是否到期。
        self.now = "UNIX_TIMESTAMP()" if self.mysql else "CAST(strftime('%s','now') AS INTEGER)"
        self.lock = " FOR UPDATE" if self.mysql else ""

    def migrate(self):
        # MySQL 的结构变更会隐式提交，因此迁移只在启动时、业务写入前执行。
        mysql_index = ", INDEX idx_interview_jobs_ready (ready_at, id)" if self.mysql else ""
        engine = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci" if self.mysql else ""
        with self.db:
            self.db.execute(f"""
                CREATE TABLE IF NOT EXISTS interview_jobs (
                    id CHAR(64) PRIMARY KEY,
                    kind VARCHAR(16) NOT NULL,
                    interview_id VARCHAR(64) NOT NULL,
                    subject_id VARCHAR(64) NOT NULL,
                    version VARCHAR(255) NOT NULL,
                    state VARCHAR(16) NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    ready_at BIGINT,
                    lease_token CHAR(32),
                    last_error VARCHAR(128),
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    {mysql_index}
                ){engine}
            """).close()
            if self.mysql:
                # 早期部署的 MySQL 8 表可能沿用了服务器的默认排序规则。
                # 任务标识需要与使用 unicode_ci 的事件键关联，因此在处理任务前统一排序规则。
                # 直接转换现有表，保留排队中的任务和已发放的租约令牌。
                old = self._one("""
                    SELECT 1 AS needs_upgrade FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='interview_jobs'
                      AND CHARACTER_SET_NAME IS NOT NULL AND COLLATION_NAME <> 'utf8mb4_unicode_ci'
                    LIMIT 1
                """, ())
                if old:
                    self.db.execute("""
                        ALTER TABLE interview_jobs CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                    """).close()
            else:
                self.db.execute("CREATE INDEX IF NOT EXISTS idx_interview_jobs_ready ON interview_jobs (ready_at, id)").close()

        from .delivery import migrate
        migrate(self.db, self.mysql)

    def enqueue(self, kind, interview_id, subject_id, version):
        """在生产者事务中登记任务；同一证据再次入队时保留原任务状态。"""
        if kind not in JOB_KINDS:
            raise ValueError("unknown interview job kind")
        key = json.dumps([kind, interview_id, subject_id, version], ensure_ascii=False, separators=(",", ":"))
        job_id = sha256(key.encode("utf-8")).hexdigest()
        conflict = "ON DUPLICATE KEY UPDATE id=id" if self.mysql else "ON CONFLICT(id) DO NOTHING"
        self.db.execute(f"""
            INSERT INTO interview_jobs (id,kind,interview_id,subject_id,version,state,ready_at)
            VALUES (?,?,?,?,?,'pending',{self.now}) {conflict}
        """, (job_id, kind, interview_id, subject_id, version)).close()
        return job_id

    def get(self, job_id):
        return self._one("SELECT * FROM interview_jobs WHERE id=?", (job_id,))

    def request_retry(self, job_id, *, include_done=False):
        """显式重试请求复用生产者事务，不打断正在执行的租约。"""
        states = "('pending','done')" if include_done else "('pending')"
        self.db.execute(f"""
            UPDATE interview_jobs SET state='pending', ready_at={self.now}
            WHERE id=? AND state IN {states}
        """, (job_id,)).close()

    @contextmanager
    def _transaction(self):
        with self.db:
            if not self.mysql:
                self.db.execute("BEGIN IMMEDIATE").close()
            yield

    def _one(self, sql, params):
        cursor = self.db.execute(sql, params)
        try:
            row = cursor.fetchone()
            return dict(row) if row is not None else None
        finally:
            cursor.close()

    def claim(self, lease_seconds, *, job_id=None, kinds=None):
        if lease_seconds < 3:
            raise ValueError("interview worker lease must be at least 3 seconds")
        # 先找候选任务，避免在 InnoDB 中锁住整个候选范围。
        # 若条件更新时其他进程已先领取，就等下一轮轮询。
        condition = " AND id=?" if job_id is not None else ""
        params = (job_id,) if job_id is not None else ()
        if kinds is not None:
            if not kinds or not set(kinds).issubset(JOB_KINDS):
                raise ValueError("unknown worker job kinds")
            marks = ",".join("?" for _ in kinds)
            condition += f" AND kind IN ({marks})"
            params += tuple(kinds)
        candidate = self._one(
            f"SELECT id FROM interview_jobs WHERE ready_at <= {self.now}{condition} ORDER BY ready_at,id LIMIT 1",
            params,
        )
        if candidate is None:
            return None
        with self._transaction():
            token = uuid4().hex
            cursor = self.db.execute(f"""
                UPDATE interview_jobs SET state='running', lease_token=?, ready_at={self.now}+?, attempts=attempts+1
                WHERE id=? AND ready_at <= {self.now}
            """, (token, lease_seconds, candidate["id"]))
            try:
                claimed = cursor.rowcount == 1
            finally:
                cursor.close()
            if claimed:
                return self._one("SELECT * FROM interview_jobs WHERE id=?", (candidate["id"],))
        return None

    def _owns_lease(self, job):
        # 先取得行锁，再用另一条语句检查数据库时间。
        # 否则 MySQL 采用的语句开始时间可能早于等待行锁的这段时间。
        row = self._one("SELECT lease_token FROM interview_jobs WHERE id=?" + self.lock, (job["id"],))
        if row is None or row["lease_token"] != job["lease_token"]:
            return False
        return self._one(f"SELECT id FROM interview_jobs WHERE id=? AND ready_at > {self.now}", (job["id"],)) is not None

    def renew(self, job, lease_seconds):
        with self._transaction():
            if not self._owns_lease(job):
                return False
            self.db.execute(f"UPDATE interview_jobs SET ready_at={self.now}+? WHERE id=?",
                            (lease_seconds, job["id"])).close()
            return True

    def _reschedule(self, job, retry, error):
        delay = retry.delay_seconds
        if delay is None:
            delay = min(300, 2 ** min(job["attempts"], 9))
        self.db.execute(f"""
            UPDATE interview_jobs SET state='pending', lease_token=NULL, ready_at={self.now}+?, last_error=?
            WHERE id=?
        """, (max(1, int(delay)), error, job["id"])).close()

    def finish(self, job, publish, *, error=None):
        """只允许持有当前租约的进程发布结果，并在同一事务内确认任务。"""
        with self._transaction():
            # 生产者先锁面试，再锁任务。此处采用相同顺序，避免发布报告时
            # 与正在入队评分或报告任务的问答回合互相等待。
            session = self._one("SELECT id FROM interview_sessions WHERE id=?" + self.lock, (job["interview_id"],))
            if not self._owns_lease(job):
                return False
            result = publish() if session else None
            if isinstance(result, RetryJob):
                self._reschedule(job, result, error)
            else:
                self.db.execute("""
                    UPDATE interview_jobs SET state='done', lease_token=NULL, ready_at=NULL, last_error=NULL WHERE id=?
                """, (job["id"],)).close()
            return True

    def retry(self, job, exc):
        # 只保存异常类型，以免异常消息泄露学生回答或模型请求细节。
        # 若面试已删除，对应任务也无需再试。
        return self.finish(job, RetryJob, error=type(exc).__name__[:128])
