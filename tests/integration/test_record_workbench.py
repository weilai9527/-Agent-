"""在独立进程中验证两个归属服务。临时目录只复制源码，名单服务由进程内接口模拟。"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize("owner,mode", [("interview", "shared"), ("interview", "isolated"),
                                         ("assessment", "shared"), ("assessment", "isolated")])
def test_workbench(tmp_path, owner, mode):
    root = Path(__file__).resolve().parents[2]
    for part in ("backend/src", "backend/rtc_token_lib", "services", "shared"):
        for source in (root / part).rglob("*.py"):
            dest = tmp_path / source.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
    shutil.copyfile(__file__, tmp_path / "exercise.py")
    env = {k: os.environ[k] for k in ("PATH", "TMPDIR") if k in os.environ}
    prefix = owner.upper() + "_"
    env.update(APP_ENV="test", SERVICE_ID=owner, LEGACY_SCHOOL_ID="school", ASSESSMENT_STORAGE_MODE=mode,
               IDENTITY_SESSION_MODE="native", SERVICE_KEY_ID="local")
    env.update({prefix + "DB_ENGINE": "sqlite", prefix + "SQLITE_PATH": str(tmp_path / "owner.sqlite")})
    result = subprocess.run([sys.executable, "exercise.py"], cwd=tmp_path, env=env, capture_output=True,
                            text=True, timeout=60)
    if mode == "shared":
        assert result.returncode != 0 and "独立存储" in result.stderr, result.stderr
        assert not (tmp_path / "owner.sqlite").exists()
    else:
        assert result.returncode == 0, result.stderr


def exercise():
    from importlib import import_module
    from unittest.mock import patch
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fastapi import HTTPException
    from fastapi.testclient import TestClient
    from services import school_records
    from shared.service_security import service_headers

    owner = os.environ["SERVICE_ID"]
    app = import_module("services." + owner + ".app").app
    from services.interview.storage import db

    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                           serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    wire = owner + ".records.read"
    os.environ["SERVICE_SIGNING_KEY"] = "test-workbench-cursor"
    os.environ["SERVICE_TRUST_POLICY"] = json.dumps({"staff": {"keys": {"local": public}, "schools": ["school","other"],
                                                       "grants": {owner: {"teacher": [wire], "admin": [wire]}}}})

    def credential(who="teacher", school="school"):
        with patch.dict(os.environ, SERVICE_ID="staff", SERVICE_SIGNING_KEY=private):
            return service_headers(owner, actor_id=who, school_id=school, scopes=[wire],
                                   actor_type="admin" if who == "admin" else "teacher")

    roster = [f"s{i:03}" for i in range(102)]
    visited = []
    async def directory(service, method, path, *, actor, scope, body):
        assert (service, method, path, scope) == ("identity", "POST", "/internal/staff/record-students",
                                                 "identity.records.scope")
        if actor["actor_id"] == "revoked" or body.get("class_id") == "forbidden":
            raise HTTPException(403)
        visible = sorted(roster + (["S001"] if actor["actor_type"] == "admin" else []))
        if body.get("college_id") == "empty":
            visible = []
        after = body["after_student"]
        visited.append(after)
        if after is not None:
            visible = [sid for sid in visible if sid > after or (sid == after and body.get("include_start"))]
        return {**actor, "action": school_records.ACTIONS[owner], "has_more": len(visible) > 100,
                "items": [{"student_id": sid, "name": sid, "class_id": "c", "college_id": "college"}
                          for sid in visible[:100]]}

    with TestClient(app) as client, patch.object(school_records, "request_json", directory):
        with db:
            # 除隐藏同名学号和错误学校绑定外，两页目录共有 6 条；最新行在最后一页。
            cases = [
                ("a","s000","completed", "2024-01-31 15:59:59", 2, 2, 80, "succeeded", 1),
                ("b","s000","running",   "2024-01-31 16:00:00", 0, 2, 0, "pending_retry", 1),
                ("c","s000","completed", "2024-02-01 00:00:00", 1, 2, 21, "degraded", 1),
                ("d","s101","completed", "2024-02-01 15:59:59", 1, 1, 0, "degraded", 1),
                ("e","s101","running",   "2024-02-01 16:00:00", None,None,97,"succeeded", 0),
                ("f","s101","draft",     "2024-03-01 00:00:00", None,None,99,"succeeded", 0),
                ("wrong","s000","completed","2025-01-01 00:00:00", 2,2,97,"succeeded",1),
                ("hidden","S001","completed","2025-01-01 00:00:00", 2,2,97,"succeeded",1),
            ]
            for iid,sid,status,stamp,scored,answer,score,generation,fallback in cases:
                db.execute("""INSERT INTO interview_sessions(id,user_id,target_role,status,created_at,updated_at)
                           VALUES (?,?,'岗位',?,?,?)""",(iid,sid,status,stamp,stamp)).close()
                if owner == "assessment":
                    db.execute("""INSERT INTO interview_reports(id,interview_id,user_id,total_score,
                        scored_answer_count,answer_count,grade,pass_recommendation,ability_radar,agent_feedback,
                        timeline_review,summary,suggestions,created_at,updated_at,generation_status,fallback,review_status)
                        VALUES (?,?,?,?,?,?,'A','hold','{}','[]','[]','摘要','[]',?,?,?,?,?)""",
                               (iid,iid,sid,score,scored,answer,stamp,stamp,generation,fallback,
                                "pending" if iid in ("a","b","c","wrong","hidden") else "approved")).close()
            db.execute("INSERT INTO interview_training_attempts VALUES ('wrong','x','other','s000')").close()
            db.execute("INSERT INTO interview_training_attempts VALUES ('d','t','school','s101')").close()
            db.execute("""INSERT INTO interview_messages(id,interview_id,sender_type,message_type,content,order_index)
                       VALUES ('legacy-answer','e','candidate','answer','可核验原文',1)""").close()

        url = "/v1/workbench"
        def get(who="teacher", **params):
            return client.get(url, headers=credential(who), params=params)
        assert client.get(url).status_code == 401
        assert client.get(url, headers=credential(school="other")).status_code == 403
        assert get("revoked").status_code == get(class_id="forbidden").status_code == 403
        assert get(limit=21).status_code == get(start_date="2024-02-03",end_date="2024-02-01").status_code == 422
        assert get(student_ids="S001").status_code == 422
        response = get(limit=2, college_id="college", class_id="c")
        assert response.is_success, response.text
        data = response.json()
        assert "s099" in visited
        assert data["total"] == 6
        assert [row["id"] for row in data["recent"]] == ["f","e"]
        assert get("admin").json()["total"] == 7
        assert get(kind="training").json()["total"] == 1
        assert get(college_id="empty").json()["total"] == 0
        assert get(start_date="2024-02-01",end_date="2024-02-01").json()["total"] == 3
        if owner == "interview":
            assert (data["completed"], data["running"], data["completed_students"], data["visible_students"]) == (3,2,2,102)
            assert data["by_kind"] == {"training":1, "practice":5}
            assert [r["id"] for r in data["running_items"]] == ["e","b"]
        else:
            latest, historical = data["recent"]
            assert latest["total_score"] is None and historical["total_score"] == 97
            assert data["eligible"] == 3 and data["average_score"] == 59
            assert data["score_bands"] == {"gte90":1,"from80":1,"from70":0,"below70":1}
            assert data["quality"] == {"pending_review":3,"zero_evidence":1,"partial_coverage":1,"unknown_coverage":2}
            assert [r["id"] for r in data["pending_items"]] == ["a","b"]

            def every_page(**filters):
                items = []
                params = {**filters, "limit": 1}
                while True:
                    response = client.get("/v1/records", params=params, headers=credential())
                    assert response.is_success, response.text
                    page = response.json()
                    items.extend(row["id"] for row in page["items"])
                    if not page["next_cursor"]:
                        return items
                    params["cursor"] = page["next_cursor"]
            expected = {"gte90": ["e"], "from80": ["a"], "from70": [], "below70": ["d"]}
            for band, ids in expected.items():
                matching = every_page(score_band=band)
                assert matching == ids and len(matching) == data["score_bands"][band]
            assert every_page(state="pending") == ["a","b","c"]
            assert every_page(state="approved", kind="training", score_band="below70",
                              start_date="2024-02-01", end_date="2024-02-01") == ["d"]
            assert get(college_id="empty").json()["average_score"] is None
            assert get(start_date="2024-03-01").json()["average_score"] is None
        roster.remove("s101")
        assert get().json()["total"] == 3
        with patch("services.record_workbench.MAX_DIRECTORY_PAGES", 1):
            assert get().status_code == 422
        async def repeated_page(service, method, path, *, actor, scope, body):
            return await directory(service, method, path, actor=actor, scope=scope,
                                   body={**body, "after_student": None})
        async def failed_next_page(service, method, path, *, actor, scope, body):
            if body["after_student"]:
                raise HTTPException(503)
            return await directory(service, method, path, actor=actor, scope=scope, body=body)

        with patch.object(school_records, "request_json", repeated_page):
            assert get().status_code == 502
        with patch.object(school_records, "request_json", failed_next_page):
            assert get().status_code == 503


if __name__ == "__main__":
    exercise()
