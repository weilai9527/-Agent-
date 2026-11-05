"""日志库与业务库隔离。事件追加后按学校、角色和当前名册读取。"""

import json

from fastapi import HTTPException


def prepare(db):
    # 配置误指业务库时在第一次建表前拒绝启动；同一 MySQL 服务器的不同地址也不能绕过。
    sql = (
        "SELECT TABLE_NAME AS name FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()"
        if db.engine == "mysql"
        else "SELECT name FROM sqlite_master WHERE type='table'"
    )
    with db.transaction() as tx:
        if any(row["name"] != "ops_events" and not row["name"].startswith("sqlite_") for row in tx.all(sql)):
            raise ValueError("日志服务必须使用独立的空库或已有日志库")
    suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin" if db.engine == "mysql" else ""
    index = (
        ", INDEX ops_chrono(school_id,category,occurred_at,event_id), INDEX ops_actor(school_id,category,actor_id,occurred_at)"
        if suffix
        else ""
    )
    db.ensure_schema(
        [
            f"""CREATE TABLE IF NOT EXISTS ops_events (
      school_id VARCHAR(128) NOT NULL, category VARCHAR(8) NOT NULL, event_id VARCHAR(64) NOT NULL,
      actor_id VARCHAR(128) NOT NULL, interview_id VARCHAR(64) NOT NULL, occurred_at VARCHAR(36) NOT NULL,
      event_type VARCHAR(80) NOT NULL, level VARCHAR(8) NOT NULL, request_id VARCHAR(32) NOT NULL,
      payload TEXT NOT NULL, PRIMARY KEY(school_id,category,event_id){index}){suffix}"""
        ]
    )
    if not suffix:
        db.ensure_schema(
            [
                "CREATE INDEX IF NOT EXISTS ops_chrono ON ops_events(school_id,category,occurred_at,event_id)",
                "CREATE INDEX IF NOT EXISTS ops_actor ON ops_events(school_id,category,actor_id,occurred_at)",
            ]
        )
    db.require_exact_keys("operations")


def insert(tx, engine, school, category, event_id, actor, interview, occurred, payload):
    """以学校、日志类别及事件编号去重；相同编号若承载不同内容则报冲突，不覆盖审计。"""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    values = (
        school,
        category,
        event_id,
        actor,
        interview,
        occurred,
        payload["event_type"],
        payload.get("level", ""),
        payload.get("request_id", ""),
        encoded,
    )
    conflict = (
        "ON DUPLICATE KEY UPDATE event_id=event_id"
        if engine == "mysql"
        else "ON CONFLICT(school_id,category,event_id) DO NOTHING"
    )
    tx.execute(
        """INSERT INTO ops_events(school_id,category,event_id,actor_id,interview_id,occurred_at,event_type,
               level,request_id,payload) VALUES (?,?,?,?,?,?,?,?,?,?) """
        + conflict,
        values,
    )
    stored = tx.one(
        "SELECT actor_id,interview_id,occurred_at,payload FROM ops_events WHERE school_id=? AND category=? AND event_id=?",
        values[:3],
    )
    if (stored["actor_id"], stored["interview_id"], stored["occurred_at"], stored["payload"]) != (
        actor,
        interview,
        occurred,
        encoded,
    ):
        raise HTTPException(409, "日志编号已绑定不同的事件")


def page(db, where, params, limit, offset):
    """各条件由处理器固定，所有输入均作为 SQL 参数传递。"""
    with db.transaction() as tx:
        total = tx.one("SELECT COUNT(*) AS n FROM ops_events WHERE " + where, tuple(params))["n"]
        rows = tx.all(
            "SELECT * FROM ops_events WHERE "
            + where
            + " ORDER BY occurred_at DESC,school_id,event_id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
    return rows, total
