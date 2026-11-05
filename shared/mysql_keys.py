"""检查鉴权实际使用的 MySQL 列是否精确区分标识。逐列检查可发现旧表遗留的不安全排序，同时保留姓名、岗位描述原有的语言排序。"""
from contextlib import closing


EXACT_COLUMNS = {
    "operations": {"ops_events": "school_id category event_id actor_id interview_id event_type request_id"},
    "identity": {
        "identity_login_limits": "bucket",
        "identity_student_credentials": "school_id actor_id student_no",
        "identity_student_grants": "school_id actor_id",
        "identity_student_sessions": "school_id actor_id token_hash",
        "identity_staff": "school_id actor_id email",
        "identity_staff_sessions": "school_id actor_id token_hash",
        "identity_legacy_permission_requests": "school_id id actor_id",
        "identity_permission_requests": "school_id id applicant reviewer request_key",
        "org_colleges": "school_id id", "org_programs": "school_id id college_id",
        "org_classes": "school_id id program_id",
        "org_staff_classes": "school_id staff_id class_id", "org_enrollments": "school_id student_id class_id",
        "org_write_lock": "school_id", "identity_audit": "school_id id actor_id target_id",
        "org_legacy_migration": "school_id", "identity_legacy_organization": "school_id record_id source_table",
        "identity_registrations": "school_id student_no actor_id class_id",
        "identity_staff_password_rotation": "school_id actor_id revision",
        "org_unit_details": "school_id kind unit_id code",
        "identity_registration_backfill": "school_id",
        "identity_cutover": "school_id",
    },
    "training": {
        "training_tasks": "task_id school_id teacher_id request_id job_id source_attempt_id",
        "training_enrollments": "task_id student_id class_id",
        "training_attempts": "attempt_id interview_id task_id student_id request_id",
        "training_completions": "school_id event_id attempt_id",
    },
    "analytics": {
        "analytics_events": "school_id event_id",
        "analytics_attempts": "school_id attempt_id student_id teacher_id class_id task_id",
        "analytics_attempt_context": "school_id attempt_id interview_id",
        "analytics_scores": "school_id attempt_id question_id dimension",
    },
    "usage": {
        "usage_limits": "school_id", "usage_spent": "school_id resource period",
        "usage_reservations": "school_id actor_id actor_type caller request_id reservation_id",
        "usage_dispatches": "reservation_id",
    },
    "credentials": {
        "credential_applications": "school_id student_id id reviewed_by first_serial",
        "teaching_certificates": "serial application_id previous_serial issued_by revoked_by successor kid issue_event revocation_event",
        "credential_issuance_intents": "application_id serial previous_serial issued_by kid",
        "credential_outbox": "event_id school_id",
    },
    "media-context": {"media_interview_context": "resource_key actor_id"},
    "media-rtc": {"media_rtc_session": "school_id actor_id id interview_id task_id role_id candidate_user_id agent_user_id channel_id"},
    "provenance": {"provenance_anchors": "school_key event_id digest binding lease"},
    "profile-settings": {"profile_school_form_settings": "school_id"},
    "profile": {
        "profile_owners": "school_id actor_id", "profile_versions": "school_id actor_id",
        "profile_analysis_runs": "school_id actor_id", "profile_access_audit": "school_id actor_id student_id",
    },
    # 职业库按学校物理隔离。学校标记及用于筛选学生的两列必须精确比较，普通目录文本可以保留原有排序。
    "career": {"career_owner": "school_id", "job_matches": "user_id", "job_jd_submissions": "user_id",
               "program_job_roles": "id program_id job_role_id", "career_program_job_state": "program_id"},
    # 仅独立评估库存放这些表，不能把其外键或排序要求施加到冻结的历史面试库。
    "assessment": {
        "interview_sessions": "user_id", "interview_reports": "user_id",
        "user_skill_stats": "user_id", "assessment_projection_inbox": "student_id school_id",
        "assessment_database_owner": "school_id",
    },
}


def require_exact_columns(read_all, domain):
    expected = {(table, col) for table, columns in EXACT_COLUMNS[domain].items() for col in columns.split()}
    tables = tuple(EXACT_COLUMNS[domain])
    markers = ",".join("?" for _ in tables)
    rows = read_all(f"""SELECT TABLE_NAME AS tbl, COLUMN_NAME AS col, COLLATION_NAME AS cmp_rule
        FROM INFORMATION_SCHEMA.COLUMNS WHERE BINARY TABLE_SCHEMA=BINARY DATABASE() AND BINARY TABLE_NAME IN ({markers})""", tables)
    actual = {(row["tbl"], row["col"]): row["cmp_rule"] for row in rows}
    # 入口拒绝标识中的空白。这两种排序规则都区分大小写与重音；0900_bin 还严格区分末尾空格。
    unsafe = [f"{table}.{col} ({actual.get((table, col)) or 'missing/non-text'})" for table, col in sorted(expected)
              if actual.get((table, col)) not in {"utf8mb4_bin", "utf8mb4_0900_bin"}]
    if unsafe:
        raise RuntimeError(f"Unsafe MySQL identifier collation [{domain}]: {', '.join(unsafe)}. "
                           "Inspect the existing store offline before cutover (deploy/MYSQL-IDENTIFIERS.md).")


def check_legacy_adapter(db, domain):
    """为使用 DB-API 游标的独立服务执行同一套逐列标识校验。"""
    def read_all(sql, params):
        with closing(db.execute(sql, params)) as cursor:
            return cursor.fetchall()
    require_exact_columns(read_all, domain)
