"""验证原生学校策略的授权边界，教师或其他学校的管理员不能更改本校策略。"""
import subprocess
import sys
import textwrap
from pathlib import Path

from services.identity.permissions import authorize_staff
from fastapi import HTTPException
import pytest


def test_policy_action_requires_school_admin():
    row = dict(actor_type="admin", school_wide=True, status="normal", permissions=["interview.policy.manage"])
    authorize_staff(row, "interview.policy.manage")
    for change in (dict(school_wide=False), dict(actor_type="teacher"), dict(permissions=[])):
        with pytest.raises(HTTPException) as denied:
            authorize_staff({**row, **change}, "interview.policy.manage")
        assert denied.value.status_code == 403


def test_signed_policy_updates_are_school_bound_and_audited(tmp_path):
    import os
    project = Path(__file__).resolve().parents[2]
    env = {k: os.environ[k] for k in ("PATH", "PYTHONPATH", "TMPDIR") if k in os.environ}
    env.update(APP_ENV="test", SERVICE_ID="interview", LEGACY_SCHOOL_ID="a", INTERVIEW_DB_ENGINE="sqlite",
               ASSESSMENT_STORAGE_MODE="isolated", INTERVIEW_SQLITE_PATH=str(tmp_path / "source.sqlite"))
    code = """
        import json, os, time
        import jwt
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from fastapi.testclient import TestClient
        from services.interview.app import app, runtime
        private = Ed25519PrivateKey.generate()
        pem = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        rule = {"keys":{"one":pem.decode()}, "schools":["a","b"],
                "grants":{"interview":{"admin":["interview.policy.manage"],"teacher":["interview.policy.manage"]}}}
        os.environ["SERVICE_TRUST_POLICY"] = json.dumps({"admin-gateway":rule,"student-gateway":rule})
        def headers(caller="admin-gateway", school="a", role="admin"):
            now = int(time.time())
            claims = {"iss":caller, "aud":"interview", "sub":"manager", "school_id":school,
                      "actor_type":role, "scopes":["interview.policy.manage"],"iat":now,"exp":now+40,"jti":"policy-test"}
            token = jwt.encode(claims, private, algorithm="EdDSA", headers={"kid":"one", "typ":"service+jwt"})
            return {"Authorization":"Bearer "+token}
        client = TestClient(app)
        url = "/api/admin/interviewer-policy"
        for bad in (headers(school="b"), headers(role="teacher"), headers(caller="student-gateway")):
            assert client.get(url, headers=bad).status_code == 403
        original = client.get(url, headers=headers()).json()
        change = {**original["policy"], "studentCanChoose": not original["policy"]["studentCanChoose"]}
        body = {"expected_revision":original["revision"],"policy":change}
        updated = client.put(url, json=body, headers=headers()).json()
        assert updated["policy"] == change and updated["revision"] != original["revision"]
        assert client.put(url, json=body, headers=headers()).json() == updated
        assert client.put(url, json={**body,"policy":original["policy"]}, headers=headers()).status_code == 409
        audit = runtime.all_rows("SELECT school_id, actor_id, old_digest, new_digest FROM interview_policy_changes")
        assert audit == [dict(school_id="a",actor_id="manager",old_digest=original["revision"],new_digest=updated["revision"])]
    """
    result = subprocess.run([sys.executable, "-c", textwrap.dedent(code)], env=env, cwd=project,
                            capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stderr
