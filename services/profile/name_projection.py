"""按简历服务的权威版本更新旧会话使用的显示名。"""


def install(db, engine):
    key = "VARCHAR(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin" if engine == "mysql" else "TEXT"
    with db:
        db.execute(f"""CREATE TABLE IF NOT EXISTS profile_name_projections (
            school_id {key} NOT NULL, user_id {key} NOT NULL, version BIGINT NOT NULL,
            PRIMARY KEY(school_id,user_id))""").close()


def apply(db, engine, user, name, version):
    if not isinstance(name, str) or not name or type(version) is not int or version < 1:
        raise ValueError("Invalid profile revision")
    owner = (user["school_id"], user["id"])
    duplicate = ("ON DUPLICATE KEY UPDATE version=version" if engine == "mysql"
                 else "ON CONFLICT(school_id,user_id) DO NOTHING")
    with db:
        db.execute("INSERT INTO profile_name_projections(school_id,user_id,version) "
                   f"VALUES(?,?,0) {duplicate}", owner).close()
        updated = db.execute("UPDATE profile_name_projections SET version=? "
                             "WHERE school_id=? AND user_id=? AND version<?",
                             (version, *owner, version))
        try:
            # 迟到的网关响应不能替换较新版本的昵称。
            if updated.rowcount:
                db.execute("UPDATE users SET name=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                           (name, user["id"])).close()
        finally:
            updated.close()
