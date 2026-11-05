import React, { useCallback, useEffect, useState } from 'react';
import { dashboardRange } from './dashboardModel.js';
import { counts, Metric, Panel, Result, useResource } from './nativeDashboardParts.jsx';
import VersionedReportPanel from './VersionedReportPanel.jsx';

const maxRows = 5;
const labels = {
  training: '班级训练', practice: '自主练习', draft: '草稿', running: '进行中', completed: '已完成',
  queued: '排队中', generating: '生成中', succeeded: '生成成功', degraded: '部分降级',
  pending_retry: '等待补评', insufficient_evidence: '证据不足', failed: '生成失败',
  pending: '待复核', approved: '已通过', rejected: '未通过', unknown: '状态未知', other: '其他状态',
  gte90: '90 分及以上', from80: '80 至 89 分', from70: '70 至 79 分', below70: '低于 70 分',
};
const text = (value) => labels[value] ?? value ?? '—';
const accountCounts = ['accounts', 'normal_accounts', 'disabled_accounts', 'must_change_password', 'assigned_accounts', 'unassigned_accounts', 'unassigned_normal_accounts'];
const groupedCounts = (obj) => obj != null && typeof obj === 'object' && !Array.isArray(obj) && counts(obj, Object.keys(obj));
const bounded = (items) => Array.isArray(items) && items.length <= maxRows && items.every((row) => typeof row?.id === 'string');
const hasInterviews = (r) => counts(r, ['total', 'running', 'completed', 'completed_students', 'visible_students'])
  && groupedCounts(r.by_status) && groupedCounts(r.by_kind) && bounded(r.recent) && bounded(r.running_items);
const hasReports = (r) => counts(r, ['total', 'eligible']) && (r.average_score === null || Number.isFinite(r.average_score))
  && groupedCounts(r.by_generation) && groupedCounts(r.by_review) && counts(r.score_bands, ['gte90', 'from80', 'from70', 'below70'])
  && counts(r.quality, ['pending_review', 'partial_coverage', 'zero_evidence', 'unknown_coverage'])
  && bounded(r.recent) && bounded(r.pending_items);

function filterQuery(values) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value) query.set(key, value);
  return query.toString();
}

function pathWithQuery(base, values) {
  const query = filterQuery(values);
  return query ? base + '?' + query : base;
}

function SummaryList({ name, values, onSelect }) {
  const entries = Object.entries(values);
  const total = entries.reduce((sum, [, count]) => sum + count, 0);
  return <div className="ops-summary"><strong>{name}</strong>
    <div className="ops-distribution"><ul>{entries.map(([key, count], i) => <li key={key}><i className={'ops-tone-' + i % 5} />{onSelect ?
        <button type="button" className="wb-link" aria-label={'查看' + text(key) + '的报告'} onClick={() => onSelect(key)}>{text(key)} <b>{count}</b></button> :
        <>{text(key)} <b>{count}</b></>}</li>)}</ul>
      {total > 0 && <div className="ops-bars" aria-hidden="true">{entries.map(([key, count], i) =>
        <span key={key} className={'ops-tone-' + i % 5} style={{ width: (100 * count / total) + '%' }} />)}</div>}
    </div>
  </div>;
}

function RecordDetail({ owner, row, request, revision, canReview, canAdjust, onReviewStart, onReviewEnd }) {
  const [review, setReview] = useState(false);
  useEffect(() => {
    if (review) return onReviewEnd;
  }, [review, onReviewEnd]);
  const report = owner === 'assessment';
  const base = '/api/admin/' + owner + '/v1/records/' + encodeURIComponent(row.id);
  const reply = useResource(request, base, revision);
  return <Result reply={reply} label={report ? '报告详情' : '面试详情'} valid={(r) => r.id === row.id && r.student_id === row.student_id}>
    {(r) => <div className="nt-detail"><small>记录编号 {r.id}</small><strong>{r.name} · {r.target_role}</strong>
      {report ? <><p>报告状态 {text(r.generation_status)} · {text(r.review_status)} · 得分 {r.total_score ?? '未评分'}</p>
        <p>{r.summary || '暂无报告摘要。'}</p>
        {r.kind === 'training' && (canReview || canAdjust) && <>
          <button type="button" className="wb-link" aria-expanded={review} onClick={() => { if (!review) onReviewStart(); setReview(!review); }}>{review ? '收起版本' : '核验负责关系并查看版本'}</button>
          {review && <VersionedReportPanel request={request} reportId={r.id} canReview={canReview} canAdjust={canAdjust} />}
        </>}</> : <><p>{text(r.kind)} · {text(r.status)}</p>
          <ol>{r.turns?.map((turn) => <li key={turn.id} className="nt-answer">{turn.content}</li>)}</ol>
          {r.next_cursor && <small>此处仅展示首批问答，更多回合请在学校面试记录中查看。</small>}</>}
    </div>}
  </Result>;
}

