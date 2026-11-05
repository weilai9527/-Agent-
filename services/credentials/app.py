"""校内教学证书业务入口 app，以及独立部署的公开只读验真入口 public_app。"""

import hashlib
import json
import os
import re
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from shared.runtime_mode import require_native_runtime
from shared.service_http import service_origin
from shared.credential_reference import application_id
from shared.service_security import require_service
from . import relay, signing, sources
from .public import create_public_app
from .storage import database, initialize


@asynccontextmanager
async def lifespan(_):
    # 直接启动签发进程也必须先拒绝旧配置，避免先写库后发现运行模式不符。
    require_native_runtime()
    initialize(database())
    yield


app = FastAPI(title="Teaching credentials", lifespan=lifespan, docs_url=None,
              redoc_url=None, openapi_url=None)
TITLE = "模拟面试训练完成证明"


@app.middleware("http")
async def no_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@app.exception_handler(signing.SigningConfigurationError)
async def key_unavailable(request, exc):
    return JSONResponse(status_code=503, content={"detail": "学校签名密钥配置不可用。"})


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Application(Body):
    report_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")


class Review(Body):
    version: int = Field(strict=True, ge=1)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=500)


class Revocation(Body):
    reason: str = Field(min_length=1, max_length=500)


def require_role(actor, *roles):
    if actor["actor_type"] not in roles:
        raise HTTPException(403, "该身份不具备此操作权限。")


def lookup(tx, app_id, school, lock=""):
    row = tx.one("SELECT * FROM credential_applications WHERE id=? AND school_id=?" + lock,
                 (app_id, school))
    if row is None:
        raise HTTPException(404, "申请不存在。")
    return row


def lock_suffix(db):
    return " FOR UPDATE" if db.engine == "mysql" else ""


def check_current(actor, application):
    expected = json.loads(application["evidence"])
    if sources.current_evidence(actor, expected["report_id"]) != expected:
        raise HTTPException(409, "证据已变更，请按当前版本重新申请并审核。")


def public_claims(application, cert):
    # 随机盐将学生、训练、教师审核和签发人绑定到同一摘要，用于验签，同时避免公开学号或成绩。
    commitment = digest([application["salt"], json.loads(application["evidence"]),
                         application["reviewed_by"], application["reviewed_at"],
                         application["decision"], application["review_note"], cert["issued_by"],
                         cert["previous_serial"]])
    return {"school_id": application["school_id"], "serial": cert["serial"], "title": TITLE,
            "issued_at": cert["issued_at"], "generation": cert["generation"], "commitment": commitment}


def serial_view(cert):
    origin = service_origin("credentials_public") if os.getenv("CREDENTIALS_PUBLIC_SERVICE_URL") else ""
    return {"id": cert["serial"], "generation": cert["generation"], "issued_at": cert["issued_at"],
            "revoked_at": cert["revoked_at"], "verification_url": origin + "/verify/" + cert["serial"]}


def application_view(tx, row, *, staff=False):
    certs = tx.all("SELECT * FROM teaching_certificates WHERE application_id=? ORDER BY generation",
                   (row["id"],))
    certificates = []
    for cert in certs:
        result = serial_view(cert)
        # 仅向持有人和获准职员返回签名文件。离线验签证明签发时的内容，撤销状态需实时查询。
        result["proof"] = {"format": "teaching-credential/v1", "kid": cert["kid"],
                           "payload": public_claims(row, cert), "signature": cert["signature"]}
        if staff:
            result.update(issued_by=cert["issued_by"], revoked_by=cert["revoked_by"],
                          revocation_reason=cert["reason"])
        certificates.append(result)
    return {"id": row["id"], "evidence": json.loads(row["evidence"]), "decision": row["decision"],
            "created_at": row["created_at"], "reviewed_at": row["reviewed_at"],
            "review_note": row["review_note"], "certificates": certificates}


@app.get("/health")
def health():
    return {"status": "ok" if database().ping() else "unavailable"}


