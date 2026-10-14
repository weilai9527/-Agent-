import { useState } from 'react';
import { useApp } from '../context.jsx';
import { navigate } from '../router.js';
import { studentStats } from '../selectors.js';
import { FOLLOW_UP_STATUS, EMPLOYMENT_STATUS } from '../constants.js';
import { displayScore, formatDate } from '../utils.js';
import PageHeading from '../components/PageHeading.jsx';
import PanelHeader from '../components/PanelHeader.jsx';
import Badge from '../components/Badge.jsx';
import InterviewTable, { interviewHeaders, interviewExportRows } from '../components/InterviewTable.jsx';
import ExportButton from '../components/ExportButton.jsx';
import MissingPage from './MissingPage.jsx';

export default function StudentDetailPage({ id }) {
  const { students, classes, colleges, interviews, plans, followUps, saveFollowUp } = useApp();
  const student = students.find(item => item.id === id);
  const [status, setStatus] = useState('scheduled');
  const [note, setNote] = useState('');
  if (!student) return <MissingPage />;
  const classEntity = classes.find(item => item.id === student.classId);
  const stats = studentStats(student, interviews, followUps);
  const history = interviews.filter(item => item.studentId === id).sort((a, b) => b.startedAt.localeCompare(a.startedAt));
  const records = followUps.filter(item => item.studentId === id).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  return (
    <>
      <PageHeading title={student.name + '的学生档案'} description={student.id + ' · ' + colleges.find(item => item.id === classEntity.college)?.name + ' · ' + classEntity.name}>
        <button className="secondary" onClick={() => navigate('/students')}>返回学生名单</button>
      </PageHeading>
      <section className="panel content-pad stack">
        <h2>基本信息</h2>
        <p>目标岗位：{student.targetRole} · 年级：{classEntity.grade} 级 · 辅导员：{classEntity.counselor}</p>
        <p>就业状态（示意）：<Badge tone={EMPLOYMENT_STATUS[student.employment].tone}>{EMPLOYMENT_STATUS[student.employment].label}</Badge></p>
        <div className="list-summary">
          <span>训练次数 <strong>{stats.count}</strong></span>
          <span>已完成 <strong>{stats.completed}</strong></span>
          <span>最近得分 <strong>{displayScore(stats.latestCompleted?.score)}</strong></span>
          <span>平均分 <strong>{displayScore(stats.average)}</strong></span>
        </div>
      </section>
      <section className="panel section-gap">
        <PanelHeader title="面试历史" description="点击任意记录查看该场面试报告。">
          <ExportButton title="学生面试历史" columns={interviewHeaders} rows={interviewExportRows(history, students, plans)} />
        </PanelHeader>
        <InterviewTable interviews={history} students={students} plans={plans} />
      </section>
      <section className="panel section-gap">
        <PanelHeader title="辅导跟进记录" description={stats.coaching ? '最近已完成面试低于 70 分，尚无已完成跟进。' : '当前无需列入待辅导队列。'} />
        <div className="content-pad">
          <form className="follow-form" onSubmit={event => {
            event.preventDefault();
            if (saveFollowUp(id, status, note)) setNote('');
          }}>
            <label>跟进状态<select value={status} onChange={event => setStatus(event.target.value)}>
              {Object.entries(FOLLOW_UP_STATUS).map(([key, item]) => <option value={key} key={key}>{item.label}</option>)}
            </select></label>
            <label>跟进备注<textarea value={note} maxLength={1000} placeholder="记录辅导安排、完成情况或后续建议" onChange={event => setNote(event.target.value)} /></label>
            <button className="primary" type="submit">保存跟进</button>
          </form>
          <ol className="follow-history">
            {records.map(item => <li key={item.id}>
              <Badge tone={FOLLOW_UP_STATUS[item.status].tone}>{FOLLOW_UP_STATUS[item.status].label}</Badge>
              <time>{formatDate(item.updatedAt)}</time>
              <p>{item.note || '未填写备注'}</p>
            </li>)}
          </ol>
          {!records.length && <p className="muted">暂无跟进记录。</p>}
        </div>
      </section>
    </>
  );
}
