import React, { useState } from 'react';
import { localDate } from '../../frontend/src/trainingUi.js';
import { counts, Metric, Panel, Result, useResource } from './nativeDashboardParts.jsx';
import NativeOperationsDashboard from './NativeOperationsDashboard.jsx';
import VersionedReportPanel from './VersionedReportPanel.jsx';
import './dashboard.css';
import './nativeTeachingDashboard.css';

const workbench = '/api/admin/training/tasks?view=workbench';
const teaching = '/api/admin/analytics/v1/teaching';

const progressKeys = ['task_count', 'enrolled_students', 'assigned_students', 'completed_students', 'assigned_task_students', 'completed_task_students'];
const coverageKeys = ['attempts', 'completed_questions', 'valid_attempts', 'insufficient_attempts', 'unknown_coverage_attempts'];
const hasWorkbench = (data) => counts(data.summary, progressKeys) && Array.isArray(data.items) && Array.isArray(data.classes)
  && data.classes.every((r) => counts(r, progressKeys)) && data.items.every((t) => Array.isArray(t.class_ids));
const hasSummary = (data) => counts(data, coverageKeys) && Array.isArray(data.by_class) && Array.isArray(data.class_weaknesses)
  && data.by_class.every((r) => counts(r, coverageKeys));

function TaskDetail({ task }) {
  return <div className="nt-detail"><strong>{task.title}</strong><small>任务编号 {task.task_id}</small>
    <p>{task.job_role} · 截止 {localDate(task.deadline)} · 每人最多 {task.max_attempts} 次</p>
    {task.questions?.length > 0 && <ol>{task.questions.map((q) => <li key={q.question_id}>{q.prompt}</li>)}</ol>}
  </div>;
}

function Participation({ data, classId }) {
  const group = classId ? data.classes.find((c) => c.class_id === classId) : data.summary;
  if (!group) return <p>当前训练范围没有该班级。</p>;
  const tasks = classId ? data.items.filter((task) => task.class_ids.includes(classId)) : data.items;
  return <>
    <dl className="nt-metrics"><Metric label="应参加" count={group.assigned_task_students} unit="人次" />
      <Metric label="已完成" count={group.completed_task_students} unit="人次" /></dl>
    <p>在册 {group.enrolled_students} 人，其中 {group.assigned_students} 人被分配任务，{group.completed_students} 人至少完成一项。</p>
    {group.task_count === 0 ? <p className="nt-message">当前范围尚未布置任务。</p> : <details><summary>查看 {group.task_count} 项任务</summary>
      <ul className="nt-tasks">{tasks.map((t) => <li key={t.task_id}><details><summary>{t.title}</summary><TaskDetail task={t} /></details></li>)}</ul>
    </details>}
  </>;
}

function Coverage({ data, classId }) {
  const group = classId ? data.by_class.find((c) => c.key === classId) : data;
  if (!group?.attempts) return <p>当前范围尚无已投递的评分样本。</p>;
  return <>
    <dl className="nt-metrics"><Metric label="有效样本" count={group.valid_attempts} unit="次" />
      <Metric label="覆盖不足" count={group.insufficient_attempts} unit="次" /></dl>
    <p>共收到 {group.attempts} 次尝试的评分，其中 {group.unknown_coverage_attempts} 次缺少历史题目总数，覆盖情况未知。</p>
  </>;
}

function Report({ request, interviewId, revision }) {
  const reference = useResource(request, '/api/admin/interviews/' + encodeURIComponent(interviewId) + '/report-reference', revision);
  return <Result reply={reference} label="关联报告" valid={(r) => typeof r.report_id === 'string' && r.report_id.length > 0}>
    {(r) => <VersionedReportPanel key={r.report_id} request={request} reportId={r.report_id} />}
  </Result>;
}

function Evidence({ request, group, canReport, tasks, revision, trainingAvailable }) {
  const [reportKey, setReportKey] = useState(null);
  const query = new URLSearchParams({ class_id: group.class_id, dimension: group.dimension });
  // 班级汇总不携带个人回答。仅在教师选择具体薄弱项后读取其当前可见的原题。
  const reply = useResource(request, teaching + '/weaknesses?' + query, revision);
  return <Result reply={reply} label="薄弱项原题" valid={(r) => Array.isArray(r.items)}>{({ items }) =>
    items.length === 0 ? <p>该维度当前没有可见原题。</p> : <ul className="nt-evidence">{items.map((row) => {
      const task = tasks.get(row.task_id);
      const key = JSON.stringify([row.attempt_id, row.question_id, row.dimension]);
      return <li key={key}><strong>{row.question_text}</strong>
        <small>学生 {row.student_id} · {row.score} 分 · 评分版本 {row.version} · 题目编号 {row.question_id}</small>
        <details><summary>查看原回答</summary><p className="nt-answer">{row.original_answer || '（未作答）'}</p></details>
        {task ? <details><summary>定位任务 · {task.title}</summary><TaskDetail task={task} /></details> :
          <p>关联任务编号 {row.task_id}。{trainingAvailable ? '当前可见任务中无此记录。' : '任务详情暂不可见。'}</p>}
        {!canReport ? <small>当前账号无权查看关联报告。</small> : !row.interview_id ?
          <small>历史记录缺少面试编号，无法定位报告。</small> : <>
            <button type="button" className="wb-link" aria-expanded={reportKey === key} onClick={() => setReportKey(reportKey === key ? null : key)}>
              {reportKey === key ? '收起关联报告' : '查看关联报告'}
            </button>
            {reportKey === key && <Report request={request} interviewId={row.interview_id} revision={revision} />}
          </>}
      </li>;
    })}</ul>}</Result>;
}

