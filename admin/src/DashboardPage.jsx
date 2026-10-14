import React, { useEffect, useMemo, useState } from 'react';
import { ArrowRight, ClipboardList, FileText, GraduationCap, Network, Search, ShieldCheck, UsersRound, X } from 'lucide-react';
import { dashboardModel, waitingLabel } from './dashboardModel.js';
import { recordFilterOptions } from './recordFilters.js';
import './dashboard.css';

function Panel({ title, subtitle, action, children, className = '' }) {
  return <section className={`wb-panel ${className}`}><header><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</header>{children}</section>;
}

export default function DashboardPage({ data, admin, onNavigate, onView }) {
  const [filters, setFilters] = useState({ college: '', className: '', period: 'all' });
  const [tab, setTab] = useState('review');
  const [lowFirst, setLowFirst] = useState(false);
  const [studentSearch, setStudentSearch] = useState('');
  const model = useMemo(() => dashboardModel(data, filters), [data, filters]);
  const options = [...(data.dashboardRoster || []), ...(data.interviews || []), ...(data.reports || [])];
  const canReports = Boolean(data.permissions?.canViewReports);
  const canInterviews = Boolean(data.permissions?.canViewInterviews);
  const canStudents = Boolean(data.permissions?.canManageStudents);
  const tabs = [
    ...(canReports ? [{ key: 'review', label: '报告复核', count: model.review.length, rows: model.review }] : []),
    ...(canStudents ? [{ key: 'pending', label: '账号激活', count: model.pending?.length, rows: model.pending || [] },
      { key: 'unassigned', label: '学生归班', count: model.unassigned?.length, rows: model.unassigned || [] }] : []),
    ...(canInterviews ? [{ key: 'running', label: '进行中训练', count: model.running.length, rows: model.running }] : []),
  ];
  const activeTab = tabs.find((item) => item.key === tab) || tabs[0];
  useEffect(() => { setStudentSearch(''); }, [tab]);
  const reviewPreset = (status = '', extra = {}) => ({ status, records: { ...model.scope, ...model.range, ...extra } });
  const go = (kind, row) => {
    if (kind === 'review') return row ? onView('report', row, model.review) : onNavigate('reports', reviewPreset('待复核'));
    if (kind === 'running') return row ? onView('interview', row, model.running) : onNavigate('interviews', reviewPreset('进行中'));
    if (kind === 'pending') return onNavigate('studentAccounts', { status: 'pending', records: model.scope, query: row?.studentNo || '' });
    return onNavigate('organization', { status: '未归班', records: model.scope, query: row?.studentNo || '' });
  };
  const metrics = [
    ...(canReports ? [{ key: 'review', title: '待复核报告', value: model.review.length, unit: '份', note: '进入报告复核', icon: ShieldCheck, tone: 'blue' }] : []),
    ...(canStudents ? [{ key: 'pending', title: '待激活学生', value: model.pending?.length, unit: '人', note: '检查资料并开通账号', icon: UsersRound, tone: 'amber' },
      { key: 'unassigned', title: '未归班学生', value: model.unassigned?.length, unit: '人', note: '完善学生归班', icon: Network, tone: 'purple' }] : []),
    ...(canInterviews ? [{ key: 'running', title: '进行中训练', value: model.running.length, unit: '场', note: '查看训练进度', icon: ClipboardList, tone: 'green' }] : []),
  ];
  const queue = [...(activeTab?.rows || [])].filter((row) => [row.name, row.candidate, row.studentNo, row.role].join(' ').toLowerCase().includes(studentSearch.trim().toLowerCase()));
  if (activeTab?.key === 'review' && lowFirst) queue.sort((a, b) => (Number(a.score) || 0) - (Number(b.score) || 0));
  const hasFilters = filters.college || filters.className || filters.period !== 'all';
  const initial = (name) => String(name || '学').replace(/^测试[·・]?/, '').slice(0, 1);
  return <div className="wb-page">
    <section className="wb-intro">
      <div><span className="wb-eyebrow">{admin?.role === 'super_admin' ? '全校管理视图' : '我的管理视图'}</span><h2>{admin?.name || '管理员'}，从待办开始</h2><p>处理学生账号与归班事项，跟进训练和报告复核。</p></div>
      <button className="wb-shortcut" type="button" onClick={() => onNavigate('guide')}>使用指引 <ArrowRight size={15} /></button>
    </section>

    <div className="wb-filter-bar">
      <label><span>学院</span><select aria-label="工作台学院" value={filters.college} onChange={(event) => setFilters({ ...filters, college: event.target.value, className: '' })}>
        <option value="">全部学院</option>{recordFilterOptions(options, 'college').map((item) => <option key={item}>{item}</option>)}
      </select></label>
      <label><span>班级</span><select aria-label="工作台班级" value={filters.className} onChange={(event) => setFilters({ ...filters, className: event.target.value })}>
        <option value="">全部班级</option>{recordFilterOptions(options, 'className', filters.college).map((item) => <option key={item}>{item}</option>)}
      </select></label>
      <label><span>训练统计时段</span><select aria-label="训练统计时段" value={filters.period} onChange={(event) => setFilters({ ...filters, period: event.target.value })}>
        <option value="all">全部时间</option><option value="today">今天</option><option value="7">近 7 天</option><option value="30">近 30 天</option>
      </select></label>
      {hasFilters && <button className="wb-clear" type="button" onClick={() => setFilters({ college: '', className: '', period: 'all' })}><X size={14} />重置筛选</button>}
      <span className="wb-scope-note">学生待办按当前名单统计，训练与报告按所选时段统计</span>
    </div>

    <section className="wb-metrics" aria-label="工作台关键指标">{metrics.map(({ key, title, value, unit, note, icon: Icon, tone }) => <button type="button" className={`wb-metric ${tone}`} key={key} onClick={() => go(key)} aria-label={`${title} ${value ?? '暂无'} ${unit}`}>
      <span className="wb-metric-top"><span>{title}</span><span className="wb-metric-icon"><Icon size={20} /></span></span>
      <span className="wb-metric-value"><strong>{value ?? '—'}</strong><small>{unit}</small></span>
      <span className="wb-metric-bottom">{note}<ArrowRight size={14} /></span>
    </button>)}</section>

    <div className={`wb-main-grid${!canReports ? ' single' : ''}`}>
      <Panel title="待处理事项" subtitle="按事项分类处理，减少遗漏" action={activeTab && <button type="button" className="wb-link" onClick={() => go(activeTab.key)}>查看全部 <ArrowRight size={14} /></button>}>
        <div className="wb-tabs" role="tablist" aria-label="待办分类">{tabs.map((item) => <button type="button" role="tab" aria-selected={item.key === activeTab?.key} aria-controls="workbench-queue" id={`wb-tab-${item.key}`} className={item.key === activeTab?.key ? 'active' : ''} key={item.key} onClick={() => setTab(item.key)}>{item.label}<span>{item.count ?? '—'}</span></button>)}</div>
        <div className="wb-queue-tools"><label><Search size={14} /><input type="search" aria-label="搜索待办" placeholder="搜索学生姓名、学号或岗位" value={studentSearch} onChange={(event) => setStudentSearch(event.target.value)} /></label>
          {activeTab?.key === 'review' && <select aria-label="待复核排序" value={lowFirst ? 'score' : 'time'} onChange={(event) => setLowFirst(event.target.value === 'score')}><option value="time">等待最久优先</option><option value="score">低分优先</option></select>}
        </div>
        <div className="wb-queue" id="workbench-queue" role="tabpanel" aria-labelledby={activeTab ? `wb-tab-${activeTab.key}` : undefined}>
          {!queue.length && <div className="wb-empty"><ShieldCheck size={28} /><strong>{studentSearch ? '没有符合搜索条件的待办' : '当前分类暂无待办'}</strong><span>{studentSearch ? '调整关键词后再试' : '可以切换分类查看其他事项'}</span></div>}
          {queue.slice(0, 5).map((row) => <button className="wb-task" type="button" key={row.id} onClick={() => go(activeTab.key, row)}>
            <span className={`wb-avatar ${activeTab.key}`}>{initial(row.name || row.candidate)}</span>
            <span className="wb-task-info"><strong>{row.name || row.candidate}</strong><small>{row.studentNo || row.role || '学生记录'}{row.college ? ` · ${row.college}` : ''}</small>
              {activeTab.key === 'pending' && <span className={`wb-task-note${row.missing?.length ? ' warning' : ''}`}>{row.missing?.length ? `待补充：${row.missing.join('、')}` : '资料齐全，可开通账号'}</span>}
              {activeTab.key === 'unassigned' && <span className="wb-task-note">已开通账号，待确认所属班级</span>}
            </span>
            <span className="wb-task-meta"><span>{activeTab.key === 'running' ? '进行中' : waitingLabel(row.createdAt)}</span>
              {activeTab.key === 'review' && <strong className={Number(row.score) < 70 ? 'low' : ''}>{row.score ?? '—'}<small> 分</small></strong>}
            </span><span className="wb-task-action">{activeTab.key === 'review' ? '查看报告' : activeTab.key === 'pending' ? '检查名单' : activeTab.key === 'unassigned' ? '处理归班' : '查看训练'}<ArrowRight size={14} /></span>
          </button>)}
          {queue.length > 5 && <button className="wb-more" type="button" onClick={() => go(activeTab.key)}>查看全部 {queue.length} 条{activeTab.label}事项 <ArrowRight size={14} /></button>}
        </div>
      </Panel>

      {canReports && <Panel title="学生训练表现" subtitle="综合报告成绩，了解当前训练情况" className="wb-performance">
        <div className="wb-score-hero"><div><span>平均报告成绩</span><strong>{model.average ?? '—'}<small>{model.average !== null ? '/100' : ''}</small></strong><p>{model.scored.length ? `来自 ${model.scored.length} 份有评分的报告` : '当前范围暂无评分报告'}</p></div><span className="wb-score-symbol"><GraduationCap size={36} /></span></div>
        <div className="wb-distribution">
          <div className="wb-stacked-bar" aria-label="报告分数分布">{model.scored.length ? model.bands.map((count, index) => <span className={`band-${index}`} key={index} style={{ width: `${count / model.scored.length * 100}%` }} />) : <span className="band-empty" />}</div>
          <div className="wb-band-legend">{['优秀 · 90 分及以上', '良好 · 80–89 分', '合格 · 70–79 分', '需关注 · 低于 70 分'].map((label, index) => <button type="button" key={label} onClick={() => onNavigate('reports', reviewPreset('', { scoreBand: ['90', '80', '70', 'low'][index] }))}><span><i className={`band-${index}`} />{label}</span><strong>{model.bands[index]}<small> 份</small></strong><ArrowRight size={13} /></button>)}</div>
        </div>
        <div className="wb-training-rates">
          {canStudents && canInterviews && <div><div><span>完成训练学生</span><strong>{model.completedStudents ?? '—'}<small> / {model.roster ? model.activeCount : '—'} 人</small></strong></div><div className="wb-rate-track"><span style={{width:`${model.participation || 0}%`}} /></div><p>当前范围已开通账号学生中，至少完成一次训练的比例 {model.participation === null ? '暂无' : `${model.participation}%`}</p></div>}
          {canInterviews && <div><div><span>训练完成率</span><strong>{model.completion === null ? '—' : `${model.completion}%`}</strong></div><div className="wb-rate-track green"><span style={{width:`${model.completion || 0}%`}} /></div><p>已完成训练 / 当前时段全部训练</p></div>}
        </div>
      </Panel>}
    </div>

    {canInterviews && <Panel title="最近训练" subtitle="查看最新训练记录，跟进学生进展" action={<button type="button" className="wb-link" onClick={() => onNavigate('interviews', reviewPreset())}>全部训练 <ArrowRight size={14} /></button>}>
      <div className="wb-recent-table"><table><thead><tr><th>学生</th><th>目标岗位</th><th>班级 / 学院</th><th>训练状态</th><th>更新时间</th><th>操作</th></tr></thead><tbody>
        {model.recent.slice(0, 5).map((row) => <tr key={row.id}><td><strong>{row.candidate}</strong><small>{row.studentNo || '未绑定学号'}</small></td><td>{row.role}</td><td><span>{row.className || '未填写班级'}</span><small>{row.college || '未填写学院'}</small></td><td><span className={`wb-training-status ${row.status === '已完成' ? 'complete' : row.status === '进行中' ? 'running' : ''}`}>{row.status}</span></td><td>{row.updatedAt}</td><td><button type="button" className="wb-link" onClick={() => onView('interview', row, model.recent)}>查看详情 <ArrowRight size={14} /></button></td></tr>)}
        {!model.recent.length && <tr><td colSpan={6}><div className="wb-empty"><FileText size={25} /><strong>当前时段暂无训练记录</strong><span>可以切换学院或时间范围查看</span></div></td></tr>}
      </tbody></table></div>
    </Panel>}
  </div>;
}
