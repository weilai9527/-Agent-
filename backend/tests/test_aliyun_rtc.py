from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest
from unittest.mock import patch

from backend.src.rtc_ai_agent_service import (
    generate_rtc_ai_agent_task_id,
    get_rtc_ai_agent,
    notify_rtc_ai_agent,
    rtc_ai_agent_client_config,
    start_rtc_ai_agent,
    stop_rtc_ai_agent,
    task_belongs_to_interview,
)
from backend.src.rtc_token_service import AppToken, Service, generate_rtc_token, normalize_rtc_user_name


class AliyunRtcTokenServiceTests(unittest.TestCase):
    def test_token_is_scoped_to_audio_publish(self):
        with patch.dict(
            os.environ,
            {
                "RTC_APP_ID": "test_app",
                "RTC_APP_KEY": "test_secret",
                "RTC_TOKEN_TTL_SECONDS": "900",
            },
            clear=False,
        ), patch("backend.src.rtc_token_service.time.time", return_value=1_800_000_000):
            result = generate_rtc_token("interview_123", "user_456")

        parsed = AppToken.parse(result["token"])
        self.assertEqual(result["app_id"], "test_app")
        self.assertEqual(result["expires_in"], 900)
        self.assertEqual(result["timestamp"], 1_800_000_900)
        self.assertEqual(parsed.service.channel_id, "interview_123")
        self.assertEqual(parsed.service.user_id, "user_456")
        self.assertEqual(
            parsed.service.privilege,
            Service.ENABLE_PRIVILEGE | Service.ENABLE_AUDIO_PRIVILEGE,
        )

    def test_rejects_invalid_rtc_identifiers(self):
        with patch.dict(
            os.environ,
            {"RTC_APP_ID": "test_app", "RTC_APP_KEY": "test_secret"},
            clear=False,
        ):
            with self.assertRaises(ValueError):
                generate_rtc_token("invalid channel", "user_456")
            with self.assertRaises(ValueError):
                generate_rtc_token("interview_123", "invalid/user")

    def test_user_name_is_limited_by_utf8_bytes(self):
        user_name = normalize_rtc_user_name("面试候选人" * 20)
        self.assertLessEqual(len(user_name.encode("utf-8")), 64)
        self.assertTrue(user_name)


class AliyunRtcAiAgentServiceTests(unittest.TestCase):
    def setUp(self):
        self.environment = {
            "RTC_APP_ID": "test_app",
            "RTC_AI_AGENT_TEMPLATE_ID": "template_1",
            "ALIBABA_CLOUD_ACCESS_KEY_ID": "test_access_key_id",
            "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "test_access_key_secret",
            "RTC_AI_AGENT_CHAT_MODE": "1",
            "RTC_AI_AGENT_INTERRUPT_MODE": "1",
            "RTC_AI_AGENT_USER_INACTIVITY_TIMEOUT": "45",
            "RTC_AI_AGENT_SOURCE_LANGUAGE": "zh",
        }

    def test_builds_start_and_stop_requests_for_one_candidate(self):
        class Body:
            request_id = "request_1"
            status = "Running"
            message = ""
            start_time = "2026-09-19T12:00:00Z"
            stop_time = None

        class Response:
            body = Body()

        class FakeClient:
            def __init__(self):
                self.start_request = None
                self.stop_request = None

            def start_agent(self, request):
                self.start_request = request
                return Response()

            def stop_agent(self, request):
                self.stop_request = request
                return Response()

            def get_agent(self, request):
                self.get_request = request
                return Response()

            def notify_agent(self, request):
                self.notify_request = request
                return Response()

        client = FakeClient()
        with patch.dict(os.environ, self.environment, clear=False):
            started = start_rtc_ai_agent(
                channel_id="interview_1",
                candidate_user_id="user_1",
                agent_user_id="agent_1",
                task_id="task_1",
                greeting="请回答当前问题。",
                prompt="候选人结构化简历分析：负责过实时音视频项目。",
                client=client,
            )
            stopped = stop_rtc_ai_agent(
                channel_id="interview_1",
                task_id="task_1",
                client=client,
            )
            notified = notify_rtc_ai_agent(
                channel_id="interview_1",
                task_id="task_1",
                message="请继续介绍你的方案取舍。",
                client=client,
            )
            inspected = get_rtc_ai_agent(
                channel_id="interview_1",
                task_id="task_1",
                client=client,
            )

        self.assertEqual(started["request_id"], "request_1")
        self.assertEqual(client.start_request.app_id, "test_app")
        self.assertEqual(client.start_request.template_id, "template_1")
        self.assertEqual(client.start_request.rtc_config.user_id, "agent_1")
        self.assertEqual(client.start_request.rtc_config.target_user_ids, ["user_1"])
        self.assertEqual(client.start_request.rtc_config.user_inactivity_timeout, 45)
        self.assertEqual(client.start_request.voice_chat_config.chat_mode, 1)
        self.assertEqual(client.start_request.voice_chat_config.asrconfig.source_language, "zh")
        self.assertEqual(client.start_request.voice_chat_config.greeting, "请回答当前问题。")
        self.assertIn("实时音视频项目", client.start_request.voice_chat_config.llmconfig.prompt)
        self.assertEqual(stopped["status"], "stopped")
        self.assertEqual(client.stop_request.task_id, "task_1")
        self.assertEqual(notified["status"], "notified")
        self.assertEqual(client.notify_request.message, "请继续介绍你的方案取舍。")
        self.assertEqual(inspected["status"], "Running")
        self.assertEqual(client.get_request.task_id, "task_1")

    def test_client_config_is_disabled_until_all_server_settings_exist(self):
        with patch.dict(os.environ, {}, clear=True):
            config = rtc_ai_agent_client_config("interview-1")
        self.assertFalse(config["enabled"])
        self.assertEqual(config["user_id"], "agent_interview-1")

    def test_task_ids_are_interview_scoped(self):
        task_id = generate_rtc_ai_agent_task_id("interview-1")
        self.assertTrue(task_belongs_to_interview(task_id, "interview-1"))
        self.assertFalse(task_belongs_to_interview(task_id, "interview-2"))
        self.assertLessEqual(len(task_id), 64)


