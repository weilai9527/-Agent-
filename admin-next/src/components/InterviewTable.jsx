import DataTable from './DataTable.jsx';
import Badge from './Badge.jsx';
import { INTERVIEW_STATUS } from '../constants.js';
import { displayScore, formatDate } from '../utils.js';
import { navigate } from '../router.js';

export const interviewHeaders = ['学生', '面试岗位', '类型', '所属计划', '得分', '状态', '时间'];
export function interviewExportRows(interviews, students, plans) {
  return interviews.map(item => {
    const student = students.find(student => student.id === item.studentId);
    return [student?.name + '（' + item.studentId + '）', item.role, item.type,
      plans.find(plan => plan.id === item.planId)?.name ?? '自主训练', displayScore(item.score),
      INTERVIEW_STATUS[item.status].label, formatDate(item.startedAt)];
  });
}
export default function InterviewTable({ interviews, students, plans }) {
  const columns = [
    { key: 'student', label: '学生', render: item => {
      const student = students.find(student => student.id === item.studentId);
      return <div className="student-cell"><span><button className="text-button" onClick={() => navigate('/students/' + item.studentId)}>{student?.name ?? '未知学生'}</button><small>{item.studentId}</small></span></div>;
    } },
    { key: 'role', label: '面试岗位' },
    { key: 'type', label: '类型' },
    { key: 'plan', label: '所属计划', render: item => plans.find(plan => plan.id === item.planId)?.name ?? '自主训练' },
    { key: 'score', label: '得分', render: item => displayScore(item.score) },
    { key: 'status', label: '状态', render: item => <Badge tone={INTERVIEW_STATUS[item.status].tone}>{INTERVIEW_STATUS[item.status].label}</Badge> },
    { key: 'startedAt', label: '时间', render: item => formatDate(item.startedAt) },
    { key: 'action', label: '操作', render: item => <button className="text-button" onClick={() => navigate('/interviews/' + item.id)}>查看{item.status === 'completed' ? '报告' : '进度'}</button> },
  ];
  return <DataTable caption="面试记录" columns={columns} rows={interviews} />;
}
