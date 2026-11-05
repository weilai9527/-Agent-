"""为简历和职业服务按当前身份提供组织选项；原生组织表仅在身份服务中读取。"""
from fastapi import APIRouter, Depends, HTTPException, Request

from shared.service_security import require_service
from .organization import _school_wide, _visible_classes
from .permissions import human_grants
from .staff import require_staff

router = APIRouter()


def active_options(tx, school):
    colleges = tx.all("""SELECT id,name FROM org_colleges
        WHERE school_id=? AND status='active' ORDER BY name,id""", (school,))
    programs = tx.all("""SELECT p.id,p.name,p.college_id FROM org_programs p
        JOIN org_colleges c ON c.school_id=p.school_id AND c.id=p.college_id
        WHERE p.school_id=? AND p.status='active' AND c.status='active' ORDER BY p.name,p.id""", (school,))
    return colleges, programs


@router.get("/internal/resume-form/organization")
def student_options(request: Request, actor=Depends(require_service("identity", "organization.options.read"))):
    """学生可获取本校的活动专业名称，不暴露班级、教师和学生名册。"""
    school = actor["school_id"]
    if actor["actor_type"] != "student" or actor["caller"] != "profile":
        raise HTTPException(403, "仅允许简历服务查询当前学生的选项。")
    with request.app.state.store.transaction() as tx:
        student = tx.one("""SELECT actor_id FROM identity_student_credentials
            WHERE school_id=? AND actor_id=? AND status='normal' AND must_change_password=0""",
            (school, actor["actor_id"]))
        if not student:
            raise HTTPException(403, "学生账号当前不可用。")
        colleges, programs = active_options(tx, school)
    majors = {c["id"]: [] for c in colleges}
    for program in programs:
        majors[program["college_id"]].append({"id": program["id"], "name": program["name"]})
    return {"school_id": school, "colleges": [{**c, "majors": majors[c["id"]]} for c in colleges]}


def program_options(action):
    def options(request: Request, actor=Depends(require_service("identity", action))):
        if actor["caller"] != "career":
            raise HTTPException(403, "仅允许职业服务核验专业管理范围。")
        school = actor["school_id"]
        with request.app.state.store.transaction() as tx:
            staff = require_staff(tx, actor, action)
            edit_grant = staff["actor_type"] == "admin" and "program_jobs.write" in human_grants(staff["permissions"])
            if _school_wide(staff):
                colleges, programs = active_options(tx, school)
                editable = {p["id"] for p in programs} if edit_grant else set()
            else:
                # 有权查看某个班即可查看该班所属专业。关联岗位影响整个专业，
                # 写入还须覆盖该专业的全部活动班级，不能借一个班的授权修改其它班。
                groups = _visible_classes(tx, actor)
                colleges = list({r["college_id"]: {"id": r["college_id"], "name": r["college_name"]} for r in groups}.values())
                programs = list({r["program_id"]: {"id": r["program_id"], "college_id": r["college_id"],
                                                   "name": r["program_name"]} for r in groups}.values())
                editable = set()
                if edit_grant and programs:
                    outside = tx.all("""SELECT DISTINCT c.program_id FROM org_classes c WHERE c.school_id=?
                        AND c.status='active' AND NOT EXISTS (SELECT 1 FROM org_staff_classes a
                          WHERE a.school_id=c.school_id AND a.class_id=c.id AND a.staff_id=?)""",
                        (school, actor["actor_id"]))
                    editable = {p["id"] for p in programs} - {r["program_id"] for r in outside}
        return {"school_id": school, "actor_id": actor["actor_id"], "actor_type": actor["actor_type"],
                "colleges": colleges, "programs": [{**p, "canEdit": p["id"] in editable} for p in programs],
                "canEdit": bool(editable)}
    return options


router.add_api_route("/internal/staff/program-job-options", program_options("program_jobs.read"), methods=["GET"])
router.add_api_route("/internal/staff/program-job-options/write", program_options("program_jobs.write"), methods=["GET"])


def check_settings(action):
    def authorize(request: Request, actor=Depends(require_service("identity", action))):
        if actor["caller"] != "profile":
            raise HTTPException(403, "仅允许简历服务核验表单设置权限。")
        with request.app.state.store.transaction() as tx:
            require_staff(tx, actor, action)
        return {k: actor[k] for k in ("school_id", "actor_id", "actor_type")} | {"action": action}
    return authorize


for access in ("read", "write"):
    router.add_api_route(f"/internal/staff/resume-form-settings/{access}",
                         check_settings("profile.settings." + access), methods=["GET"])
