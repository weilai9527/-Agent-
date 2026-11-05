"""验证原生候选网关的上传委派、分析方向脱敏，以及旧任务显式选择策略。"""
import json

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient


def test_native_gateway_upload_and_analysis_forward_only_authorized_data(monkeypatch):
    from services.gateway.native_student import create_app
    from services.profile import candidate

    key = Ed25519PrivateKey.generate()
    for name, value in {
        "IDENTITY_SESSION_MODE": "native", "SERVICE_ID": "gateway", "SERVICE_KEY_ID": "k",
        "PROFILE_SERVICE_URL": "https://profile.test", "CAREER_SERVICE_URL": "https://career.test",
        "SERVICE_SIGNING_KEY": key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                serialization.NoEncryption()).decode(),
    }.items():
        monkeypatch.setenv(name, value)

    # 登录与身份内省由原生网关集成用例覆盖，这里专门核对业务请求的签名、文件和出站字段。
    actor = {"actor_id": "s", "school_id": "school", "actor_type": "student"}
    monkeypatch.setattr(candidate, "resolve_native", lambda request, scope, kind: {**actor, "scopes":[scope]})
    calls = []
    async def dispatch(transport, request):
        service = request.url.host.split(".")[0]
        token = request.headers["Authorization"].split()[1]
        claims = jwt.decode(token, key.public_key(), issuer="gateway", audience=service, algorithms=["EdDSA"])
        assert (claims["school_id"], claims["sub"], claims["actor_type"]) == ("school","s","student")
        assert "cookie" not in request.headers
        body = await request.aread()
        path = request.url.path
        scope, = claims["scopes"]
        calls.append((path,scope))
        if path.endswith("/resume-upload"):
            assert service == "profile" and b'filename="sample.txt"' in body and b"private-source" in body
            result = {"filename":"sample.txt", "profile":{"resume_filename":"sample.txt"}}
        elif path.endswith("/resume-analysis"):
            assert service == "profile" and json.loads(body) == {"force":True}
            result = {"resume_analysis":{"source_hash":"sha","analysis":{"recommended_directions":[
                {"name":"软件开发","evidence":["private-source"]}]}}}
        else:
            values = json.loads(body)
            assert service == "career" and set(values) == {"names","event_id","record"}
            assert values["names"] == ["软件开发"] and values["record"] is True and b"private-source" not in body
            result = {"directions":[{"name":"软件开发","catalog_status":"matched"}]}
        return httpx.Response(200,json=result)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", dispatch)
    with TestClient(create_app()) as client:
        client.cookies.set("identity_student_session","synthetic")
        uploaded=client.post("/api/profile/resume-upload",files={"file":("sample.txt",b"private-source")})
        assert uploaded.status_code==200 and uploaded.json()["profile"]["resume_filename"]=="sample.txt"
        reply=client.post("/api/profile/resume-analysis",json={"force":True})
        assert reply.status_code==200 and "matched" in reply.text
        assert calls == [("/api/profile/resume-upload","profile.upload"),
                         ("/api/profile/resume-analysis","profile.analyze"),("/v1/catalog/suggestions","catalog.suggest")]


def test_legacy_resume_never_inherits_general_provider_order(monkeypatch):
    from fastapi import HTTPException
    import pytest
    from services.profile.privacy import external_enabled

    monkeypatch.setenv("FOLLOWUP_PROVIDER_ORDER", "openai,custom")
    for key in ("JOB_MATCH_PROVIDER_ORDER", "RESUME_ANALYSIS_PROVIDER_ORDER"):
        monkeypatch.delenv(key, raising=False)
        assert not external_enabled(key)
        monkeypatch.setenv(key, "local")
        assert not external_enabled(key)
        monkeypatch.setenv(key, "openai,custom")
        with pytest.raises(HTTPException) as error:
            external_enabled(key)
        assert error.value.status_code == 503
        monkeypatch.setenv(key, "custom")
        assert external_enabled(key)
