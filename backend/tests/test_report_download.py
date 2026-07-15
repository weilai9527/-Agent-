from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_completed_report_can_be_downloaded_as_utf8_markdown(tmp_path):
    project_dir = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "report-download.sqlite"
    environment = os.environ.copy()
    environment.update({"APP_ENV": "test", "DB_ENGINE": "sqlite", "SQLITE_PATH": str(database_path)})
    script = textwrap.dedent(
        """
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
        finished = client.post(f"/api/interviews/{interview_id}/finish")
        assert finished.status_code == 200, finished.text

        main.generate_ai_report = lambda **_: {
            "total_score": 78,
            "grade": "B",
            "pass_recommendation": "pass",
            "ability_radar": {name: 70 for name in main.DIMENSIONS},
            "agent_feedback": [{"agent_name": "技术一面 Agent", "score": 78, "comment": "回答结构清晰。"}],
            "timeline_review": [{
                "sender_type": "candidate",
                "agent_name": "技术一面 Agent",
                "question_preview": "如何限制并发？",
                "answer_preview": "使用 asyncio.Semaphore。",
                "score": 85,
                "strengths": "方案明确",
                "issues": "缺少阈值依据",
                "suggestions": "补充压测过程",
            }],
            "summary": "能够清晰说明异步任务方案。",
            "suggestions": "补充并发阈值依据\\n增加性能压测数据",
            "provider": "qwen",
            "model": "qwen-plus",
            "prompt_version": "report-v3",
            "fallback": False,
            "generation_error": None,
        }
        generated = client.post(f"/api/interviews/{interview_id}/report")
        assert generated.status_code == 201, generated.text

        downloaded = client.get(f"/api/interviews/{interview_id}/report/download")
        assert downloaded.status_code == 200, downloaded.text
        assert downloaded.headers["content-type"].startswith("text/markdown")
        assert "attachment" in downloaded.headers["content-disposition"]
        assert "filename*=UTF-8''" in downloaded.headers["content-disposition"]
        assert downloaded.content.startswith(b"\\xef\\xbb\\xbf")
        text = downloaded.content.decode("utf-8-sig")
        assert "# AI 智能面试综合复盘报告" in text
        assert "后端开发/工程师" in text
        assert "综合评分：78/100" in text
        assert "如何限制并发？" in text
        assert "补充压测过程" in text
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
