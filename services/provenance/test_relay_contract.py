"""离线联测证书事件投递、带签名的 HTTP 路由和存证进程。"""
import json
from pathlib import Path
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
import httpx

from services.credentials import relay, storage
from shared.service_db import ServiceDatabase
from .adapter import ManagedEvm
from .app import create_app
from .test_provenance import ACCOUNT, DEST, DIGEST, EVENT, LocalChainFixture, RPC, SUBMIT, TX
from .worker import run_once


class RelayContractTest(unittest.TestCase):
    def test_outage_retry_and_public_readback(self):
        # 为两个服务分别创建数据库，并在请求边界切换服务身份。
        tmp = Path(self.enterContext(TemporaryDirectory()))
        school = "contract-test-school"
        secret = Ed25519PrivateKey.generate()
        pub = secret.public_key().public_bytes(serialization.Encoding.PEM,
                                               serialization.PublicFormat.SubjectPublicKeyInfo)
        pem = secret.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                   serialization.NoEncryption())
        trust = {"credentials": {
            "keys": {"temp": pub.decode()}, "schools": [school],
            "grants": {"provenance": {"system": ["provenance.read", "provenance.submit"]}}}}
        self.enterContext(patch.dict("os.environ", {
            "CREDENTIALS_DB_ENGINE": "sqlite", "CREDENTIALS_SQLITE_PATH": str(tmp / "credentials.sqlite"),
            "PROVENANCE_DB_ENGINE": "sqlite", "PROVENANCE_SQLITE_PATH": str(tmp / "provenance.sqlite"),
            "SERVICE_ID": "credentials", "SERVICE_KEY_ID": "temp", "SERVICE_SIGNING_KEY": pem.decode(),
            "SERVICE_TRUST_POLICY": json.dumps(trust), "PROVENANCE_SERVICE_URL": "https://proof.invalid"}))
        credentials = storage.database()
        storage.initialize(credentials)
        proof_app = create_app(ServiceDatabase.from_env("provenance"))
        api = self.enterContext(TestClient(proof_app, base_url="https://proof.invalid"))
        event = {"event_id": EVENT, "digest": DIGEST, "school_id": school}
        with credentials.transaction(write=True) as tx:
            tx.execute("INSERT INTO credential_outbox(event_id,digest,school_id) VALUES(?,?,?)",
                       (EVENT, DIGEST, school))

        available = False

        def dispatch(method, url, **kwargs):
            # 仅替换网络传输，实际执行服务签名、路由鉴权及两端数据库操作。
            if not available:
                raise httpx.ConnectError("fixture outage")
            kwargs.pop("trust_env", None)
            kwargs.pop("timeout", None)
            self.assertTrue(url.startswith("https://proof.invalid/internal/anchors"))
            with patch.dict("os.environ", {"SERVICE_ID": "provenance"}):
                return api.request(method, url, **kwargs)

        self.enterContext(patch.object(relay.httpx, "request", dispatch))
        self.assertTrue(relay.deliver_one(credentials, now=100))
        self.assertEqual(relay.anchor_status(event), {"status": "unconfirmed"})
        self.assertFalse(relay.deliver_one(credentials, now=101))
        available = True
        self.assertTrue(relay.deliver_one(credentials, now=102))
        self.assertEqual(relay.anchor_status(event), {"status": "pending"})
        self.assertFalse(relay.deliver_one(credentials, now=1000))

        chain = LocalChainFixture()
        client = self.enterContext(httpx.Client(transport=httpx.MockTransport(chain.handle)))
        adapter = ManagedEvm(client, submit_url=SUBMIT, rpc_url=RPC, chain_id=31337,
                             account=ACCOUNT, recipient=DEST, token="fixture-token")
        adapter.network = "fixture"
        self.assertTrue(run_once(proof_app.state.anchors, adapter, clock=lambda: 200))
        expected = {"network": "fixture", "fixture": True, "status": "submitted"}
        self.assertEqual(relay.anchor_status(event), expected)
        chain.mine()
        chain.finalized["number"] = "0x4"
        self.assertTrue(run_once(proof_app.state.anchors, adapter, clock=lambda: 210))
        self.assertEqual(relay.anchor_status(event), expected)
        chain.finalized["number"] = "0x5"
        self.assertTrue(run_once(proof_app.state.anchors, adapter, clock=lambda: 220))
        confirmed = {**expected, "status": "confirmed", "tx_hash": TX, "block_number": 5}
        self.assertEqual(relay.anchor_status(event), confirmed)

        # 已经确认过的事件在查询失联时也应显示未核实。
        available = False
        self.assertEqual(relay.anchor_status(event), {"status": "unconfirmed"})
        available = True
        self.assertEqual(relay.anchor_status(event), confirmed)
