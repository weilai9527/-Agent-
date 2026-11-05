"""学生网关转发档案请求，原生账户信息以身份服务为准。"""
import os

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from services.identity.gateway import candidate_gateway_context, resolve_native, session_mode

from .directions import enrich_response
from shared.service_http import request_json, service_origin
from shared.service_security import service_headers


def student_for(scope, legacy_auth):
    def resolve(request: Request):
        if session_mode() == "native":
            context = resolve_native(request, scope, "student")
            # 原生账户的显示信息只从身份服务取得，不能从同 ID 的旧账号补齐。
            return {"id": context["actor_id"], "school_id": context["school_id"], "_native": True}
        context = candidate_gateway_context(request, scope)
        user = legacy_auth(request)
        if user["id"] != context["actor_id"]:
            raise HTTPException(403, "学生会话已变更。")
        return {**user, "school_id": context["school_id"]}
    return resolve


def student_actor(user):
    return {"actor_id": user["id"], "actor_type": "student", "school_id": user["school_id"]}


async def student_details(user):
    if not user.get("_native"):
        return user
    actor = student_actor(user)
    account = await request_json("identity", "GET", "/internal/students/me", actor=actor, scope="identity.student.read")
    if (not isinstance(account, dict) or account.get("actor_id") != actor["actor_id"]
            or account.get("school_id") != actor["school_id"] or account.get("status") != "normal"
            or account.get("must_change_password") is not False):
        raise HTTPException(403, "学生身份与会话不匹配。")
    return {**user, **{k: account.get(k) for k in ("name", "student_no", "college")}}


def router(auth, form_settings, update_name):
    routes = APIRouter()

    @routes.get("/api/profile")
    async def get(user=Depends(student_for("profile.read", auth))):
        result = await request_json("profile", "GET", "/api/profile", actor=student_actor(user), scope="profile.read")
        if not result["profile"].get("nickname"):
            result["profile"]["nickname"] = (await student_details(user)).get("name") or ""
        return result

    @routes.put("/api/profile")
    async def put(body: dict, user=Depends(student_for("profile.write", auth))):
        actor = student_actor(user)
        result = await request_json("profile", "PUT", "/api/profile", actor=actor, scope="profile.write", body=body)
        # 离线兼容夹具中的姓名投影按档案版本同步，失败后可重试。
        if not user.get("_native"):
            await run_in_threadpool(update_name, user, result["profile"]["nickname"], result["version"])
        return result

    @routes.get("/api/resume-form/settings")
    async def settings(user=Depends(student_for("profile.read", auth))):
        if user.get("_native"):
            return await request_json("profile", "GET", "/api/resume-form/settings", actor=student_actor(user), scope="profile.read")
        return await form_settings(user)

    @routes.get("/api/resume-form")
    async def form(user=Depends(student_for("profile.read", auth))):
        result = await request_json("profile", "GET", "/api/resume-form", actor=student_actor(user), scope="profile.read")
        user = await student_details(user)
        return {**result, "name": user.get("name"), "student_no": user.get("student_no"), "college": user.get("college")}

    @routes.put("/api/resume-form")
    async def save_form(body: dict, user=Depends(student_for("profile.write", auth))):
        return await request_json("profile", "PUT", "/api/resume-form", actor=student_actor(user), scope="profile.write", body=body)

    @routes.get("/api/profile/resume-analysis")
    async def analysis(user=Depends(student_for("profile.read", auth))):
        actor = student_actor(user)
        result = await request_json("profile", "GET", "/api/profile/resume-analysis", actor=actor, scope="profile.read")
        return await enrich_response(result, actor) if user.get("_native") or "CAREER_SERVICE_URL" in os.environ else result

    @routes.post("/api/profile/resume-analysis")
    async def analyze(body: dict | None = None, user=Depends(student_for("profile.analyze", auth))):
        actor = student_actor(user)
        result = await request_json("profile", "POST", "/api/profile/resume-analysis", actor=actor, scope="profile.analyze", body=body or {})
        return await enrich_response(result, actor, record=True) if user.get("_native") or "CAREER_SERVICE_URL" in os.environ else result

    @routes.get("/api/profile/versions")
    async def versions(limit: int = 50, before: int | None = None, user=Depends(student_for("profile.versions.read", auth))):
        return await request_json("profile", "GET", "/api/profile/versions", actor=student_actor(user), scope="profile.versions.read",
                                  params={"limit": limit, **({"before": before} if before is not None else {})})

    @routes.get("/api/profile/versions/{version}")
    async def version(version: int, user=Depends(student_for("profile.versions.read", auth))):
        return await request_json("profile", "GET", f"/api/profile/versions/{version}", actor=student_actor(user), scope="profile.versions.read")

    @routes.post("/api/profile/resume-upload")
    async def upload(file: UploadFile = File(...), user=Depends(student_for("profile.upload", auth))):
        actor = student_actor(user)
        url = service_origin("profile") + "/api/profile/resume-upload"
        limit = 10 * 1024 * 1024
        if file.size is not None and file.size > limit:
            raise HTTPException(413, "简历文件超过 10 MB。")
        content = await file.read(limit + 1)
        if len(content) > limit:
            raise HTTPException(413, "简历文件超过 10 MB。")
        try:
            headers = service_headers("profile", **actor, scopes=["profile.upload"])
            async with httpx.AsyncClient(timeout=40, follow_redirects=False, trust_env=False) as client:
                response = await client.post(url, headers=headers, files={"file": (file.filename, content)})
        except (ValueError, KeyError, httpx.RequestError):
            raise HTTPException(503, "简历上传服务不可用。") from None
        if 400 <= response.status_code < 500:
            raise HTTPException(response.status_code, "上传被拒绝，请检查文件大小、内容、格式及权限。")
        if response.status_code != 200:
            raise HTTPException(502, "简历上传服务未能处理请求。")
        try:
            return response.json()
        except ValueError:
            raise HTTPException(502, "简历上传服务响应无效。") from None

    return routes
