"""供 smoke_microservices.py 调用的离线恢复演练，仅使用合成数据。"""
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

DOMAINS = ("identity", "training", "interviews", "assessment", "analytics", "credentials", "provenance")
WATERMARKS = {
    "interviews": [
        "SELECT interview_id, sequence_no, digest FROM interview_assessment_streams ORDER BY interview_id",
        "SELECT id,kind,state FROM interview_jobs ORDER BY id",
    ],
    "assessment": [
        "SELECT interview_id, sequence_no, digest FROM assessment_projection_inbox ORDER BY interview_id,sequence_no",
        "SELECT id,kind,state FROM interview_jobs ORDER BY id",
        "SELECT report_id, version, source FROM assessment_report_versions ORDER BY report_id,version",
    ],
    "training": ["SELECT event_id,attempt_id FROM training_completions ORDER BY event_id"],
    "analytics": ["SELECT event_id,digest FROM analytics_events ORDER BY event_id"],
    "credentials": ["SELECT event_id,digest,delivered FROM credential_outbox ORDER BY event_id"],
    "provenance": ["SELECT event_id,digest,status FROM provenance_anchors ORDER BY event_id"],
}


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_only(path):
    return closing(sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True))


def watermarks(folder):
    result = {}
    for domain, queries in WATERMARKS.items():
        with read_only(folder / (domain + ".sqlite")) as db:
            result[domain] = [[list(row) for row in db.execute(query)] for query in queries]
    return result


def snapshot_file(source, dest):
    with read_only(source) as reader, closing(sqlite3.connect(dest)) as writer:
        # SQLite 备份接口会包含已提交的 WAL 页。只复制主文件可能让已撤销的凭证或已修改的评分恢复到旧状态。
        reader.backup(writer)
        writer.execute("PRAGMA journal_mode=DELETE").fetchone()


def backup_frozen(source, archive):
    archive.mkdir(mode=0o700)
    manifest = {"format": 1, "watermarks": watermarks(source), "files": {}}
    for domain in DOMAINS:
        filename = domain + ".sqlite"
        dest = archive / filename
        snapshot_file(source / filename, dest)
        manifest["files"][filename] = checksum(dest)
    if watermarks(archive) != manifest["watermarks"]:
        raise RuntimeError("Source watermarks advanced while frozen")
    path = archive / "manifest.json"
    path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return checksum(path)


def restore(archive, dest, pinned_digest):
    index = archive / "manifest.json"
    if index.is_symlink() or checksum(index) != pinned_digest:
        raise ValueError("Untrusted backup manifest")
    manifest = json.loads(index.read_text(encoding="utf-8"))
    names = {domain + ".sqlite" for domain in DOMAINS}
    if (manifest.get("format") != 1 or set(manifest.get("files", {})) != names
            or dest.exists() or dest.is_symlink()):
        raise ValueError("Expected a complete backup and a fresh destination")
    # 先将各库恢复到私有暂存目录。即使直到最后一个库才发现缺失或损坏，也不能发布不完整的恢复结果。
    with tempfile.TemporaryDirectory(prefix="restore-stage-", dir=dest.parent) as temporary:
        staged = Path(temporary) / "domains"
        staged.mkdir(mode=0o700)
        for name in sorted(names):
            source = archive / name
            if source.is_symlink() or not source.is_file():
                raise ValueError(f"Missing backup file {name}")
            target = staged / name
            shutil.copyfile(source, target)
            if checksum(target) != manifest["files"][name]:
                raise ValueError(f"Checksum mismatch for {name}")
            with read_only(target) as db:
                if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError(f"Corrupt database {name}")
                if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise ValueError(f"Broken references in {name}")
        if watermarks(staged) != manifest["watermarks"]:
            raise ValueError("Event watermark mismatch after restoration")
        os.rename(staged, dest)


