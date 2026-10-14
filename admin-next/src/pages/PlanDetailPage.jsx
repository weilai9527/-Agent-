import { useApp } from '../context.jsx';
import { navigate } from '../router.js';
import { targetStudents, planProgress, planStatus, todayISO } from '../selectors.js';
import { canManagePlan } from '../roles.js';
import { PLAN_STATUS } from '../constants.js';
import { useList } from '../listHooks.js';
import PageHeading from '../components/PageHeading.jsx';
import PanelHeader from '../components/PanelHeader.jsx';
import Progress from '../components/Progress.jsx';
import Badge from '../components/Badge.jsx';
import DataTable from '../components/DataTable.jsx';
import Pagination from '../components/Pagination.jsx';
import ExportButton from '../components/ExportButton.jsx';
import MissingPage from './MissingPage.jsx';

export default function PlanDetailPage({ id, route }) {
  const { role, plans, students, classes, interviews, savePlan, notify } = useApp();
  const plan = plans.find(item => item.id === id);
  const targets = plan ? targetStudents(plan, students, classes) : [];
  const list = useList(route, targets);
  if (!plan) return <MissingPage />;
  const progress = planProgress(plan, students, interviews, classes);
  const status = PLAN_STATUS[planStatus(plan)];
  const completedIds = new Set(interviews.filter(item => item.planId === id && item.status === 'completed').map(item => item.studentId));
  const scopeLabel = plan.target.kind === 'all' ? '全校' : plan.target.kind === 'colleges' ? '所选学院' : '所选专业班级';
  const columns = [
    { key: 'name', label: '学生', render: student => <button className="text-button" onClick={() => navigate('/students/' + student.id)}>{student.name}</button> },
    { key: 'id', label: '学号' },
    { key: 'class', label: '班级', render: student => classes.find(item => item.id === student.classId)?.name },
    { key: 'status', label: '完成情况', render: student => <Badge tone={completedIds.has(student.id) ? 'success' : 'neutral'}>{completedIds.has(student.id) ? '已完成' : '未完成'}</Badge> },
  ];
  return (
    <>
      <PageHeading title={plan.name} description="进度与目标名单均按当前角色范围展示。">
        <Badge tone={status.tone}>{status.label}</Badge>
        <button className="secondary" onClick={() => navigate('/plans')}>返回计划列表</button>
        {plan.status === 'draft' && canManagePlan(role, plan) && <>
          <button className="secondary" onClick={() => navigate('/plans/' + id + '/edit')}>编辑草稿</button>
          <button className="primary" onClick={() => {
            if (plan.deadline < todayISO() || plan.deadline < plan.startDate) { notify('请先编辑草稿，更新有效的开始与截止日期。'); return; }
            savePlan({ ...plan, status: 'published' });
          }}>发布计划</button>
        </>}
      </PageHeading>
      <section className="panel content-pad stack">
        <h2>配置信息</h2>
        <dl className="config-grid">
          <div><dt>面试岗位</dt><dd>{plan.role}</dd></div>
          <div><dt>面试类型</dt><dd>{plan.type}</dd></div>
          <div><dt>目标范围</dt><dd>{scopeLabel} · 当前可见 {targets.length} 人</dd></div>
          <div><dt>可见目标班级</dt><dd>{classes.filter(item => targets.some(student => student.classId === item.id)).map(item => item.name).join('、') || '暂无目标学生'}</dd></div>
          <div><dt>难度</dt><dd>{plan.difficulty}</dd></div>
          <div><dt>面试官风格</dt><dd>{plan.style}</dd></div>
          <div><dt>开始日期</dt><dd>{plan.startDate}</dd></div>
          <div><dt>截止日期</dt><dd>{plan.deadline}</dd></div>
        </dl>
        <p>{plan.description || '暂无说明'}</p>
        <h2>完成进度</h2><Progress progress={progress} />
        <button className="text-button self-start" onClick={() => navigate('/interviews', { plan: id })}>查看关联面试记录</button>
      </section>
      <section className="panel section-gap">
        <PanelHeader title="目标学生">
          <ExportButton title="计划目标学生" columns={['学生', '学号', '班级', '完成情况']} rows={targets.map(student => [
            student.name, student.id, classes.find(item => item.id === student.classId)?.name, completedIds.has(student.id) ? '已完成' : '未完成',
          ])} />
        </PanelHeader>
        <DataTable caption="计划目标学生" columns={columns} rows={list.pageRows} />
        <Pagination total={targets.length} page={list.page} onChange={list.setPage} />
      </section>
    </>
  );
}
