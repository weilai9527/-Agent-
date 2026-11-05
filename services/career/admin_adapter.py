"""管理网关的职业管理转发逻辑；旧学籍名单仅用于显式离线回归。"""

import functools
import inspect
import json
import os

from fastapi import Depends, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from shared.security_logging import audit_context, bind_actor


MAX_STUDENTS = 10_000
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _student_ids(admin, student_scope, scope_sql, all_rows):
    scope = student_scope(admin)
    if scope is None:  # 仅限已核验且具有全校权限的旧主管理员。
        return None
    condition, params = scope_sql(scope, "users.id")
    rows = all_rows(f"SELECT users.id FROM users WHERE {condition} LIMIT ?", (*params, MAX_STUDENTS + 1))
    if len(rows) > MAX_STUDENTS:
        raise HTTPException(503, "管理范围过大，无法提交完整的学生范围。")
    return [row["id"] for row in rows]


async def read_payload(request):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 1024 * 1024:
            raise HTTPException(413, "请求正文超过 1MB。")
        raw.extend(chunk)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(400, "请求正文必须是 JSON 对象。") from None
    if not isinstance(data, dict):
        raise HTTPException(400, "请求正文必须是 JSON 对象。")
    # 转发前剔除客户端伪造的身份和名单字段，使用真实会话及服务端计算的学籍范围。
    for key in ("actor_id", "actor_type", "school_id", "caller", "scopes", "student_ids"):
        data.pop(key, None)
    return data


