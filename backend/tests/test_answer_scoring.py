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
            if sender == 'agent':
                message_id = main.append_message(interview['id'], agent['id'], kind, content)
                main.db.commit()
                return main.find_message_by_interview_id(message_id, interview['id'])
            return post(path + '/messages', {'sender_type': sender, 'message_type': kind, 'content': content,
                                              'agent_id': agent['id'] if sender == 'agent' else None})['message']
        message('agent', 'question', '解释算法复杂度。')
        answer = message('candidate', 'answer', '我不会。')
        main.db.execute('UPDATE interview_messages SET reply_to_message_id=NULL WHERE id=?', (answer['id'],)).close()
        main.db.commit()
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


def test_managed_rtc_scores_only_the_recorded_question(tmp_path):
    script = dedent("""
        from fastapi.testclient import TestClient
        from backend.src import main

        client = TestClient(main.app)
        def post(path, body=None):
            response = client.post(path, json=body or {})
            assert response.is_success, response.text
            return response.json()

        post('/api/auth/register', {'email':'paired-rtc@example.com','password':'Password123!'})
        created = post('/api/interviews', {'target_role':'后端工程师'})
        interview, agents = created['interview'], created['agents']
        interview_id = interview['id']
        agent_id = agents[0]['id']
        path = '/api/interviews/' + interview_id
        main.append_message(interview_id, agent_id, 'question', '说说缓存设计？')
        main.db.commit()
        first = post(path + '/current-question')['question']
        newer = main.append_message(interview_id, agent_id, 'question', '历史记录里较晚的另一道题？')
        main.db.commit()
        turn = post(path + '/turns', {'question_id':first['id'], 'submission_id':'rtc-pair',
                                     'content':'使用缓存减少数据库查询。', 'source':'aliyun_rtc'})
        answer = turn['answer']
        assert answer['reply_to_message_id'] == first['id']
        calls = []
        def evaluate(**args):
            calls.append(args['question'])
            assert args['question'] == first['content']
            assert turn['question']['content'] not in [item['content'] for item in args['messages']]
            return {'score':72, 'strengths':'具体做法', 'issues':'', 'suggestions':'',
                    'dimension_scores':{'technical_depth':72},
                    'dimension_evidence':{'technical_depth':'使用缓存'},
                    'provider':'custom', 'model':'test-model',
                    'prompt_version':main.EVALUATION_PROMPT_VERSION, 'fallback':False}
        main.generate_ai_evaluation = evaluate
        url = path + '/evaluations'
        payload = {'message_id':answer['id']}
        assert post(url, payload)['evaluation']['score'] == 72
        other = post('/api/interviews', {'target_role':'另一场面试'})
        foreign_question = main.append_message(other['interview']['id'], other['agents'][0]['id'],
                                               'question', '别场面试的题目？')
        main.db.commit()
        # 已缓存的成功评分也必须先验证绑定。后一题虽为同角色的真实题，仍与提交轮次不符。
        for bad_id in (None, newer, turn['question']['id'], foreign_question):
            main.db.execute('UPDATE interview_messages SET reply_to_message_id=? WHERE id=?',
                            (bad_id, answer['id'])).close()
            main.db.commit()
            assert client.post(url, json=payload).status_code == 409
            assert client.post(url, json={**payload, 'force':True}).status_code == 409
        main.db.execute('UPDATE interview_messages SET reply_to_message_id=?, round_agent_id=? WHERE id=?',
                        (first['id'], agents[1]['id'], answer['id'])).close()
        main.db.commit()
        assert client.post(url, json=payload).status_code == 409
        assert len(calls) == 1

        report = main.build_scored_report(interview, agents, main.list_messages_by_interview_id(interview_id),
                    main.list_evaluations_by_interview_id(interview_id), [main.turn_by(interview_id, 'rtc-pair')])
        assert report['answer_count'] == 1 and report['scored_answer_count'] == 0
        assert report['timeline_review'][0]['question_id'] is None
        assert report['timeline_review'][0]['agent_id'] is None
        assert report['timeline_review'][0]['score'] is None
    """)
    subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[2],
                   env={**os.environ, 'APP_ENV':'test', 'DB_ENGINE':'sqlite',
                        'SQLITE_PATH':str(tmp_path / 'rtc-pair.sqlite')}, check=True, timeout=30)
