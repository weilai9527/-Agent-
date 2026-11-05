"""用临时学校快照和独立 Ed25519 密钥验证真实应急 HTTP 边界，不启动监听端口。"""
import hashlib
import secrets
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from deploy import emergency


SUMMARY = "/emergency/summary"
STATUS = "/emergency/reports/report-a/status"
PRIVATE = "private-fixture-student@example.invalid"


@dataclass
class Case:
    snapshot: Path
    ticket: Path
    public_key: Path
    key: Ed25519PrivateKey
    token: str
    claims: dict

    @property
    def headers(self):
        return {"Authorization": "Bearer " + self.token}

    def sign(self, *, key=None, **changes):
        data = self.claims | changes
        self.ticket.write_text(jwt.encode(data, key or self.key, algorithm="EdDSA",
                                          headers={"typ":"emergency+jwt"}), encoding="ascii")

    def client(self, peer="127.0.0.1"):
        settings = emergency.Settings("school-a", self.snapshot, self.ticket, self.public_key)
        return TestClient(emergency.create_app(settings), client=(peer, 2048))


@pytest.fixture
def issued(tmp_path):
    snapshot = tmp_path / "private snapshot.sqlite"
    with closing(sqlite3.connect(snapshot)) as db, db:
        db.execute("CREATE TABLE snapshot_meta(format TEXT,school TEXT,as_of TEXT,report_count INTEGER)")
        db.execute("INSERT INTO snapshot_meta VALUES ('school-report-status-v1','school-a','2026-01-01T00:00:00Z',1)")
        db.execute("CREATE TABLE report_status(id TEXT PRIMARY KEY, generation_status TEXT, review_status TEXT)")
        db.execute("INSERT INTO report_status VALUES ('report-a','succeeded','pending')")
    key = Ed25519PrivateKey.generate()
    pem = tmp_path / "approver.pem"
    pem.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    token = secrets.token_urlsafe(36)
    now = int(time.time())
    claims = {"iss":"school-emergency-approver", "aud":"legacy-readonly-rescue",
              "sub":"operator-1","jti":"incident-7","school":"school-a","scope":"emergency.report-status.read",
              "iat":now - 5, "nbf":now - 5, "exp":now + 1800,
              "snapshot_sha256":hashlib.sha256(snapshot.read_bytes()).hexdigest(),
              "bearer_sha256":hashlib.sha256(token.encode()).hexdigest()}
    case = Case(snapshot, tmp_path / "incident.jwt", pem, key, token, claims)
    case.sign()
    return case


def test_only_approved_status_fields_are_disclosed_and_snapshot_is_unchanged(issued, caplog):
    before = issued.snapshot.read_bytes()
    with issued.client() as client:
        for route, expected in (
            (SUMMARY, {"school":"school-a", "snapshot_at":"2026-01-01T00:00:00Z", "reports":1, "read_only":True}),
            (STATUS, {"school":"school-a", "snapshot_at":"2026-01-01T00:00:00Z",
                      "generation_status":"succeeded", "review_status":"pending"}),
        ):
            response = client.get(route, headers=issued.headers)
            assert response.status_code == 200 and response.json() == expected
            assert response.headers["cache-control"] == "no-store"
        assert client.get("/emergency/reports/no-such-report/status", headers=issued.headers).status_code == 404
        assert client.get("/emergency/reports/" + PRIVATE + "/status", headers=issued.headers).status_code == 404
    assert before == issued.snapshot.read_bytes()
    assert not any(issued.snapshot.parent.glob("*.sqlite-*"))
    assert "incident-7" in caplog.text and "operator-1" in caplog.text
    for secret in (issued.token, issued.ticket.read_text(), str(issued.snapshot), PRIVATE):
        assert secret not in caplog.text


@pytest.mark.parametrize("fault", ["signature", "snapshot", "school", "scope", "issuer", "audience",
                                    "expired", "not-yet-valid", "long-window", "missing-ticket", "missing-operator"])
