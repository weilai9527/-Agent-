"""使用独立 SQLite 文件验证真实请求校验和 Ed25519 服务授权。"""
import json
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from shared.service_db import Transaction
from services.usage.app import app

PREFIX = "/internal/usage"
RESERVATIONS = PREFIX + "/reservations"


class UsageTests(unittest.TestCase):
    def setUp(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.signing_key = Ed25519PrivateKey.generate()
        public = self.signing_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        scopes = ["usage.read", "usage.configure", "usage.reserve", "usage.settle"]
        trust = {"schools": ["school1", "school2"], "keys": {"test": public},
                 "grants": {"usage": {role: scopes for role in ["admin", "student", "teacher"]}}}
        self.enterContext(patch.dict(os.environ, {
            "SERVICE_ID": "usage", "SERVICE_TRUST_POLICY": json.dumps({"interview": trust, "media": trust}),
            "USAGE_DB_ENGINE": "sqlite", "USAGE_SQLITE_PATH": str(Path(tmp) / "db.sqlite")}))
        self.client = self.enterContext(TestClient(app))
        self.configure()

    def auth(self, scope, *, school="school1", actor="student1", role="student", issuer="interview"):
        now = int(time.time())
        token = jwt.encode({"iss": issuer, "aud": "usage", "sub": actor, "school_id": school,
                            "actor_type": role, "scopes": [scope], "iat": now, "exp": now + 45,
                            "jti": str(uuid4())}, self.signing_key, algorithm="EdDSA",
                           headers={"kid": "test", "typ": "service+jwt"})
        return {"Authorization": "Bearer " + token}

    def configure(self, text=5, media=7):
        response = self.client.put(PREFIX + "/quota", json={"text": text, "media": media},
                                   headers=self.auth("usage.configure", role="admin"))
        self.assertEqual(response.status_code, 200, response.text)

    def quota(self):
        return self.client.get(PREFIX + "/quota", headers=self.auth("usage.read", role="admin")).json()

    def reserve(self, key="turn2", units=5, resource="text", ttl_seconds=120, **identity):
        return self.client.post(RESERVATIONS, headers=self.auth("usage.reserve", **identity),
                                json={"request_id": key, "resource": resource, "units": units, "ttl_seconds": ttl_seconds})

    def settle(self, rid, amount, **identity):
        return self.client.post(f"{RESERVATIONS}/{rid}/settle", headers=self.auth("usage.settle", **identity),
                                json={"actual_units": amount})

    def test_retries_refund_restart_and_conflicts(self):
        first = self.reserve().json()
        rid = first["reservation_id"]
        self.assertEqual(self.reserve().json(), first)
        self.assertEqual(self.reserve(units=1).status_code, 409)
        self.assertEqual(self.reserve(ttl_seconds=121).status_code, 409)
        self.assertEqual(self.reserve(resource="media").status_code, 409)
        self.assertEqual(self.settle(rid, 6).status_code, 409)
        self.assertEqual(self.quota()["text"]["available"], 0)
        done = self.settle(rid, 3).json()
        self.assertEqual(done["state"], "settled")
        with TestClient(app) as restarted:
            response = restarted.post(f"{RESERVATIONS}/{rid}/settle", json={"actual_units": 3},
                                      headers=self.auth("usage.settle"))
            self.assertEqual(response.json(), done)
        self.assertEqual(self.reserve().json(), done)
        self.assertEqual(self.settle(rid, 2).status_code, 409)
        self.assertEqual(self.quota()["text"], {"limit": 5, "used": 3, "reserved": 0, "available": 2})
        other = self.reserve("retry2", units=2).json()
        self.assertEqual(self.settle(other["reservation_id"], 0).status_code, 200)
        self.assertEqual(self.quota()["text"]["available"], 2)

    def test_expiry_exact_boundary_and_month_rollover(self):
        jan_end = int(datetime(2030, 2, 1, tzinfo=timezone.utc).timestamp()) - 1
        with patch.object(app.state.ledger, "_now", return_value=jan_end) as clock:
            first = self.reserve(ttl_seconds=1).json()
            media = self.reserve("media1", 3, "media", ttl_seconds=5).json()
            clock.return_value += 1
            self.assertEqual(self.reserve(ttl_seconds=1).json()["state"], "expired")
            self.assertEqual(self.settle(first["reservation_id"], 1).status_code, 409)
            self.assertEqual(self.settle(media["reservation_id"], 3).status_code, 200)
            self.assertEqual(self.quota()["media"]["used"], 0)
            feb = self.reserve("feb", ttl_seconds=1)
            self.assertEqual(feb.status_code, 200)
            self.assertEqual(self.quota()["text"]["available"], 0)
            clock.return_value += 1
            self.assertEqual(self.quota()["text"]["available"], 5)
            self.assertEqual(self.reserve("feb_again").status_code, 200)

    def test_degrade_and_reduce_limit_with_live_holds(self):
        response = self.reserve(units=8, resource="media")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["detail"],
                         {"code": "quota_exhausted", "resource": "media", "fallback": "text"})
        live = self.reserve().json()
        self.configure(text=1)
        self.assertEqual(self.reserve("next", 1).json()["detail"]["fallback"], "deferred")
        self.assertEqual(self.settle(live["reservation_id"], 4).status_code, 200)
        self.assertEqual(self.quota()["text"], {"limit": 1, "used": 4, "reserved": 0, "available": 0})
        self.assertEqual(self.reserve(school="school2").status_code, 429)

    def test_identity_ownership_and_validation(self):
        rid = self.reserve().json()["reservation_id"]
        for change in [{"actor": "other"}, {"school": "school2"}, {"issuer": "media"}, {"role": "teacher"}]:
            self.assertEqual(self.settle(rid, 0, **change).status_code, 404)
        self.assertEqual(self.client.get(PREFIX + "/quota").status_code, 401)
        self.assertEqual(self.client.get(PREFIX + "/quota", headers=self.auth("usage.read")).status_code, 403)
        self.assertEqual(self.client.get(PREFIX + "/quota", headers=self.auth("usage.reserve", role="admin")).status_code, 403)
        for changes in [{"school_id": "school2"}, {"units": -1}, {"units": True}, {"ttl_seconds": 0}]:
            body = {"resource": "text", "request_id": "test", "units": 1, **changes}
            response = self.client.post(RESERVATIONS, json=body, headers=self.auth("usage.reserve"))
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.quota()["text"]["reserved"], 5)

    def test_atomic_under_concurrent_admission_and_settlement(self):
        racers = 16
        barrier = Barrier(racers)

        def request_slot(index):
            barrier.wait(timeout=10)
            return self.reserve(str(index), 1)

        with ThreadPoolExecutor(max_workers=racers) as pool:
            results = list(pool.map(request_slot, range(racers)))
        settled = [r.json()["reservation_id"] for r in results if r.status_code == 200]
        self.assertEqual(len(settled), 5)
        self.assertEqual(sum(r.status_code == 429 for r in results), 11)
        # 获得额度的调用方各用独立连接，并发重复提交结算。
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(lambda rid: self.settle(rid, 1), settled * 2))
        self.assertTrue(all(r.status_code == 200 for r in results))
        self.assertEqual(self.quota()["text"], {"limit": 5, "used": 5, "reserved": 0, "available": 0})

    def test_transaction_interruption_rolls_back_both_changes(self):
        rid = self.reserve().json()["reservation_id"]
        original = Transaction.execute

        def interrupt(tx, sql, params=()):
            if "INSERT INTO usage_spent" in sql:
                raise RuntimeError("simulated process interruption")
            return original(tx, sql, params)

        with patch.object(Transaction, "execute", interrupt), self.assertRaisesRegex(RuntimeError, "interruption"):
            self.settle(rid, 2)
        self.assertEqual(self.quota()["text"], {"limit": 5, "used": 0, "reserved": 5, "available": 0})
        self.assertEqual(self.settle(rid, 2).json()["state"], "settled")
        self.assertEqual(self.quota()["text"]["used"], 2)


if __name__ == "__main__":
    unittest.main()
