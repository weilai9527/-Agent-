import React, { useEffect, useRef, useState } from 'react';
import VersionedReportPanel from './VersionedReportPanel.jsx';
import { futureDeadline, keyedWrite, localDate, newRequestId, postJson, readError } from '../../frontend/src/trainingUi.js';
import '../../frontend/src/training.css';

const training = '/api/admin/training';
const analytics = '/api/admin/analytics/v1/teaching';

function useRead(request, path, revision) {
  const [reply, setReply] = useState(null);
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    request(path, { signal: controller.signal }).then((data) => {
      if (!controller.signal.aborted) setReply({ path, revision, data });
    }).catch((error) => {
      if (!controller.signal.aborted) setReply({ path, revision, error: readError(error) });
    });
    return () => controller.abort();
  }, [request, path, revision]);
  // 读取新名单时先隐藏旧结果，避免暂时显示上一任务或上一组筛选条件下的学生。
  return reply?.path === path && reply?.revision === revision ? reply : {};
}

function ReadPanel({ result, children }) {
  if (result.error) return <p role="alert">{result.error}</p>;
  if (!result.data) return <p role="status">正在读取…</p>;
  return children(result.data);
}

function Limits() {
  return <div className="training-row">
    <label className="training-field">截止时间（当地时间）<input required type="datetime-local" name="deadline" /></label>
    <label className="training-field">每人最多尝试<input required type="number" name="max_attempts" min="1" max="100" step="1" defaultValue="1" /></label>
  </div>;
}

function readLimits(form) {
  return { deadline: futureDeadline(form.get('deadline')), max_attempts: Number(form.get('max_attempts')) };
}

