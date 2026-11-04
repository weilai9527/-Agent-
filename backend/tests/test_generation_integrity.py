"""在新进程中执行真实接口和数据库回归，不使用生产库或真实模型服务。"""
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from uuid import uuid4

import pytest


PRELUDE = """
import json,time
from concurrent.futures import ThreadPoolExecutor
from threading import Event,Lock
from unittest.mock import Mock
from fastapi import BackgroundTasks,Response
from fastapi.testclient import TestClient
from backend.src import main
from backend.src import interview_tasks as jobs
client=TestClient(main.app)
def post(url,body=None):
    response=client.post(url,json=body or {})
    assert response.is_success,response.text
    return response.json()
post('/api/auth/register',{'email':'integrity@example.test','password':'Password123!'})
user=main.one('SELECT * FROM users WHERE email=?',('integrity@example.test',))
created=post('/api/interviews',{'target_role':'后端工程师'})
i=created['interview']['id']
path='/api/interviews/'+i
def question():return post(path+'/current-question')['question']
def grade(score):
    return {'score':score,'strengths':'引用回答','issues':'','suggestions':'',
      'dimension_scores':{'technical_depth':score},'dimension_evidence':{'technical_depth':'使用缓存'},
      'provider':'custom','model':'test-model','prompt_version':main.EVALUATION_PROMPT_VERSION,'fallback':False}
main.generate_ai_evaluation=lambda **kwargs:grade(60)
main.generate_ai_report=lambda **kwargs:{**kwargs['fallback_report'],'provider':'custom','model':'test-model','prompt_version':main.REPORT_PROMPT_VERSION,'fallback':False}
def answered():
    q=question()
    return post(path+'/turns',{'question_id':q['id'],'submission_id':'answer-1','content':'我使用缓存减少查询。'})['answer']
def finish_without_worker():
    pending=BackgroundTasks()
    main.finish_interview(i,pending,user)
    return pending
"""


