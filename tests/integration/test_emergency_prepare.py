"""从冻结校库到运维查询的完整演练，验证两端均无法修改学校业务数据。"""
import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from deploy.emergency import Settings, create_app
from deploy.emergency_prepare import issue, snapshot


@pytest.mark.parametrize("legacy", [False, True])
def test_operator_can_inspect_only_an_approved_snapshot(tmp_path, legacy):
    source = tmp_path / "frozen.sqlite"
    with closing(sqlite3.connect(source)) as db, db:
        db.execute("CREATE TABLE interview_reports(id TEXT,generation_status TEXT,review_status TEXT,answer TEXT)")
        db.execute("INSERT INTO interview_reports VALUES ('r1','succeeded','approved','PRIVATE-STUDENT-ANSWER')")
        if not legacy:
            db.execute("CREATE TABLE assessment_database_owner(slot INTEGER,school_id TEXT)")
            db.execute("INSERT INTO assessment_database_owner VALUES (1,'campus')")
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    status_file = tmp_path / "status.sqlite"
    params = SimpleNamespace(school="campus", sqlite=source, as_of=datetime.now(timezone.utc).isoformat(),
                             output=status_file, legacy_sha256=original_hash if legacy else None)
    if not legacy:
        with pytest.raises(ValueError, match="学校不一致"):
            snapshot(SimpleNamespace(**{**vars(params), "school":"another"}))
        assert not status_file.exists()
    snapshot(params)
    assert b"PRIVATE-STUDENT-ANSWER" not in status_file.read_bytes()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    private = Ed25519PrivateKey.generate()
    private_file, public_file = (tmp_path / p for p in ("private.pem", "public.pem"))
    private_file.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                  serialization.NoEncryption()))
    public_file.write_bytes(private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    bundle = tmp_path / "incident"
    issue(SimpleNamespace(school="campus", incident="INC-1", operator="oncall", minutes=10, key=private_file,
                          snapshot=status_file, output=bundle))
    private_file.unlink()
    application = create_app(Settings("campus", status_file, bundle / "permit.jwt", public_file))
    headers = {"Authorization":"Bearer " + (bundle / "bearer").read_text().strip()}
    with TestClient(application, client=("127.0.0.1", 5555)) as client:
        assert client.get("/emergency/summary", headers=headers).json()["reports"] == 1
        assert client.get("/emergency/reports/r1/status", headers=headers).json()["review_status"] == "approved"
        assert client.put("/emergency/reports/r1/status", headers=headers).status_code == 405
        (bundle / "permit.jwt").unlink()
        assert client.get("/emergency/summary", headers=headers).status_code == 403


@pytest.mark.parametrize("ownership", ["native", "mixed", "case", "missing"])
def test_legacy_hash_never_overrides_school_evidence(tmp_path, ownership):
    source = tmp_path/"legacy.sqlite"
    with closing(sqlite3.connect(source)) as db, db:
        db.execute("CREATE TABLE interview_reports(id TEXT PRIMARY KEY,generation_status TEXT,review_status TEXT)")
        db.execute("INSERT INTO interview_reports VALUES ('private-foreign-id','succeeded','approved')")
        if ownership == "native":
            db.execute("CREATE TABLE assessment_database_owner(slot INTEGER PRIMARY KEY,school_id TEXT)")
            db.execute("INSERT INTO assessment_database_owner VALUES (1,'school-b')")
        else:
            db.execute("CREATE TABLE interview_training_attempts(school_id TEXT COLLATE NOCASE)")
            db.executemany("INSERT INTO interview_training_attempts VALUES (?)",
                           [("school-a",), ({"mixed":"school-b","case":"School-A","missing":None}[ownership],)])
    output = tmp_path/"snapshot.sqlite"
    args=SimpleNamespace(sqlite=source,school="school-a",output=output,as_of="2026-01-01T00:00:00Z",
                         legacy_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    with pytest.raises(ValueError,match="学校不一致"):
        snapshot(args)
    assert not output.exists()


def test_approval_signs_the_exact_bytes_it_reviewed(tmp_path, monkeypatch):
    import jwt
    from deploy import emergency_prepare as prep

    frozen = tmp_path/"status.sqlite"
    with closing(sqlite3.connect(frozen)) as db, db:
        db.execute("CREATE TABLE snapshot_meta(format TEXT,school TEXT,as_of TEXT,report_count INTEGER)")
        db.execute("INSERT INTO snapshot_meta VALUES ('school-report-status-v1','s','2026-01-01T00:00:00Z',1)")
        db.execute("CREATE TABLE report_status(id TEXT PRIMARY KEY,generation_status TEXT,review_status TEXT)")
        db.execute("INSERT INTO report_status VALUES ('r','succeeded','approved')")
    original_digest=hashlib.sha256(frozen.read_bytes()).hexdigest()
    private=Ed25519PrivateKey.generate()
    key=tmp_path/"approver.pem"
    key.write_bytes(private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    inspect = prep.snapshot_meta

    def change_source_after_inspection(db, school):
        result=inspect(db,school)
        # 审批读取后故意换掉同名源文件，不能把新的业务状态签进刚完成的审批。
        with closing(sqlite3.connect(frozen)) as changed, changed:
            changed.execute("UPDATE report_status SET review_status='rejected'")
        return result

    monkeypatch.setattr(prep,"snapshot_meta",change_source_after_inspection)
    bundle=tmp_path/"ticket"
    issue(SimpleNamespace(school="s",incident="synthetic",operator="operator",minutes=5,key=key,
                          snapshot=frozen,output=bundle))
    token=(bundle/"permit.jwt").read_text().strip()
    claims=jwt.decode(token,private.public_key(),algorithms=["EdDSA"],audience="legacy-readonly-rescue")
    assert claims["snapshot_sha256"] == original_digest
    assert claims["snapshot_sha256"] != hashlib.sha256(frozen.read_bytes()).hexdigest()
