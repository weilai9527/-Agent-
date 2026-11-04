"""在新解释器进程中，通过真实路由验证独立测试数据库。"""
import os
from pathlib import Path
import subprocess
import sys
from textwrap import dedent


def test_progress_is_atomic_and_recovers_awaited_captions(tmp_path):
    script = dedent("""
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from fastapi.testclient import TestClient
        from backend.src import main

        client = TestClient(main.app)
        def post(url, data=None):
            result = client.post(url, json=data or {})
            assert result.is_success, result.text
            return result.json()

        post('/api/auth/register', {'email':'turns@example.com','password':'Password123!'})
        interview = post('/api/interviews', {'target_role':'后端工程师'})['interview']
        path = '/api/interviews/' + interview['id']
        first = post(path + '/current-question')['question']
        assert post(path + '/current-question')['question']['id'] == first['id']
        payload = {'question_id':first['id'], 'submission_id':'turn-1', 'content':'还不清楚'}
        def follow(**kwargs):
            assert not main.db.connect().in_transaction
            assert kwargs['turn_decision']['question'] and kwargs['turn_decision']['evidence']
            return {'question':'能举一个例子吗？'}
        main.generate_kimi_followup = follow
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _:post(path+'/turns', payload), range(2)))
        assert sorted(r['duplicate'] for r in results) == [False,True]
        assert len({r['answer']['id'] for r in results}) == 1
        assert len({r['question']['id'] for r in results}) == 1
        assert client.post(path+'/turns',json={**payload,'submission_id':'other-tab'}).status_code == 409
        assert client.post(path+'/turns',json={**payload,'content':'另一回答'}).status_code == 409
        legacy = {'sender_type':'candidate','message_type':'answer','content':'绕过提交'}
        assert client.post(path+'/messages',json=legacy).status_code == 409

        previous = results[0]['question']
        for n in range(2,17):
            sid = f'rtc-{n}'
            turn = post(path+'/turns',{'question_id':previous['id'], 'submission_id':sid,
                                      'content':'不知道', 'source':'aliyun_rtc'})
            assert turn['answer']['reply_to_message_id'] == previous['id']
            state = post(path+'/current-question')
            if n in (7,13):
                assert turn['action'] == 'switch_agent'
                previous = state['question']
                assert previous['agent_id'] == state['active_agent']['id'] != turn['answer']['round_agent_id']
                assert turn['decision']['reason'] == 'turn_limit'
            elif n == 16:
                assert state['action'] == 'finish_interview' and state['question'] is None
                assert turn['decision']['round_count'] == 3
            else:
                assert state['question'] is None and state['pending_spoken_submission_id'] == sid
                spoken = {'content':'遇到这个问题你怎么做？','transcript_text':'那么，遇到这个问题你怎么做？',
                          'source_ref':'agent-'+sid}
                endpoint = path+'/turns/'+sid+'/spoken-question'
                if n == 2:
                    previous = post(path+'/current-question',{'recover_spoken':True})['question']
                else:
                    previous = post(endpoint,spoken)['question']
                    assert previous['content'] == turn['decision']['question']
                assert post(endpoint,spoken)['question']['id'] == previous['id']
                assert client.post(path+'/turns/turn-1/spoken-question',json=spoken).status_code == 409
        assert main.one('SELECT count(*) AS n FROM interview_turns')['n'] == 16
        assert post(path + '/current-question', {'recover_spoken':True})['action'] == 'finish_interview'
        from unittest.mock import Mock
        main.generate_report_after_finish = Mock()
        with ThreadPoolExecutor(2) as pool:
            reports = list(pool.map(lambda _: post(path+'/finish')['report'], range(2)))
        assert len({r['id'] for r in reports}) == 1 and reports[0]['answer_count'] == 16
        assert main.generate_report_after_finish.call_count == 1
        assert post(path+'/turns', {'question_id':previous['id'], 'submission_id':sid,
                                    'content':'不知道', 'source':'aliyun_rtc'})['duplicate']
        assert post(path+'/current-question')['action'] == 'finish_interview'
    """)
    run_isolated(script, tmp_path)


def run_isolated(script, tmp_path):
    subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[2],
                   env={**os.environ, "APP_ENV":"test", "DB_ENGINE":"sqlite",
                        "SQLITE_PATH":str(tmp_path/"turns.sqlite")}, check=True, timeout=35)


def test_finish_wins_while_model_is_running(tmp_path):
    run_isolated(dedent("""
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from fastapi.testclient import TestClient
        from backend.src import main
        from unittest.mock import Mock

        client = TestClient(main.app)
        client.post('/api/auth/register', json={'email':'race@example.com','password':'Password123!'}).raise_for_status()
        session = client.post('/api/interviews', json={'target_role':'后端工程师'}).json()['interview']
        path = '/api/interviews/' + session['id']
        question = client.post(path+'/current-question').json()['question']
        started, release = Event(), Event()
        def slow(**_):
            started.set()
            assert release.wait(5)
            return {'question':'迟到的问题？'}
        main.generate_kimi_followup = slow
        main.generate_report_after_finish = Mock()
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(client.post, path+'/turns', json={
                'question_id':question['id'], 'submission_id':'race', 'content':'回答'})
            assert started.wait(5)
            try:
                finished = client.post(path+'/finish')
                finished.raise_for_status()
                assert finished.json()['report']['answer_count'] == 0
            finally:
                release.set()
            assert pending.result().status_code == 409
        assert main.one('SELECT COUNT(*) AS n FROM interview_turns')['n'] == 0
        assert client.post(path+'/current-question').json()['action'] == 'finish_interview'
    """), tmp_path)


