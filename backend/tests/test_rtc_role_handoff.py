import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_new_rtc_task_uses_current_role_question_and_bounded_opening_context(tmp_path):
    environment = {
        **os.environ,
        "APP_ENV": "test",
        "DB_ENGINE": "sqlite",
        "SQLITE_PATH": str(tmp_path / "rtc-handoff.sqlite"),
    }
    script = textwrap.dedent('''
        from fastapi.testclient import TestClient
        import backend.src.main as main

        client = TestClient(main.app)
        registered = client.post('/api/auth/register', json={
            'email': 'rtc-handoff@example.com', 'password': 'Password123!',
        })
        assert registered.status_code == 201, registered.text
        created = client.post('/api/interviews', json={'target_role': '后端工程师'})
        assert created.status_code == 201, created.text
        interview = created.json()['interview']
        prefix = f"/api/interviews/{interview['id']}"
        agents = client.get(prefix + '/agents').json()['agents']
        calls = []
        def start(**kwargs):
            calls.append(kwargs)
            return {'task_id': kwargs['task_id'], 'request_id': 'start'}
        main.start_rtc_ai_agent = start
        stops = []
        def stop(**kwargs):
            stops.append(kwargs['task_id'])
            return {'request_id': 'stop'}
        main.stop_rtc_ai_agent = stop
        main.resume_analysis_for_prompt = lambda *args, **kwargs: None

        def ask(agent, question):
            main.append_message(interview['id'], agent['id'], 'question', question)
            main.db.commit()

        ask(agents[0], '请描述你亲自实现的接口。')
        first = client.post(prefix + '/rtc/agent/start')
        assert first.status_code == 200, first.text
        assert '当前面试官：' + agents[0]['agent_name'] in calls[0]['prompt']
        assert calls[0]['greeting'] == '请描述你亲自实现的接口。'

        for index, question in [(1, '如何设计扩容与回滚？'), (2, '为什么选择这个岗位？')]:
            old_task = calls[-1]['task_id']
            if index == 1:
                stopped = client.post(prefix + '/rtc/agent/stop')
                assert stopped.json()['status'] == 'stopped', stopped.text
            # 人事轮交接时，页面刷新可能在旧浏览器发出
            # 停止请求之前打断流程；启动新角色时必须先结束旧任务。
            for agent, status in [(agents[index - 1], 'completed'), (agents[index], 'active')]:
                result = client.patch(prefix + f"/agents/{agent['id']}", json={'status': status})
                assert result.status_code == 200, result.text
            ask(agents[index], question)
            result = client.post(prefix + '/rtc/agent/start')
            assert result.status_code == 200, result.text
            assert result.json()['idempotent'] is False
            assert calls[-1]['task_id'] != calls[-2]['task_id']
            assert stops.count(old_task) == 1
            late_stop = client.post(prefix + '/rtc/agent/stop', json={'expected_task_id': old_task})
            assert late_stop.json()['rtc_session']['task_id'] == calls[-1]['task_id']
            assert calls[-1]['task_id'] not in stops
            assert calls[-1]['greeting'] == question
            assert '当前问题：' + question in calls[-1]['prompt']
            assert '当前面试官：' + agents[index]['agent_name'] in calls[-1]['prompt']
        assert '不再继续上一轮技术或架构追问' in calls[-1]['prompt']
        prompt = main.build_rtc_ai_agent_prompt(
            {**interview, 'resume_context': '长简历' * 10000},
            [{**agents[-1], 'status': 'active'}],
            [{'sender_type': 'agent', 'message_type': 'question', 'content': '本轮职业动机问题'}],
            None,
        )
        assert len(prompt) <= 5000
        assert '本轮职业动机问题' in prompt
        assert '不是替候选人解题的助手' in prompt
        assert 'Greeting' in prompt
        assert '历史回答不能当作刚收到的新回答' in prompt
    ''')
    result = subprocess.run(
        [sys.executable, '-c', script],
        cwd=Path(__file__).resolve().parents[2], env=environment,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def test_restarting_rtc_plays_next_canonical_question_for_same_role(tmp_path):
    environment = {
        **os.environ, "APP_ENV": "test", "DB_ENGINE": "sqlite",
        "SQLITE_PATH": str(tmp_path / "rtc-notify.sqlite"),
    }
    script = textwrap.dedent('''
        from fastapi.testclient import TestClient
        from backend.src import main

        client = TestClient(main.app)
        def post(url, payload=None):
            response = client.post(url, json=payload or {})
            assert response.is_success, response.text
            return response.json()

        post('/api/auth/register', {'email':'rtc-notify@example.com', 'password':'Password123!'})
        created = post('/api/interviews', {'target_role':'后端工程师'})
        interview_id = created['interview']['id']
        agent_id = created['agents'][0]['id']
        path = '/api/interviews/' + interview_id
        main.append_message(interview_id, agent_id, 'question', '首个服务端问题？')
        main.db.commit()
        first = post(path + '/current-question')['question']
        started, stopped = [], []
        def start(**options):
            started.append(options)
            return {'task_id': options['task_id'], 'request_id': 'start'}
        def stop(**options):
            stopped.append(options['task_id'])
            return {'request_id': 'stop'}
        main.start_rtc_ai_agent = start
        main.stop_rtc_ai_agent = stop
        main.resume_analysis_for_prompt = lambda *args, **kwargs: None
        task = post(path + '/rtc/agent/start')['task_id']
        assert started[0]['greeting'] == first['content']
        assert '禁止自行生成问题' in started[0]['prompt']

        turn = post(path + '/turns', {'question_id':first['id'], 'submission_id':'rtc-turn',
                                     'content':'还不清楚', 'source':'aliyun_rtc'})
        assert turn['action'] == 'ask_follow_up'
        current = turn['question']
        assert current['agent_id'] == agent_id
        assert post(path + '/rtc/agent/start')['task_id'] == task
        assert len(started) == 1

        assert post(path + '/rtc/agent/stop', {'expected_task_id':task})['status'] == 'stopped'
        next_start = post(path + '/rtc/agent/start')
        assert next_start['task_id'] != task
        assert stopped == [task]
        assert [call['greeting'] for call in started] == [first['content'], current['content']]
        assert next_start['current_question_id'] == current['id']
        assert started[0]['channel_id'] == started[1]['channel_id']
    ''')
    result = subprocess.run(
        [sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[2],
        env=environment, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
