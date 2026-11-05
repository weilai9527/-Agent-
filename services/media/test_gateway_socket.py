import asyncio
import json
import os
import unittest
from threading import Event
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from services.identity.browser import check_origin
from services.media import gateway_socket as bridge


class TestPeer:
    __test__ = False

    def __init__(self):
        self.outbox = asyncio.Queue()
        self.received = []
        self.closed = Event()
        self.receiver_stopped = Event()
        self.ready = Event()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.closed.set()

    async def send(self, frame):
        self.received.append(frame)
        if isinstance(frame, str) and json.loads(frame)["type"] == "stop":
            await self.outbox.put(b"response-audio")
            await self.outbox.put('{"type":"audio_done","debug":"private-test-value"}')
            await self.outbox.put(None)

    async def __aiter__(self):
        self.ready.set()
        try:
            while (frame := await self.outbox.get()) is not None:
                yield frame
        finally:
            self.receiver_stopped.set()


class GatewaySocketTests(unittest.TestCase):
    path = "/ws/interviews/int-1/qwen/omni-realtime"

    def setUp(self):
        app = FastAPI()
        app.websocket("/ws/interviews/{interview_id}/qwen/omni-realtime")(bridge.relay_socket)
        self.client = self.enterContext(TestClient(app))
        self.client.cookies.set("session", "browser-only-cookie")
        self.key = Ed25519PrivateKey.generate()
        pem = self.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption()).decode()
        self.enterContext(patch.dict(os.environ, {"SERVICE_ID": "gateway", "SERVICE_KEY_ID": "test-key",
                                    "SERVICE_SIGNING_KEY": pem, "MEDIA_SERVICE_URL": "https://media.invalid"}))
        self.peer = TestPeer()
        self.connect = self.enterContext(patch.object(bridge, "DirectConnection", return_value=self.peer))
        self.actor = {"actor_id": "student", "school_id": "school", "actor_type": "student"}
        self.calls = []
        self.switch_at = None

        async def sync(request, interview_id, scope):
            self.calls.append((request, interview_id, scope))
            check_origin(request)
            return {**self.actor, "school_id": "other"} if len(self.calls) == self.switch_at else self.actor

        self.enterContext(patch("services.media.gateway.sync_browser_context", side_effect=sync))

    def websocket(self, **headers):
        return self.client.websocket_connect(self.path, headers={"origin": "http://testserver", **headers})

    def test_scoped_handshake_refreshed_turn_and_downstream_disconnect(self):
        with self.websocket() as ws:
            ws.send_json({"type": "start", "mimeType": "audio/webm", "sampleRate": 16000,
                          "currentQuestion": "injected", "activeAgent": "injected", "session": {"override": True}})
            ws.send_bytes(b"recording")
            ws.send_json({"type": "stop", "system": "injected"})
            self.assertEqual(ws.receive_bytes(), b"response-audio")
            self.assertEqual(ws.receive_json(), {"type": "audio_done"})
            with self.assertRaises(WebSocketDisconnect) as closed:
                ws.receive_text()
            self.assertEqual(closed.exception.code, 1000)
        self.assertTrue(self.peer.closed.wait(2))
        self.assertTrue(self.peer.receiver_stopped.is_set())
        self.assertEqual(len(self.calls), 3)
        for request, interview_id, scope in self.calls:
            self.assertEqual((request.method, request.cookies["session"], interview_id, scope),
                             ("POST", "browser-only-cookie", "int-1", bridge.SCOPE))
        url = self.connect.call_args.args[0]
        self.assertEqual(url, "wss://media.invalid" + self.path)
        kwargs = self.connect.call_args.kwargs
        self.assertEqual(list(kwargs["additional_headers"]), ["Authorization"])
        self.assertIsNone(kwargs.get("proxy"))
        token = kwargs["additional_headers"]["Authorization"].split()[1]
        claims = jwt.decode(token, self.key.public_key(), algorithms=["EdDSA"], audience="media", issuer="gateway")
        self.assertEqual((claims["scopes"], claims["sub"], claims["school_id"]), ([bridge.SCOPE], "student", "school"))
        self.assertEqual(self.peer.received, [json.dumps({"type": "start", "mimeType": "audio/webm",
                                                          "sampleRate": 16000}), b"recording", '{"type": "stop"}'])

    def test_cross_origin_and_rebound_identity_blocked(self):
        with self.assertRaises(WebSocketDisconnect), self.websocket(origin="https://attacker.invalid"):
            pass
        self.connect.assert_not_called()
        self.calls.clear()
        self.switch_at = 2
        with self.websocket() as ws:
            ws.send_json({"type": "start"})
            with self.assertRaises(WebSocketDisconnect) as denied:
                ws.receive_text()
            self.assertEqual(denied.exception.code, 1008)
        self.assertFalse(self.peer.received)
        self.assertTrue(self.peer.closed.is_set())

    def test_invalid_control_audio_before_start_and_aggregate_audio_cap(self):
        for events, code, count in [([{"type": "session.start"}], 1008, 0), ([b"early"], 1008, 0),
                                    ([{"type": "start"}, b"ab", b"cd"], 1009, 2)]:
            with self.subTest(events=events):
                self.peer.received.clear()
                with patch.object(bridge, "MAX_AUDIO_BYTES", 3), self.websocket() as ws:
                    for event in events:
                        if isinstance(event, bytes):
                            ws.send_bytes(event)
                        else:
                            ws.send_json(event)
                    with self.assertRaises(WebSocketDisconnect) as denied:
                        ws.receive_text()
                    self.assertEqual(denied.exception.code, code)
                self.assertEqual(len(self.peer.received), count)

    def test_browser_disconnect_cancels_peer_receive(self):
        with self.websocket() as ws:
            self.assertTrue(self.peer.ready.wait(2))
            ws.close()
            self.assertTrue(self.peer.receiver_stopped.wait(2))
            self.assertTrue(self.peer.closed.wait(2))


if __name__ == "__main__":
    unittest.main()
