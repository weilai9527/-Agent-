"""简历表单学院和专业。组织、已发布目录、管理员补充选项依次提供数据。"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from shared.service_http import request_json
from shared.service_security import require_service
from . import settings_store

router = APIRouter()


def role(scope, allowed):
    def check(actor=Depends(require_service("profile", scope))):
        if actor["actor_type"] not in allowed:
            raise HTTPException(403, "当前身份无权查看或维护此配置。")
        return actor
    return Depends(check)


def merge(*sources):
    # 按名称保持旧表单的优先级。同名学院只在较高优先级没有专业时才使用下一来源；
    # 同一来源中不同学院编号可能显示同名，合并时保留首个编号并去重专业。
    result = {}
    for colleges in sources:
        already_filled = {k for k, item in result.items() if item["majors"]}
        for college in colleges:
            name = college["name"]
            if name in already_filled:
                continue
            combined = result.setdefault(name, {"id": college["id"], "name": name, "majors": {}})
            for major in college["majors"]:
                combined["majors"].setdefault(major["name"], major)
    return [{**item, "majors": list(item["majors"].values())} for item in result.values()]


async def options(service, path, scope, actor):
    data = await request_json(service, "GET", path, actor=actor, scope=scope)
    if not isinstance(data, dict) or data.get("school_id") != actor["school_id"]:
        raise HTTPException(502, "选项来源返回了错误的学校标识。")
    try:
        colleges = data.get("colleges")
        if not isinstance(colleges, list) or any(not isinstance(c, dict) or "majors" not in c for c in colleges):
            raise ValueError()
        return settings_store.normalize(colleges, manual=False)
    except ValueError:
        raise HTTPException(502, "选项来源返回的学院或专业无效。") from None


@router.get("/api/resume-form/settings")
async def student_settings(request: Request, actor=role("profile.read", {"student"})):
    # 每个来源必须明确返回本校结果。无发布目录返回空列表，断网、权限错误及缺失路由均向上传递。
    organization, catalog, custom = await asyncio.gather(
        options("identity", "/internal/resume-form/organization", "organization.options.read", actor),
        options("career", "/internal/resume-form/catalog", "catalog.read", actor),
        run_in_threadpool(settings_store.read, request.app.state.db, actor["school_id"]),
    )
    return {"colleges": merge(organization, catalog, custom["colleges"])}


async def authorize_staff(actor, operation):
    # 刷新账号状态与本校授权，防止网关验权后账号被停用或校级权限被收回。
    action = "profile.settings." + operation
    response = await request_json("identity", "GET", "/internal/staff/resume-form-settings/" + operation,
                                  actor=actor, scope=action)
    expected = {key: actor[key] for key in ("school_id", "actor_id", "actor_type")}
    if response != {**expected, "action": action}:
        raise HTTPException(403, "无法核验当前学校的配置授权。")


@router.get("/api/admin/resume-form-settings")
async def admin_settings(request: Request, actor=role("profile.settings.read", {"admin", "teacher"})):
    await authorize_staff(actor, "read")
    return await run_in_threadpool(settings_store.read, request.app.state.db, actor["school_id"])


@router.put("/api/admin/resume-form-settings")
async def update_admin_settings(body: dict, request: Request, actor=role("profile.settings.write", {"admin"})):
    await authorize_staff(actor, "write")
    expected = body.get("expected_revision")
    if (body.keys() - {"colleges","expected_revision"}
            or expected is not None and (type(expected) is not int or not 0 <= expected <= 2**63-1)):
        raise HTTPException(400, "请求字段或配置版本无效。")
    try:
        colleges = settings_store.normalize(body.get("colleges"), manual=True)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return await run_in_threadpool(settings_store.replace, request.app.state.db, actor["school_id"],
                                   actor["actor_id"], colleges, expected_revision=expected)