function Records({ owner, rows, request, revision, permissions, onReviewStart, onReviewEnd }) {
  const [selected, setSelected] = useState('');
  if (!rows.length) return <p className="nt-message">此列表暂无记录。</p>;
  return <ul className="ops-records">{rows.map((r) => <li key={r.id}>
    <div className="nt-group"><div><strong>{r.name || r.student_id} · {r.target_role || '未登记岗位'}</strong>
      <p>{r.class_name || '未归班'} · {text(r.kind)} · {owner === 'assessment' ? text(r.review_status) : text(r.status)}</p>
      <small>{owner === 'assessment' ? '创建时间' : '更新时间'} {String((owner === 'assessment' ? r.created_at : r.updated_at) || '—').replace('T', ' ')}</small>
    </div><button type="button" className="wb-link" aria-expanded={selected === r.id} onClick={() => setSelected(selected === r.id ? '' : r.id)}>
      {selected === r.id ? '收起详情' : '查看详情'}
    </button></div>
    {selected === r.id && <RecordDetail owner={owner} row={r} request={request} revision={revision}
      onReviewStart={onReviewStart} onReviewEnd={onReviewEnd}
      canReview={permissions.canReadTrainingReports && permissions.canReviewReports}
      canAdjust={permissions.canReadTrainingReports && permissions.canAdjustScores} />}
  </li>)}</ul>;
}

function RecordPanel({ owner, data, request, revision, scope, onNavigate, permissions, onReviewStart, onReviewEnd }) {
  const [tab, setTab] = useState('queue');
  const report = owner === 'assessment';
  function openList(extra) {
    onNavigate(report ? 'schoolReports' : 'schoolInterviews', filterQuery({ ...scope, ...extra }));
  }
  return <>
    {report ? <>
      <dl className="nt-metrics"><Metric label="报告总数" count={data.total} unit="份" /><Metric label="待质检" count={data.quality.pending_review} unit="份" /></dl>
      {data.total ? <>
        <p>可计分报告 {data.eligible} 份，平均 {data.average_score ?? '—'} 分。部分覆盖 {data.quality.partial_coverage} 份，无评分依据 {data.quality.zero_evidence} 份，覆盖未知 {data.quality.unknown_coverage} 份。</p>
        <SummaryList name="生成状态" values={data.by_generation} /><SummaryList name="质检状态" values={data.by_review} />
        <SummaryList name="有效成绩分布" values={data.score_bands} onSelect={onNavigate && ((score_band) => openList({ score_band }))} />
      </> : <p>当前范围没有报告。</p>}
    </> : <>
      <dl className="nt-metrics"><Metric label="面试总数" count={data.total} unit="场" /><Metric label="进行中" count={data.running} unit="场" /></dl>
      <p>当前可见学生 {data.visible_students} 人，其中 {data.completed_students} 人在所选时段完成面试{data.visible_students > 0 ? '，占 ' + Math.round(100 * data.completed_students / data.visible_students) + '%' : ''}。</p>
      {data.total ? <><p>场次完成率 {Math.round(100 * data.completed / data.total)}%（{data.completed} / {data.total}）。</p>
        <SummaryList name="面试状态" values={data.by_status} /><SummaryList name="训练来源" values={data.by_kind} /></> : <p>当前范围没有面试。</p>}
    </>}
    <div className="ops-actions"><button type="button" aria-pressed={tab === 'queue'} onClick={() => setTab('queue')}>{report ? '待质检报告' : '进行中的面试'}</button>
      <button type="button" aria-pressed={tab === 'recent'} onClick={() => setTab('recent')}>{report ? '近期报告' : '近期面试'}</button>
      {onNavigate && <button type="button" className="wb-link" onClick={() => openList(tab === 'queue' ? { state: report ? 'pending' : 'running' } : {})}>
        查看全部{tab === 'queue' ? (report ? '待质检报告' : '进行中面试') : (report ? '报告记录' : '面试记录')}</button>}
    </div>
    <Records key={tab} rows={tab === 'recent' ? data.recent : report ? data.pending_items : data.running_items}
      owner={owner} request={request} revision={revision} permissions={permissions} onReviewStart={onReviewStart} onReviewEnd={onReviewEnd} />
  </>;
}