@app.post("/applications")
def apply(body: Application, actor=Depends(require_service("credentials", "credential.apply"))):
    require_role(actor, "student")
    evidence = sources.current_evidence(actor, body.report_id)
    if (evidence["school_id"], evidence["student_id"], evidence["report_id"]) != (
            actor["school_id"], actor["actor_id"], body.report_id):
        raise HTTPException(403, "该报告不属于当前学生。")
    # 同校同一学生的每个报告版本只有一条申请。即使成绩改回原值，新版本也须重新审核。
    app_id = application_id(evidence["school_id"], evidence["student_id"], body.report_id, evidence["version"])
    db = database()
    duplicate = (" ON DUPLICATE KEY UPDATE id=id" if db.engine == "mysql"
                 else " ON CONFLICT(id) DO NOTHING")
    with db.transaction(write=True) as tx:
        tx.execute("""INSERT INTO credential_applications
            (id, school_id, student_id, evidence, salt, created_at, decision)
            VALUES (?, ?, ?, ?, ?, ?, 'pending')""" + duplicate,
                   (app_id, actor["school_id"], actor["actor_id"], encoded(evidence),
                    secrets.token_hex(32), now()))
        row = lookup(tx, app_id, actor["school_id"])
        if json.loads(row["evidence"]) != evidence:
            raise HTTPException(409, "同一报告版本的来源不一致。")
        return application_view(tx, row)


Cursor = Annotated[str, Query(pattern=r"^(?:[0-9a-f]{64})?$")]


def applications(actor, student_id, after, limit, managed):
    db = database()
    items = []
    while True:
        with db.transaction() as tx:
            rows = tx.all("""SELECT * FROM credential_applications
                WHERE school_id=? AND student_id=? AND id>? ORDER BY id LIMIT ?""",
                          (actor["school_id"], student_id, after, limit + 1))
        for row in rows:
            after = row["id"]
            if managed:
                try:
                    sources.authorize(actor, "credential.read", json.loads(row["evidence"]))
                except HTTPException as exc:
                    if exc.status_code in (403, 404):
                        continue
                    raise
            if len(items) == limit:
                # 下一页游标只能指向调用者已经获准查看的记录。
                return {"items": items, "next": items[-1]["id"]}
            with db.transaction() as tx:
                items.append(application_view(tx, lookup(tx, after, actor["school_id"]), staff=managed))
        if len(rows) < limit + 1:
            return {"items": items, "next": None}


@app.get("/me/applications")
def my_applications(after: Cursor = "", limit: Annotated[int, Query(ge=1, le=100)] = 50,
                    actor=Depends(require_service("credentials", "credential.read"))):
    require_role(actor, "student")
    return applications(actor, actor["actor_id"], after, limit, False)


@app.get("/students/{student_id}/applications")
def student_applications(student_id: str, after: Cursor = "",
                         limit: Annotated[int, Query(ge=1, le=100)] = 50,
                         actor=Depends(require_service("credentials", "credential.read"))):
    require_role(actor, "teacher", "admin")
    return applications(actor, student_id, after, limit, True)


@app.post("/applications/{app_id}/review")
def review(app_id: str, body: Review, actor=Depends(require_service("credentials", "credential.approve"))):
    require_role(actor, "teacher")
    db = database()
    with db.transaction() as tx:
        snapshot = lookup(tx, app_id, actor["school_id"])
    # 申请绑定不可变证据。在本地写事务外查询当前报告与对象授权，避免上游故障占住写锁。
    check_current(actor, snapshot)
    evidence = json.loads(snapshot["evidence"])
    sources.check_student_action(actor, evidence["student_id"], "credential.approve")
    if (body.version, body.digest) != (evidence["version"], evidence["digest"]):
        raise HTTPException(409, "提交的审核依据与申请版本不匹配。")
    with db.transaction(write=True) as tx:
        row = lookup(tx, app_id, actor["school_id"], lock_suffix(db))
        if row["decision"] == "pending":
            tx.execute("""UPDATE credential_applications SET decision=?, reviewed_by=?, reviewed_at=?,
                review_note=? WHERE id=?""", (body.decision, actor["actor_id"], now(), body.note, app_id))
        elif (row["decision"], row["reviewed_by"], row["review_note"]) != (
                body.decision, actor["actor_id"], body.note):
            raise HTTPException(409, "此版本已有不可覆盖的审核决定。")
        return application_view(tx, lookup(tx, app_id, actor["school_id"]))


def issue_event(kid, claims, signature):
    return ["issued/v1", kid, claims, signature]


def revocation_event(application, cert):
    reason = digest([application["salt"], cert["reason"], cert["revoked_by"]])
    return ["revoked/v1", cert["signature"], cert["revoked_at"], reason]


def enqueue(tx, event_id, school, event):
    tx.execute("INSERT INTO credential_outbox (event_id, school_id, digest) VALUES (?, ?, ?)",
               (event_id, school, digest(event)))


