import { useApp } from '../context.jsx';
import { navigate } from '../router.js';
import { aggregateStats, needsCoaching, studentStats, planProgress, planStatus, todayISO } from '../selectors.js';
import { FOLLOW_UP_STATUS } from '../constants.js';
import { displayScore, formatDate } from '../utils.js';
import PageHeading from '../components/PageHeading.jsx';
import PanelHeader from '../components/PanelHeader.jsx';
import Badge from '../components/Badge.jsx';
import Progress from '../components/Progress.jsx';
import Avatar from '../components/Avatar.jsx';

export default function OverviewPage() {
  const { role, students, interviews, followUps, plans, classes, saveFollowUp } = useApp();
  const stats = aggregateStats(students, interviews, followUps);
  const coaching = students.filter(student => needsCoaching(student, interviews, followUps));
  const activePlans = plans.filter(plan => planStatus(plan) === 'active');
  const recent = interviews.filter(item => item.status === 'completed').sort((a, b) => b.startedAt.localeCompare(a.startedAt)).slice(0, 5);
  const monday = new Date();
  monday.setDate(monday.getDate() - (monday.getDay() + 6) % 7);
  const sunday = new Date(monday);
  sunday.setDate(sunday.getDate() + 6);
  const metrics = [
    { label: '学生数', value: stats.students, path: '/students', query: {} },
    { label: '本周完成面试', value: stats.weeklyCompleted, path: '/interviews', query: { status: 'completed', from: todayISO(monday), to: todayISO(sunday) } },
    { label: '平均分', value: displayScore(stats.average), path: '/interviews', query: { status: 'completed' } },
    { label: '待辅导人数', value: stats.coaching, path: '/students', query: { coaching: 'needed' } },
  ];
  return (
    <>
      <PageHeading title="工作台" description={role.scopeLabel + ' · ' + new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' })}>
        <button className="primary" onClick={() => navigate('/plans/new')}>新建训练计划</button>
      </PageHeading>
      <div className="overview-numbers">
        {metrics.map(metric => <button key={metric.label} onClick={() => navigate(metric.path, metric.query)}>
          <span>{metric.label} →</span><strong>{metric.value}</strong>
        </button>)}
      </div>
      <div className="task-layout">
        <section className="panel">
          <PanelHeader title="待辅导队列" description="最近已完成面试低于 70 分且尚无已完成跟进的学生。" />
          {coaching.map(student => {
            const stats = studentStats(student, interviews, followUps);
            const follow = FOLLOW_UP_STATUS[stats.followUp?.status ?? 'pending'];
            return <div className="coaching-row" key={student.id}>
              <Avatar student={student} />
              <button className="student-link" onClick={() => navigate('/students/' + student.id)}>
                <strong>{student.name}</strong><small>{classes.find(item => item.id === student.classId)?.name}</small>
              </button>
              <strong className="orange-text">{displayScore(stats.latestCompleted?.score)}</strong>
              <Badge tone={follow.tone}>{follow.label}</Badge>
              {stats.followUp?.status !== 'scheduled' && <button className="text-button" onClick={() => saveFollowUp(student.id, 'scheduled', '已从工作台安排辅导，具体时间待确认。')}>标记已安排</button>}
            </div>;
          })}
          {!coaching.length && <p className="empty-state">当前范围暂无待辅导学生</p>}
        </section>
        <aside className="task-rail">
          <section className="panel">
            <PanelHeader title="进行中的训练计划" />
            {activePlans.map(plan => <button className="running-plan" key={plan.id} onClick={() => navigate('/plans/' + plan.id)}>
              <strong>{plan.name}</strong><small>截止日期：{plan.deadline}</small>
              <Progress progress={planProgress(plan, students, interviews, classes)} />
            </button>)}
            {!activePlans.length && <p className="empty-state">暂无进行中的计划</p>}
          </section>
          <section className="panel">
            <PanelHeader title="最近完成的面试" description="最近 5 场面试" />
            {recent.map(item => <button className="recent-row" key={item.id} onClick={() => navigate('/interviews/' + item.id)}>
              <span><strong>{students.find(student => student.id === item.studentId)?.name} · {item.type}</strong><small>{formatDate(item.startedAt)}</small></span>
              <span>{displayScore(item.score)}</span>
            </button>)}
            {!recent.length && <p className="empty-state">暂无已完成的面试</p>}
          </section>
        </aside>
      </div>
    </>
  );
}