function Filters({ onApply, classes, colleges, canReadRecords }) {
  return <form className="wb-filter-bar ops-filters" aria-label="运营统计范围" onSubmit={(e) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    onApply({ college: form.get('college').trim(), classId: form.get('class').trim(), period: form.get('period') || 'all', kind: form.get('kind') || '' });
  }}>
    <label>学院编号<input name="college" list="ops-colleges" maxLength={128} placeholder="全部可见学院" /></label>
    <datalist id="ops-colleges">{[...colleges].map(([id, name]) => <option key={id} value={id}>{name}</option>)}</datalist>
    <label>班级编号<input name="class" list="ops-classes" maxLength={128} placeholder="全部可见班级" /></label>
    <datalist id="ops-classes">{[...classes].map(([id, name]) => <option key={id} value={id}>{name}</option>)}</datalist>
    {canReadRecords && <><label>记录时段<select name="period" defaultValue="all">
      <option value="all">全部时间</option><option value="today">今天</option><option value="7">近 7 天</option><option value="30">近 30 天</option>
    </select></label><label>记录来源<select name="kind"><option value="">全部来源</option><option value="training">班级训练</option><option value="practice">自主练习</option></select></label></>}
    <button type="submit" className="wb-clear">应用运营筛选</button>
    <button type="reset" className="wb-clear" onClick={() => onApply({})}>重置</button>
  </form>;
}