function Weaknesses({ request, data, training, classId, classNames, canReport, revision }) {
  const [selected, setSelected] = useState(null);
  const rows = data.class_weaknesses.filter((r) => !classId || r.class_id === classId);
  const taskById = new Map(training?.items.map((t) => [t.task_id, t]));
  const coverage = classId ? data.by_class.find((r) => r.key === classId) : data;
  if (!coverage?.completed_questions) return <p>当前范围暂无已评原题，尚无法判断薄弱项。</p>;
  if (!rows.length) return <p>当前范围未发现低于 60 分的已评原题。</p>;
  return <ul className="nt-groups">{rows.map((row) => {
    const key = JSON.stringify([row.class_id, row.dimension]);
    return <li key={key}><div className="nt-group"><div><h3>{classNames.get(row.class_id) || row.class_id} · {row.dimension}</h3>
      <p>{row.weak_questions} / {row.scored_questions} 道已评原题低于 60 分，涉及 {row.affected_students} 名学生 · 该维度均分 {row.average_score ?? '—'}</p></div>
      <button type="button" className="wb-link" aria-expanded={selected === key} onClick={() => setSelected(selected === key ? null : key)}>
        {selected === key ? '收起原题' : '定位原题'}
      </button></div>
      {selected === key && <Evidence request={request} group={row} canReport={canReport} tasks={taskById} trainingAvailable={!!training} revision={revision} />}
    </li>;
  })}</ul>;
}

export default function NativeTeachingDashboard({ request, canReadTraining = false, canReadAnalytics = false, permissions = {}, grants = [], onOpenTasks, onNavigate, revision = 0 }) {
  const [classId, setClassId] = useState('');
  const [reload, setReload] = useState(0);
  const snapshot = String(revision) + '/' + reload;
  const progress = useResource(request, canReadTraining && workbench, snapshot);
  const scores = useResource(request, canReadAnalytics && teaching + '/summary', snapshot);
  const training = progress.data && hasWorkbench(progress.data) ? progress.data : null;
  const classes = new Map(training?.classes.map((c) => [c.class_id, c.name || c.class_id]));
  if (scores.data && hasSummary(scores.data)) {
    for (const { key } of scores.data.by_class) if (!classes.has(key)) classes.set(key, key);
  }
  return <div className="wb-page nt-dashboard">
    <header className="wb-intro"><div><span className="wb-eyebrow">学校工作台</span><h2>学校运营与教学进度</h2><p>查看当前授权范围内的账号待办、面试进展、报告质检和班级训练。</p></div>
      {onOpenTasks && (canReadTraining || canReadAnalytics) && <button type="button" className="secondary-button" onClick={onOpenTasks}>进入教学任务与分析</button>}
    </header>
    <NativeOperationsDashboard request={request} permissions={permissions} grants={grants} onNavigate={onNavigate}
      revision={snapshot} classes={classes} />
    <header className="wb-intro"><div><h2>班级任务与薄弱项</h2><p>按冻结任务与当前学籍查看全时段的教学训练。</p></div></header>
    {(canReadTraining || canReadAnalytics) && <div className="wb-filter-bar"><label>查看班级<select value={classId} onChange={(e) => setClassId(e.target.value)}>
      <option value="">全部可见班级</option>{classId && !classes.has(classId) && <option value={classId}>已选班级</option>}
      {[...classes].map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
      <button type="button" className="wb-clear" onClick={() => setReload((n) => n + 1)}>刷新教学数据</button></div>}
    <div className="nt-grid"><Panel title="任务参与" note="同一学生在同一任务中多次尝试，仅计一次。名单限当前可见学籍。">
      <Result reply={progress} label="训练名单与进度" valid={hasWorkbench}>{(d) => <Participation data={d} classId={classId} />}</Result>
    </Panel><Panel title="评分覆盖" note="每次尝试计一个样本。全部冻结原题均取得最新评分，才计入有效样本。">
      <Result reply={scores} label="评分覆盖" valid={hasSummary}>{(d) => <Coverage data={d} classId={classId} />}</Result>
    </Panel></div>
    <Panel title="班级薄弱项" note="按班级和能力维度查看。每道原题的计数均对应一条学生尝试。">
      <Result reply={scores} label="班级薄弱项" valid={hasSummary}>{(d) =>
        <Weaknesses key={classId} request={request} data={d} classId={classId} training={training} classNames={classes}
          canReport={Boolean(permissions?.canReadTrainingReports)} revision={snapshot} />}</Result>
    </Panel>
  </div>;
}