function NewTask({ classes, request, onPosted }) {
  const [questions, setQuestions] = useState(() => [newRequestId()]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const lastWrite = useRef(null);
  async function publish(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    setError('');
    try {
      const payload = {
        title: values.get('title').trim(), job_role: values.get('job_role').trim(),
        class_ids: values.getAll('class_id'), ...readLimits(values),
        questions: questions.map((question_id) => ({ question_id, prompt: values.get(question_id).trim() })),
      };
      if (!payload.class_ids.length || payload.class_ids.length > 100) throw new Error('每个任务可选择 1 至 100 个目标班级。');
      if (!payload.title || !payload.job_role || payload.questions.some((item) => !item.prompt)) throw new Error('请填写任务名称、目标岗位与每道题的题干。');
      setPending(true);
      lastWrite.current = keyedWrite(lastWrite.current, payload);
      const task = await postJson(request, training + '/tasks', { ...payload, request_id: lastWrite.current.request_id });
      lastWrite.current = null;
      form.reset();
      setQuestions([newRequestId()]);
      onPosted(task);
    } catch (err) { setError(readError(err)); }
    finally { setPending(false); }
  }
  return <form className="training-card" onSubmit={publish}>
    <header><h3>布置班级任务</h3><p className="training-meta">发布时按所选班级冻结在册名单。</p></header>
    <fieldset disabled={pending} className="training-stack">
      <legend>任务设置</legend>
      <label className="training-field">任务名称<input required name="title" maxLength={160} /></label>
      <label className="training-field">目标岗位<input required name="job_role" maxLength={128} /></label>
      <fieldset><legend>目标班级</legend><div className="training-row">{classes.map((entry) => <label key={entry.class_id}>
        <input type="checkbox" name="class_id" value={entry.class_id} /> {entry.name || entry.class_id}
      </label>)}{!classes.length && <span>当前没有可布置任务的班级。</span>}</div></fieldset>
      <Limits />
      {questions.map((key, i) => <div key={key} className="training-stack">
        <label className="training-field">第 {i + 1} 题<textarea name={key} required rows={2} maxLength={4000} /></label>
        {questions.length > 1 && <div><button type="button" onClick={() => setQuestions(questions.filter((id) => id !== key))}>移除第 {i + 1} 题</button></div>}
      </div>)}
      <div><button type="button" disabled={questions.length >= 100} onClick={() => setQuestions([...questions, newRequestId()])}>添加题目</button></div>
    </fieldset>
    {error && <p role="alert">{error}</p>}
    <div><button className="training-primary" disabled={pending || !classes.length}>{pending ? '正在发布…' : '发布并冻结名单'}</button></div>
  </form>;
}

function TaskList({ request, revision, tasks, permissions }) {
  const [selected, setSelected] = useState('');
  const [interview, setInterview] = useState('');
  const roster = useRead(request, selected && training + '/tasks/' + encodeURIComponent(selected) + '/roster', revision);
  const reference = useRead(request, interview && '/api/admin/interviews/' + encodeURIComponent(interview) + '/report-reference', revision);
  return <section className="training-card"><h3>已发布任务</h3>{tasks.length === 0 && <p>暂无任务。</p>}
    <ul className="training-list">{tasks.map((task) => <li key={task.task_id}>
      <strong>{task.title}</strong><p className="training-meta">{task.job_role} · {task.student_count} 人 · 每人 {task.max_attempts} 次 · 截止 {localDate(task.deadline)}</p>
      <div><button type="button" aria-expanded={selected === task.task_id} onClick={() => {
        setInterview(''); setSelected(selected === task.task_id ? '' : task.task_id);
      }}>查看冻结名单与进度</button></div>
      {selected === task.task_id && <ReadPanel result={roster}>{({ items }) => items.length ? <div className="training-scroll"><table>
        <thead><tr><th>学生编号</th><th>冻结班级</th><th>已领取</th><th>已完成</th></tr></thead>
        <tbody>{items.map((r) => <tr key={r.student_id}><td>{r.student_id}</td><td>{r.class_id}</td><td>{r.used_attempts}</td><td>{r.completed_attempts}
          {permissions?.canReadTrainingReports && r.latest_completed_interview && <button type="button"
            onClick={() => setInterview(r.latest_completed_interview)}>查看最近报告</button>}
        </td></tr>)}</tbody>
      </table></div> : <p>名单为空。</p>}</ReadPanel>}
      {selected === task.task_id && interview && permissions?.canReadTrainingReports && <ReadPanel result={reference}>
        {({ report_id }) => <VersionedReportPanel key={report_id} reportId={report_id} request={request}
          canReview={permissions.canReviewReports} canAdjust={permissions.canAdjustScores} />}
      </ReadPanel>}
    </li>)}</ul></section>;
}

function PracticeForm({ request, row, onPosted }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const lastWrite = useRef(null);
  async function publish(event) {
    event.preventDefault();
    setError('');
    try {
      // 服务端从原训练记录确定复练学生，并读取当时保存的题目。
      const payload = { attempt_id: row.attempt_id, question_id: row.question_id, ...readLimits(new FormData(event.currentTarget)) };
      lastWrite.current = keyedWrite(lastWrite.current, payload);
      setPending(true);
      const task = await postJson(request, analytics + '/practice', { ...payload, request_id: lastWrite.current.request_id });
      onPosted(task);
    } catch (err) { setError(readError(err)); }
    finally { setPending(false); }
  }
  return <details><summary>给原答题学生布置复练</summary><form className="training-stack" onSubmit={publish}>
    <fieldset disabled={pending}><legend>复练设置</legend><Limits /></fieldset>
    {error && <p role="alert">{error}</p>}
    <div><button className="training-primary" disabled={pending}>{pending ? '正在下发…' : '下发原题复练'}</button></div>
  </form></details>;
}

const groups = [['by_task', '任务'], ['by_class', '班级'], ['by_job', '岗位'], ['by_dimension', '能力维度']];

function Teaching({ request, revision, tasks, classes, onPosted, canAssignPractice }) {
  const [query, setQuery] = useState('');
  const [group, setGroup] = useState('by_dimension');
  const summary = useRead(request, analytics + '/summary' + query, revision);
  const weak = useRead(request, analytics + '/weaknesses' + query, revision);
  function filter(event) {
    event.preventDefault();
    const search = new URLSearchParams();
    for (const [key, value] of new FormData(event.currentTarget)) if (value.trim()) search.set(key, value.trim());
    setQuery(search.size ? '?' + search : '');
  }
  const names = {
    by_class: new Map(classes.map((r) => [r.class_id, r.name])),
    by_task: new Map(tasks.map((r) => [r.task_id, r.title])),
  };
  return <section className="training-stack">
    <form className="training-card" onSubmit={filter}><h3>教学分析范围</h3><div className="training-row">
      <label className="training-field">班级<select name="class_id"><option value="">全部可见班级</option>{classes.map((r) => <option key={r.class_id} value={r.class_id}>{r.name || r.class_id}</option>)}</select></label>
      <label className="training-field">任务<select name="task_id"><option value="">全部可见任务</option>{tasks.map((r) => <option key={r.task_id} value={r.task_id}>{r.title}</option>)}</select></label>
      <label className="training-field">岗位<input name="job_role" /></label><label className="training-field">能力维度<input name="dimension" /></label>
      <button>应用筛选</button>
    </div></form>
    <section className="training-card"><h3>已评估成绩</h3><ReadPanel result={summary}>{(data) => <>
      <p>{data.attempts} 次尝试 · {data.completed_questions} 道已评估题目 · 平均分 {data.average_score ?? '—'}</p>
      <div className="training-row">{groups.map(([key, label]) => <button type="button" key={key} aria-pressed={key === group} onClick={() => setGroup(key)}>按{label}</button>)}</div>
      {data[group].length ? <div className="training-scroll"><table><thead><tr><th>分组</th><th>尝试数</th><th>题数</th><th>平均分</th></tr></thead><tbody>
        {data[group].map((r) => <tr key={r.key}><td>{names[group]?.get(r.key) || r.key}</td><td>{r.attempts}</td><td>{r.completed_questions}</td><td>{r.average_score ?? '—'}</td></tr>)}
      </tbody></table></div> : <p>当前条件下暂无成绩。</p>}
    </>}</ReadPanel></section>
    <section className="training-card"><h3>薄弱项与原题复练</h3><ReadPanel result={weak}>{({ items }) => !items.length ? <p>当前条件下没有薄弱项。</p> : <ul className="training-list">{items.map((r) =>
      <li key={JSON.stringify([r.attempt_id, r.question_id, r.dimension])}><strong>{r.question_text}</strong><p className="training-meta">学生 {r.student_id} · {r.job_role} · {r.dimension} · {r.score} 分 · 第 {r.version} 版评分</p>
        <details><summary>查看原回答</summary><pre>{r.original_answer || '（未作答）'}</pre></details>
        {canAssignPractice && <PracticeForm request={request} row={r} onPosted={onPosted} />}
      </li>)}</ul>}</ReadPanel></section>
  </section>;
}

export default function TrainingTasksPage({ request, permissions, canAssign = false, canAssignPractice = false }) {
  const [tab, setTab] = useState('tasks');
  const [revision, setRevision] = useState(0);
  const [notice, setNotice] = useState('');
  const classes = useRead(request, training + '/classes', revision);
  const tasks = useRead(request, training + '/tasks', revision);
  function posted(task) {
    setNotice('已发布「' + task.title + '」，冻结名单共 ' + task.student_count + ' 人。');
    setRevision((n) => n + 1);
  }
  return <div className="training-page">
    <div className="training-row training-between"><div className="training-row"><button type="button" aria-pressed={tab === 'tasks'} onClick={() => setTab('tasks')}>班级训练</button>
      <button type="button" aria-pressed={tab === 'analysis'} onClick={() => setTab('analysis')}>教学分析</button></div>
      <button type="button" onClick={() => setRevision((n) => n + 1)}>刷新数据</button></div>
    {notice && <p className="training-output" role="status">{notice}</p>}
    {tab === 'tasks' ? <div className="training-grid">
      {canAssign && <ReadPanel result={classes}>{(data) => <NewTask classes={data.items} request={request} onPosted={posted} />}</ReadPanel>}
      <ReadPanel result={tasks}>{(data) => <TaskList request={request} revision={revision} tasks={data.items} permissions={permissions} />}</ReadPanel>
    </div> : <Teaching request={request} revision={revision} tasks={tasks.data?.items ?? []} classes={classes.data?.items ?? []} onPosted={posted} canAssignPractice={canAssignPractice} />}
  </div>;
}
