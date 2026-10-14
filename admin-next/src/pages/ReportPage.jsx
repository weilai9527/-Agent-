import { useApp } from '../context.jsx';
import { navigate } from '../router.js';
import { formatDate, displayScore } from '../utils.js';
import PageHeading from '../components/PageHeading.jsx';
import PanelHeader from '../components/PanelHeader.jsx';
import Badge from '../components/Badge.jsx';
import MissingPage from './MissingPage.jsx';

export default function ReportPage({ id }) {
  const { interviews, students, plans } = useApp();
  const interview = interviews.find(item => item.id === id);
  if (!interview) return <MissingPage />;
  const student = students.find(item => item.id === interview.studentId);
  return (
    <>
      <PageHeading title="面试报告" description={student.name + ' · ' + interview.role + ' · ' + formatDate(interview.startedAt)}>
        <Badge tone="warning">演示报告</Badge>
        <button className="secondary" onClick={() => navigate('/interviews')}>返回面试记录</button>
      </PageHeading>
      <p className="info-banner">以下为原型演示内容，能力评分与面试官反馈均为示例。</p>
      <section className="panel content-pad stack">
        <p>面试类型：{interview.type} · 所属计划：{plans.find(plan => plan.id === interview.planId)?.name ?? '自主训练'}</p>
        <button className="text-button self-start" onClick={() => navigate('/students/' + student.id)}>查看 {student.name} 的学生档案</button>
        {interview.status === 'in_progress' ? <div className="empty-state"><h2>面试进行中，完成后生成报告</h2></div> : <>
          <div className="report-score"><strong>{displayScore(interview.score)}</strong><Badge tone={interview.score < 70 ? 'warning' : 'success'}>{interview.grade}</Badge></div>
          <h2>能力维度</h2>
          <div className="dimension-list">
            {interview.dimensions.map(dimension => <div key={dimension.name}>
              <div><span>{dimension.name}</span><strong>{dimension.score} 分</strong></div>
              <div className="progress" role="meter" aria-label={dimension.name} aria-valuemin={0} aria-valuemax={100} aria-valuenow={dimension.score}>
                <i style={{ width: dimension.score + '%' }} />
              </div>
            </div>)}
          </div>
        </>}
      </section>
      {interview.status === 'completed' && <>
        <section className="section-gap">
          <h2>各面试官反馈</h2>
          <div className="feedback-grid section-gap">
            {interview.agentFeedback.map(agent => <article className="panel content-pad stack" key={agent.name}><h3>{agent.name}</h3><p>{agent.feedback}</p></article>)}
          </div>
        </section>
        <section className="panel section-gap">
          <PanelHeader title="总结与提升建议" />
          <div className="content-pad"><p>{interview.summary}</p><ul className="feature-list">{interview.suggestions.map(text => <li key={text}>{text}</li>)}</ul></div>
        </section>
      </>}
    </>
  );
}
