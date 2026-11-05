import asyncio
import io
import json
from concurrent.futures import ThreadPoolExecutor
from zipfile import ZipFile

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from fastapi.testclient import TestClient

from shared.service_security import service_headers
from services.profile import directions, parser, store
from services.profile.app import app


@pytest.fixture
def boundary(tmp_path, monkeypatch):
    private = Ed25519PrivateKey.generate()
    key = private.public_key().public_bytes(serialization.Encoding.PEM,
                                            serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    scopes = ["profile.read", "profile.write", "profile.upload", "profile.analyze",
              "profile.snapshot.read", "profile.versions.read"]
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps({"gateway": {"keys": {"k": key},
        "schools": ["A", "B"], "grants": {"profile": {"student": scopes, "teacher": scopes}}}}))
    monkeypatch.setenv("PROFILE_DB_ENGINE", "sqlite")
    monkeypatch.setenv("PROFILE_SQLITE_PATH", str(tmp_path / "profile.sqlite"))
    monkeypatch.setenv("SERVICE_KEY_ID", "k")
    monkeypatch.setenv("SERVICE_SIGNING_KEY", private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())
    monkeypatch.setenv("SERVICE_ID", "profile")
    def headers(scope, school="A", student="s", role="student"):
        monkeypatch.setenv("SERVICE_ID", "gateway")
        try:
            return service_headers("profile", actor_id=student, school_id=school, actor_type=role, scopes=[scope])
        finally:
            monkeypatch.setenv("SERVICE_ID", "profile")
    with TestClient(app) as client:
        yield client, headers, app.state.db


def test_profile_revisions_and_private_local_analysis(boundary):
    client, headers, _ = boundary
    assert client.get("/health").json() == {"ok": True}
    assert client.get("/ready").json() == {"ok": True}
    form = {"major": "自动化", "projects": "机器人视觉联调", "skills": "Python",
            "user_id": "another", "school_id": "B"}
    response = client.put("/api/resume-form", json=form, headers=headers("profile.write"))
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "机器人视觉联调" in response.json()["resume_text"]
    result = client.post("/api/profile/resume-analysis", json={}, headers=headers("profile.analyze")).json()
    assert result["resume_analysis"]["provider"] == "local"
    assert result["resume_analysis"]["analysis"]["recommended_directions"]
    assert client.get("/api/profile/resume-analysis", headers=headers("profile.read")).json()["stale"] is False
    content = "新的简历" * 4000
    response = client.post("/api/profile/resume-upload", files={"file": ("../resume.md", content)},
                           headers=headers("profile.upload"))
    assert response.status_code == 200, response.text
    upload = response.json()
    assert (upload["filename"], upload["char_count"], upload["original_char_count"]) == ("resume.md", 12000, len(content))
    assert client.get("/api/profile/resume-analysis", headers=headers("profile.read")).json()["stale"]
    returned = client.put("/api/profile", json={**upload["profile"], "nickname": "我"},
                          headers=headers("profile.write")).json()
    assert returned["profile"]["resume_filename"] == "resume.md"
    path = "/api/profile/versions"
    assert returned["version"] == 3
    for _ in range(2):
        same = client.put("/api/profile", json=returned["profile"], headers=headers("profile.write"))
        assert same.status_code == 200 and same.json()["version"] == 3
    assert [v["source"] for v in client.get(path, headers=headers("profile.versions.read")).json()["versions"]] == [
        "profile", "upload", "form"]
    first = client.get(path+"/1", headers=headers("profile.versions.read")).json()
    assert first["profile"]["resume_text"] != upload["text"] and first["form"]["major"] == "自动化"
    current = client.get(path+"/current", headers=headers("profile.snapshot.read")).json()
    assert (current["school_id"], current["actor_id"], current["version"]) == ("A", "s", 3)
    assert client.get(path+"/current", headers=headers("profile.versions.read")).status_code == 403
    for school, student in (("A", "other"), ("B", "s")):
        assert client.get(path+"/1", headers=headers("profile.versions.read", school, student)).status_code == 404
        assert client.get("/api/resume-form", headers=headers("profile.read", school, student)).json()["form"] == {}
        assert client.get("/api/profile/resume-analysis", headers=headers("profile.read", school, student)).json()["resume_analysis"] is None
    assert client.get(path+"/1", headers=headers("profile.versions.read", role="teacher")).status_code == 403
    assert client.get(path+"/1").status_code == 401


def test_input_boundaries_do_not_create_revisions(boundary):
    client, headers, _ = boundary
    for filename, data in [("bad.pdf", b"bad"), ("bad.docx", b"PKbad"), ("bad.txt", b"\x00"), ("bad.exe", b"x")]:
        assert client.post("/api/profile/resume-upload", files={"file": (filename, data)},
                           headers=headers("profile.upload")).status_code == 422
    assert client.post("/api/profile/resume-upload", files={"file": ("large.md", b"x" * (parser.MAX_FILE+1))},
                       headers=headers("profile.upload")).status_code == 413
    for body in ({"major": ["x"]}, {"major": "x"*161}, {"college": "x"*161}):
        assert client.put("/api/resume-form", json=body, headers=headers("profile.write")).status_code == 400
    for body in ({}, {"nickname":"n", "avatar_url":"file:///etc/hosts"}):
        assert client.put("/api/profile", json=body, headers=headers("profile.write")).status_code == 400
    assert client.post("/api/profile/resume-analysis", headers=headers("profile.analyze")).status_code == 400
    assert client.get("/api/profile/versions", headers=headers("profile.versions.read")).json()["versions"] == []


