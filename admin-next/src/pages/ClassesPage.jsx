import { useApp } from '../context.jsx';
import { classStats } from '../selectors.js';
import { navigate } from '../router.js';
import { displayScore } from '../utils.js';
import { useList } from '../listHooks.js';
import PageHeading from '../components/PageHeading.jsx';
import ExportButton from '../components/ExportButton.jsx';
import FilterBar from '../components/FilterBar.jsx';
import Pagination from '../components/Pagination.jsx';

export default function ClassesPage({ route }) {
  const { students, classes, colleges, interviews, followUps } = useApp();
  const rows = classes.filter(item => (!route.query.college || item.college === route.query.college) &&
    (!route.query.q || (item.name + item.counselor).includes(route.query.q))
  ).map(item => ({ ...item, collegeName: colleges.find(college => college.id === item.college)?.name, stats: classStats(item, students, interviews, followUps) }));
  const list = useList(route, rows);
  return (
    <>
      <PageHeading title="班级" description="按班级查看真实计算的训练进度与辅导需求。">
        <ExportButton title="班级" columns={['班级', '学院', '辅导员', '年级', '学生数', '完成面试数', '平均分', '待辅导人数']} rows={rows.map(item => [
          item.name, item.collegeName, item.counselor, item.grade, item.stats.students, item.stats.completed, displayScore(item.stats.average), item.stats.coaching,
        ])} />
      </PageHeading>
      <section className="panel section-gap">
        <FilterBar query={route.query} onChange={list.change} colleges={colleges} placeholder="搜索班级或辅导员" />
      </section>
      <div className="class-grid section-gap">
        {list.pageRows.map(item => <article className="panel class-card" key={item.id}>
          <h2>{item.name}</h2><p>{item.collegeName} · {item.grade} 级</p><p>辅导员：{item.counselor}</p>
          <div className="class-metrics">
            <div><strong>{item.stats.students}</strong><small>学生数</small></div>
            <div><strong>{item.stats.completed}</strong><small>完成面试</small></div>
          </div>
          <div className="class-metrics">
            <div><strong>{displayScore(item.stats.average)}</strong><small>平均分</small></div>
            <div><strong className="orange-text">{item.stats.coaching}</strong><small>待辅导</small></div>
          </div>
          <button className="class-link" onClick={() => navigate('/students', { class: item.id })}>查看学生名单 →</button>
        </article>)}
      </div>
      {!rows.length && <p className="empty-state">暂无符合条件的班级</p>}
      <Pagination total={rows.length} page={list.page} onChange={list.setPage} />
    </>
  );
}
