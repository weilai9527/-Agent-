import json
import os
import unittest

import httpx
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from services.media import omni_socket as omni


STREAM_HTTP = omni.stream_http


class OmniSocketTests(unittest.TestCase):
    path = "/ws/interviews/interview1/qwen/omni-realtime"

    def setUp(self):
        app = FastAPI()
        app.include_router(omni.router)
        self.client = self.enterContext(TestClient(app))
        self.actor = {"actor_id": "student1", "school_id": "school1", "actor_type": "student",
                      "caller": "gateway", "scopes": ["media.voice.connect"]}
        self.ctx = {"question_order": 3, "question_id": "q3", "role_id": "tech", "active_agent": "工程师",
                    "greeting": "当前题", "prompt": "当前轮次指令"}
        self.authorize = self.enterContext(patch.object(omni, "authorize", return_value=self.actor))
        self.session = self.enterContext(patch.object(omni, "owned_session", return_value=self.ctx))
        self.admit = self.enterContext(patch.object(omni, "admit"))
        self.settings = self.enterContext(patch.object(omni, "media_settings", return_value={}))
        self.stream = self.enterContext(patch.object(omni, "stream_http", new_callable=AsyncMock))

        async def respond(socket, *args):
            await socket.send_json({"type": "audio_done"})

        self.stream.side_effect = respond
        self.enterContext(patch.dict(os.environ, {"QWEN_OMNI_TRANSPORT": "http", "QWEN_OMNI_API_KEY": "test-dedicated",
                                                  "QWEN_OMNI_REALTIME_WS_URL": "", "DASHSCOPE_API_KEY": "",
                                                  "QWEN_OMNI_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1"}))

    def start(self, ws):
        self.assertEqual(ws.receive_json()["type"], "status")
        ws.send_json({"type": "start", "mimeType": "audio/webm;codecs=opus", "currentQuestion": "恶意覆盖",
                      "instructions": "浏览器注入", "activeAgent": "其他角色"})
        self.assertEqual(ws.receive_json()["type"], "status")

    def test_authoritative_http_round(self):
        with self.client.websocket_connect(self.path) as ws:
            self.start(ws)
            ws.send_bytes(b"abc")
            ws.send_bytes(b"def")
            ws.send_json({"type": "stop", "prompt": "浏览器注入"})
            self.assertEqual(ws.receive_json()["type"], "audio_done")
        _, audio, mime, config, url = self.stream.await_args.args
        self.assertEqual(url, "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.assertEqual(self.settings.call_count, 2)
        self.assertEqual((audio, mime), (b"abcdef", "audio/webm;codecs=opus"))
        self.assertEqual((config["current_question"], config["instructions"], config["active_agent"]),
                         ("当前题", "当前轮次指令", "工程师"))
        self.assertEqual(self.session.call_count, 3)
        self.admit.assert_called_once()

    def test_role_or_question_changes_discard_audio(self):
        for change in [{"question_order": 4}, {"question_id": "q4"}, {"role_id": "hr"}]:
            self.session.side_effect = [self.ctx, self.ctx, {**self.ctx, **change}]
            with self.client.websocket_connect(self.path) as ws:
                self.start(ws)
                ws.send_bytes(b"old answer")
                ws.send_json({"type": "stop"})
                self.assertIn("已变化", ws.receive_json()["message"])
        self.stream.assert_not_called()
        self.admit.assert_not_called()

    def test_oversize_and_timeout_never_reach_provider(self):
        with patch.object(omni, "MAX_AUDIO_BYTES", 3), self.client.websocket_connect(self.path) as ws:
            self.start(ws)
            ws.send_bytes(b"ab")
            ws.send_bytes(b"cd")
            self.assertIn("过大", ws.receive_json()["message"])
            with self.assertRaises(WebSocketDisconnect) as closed:
                ws.receive_text()
            self.assertEqual(closed.exception.code, 1009)
        with patch.object(omni, "MAX_RECORD_SECONDS", 0), self.client.websocket_connect(self.path) as ws:
            self.start(ws)
            self.assertIn("过长", ws.receive_json()["message"])
        self.stream.assert_not_called()
        self.admit.assert_not_called()

    def test_invalid_scope_owner_quota_and_provider_disabled(self):
        self.authorize.side_effect = HTTPException(403, "Wrong signature or scope")
        with self.assertRaises(WebSocketDisconnect), self.client.websocket_connect(self.path):
            pass
        self.authorize.side_effect = None
        self.session.side_effect = HTTPException(404, "Wrong school")
        with self.assertRaises(WebSocketDisconnect), self.client.websocket_connect(self.path):
            pass
        self.session.side_effect = None
        with patch.dict(os.environ, {"QWEN_OMNI_API_KEY": ""}), self.client.websocket_connect(self.path) as ws:
            self.assertIn("未配置", ws.receive_json()["message"])
        with (patch.dict(os.environ, {"QWEN_OMNI_TRANSPORT": "ws", "QWEN_OMNI_REALTIME_WS_URL": "wss://untrusted.invalid/",
                                      "QWEN_OMNI_REALTIME_API_KEY": "selfhosted"}),
              self.client.websocket_connect(self.path) as ws):
            self.assertIn("未获授权", ws.receive_json()["message"])
        self.admit.assert_not_called()
        self.admit.side_effect = HTTPException(429, {"code": "quota_exhausted", "fallback": "text"})
        with self.client.websocket_connect(self.path) as ws:
            self.start(ws)
            ws.send_bytes(b"answer")
            ws.send_json({"type": "stop"})
            self.assertEqual(ws.receive_json()["fallback"], "text")
        self.stream.assert_not_called()

    def test_generic_key_without_authorized_transport_cannot_upload_audio(self):
        for mode in ("", "ws", "automatic"):
            with self.subTest(mode=mode), patch.dict(os.environ, {"QWEN_OMNI_TRANSPORT": mode,
                    "QWEN_OMNI_REALTIME_WS_URL": "", "DASHSCOPE_API_KEY": "official-only"}):
                with self.client.websocket_connect(self.path) as ws:
                    event = ws.receive_json()
                    self.assertEqual((event["type"], event["fallback"]), ("error", "text"))
        self.admit.assert_not_called()
        self.stream.assert_not_called()

    def test_control_plane_loss_between_record_and_submit_costs_nothing(self):
        self.settings.side_effect = [{}, HTTPException(503, "控制服务离线")]
        with self.client.websocket_connect(self.path) as ws:
            self.start(ws)
            ws.send_bytes(b"audio")
            ws.send_json({"type": "stop"})
            self.assertEqual(ws.receive_json()["fallback"], "text")
        self.admit.assert_not_called()
        self.stream.assert_not_called()

    def test_http_vendor_refusal_does_not_use_websocket_or_expose_vendor_detail(self):
        hosts = []

        async def deny(transport, request):
            hosts.append(request.url.host)
            return httpx.Response(403, json={"debug": "敏感厂商错误"})

        self.stream.side_effect = STREAM_HTTP
        with (patch.dict(os.environ, {"QWEN_OMNI_STREAM": "false"}),
              patch.object(httpx.AsyncHTTPTransport, "handle_async_request", deny),
              patch.object(omni, "stream_ws", new_callable=AsyncMock) as send_ws,
              self.client.websocket_connect(self.path) as ws):
            self.start(ws)
            ws.send_bytes(b"audio")
            ws.send_json({"type": "stop"})
            self.assertEqual(ws.receive_json()["type"], "status")
            failure = ws.receive_json()
            self.assertEqual((failure["type"], failure["fallback"]), ("error", "text"))
            self.assertNotIn("敏感厂商错误", str(failure))
        self.assertEqual(hosts, ["dashscope.aliyuncs.com"])
        self.admit.assert_called_once()
        send_ws.assert_not_called()

    def test_unavailable_self_hosted_peer_does_not_send_to_http(self):
        url = "wss://dedicated.example.test/omni"
        with (patch.dict(os.environ, {"QWEN_OMNI_TRANSPORT": "", "QWEN_OMNI_REALTIME_WS_URL": url,
                                     "PROVIDER_ALLOWED_QWEN_WS_ENDPOINTS": url,
                                     "QWEN_OMNI_REALTIME_API_KEY": "dedicated"}),
              patch.object(omni, "stream_ws", AsyncMock(side_effect=OSError("断开连接"))) as send_ws,
              self.client.websocket_connect(self.path) as ws):
            self.start(ws)
            ws.send_bytes(b"audio")
            ws.send_json({"type": "stop"})
            self.assertEqual(ws.receive_json()["fallback"], "text")
        send_ws.assert_awaited_once()
        self.stream.assert_not_called()

    def test_self_hosted_round_protocol_and_isolated_credential(self):
        # 用隔离的异步连接验证自托管供应商收到的会话与音频帧。
        class Connection:
            def __init__(client, url, **kwargs):
                urls.append((url, kwargs))
            async def __aenter__(client):
                return client
            async def __aexit__(client, *args):
                pass
            async def send(client, frame):
                frames.append(frame)
            async def __aiter__(client):
                yield b"voice-response"
                yield '{"type":"audio_done"}'

        urls, frames = [], []
        url = "wss://dedicated.example.test/omni"
        with (patch.dict(os.environ, {"QWEN_OMNI_TRANSPORT": "ws", "QWEN_OMNI_REALTIME_WS_URL": url,
                                     "PROVIDER_ALLOWED_QWEN_WS_ENDPOINTS": url,
                                     "QWEN_OMNI_REALTIME_API_KEY": "test-selfhosted"}),
              patch("websockets.connect", Connection), self.client.websocket_connect(self.path) as ws):
            self.start(ws)
            ws.send_bytes(b"answer")
            ws.send_json({"type": "stop"})
            self.assertEqual(ws.receive_bytes(), b"voice-response")
            self.assertEqual(ws.receive_json()["type"], "audio_done")
        self.assertEqual(urls[0][1]["additional_headers"], {"Authorization": "Bearer test-selfhosted"})
        self.assertEqual(json.loads(frames[0])["session"]["instructions"], "当前轮次指令")
        self.assertEqual(json.loads(frames[1])["currentQuestion"], "当前题")
        self.assertEqual(frames[2:], [b"answer", '{"type":"stop"}'])
        self.admit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