def test_invalid_ticket_or_snapshot_refused_at_startup(issued, fault):
    now = int(time.time())
    if fault == "signature":
        issued.sign(key=Ed25519PrivateKey.generate())
    elif fault == "missing-ticket":
        issued.ticket.unlink()
    elif fault == "missing-operator":
        del issued.claims["sub"]
        issued.sign()
    else:
        changes = {
            "snapshot":{"snapshot_sha256":"0" * 64}, "school":{"school":"school-b"},
            "scope":{"scope":"emergency.write"}, "issuer":{"iss":"some-gateway"}, "audience":{"aud":"identity"},
            "expired":{"iat":now - 60, "nbf":now - 60, "exp":now - 1},
            "not-yet-valid":{"nbf":now + 600}, "long-window":{"exp":issued.claims["iat"] + 3601},
        }
        issued.sign(**changes[fault])
    with pytest.raises((jwt.InvalidTokenError, ValueError, OSError)), issued.client():
        pytest.fail("工单无效时进入了应急应用")


def test_metadata_must_match_school_even_with_a_valid_signature(issued):
    with closing(sqlite3.connect(issued.snapshot)) as db, db:
        db.execute("UPDATE snapshot_meta SET school='school-b'")
    issued.sign(snapshot_sha256=hashlib.sha256(issued.snapshot.read_bytes()).hexdigest())
    with pytest.raises(ValueError), issued.client():
        pytest.fail("已签摘要不能替代校区绑定检查")


def test_signed_snapshot_stays_pinned_after_source_replacement(issued):
    with issued.client() as client:
        expected = client.get(STATUS, headers=issued.headers).json()
        other = issued.snapshot.with_suffix(".replacement")
        other.write_bytes(issued.snapshot.read_bytes())
        with closing(sqlite3.connect(other)) as db, db:
            db.execute("UPDATE report_status SET review_status='approved'")
        other.replace(issued.snapshot)
        reply = client.get(STATUS, headers=issued.headers)
        assert reply.status_code == 200 and reply.json() == expected
    # 下次启动不能把已更换的源库当作旧工单签过的快照。
    with pytest.raises(ValueError), issued.client():
        pytest.fail("启动时没有重新检查源快照摘要")


def test_bearer_and_loopback_are_both_required(issued, caplog):
    with issued.client() as client:
        for headers in [
            {}, {"Cookie":"admin_session=" + issued.token}, {"X-Emergency-Token":issued.token},
            {"Authorization":"Bearer " + issued.ticket.read_text()},
            [("Authorization","Bearer invalid"), ("Authorization","Bearer " + issued.token)],
            issued.headers | {"Cookie":"interview_session=legacy"},
            issued.headers | {"Origin":"https://untrusted.example"},
            issued.headers | {"X-Forwarded-For":"127.0.0.1"},
        ]:
            denied = client.get(STATUS, headers=headers)
            assert denied.status_code in (401, 403) and "review_status" not in denied.text
            assert issued.token not in denied.text
        assert client.get(SUMMARY, params={"token":issued.token}).status_code == 403
        assert client.get(SUMMARY, headers=issued.headers).status_code == 200
    with issued.client(peer="198.51.100.4") as remote:
        for headers in (issued.headers, issued.headers | {"X-Forwarded-For":"127.0.0.1"}):
            assert remote.get(SUMMARY, headers=headers).status_code == 403
    assert issued.token not in caplog.text


def test_expiry_and_revocation_apply_to_an_already_running_app(issued, monkeypatch):
    for invalidate in ("deadline", "removed", "replaced"):
        issued.sign()
        with monkeypatch.context() as local, issued.client() as client:
            assert client.get(STATUS, headers=issued.headers).status_code == 200
            if invalidate == "deadline":
                # 跨过截止边界但保留同一 ASGI 进程及客户端，不依赖真实时间等待。
                local.setattr(emergency, "time", SimpleNamespace(time=lambda: issued.claims["exp"]))
            elif invalidate == "removed":
                issued.ticket.unlink()
            else:
                issued.sign(jti="new-incident")
            for url in (SUMMARY, STATUS):
                reply = client.get(url, headers=issued.headers)
                assert reply.status_code == 403 and "snapshot_at" not in reply.text
                assert client.post(url, headers=issued.headers, json={}).status_code in (403, 404, 405)