def test_import_is_atomic_and_never_overwrites(boundary):
    client, headers, db = boundary
    old = {"id":"old","nickname":"legacy","user_id":"s", "resume_text":"imported"}
    with pytest.raises(ValueError):
        store.import_legacy(db, "B", "other", old)
    with pytest.raises(ValueError):
        store.import_legacy(db, "A", "s", old, resume_analysis={"analysis_json":"[]"})
    def importer(_):
        return store.import_legacy(db, "A", "s", old, {"major": "历史专业"}, {
            "analysis_json": '{"core_skills":["Python"]}', "source_hash":store.source_hash(old)})
    with ThreadPoolExecutor(4) as pool:
        assert sum(pool.map(importer, range(4))) == 1
    result = client.get("/api/profile/resume-analysis", headers=headers("profile.read")).json()
    assert result["resume_analysis"]["analysis"]["core_skills"] == ["Python"] and not result["stale"]
    def save(i):
        store.save(db, ("A", "s"), "profile", {"nickname":str(i)})
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(save, range(4)))
    assert not importer(0)
    snapshots = client.get("/api/profile/versions", headers=headers("profile.versions.read")).json()["versions"]
    assert [r["version"] for r in snapshots] == [5,4,3,2,1]
    assert client.get("/api/profile/versions/1", headers=headers("profile.versions.read")).json()["profile"]["id"] == "old"


def test_docx_is_local_and_ignores_external_parts():
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>My sample CV</w:t></w:r></w:p></w:body></w:document>')
        archive.writestr("_rels/.rels", '<Relationship Target="https://external.invalid/private"/>')
    assert parser.extract("test.docx", buffer.getvalue()) == ("test.docx", "My sample CV", 12)
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", '<!DOCTYPE d [<!ENTITY secret "private">]><d>&secret;</d>')
    with pytest.raises(HTTPException):
        parser.extract("bad.docx", buffer.getvalue())


def test_direction_enrichment_only_sends_names_and_repeatable_event(monkeypatch):
    requests = []
    async def call(service, method, path, **kwargs):
        body = kwargs["body"]
        expected_action = ("suggestions", "catalog.suggest") if body["record"] else ("directions", "catalog.enrich")
        assert (path.rsplit("/", 1)[-1], kwargs["scope"]) == expected_action
        requests.append(body)
        return {"directions":[{"name":"研发","catalog_status":"matched","score":0}]}
    monkeypatch.setattr(directions, "request_json", call)
    result = {"resume_analysis":{"source_hash":"sha","analysis":{"recommended_directions":[
        {"name":"研发","score":90,"evidence":["private"],"nearest_catalog_job_id":"old"}]}}}
    for record in (True, True, False):
        enriched = asyncio.run(directions.enrich_response(result, {}, record))
        assert enriched["resume_analysis"]["analysis"]["recommended_directions"][0] == {
            "name":"研发","score":90,"evidence":["private"],"catalog_status":"matched"}
    assert requests[0] == requests[1] and set(requests[0]) == {"names", "record", "event_id"}
    assert requests[2] == {"names":["研发"], "record":False}


def test_pdf_worker_reads_selectable_text():
    from services.profile.test_native_package import selectable_pdf

    name, text, count = parser.extract("resume.pdf", selectable_pdf("Synthetic resume Python FastAPI PostgreSQL"))
    assert name == "resume.pdf" and "FastAPI" in text and count == len(text)


def test_streaming_body_without_content_length_is_bounded(boundary):
    client, headers, _ = boundary
    token = headers("profile.write")
    response = client.put("/api/profile", headers={**token, "Content-Type":"application/json"},
                          content=iter([b'{"nickname":"N","resume_text":"', b'x' * 262144, b'"}']))
    assert response.status_code == 413
    assert client.get("/api/profile/versions", headers=headers("profile.versions.read")).json()["versions"] == []


def test_parser_and_validation_errors_do_not_log_private_inputs(boundary, caplog, capfd):
    client, headers, _ = boundary
    marker = "Private-Resume-Canary-467"
    broken = client.post("/api/profile/resume-upload", files={"file": (marker + ".docx", marker.encode())},
                         headers=headers("profile.upload"))
    invalid = client.put("/api/resume-form", json=[marker], headers=headers("profile.write"))
    assert (broken.status_code, invalid.status_code) == (422, 422)
    output = capfd.readouterr()
    for channel in (broken.text, invalid.text, output.out, output.err, caplog.text):
        assert marker not in channel


def test_full_editor_roundtrip_preserves_valid_long_form_and_historical_values(boundary):
    client, headers, _ = boundary
    form = {"works": "内部作品集可在面试中演示", "education": "课程 " * 400, "skills": "abc " * 220}
    saved = client.put("/api/resume-form", json=form, headers=headers("profile.write")).json()
    edited = {**saved["profile"], "nickname": "new name"}
    reply = client.put("/api/profile", json=edited, headers=headers("profile.write"))
    assert reply.status_code == 200
    for key in ("portfolio_links", "education_level", "skills"):
        assert reply.json()["profile"][key] == saved["profile"][key]
    edited["education_level"] = "new " * 400
    assert client.put("/api/profile", json=edited, headers=headers("profile.write")).status_code == 400


def test_resume_form_accepts_longest_college_and_major_option(boundary):
    client, headers, _ = boundary
    body = {"college":"院"*160, "major":"专"*160}
    reply = client.put("/api/resume-form", json=body, headers=headers("profile.write"))
    assert reply.status_code == 200
    assert all(reply.json()["form"][field] == value for field,value in body.items())
