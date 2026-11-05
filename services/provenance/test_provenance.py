"""使用独立测试密钥、临时库与内存链回执验证存证流程。"""
import json
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
import httpx
import jwt

from shared.service_db import ServiceDatabase
from .adapter import ManagedEvm
from .app import create_app
from .store import AnchorStore, ConflictingDigest
from .worker import run_once

EVENT = "01" * 16
DIGEST = "11" * 32
TX = "0x" + "ab" * 32
BLOCK = "0x" + "cd" * 32
ACCOUNT = "0x" + "01" * 20
DEST = "0x" + "02" * 20
SUBMIT = "https://submit.invalid/transactions"
RPC = "https://rpc.invalid/"


class LocalChainFixture:
    """模拟幂等提交端与 RPC，由测试控制出块和最终确认。"""
    def __init__(self):
        self.submissions = {}
        self.rpc = {"eth_chainId": "0x7a69", "eth_getTransactionReceipt": None}
        self.finalized = {"number": "0x5", "hash": BLOCK}
        self.canonical = {"number": "0x5", "hash": BLOCK, "transactions": [TX]}
        self.lose_response = False

    def handle(self, req):
        body = json.loads(req.content)
        if str(req.url) == SUBMIT:
            assert req.headers["authorization"] == "Bearer fixture-token"
            key = req.headers["Idempotency-Key"]
            assert self.submissions.setdefault(key, body) == body
            if self.lose_response:
                self.lose_response = False
                raise httpx.ReadTimeout("simulated lost acknowledgement")
            return httpx.Response(200, json={"transactionHash": TX})
        assert str(req.url) == RPC and "authorization" not in req.headers
        method, params = body["method"], body["params"]
        if method == "eth_getBlockByNumber":
            value = self.finalized if params[0] == "finalized" else self.canonical
        else:
            value = self.rpc[method]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": value})

    def mine(self):
        call = next(iter(self.submissions.values()))
        self.rpc["eth_getTransactionReceipt"] = {
            "transactionHash": TX, "status": "0x1", "blockNumber": "0x5", "blockHash": BLOCK}
        self.rpc["eth_getTransactionByHash"] = {
            "hash": TX, "from": call["from"], "to": call["to"], "value": call["value"],
            "input": call["data"], "blockNumber": "0x5", "blockHash": BLOCK,
        }


