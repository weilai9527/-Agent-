import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_policy_round_trip_permissions_and_all_prompt_paths(tmp_path):
    environment = os.environ.copy()
    environment.update({"APP_ENV": "test", "DB_ENGINE": "sqlite", "SQLITE_PATH": str(tmp_path / "policy.sqlite"), "ADMIN_COOKIE_SECURE": "false", "PYTHONIOENCODING": "utf-8"})
    script = textwrap.dedent('''
        from copy import deepcopy
        from fastapi.testclient import TestClient
        from unittest.mock import patch
        import backend.src.main as main
        import admin_backend.src.main as admin
        from backend.src.kimi_followup import _build_messages, generate_opening_question, FollowupProvider
        from shared.interviewer_policy import ensure_interviewer_policy_schema, load_snapshot

        # Schema initialization is repeatable for shared candidate/admin startup.
        ensure_interviewer_policy_schema(main.db, "sqlite")
        root = TestClient(admin.app)
        actor = {"id": "root", "email": admin.MASTER_ADMIN_EMAIL, "role": "super_admin"}
        admin.app.dependency_overrides[admin.require_admin] = lambda: actor
        origin = {"Origin": "http://127.0.0.1:5174"}
        policy = root.get("/api/admin/interviewer-policy").json()["policy"]
        policy["roles"]["technical"]["focus"] = "技术轮测试侧重点"
        policy["roles"]["hr"]["focus"] = "HR轮测试侧重点"
        policy["allowed"]["style"] = ["友好引导", "专业严谨"]
        policy["defaults"]["style"] = "专业严谨"
        assert root.put("/api/admin/interviewer-policy", headers=origin, json=policy).status_code == 200
        invalid = deepcopy(policy); invalid["allowed"]["depth"] = []
        assert root.put("/api/admin/interviewer-policy", headers=origin, json=invalid).status_code == 400
        invalid = deepcopy(policy); invalid["defaults"]["style"] = "压力面试"
        assert root.put("/api/admin/interviewer-policy", headers=origin, json=invalid).status_code == 400
        invalid = deepcopy(policy); invalid["roles"]["hr"]["strategy"] = "x" * 241
        assert root.put("/api/admin/interviewer-policy", headers=origin, json=invalid).status_code == 400
        assert root.get("/api/admin/interviewer-policy").json()["policy"] == policy
        actor["email"] = "limited@example.test"
        actor["permissions"] = ["manageModelConfig"]
        assert root.get("/api/admin/interviewer-policy").status_code == 403
        assert root.put("/api/admin/interviewer-policy", headers=origin, json=policy).status_code == 403
        actor["email"] = admin.MASTER_ADMIN_EMAIL

        student = TestClient(main.app)
        assert student.get("/api/interviewer-policy").status_code == 401
        registered = student.post("/api/auth/register", json={"email": "strategy@example.test", "password": "Password123!"})
        assert registered.status_code == 201, registered.text
        assert student.get("/api/interviewer-policy").json()["policy"] == policy
        selection = {"style": "友好引导", "focus": "沟通表达", "depth": "连续深挖"}
        created = student.post("/api/interviews", json={"target_role": "测试岗位", "interviewer_strategy": selection})
        assert created.status_code == 201, created.text
        interview = created.json()["interview"]
        interview_id = interview["id"]
        agents = created.json()["agents"]
        assert interview["interviewer_strategy"]["selection"] == selection
        assert interview["focus_areas"] == "沟通表达"
        assert agents[0]["agent_role"] == "技术轮测试侧重点"
        assert load_snapshot(main.db, interview_id) == interview["interviewer_strategy"]
        assert student.patch(f"/api/interviews/{interview_id}", json={"interviewer_style": "专业严谨"}).status_code == 409
        malicious = {**selection, "style": "压力面试"}
        assert student.post("/api/interviews", json={"target_role": "Test", "interviewer_strategy": malicious}).status_code == 400
        assert student.post("/api/interviews", json={"target_role": "Test", "interviewer_strategy": {**selection, "roles": {}}}).status_code == 400

        # A later policy change cannot rewrite a created session or its reconnection.
        policy["defaults"]["style"] = "友好引导"
        policy["roles"]["technical"]["focus"] = "管理员后续修改"
        assert root.put("/api/admin/interviewer-policy", headers=origin, json=policy).status_code == 200
        reloaded = student.get(f"/api/interviews/{interview_id}").json()["interview"]
        assert reloaded["interviewer_strategy"] == interview["interviewer_strategy"]
        legacy = {key: value for key, value in reloaded.items() if key != "interviewer_strategy"}
        assert "背景职责 -> 方案取舍" in main.build_realtime_session_config(legacy, agents, [], None)["instructions"]
        assert "追问优先覆盖：候选人职责" in main.build_rtc_ai_agent_prompt(legacy, agents, [], None)
        assert "本场固定面试官策略" not in main.build_rtc_ai_agent_prompt(legacy, agents, [], None)
        for active in agents:
            round_agents = [{**agent, "status": "active" if agent["id"] == active["id"] else "pending"} for agent in agents]
            session = main.build_realtime_session_config(reloaded, round_agents, [], None)
            openai = main.build_openai_realtime_session_config(reloaded, round_agents, [], None)
            qwen = main.build_qwen_realtime_session_update(session)["session"]
            rtc = main.build_rtc_ai_agent_prompt(reloaded, round_agents, [], None)
            text = _build_messages(interview=reloaded, active_agent=active, messages=[], last_answer="测试回答")[0]["content"]
            expected_focus = interview["interviewer_strategy"]["roles"][active["agent_type"]]["focus"]
            for prompt in (session["instructions"], openai["instructions"], qwen["instructions"], rtc, text):
                assert all(value in prompt for value in selection.values())
                assert expected_focus in prompt
                assert "管理员后续修改" not in prompt
                assert "不改变评分标准" in prompt
            assert len(rtc) <= 5000

        provider = FollowupProvider("test", "fake", "https://example.test", "fake", 5, 0.5, 100)
        with patch("backend.src.kimi_followup._provider_order", return_value=[provider]), patch("backend.src.kimi_followup._call_provider_content", return_value="请介绍你的项目。") as call:
            generate_opening_question(interview=reloaded, active_agent=agents[0], resume_analysis=None, selected_resume_point={"value": "项目"})
            messages = call.call_args.args[1]
            assert "连续深挖" in messages[0]["content"]

        policy["studentCanChoose"] = False
        assert root.put("/api/admin/interviewer-policy", headers=origin, json=policy).status_code == 200
        assert student.post("/api/interviews", json={"target_role": "Test", "interviewer_strategy": selection}).status_code == 400
        locked = student.post("/api/interviews", json={"target_role": "Test", "interviewer_style": "压力面试"})
        assert locked.status_code == 201
        assert locked.json()["interview"]["interviewer_strategy"]["selection"] == policy["defaults"]
        assert student.get(f"/api/interviews/{interview_id}").json()["interview"]["interviewer_strategy"] == interview["interviewer_strategy"]
        print("PASS: policy administration, client selection, immutable snapshots, role rotation and all prompt paths")
    ''')
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[2], env=environment, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
