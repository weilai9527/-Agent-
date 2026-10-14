import { COACHING_THRESHOLD } from './constants.js';
import { classes as defaultClasses } from './data.js';

export function todayISO(now = new Date()) {
  return [now.getFullYear(), String(now.getMonth() + 1).padStart(2, '0'), String(now.getDate()).padStart(2, '0')].join('-');
}
export function latestInterview(student, interviews, completedOnly = false) {
  const id = typeof student === 'string' ? student : student.id;
  return interviews.filter(item => item.studentId === id && (!completedOnly || item.status === 'completed'))
    .sort((a, b) => b.startedAt.localeCompare(a.startedAt) || b.id.localeCompare(a.id))[0] ?? null;
}
export function latestFollowUp(student, followUps) {
  const id = typeof student === 'string' ? student : student.id;
  return followUps.filter(item => item.studentId === id)
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))[0] ?? null;
}
export function needsCoaching(student, interviews, followUps = []) {
  const latest = latestInterview(student, interviews, true);
  return latest?.score != null && latest.score < COACHING_THRESHOLD &&
    !followUps.some(item => item.studentId === student.id && item.status === 'done');
}
export function averageScore(interviews) {
  const completed = interviews.filter(item => item.status === 'completed' && Number.isFinite(item.score));
  return completed.length ? Math.round(completed.reduce((sum, item) => sum + item.score, 0) / completed.length * 10) / 10 : null;
}
export function studentStats(student, interviews, followUps = []) {
  const history = interviews.filter(item => item.studentId === student.id);
  return {
    count: history.length,
    completed: history.filter(item => item.status === 'completed').length,
    average: averageScore(history),
    latest: latestInterview(student, history),
    latestCompleted: latestInterview(student, history, true),
    coaching: needsCoaching(student, history, followUps),
    followUp: latestFollowUp(student, followUps),
  };
}
export function aggregateStats(students, interviews, followUps = [], now = new Date()) {
  const ids = new Set(students.map(student => student.id));
  const scoped = interviews.filter(item => ids.has(item.studentId));
  const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  monday.setDate(monday.getDate() - (monday.getDay() + 6) % 7);
  const end = new Date(monday);
  end.setDate(end.getDate() + 7);
  return {
    students: students.length,
    classes: new Set(students.map(student => student.classId)).size,
    interviews: scoped.length,
    completed: scoped.filter(item => item.status === 'completed').length,
    weeklyCompleted: scoped.filter(item => item.status === 'completed' && new Date(item.startedAt) >= monday && new Date(item.startedAt) < end).length,
    average: averageScore(scoped),
    coaching: students.filter(student => needsCoaching(student, scoped, followUps)).length,
  };
}
export function classStats(classEntity, students, interviews, followUps = []) {
  const id = typeof classEntity === 'string' ? classEntity : classEntity.id;
  return aggregateStats(students.filter(student => student.classId === id), interviews, followUps);
}
export function planStatus(plan, today = todayISO()) {
  if (plan.status === 'draft') return 'draft';
  if (plan.deadline < today) return 'ended';
  if (plan.startDate > today) return 'upcoming';
  return 'active';
}
export function targetStudents(plan, students, classes = defaultClasses) {
  const ids = new Set(plan.target.ids);
  return students.filter(student => plan.target.kind === 'all' ||
    (plan.target.kind === 'classes' && ids.has(student.classId)) ||
    (plan.target.kind === 'colleges' && ids.has(classes.find(item => item.id === student.classId)?.college)));
}
export function planProgress(plan, students, interviews, classes = defaultClasses) {
  const targets = targetStudents(plan, students, classes);
  const targetIds = new Set(targets.map(student => student.id));
  const completedIds = new Set(interviews.filter(item =>
    item.planId === plan.id && item.status === 'completed' && targetIds.has(item.studentId)
  ).map(item => item.studentId));
  return { total: targets.length, completed: completedIds.size, percent: targets.length ? Math.round(completedIds.size / targets.length * 100) : 0 };
}
export function employmentSummary(students) {
  return students.reduce((result, student) => {
    result[student.employment] = (result[student.employment] ?? 0) + 1;
    result.total += 1;
    return result;
  }, { total: 0, seeking: 0, signed: 0, studying: 0 });
}