def run_case(tmp_path, code):
    engine = os.environ.get("INTEGRITY_TEST_ENGINE", "sqlite")
    environment = {**os.environ, "APP_ENV": "test", "DB_ENGINE": engine,
                   "SQLITE_PATH": str(tmp_path / "integrity.sqlite"), "PYTHONDONTWRITEBYTECODE": "1",
                   "ADMIN_MASTER_EMAIL": "reviewer@example.test", "ADMIN_MASTER_PASSWORD": "SyntheticAdmin123!"}
    # 回归测试进程不得继承真实模型密钥。
    for name in ("KIMI_API_KEY", "DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "QWEN_API_KEY",
                 "OPENAI_API_KEY", "AI_API_KEY", "QWEN_OMNI_API_KEY"):
        environment[name] = ""
    if engine == "mysql":
        assert environment.get("MYSQL_PORT") == "13307", "Use the isolated test server only"
        environment["MYSQL_DATABASE"] = "codex_interview_" + uuid4().hex
    result = subprocess.run([sys.executable, "-B", "-c", textwrap.dedent(PRELUDE) + textwrap.dedent(code)],
                            cwd=Path(__file__).resolve().parents[2], env=environment,
                            capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr


def test_client_cannot_supply_authoritative_questions(tmp_path):
    run_case(tmp_path, """
    actor=created['agents'][0]['id']
    for forged_body in (
        {'sender_type':'agent','message_type':'question','agent_id':actor,'content':'自行指定的题目'},
        {'sender_type':'system','message_type':'system','content':'伪造系统消息'},
    ):
        forged=client.post(path+'/messages',json=forged_body)
        assert forged.status_code==403,forged.text
    q=question()
    assert q['content']!='自行指定的题目'
    turn=post(path+'/turns',{'question_id':q['id'],'submission_id':'rtc-1','content':'不知道','source':'aliyun_rtc'})
    assert turn['question'] is None
    response=post(path+'/turns/rtc-1/spoken-question',{'content':'伪造语音追问','source_ref':'untrusted'})
    assert response['requires_reconciliation']
    assert response['question']['content']==turn['decision']['question']
    assert question()['id']==response['question']['id']
    assert post(path+'/turns/rtc-1/spoken-question',{'content':'另一个伪造题目','source_ref':'another'})['question']['id']==response['question']['id']
    """)


def test_concurrent_retries_call_generator_once(tmp_path):
    run_case(tmp_path, """
    q=question()
    entered,release=Event(),Event()
    calls=[]
    def generate(**kwargs):
        calls.append(1);entered.set()
        assert release.wait(5)
        return {'question':'服务端追问'}
    main.generate_kimi_followup=generate
    body={'question_id':q['id'],'submission_id':'same','content':'我使用缓存减少查询。'}
    with ThreadPoolExecutor(6) as pool:
        futures=[pool.submit(main.submit_turn,i,dict(body),user) for _ in range(6)]
        assert entered.wait(5)
        time.sleep(.1)
        assert len(calls)==1
        other=client.post(path+'/turns',json={**body,'submission_id':'different','content':'不同答案'})
        assert other.status_code==409,other.text
        release.set()
        replies=[f.result() for f in futures]
    assert len(calls)==1 and sum(r['duplicate'] for r in replies)==5
    assert main.one('SELECT COUNT(*) AS n FROM interview_turns')['n']==1
    job=jobs.task_by_key(i,'followup',q['id'])
    assert job['status']=='succeeded' and job['attempt_count']==1
    assert json.loads(job['result_json'])['answer']['id']==replies[0]['answer']['id']
    """)


def test_late_report_cannot_overwrite_rescore_or_review(tmp_path):
    run_case(tmp_path, """
    answer=answered()
    post(path+'/evaluations',{'message_id':answer['id']})
    pending=finish_without_worker()
    entered,release=Event(),Event()
    def generate(**kwargs):
        if kwargs['fallback_report']['total_score']==60:
            entered.set();assert release.wait(8)
        return {**kwargs['fallback_report'],'provider':'custom','model':'test-model','prompt_version':main.REPORT_PROMPT_VERSION,'fallback':False}
    main.generate_ai_report=generate
    call=pending.tasks[0]
    with ThreadPoolExecutor(1) as pool:
        old=pool.submit(call.func,*call.args,**call.kwargs)
        assert entered.wait(5)
        main.generate_ai_evaluation=lambda **kwargs:grade(85)
        post(path+'/evaluations',{'message_id':answer['id'],'force':True})
        fresh=post(path+'/report')['report']
        assert fresh['total_score']==85 and fresh['source_revision']==2,fresh
        main.db.execute("UPDATE interview_reports SET review_status='approved' WHERE id=?",(fresh['id'],)).close()
        main.db.commit()
        release.set();old.result()
    latest=post(path+'/report')['report']
    assert latest['total_score']==85 and latest['source_revision']==2
    assert latest['review_status']=='approved'
    old_job=jobs.task_by_key(i,'report','1')
    assert old_job['status']=='superseded' and json.loads(old_job['result_json'])['total_score']==60
    """)


def test_http_retry_observes_pending_job_and_reuses_completed_turn(tmp_path):
    run_case(tmp_path, """
    import os
    os.environ['INTERVIEW_TASK_WAIT_SECONDS']='0'
    q=question();entered,release=Event(),Event();calls=[]
    def generate(**kwargs):
        calls.append(1);entered.set();assert release.wait(5)
        return {'question':'服务端追问'}
    main.generate_kimi_followup=generate
    body={'question_id':q['id'],'submission_id':'http-retry','content':'我使用缓存减少查询。'}
    with ThreadPoolExecutor(1) as pool:
        first=pool.submit(main.submit_turn,i,body,user)
        assert entered.wait(5)
        pending=client.post(path+'/turns',json=body)
        assert pending.status_code==202 and pending.json()['processing'],pending.text
        assert jobs.task_by_id(pending.json()['task_id'])['status']=='running'
        release.set();original=first.result()
    replay=post(path+'/turns',body)
    assert replay['duplicate'] and replay['answer']['id']==original['answer']['id']
    assert calls==[1]
    """)


def test_lost_report_job_recovers_and_old_lease_is_fenced(tmp_path):
    run_case(tmp_path, """
    pending=finish_without_worker()
    task=jobs.task_by_key(i,'report','0')
    old_token=task['lease_token']
    main.db.execute('UPDATE interview_tasks SET lease_until=0 WHERE id=?',(task['id'],)).close();main.db.commit()
    main.recover_generation_tasks_once()
    recovered=jobs.task_by_id(task['id'])
    assert recovered['status']=='succeeded' and recovered['attempt_count']==2,recovered
    assert client.get(path+'/report').json()['report']['generation_status']!='queued'
    main.recover_generation_tasks_once()
    assert jobs.task_by_id(task['id'])['attempt_count']==2
    with main.locked_session(i,user['id']):
        assert not jobs.finish_locked(task['id'],old_token,{'stale':True})
    """)


def test_lost_followup_job_recovers_from_saved_input(tmp_path):
    run_case(tmp_path, """
    q=question()
    message=main.parse_message_input({'sender_type':'candidate','message_type':'answer','content':'我使用缓存减少查询。','source_ref':'recover'})
    with main.locked_session(i,user['id']):
        task=jobs.enqueue_locked(i,'followup',q['id'],{'question_id':q['id'],'submission_id':'recover','message':message,'answer_id':'recovered-answer'})
    main.generate_kimi_followup=lambda **kwargs:{'question':'恢复后的追问'}
    main.recover_generation_tasks_once()
    assert jobs.task_by_id(task['id'])['status']=='succeeded'
    turn=main.turn_by(i,'recover')
    assert turn['answer_id']=='recovered-answer'
    assert main.find_message_by_interview_id(turn['next_question_id'],i)['content']=='恢复后的追问'
    """)


def test_expired_report_worker_cannot_publish_after_replacement(tmp_path):
    run_case(tmp_path, """
    answer=answered();post(path+'/evaluations',{'message_id':answer['id']})
    pending=finish_without_worker();call=pending.tasks[0]
    entered,release=Event(),Event()
    calls=[]
    def generate(**kwargs):
        calls.append(1)
        is_old=len(calls)==1
        if is_old:entered.set();assert release.wait(8)
        return {**kwargs['fallback_report'],'summary':'old' if is_old else 'fresh',
            'provider':'custom','model':'test-model','prompt_version':main.REPORT_PROMPT_VERSION,'fallback':False}
    main.generate_ai_report=generate
    with ThreadPoolExecutor(1) as pool:
        old=pool.submit(call.func,*call.args,**call.kwargs)
        assert entered.wait(5)
        main.db.execute('UPDATE interview_tasks SET lease_until=0 WHERE interview_id=?',(i,)).close();main.db.commit()
        fresh=post(path+'/report')['report']
        assert fresh['summary']=='fresh'
        release.set();old.result()
    assert client.get(path+'/report').json()['report']['summary']=='fresh'
    assert len(calls)==2 and jobs.task_by_key(i,'report','1')['attempt_count']==2
    """)


def test_another_process_recovers_persisted_report(tmp_path):
    run_case(tmp_path, """
    import os,subprocess,sys
    answer=answered();post(path+'/evaluations',{'message_id':answer['id']})
    finish_without_worker()
    main.db.execute('UPDATE interview_tasks SET lease_until=0 WHERE interview_id=?',(i,)).close();main.db.commit()
    worker = ("from backend.src import main\\n"
        "from fastapi.testclient import TestClient\\nimport time\\n"
        "main.generate_ai_report=lambda **kw:{**kw['fallback_report'],'provider':'custom','model':'test-model','prompt_version':main.REPORT_PROMPT_VERSION,'fallback':False}\\n"
        "with TestClient(main.app):\\n"
        "    deadline=time.monotonic()+8\\n"
        "    while main.one('SELECT COUNT(*) AS n FROM interview_tasks WHERE task_type=? AND status=?', ('report','succeeded'))['n']==0:\\n"
        "        assert time.monotonic()<deadline,'startup recovery timed out'\\n"
        "        time.sleep(.05)\\n")
    result=subprocess.run([sys.executable,'-B','-c',worker],env=os.environ.copy(),capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stdout+result.stderr
    job=jobs.task_by_key(i,'report','1')
    assert job['status']=='succeeded' and job['attempt_count']==2,job
    report=client.get(path+'/report').json()['report']
    assert report['total_score']==60 and report['source_revision']==1
    """)


def test_invalid_rescore_does_not_advance_revision(tmp_path):
    run_case(tmp_path, """
    answer=answered()
    post(path+'/evaluations',{'message_id':answer['id']})
    def unavailable(**kwargs):raise main.AiEvaluationError('mock failure')
    main.generate_ai_evaluation=unavailable
    result=post(path+'/evaluations',{'message_id':answer['id'],'force':True})
    assert result['evaluation']['score']==60
    assert main.one('SELECT evaluation_revision FROM interview_sessions WHERE id=?',(i,))['evaluation_revision']==1
    main.database_module.init_db();main.database_module.init_db()
    assert main.one('SELECT evaluation_revision FROM interview_sessions WHERE id=?',(i,))['evaluation_revision']==1
    """)


def test_additive_migration_preserves_existing_report_and_review(tmp_path):
    run_case(tmp_path, """
    answer=answered();post(path+'/evaluations',{'message_id':answer['id']})
    pending=finish_without_worker();call=pending.tasks[0];call.func(*call.args,**call.kwargs)
    main.db.execute("UPDATE interview_reports SET review_status='approved' WHERE interview_id=?",(i,)).close();main.db.commit()
    original=main.find_report_by_interview_id(i,user['id'])
    # 保留实际面试与报告记录，重建上一版表结构以验证增量迁移。
    main.db.execute('DROP TABLE interview_tasks').close()
    main.db.execute('ALTER TABLE interview_sessions DROP COLUMN evaluation_revision').close()
    main.db.execute('ALTER TABLE interview_reports DROP COLUMN source_revision').close();main.db.commit()
    main.database_module.init_db();main.database_module.init_db()
    upgraded=main.find_report_by_interview_id(i,user['id'])
    for key in ('id','total_score','summary','review_status','timeline_review'):
        assert upgraded[key]==original[key],(key,upgraded)
    assert upgraded['source_revision'] is None
    assert main.one('SELECT evaluation_revision FROM interview_sessions WHERE id=?',(i,))['evaluation_revision']==0
    assert main.one('SELECT COUNT(*) AS n FROM interview_tasks')['n']==0
    """)


def test_review_rejects_a_changed_report_snapshot(tmp_path):
    run_case(tmp_path, """
    answer=answered();post(path+'/evaluations',{'message_id':answer['id']})
    pending=finish_without_worker();call=pending.tasks[0];call.func(*call.args,**call.kwargs)
    from admin_backend.src import main as admin
    import asyncio
    admin.validate_admin_origin=lambda request:None
    admin._ensure_student_in_scope=lambda actor,uid:None
    admin.record_audit=lambda *a,**k:None
    report=admin.get_report_detail(main.find_report_by_interview_id(i,user['id'])['id'])
    payload={'status':'approved','source_revision':report['source_revision'],'review_token':report['review_token']}
    class Request:
        async def json(self):return payload
    actor={'id':'test-reviewer'}
    asyncio.run(admin.review_report(Request(),report['id'],actor))
    # 即使评分版本相同，报告文字变化后也必须拒绝旧复核令牌。
    main.db.execute("UPDATE interview_reports SET summary='new summary' WHERE id=?",(report['id'],)).close();main.db.commit()
    try:asyncio.run(admin.review_report(Request(),report['id'],actor))
    except admin.HTTPException as exc:assert exc.status_code==409
    else:raise AssertionError('stale review token accepted')
    """)