def test_rtc_token_endpoint_is_authenticated_and_interview_scoped(tmp_path):
    project_dir = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "aliyun-rtc.sqlite"
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "test",
            "DB_ENGINE": "sqlite",
            "SQLITE_PATH": str(database_path),
            "RTC_APP_ID": "test_app",
            "RTC_APP_KEY": "test_secret",
            "RTC_TOKEN_TTL_SECONDS": "600",
            "RTC_AI_AGENT_TEMPLATE_ID": "template_1",
            "ALIBABA_CLOUD_ACCESS_KEY_ID": "test_access_key_id",
            "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "test_access_key_secret",
        }
    )
    script = textwrap.dedent(
        """
        from fastapi.testclient import TestClient
        import backend.src.main as main

        anonymous = TestClient(main.app)
        unauthorized = anonymous.post("/api/interviews/missing/rtc/token")
        assert unauthorized.status_code == 401, unauthorized.text

        owner = TestClient(main.app)
        registered = owner.post(
            "/api/auth/register",
            json={"email": "rtc-owner@example.com", "password": "Password123!", "name": "RTC Owner"},
        )
        assert registered.status_code == 201, registered.text
        user_id = registered.json()["user"]["id"]

        profile_updated = owner.put(
            "/api/profile",
            json={
                "nickname": "RTC Owner",
                "target_role": "RTC Engineer",
                "skills": ["Python", "WebRTC"],
                "resume_text": "负责阿里云 RTC 实时面试项目，完成会话状态和异常回收。",
                "project_experience": "RTC 智能面试项目",
            },
        )
        assert profile_updated.status_code == 200, profile_updated.text
        profile = main.find_profile_by_user_id(user_id)
        main.upsert_resume_analysis(
            user_id,
            main.resume_source_hash(profile),
            {
                "candidate_summary": "有 RTC 面试系统落地经验",
                "core_skills": ["Python", "WebRTC"],
                "projects": [
                    {
                        "name": "RTC 智能面试项目",
                        "role": "后端负责人",
                        "highlights": ["幂等启动", "异常回收"],
                    }
                ],
                "risk_points": ["需核实并发用户量"],
            },
            "test",
        )

        created = owner.post("/api/interviews", json={"target_role": "RTC Engineer"})
        assert created.status_code == 201, created.text
        interview_id = created.json()["interview"]["id"]

        issued = owner.post(f"/api/interviews/{interview_id}/rtc/token")
        assert issued.status_code == 200, issued.text
        credentials = issued.json()
        assert credentials["app_id"] == "test_app"
        assert credentials["channel_id"] == f"interview_{interview_id}"
        assert credentials["user_id"] == f"user_{user_id}"
        assert credentials["user_name"] == "RTC Owner"
        assert credentials["expires_in"] == 600
        assert credentials["token"].startswith("000")
        assert credentials["ai_agent"]["enabled"] is True
        assert credentials["ai_agent"]["user_id"] == f"agent_{interview_id}"

        agents = owner.get(f"/api/interviews/{interview_id}/agents").json()["agents"]
        question = owner.post(
            f"/api/interviews/{interview_id}/messages",
            json={
                "agent_id": agents[0]["id"],
                "sender_type": "agent",
                "message_type": "question",
                "content": "请介绍一个你负责的核心项目。",
            },
        )
        assert question.status_code == 201, question.text
        rtc_answer_payload = {
            "sender_type": "candidate",
            "message_type": "answer",
            "content": "我负责核心模块设计和落地。",
            "transcript_text": "我负责核心模块设计和落地。",
            "source": "aliyun_rtc",
            "source_ref": "turn_1",
        }
        first_answer = owner.post(f"/api/interviews/{interview_id}/messages", json=rtc_answer_payload)
        assert first_answer.status_code == 201, first_answer.text
        assert first_answer.json()["duplicate"] is False
        assert first_answer.json()["message"]["reply_to_message_id"] == question.json()["message"]["id"]
        assert first_answer.json()["message"]["round_agent_id"] == agents[0]["id"]
        duplicate_answer = owner.post(f"/api/interviews/{interview_id}/messages", json=rtc_answer_payload)
        assert duplicate_answer.status_code == 200, duplicate_answer.text
        assert duplicate_answer.json()["duplicate"] is True
        saved_messages = owner.get(f"/api/interviews/{interview_id}/messages").json()["messages"]
        assert len([item for item in saved_messages if item.get("source_ref") == "turn_1"]) == 1

        calls = {
            "started": None,
            "start_count": 0,
            "stopped": None,
            "stop_count": 0,
            "fail_stop_once": False,
            "notified": None,
        }
        def fake_start(**kwargs):
            calls["started"] = kwargs
            calls["start_count"] += 1
            return {
                "task_id": kwargs["task_id"],
                "agent_user_id": kwargs["agent_user_id"],
                "status": "starting",
                "request_id": "request_start",
            }
        def fake_stop(**kwargs):
            calls["stopped"] = kwargs
            calls["stop_count"] += 1
            if calls["fail_stop_once"]:
                calls["fail_stop_once"] = False
                raise RuntimeError("temporary provider outage")
            return {"task_id": kwargs["task_id"], "status": "stopped", "request_id": "request_stop"}
        def fake_notify(**kwargs):
            calls["notified"] = kwargs
            return {"task_id": kwargs["task_id"], "status": "notified", "request_id": "request_notify"}
        main.start_rtc_ai_agent = fake_start
        main.stop_rtc_ai_agent = fake_stop
        main.notify_rtc_ai_agent = fake_notify

        agent_started = owner.post(f"/api/interviews/{interview_id}/rtc/agent/start")
        assert agent_started.status_code == 200, agent_started.text
        agent_task_id = agent_started.json()["task_id"]
        assert calls["started"]["candidate_user_id"] == f"user_{user_id}"
        assert calls["started"]["channel_id"] == f"interview_{interview_id}"
        assert calls["started"]["greeting"] == "请介绍一个你负责的核心项目。"
        assert "候选人结构化简历分析" in calls["started"]["prompt"]
        assert "RTC 智能面试项目" in calls["started"]["prompt"]
        assert agent_started.json()["resume_analysis_injected"] is True
        assert agent_started.json()["current_question_id"] == question.json()["message"]["id"]
        duplicate_start = owner.post(f"/api/interviews/{interview_id}/rtc/agent/start")
        assert duplicate_start.status_code == 200, duplicate_start.text
        assert duplicate_start.json()["task_id"] == agent_task_id
        assert duplicate_start.json()["idempotent"] is True
        assert calls["start_count"] == 1

        heartbeat = owner.post(f"/api/interviews/{interview_id}/rtc/session/heartbeat")
        assert heartbeat.status_code == 200, heartbeat.text
        assert heartbeat.json()["rtc_session"]["state"] == "active"

        agent_notified = owner.post(
            f"/api/interviews/{interview_id}/rtc/agent/notify",
            json={"task_id": agent_task_id, "message_id": question.json()["message"]["id"]},
        )
        assert agent_notified.status_code == 200, agent_notified.text
        assert calls["notified"]["message"] == "请介绍一个你负责的核心项目。"

        agent_stopped = owner.post(
            f"/api/interviews/{interview_id}/rtc/agent/stop",
            json={"task_id": "task_for_another_interview"},
        )
        assert agent_stopped.status_code == 200, agent_stopped.text
        assert calls["stopped"]["task_id"] == agent_task_id
        assert calls["stop_count"] == 1
        duplicate_stop = owner.post(f"/api/interviews/{interview_id}/rtc/agent/stop", json={})
        assert duplicate_stop.status_code == 200, duplicate_stop.text
        assert duplicate_stop.json()["status"] == "stopped"
        assert calls["stop_count"] == 1

        restarted = owner.post(f"/api/interviews/{interview_id}/rtc/agent/start")
        assert restarted.status_code == 200, restarted.text
        assert restarted.json()["task_id"] != agent_task_id
        assert calls["start_count"] == 2
        assert calls["started"]["greeting"] == "请介绍一个你负责的核心项目。"
        main.db.execute(
            "UPDATE interview_rtc_sessions SET last_heartbeat_at = ?, updated_at = ? WHERE interview_id = ?",
            ("2000-01-01 00:00:00", "2000-01-01 00:00:00", interview_id),
        )
        main.db.commit()
        assert main.reconcile_rtc_sessions_once() >= 1
        recovered_session = owner.get(f"/api/interviews/{interview_id}/rtc/session").json()["rtc_session"]
        assert recovered_session["state"] == "stopped", recovered_session
        assert calls["stop_count"] == 2

        restarted_after_recovery = owner.post(f"/api/interviews/{interview_id}/rtc/agent/start")
        assert restarted_after_recovery.status_code == 200, restarted_after_recovery.text
        assert calls["start_count"] == 3

        other = TestClient(main.app)
        other_registered = other.post(
            "/api/auth/register",
            json={"email": "rtc-other@example.com", "password": "Password123!"},
        )
        assert other_registered.status_code == 201, other_registered.text
        forbidden = other.post(f"/api/interviews/{interview_id}/rtc/token")
        assert forbidden.status_code == 404, forbidden.text
        forbidden_agent = other.post(f"/api/interviews/{interview_id}/rtc/agent/start")
        assert forbidden_agent.status_code == 404, forbidden_agent.text

        calls["fail_stop_once"] = True
        finished = owner.post(f"/api/interviews/{interview_id}/finish")
        assert finished.status_code == 200, finished.text
        assert calls["stop_count"] == 3
        session_after_finish = owner.get(f"/api/interviews/{interview_id}/rtc/session")
        assert session_after_finish.status_code == 200, session_after_finish.text
        assert session_after_finish.json()["rtc_session"]["state"] == "stop_failed"
        retry_stop = owner.post(f"/api/interviews/{interview_id}/rtc/agent/stop", json={})
        assert retry_stop.status_code == 200, retry_stop.text
        assert retry_stop.json()["status"] == "stopped"
        assert calls["stop_count"] == 4
        after_finish = owner.post(f"/api/interviews/{interview_id}/rtc/token")
        assert after_finish.status_code == 409, after_finish.text
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_rtc_agent_start_is_idempotent_under_concurrency(tmp_path):
    project_dir = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "aliyun-rtc-concurrency.sqlite"
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "test",
            "DB_ENGINE": "sqlite",
            "SQLITE_PATH": str(database_path),
            "RTC_APP_ID": "test_app",
            "RTC_APP_KEY": "test_secret",
            "RTC_AI_AGENT_TEMPLATE_ID": "template_1",
            "ALIBABA_CLOUD_ACCESS_KEY_ID": "test_access_key_id",
            "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "test_access_key_secret",
        }
    )
    script = textwrap.dedent(
        """
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor
        from fastapi.testclient import TestClient
        import backend.src.main as main

        owner = TestClient(main.app)
        registered = owner.post(
            "/api/auth/register",
            json={"email": "rtc-race@example.com", "password": "Password123!", "name": "RTC Race"},
        )
        assert registered.status_code == 201, registered.text
        created = owner.post("/api/interviews", json={"target_role": "RTC Engineer"})
        interview_id = created.json()["interview"]["id"]
        assert owner.post(f"/api/interviews/{interview_id}/rtc/token").status_code == 200

        second = TestClient(main.app)
        second.cookies.update(owner.cookies)
        calls = {"count": 0}
        lock = threading.Lock()
        def fake_start(**kwargs):
            with lock:
                calls["count"] += 1
            time.sleep(0.25)
            return {
                "task_id": kwargs["task_id"],
                "agent_user_id": kwargs["agent_user_id"],
                "status": "starting",
                "request_id": "request_start",
            }
        main.start_rtc_ai_agent = fake_start

        url = f"/api/interviews/{interview_id}/rtc/agent/start"
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda client: client.post(url), (owner, second)))
        assert all(item.status_code == 200 for item in responses), [item.text for item in responses]
        task_ids = {item.json()["task_id"] for item in responses}
        assert len(task_ids) == 1, task_ids
        assert calls["count"] == 1, calls
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


if __name__ == "__main__":
    unittest.main()
