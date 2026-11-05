"""学生职业服务网关。浏览器提交岗位描述，职业服务按签名主体读取简历。"""
import os

from fastapi import APIRouter, Depends, HTTPException, Request

from services.profile.candidate import student_actor, student_details, student_for
from services.identity.gateway import session_mode
from shared.service_http import request_json, resource_segment


def router(auth):
    routes = APIRouter()

    def catalog_actor(request: Request):
        cookie = "identity_student_session" if session_mode() == "native" else "interview_session"
        if cookie in request.cookies:
            return student_actor(student_for("catalog.read", auth)(request))
        # 匿名目录限定为部署端明确公开的学校，浏览器不能选择租户。
        school = os.environ.get("PUBLIC_CATALOG_SCHOOL_ID")
        if not school:
            raise HTTPException(401, "请先登录。")
        return {"actor_id": "public-catalog", "actor_type": "system", "school_id": school}

    @routes.get("/api/catalog/versions")
    async def versions(actor=Depends(catalog_actor)):
        return await request_json("career", "GET", "/v1/catalog/versions", actor=actor, scope="catalog.read")

    @routes.get("/api/catalog/tree")
    async def tree(version: str | None = None, actor=Depends(catalog_actor)):
        return await request_json("career", "GET", "/v1/catalog/tree", actor=actor, scope="catalog.read",
                                  params={"version": version} if version else None)

    @routes.get("/api/job-postings")
    async def postings(keyword: str = "", user=Depends(student_for("posting.read", auth))):
        return await request_json("career", "GET", "/v1/job-postings", actor=student_actor(user),
                                  scope="posting.read", params={"keyword": keyword})

    @routes.post("/api/job-matches", status_code=201)
    async def create(body: dict, user=Depends(student_for("match.create", auth))):
        # 只转发岗位输入和已认证的学生信息，简历由职业服务按签名身份读取。
        if "PROFILE_SERVICE_URL" not in os.environ:
            raise HTTPException(503, "岗位匹配须同时启用职业和简历服务。")
        payload = {k: body[k] for k in ("job_posting_id", "jd_text", "job_title", "company") if k in body}
        user = await student_details(user)
        payload["student"] = {k: user.get(k) or "" for k in ("name", "student_no", "college")}
        return await request_json("career", "POST", "/v1/job-matches", actor=student_actor(user),
                                  scope="match.create", body=payload)

    @routes.get("/api/job-matches")
    async def matches(user=Depends(student_for("match.read", auth))):
        return await request_json("career", "GET", "/v1/job-matches", actor=student_actor(user), scope="match.read")

    @routes.get("/api/job-matches/{match_id}")
    async def match(match_id: str, user=Depends(student_for("match.read", auth))):
        return await request_json("career", "GET", "/v1/job-matches/" + resource_segment(match_id),
                                  actor=student_actor(user), scope="match.read")

    return routes
