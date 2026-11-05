import React, { useEffect, useState } from 'react';
import { claimRequestId, localDate, postJson, readError } from './trainingUi.js';
import './training.css';

const tasksPath = '/api/training/tasks';
const weakPath = '/api/analytics/v1/me/weaknesses';

function useItems(request, path, revision) {
  const [state, setState] = useState({});
  useEffect(() => {
    const controller = new AbortController();
    request(path, { signal: controller.signal }).then(({ items }) => {
      if (!controller.signal.aborted) setState({ revision, items });
    }).catch((error) => {
      if (!controller.signal.aborted) setState({ revision, error: readError(error) });
    });
    return () => controller.abort();
  }, [request, path, revision]);
  return state.revision === revision ? state : {};
}

function StudentTask({ request, task, onOpenAttempt, refresh }) {
  const [receipt, setReceipt] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  // 教学服务先预留面试编号。进入面试时，网关还要用当前学生会话向面试服务核验并创建会话。
  const active = receipt || (task.latest_attempt?.status === 'started' && task.latest_attempt);
  const exhausted = task.used_attempts >= task.max_attempts;
  const expired = Date.parse(task.deadline) <= Date.now();
  const count = Math.max(task.used_attempts, active?.attempt_no ?? 0);
  async function claim() {
    setBusy(true);
    setError('');
    try {
      const url = tasksPath + '/' + encodeURIComponent(task.task_id) + '/attempts';
      const attempt = await postJson(request, url, { request_id: claimRequestId(task.used_attempts) });
      // 重放领取请求可能返回其他标签页已完成的尝试，以服务端记录刷新次数。
      if (attempt.status === 'completed') refresh();
      else setReceipt(attempt);
    } catch (err) { setError(readError(err)); }
    finally { setBusy(false); }
  }
  async function open() {
    setBusy(true);
    setError('');
    try { await onOpenAttempt({ ...active, task_id: task.task_id }); }
    catch (err) { setError(readError(err)); }
    finally { setBusy(false); }
  }
  return <li>
    <h3>{task.title}</h3><p className="training-meta">{task.source_attempt_id ? '原题复练' : '班级任务'} · {task.job_role} · 已用 {count} / {task.max_attempts} 次</p>
    <p>截止 {localDate(task.deadline)} · {task.questions.length} 道题</p>
    <details><summary>查看任务题目</summary><ol>{task.questions.map((q) => <li key={q.question_id}><pre>{q.prompt}</pre></li>)}</ol></details>
    {task.latest_attempt?.status === 'completed' && !active && <p className="training-meta">第 {task.latest_attempt.attempt_no} 次训练已完成。</p>}
    {active ? <div className="training-output"><p>第 {active.attempt_no} 次已领取</p>
      <small>尝试编号 {active.attempt_id}</small>
      {onOpenAttempt && <div><button className="training-primary" type="button" disabled={busy} onClick={open}>{busy ? '正在进入…' : '继续本次面试'}</button></div>}
    </div> : <div><button type="button" className="training-primary" disabled={busy || expired || exhausted} onClick={claim}>
      {busy ? '正在领取…' : expired ? '已截止' : exhausted ? '次数已用完' : '领取一次训练'}
    </button></div>}
    {error && <p role="alert">{error}</p>}
  </li>;
}

export default function StudentTrainingPage({ request, onOpenAttempt }) {
  const [revision, setRevision] = useState(0);
  const refresh = () => setRevision((n) => n + 1);
  const tasks = useItems(request, tasksPath, revision);
  const weak = useItems(request, weakPath, revision);
  return <section className="training-page training-candidate">
    <header className="training-row training-between"><div><h2>我的训练</h2><p className="training-meta">查看班级任务、老师下发的原题复练，以及已评估的薄弱项。</p></div>
      <button type="button" onClick={refresh}>刷新数据</button></header>
    <div className="training-grid">
      <section className="training-card"><h2>待办与训练记录</h2>
        {tasks.error ? <p role="alert">{tasks.error}</p> : !tasks.items ? <p role="status">正在读取任务…</p> : !tasks.items.length ? <p>目前没有分配给你的训练任务。</p> :
          <ul className="training-list">{tasks.items.map((task) => <StudentTask key={task.task_id} task={task} request={request} onOpenAttempt={onOpenAttempt} refresh={refresh} />)}</ul>}
      </section>
      <section className="training-card"><h2>我的薄弱项</h2>
        {weak.error ? <p role="alert">{weak.error}</p> : !weak.items ? <p role="status">正在读取评分…</p> : !weak.items.length ? <p>目前没有标为薄弱项的题目。</p> :
          <ul className="training-list">{weak.items.map((item) => <li key={JSON.stringify([item.attempt_id, item.question_id, item.dimension])}>
            <h3>{item.question_text}</h3><p className="training-meta">{item.job_role} · {item.dimension} · {item.score} 分</p>
            <details><summary>回看我的原回答</summary><pre>{item.original_answer || '（未作答）'}</pre></details>
          </li>)}</ul>}
      </section>
    </div>
  </section>;
}