async def _workbook_request(method, path, scope, actor, query, upload):
    import httpx
    from shared.service_http import service_origin
    from shared.service_security import service_headers

    url = service_origin("career") + path
    try:
        headers = service_headers("career", **actor, scopes=[scope])
    except (KeyError, ValueError):
        raise HTTPException(503, "未配置职业服务身份。") from None
    files = None
    if upload:
        limit = (10 if scope == "catalog.import" else 5) * 1024 * 1024
        name = upload.filename or ""
        if not name.lower().endswith(".xlsx"):
            raise HTTPException(400, "请上传 .xlsx 文件。")
        content = await upload.read(limit + 1)
        if not content or len(content) > limit:
            raise HTTPException(413 if content else 400, "Excel 文件为空或超过大小限制。")
        files = {"file": (name, content, XLSX_TYPE)}
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            reply = await client.request(method, url, params=query, headers=headers, files=files)
    except httpx.RequestError:
        raise HTTPException(503, "职业服务不可用。") from None
    if reply.status_code >= 300:
        status = reply.status_code if 400 <= reply.status_code < 500 else 502
        raise HTTPException(status, "职业服务拒绝了该表格请求。")
    if files:
        try:
            return reply.json()
        except ValueError:
            raise HTTPException(502, "职业服务返回的导入结果无效。") from None
    if reply.headers.get("Content-Type", "").split(";")[0] != XLSX_TYPE:
        raise HTTPException(502, "职业服务返回的表格格式无效。")
    filename = "job-posting-import-template.xlsx" if path.endswith("/template") else "job-postings.xlsx"
    return Response(reply.content, media_type=XLSX_TYPE,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


async def _native_students(actor):
    from shared.service_http import request_json

    # 组织服务按当前负责班级和在籍关系计算名单。原生账号不查找同 ID 的旧学生。
    classes = await request_json("identity", "GET", "/classes", actor=actor, scope="identity.classes.read")
    try:
        class_ids = [row["class_id"] for row in classes["items"]]
    except (KeyError, TypeError):
        raise HTTPException(502, "身份服务返回了无效的班级列表。") from None
    result = set()
    for offset in range(0, len(class_ids), 500):
        selected = class_ids[offset:offset + 500]
        response = await request_json("identity", "POST", "/classes/roster", actor=actor,
                                      scope="identity.roster.read", body={"class_ids": selected})
        try:
            groups = {row["class_id"]: row["student_ids"] for row in response["classes"]}
            if groups.keys() != set(selected):
                raise ValueError()
            for ids in groups.values():
                if not isinstance(ids, list) or not all(isinstance(uid, str) and uid for uid in ids):
                    raise ValueError()
                result.update(ids)
        except (KeyError, ValueError, TypeError):
            raise HTTPException(502, "身份服务未返回完整的学生名单。") from None
        if len(result) > MAX_STUDENTS:
            raise HTTPException(503, "学生管理范围超过上限。")
    return sorted(result)


def admin_career_route(scope, *, validate_origin, student_scope, scope_sql, all_rows, audit):
    """保留已有 FastAPI 路径、参数和逐动作授权。挂载时确定处理器，运行中断开下游不能切换到旧库。"""
    def decorate(legacy):
        from services.identity.gateway import resolve_native, session_mode
        native = session_mode() == "native"
        if not native and "CAREER_SERVICE_URL" not in os.environ:
            return legacy

        @functools.wraps(legacy)
        async def dispatch(**args):
            from shared.service_http import request_json, resource_segment

            request = args["request"]
            admin = args.get("admin") or args["_admin"]
            method = request.method
            if method != "GET":
                validate_origin(request)
            if native:
                actor = {key: admin[key] for key in ("actor_id", "actor_type", "school_id")}
            else:
                # 旧库无学校列，部署端绑定的学校必须与已验证的会话一致。
                school_id = os.environ.get("LEGACY_SCHOOL_ID")
                if not school_id:
                    raise HTTPException(503, "未配置管理端学校身份。")
                if admin.get("school_id") and admin["school_id"] != school_id:
                    raise HTTPException(403, "账户与旧库的学校绑定不匹配。")
                role = admin.get("actor_type")
                if role not in {"teacher", "admin"}:
                    raise HTTPException(403, "管理端身份类型无效。")
                actor = {"actor_id": admin["id"], "actor_type": role, "school_id": school_id}
            template = request.scope["route"].path.replace("/api/admin/", "/v1/admin/", 1)
            path = template.format(**{key: resource_segment(value) for key, value in request.path_params.items()})
            target = next(reversed(request.path_params.values()), "")
            bind_actor(request, {"id": actor["actor_id"]}, actor["actor_type"])
            audit_context(request, action=scope, target_type="career", target_id=target)
            query = {key: args[key] for key in ("status", "keyword", "version", "jobPostingId", "limit", "mode")
                     if key in args and args[key] is not None}
            if "file" in args or path in ("/v1/admin/job-postings/template", "/v1/admin/job-postings/export"):
                result = await _workbook_request(method, path, scope, actor, query, args.get("file"))
            else:
                body = await read_payload(request) if method in ("POST", "PATCH", "PUT") else None
                if scope.startswith(("match.", "jd.")):
                    # 仅加入网关核实的学生名单，不接受浏览器提供的名单或身份头。
                    if native:
                        ids = await _native_students(actor)
                    else:
                        ids = await run_in_threadpool(_student_ids, admin, student_scope, scope_sql, all_rows)
                        if ids is None and actor["actor_type"] != "admin":
                            raise HTTPException(403, "教师访问需要明确学生范围。")
                    body = {"student_ids": ids, "payload": body}
                result = await request_json("career", method, path, scope=scope, actor=actor, params=query, body=body)
            # 原生主体仅写请求审计，不能用其 ID 引用旧管理账号外键。
            if not native and (method != "GET" or isinstance(result, Response)):
                await run_in_threadpool(audit, request, admin, scope, target_type="career", target_id=target)
                bind_actor(request, {"id": actor["actor_id"]}, actor["actor_type"])
            return result

        if native:
            # 保留原路径、查询参数和上传字段，仅替换旧 Cookie 鉴权依赖。
            def native_admin(request: Request):
                return resolve_native(request, scope, "staff")

            signature = inspect.signature(legacy, eval_str=True)
            dispatch.__signature__ = signature.replace(parameters=[
                p.replace(default=Depends(native_admin)) if p.name in ("admin", "_admin") else p
                for p in signature.parameters.values()
            ])
        return dispatch
    return decorate