def test_legacy_adoption_and_fallback(tmp_path):
    run_isolated(dedent("""
        from concurrent.futures import ThreadPoolExecutor
        from fastapi.testclient import TestClient
        from backend.src import main
        client = TestClient(main.app)
        def post(url, body=None):
            response = client.post(url, json=body or {})
            response.raise_for_status()
            return response.json()
        post('/api/auth/register', {'email':'legacy@example.com','password':'Password123!'})
        session = post('/api/interviews', {'target_role':'后端工程师'})['interview']
        path = '/api/interviews/' + session['id']
        agent = client.get(path+'/agents').json()['agents'][0]
        question_id = main.append_message(session['id'],agent['id'],'question','请谈谈你的项目。')
        main.db.commit()
        question = main.find_message_by_interview_id(question_id,session['id'])
        answer = post(path+'/messages', {'sender_type':'candidate', 'message_type':'answer',
            'content':'我负责设计缓存策略。'})['message']
        main.db.execute('UPDATE interview_messages SET round_agent_id=NULL,reply_to_message_id=NULL WHERE id=?',
                        (answer['id'],)).close()
        main.db.commit()
        with ThreadPoolExecutor(2) as pool:
            states = list(pool.map(lambda _: post(path+'/current-question'), range(2)))
        assert states[0]['question']['id'] == states[1]['question']['id'] != question['id']
        assert main.one('SELECT COUNT(*) AS n FROM interview_turns')['n'] == 1
        stored = main.find_message_by_interview_id(answer['id'], session['id'])
        assert stored['round_agent_id'] == agent['id'] and stored['reply_to_message_id'] == question['id']

        def unavailable(**kwargs):
            raise main.KimiFollowupError('offline')
        main.generate_kimi_followup = unavailable
        result = post(path+'/turns', {'question_id':states[0]['question']['id'],
                      'submission_id':'fallback', 'content':'暂时想不起来'})
        assert result['question']['content'] == result['decision']['question']
        assert result['decision']['round_count'] == 2
    """), tmp_path)


def test_concurrent_opening_and_distinct_submissions(tmp_path):
    run_isolated(dedent("""
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from fastapi.testclient import TestClient
        from backend.src import main
        client = TestClient(main.app)
        def post(url, body=None):
            response = client.post(url, json=body or {})
            response.raise_for_status()
            return response.json()
        post('/api/auth/register', {'email':'tabs@example.com','password':'Password123!'})
        session = post('/api/interviews', {'target_role':'后端工程师'})['interview']
        main.db.execute("UPDATE profiles SET resume_text='我负责缓存项目的延迟优化。'").close()
        main.db.commit()
        main.analyze_resume = lambda _: {'analysis':{}, 'provider':'local'}
        path = '/api/interviews/' + session['id']
        together = Barrier(2)
        def generate(**kwargs):
            assert not main.db.connect().in_transaction
            if 'turn_decision' not in kwargs:
                together.wait(5)
            return {'question':'请描述一次具体的优化。'}
        main.generate_opening_question = main.generate_kimi_followup = generate
        with ThreadPoolExecutor(2) as pool:
            questions = list(pool.map(lambda _: post(path+'/current-question')['question'], range(2)))
            assert questions[0]['id'] == questions[1]['id']
            def submit(i):
                return client.post(path+'/turns', json={'question_id':questions[i]['id'],
                                   'submission_id':f'tab-{i}','content':f'我是第{i}个标签页。'})
            results = list(pool.map(submit, range(2)))
        assert sorted(r.status_code for r in results) == [200,409]
        assert main.one('SELECT COUNT(*) AS n FROM interview_messages')['n'] == 3
    """), tmp_path)


def test_interrupted_legacy_role_switch_and_terminal_recovery(tmp_path):
    run_isolated(dedent("""
        from fastapi.testclient import TestClient
        from backend.src import main
        client = TestClient(main.app)
        def post(url, body=None):
            response = client.post(url, json=body or {})
            response.raise_for_status()
            return response.json()
        post('/api/auth/register', {'email':'handoff@example.com','password':'Password123!'})
        for terminal in (False, True):
            session = post('/api/interviews', {'target_role':'后端工程师'})['interview']
            path = '/api/interviews/' + session['id']
            agents = client.get(path+'/agents').json()['agents']
            old_id = main.append_message(session['id'],agents[0]['id'],'question','上轮的问题？')
            main.db.commit()
            old = main.find_message_by_interview_id(old_id,session['id'])
            if terminal:
                main.db.execute("UPDATE interview_agents SET status='completed' WHERE interview_id=?", (session['id'],))
            else:
                main.db.execute("UPDATE interview_agents SET status='completed' WHERE id=?", (agents[0]['id'],))
            main.db.commit()
            state = post(path+'/current-question')
            assert state == post(path+'/current-question')
            if terminal:
                assert state['question'] is None and state['action'] == 'finish_interview'
                assert client.post(path+'/messages',json={'sender_type':'candidate','message_type':'answer',
                                                         'content':'迟到了'}).status_code == 409
            else:
                assert state['question']['id'] != old['id']
                assert state['question']['agent_id'] == state['active_agent']['id'] == agents[1]['id']
    """), tmp_path)
