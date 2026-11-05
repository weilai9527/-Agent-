"""学校按月核算额度。每次变更先锁定该学校，再读取账本，避免并发超额。"""
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException


class UsageLedger:
    def __init__(self, store):
        self.store = store
        self.mysql = store.engine == "mysql"

    def initialize(self):
        # 显式区分大小写，避免 MySQL 默认排序规则把不同学校或学生的标识视为相同。
        suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin" if self.mysql else ""
        live_index = "usage_live (school_id, period, resource, actual_units, expires_at)"
        statements = [
            """CREATE TABLE IF NOT EXISTS usage_limits (
                school_id VARCHAR(128) PRIMARY KEY, text_limit BIGINT NOT NULL,
                media_limit BIGINT NOT NULL
            )""" + suffix,
            """CREATE TABLE IF NOT EXISTS usage_spent (
                school_id VARCHAR(128) NOT NULL, period CHAR(7) NOT NULL,
                resource VARCHAR(8) NOT NULL, units BIGINT NOT NULL,
                PRIMARY KEY (school_id, period, resource)
            )""" + suffix,
            """CREATE TABLE IF NOT EXISTS usage_reservations (
                reservation_id CHAR(32) PRIMARY KEY, school_id VARCHAR(128) NOT NULL,
                caller VARCHAR(128) NOT NULL, actor_type VARCHAR(16) NOT NULL,
                actor_id VARCHAR(128) NOT NULL, request_id VARCHAR(128) NOT NULL,
                period CHAR(7) NOT NULL, resource VARCHAR(8) NOT NULL, units BIGINT NOT NULL,
                ttl_seconds INTEGER NOT NULL, expires_at BIGINT NOT NULL, actual_units BIGINT,
                UNIQUE (school_id, caller, actor_type, actor_id, request_id)
            """ + (", INDEX " + live_index if self.mysql else "") + ")" + suffix,
            """CREATE TABLE IF NOT EXISTS usage_dispatches (
                reservation_id CHAR(32) PRIMARY KEY, started_at BIGINT NOT NULL,
                FOREIGN KEY(reservation_id) REFERENCES usage_reservations(reservation_id)
            )""" + suffix,
        ]
        if not self.mysql:
            statements.append("CREATE INDEX IF NOT EXISTS usage_live ON " +
                              "usage_reservations (school_id, period, resource, actual_units, expires_at)")
        self.store.ensure_schema(statements)
        self.store.require_exact_keys("usage")

    def _now(self, tx):
        # 以数据库时钟判定到期时间，保证所有副本使用同一时间基准。
        clock = "UNIX_TIMESTAMP()" if self.mysql else "CAST(strftime('%s','now') AS INTEGER)"
        return tx.one("SELECT " + clock + " AS ts")["ts"]

    def _limits(self, tx, school, *, lock=False):
        clause = " FOR UPDATE" if self.mysql and lock else ""
        return tx.one("SELECT * FROM usage_limits WHERE school_id=?" + clause, (school,))

    @staticmethod
    def _owner(ctx):
        return (ctx["school_id"], ctx["caller"], ctx["actor_type"], ctx["actor_id"])

    @staticmethod
    def _period(now):
        return datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m")

    @staticmethod
    def _view(row, now):
        if row["actual_units"] is not None:
            state = "settled"
        elif row["started_at"] is not None:
            state = "in_flight"
        else:
            state = "reserved" if row["expires_at"] > now else "expired"
        return {**{k: row[k] for k in ("reservation_id", "resource", "units", "actual_units", "expires_at")},
                "state": state}

    @staticmethod
    def _balance(tx, school, period, resource, limit, now):
        bucket = (school, period, resource)
        used = tx.one("SELECT units FROM usage_spent WHERE school_id=? AND period=? AND resource=?", bucket)
        used = used["units"] if used else 0
        # 未获派发授权的预留到期自动释放。已授权的请求可能正在执行，须保留额度直至结果明确。
        reserved = tx.one("""SELECT COALESCE(SUM(r.units),0) AS total FROM usage_reservations r
                             LEFT JOIN usage_dispatches d ON d.reservation_id=r.reservation_id
                             WHERE r.school_id=? AND r.period=? AND r.resource=? AND r.actual_units IS NULL
                             AND (r.expires_at>? OR d.started_at IS NOT NULL)""", (*bucket, now))
        reserved = int(reserved["total"])
        return {"limit": limit, "used": used, "reserved": reserved, "available": max(0, limit-used-reserved)}

    def _summary(self, tx, school, limits):
        now = self._now(tx)
        period = self._period(now)
        resources = {resource: self._balance(tx, school, period, resource,
                                             limits[resource + "_limit"] if limits else 0, now)
                     for resource in ("text", "media")}
        return {"period": period, **resources}

    def quota(self, school):
        with self.store.transaction() as tx:
            return self._summary(tx, school, self._limits(tx, school))

    def configure(self, school, text_limit, media_limit):
        conflict = ("ON DUPLICATE KEY UPDATE text_limit=?, media_limit=?" if self.mysql else
                    "ON CONFLICT(school_id) DO UPDATE SET text_limit=?, media_limit=?")
        with self.store.transaction(write=True) as tx:
            tx.execute("INSERT INTO usage_limits (school_id,text_limit,media_limit) VALUES (?,?,?) " + conflict,
                       (school, text_limit, media_limit, text_limit, media_limit))
            return self._summary(tx, school, {"text_limit": text_limit, "media_limit": media_limit})

    @staticmethod
    def _reservation(tx, owner, field, identifier):
        # 查询字段由服务端调用点固定选择，客户端仅提供标识值。
        return tx.one(f"""SELECT r.*,d.started_at FROM usage_reservations r
                          LEFT JOIN usage_dispatches d ON r.reservation_id=d.reservation_id
                          WHERE r.school_id=? AND r.caller=? AND r.actor_type=? AND r.actor_id=?
                          AND r.{field}=?""", (*owner, identifier))

    def reserve(self, ctx, body):
        owner = self._owner(ctx)
        school = owner[0]
        with self.store.transaction(write=True) as tx:
            limits = self._limits(tx, school, lock=True)
            now = self._now(tx)
            row = self._reservation(tx, owner, "request_id", body.request_id)
            if row:
                if (row["resource"], row["units"], row["ttl_seconds"]) != (body.resource, body.units, body.ttl_seconds):
                    raise HTTPException(409, "Reservation key already used with different terms")
                return self._view(row, now)
            period = self._period(now)
            limit = limits[body.resource + "_limit"] if limits else 0
            if not limit or self._balance(tx, school, period, body.resource, limit, now)["available"] < body.units:
                raise HTTPException(429, {"code": "quota_exhausted", "resource": body.resource,
                                          "fallback": "text" if body.resource == "media" else "deferred"})

            reservation_id = uuid4().hex
            expires = now + body.ttl_seconds
            tx.execute("""INSERT INTO usage_reservations (reservation_id,school_id,caller,actor_type,actor_id,
                          request_id,period,resource,units,ttl_seconds,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                       (reservation_id, *owner, body.request_id, period, body.resource, body.units, body.ttl_seconds, expires))
            return {"reservation_id": reservation_id, "resource": body.resource, "units": body.units,
                    "actual_units": None, "expires_at": expires, "state": "reserved"}

    def begin(self, ctx, reservation_id):
        """派发前确认有效的文字预留。此步保留额度，实际用量待结算。"""
        owner = self._owner(ctx)
        with self.store.transaction(write=True) as tx:
            self._limits(tx, owner[0], lock=True)
            now = self._now(tx)
            row = self._reservation(tx, owner, "reservation_id", reservation_id)
            if not row:
                raise HTTPException(404, "Unknown reservation")
            if ctx["actor_type"] != "student" or (row["resource"], row["units"]) != ("text", 1):
                raise HTTPException(403, "Only single student text operations can mark dispatch")
            if row["actual_units"] is not None or (row["started_at"] is None and row["expires_at"] <= now):
                raise HTTPException(409, "Reservation unavailable for dispatch")
            if row["started_at"] is None:
                tx.execute("INSERT INTO usage_dispatches (reservation_id,started_at) VALUES (?,?)",
                           (reservation_id, now))
                row["started_at"] = now
            return self._view(row, now)

    def settle(self, ctx, reservation_id, actual):
        owner = self._owner(ctx)
        with self.store.transaction(write=True) as tx:
            self._limits(tx, owner[0], lock=True)
            now = self._now(tx)
            row = self._reservation(tx, owner, "reservation_id", reservation_id)
            if not row:
                raise HTTPException(404, "Unknown reservation")
            if row["actual_units"] is not None:
                if row["actual_units"] != actual:
                    raise HTTPException(409, "Reservation already settled with a different amount")
                return self._view(row, now)
            if row["started_at"] is None and row["expires_at"] <= now:
                raise HTTPException(409, "Reservation expired")
            if actual > row["units"]:
                raise HTTPException(409, "Cannot settle above the reserved amount")
            tx.execute("UPDATE usage_reservations SET actual_units=? WHERE reservation_id=?", (actual, reservation_id))
            conflict = ("ON DUPLICATE KEY UPDATE units=units+?" if self.mysql else
                        "ON CONFLICT(school_id,period,resource) DO UPDATE SET units=units+?")
            tx.execute("INSERT INTO usage_spent (school_id,period,resource,units) VALUES (?,?,?,?) " + conflict,
                       (owner[0], row["period"], row["resource"], actual, actual))
            return self._view({**row, "actual_units": actual}, now)
