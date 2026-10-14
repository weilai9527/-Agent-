import { useApp } from '../context.jsx';
import { navigate } from '../router.js';
import { needsCoaching, studentStats, aggregateStats } from '../selectors.js';
import { FOLLOW_UP_STATUS } from '../constants.js';
import { displayScore, formatDate } from '../utils.js';
import { matchStudent, useList } from '../listHooks.js';
import PageHeading from '../components/PageHeading.jsx';
import ExportButton from '../components/ExportButton.jsx';
import FilterBar from '../components/FilterBar.jsx';
import DataTable from '../components/DataTable.jsx';
import Pagination from '../components/Pagination.jsx';
import Badge from '../components/Badge.jsx';
import Avatar from '../components/Avatar.jsx';

export function coachingLabel(stats) {
  if (stats.followUp) return FOLLOW_UP_STATUS[stats.followUp.status];
  if (stats.coaching) return FOLLOW_UP_STATUS.pending;
  return { label: '无需辅导', tone: 'neutral' };
}
export default function StudentsPage({ route }) {
  const { students, interviews, followUps, classes, colleges } = useApp();
  const rows = students.filter(student => matchStudent(student, route.query, classes) &&
    (route.query.coaching !== 'needed' || needsCoaching(student, interviews, followUps))
  ).map(student => {
    const classEntity = classes.find(item => item.id === student.classId);
    const stats = studentStats(student, interviews, followUps);
    return { ...student, stats, className: classEntity?.name, collegeName: colleges.find(item => item.id === classEntity?.college)?.name };
  });
  const list = useList(route, rows);
  const summary = aggregateStats(rows, interviews, followUps);
  const columns = [
    { key: 'student', label: '学生', render: row => <div className="student-cell"><Avatar student={row} /><span><strong>{row.name}</strong><small>{row.id}</small></span></div> },
    { key: 'class', label: '学院班级', render: row => <div className="school-cell">{row.collegeName}<small>{row.className}</small></div> },
    { key: 'targetRole', label: '目标岗位' },
    { key: 'count', label: '训练次数', render: row => row.stats.count },
    { key: 'score', label: '最近得分', render: row => displayScore(row.stats.latestCompleted?.score) },
    { key: 'coaching', label: '辅导状态', render: row => <Badge tone={coachingLabel(row.stats).tone}>{coachingLabel(row.stats).label}</Badge> },
    { key: 'recent', label: '最近训练', render: row => formatDate(row.stats.latest?.startedAt) },
    { key: 'action', label: '操作', render: row => <button className="text-button" onClick={() => navigate('/students/' + row.id)}>查看详情</button> },
  ];
  return (
    <>
      <PageHeading title="学生名单" description="最近得分取最近一次已完成面试；所有数据均在当前角色范围内。">
        <ExportButton title="学生名单" columns={columns.slice(0, -1).map(item => item.label)} rows={rows.map(row => [
          row.name + '（' + row.id + '）', row.collegeName + ' / ' + row.className, row.targetRole, row.stats.count,
          displayScore(row.stats.latestCompleted?.score), coachingLabel(row.stats).label, formatDate(row.stats.latest?.startedAt),
        ])} />
      </PageHeading>
      <div className="list-summary">
        <span>学生数 <strong>{summary.students}</strong></span>
        <span>覆盖班级 <strong>{summary.classes}</strong></span>
        <span>待辅导 <strong className="orange-text">{summary.coaching}</strong></span>
      </div>
      <section className="panel list-panel">
        <FilterBar query={route.query} onChange={list.change} colleges={colleges} classes={classes}>
          <select aria-label="筛选辅导需求" value={route.query.coaching ?? ''} onChange={event => list.change({ coaching: event.target.value })}>
            <option value="">全部辅导状态</option><option value="needed">需要辅导</option>
          </select>
        </FilterBar>
        <DataTable caption="学生名单" columns={columns} rows={list.pageRows} />
        <Pagination total={rows.length} page={list.page} onChange={list.setPage} />
      </section>
    </>
  );
}