def verify_graph(restored, expected):
    student, task, attempt, iid, rid, serial = (expected[name] for name in
                                              ("student", "task", "attempt", "interview", "report", "serial"))
    def rows(domain, sql, *args):
        with read_only(restored / (domain + ".sqlite")) as db:
            return db.execute(sql, args).fetchall()

    assert rows("identity", "SELECT name FROM identity_student_credentials WHERE actor_id=? AND school_id=?",
                student, expected["school"]) == [("New Student",)]
    assert rows("training", """SELECT task_id,interview_id,student_id,status FROM training_attempts
                WHERE attempt_id=?""", attempt) == [(task, iid, student, "completed")]
    assert rows("interviews", """SELECT m.content FROM interview_turns t JOIN interview_messages m
                ON t.answer_id=m.id WHERE t.interview_id=? AND t.submission_id='synthetic-one'""", iid) == [(expected["answer"],)]
    assert rows("assessment", "SELECT total_score FROM interview_reports WHERE id=? AND interview_id=? AND user_id=?",
                rid, iid, student) == [(expected["latest_score"],)]
    assert rows("assessment", """SELECT actor_id,reason FROM assessment_report_versions
                WHERE report_id=? AND version=?""", rid, expected["review_version"]) == [(expected["teacher"], "Reviewed original answer")]
    assert rows("assessment", """SELECT status,actor_id,note FROM assessment_report_reviews
                WHERE report_id=? AND version=?""", rid, expected["review_version"]) == [("approved", expected["teacher"], "Checked")]
    assert rows("assessment", """SELECT serial FROM assessment_issuance_permits
                WHERE report_id=? AND application_id=? AND version=?""",
                rid, expected["application"], expected["review_version"]) == [(serial,)]
    assert rows("analytics", """SELECT DISTINCT original_answer FROM analytics_scores
                WHERE attempt_id=?""", attempt) == [(expected["answer"],)]
    assert rows("credentials", """SELECT a.id,a.decision,a.reviewed_by,c.signature,c.revoked_by,c.reason
                FROM teaching_certificates c JOIN credential_applications a ON a.id=c.application_id
                WHERE c.serial=? AND a.student_id=? AND c.revoked_at IS NOT NULL""",
                serial, student) == [(expected["application"], "approved", expected["teacher"], expected["signature"], expected["teacher"], "Superseded")]
    # 演练刻意在溯源服务离线时撤销凭证。待上链事件必须保留在发件箱中，撤销操作无需等待上链。
    assert rows("credentials", """SELECT o.delivered FROM credential_outbox o JOIN teaching_certificates c
                ON c.revocation_event=o.event_id WHERE c.serial=?""", serial) == [(0,)]
    source = rows("interviews", "SELECT sequence_no FROM interview_assessment_streams WHERE interview_id=?", iid)
    target = rows("assessment", "SELECT MAX(sequence_no) FROM assessment_projection_inbox WHERE interview_id=?", iid)
    assert source == target and source[0][0] > 0


def exercise_restore(deployment, expected):
    # 先关闭请求入口，再停止工作进程。保留尚未投递的发件箱记录，确保关闭接收服务时没有新的写入。
    first = ("student-gateway", "admin-gateway", "public", "score-worker", "completion-worker", "anchor-relay")
    for name in dict.fromkeys((*first, *deployment.processes)):
        deployment.stop(name)
    assert all(proc.poll() is not None for proc in deployment.processes.values())
    archive, restored = (deployment.temp / name for name in ("backup", "restored"))
    pinned_digest = backup_frozen(deployment.temp, archive)
    for case in ("missing", "corrupt"):
        broken = deployment.temp / case
        shutil.copytree(archive, broken)
        credentials = broken / "credentials.sqlite"
        if case == "missing":
            credentials.unlink()
        else:
            with credentials.open("ab") as altered:
                altered.write(b"invalid")
        try:
            restore(broken, restored, pinned_digest)
        except ValueError:
            assert not restored.exists()
        else:
            raise AssertionError(f"Accepted {case} snapshot")
    restore(archive, restored, pinned_digest)
    verify_graph(restored, expected)
    # 独立验证进程只能打开恢复目录中的 SQLite 文件，使用预先固定的学校公钥，不持有签发私钥或真实上链凭据。
    deployment.command(["-c", """
import json, os, sys
from pathlib import Path
root = Path(os.environ["RESTORED_FOLDER"]).resolve()
def guard(event,args):
    if event == "sqlite3.connect" and Path(args[0]).resolve().parent != root:
        raise RuntimeError("Verifier attempted to read outside restored storage")
sys.addaudithook(guard)
from fastapi.testclient import TestClient
from services.credentials.app import public_app
with TestClient(public_app) as client:
    result = client.get("/verify/" + os.environ["EXPECTED_SERIAL"])
    assert result.status_code == 200
    body = result.json()
    assert body["valid"] is False and body["status"] == "revoked" and body["anchor"]["status"] != "confirmed"
"""], RESTORED_FOLDER=str(restored), CREDENTIALS_SQLITE_PATH=str(restored / "credentials.sqlite"),
                       SERVICE_ID="credentials-verifier", EXPECTED_SERIAL=expected["serial"])
    print(f"PASS: restored {len(DOMAINS)} frozen SQLite domains; SHA-256 {pinned_digest}; "
          "rejected corrupt/missing domains; original permit, signature and revocation verified", flush=True)
