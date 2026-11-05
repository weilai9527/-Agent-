"""仅从操作员核验过的单校只读快照执行一次身份切换。"""
import argparse
import json

from shared.service_db import ServiceDatabase
from . import candidate, organization, organization_details, registrations
from .app import initialize
from .permissions import NATIVE_EXPLICIT_GRANTS, STAFF_ACTIONS, human_grants, legacy_school_id


def _check_separate_stores(source, target):
    if source.engine == target.engine == "sqlite":
        if not source._path.is_file():
            raise ValueError("Expected an existing SQLite snapshot")
        if target._path.exists() and source._path.samefile(target._path):
            raise ValueError("Identity target must be separate from the source")
    if source.engine == target.engine == "mysql":
        keys = ("host", "port", "database")
        if all(source._mysql_options[k] == target._mysql_options[k] for k in keys):
            raise ValueError("Identity target must be separate from the source")


def migrate(source, target, school, master_email):
    if school != legacy_school_id():
        raise ValueError("Source must be bound to LEGACY_SCHOOL_ID")
    _check_separate_stores(source, target)
    initialize(target)
    counts = {}
    with source.transaction() as snapshot, target.transaction(write=True) as tx:
        organization.lock_school(tx, target, school)
        if tx.one("SELECT school_id FROM identity_cutover WHERE school_id=?", (school,)):
            organization_details.backfill(tx, school)
            registrations.backfill(tx, school, snapshot, source.engine)
            return {"already_migrated": True}
        # 拒绝合并独立命名空间或覆盖已经授予的原生权限。
        for table in ("identity_staff", "identity_student_credentials", "org_colleges"):
            if tx.one(f"SELECT school_id FROM {table} WHERE school_id=? LIMIT 1", (school,)):
                raise ValueError("Destination school already contains identity data")
        staff = snapshot.all("SELECT * FROM admin_users")
        master_email = master_email.lower().strip()
        if not master_email or not any(row["email"].lower() == master_email and row["status"] == "normal" for row in staff):
            raise ValueError("The named school administrator must already exist and be enabled")
        for row in staff:
            if row.get("school_id", school) != school:
                raise ValueError("Source staff outside bound school")
            email = row["email"].lower()
            master = email == master_email
            actor_type = "admin" if master else row.get("actor_type", "admin")
            if actor_type not in {"teacher", "admin"}:
                raise ValueError("Unknown staff account type")
            grants = set(STAFF_ACTIONS) if master else human_grants(row.get("permissions"))
            grants -= NATIVE_EXPLICIT_GRANTS
            tx.execute("""INSERT INTO identity_staff
                       (school_id,actor_id,email,name,password_hash,actor_type,status,permissions,school_wide)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                       (school, row["id"], email, row["name"], row["password_hash"], actor_type,
                        row["status"], json.dumps(sorted(grants)), int(master)))
        counts["staff"] = len(staff)
        counts["students"] = candidate.migrate_legacy(tx, snapshot, school)
        organization.migrate_legacy(tx, snapshot, school)
        organization_details.backfill(tx, school)
        registrations.backfill(tx, school, snapshot, source.engine)
        # 待审批记录只供学校后续审核。迁移不得直接授予申请中的权限。
        requests = snapshot.all("SELECT * FROM admin_permission_requests")
        for row in requests:
            if row.get("school_id", school) != school:
                raise ValueError("Source permission request outside bound school")
            tx.execute("""INSERT INTO identity_legacy_permission_requests
                       (school_id,id,actor_id,legacy_record) VALUES (?,?,?,?)""",
                       (school, row["id"], row["admin_user_id"], json.dumps(row, default=str, ensure_ascii=False)))
        counts["permission_requests"] = len(requests)
        tx.execute("INSERT INTO identity_cutover (school_id) VALUES (?)", (school,))
        organization.audit(tx, {"school_id": school, "actor_id": "migration"}, "identity.cutover", school)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--school", required=True)
    parser.add_argument("--master-email", required=True)
    args = parser.parse_args()
    source = ServiceDatabase.from_env("identity_source")
    target = ServiceDatabase.from_env("identity")
    print(json.dumps(migrate(source, target, args.school, args.master_email)))


if __name__ == "__main__":
    main()
