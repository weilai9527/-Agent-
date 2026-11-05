"""持久化每场面试的语音任务归属。云端调用在数据库事务之外执行。"""
import hashlib
import json
import time

from shared.service_db import ServiceDatabase


def _key(school_id, actor_id, interview_id):
    # 分别编码学校、学生和面试三个字段，标识中含分隔符时仍能区分频道归属。
    material = json.dumps([school_id, actor_id, interview_id], ensure_ascii=False).encode()
    return hashlib.sha256(material).hexdigest()


def channel_id(school_id, actor_id, interview_id):
    return "room_" + _key(school_id, actor_id, interview_id)[:48]


def candidate_user_id(school_id, actor_id, interview_id):
    return "user_" + _key(school_id, actor_id, interview_id)[:48]


def database():
    return ServiceDatabase.from_env("media")


def initialize():
    db = database()
    # 恢复进程只扫描到期会话；任务结束后仍保留归属信息供授权查询。
    mysql_index = ", INDEX media_rtc_due (recover_at, id)" if db.engine == "mysql" else ""
    engine = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin" if db.engine == "mysql" else ""
    statements = ["""CREATE TABLE IF NOT EXISTS media_rtc_session (
        id CHAR(64) PRIMARY KEY, school_id VARCHAR(128) NOT NULL, actor_id VARCHAR(128) NOT NULL,
        interview_id VARCHAR(128) NOT NULL, channel_id VARCHAR(64) NOT NULL,
        candidate_user_id VARCHAR(64) NOT NULL, agent_user_id VARCHAR(64) NOT NULL,
        state VARCHAR(32) NOT NULL DEFAULT 'idle', task_id VARCHAR(64), role_id VARCHAR(128),
        revision BIGINT NOT NULL DEFAULT 0, recover_at BIGINT, stop_attempts INTEGER NOT NULL DEFAULT 0,
        last_heartbeat_at BIGINT, token_expires_at BIGINT, started_at BIGINT, stopped_at BIGINT,
        last_error VARCHAR(256)
    """ + mysql_index + ")" + engine]
    if db.engine == "sqlite":
        statements.append("CREATE INDEX IF NOT EXISTS media_rtc_due ON media_rtc_session(recover_at,id)")
    db.ensure_schema(statements)
    db.require_exact_keys("media-rtc")


def session(context, create=False):
    identity = (context["school_id"], context["actor_id"], context["interview_id"])
    key = _key(*identity)
    db = database()
    with db.transaction(write=create) as tx:
        if create:
            conflict = ("ON DUPLICATE KEY UPDATE id=id" if db.engine == "mysql" else
                        "ON CONFLICT(id) DO NOTHING")
            tx.execute("""INSERT INTO media_rtc_session
                       (id,school_id,actor_id,interview_id,channel_id,candidate_user_id,agent_user_id)
                       VALUES (?,?,?,?,?,?,?) """ + conflict,
                       (key, *identity, channel_id(*identity), candidate_user_id(*identity), "agent_" + key[:48]))
        return tx.one("SELECT * FROM media_rtc_session WHERE id=?", (key,))


def get(key):
    with database().transaction() as tx:
        return tx.one("SELECT * FROM media_rtc_session WHERE id=?", (key,))


def update(snapshot, **changes):
    """以读到的版本号作为更新条件，阻止迟到回调和并发恢复进程覆写新状态。"""
    # 列名来自服务代码中的固定关键字参数；数据值一律参数化。
    sql = ", ".join(column + "=?" for column in changes)
    with database().transaction(write=True) as tx:
        updated = tx.execute(f"UPDATE media_rtc_session SET {sql}, revision=revision+1 WHERE id=? AND revision=?",
                             (*changes.values(), snapshot["id"], snapshot["revision"]))
        if updated:
            return tx.one("SELECT * FROM media_rtc_session WHERE id=?", (snapshot["id"],))
    return None


def set_token_expiry(key, expiry):
    # 续发凭证不改变任务归属或版本，避免打断并发启停。到期时间取已发凭证的最大值。
    with database().transaction(write=True) as tx:
        tx.execute("""UPDATE media_rtc_session SET token_expires_at=?
                      WHERE id=? AND (token_expires_at IS NULL OR token_expires_at<?)""", (expiry, key, expiry))
        return tx.one("SELECT * FROM media_rtc_session WHERE id=?", (key,))


def due(now=None):
    with database().transaction() as tx:
        return tx.all("""SELECT * FROM media_rtc_session WHERE recover_at<=?
                         ORDER BY recover_at,id LIMIT 100""", (int(time.time()) if now is None else now,))
