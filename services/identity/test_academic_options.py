"""用同名账号和专业验证组织查询的租户、角色与完整专业范围边界。"""
import json
import os
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from services.identity.app import app
from shared.service_security import service_headers


def test_scoped_manager_must_cover_entire_program_and_keep_current_grant(monkeypatch, tmp_path):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    scopes = ["program_jobs.read", "program_jobs.write", "profile.settings.read", "profile.settings.write"]
    policy = {issuer: {"schools": ["A", "a"], "keys": {"k": public},
                       "grants": {"identity": {"admin": scopes, "teacher": scopes}}}
              for issuer in ("career", "profile", "unexpected")}
    monkeypatch.setenv("IDENTITY_DB_ENGINE", "sqlite")
    monkeypatch.setenv("IDENTITY_SQLITE_PATH", str(tmp_path / "identity.sqlite"))
    monkeypatch.setenv("SERVICE_KEY_ID", "k")
    monkeypatch.setenv("SERVICE_ID", "identity")
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(policy))
    monkeypatch.setenv("SERVICE_SIGNING_KEY", key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())

    with TestClient(app) as client:
        store = app.state.store
        with store.transaction(write=True) as tx:
            for school in ("A", "a"):
                tx.execute("INSERT INTO identity_staff VALUES (?,?,?,'unused','教务','admin','normal',?,0)",
                           (school, "mgr", "same@example.test", json.dumps(["program_jobs.write","profile.settings.write"])))
                tx.execute("INSERT INTO org_colleges VALUES (?,'c',?,'active')", (school, school+"学院"))
                for i in (1, 2):
                    tx.execute("INSERT INTO org_programs VALUES (?,?,'c',?,'active')",
                               (school, "p"+str(i), school+"专业"+str(i)))
                for cls, program in (("mine", "p1"), ("sibling", "p1"), ("other", "p2")):
                    tx.execute("INSERT INTO org_classes VALUES (?,?,?,?,'active')", (school,cls,program,cls))
            tx.execute("INSERT INTO org_staff_classes VALUES ('A','mgr','mine')")
            tx.execute("INSERT INTO org_staff_classes VALUES ('a','mgr','other')")

        def get(path, action, school="A", caller="career"):
            with patch.dict(os.environ, SERVICE_ID=caller):
                headers = service_headers("identity", actor_id="mgr", actor_type="admin", school_id=school, scopes=[action])
            return client.get(path, headers=headers)

        path = "/internal/staff/program-job-options"
        assert get(path, "program_jobs.read", caller="unexpected").status_code == 403
        initial = get(path, "program_jobs.read").json()
        assert [(p["id"], p["canEdit"]) for p in initial["programs"]] == [("p1", False)]
        alternate = get(path+"/write", "program_jobs.write", school="a").json()
        assert [(p["id"], p["canEdit"]) for p in alternate["programs"]] == [("p2", True)]
        settings = "/internal/staff/resume-form-settings/"
        for op in ("read", "write"):
            assert get(settings+op, "profile.settings."+op, caller="profile").status_code == 403
        with store.transaction(write=True) as tx:
            tx.execute("INSERT INTO org_staff_classes VALUES ('A','mgr','sibling')")
        assert get(path+"/write", "program_jobs.write").json()["programs"][0]["canEdit"]
        with store.transaction(write=True) as tx:
            tx.execute("UPDATE identity_staff SET school_wide=1 WHERE school_id='A'")
        assert get(settings+"write", "profile.settings.write", caller="profile").status_code == 200
        with store.transaction(write=True) as tx:
            tx.execute("UPDATE identity_staff SET permissions='[]' WHERE school_id='A'")
        assert get(path, "program_jobs.read").status_code == 403
        assert get(settings+"write", "profile.settings.write", caller="profile").status_code == 403


def test_teacher_cannot_gain_read_scope_from_an_ineligible_write_grant():
    from services.identity.permissions import ADMIN_ONLY, authorize_staff
    from fastapi import HTTPException
    import pytest

    writes = {"program_jobs.write", "profile.settings.write"}
    assert writes <= ADMIN_ONLY
    account = {"actor_type": "teacher", "school_wide": 1, "permissions": list(writes), "status": "normal"}
    for scope in writes | {"program_jobs.read", "profile.settings.read"}:
        with pytest.raises(HTTPException) as denied:
            authorize_staff(account, scope)
        assert denied.value.status_code == 403
