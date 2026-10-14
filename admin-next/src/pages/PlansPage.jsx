import { useApp } from '../context.jsx';
import { navigate } from '../router.js';
import { planProgress, planStatus } from '../selectors.js';
import { PLAN_STATUS } from '../constants.js';
import { useList } from '../listHooks.js';
import PageHeading from '../components/PageHeading.jsx';
import ExportButton from '../components/ExportButton.jsx';
import FilterBar from '../components/FilterBar.jsx';
import Pagination from '../components/Pagination.jsx';
import Badge from '../components/Badge.jsx';
import Progress from '../components/Progress.jsx';

export default function PlansPage({ route }) {
  const { plans, students, interviews, classes } = useApp();
  const rows = plans.filter(plan => (!route.query.q || (plan.name + plan.role).includes(route.query.q)) &&
    (!route.query.status || planStatus(plan) === route.query.status)
  ).map(plan => ({ ...plan, progress: planProgress(plan, students, interviews, classes), displayStatus: PLAN_STATUS[planStatus(plan)] }));
  const list = useList(route, rows);
  return (
    <>
      <PageHeading title="训练计划" description="完成进度按关联面试去重计算，仅统计当前角色可见的目标学生。">
        <ExportButton title="训练计划" columns={['计划名称', '说明', '岗位', '类型', '状态', '开始日期', '截止日期', '目标人数', '完成人数', '完成比例']} rows={rows.map(plan => [
          plan.name, plan.description, plan.role, plan.type, plan.displayStatus.label, plan.startDate, plan.deadline,
          plan.progress.total, plan.progress.completed, plan.progress.percent + '%',
        ])} />
        <button className="primary" onClick={() => navigate('/plans/new')}>新建训练计划</button>
      </PageHeading>
      <section className="panel">
        <FilterBar query={route.query} onChange={list.change} placeholder="搜索计划名称或面试岗位">
          <select aria-label="筛选计划状态" value={route.query.status ?? ''} onChange={event => list.change({ status: event.target.value })}>
            <option value="">全部计划状态</option>
            {Object.entries(PLAN_STATUS).map(([key, item]) => <option value={key} key={key}>{item.label}</option>)}
          </select>
        </FilterBar>
      </section>
      <div className="training-grid section-gap">
        {list.pageRows.map(plan => <article className="panel" key={plan.id}>
          <div className="training-cover"><span>{plan.type} · {plan.role}</span></div>
          <div className="training-body">
            <Badge tone={plan.displayStatus.tone}>{plan.displayStatus.label}</Badge>
            <h2>{plan.name}</h2><p>{plan.description || '暂无说明'}</p>
            <p>{plan.startDate} 至 {plan.deadline}</p>
            <Progress progress={plan.progress} />
            <div className="training-card-footer"><button className="text-button" onClick={() => navigate('/plans/' + plan.id)}>查看计划详情 →</button></div>
          </div>
        </article>)}
      </div>
      {!rows.length && <p className="empty-state">暂无符合条件的计划</p>}
      <Pagination total={rows.length} page={list.page} onChange={list.setPage} />
    </>
  );
}
