"""学生账号页面的 JSON 行测试传输，仅使用临时数据库。"""
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from services.identity.app import app
from shared.service_security import service_headers


def main():
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    scopes = ["student.read", "student.reset", "student.status", "student.import", "permissions.manage"]
    with tempfile.TemporaryDirectory(prefix="native-student-ui-") as work:
        os.environ.update(IDENTITY_DB_ENGINE="sqlite", IDENTITY_SQLITE_PATH=str(Path(work) / "test.sqlite"),
                          SERVICE_KEY_ID="local", SERVICE_TRUST_POLICY=json.dumps({"ui-test": {
                              "keys": {"local": public.decode()}, "schools": ["UI-test"],
                              "grants": {"identity": {"admin": scopes}}}}))
        os.environ["SERVICE_SIGNING_KEY"] = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                            serialization.NoEncryption()).decode()
        with TestClient(app) as client:
            with app.state.store.transaction(write=True) as tx:
                tx.execute("""INSERT INTO identity_staff (school_id,actor_id,email,password_hash,name,
                              actor_type,status,permissions,school_wide) VALUES (
                              'UI-test','office','test@example.test','unused','教务','admin','normal',?,1)""", (json.dumps(scopes),))
            for line in sys.stdin:
                req = json.loads(line)
                prefix = "/api/admin/identity"
                assert req["url"].startswith(prefix + "/")
                path = req["url"][len(prefix):]
                route = urlsplit(path).path
                method = req["method"]
                if method == "GET" and route == "/v1/students":
                    action = "student.read"
                elif method in {"GET", "PUT"} and route.endswith("/grants"):
                    action = "permissions.manage"
                elif method == "POST" and route == "/students/import":
                    action = "student.import"
                elif method == "POST" and route.endswith("/reset-password"):
                    action = "student.reset"
                elif method == "PATCH" and route.endswith("/status"):
                    action = "student.status"
                else:
                    raise ValueError("Unexpected component request")
                os.environ["SERVICE_ID"] = "ui-test"
                headers = service_headers("identity", actor_id="office", school_id="UI-test", actor_type="admin", scopes=[action])
                os.environ["SERVICE_ID"] = "identity"
                reply = client.request(method, path, json=req.get("body"), headers=headers)
                print(json.dumps({"status":reply.status_code, "data":reply.json()}), flush=True)


if __name__ == "__main__":
    main()
