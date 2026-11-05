"""持久化存证队列，并用租约令牌防止旧任务覆盖新结果。"""
import hashlib
from uuid import uuid4

from shared.service_db import ServiceDatabase

FIELDS = "event_id, digest, status, network, tx_hash, block_number"


def school_key(school_id):
    # 先按学校标识的原始字节计算摘要，保留大小写差异。
    return hashlib.sha256(school_id.encode("utf-8")).hexdigest()


class ConflictingDigest(Exception):
    pass


class AnchorStore:
    def __init__(self, db: ServiceDatabase):
        self.db = db

    def initialize(self):
        mysql = self.db.engine == "mysql"
        suffix = ", INDEX provenance_due (status, due_at)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin" if mysql else ")"
        ddl = ["""CREATE TABLE IF NOT EXISTS provenance_anchors (
            school_key CHAR(64) NOT NULL, event_id CHAR(32) NOT NULL, digest CHAR(64) NOT NULL,
            status VARCHAR(16) NOT NULL, network VARCHAR(96), binding CHAR(64),
            tx_hash CHAR(66), block_number BIGINT, due_at BIGINT NOT NULL,
            lease CHAR(32), PRIMARY KEY (school_key, event_id)
        """ + suffix]
        if not mysql:
            ddl.append("CREATE INDEX IF NOT EXISTS provenance_due ON provenance_anchors(status,due_at)")
        self.db.ensure_schema(ddl)
        self.db.require_exact_keys("provenance")

    def put(self, school_id, event_id, digest):
        key = (school_key(school_id), event_id)
        suffix = (" ON DUPLICATE KEY UPDATE digest=provenance_anchors.digest"
                  if self.db.engine == "mysql" else " ON CONFLICT(school_key,event_id) DO NOTHING")
        with self.db.transaction(write=True) as tx:
            tx.execute("""INSERT INTO provenance_anchors
                (school_key,event_id,digest,status,due_at) VALUES (?,?,?,'pending',0)""" + suffix,
                       (*key, digest))
            row = tx.one(f"SELECT {FIELDS} FROM provenance_anchors WHERE school_key=? AND event_id=?", key)
            if row["digest"] != digest:
                raise ConflictingDigest
            return row

    def get(self, school_id, event_id):
        with self.db.transaction() as tx:
            return tx.one(f"SELECT {FIELDS} FROM provenance_anchors WHERE school_key=? AND event_id=?",
                          (school_key(school_id), event_id))

    def claim(self, now, network, binding):
        # 广播前固定目标链、账户和接收地址，防止改配重启后向其他链重发。
        lock = " FOR UPDATE" if self.db.engine == "mysql" else ""
        with self.db.transaction(write=True) as tx:
            row = tx.one("""SELECT * FROM provenance_anchors WHERE
                status IN ('pending','submitted') AND due_at<=? AND (binding IS NULL OR binding=?)
                ORDER BY due_at,school_key,event_id LIMIT 1""" + lock, (now, binding))
            if row:
                row["lease"] = uuid4().hex
                tx.execute("""UPDATE provenance_anchors SET lease=?,due_at=?,network=?,binding=?
                    WHERE school_key=? AND event_id=?""",
                           (row["lease"], now + 60, network, binding, row["school_key"], row["event_id"]))
            return row

    def finish(self, row, status, tx_hash, block_number, due_at):
        with self.db.transaction(write=True) as tx:
            return tx.execute("""UPDATE provenance_anchors SET status=?,tx_hash=?,block_number=?,
                due_at=?,lease=NULL WHERE school_key=? AND event_id=? AND lease=?""",
                              (status, tx_hash, block_number, due_at, row["school_key"],
                               row["event_id"], row["lease"])) == 1