class AnchorTests(unittest.TestCase):
    def setUp(self):
        tmp = self.enterContext(TemporaryDirectory())
        self.db = ServiceDatabase.from_env("provenance", {
            "PROVENANCE_DB_ENGINE": "sqlite", "PROVENANCE_SQLITE_PATH": str(Path(tmp) / "test.db")})
        self.store = AnchorStore(self.db)
        self.store.initialize()
        self.fixture = LocalChainFixture()
        http = self.enterContext(httpx.Client(transport=httpx.MockTransport(self.fixture.handle)))
        self.adapter = ManagedEvm(http, submit_url=SUBMIT, rpc_url=RPC, chain_id=31337,
                                  account=ACCOUNT, recipient=DEST, token="fixture-token")
        self.adapter.network = "fixture"
        self.now = 1000

    def step(self):
        run_once(self.store, self.adapter, lambda: self.now)
        self.now += 10
        return self.store.get("School", EVENT)

    def test_idempotent_submission_and_finalized_confirmation(self):
        self.store.put("School", EVENT, DIGEST)
        self.fixture.lose_response = True
        self.assertEqual(self.step()["status"], "pending")
        self.assertEqual(self.step()["status"], "submitted")
        self.assertEqual(len(self.fixture.submissions), 1)
        self.assertEqual(self.step()["status"], "submitted")
        self.fixture.mine()
        self.fixture.finalized["number"] = "0x4"
        self.assertEqual(self.step()["status"], "submitted")
        self.fixture.finalized["number"] = "0x5"
        self.fixture.canonical["hash"] = "0x" + "00" * 32
        self.assertEqual(self.step()["status"], "submitted")
        self.fixture.canonical["hash"] = BLOCK
        self.fixture.canonical["transactions"] = []
        self.assertEqual(self.step()["status"], "submitted")
        self.fixture.canonical["transactions"] = [TX]
        result = self.step()
        self.assertEqual(result, {"event_id": EVENT, "digest": DIGEST, "status": "confirmed",
                                  "network": "fixture", "tx_hash": TX, "block_number": 5})
        self.assertFalse(run_once(self.store, self.adapter, lambda: self.now))
        self.assertEqual(result, self.store.put("School", EVENT, DIGEST))

    def test_reverted_transaction(self):
        self.store.put("School", EVENT, DIGEST)
        self.step()
        self.fixture.mine()
        self.fixture.rpc["eth_getTransactionReceipt"]["status"] = "0x0"
        self.assertEqual(self.step()["status"], "failed")

    def test_restart_after_broadcast_before_transaction_saved(self):
        self.store.put("School", EVENT, DIGEST)
        lease = self.store.claim(100, "fixture", self.adapter.binding)
        self.assertEqual(self.adapter.submit(lease), TX)
        # 模拟广播成功后、交易哈希写回前进程退出；新进程从数据库恢复。
        recovered = AnchorStore(self.db)
        recovered.initialize()
        new_client = self.enterContext(httpx.Client(transport=httpx.MockTransport(self.fixture.handle)))
        adapter = ManagedEvm(new_client, submit_url=SUBMIT, rpc_url=RPC, chain_id=31337,
                             account=ACCOUNT, recipient=DEST, token="fixture-token")
        adapter.network = "fixture"
        self.assertFalse(run_once(recovered, adapter, clock=lambda: 159))
        self.assertTrue(run_once(recovered, adapter, clock=lambda: 160))
        self.assertEqual(recovered.get("School", EVENT)["status"], "submitted")
        self.assertEqual(len(self.fixture.submissions), 1)
        expected = sha256(b"teaching-anchor-v1\0" + sha256(b"School").digest()
                          + bytes.fromhex(EVENT) + bytes.fromhex(DIGEST)).hexdigest()
        self.assertEqual(next(iter(self.fixture.submissions.values())), {
            "chainId": 31337, "from": ACCOUNT, "to": DEST, "value": "0x0", "data": "0x" + expected})
        self.fixture.mine()
        self.assertTrue(run_once(recovered, adapter, clock=lambda: 170))
        self.assertEqual(recovered.get("School", EVENT)["status"], "confirmed")

    def test_wrong_rpc_response_id_keeps_transaction_unconfirmed(self):
        self.store.put("School", EVENT, DIGEST)
        self.step()
        self.fixture.mine()

        def invalid_id(request):
            response = self.fixture.handle(request).json()
            # Python 中 True == 1，但布尔值不能匹配 JSON-RPC 的数字请求标识。
            return httpx.Response(200, json={**response, "id": True})

        self.adapter.client = self.enterContext(httpx.Client(transport=httpx.MockTransport(invalid_id)))
        self.assertEqual(self.step()["status"], "submitted")

    def test_wrong_commitment(self):
        self.store.put("School", EVENT, DIGEST)
        self.step()
        self.fixture.mine()
        self.fixture.rpc["eth_getTransactionByHash"]["input"] = "0x" + DIGEST
        self.assertEqual(self.step()["status"], "failed")

    def test_wrong_rpc_network_or_changed_account(self):
        self.store.put("School", EVENT, DIGEST)
        self.fixture.rpc["eth_chainId"] = "0x1"
        self.assertEqual(self.step()["status"], "pending")
        self.assertFalse(self.fixture.submissions)
        self.adapter.account = "0x" + "09" * 20
        self.assertFalse(run_once(self.store, self.adapter, lambda: self.now))

    def test_duplicate_concurrent_requests_and_fenced_leases(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(lambda _: self.store.put("School", EVENT, DIGEST), range(8)))
        self.assertTrue(all(row == rows[0] for row in rows))
        with self.assertRaises(ConflictingDigest):
            self.store.put("School", EVENT, "55" * 32)
        lease1 = self.store.claim(100, "fixture", self.adapter.binding)
        self.assertIsNone(self.store.claim(120, "fixture", self.adapter.binding))
        lease2 = self.store.claim(160, "fixture", self.adapter.binding)
        self.assertFalse(self.store.finish(lease1, "confirmed", TX, 5, 200))
        self.assertTrue(self.store.finish(lease2, "submitted", TX, None, 200))

    def test_routes_and_signed_tenant_scope(self):
        key = Ed25519PrivateKey.generate()
        pub = key.public_key().public_bytes(serialization.Encoding.PEM,
                                            serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        scopes = ["provenance.read", "provenance.submit"]
        peer = {"keys": {"test": pub}, "grants": {"provenance": {"system": scopes, "teacher": scopes}},
                "schools": ["School", "school"]}
        verifier = "credentials-verifier"
        verifier_key = Ed25519PrivateKey.generate()
        verifier_pem = verifier_key.public_key().public_bytes(serialization.Encoding.PEM,
                                                              serialization.PublicFormat.SubjectPublicKeyInfo)
        # 故意向验真进程多授写权限，验证路由仍会拒绝写入和混用身份。
        policy = {"credentials": peer, "unrelated": peer,
                  verifier: {**peer, "keys": {"test": verifier_pem.decode()}}}
        self.enterContext(patch.dict("os.environ", {
            "SERVICE_ID": "provenance", "SERVICE_TRUST_POLICY": json.dumps(policy)}))
        app = self.enterContext(TestClient(create_app(self.db)))

        def headers(school="School", issuer="credentials", role="system",
                    actor="credentials-relay", grants=None):
            now = int(time.time())
            claims = {"iss": issuer, "sub": actor, "aud": "provenance", "scopes": grants or scopes,
                      "school_id": school, "actor_type": role, "iat": now, "exp": now + 30, "jti": "test"}
            signing_key = verifier_key if issuer == verifier else key
            token = jwt.encode(claims, signing_key, algorithm="EdDSA",
                               headers={"kid": "test", "typ": "service+jwt"})
            return {"Authorization": f"Bearer {token}"}

        body = {"event_id": EVENT, "digest": DIGEST}
        url = "/internal/anchors"
        self.assertEqual(app.post(url, json=body).status_code, 401)
        for invalid in (headers(issuer="unrelated"), headers(role="teacher"), headers(actor="user"),
                        headers(grants=["provenance.read"]), headers(school="foreign")):
            self.assertEqual(app.post(url, headers=invalid, json=body).status_code, 403)
        self.assertEqual(app.post(url, headers=headers(), json={**body, "school_id": "x"}).status_code, 422)
        result = app.post(url, headers=headers(), json=body)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["status"], "pending")
        read_token = headers(issuer=verifier, actor=verifier, grants=["provenance.read"])
        self.assertEqual(app.get(f"{url}/{EVENT}", headers=read_token).json()["digest"], DIGEST)
        foreign = headers(school="school", issuer=verifier, actor=verifier, grants=["provenance.read"])
        self.assertEqual(app.get(f"{url}/{EVENT}", headers=foreign).status_code, 404)
        for invalid in (headers(issuer=verifier), headers(actor=verifier),
                        headers(issuer=verifier, actor=verifier, role="teacher")):
            self.assertEqual(app.get(f"{url}/{EVENT}", headers=invalid).status_code, 403)
        overgranted = headers(issuer=verifier, actor=verifier, grants=["provenance.submit"])
        self.assertEqual(app.post(url, headers=overgranted, json=body).status_code, 403)
        self.assertEqual(app.get(f"{url}/{EVENT}", headers=headers("school")).status_code, 404)
        other = {**body, "digest": "22" * 32}
        self.assertEqual(app.post(url, headers=headers("school"), json=other).status_code, 200)
        self.assertEqual(app.post(url, headers=headers(), json=other).status_code, 409)
        self.assertEqual(app.get(f"{url}/{EVENT}", headers=headers()).json()["digest"], DIGEST)
