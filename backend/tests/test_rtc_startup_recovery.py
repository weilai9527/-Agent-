import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_rtc_startup_uses_cache_and_recovers_only_after_request_settles(tmp_path):
    environment = {
        **os.environ,
        "APP_ENV": "test",
        "DB_ENGINE": "sqlite",
        "SQLITE_PATH": str(tmp_path / "rtc-startup.sqlite"),
        "RTC_AI_AGENT_CONNECT_TIMEOUT_MS": "10000",
        "RTC_AI_AGENT_READ_TIMEOUT_MS": "60000",
        "RTC_SESSION_START_TIMEOUT_SECONDS": "45",
    }
    script = textwrap.dedent('''
        from datetime import datetime, timedelta, timezone
        from fastapi.testclient import TestClient
        import backend.src.main as main
        from backend.src import rtc_session_store as store

        client = TestClient(main.app)
        registered = client.post('/api/auth/register', json={
            'email': 'rtc-startup@example.com', 'password': 'Password123!',
        })
        assert registered.status_code == 201, registered.text
        user = registered.json()['user']
        saved = client.put('/api/profile', json={'nickname': 'RTC Tester', 'resume_text': 'Built a voice interview service.'})
        assert saved.status_code == 200, saved.text
        created = client.post('/api/interviews', json={'target_role': 'Engineer'})
        assert created.status_code == 201, created.text
        interview_id = created.json()['interview']['id']
        url = f'/api/interviews/{interview_id}/rtc/agent/start'

        def unexpected_analysis(*args, **kwargs):
            raise AssertionError('RTC startup must not generate a resume analysis')
        main.ensure_resume_analysis_for_user = unexpected_analysis
        assert main.resume_analysis_for_prompt(user, cached_only=True) is None
        profile = main.find_profile_by_user_id(user['id'])
        main.upsert_resume_analysis(user['id'], main.resume_source_hash(profile), {'summary': 'Saved summary'}, 'test')
        assert main.resume_analysis_for_prompt(user, cached_only=True)['summary'] == 'Saved summary'
        saved = client.put('/api/profile', json={'nickname': 'RTC Tester', 'resume_text': 'Updated resume content.'})
        assert saved.status_code == 200, saved.text
        assert main.resume_analysis_for_prompt(user, cached_only=True) is None

        remote_reads = []
        def missing(**kwargs):
            remote_reads.append(kwargs)
            raise RuntimeError('CLIENT_ERROR_TASK_NOT_FOUND: task does not exist')
        main.get_rtc_ai_agent = missing
        def stamp(seconds_ago):
            return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).strftime('%Y-%m-%d %H:%M:%S')

        def slow_start(**kwargs):
            main.db.execute('UPDATE interview_rtc_sessions SET updated_at = ? WHERE interview_id = ?', (stamp(50), interview_id))
            main.db.commit()
            main.reconcile_rtc_sessions_once()
            assert not remote_reads, 'recovery queried an in-flight StartAgent request'
            assert store.get_rtc_session(interview_id)['state'] == 'starting'
            return {'task_id': kwargs['task_id'], 'status': 'starting', 'request_id': 'ok'}
        main.start_rtc_ai_agent = slow_start
        main.stop_rtc_ai_agent = lambda **kwargs: {'request_id': 'stop'}
        result = client.post(url)
        assert result.status_code == 200, result.text
        assert result.json()['status'] == 'active'
        client.post(f'/api/interviews/{interview_id}/rtc/agent/stop')

        class Rejected(Exception):
            data = {'statusCode': 400}
        def rejected(**kwargs):
            raise Rejected('invalid template')
        main.start_rtc_ai_agent = rejected
        result = client.post(url)
        assert result.status_code == 502
        assert store.get_rtc_session(interview_id)['state'] == 'start_failed'
        assert '待确认' not in result.text

        def timeout(**kwargs):
            raise TimeoutError('original transport timeout')
        main.start_rtc_ai_agent = timeout
        result = client.post(url)
        assert result.status_code == 502
        assert store.get_rtc_session(interview_id)['state'] == 'starting'
        session = store.get_rtc_session(interview_id)
        # next_retry_at is UTC even when the application uses MySQL local time.
        original_engine = main.DB_ENGINE
        main.DB_ENGINE = 'mysql'
        assert not main.rtc_start_ready_for_recovery({**session, 'next_retry_at': stamp(-60)})
        assert main.rtc_start_ready_for_recovery({**session, 'next_retry_at': stamp(60)})
        main.DB_ENGINE = original_engine
        main.db.execute('UPDATE interview_rtc_sessions SET next_retry_at = ? WHERE interview_id = ?', (stamp(1), interview_id))
        main.db.commit()
        main.reconcile_rtc_sessions_once()
        failed = store.get_rtc_session(interview_id)
        assert failed['state'] == 'start_failed'
        assert 'original transport timeout' in failed['last_error']
        assert 'remote task missing' in failed['last_error']

        # A dead worker is also recoverable once the full request budget expires.
        session, claimed = store.claim_rtc_start(failed['id'], 'replacement_task')
        assert claimed
        main.db.execute('UPDATE interview_rtc_sessions SET updated_at = ? WHERE interview_id = ?', (stamp(100), interview_id))
        main.db.commit()
        main.reconcile_rtc_sessions_once()
        assert store.get_rtc_session(interview_id)['state'] == 'start_failed'
    ''')
    result = subprocess.run(
        [sys.executable, '-c', script],
        cwd=Path(__file__).resolve().parents[2], env=environment,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