def prepare_serial(application, actor, previous):
    if application["decision"] != "approved" or not application["reviewed_by"]:
        raise HTTPException(409, "须先由负责教师批准此版本。")
    cert = {"serial": secrets.token_hex(16), "generation": previous["generation"] + 1 if previous else 1,
            "previous_serial": previous["serial"] if previous else None, "issued_at": now(),
            "issued_by": actor["actor_id"], "revoked_at": None}
    claims = public_claims(application, cert)
    kid, signature = signing.sign_payload(application["school_id"], claims)
    return {**cert, "kid": kid, "signature": signature}


def reserve_intent(db, row, actor, previous):
    generation = previous["generation"] + 1 if previous else 1
    query = "SELECT * FROM credential_issuance_intents WHERE application_id=? AND generation=?"
    identity = (row["id"], generation)
    with db.transaction() as tx:
        intent = tx.one(query, identity)
    if intent:
        return intent
    # 签名在写事务外进行。并发申请只保留本代次的一份签名产物，供远端许可和故障恢复使用。
    candidate = prepare_serial(row, actor, previous)
    conflict = (" ON DUPLICATE KEY UPDATE serial=credential_issuance_intents.serial" if db.engine == "mysql"
                else " ON CONFLICT(application_id,generation) DO NOTHING")
    with db.transaction(write=True) as tx:
        tx.execute("""INSERT INTO credential_issuance_intents
            (application_id,generation,serial,previous_serial,issued_at,issued_by,kid,signature)
            VALUES (?,?,?,?,?,?,?,?)""" + conflict,
            (*identity, candidate["serial"], candidate["previous_serial"], candidate["issued_at"],
             candidate["issued_by"], candidate["kid"], candidate["signature"]))
        intent = tx.one(query + lock_suffix(db), identity)
        if not intent:
            raise HTTPException(409, "证书编号冲突，请重试。")
        return intent


def stored_serial(tx, serial, lock=""):
    return tx.one("SELECT * FROM teaching_certificates WHERE serial=?" + lock, (serial,))


def authorized_certificate(db, actor, serial, action):
    with db.transaction() as tx:
        row = tx.one("""SELECT a.* FROM credential_applications a JOIN teaching_certificates c
            ON c.application_id=a.id WHERE c.serial=? AND a.school_id=?""", (serial, actor["school_id"]))
        if not row:
            raise HTTPException(404, "证书不存在。")
        cert = stored_serial(tx, serial)
    sources.authorize(actor, action, json.loads(row["evidence"]))
    return row, cert


def publish(db, row, actor, previous=None):
    existing = previous["successor"] if previous else row["first_serial"]
    if existing:
        with db.transaction() as tx:
            return serial_view(stored_serial(tx, existing))
    candidate = reserve_intent(db, row, actor, previous)
    kid, signature = candidate["kid"], candidate["signature"]
    claims = public_claims(row, candidate)
    if not signing.verify_payload(row["school_id"], claims, kid, signature):
        raise HTTPException(409, "预留的证书签名无法通过当前学校公钥核验。")
    event = issue_event(kid, claims, signature)
    # 评估服务在报告锁内核对版本并持久化许可。回包丢失时，仍以原序号和签名摘要查回同一许可。
    sources.authorize_issuance(actor, row["id"], json.loads(row["evidence"]), candidate, digest(event))
    with db.transaction(write=True) as tx:
        # 锁住申请后复查代次。并发请求返回先提交的证书，证书、代次指针、待存证事件一并提交。
        current = lookup(tx, row["id"], actor["school_id"], lock_suffix(db))
        existing = current["first_serial"]
        if previous:
            existing = stored_serial(tx, previous["serial"], lock_suffix(db))["successor"]
        if existing:
            return serial_view(stored_serial(tx, existing, lock_suffix(db)))
        event_id = secrets.token_hex(16)
        tx.execute("""INSERT INTO teaching_certificates
            (serial, application_id, generation, previous_serial, issued_at, issued_by, kid, signature, issue_event)
            VALUES (?,?,?,?,?,?,?,?,?)""", (candidate["serial"], row["id"], candidate["generation"],
                   candidate["previous_serial"], candidate["issued_at"], candidate["issued_by"], kid, signature, event_id))
        enqueue(tx, event_id, row["school_id"], event)
        if previous:
            tx.execute("UPDATE teaching_certificates SET successor=? WHERE serial=?",
                       (candidate["serial"], previous["serial"]))
        else:
            tx.execute("UPDATE credential_applications SET first_serial=? WHERE id=?",
                       (candidate["serial"], row["id"]))
        return serial_view({**candidate, "revoked_at": None})


