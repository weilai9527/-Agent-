"""将管理端原有登录和导航请求接入身份服务。"""
from fastapi import APIRouter, Request, Response

from .browser import gateway_origins
from .gateway import admin_gateway_context, session_mode
from .session_proxy import forward_session


def _public(account):
    return {
        "id": account["actor_id"], "school_id": account["school_id"], "name": account["name"],
        "email": account["email"], "actorType": account["actor_type"], "role": account["actor_type"],
        "permissions": account["permissions"], "status": "normal",
    }


def _management_permissions(account, grants):
    school_admin = account["actor_type"] == "admin" and account["school_wide"]
    actions = {
        "canReadOrganization": "organization.read" in grants,
        "canManageNativeOrganization": school_admin and "organization.manage" in grants,
        "canImportRoster": "roster.import" in grants,
        "canReadStudentAccounts": "student.read" in grants,
        "canReadStudentProfile": "profile.student.read" in grants,
        "canImportStudentAccounts": school_admin and "student.import" in grants,
        "canResetStudentPasswords": school_admin and "student.reset" in grants,
        "canSetStudentStatus": school_admin and "student.status" in grants,
        "canManageStaff": school_admin and "permissions.manage" in grants,
        "canManageStudentGrants": school_admin and "permissions.manage" in grants,
        "canReadIdentityAudit": school_admin and "audit.read" in grants,
    }
    return {**actions, "canUseSchoolManagement": any(actions.values())}


def mount_staff_auth(app, *, snapshot_extension=None):
    if session_mode() != "native":
        return
    router = APIRouter(prefix="/api/admin")

    @router.post("/auth/login")
    async def login(request: Request, response: Response, body: dict):
        data = await forward_session(request, response, kind="staff", operation="login",
                                     body={k: body[k] for k in ("email", "password", "new_password") if k in body})
        return {"admin": _public(data)}

    @router.get("/auth/me")
    async def me(request: Request, response: Response):
        return {"admin": _public(await forward_session(request, response, kind="staff", operation="me"))}

    @router.post("/auth/logout")
    async def logout(request: Request, response: Response):
        return await forward_session(request, response, kind="staff", operation="logout")

    @router.get("/snapshot")
    async def snapshot(request: Request, response: Response):
        account = await forward_session(request, response, kind="staff", operation="me")
        grants = set(account["permissions"])
        teacher = account["actor_type"] == "teacher"
        # 工作台只公布已有原生接口可执行的动作，学校数据按当前身份读取。
        result = {"admin": _public(account), "identityMode": "native", "assessmentVersioned": True, "permissions": {
            **_management_permissions(account, grants),
            "canReadProgramJobs": "program_jobs.read" in grants,
            "canManageProgramJobs": account["actor_type"] == "admin" and "program_jobs.write" in grants,
            "canReadResumeFormSettings": "profile.settings.read" in grants,
            "canManageResumeFormSettings": account["actor_type"] == "admin" and account["school_wide"]
                                           and "profile.settings.write" in grants,
            "canMaintainStaffProfiles": account["actor_type"] == "admin" and account["school_wide"]
                                        and bool({"staff.profile.write", "staff.password.reset"} & grants),
            "canUseRegistrationBook": account["actor_type"] == "admin" and account["school_wide"]
                                      and bool({"registration.read", "registration.import", "registration.export"} & grants),
            "canManageInterviewPolicy": account["actor_type"] == "admin" and account["school_wide"]
                                       and "interview.policy.manage" in grants,
            "canReadAgentTemplates": "interview.templates.read" in grants,
            "canViewConnectionLogs": "operations.rtc.read" in grants,
            "canViewAudit": bool(account["school_wide"] and not teacher and "operations.audit.read" in grants),
            "canRequestStaffAccess": True, "canUseSchoolManagement": True,
            "canViewTraining": bool(grants & {"training.read", "analytics.teaching.read"}),
            "canReadUsage": not teacher and "usage.read" in grants,
            "canManageUsage": not teacher and "usage.configure" in grants,
            "canReadSchoolInterviews": "interview.records.read" in grants,
            "canReadSchoolReports": "report.read" in grants,
            "canReadTrainingReports": teacher and "report.read" in grants,
            "canExportReports": "report.export" in grants,
            "canAssignTraining": teacher and "training.assign" in grants,
            "canAssignPractice": teacher and "analytics.practice.assign" in grants,
            "canReviewReports": teacher and "report.review" in grants,
            "canAdjustScores": teacher and "score.adjust" in grants,
            "canApproveCredentials": teacher and "credential.approve" in grants,
            "canViewCredentials": "credential.read" in grants,
            "canIssueCredentials": "credential.issue" in grants,
            "canReissueCredentials": "credential.reissue" in grants,
            "canRevokeCredentials": "credential.revoke" in grants,
            "canViewCatalog": "catalog.admin.read" in grants,
            "canWriteCatalog": "catalog.write" in grants,
            "canImportCatalog": "catalog.import" in grants,
            "canPublishCatalog": "catalog.publish" in grants,
            "canViewJobPostings": "posting.admin.read" in grants,
        }}
        if snapshot_extension is not None:
            await snapshot_extension(account, result)
        return result

    replacement = {r.path for r in router.routes}
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") not in replacement]
    app.include_router(router)

    # 原生名录路由仅在原生管理入口注册，通过已签名中继向身份服务读取当前数据。
    from services.gateway.routes import _endpoint
    origins = gateway_origins("staff")
    for method, path, action in (
        ("GET", "/v1/staff/{staff_id}/profile", "staff.profile.write"),
        ("PATCH", "/v1/staff/{staff_id}/profile", "staff.profile.write"),
        ("GET", "/v1/staff/{staff_id}/password-reset", "staff.password.reset"),
        ("POST", "/v1/staff/{staff_id}/password-reset", "staff.password.reset"),
        ("GET", "/v1/registrations", "registration.read"),
        ("GET", "/v1/registrations/export", "registration.export"),
        ("POST", "/v1/organization/import-workbook", "organization.manage"),
        ("POST", "/v1/registrations/import", "registration.import"),
        ("POST", "/v1/registrations/import-xlsx", "registration.import"),
        ("POST", "/v1/registrations/issue", "registration.issue"),
        ("POST", "/v1/registrations/reissue", "registration.reissue"),
        ("POST", "/v1/registrations/apply", "registration.status"),
        ("POST", "/v1/registrations/revoke", "registration.status"),
        ("POST", "/v1/registrations/archive", "registration.status"),
        ("POST", "/v1/registrations/restore", "registration.status"),
        ("GET", "/v1/me/permission-requests", "identity.permissions.self"),
        ("POST", "/v1/me/permission-requests", "identity.permissions.self"),
        ("GET", "/v1/permission-requests", "permissions.manage"),
        ("POST", "/v1/permission-requests/{request_id}/decision", "permissions.manage"),
        ("GET", "/v1/staff", "permissions.manage"),
        ("GET", "/v1/students", "student.read"),
        ("GET", "/v1/students/{student_id}/grants", "permissions.manage"),
        ("PUT", "/v1/students/{student_id}/grants", "permissions.manage"),
        ("GET", "/v1/classes/{class_id}/roster", "organization.read"),
        ("GET", "/v1/classes/{class_id}/staff", "organization.manage"),
        ("PUT", "/v1/classes/{class_id}/staff", "organization.manage"),
        ("GET", "/v1/organization/roster-candidates", "roster.import"),
    ):
        app.add_api_route("/api/admin/identity" + path,
                          _endpoint("identity", method, path, action, admin_gateway_context, origins),
                          methods=[method], name="native-school." + method + path)