export default function NativeOperationsDashboard({ request, permissions, grants, classes, revision, onNavigate }) {
  const [filter, setFilter] = useState({});
  const [version, setVersion] = useState(0);
  const current = revision + '/ops/' + version;
  // 教师撰写复核意见时保留当前报告。切换筛选、收回读取授权或离开报告都会卸载表单；
  // 写入仍由评估服务检查最新负责关系和预期版本。
  const [heldReport, setHeldReport] = useState(null);
  const releaseReport = useCallback(() => setHeldReport(null), []);
  const reportRevision = heldReport ?? current;
  const scope = { college_id: filter.college, class_id: filter.classId };
  const { startDate, endDate } = dashboardRange(filter.period || 'all');
  const recordScope = { ...scope, start_date: startDate, end_date: endDate, kind: filter.kind };
  const period = { ...recordScope, limit: String(maxRows) };
  const accountRead = permissions.canReadStudentAccounts || grants.includes('student.read');
  const interviewRead = permissions.canReadSchoolInterviews || grants.includes('interview.records.read');
  const reportRead = permissions.canReadSchoolReports || grants.includes('report.read');
  const registrations = useResource(request, permissions.canUseRegistrationBook && '/api/admin/identity/v1/student-accounts/pending-summary', current);
  const accounts = useResource(request, accountRead && pathWithQuery('/api/admin/identity/v1/student-accounts/summary', scope), current);
  const interviews = useResource(request, interviewRead && pathWithQuery('/api/admin/interview/v1/workbench', period), current);
  const reports = useResource(request, reportRead && pathWithQuery('/api/admin/assessment/v1/workbench', period), reportRevision);
  const classHints = new Map(classes);
  const colleges = new Map();
  const recentInterviews = interviews.data && hasInterviews(interviews.data) ? interviews.data.recent : [];
  const recentReports = reports.data && hasReports(reports.data) ? reports.data.recent : [];
  for (const row of [...recentInterviews, ...recentReports]) {
    if (row.class_id) classHints.set(row.class_id, row.class_name || row.class_id);
    if (row.college_id) colleges.set(row.college_id, row.college_name || row.college_id);
  }
  return <section className="ops-workbench" aria-label="学校运营概览">
    <div className="nt-group"><h2>学校运营概览</h2>
      {(permissions.canUseRegistrationBook || accountRead || interviewRead || reportRead) && <button type="button" className="wb-clear" onClick={() => setVersion((n) => n + 1)}>刷新运营数据</button>}
    </div>
    {(accountRead || interviewRead || reportRead) && <Filters onApply={setFilter} classes={classHints} colleges={colleges} canReadRecords={interviewRead || reportRead} />}
    <div className="nt-grid"><Panel title="学生账号与归班" note="按当前可见学籍统计。账号和归班以当前状态为准。">
      <Result reply={accounts} label="学生账号概况" valid={(r) => counts(r, accountCounts)}>{(d) => <>
        <dl className="nt-metrics"><Metric label="学生账号" count={d.accounts} unit="个" /><Metric label="已启用未归班" count={d.unassigned_normal_accounts} unit="人" />
          <Metric label="待改密" count={d.must_change_password} unit="人" /></dl>
        <small>{d.scope === 'school' ? '本校管理范围' : '授权班级范围'} · 待改密包含首次登录和密码重置后的改密。</small>
        {d.accounts ? <p>已启用 {d.normal_accounts} 个，未启用或已停用 {d.disabled_accounts} 个。当前已归班 {d.assigned_accounts} 人，所有状态合计未归班 {d.unassigned_accounts} 人。</p> : <p>当前范围没有学生账号。</p>}
        {onNavigate && <button type="button" className="wb-link" onClick={() => onNavigate('nativeSchool', 'students')}>查看学生账号</button>}
      </>}</Result>
    </Panel><Panel title="登记开通待办" note="全校未归档且未开通的登记，含已撤销开户的记录；办理前需核验学生状态。">
      <Result reply={registrations} label="登记开通待办" valid={(r) => counts(r, ['pending_accounts']) && Array.isArray(r.items) && r.items.length <= maxRows}>{(d) => <>
        <dl className="nt-metrics"><Metric label="待开通" count={d.pending_accounts} unit="人" /></dl>
        {d.pending_accounts ? <><small>按学号列出前 5 人。此队列不随学院、班级和时段筛选。</small>
          <ul className="ops-pending">{d.items.map((r) => <li key={r.student_no}>{r.name} · {r.student_no}</li>)}</ul></> : <p>目前没有待开通的学生登记。</p>}
        {onNavigate && <button type="button" className="wb-link" onClick={() => onNavigate('nativeSchool', 'registrations')}>查看登记开通名单</button>}
      </>}</Result>
    </Panel></div>
    <div className="nt-grid"><Panel title="面试运营" note="按面试更新时间统计；待办及近期列表各最多展示 5 场。">
      <Result reply={interviews} label="学校面试统计" valid={hasInterviews}>{(data) =>
        <RecordPanel data={data} scope={recordScope} owner="interview" request={request} revision={current} onNavigate={onNavigate} permissions={permissions} />}
      </Result>
    </Panel><Panel title="报告与质检" note="按报告创建时间统计；展示当前状态与最新成绩，列表各最多 5 份。">
      {heldReport && <p role="status">正在查看报告版本，收起后恢复此区域的自动刷新。</p>}
      <Result reply={reports} label="学校报告统计" valid={hasReports}>{(data) =>
        <RecordPanel data={data} scope={recordScope} owner="assessment" request={request} revision={reportRevision} onNavigate={onNavigate} permissions={permissions}
          onReviewStart={() => setHeldReport(reportRevision)} onReviewEnd={releaseReport} />}
      </Result>
    </Panel></div>
  </section>;
}
