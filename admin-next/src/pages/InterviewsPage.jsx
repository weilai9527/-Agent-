import { useApp } from '../context.jsx';
import { todayISO, averageScore } from '../selectors.js';
import { INTERVIEW_STATUS } from '../constants.js';
import { matchStudent, useList } from '../listHooks.js';
import PageHeading from '../components/PageHeading.jsx';
import ExportButton from '../components/ExportButton.jsx';
import FilterBar from '../components/FilterBar.jsx';
import Pagination from '../components/Pagination.jsx';
import InterviewTable, { interviewHeaders, interviewExportRows } from '../components/InterviewTable.jsx';
import { displayScore } from '../utils.js';

export default function InterviewsPage({ route }) {
  const { students, classes, colleges, interviews, plans } = useApp();
  const rows = interviews.filter(item => {
    const student = students.find(student => student.id === item.studentId);
    return student && matchStudent(student, { ...route.query, q: '' }, classes) &&
      (!route.query.q || [student.name, student.id, item.role, item.id].join(' ').toLowerCase().includes(route.query.q.toLowerCase())) &&
      (!route.query.status || item.status === route.query.status) &&
      (!route.query.plan || item.planId === route.query.plan) &&
      (!route.query.from || item.startedAt.slice(0, 10) >= route.query.from) &&
      (!route.query.to || item.startedAt.slice(0, 10) <= route.query.to);
  }).sort((a, b) => b.startedAt.localeCompare(a.startedAt));
  const list = useList(route, rows);
  return (
    <>
      <PageHeading title="面试记录" description="每行对应一场面试，独立查看报告和训练进度。">
        <ExportButton title="面试记录" columns={interviewHeaders} rows={interviewExportRows(rows, students, plans)} />
      </PageHeading>
      <div className="list-summary">
        <span>面试数 <strong>{rows.length}</strong></span>
        <span>已完成 <strong>{rows.filter(item => item.status === 'completed').length}</strong></span>
        <span>平均分 <strong>{displayScore(averageScore(rows))}</strong></span>
      </div>
      <section className="panel list-panel">
        <FilterBar query={route.query} onChange={list.change} colleges={colleges} classes={classes}>
          <select aria-label="筛选面试状态" value={route.query.status ?? ''} onChange={event => list.change({ status: event.target.value })}>
            <option value="">全部面试状态</option>
            {Object.entries(INTERVIEW_STATUS).map(([key, item]) => <option key={key} value={key}>{item.label}</option>)}
          </select>
          <select aria-label="筛选训练计划" value={route.query.plan ?? ''} onChange={event => list.change({ plan: event.target.value })}>
            <option value="">全部训练计划</option>
            {plans.map(plan => <option key={plan.id} value={plan.id}>{plan.name}</option>)}
          </select>
          <label>开始日期 <input type="date" aria-label="面试开始日期" value={route.query.from ?? ''} onChange={event => list.change({ from: event.target.value })} /></label>
          <label>结束日期 <input type="date" aria-label="面试结束日期" max={todayISO()} value={route.query.to ?? ''} onChange={event => list.change({ to: event.target.value })} /></label>
        </FilterBar>
        <InterviewTable interviews={list.pageRows} students={students} plans={plans} />
        <Pagination total={rows.length} page={list.page} onChange={list.setPage} />
      </section>
    </>
  );
}
