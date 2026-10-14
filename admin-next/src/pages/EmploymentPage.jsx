import { useApp } from '../context.jsx';
import { employmentSummary } from '../selectors.js';
import { EMPLOYMENT_STATUS } from '../constants.js';
import { matchStudent, useList } from '../listHooks.js';
import { navigate } from '../router.js';
import PageHeading from '../components/PageHeading.jsx';
import ExportButton from '../components/ExportButton.jsx';
import FilterBar from '../components/FilterBar.jsx';
import DataTable from '../components/DataTable.jsx';
import Pagination from '../components/Pagination.jsx';
import Badge from '../components/Badge.jsx';

export default function EmploymentPage({ route }) {
  const { students, classes, colleges } = useApp();
  const rows = students.filter(student => matchStudent(student, route.query, classes) && (!route.query.employment || student.employment === route.query.employment));
  const summary = employmentSummary(rows);
  const list = useList(route, rows);
  const columns = [
    { key: 'name', label: '学生' },
    { key: 'id', label: '学号' },
    { key: 'college', label: '学院', render: student => colleges.find(college => college.id === classes.find(item => item.id === student.classId)?.college)?.name },
    { key: 'class', label: '班级', render: student => classes.find(item => item.id === student.classId)?.name },
    { key: 'targetRole', label: '目标岗位' },
    { key: 'employment', label: '就业状态（示意）', render: student => <Badge tone={EMPLOYMENT_STATUS[student.employment].tone}>{EMPLOYMENT_STATUS[student.employment].label}</Badge> },
    { key: 'action', label: '操作', render: student => <button className="text-button" onClick={() => navigate('/students/' + student.id)}>查看学生</button> },
  ];
  return (
    <>
      <PageHeading title="就业统计" description="汇总与名单使用同一份演示学生数据，并随筛选同步变化。">
        <ExportButton title="就业示意名单" columns={columns.slice(0, -1).map(item => item.label)} rows={rows.map(student => [
          student.name, student.id, colleges.find(college => college.id === classes.find(item => item.id === student.classId)?.college)?.name,
          classes.find(item => item.id === student.classId)?.name, student.targetRole, EMPLOYMENT_STATUS[student.employment].label,
        ])} />
      </PageHeading>
      <p className="info-banner prominent" role="note">就业去向数据需对接学校就业系统，以下为示意</p>
      <div className="stats-grid">
        <div className="stat-card"><p>当前名单人数</p><strong className="stat-value">{summary.total}</strong></div>
        {Object.entries(EMPLOYMENT_STATUS).map(([key, item]) => <div className="stat-card" key={key}>
          <p>{item.label}</p><strong className="stat-value">{summary[key]}</strong>
        </div>)}
      </div>
      <section className="panel">
        <FilterBar query={route.query} onChange={list.change} colleges={colleges} classes={classes}>
          <select aria-label="筛选就业状态" value={route.query.employment ?? ''} onChange={event => list.change({ employment: event.target.value })}>
            <option value="">全部就业状态</option>
            {Object.entries(EMPLOYMENT_STATUS).map(([key, item]) => <option key={key} value={key}>{item.label}</option>)}
          </select>
        </FilterBar>
        <DataTable caption="就业示意名单" columns={columns} rows={list.pageRows} />
        <Pagination total={rows.length} page={list.page} onChange={list.setPage} />
      </section>
    </>
  );
}
