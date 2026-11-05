"""端到端验收使用的合成学校记录和本地 HTTPS 模型回包。"""
import ipaddress
import json
import ssl
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

SCHOOL = "smoke-school"
PASSWORD = "Synthetic-Only-Student-138!"
TEACHER_PASSWORD = "Synthetic-Only-Teacher-572!"
MASTER = "school-master@example.test"
ANSWER = "A row lock serializes concurrent writes to the same record."


def seed():
    from shared.offline_fixture import enable_offline_fixture
    enable_offline_fixture()
    from admin_backend.offline import main
    enums = ["viewInterviews", "report.read", "report.review", "report.export", "score.adjust", "training.assign", "training.read",
             "credential.read", "credential.approve", "credential.issue", "credential.revoke",
             "analytics.teaching.read", "analytics.practice.assign"]
    db = main.db
    db.execute("INSERT INTO campus_colleges(id,code,name) VALUES ('college','demo','Demo')")
    db.execute("INSERT INTO campus_programs(id,college_id,name) VALUES ('program','college','Program')")
    db.execute("INSERT INTO campus_classes(id,program_id,name,graduation_year,invite_code) "
               "VALUES ('cls','program','Class',2027,'smoke-code')")
    for teacher in ("owner", "coworker"):
        db.execute("INSERT INTO admin_users(id,email,name,actor_type,password_hash,permissions,student_scope) "
                   "VALUES (?,?,?,'teacher',?,?,?)", (teacher, teacher + "@example.test", teacher,
                   main.hash_password(TEACHER_PASSWORD), json.dumps(enums),
                   json.dumps([{"college":"college","program":"program","class":"cls"}])))
    db.commit()


class ChatFixture(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        if self.path != "/v1/chat/completions" or self.headers.get("Authorization") != "Bearer synthetic-model-token":
            self.send_error(403)
            return
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        text = json.dumps(request["messages"], ensure_ascii=False)
        if "dimension_scores" in text and ANSWER in text:
            payload = {"question_types": ["technical"], "dimension_scores": {"technical_accuracy": 52},
                       "dimension_evidence": {"technical_accuracy": ANSWER}, "strengths": "Evidence verified"}
        else:
            payload = {"summary": "Assessment completed.", "suggestions": ["Explain transaction boundaries."]}
        response = json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


def local_model(temp):
    """为本次测试签发仅限回环地址、受子进程信任的开发证书。"""
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "smoke fixture")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
            .add_extension(x509.KeyUsage(True, False, False, False, False, True, True, None, None), True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), False)
            .sign(key, hashes.SHA256()))
    pem = temp / "local-ca.pem"
    pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path = temp / "local-tls-key.pem"
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    server = ThreadingHTTPServer(("127.0.0.1", 0), ChatFixture)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(pem, key_path)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    Thread(target=server.serve_forever, daemon=True).start()
    return server, pem


def permit_fault_proxy(assessment, crash_after_commit):
    """转发真实回环 HTTP 请求，故意扣留首次成功的签发许可回执。"""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def forward(self):
            if not self.path.startswith("/internal/credential-evidence/"):
                self.send_error(404)
                return
            content = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            response = httpx.request(self.command, assessment + self.path, content=content,
                                     headers={"Authorization": self.headers["Authorization"],
                                              "Content-Type": "application/json"},
                                     trust_env=False, follow_redirects=False, timeout=10)
            if self.path.endswith("/authorize") and response.status_code == 200:
                if crash_after_commit(response.json()["serial"]):
                    return
            self.send_response(response.status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(response.content)

        do_GET = do_POST = forward

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    seed()