@app.post("/applications/{app_id}/issue")
def issue(app_id: str, actor=Depends(require_service("credentials", "credential.issue"))):
    require_role(actor, "teacher", "admin")
    db = database()
    with db.transaction() as tx:
        row = lookup(tx, app_id, actor["school_id"])
    sources.authorize(actor, "credential.issue", json.loads(row["evidence"]))
    return publish(db, row, actor)


@app.post("/certificates/{serial}/revoke")
def revoke(serial: str, body: Revocation, actor=Depends(require_service("credentials", "credential.revoke"))):
    require_role(actor, "teacher", "admin")
    db = database()
    row, _ = authorized_certificate(db, actor, serial, "credential.revoke")
    with db.transaction(write=True) as tx:
        cert = stored_serial(tx, serial, lock_suffix(db))
        if cert["revoked_at"]:
            if cert["reason"] != body.reason:
                raise HTTPException(409, "撤销原因已记录。")
            return serial_view(cert)
        event_id, timestamp = secrets.token_hex(16), now()
        tx.execute("""UPDATE teaching_certificates SET revoked_at=?, revoked_by=?, reason=?,
            revocation_event=? WHERE serial=?""", (timestamp, actor["actor_id"], body.reason, event_id, serial))
        cert.update(revoked_at=timestamp, revoked_by=actor["actor_id"], reason=body.reason)
        enqueue(tx, event_id, row["school_id"], revocation_event(row, cert))
        return serial_view(cert)


@app.post("/certificates/{serial}/reissue")
def reissue(serial: str, actor=Depends(require_service("credentials", "credential.reissue"))):
    require_role(actor, "teacher", "admin")
    db = database()
    row, cert = authorized_certificate(db, actor, serial, "credential.reissue")
    if not cert["revoked_at"]:
        raise HTTPException(409, "补发前须先撤销原证。")
    return publish(db, row, actor, cert)


@app.get("/verify/{serial}")
def verify(serial: str):
    if not re.fullmatch("[a-f0-9]{32}", serial):
        raise HTTPException(404, "证书不存在。")
    with database().transaction() as tx:
        cert = stored_serial(tx, serial)
        if not cert:
            raise HTTPException(404, "证书不存在。")
        row = tx.one("SELECT * FROM credential_applications WHERE id=?", (cert["application_id"],))
        claims = public_claims(row, cert)
        if not signing.verify_payload(row["school_id"], claims, cert["kid"], cert["signature"]):
            return {"valid": False, "status": "invalid_signature"}
        event = tx.one("SELECT * FROM credential_outbox WHERE event_id=?",
                       (cert["revocation_event"] or cert["issue_event"],))
    revoked = cert["revoked_at"] is not None
    expected = revocation_event(row, cert) if revoked else issue_event(cert["kid"], claims, cert["signature"])
    if not event or (event["school_id"], event["digest"]) != (row["school_id"], digest(expected)):
        # 其他证书或历史状态的链回执不能证明这次签发或撤销。摘要不匹配时只保留业务验签结论。
        event = None
    return {"valid": not revoked, "status": "revoked" if revoked else "valid", "title": TITLE,
            "issuer": row["school_id"], "issued_at": cert["issued_at"], "anchor": relay.anchor_status(event)}


# 公开入口仅查询证书和存证状态，部署时使用只读数据库账号。
@asynccontextmanager
async def public_lifespan(_):
    # 直接通过 ASGI 启动时也检查部署身份，防止公开入口误用校内签发或链提交凭据。
    if os.getenv("SERVICE_ID") != "credentials-verifier":
        raise RuntimeError("公开入口要求 SERVICE_ID=credentials-verifier")
    if os.getenv("CREDENTIALS_SIGNING_KEYS_JSON") or os.getenv("PROVENANCE_SUBMIT_TOKEN"):
        raise RuntimeError("公开验真进程不能持有学校签名私钥或链提交令牌")
    # 只检查数据库标识列的实际排序规则；公开进程没有建表或修复表的权限。
    database().require_exact_keys("credentials")
    yield


public_app = create_public_app(verify, lifespan=public_lifespan)
