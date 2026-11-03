import os
from pathlib import Path
import subprocess
import sys
from textwrap import dedent

import pytest

from backend.src.ai_evaluation import AiEvaluationError, normalize_evaluation


def test_score_uses_only_tested_dimensions_with_answer_quotes():
    result = normalize_evaluation({
        "score": 99, "question_types": ["technical"],
        "dimension_scores": {"technical_accuracy": 0, "expression_clarity": 50, "role_fit": 85},
        "dimension_evidence": {"technical_accuracy": "我不会", "expression_clarity": "我不会"},
    }, answer="这个算法我不会。")
    assert result["score"] == 25
    assert result["dimension_scores"] == {"technical_accuracy": 0, "expression_clarity": 50}
    assert set(result["dimension_evidence"]) == set(result["dimension_scores"])


@pytest.mark.parametrize(("score", "quote"), [(None, ""), (70, "编造的回答"), (True, "原话"), (110, "原话")])
def test_invalid_or_unassessable_response_requires_retry(score, quote):
    with pytest.raises(AiEvaluationError):
        normalize_evaluation({
            "question_types": ["technical"],
            "dimension_scores": {"technical_depth": score},
            "dimension_evidence": {"technical_depth": quote},
        }, answer="原话")


def test_retry_reuses_record_and_freezes_conversation(tmp_path):
    script = dedent("""
        from fastapi.testclient import TestClient
        from backend.src import main, ai_evaluation as ai
        from types import SimpleNamespace

        client = TestClient(main.app)
        def post(path, body):
            response = client.post(path, json=body)
            assert response.is_success, response.text
            return response.json()

        post('/api/auth/register', {'email': 'scoring@example.com', 'password': 'Password123!'})
        interview = post('/api/interviews', {'target_role': '工程师', 'focus_areas': '算法'})['interview']
        path = '/api/interviews/' + interview['id']
        agent = client.get(path + '/agents').json()['agents'][0]
        def message(sender, kind, content):
            return post(path + '/messages', {'sender_type': sender, 'message_type': kind, 'content': content,
                                              'agent_id': agent['id'] if sender == 'agent' else None})['message']
        message('agent', 'question', '解释算法复杂度。')
        answer = message('candidate', 'answer', '我不会。')
        message('agent', 'follow_up', '后续问题不应出现')
        message('candidate', 'answer', '后续答案不应出现')
        def evaluate():
            return post(path + '/evaluations', {'message_id': answer['id']})['evaluation']

        ai.get_task_providers = lambda *a, **kw: []
        first = evaluate()
        assert first['generation_status'] == 'pending_retry' and first['fallback'] == 1
        assert first['score'] is None
        stored = main.one('SELECT score FROM interview_evaluations WHERE id = ?', (first['id'],))
        assert stored['score'] == 0
        calls = []
        def provider(*args, **kwargs):
            prompt = args[1][1]['content']
            assert '后续' not in prompt and '解释算法复杂度' in prompt
            calls.append(prompt)
            return ({'question_types': ['technical'], 'dimension_scores': {'technical_depth': 0},
                     'dimension_evidence': {'technical_depth': '我不会'}},
                    SimpleNamespace(name='qwen', model='test'), False, None)
        ai._call_with_fallback = provider
        second = evaluate()
        assert second['id'] == first['id']
        assert second['score'] == 0 and second['generation_status'] == 'succeeded'
        assert evaluate()['id'] == first['id'] and len(calls) == 1
        def unavailable(*args, **kwargs):
            raise ai.AiEvaluationError('临时不可用')
        ai._call_with_fallback = unavailable
        preserved = post(path + '/evaluations', {'message_id': answer['id'], 'force': True})['evaluation']
        assert preserved['generation_status'] == 'succeeded' and preserved['score'] == 0
        assert len(client.get(path + '/evaluations').json()['evaluations']) == 1
    """)
    subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[2],
                   env={**os.environ, "APP_ENV": "test", "DB_ENGINE": "sqlite",
                        "SQLITE_PATH": str(tmp_path / "answer-scoring.sqlite")}, check=True)
