"""通过真实接口验证回答评分、补评、报告生成及历史记录。"""

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch


def test_evidence_scoring_flow(tmp_path):
    # 应用在导入时绑定数据库；使用新进程还可以
    # 将接口工作线程与其余测试隔离。
    environment = {
        **os.environ, "APP_ENV": "test", "DB_ENGINE": "sqlite",
        "SQLITE_PATH": str(tmp_path / "scoring.sqlite"),
    }
    result = subprocess.run(
        [sys.executable, "-m", "backend.tests.test_evidence_scoring_flow"],
        cwd=Path(__file__).resolve().parents[2], env=environment,
        capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def run_flow():
    from fastapi.testclient import TestClient
    from backend.src import ai_evaluation, main

    client = TestClient(main.app)

    def request(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        assert response.is_success, (path, response.status_code, response.text)
        return response.json()

    def post(path, **payload):
        return request("POST", path, json=payload)

    post("/api/auth/register", email="scoring@example.com", password="Password123!")
    interview = post("/api/interviews", target_role="后端工程师")
    path = "/api/interviews/" + interview["interview"]["id"]
    agent_id = interview["agents"][0]["id"]

    def add_answer(question, answer):
        main.append_message(interview["interview"]["id"], agent_id, "question", question)
        main.db.commit()
        return post(path + "/messages", sender_type="candidate",
                    message_type="answer", content=answer)["message"]["id"]

    def evaluate(message_id):
        return post(path + "/evaluations", message_id=message_id)["evaluation"]

    first_text = "用唯一约束避免重复写入。"
    second_text = "按请求键缓存结果，重试时复用已有结果。"
    first_id = add_answer("如何避免重复写入？", first_text)
    second_id = add_answer("如何处理重复请求？", second_text)

    def providers(setting, **kwargs):
        return [SimpleNamespace(name="custom", model=setting)]

    model_answer = None
    scoring_prompts = []

    def model(provider, messages):
        if provider.model == "REPORT_PROVIDER_ORDER":
            # 故意让文字总结中的评分说法不可信，以验证程序汇总结果仍为准。
            return {"summary": "两次作答讨论了重复请求。", "suggestions": ["补充失败场景。"],
                    "total_score": 99, "grade": "A", "pass_recommendation": "strong_pass",
                    "ability_radar": {"role_fit": 99}}
        scoring_prompts.append(messages[-1]["content"])
        if model_answer is None:
            raise ValueError("offline test: scoring provider unavailable")
        return model_answer

    def scored_answer(quote, score):
        return {
            "question_types": ["technical"], "score": 99,
            "dimension_scores": {"technical_accuracy": score},
            "dimension_evidence": {"technical_accuracy": quote},
            "strengths": ["给出了具体做法。"], "issues": [], "suggestions": [],
        }

    def decoded(value):
        return json.loads(value) if isinstance(value, str) else value

    with patch.object(ai_evaluation, "get_task_providers", providers), \
            patch.object(ai_evaluation, "call_provider_json", model):
        pending = evaluate(first_id)
        assert pending["generation_status"] == "pending_retry", pending
        assert pending["score"] is None
        assert first_text in scoring_prompts[-1]
        assert second_text not in scoring_prompts[-1]
        model_answer = scored_answer(second_text, 80)
        scored = evaluate(second_id)
        assert scored["generation_status"] == "succeeded", scored
        assert scored["score"] == 80
        assert decoded(scored["dimension_evidence"])["technical_accuracy"] == second_text

        post(path + "/finish")
        partial = request("GET", path + "/report")["report"]
        assert (partial["scored_answer_count"], partial["answer_count"]) == (1, 2), partial
        assert partial["total_score"] == 80
        partial_scores = {row["message_id"]: row["score"] for row in decoded(partial["timeline_review"])}
        assert partial_scores == {first_id: None, second_id: 80}
        assert request("GET", "/api/stats/me")["stats"]["average_total_score"] == 0

        model_answer = scored_answer(first_text, 40)
        repaired = evaluate(first_id)
        assert repaired["id"] == pending["id"]
        assert repaired["score"] == 40
        assert repaired["generation_status"] == "succeeded"
        assert len(request("GET", path + "/evaluations")["evaluations"]) == 2
        final = post(path + "/report")["report"]
        assert final["id"] == partial["id"]
        assert (final["scored_answer_count"], final["answer_count"]) == (2, 2)
        assert decoded(final["ability_radar"]) == {"technical_accuracy": 60}
        assert (final["total_score"], final["grade"], final["pass_recommendation"]) == (
            60, "D", "borderline",
        )

    # 迁移前仅靠规则生成的旧报告虽有分数，但没有经过验证的评分覆盖信息。
    legacy = post("/api/interviews", target_role="后端工程师")["interview"]
    legacy_path = "/api/interviews/" + legacy["id"]
    post(legacy_path + "/messages", sender_type="candidate", message_type="answer", content="不知道")
    main.db.execute(
        """INSERT INTO interview_reports
           (id, user_id, interview_id, total_score, grade, pass_recommendation,
            ability_radar, agent_feedback, timeline_review, summary, suggestions,
            provider, model, generation_status, fallback)
           VALUES ('legacy-report', ?, ?, 94, 'A', 'strong_pass',
                   '{"technical_accuracy":94}', '[]', '[]', '', '',
                   'local', 'rules-v1', 'degraded', 1)""",
        (legacy["user_id"], legacy["id"]),
    )
    main.db.commit()
    stats = request("GET", "/api/stats/me")["stats"]
    assert stats["average_total_score"] == 60
    dimensions = request("GET", "/api/stats/me/dimensions")["dimensions"]
    accuracy = next(row for row in dimensions if row["key"] == "technical_accuracy")
    assert accuracy["evidence_count"] == 1
    assert accuracy["average_score"] == 60


if __name__ == "__main__":
    run_flow()