def test_even_an_authorized_operator_has_no_legacy_http_or_websocket(issued):
    before = issued.snapshot.read_bytes()
    with issued.client() as client:
        # 这些旧 GET 分别会补建档案、统计或面试官、刷新诊断记录，或披露口令与底层库路径。
        for route in ("/api/profile", "/api/stats/me", "/api/stats/me/dimensions", "/api/interviews/i/agents",
                      "/api/interviews/i/webrtc-events", "/api/health", "/api/admin/health",
                      "/api/admin/snapshot", "/api/admin/connection-logs", "/api/admin/student-accounts/export",
                      "/api/admin/student-accounts/other/temporary-password", "/openapi.json"):
            response = client.get(route, headers=issued.headers)
            assert response.status_code == 404, route
            assert str(issued.snapshot) not in response.text
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            for url in (SUMMARY, STATUS, "/api/interviews", "/api/admin/reports/report-a/score"):
                response = client.request(method, url, headers=issued.headers, json={"review_status":"approved"})
                assert response.status_code in (404, 405), (method, url)
        with pytest.raises(WebSocketDisconnect), client.websocket_connect(
                "/ws/interviews/report-a/qwen/omni-realtime", headers=issued.headers):
            pytest.fail("应急进程接受了 WebSocket 握手")
        assert client.get(STATUS, headers=issued.headers).json()["review_status"] == "pending"
    assert before == issued.snapshot.read_bytes()


@pytest.mark.parametrize("fault", ["view", "review-status", "generation-status", "time", "count"])
def test_signed_but_malformed_snapshot_cannot_return_unapproved_information(issued, fault):
    # 审批签名确认了文件来源；生成快照出现列映射错误时，接口也不能返回任意业务文本。
    with closing(sqlite3.connect(issued.snapshot)) as db, db:
        if fault == "view":
            db.execute("DROP TABLE report_status")
            db.execute("CREATE TABLE unrelated(id TEXT, display_name TEXT)")
            db.execute("INSERT INTO unrelated VALUES ('report-a',?)", (PRIVATE,))
            db.execute("""CREATE VIEW report_status AS SELECT id, display_name AS generation_status,
                       display_name AS review_status FROM unrelated""")
        elif fault == "time":
            db.execute("UPDATE snapshot_meta SET as_of=?", (PRIVATE,))
        elif fault == "count":
            db.execute("UPDATE snapshot_meta SET report_count=?", (PRIVATE,))
        elif fault == "review-status":
            db.execute("UPDATE report_status SET review_status=?", (PRIVATE,))
        else:
            db.execute("UPDATE report_status SET generation_status=?", (PRIVATE,))
    issued.sign(snapshot_sha256=hashlib.sha256(issued.snapshot.read_bytes()).hexdigest())
    try:
        with issued.client() as client:
            route = SUMMARY if fault in ("time", "count") else STATUS
            response = client.get(route, headers=issued.headers)
    except ValueError:
        return  # 启动即拒绝损坏的快照，也符合安全边界。
    assert response.status_code >= 400 and PRIVATE not in response.text


def test_command_line_binds_only_loopback_without_trusting_proxy_headers(issued, monkeypatch):
    import runpy
    from unittest.mock import patch

    for key, value in {"EMERGENCY_SCHOOL_ID":"school-a", "EMERGENCY_SNAPSHOT":str(issued.snapshot),
                       "EMERGENCY_TICKET_FILE":str(issued.ticket), "EMERGENCY_APPROVER_PUBLIC_KEY_FILE":str(issued.public_key),
                       "UVICORN_HOST":"0.0.0.0", "FORWARDED_ALLOW_IPS":"*"}.items():
        monkeypatch.setenv(key, value)
    with patch("uvicorn.run") as serve:
        runpy.run_path(emergency.__file__, run_name="__main__")
    options = serve.call_args.kwargs
    assert (options["host"], options["port"], options["proxy_headers"], options["access_log"]) == (
        "127.0.0.1", 3010, False, False)


