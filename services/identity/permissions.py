"""教职工授权与内部动作映射。服务动作只映射到一个明确的人员权限。"""
import json
import os

from fastapi import HTTPException

CAREER_ACTIONS = (
    "catalog.admin.read", "catalog.write", "catalog.publish", "catalog.import", "catalog.review",
    "posting.admin.read", "posting.write", "posting.sync", "posting.import", "posting.delete",
    "match.admin.read", "jd.read", "jd.write", "jd.delete", "jd.approve",
)
REGISTRATION_ACTIONS = ("registration.read", "registration.export", "registration.import", "registration.issue", "registration.status", "registration.reissue")
STAFF_ACTIONS = (
    "operations.rtc.read", "operations.audit.read",
    *REGISTRATION_ACTIONS, "staff.profile.write", "staff.password.reset",
    "interview.records.read", "interview.templates.read",
    "report.read", "report.review", "report.export", "score.adjust",
    "credential.read", "credential.approve", "credential.issue", "credential.revoke", "credential.reissue",
    "training.read", "training.assign", "analytics.teaching.read", "analytics.practice.assign",
    "organization.read", "organization.manage", "roster.import", "student.read", "student.import", "student.reset", "student.status",
    "permissions.manage", "audit.read", "model.config.read", "model.config.write",
    "program_jobs.read", "program_jobs.write", "profile.settings.read", "profile.settings.write",
    "profile.student.read",
    *CAREER_ACTIONS, "usage.read", "usage.configure", "interview.policy.manage",
)
# 私人教学档案需由本校另行批准；开户和迁移不能用通用管理员权限代授。
NATIVE_EXPLICIT_GRANTS = {"profile.student.read"}
# 只在旧权限含义明确时才映射。报告查看权限不包含复核和导出。
LEGACY_GRANTS = {
    "viewConnectionLogs": ("operations.rtc.read",),
    "viewInterviews": ("interview.records.read",),
    "viewReports": ("report.read",),
    "manageModelConfig": ("model.config.read","interview.templates.read"),
    "manageCatalog": (*CAREER_ACTIONS, "program_jobs.read", "profile.settings.read"),
    "manageStudents": ("organization.read", "roster.import", "student.read", "program_jobs.read", "profile.settings.read"),
    "manageOrganization": ("organization.read", "organization.manage", "program_jobs.read", "program_jobs.write", "profile.settings.read"),
}
WIRE_ACTIONS = {
    "assessment.records.read": "report.read",
    "assessment.history": "report.read", "assessment.review": "report.review",
    "assessment.score": "score.adjust", "assessment.export": "report.export",
}
ROSTER_GRANTS = {"organization.read", "organization.manage", "training.read", "training.assign",
                 "report.read", "report.export", "credential.issue", "credential.reissue",
                 "analytics.teaching.read", "analytics.practice.assign", "score.adjust",
                 "report.review", "credential.approve", "credential.read", "credential.revoke",
                 "match.admin.read", "jd.read", "jd.write", "jd.delete", "jd.approve"}
TEACHER_ONLY = {"score.adjust", "credential.approve", "training.assign", "analytics.practice.assign"}
ADMIN_ONLY = {"operations.audit.read", *REGISTRATION_ACTIONS, "staff.profile.write", "staff.password.reset", "organization.manage", "student.import", "student.reset", "student.status", "permissions.manage", "audit.read",
              "program_jobs.write", "profile.settings.write", "model.config.read", "model.config.write", "interview.policy.manage"}


def legacy_school_id():
    school = os.environ.get("LEGACY_SCHOOL_ID", "")
    if not school or len(school) > 128 or any(c.isspace() or ord(c) < 32 for c in school):
        raise HTTPException(503, "Gateway school is not configured")
    return school


def human_grants(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return set()
    if not isinstance(raw, list):
        return set()
    grants = set()
    for key in raw:
        if isinstance(key, str):
            if key in STAFF_ACTIONS:
                grants.add(key)
            grants.update(LEGACY_GRANTS.get(key, ()))
    return grants


def effective_staff_grants(account):
    """编辑包含查看本项配置，仅对具备相应角色及学校范围的账号生效。"""
    grants = human_grants(account["permissions"])
    if account["actor_type"] == "admin":
        if "program_jobs.write" in grants:
            grants.add("program_jobs.read")
        if account.get("school_wide") == 1 and "profile.settings.write" in grants:
            grants.add("profile.settings.read")
    return grants


def authorize_staff(account, scope):
    role = account["actor_type"]
    if account["status"] != "normal" or role not in {"teacher", "admin"}:
        raise HTTPException(403, "Staff account unavailable")
    grants = effective_staff_grants(account)
    action = WIRE_ACTIONS.get(scope, scope)
    if action == "identity.permissions.self":
        allowed = True  # 在用职员可以发起申请，批准须由另一位有权管理员完成。
    elif action in {"identity.roster.read", "identity.classes.read"}:
        allowed = not grants.isdisjoint(ROSTER_GRANTS)
    else:
        allowed = action in grants
    if action == "profile.settings.write" and account.get("school_wide") != 1:
        raise HTTPException(403, "维护全校简历表单需要全校管理员授权。")
    if action == "interview.policy.manage" and not account.get("school_wide"):
        raise HTTPException(403, "School-wide interview policy requires a school administrator")
    if (not allowed or (action in TEACHER_ONLY and role != "teacher")
            or (action in ADMIN_ONLY and role != "admin")):
        raise HTTPException(403, "Staff action not granted")
