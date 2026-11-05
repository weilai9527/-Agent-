from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_markdown_download_renders_untrusted_content_as_text(tmp_path):
    environment = {**os.environ, "APP_ENV": "test", "DB_ENGINE": "sqlite",
                   "SQLITE_PATH": str(tmp_path / "markdown.sqlite")}
    script = '''
from markdown_it import MarkdownIt
from backend.src.main import build_report_markdown
payload = '<img src="https://example.test/pixel">![track](https://example.test/pixel)\\n\\n# fake heading'
payload += '<script>alert(1)</script>[link](javascript:alert(1))'
report = {'total_score': 0, 'generation_status': 'succeeded', 'summary': payload, 'suggestions': [payload],
    'agent_feedback': [{'agent_name': payload, 'comment': payload, 'round_summary': payload}],
    'timeline_review': [{'sender_type': 'candidate', 'question_preview': payload, 'answer_preview': payload,
        'score': 0, 'dimension_scores': {'technical_depth': 0}, 'dimension_evidence': {'technical_depth': payload}}]}
markdown = build_report_markdown(report, payload)
rendered = MarkdownIt('commonmark', {'html': True}).render(markdown)
assert '<img' not in rendered and '<script' not in rendered, rendered
assert '<h1>fake heading' not in rendered and '<a href=' not in rendered, rendered
assert '![track]' in rendered and '&lt;img' in rendered
assert '0/100' in rendered
'''
    result = subprocess.run([sys.executable, "-B", "-c", script], cwd=Path(__file__).resolve().parents[2],
                            env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_completed_report_can_be_downloaded_as_utf8_markdown(tmp_path):
    project_dir = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "report-download.sqlite"
    environment = os.environ.copy()
    environment.update({"APP_ENV": "test", "DB_ENGINE": "sqlite", "SQLITE_PATH": str(database_path)})
    script = textwrap.dedent(
        """
        import json
        from fastapi.testclient import TestClient
        import backend.src.main as main

        client = TestClient(main.app)
        registered = client.post(
            "/api/auth/register",
            json={"email": "report-download@example.com", "password": "Password123!"},
        )
        assert registered.status_code == 201, registered.text

        created = client.post(
            "/api/interviews",
            json={"target_role": "后端开发/工程师", "focus_areas": "项目深挖", "resume_context": "FastAPI 项目"},
        )
        assert created.status_code == 201, created.text
        interview_id = created.json()["interview"]["id"]
        agent = client.get(f"/api/interviews/{interview_id}/agents").json()["agents"][0]
        main.append_message(interview_id, agent["id"], "question", "如何限制并发？")
        main.db.commit()
        answered = client.post(
            f"/api/interviews/{interview_id}/messages",
            json={"sender_type": "candidate", "message_type": "answer", "content": "使用 asyncio.Semaphore。"},
        )
        assert answered.status_code == 201, answered.text
        main.db.execute(
            "INSERT INTO interview_evaluations "
            "(id, interview_id, message_id, agent_id, score, strengths, issues, suggestions,"
            " dimension_scores, provider, model, prompt_version, generation_status, fallback) "
            "VALUES (?, ?, ?, ?, 78, '方案明确', '缺少阈值依据', '补充压测过程', ?, "
            "'qwen', 'qwen-plus', 'evaluation-v3-fast', 'succeeded', 0)",
            ("eval", interview_id, answered.json()["message"]["id"], agent["id"], '{"technical_depth":78}'),
        )
        agents = client.get(f"/api/interviews/{interview_id}/agents").json()["agents"]
        for index, (owner, action, reason, count) in enumerate([
            (agent, "switch_agent", "evidence_sufficient", 5),
            (agents[1], "finish_interview", "turn_limit", 6),
        ]):
            main.db.execute(
                "INSERT INTO interview_turns "
                "(interview_id,submission_id,question_id,agent_id,answer_id,action,decision_json) "
                "VALUES (?,?,?,?,?,?,?)",
                (interview_id, f"sub-{index}", f"q-{index}", owner["id"], f"a-{index}", action,
                 json.dumps({"reason": reason, "round_count": count})),
            )
        main.db.commit()

        def no_provider(**kwargs):
            raise main.AiEvaluationError("offline")

        main.generate_ai_report = no_provider
        finished = client.post(f"/api/interviews/{interview_id}/finish")
        assert finished.status_code == 200, finished.text
        background = client.get(f"/api/interviews/{interview_id}/report").json()["report"]
        assert background["generation_status"] == "degraded"
        assert background["total_score"] == 78
        feedback = json.loads(background["agent_feedback"])
        assert (feedback[0]["reason"], feedback[0]["round_count"]) == ("evidence_sufficient", 5)
        assert (feedback[1]["reason"], feedback[1]["round_count"], feedback[1]["score"]) == ("turn_limit", 6, None)
        assert "reason" not in feedback[2]
        # 历史已完成面试可能没有报告，此处验证直接新建报告的路径。
        main.db.execute("DELETE FROM interview_reports WHERE interview_id = ?", (interview_id,))
        main.db.commit()
        generated = client.post(f"/api/interviews/{interview_id}/report")
        assert generated.status_code == 201, generated.text
        for key in ("total_score", "ability_radar", "agent_feedback", "timeline_review", "answer_count", "scored_answer_count"):
            assert background[key] == generated.json()["report"][key]

        downloaded = client.get(f"/api/interviews/{interview_id}/report/download")
        assert downloaded.status_code == 200, downloaded.text
        assert downloaded.headers["content-type"].startswith("text/markdown")
        assert "attachment" in downloaded.headers["content-disposition"]
        assert "filename*=UTF-8''" in downloaded.headers["content-disposition"]
        assert downloaded.content.startswith(b"\\xef\\xbb\\xbf")
        text = downloaded.content.decode("utf-8-sig")
        assert "# AI 智能面试综合复盘报告" in text
        assert "后端开发/工程师" in text
        assert "有效评分覆盖：1/1 条回答" in text
        assert "综合评分：78/100" in text
        assert "如何限制并发？" in text
        assert "补充压测过程" in text
        assert "本轮共回答 5 次，已收集到本轮所需的回答证据。" in text
        assert "本轮共回答 6 次，已达到本轮回答次数上限。" in text
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