@pytest.mark.parametrize("fault", ["duplicate", "bad-id", "extra-view", "trigger", "generated"])
def test_even_signed_snapshot_rejects_ambiguous_or_nonminimal_schema(issued,fault):
    with closing(sqlite3.connect(issued.snapshot)) as db, db:
        if fault == "duplicate":
            db.execute("ALTER TABLE report_status RENAME TO old")
            db.execute("CREATE TABLE report_status(id TEXT,generation_status TEXT,review_status TEXT)")
            db.execute("INSERT INTO report_status SELECT * FROM old")
            db.execute("INSERT INTO report_status VALUES ('report-a','failed','rejected')")
            db.execute("DROP TABLE old")
            db.execute("UPDATE snapshot_meta SET report_count=2")
        elif fault == "bad-id":
            db.execute("UPDATE report_status SET id='cannot/lookup'")
        elif fault == "extra-view":
            db.execute("CREATE VIEW unrelated AS SELECT 1")
        elif fault == "trigger":
            db.execute("CREATE TRIGGER unrelated AFTER UPDATE ON report_status BEGIN SELECT 1; END")
        else:
            db.execute("DROP TABLE report_status")
            db.execute("""CREATE TABLE report_status(id TEXT PRIMARY KEY,generation_status TEXT,
                review_status TEXT GENERATED ALWAYS AS ('approved') VIRTUAL)""")
            db.execute("INSERT INTO report_status(id,generation_status) VALUES ('report-a','succeeded')")
    issued.sign(snapshot_sha256=hashlib.sha256(issued.snapshot.read_bytes()).hexdigest())
    with pytest.raises(ValueError), issued.client():
        pytest.fail("带签名的非最小快照不能进入查询状态")


def test_restoring_observed_revoked_token_does_not_reenable_server(issued):
    approved = issued.ticket.read_bytes()
    with issued.client() as client:
        issued.ticket.unlink()
        assert client.get(SUMMARY,headers=issued.headers).status_code == 403
        issued.ticket.write_bytes(approved)
        assert client.get(SUMMARY,headers=issued.headers).status_code == 403


@pytest.mark.parametrize("replacement", ["restored","link","fifo"])
def test_ticket_path_replacement_fails_without_blocking(issued, replacement):
    import os
    approved = issued.ticket.read_bytes()
    with issued.client() as client:
        old = issued.ticket.with_name("old.jwt")
        issued.ticket.rename(old)
        if replacement=="restored":
            issued.ticket.write_bytes(approved)
        elif replacement=="link":
            issued.ticket.symlink_to(old)
        else:
            if not hasattr(os, "mkfifo"):
                pytest.skip("此平台不提供命名管道文件")
            os.mkfifo(issued.ticket)
        assert client.get(SUMMARY,headers=issued.headers).status_code == 403


@pytest.mark.parametrize("fault", ["expired", "removed"])
def test_revocation_before_response_start_never_releases_status(issued, monkeypatch, fault):
    original = emergency.read_db
    with issued.client() as client:
        def slow_query(path):
            # 此时已取得查询授权；在数据库返回前撤回许可，响应和审计均须按拒绝处理。
            if fault == "expired":
                monkeypatch.setattr(emergency,"time",SimpleNamespace(time=lambda: issued.claims["exp"]))
            else:
                issued.ticket.unlink()
            return original(path)
        monkeypatch.setattr(emergency,"read_db",slow_query)
        response = client.get(STATUS, headers=issued.headers)
        assert response.status_code == 403
        assert all(field not in response.text for field in ("school-a","snapshot_at","generation_status","review_status"))
