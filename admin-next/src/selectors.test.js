import test from 'node:test';
import assert from 'node:assert/strict';
import { students, interviews } from './data.js';
import { COACHING_THRESHOLD } from './constants.js';
import {
  latestInterview, needsCoaching, studentStats, classStats, planStatus,
  planProgress, targetStudents, aggregateStats, employmentSummary, todayISO,
} from './selectors.js';

const student = { id: 's1', classId: 'c1', employment: 'seeking' };
const classEntities = [{ id: 'c1', college: 'college1' }, { id: 'c2', college: 'college2' }];
const completed = (score, overrides = {}) => ({
  id: 'i1', studentId: 's1', status: 'completed', score, startedAt: '2026-10-14T10:00:00', planId: 'p1', ...overrides,
});

test('需辅导包含零分和阈值以下，排除阈值、空值、未训练与进行中', () => {
  assert.equal(needsCoaching(student, [completed(0)]), true);
  assert.equal(needsCoaching(student, [completed(COACHING_THRESHOLD - 1)]), true);
  assert.equal(needsCoaching(student, [completed(COACHING_THRESHOLD)]), false);
  assert.equal(needsCoaching(student, [completed(92)]), false);
  assert.equal(needsCoaching(student, [completed(null)]), false);
  assert.equal(needsCoaching(student, []), false);
  assert.equal(needsCoaching(student, [completed(null, { status: 'in_progress' })]), false);
});

test('最近得分仅使用最近已完成面试，后续进行中不掩盖低分', () => {
  const history = [
    completed(90, { id: 'old', startedAt: '2026-10-10T10:00:00' }),
    completed(60),
    completed(null, { id: 'live', startedAt: '2026-10-15T10:00:00', status: 'in_progress' }),
  ];
  const originalOrder = history.map(item => item.id);
  assert.equal(latestInterview(student, history).id, 'live');
  assert.equal(latestInterview(student, history, true).score, 60);
  assert.equal(needsCoaching(student, history), true);
  assert.deepEqual(history.map(item => item.id), originalOrder);
  assert.equal(needsCoaching(student, [...history, completed(80, { id: 'new', startedAt: '2026-10-16T10:00:00' })]), false);
});

test('已安排仍需辅导，已完成跟进排除，其他学生记录不影响', () => {
  const history = [completed(60)];
  assert.equal(needsCoaching(student, history, [{ studentId: 's1', status: 'pending' }]), true);
  assert.equal(needsCoaching(student, history, [{ studentId: 's1', status: 'scheduled' }]), true);
  assert.equal(needsCoaching(student, history, [{ studentId: 's1', status: 'done' }]), false);
  assert.equal(needsCoaching(student, history, [{ studentId: 's2', status: 'done' }]), true);
});

test('学生与班级汇总计入零分，平均分排除未完成，空班级无平均分', () => {
  const history = [completed(0), completed(100, { id: 'i2' }), completed(null, { id: 'i3', status: 'in_progress' })];
  const stats = studentStats(student, history);
  assert.equal(stats.count, 3);
  assert.equal(stats.completed, 2);
  assert.equal(stats.average, 50);
  assert.equal(classStats('c1', [student], history).completed, 2);
  assert.equal(classStats('c2', [student], history).average, null);
});

test('计划状态以草稿优先，开始日和截止日均属进行中', () => {
  const plan = { status: 'published', startDate: '2026-10-10', deadline: '2026-10-14' };
  assert.equal(planStatus(plan, '2026-10-09'), 'upcoming');
  assert.equal(planStatus(plan, '2026-10-10'), 'active');
  assert.equal(planStatus(plan, '2026-10-14'), 'active');
  assert.equal(planStatus(plan, '2026-10-15'), 'ended');
  assert.equal(planStatus({ ...plan, status: 'draft' }, '2026-10-20'), 'draft');
});

test('计划进度按目标学生去重，排除别的计划、非目标和进行中', () => {
  const plan = { id: 'p1', target: { kind: 'classes', ids: ['c1'] } };
  const roster = [student, { id: 's2', classId: 'c1' }, { id: 's3', classId: 'c2' }];
  const history = [
    completed(0), completed(80, { id: 'i2' }),
    completed(90, { studentId: 's3' }),
    completed(90, { studentId: 's2', planId: 'other' }),
    completed(null, { studentId: 's2', status: 'in_progress' }),
  ];
  assert.deepEqual(planProgress(plan, roster, history, classEntities), { total: 2, completed: 1, percent: 50 });
  assert.deepEqual(planProgress(plan, [], history, classEntities), { total: 0, completed: 0, percent: 0 });
  assert.deepEqual(targetStudents({ target: { kind: 'colleges', ids: ['college2'] } }, roster, classEntities).map(item => item.id), ['s3']);
  assert.equal(targetStudents({ target: { kind: 'all', ids: [] } }, roster, classEntities).length, 3);
});

test('本周统计以本地周一为起点，汇总不包含范围外学生', () => {
  const history = [
    completed(60, { startedAt: '2026-10-11T12:00:00' }),
    completed(80, { id: 'i2', startedAt: '2026-10-12T00:00:00' }),
    completed(90, { studentId: 's2', startedAt: '2026-10-13T10:00:00' }),
  ];
  const stats = aggregateStats([student], history, [], new Date(2026, 9, 14));
  assert.equal(stats.weeklyCompleted, 1);
  assert.equal(stats.average, 70);
  assert.equal(todayISO(new Date(2026, 0, 2)), '2026-01-02');
});

test('演示实体一致：每人最多四场、总计二十场、学生无面试状态和分数', () => {
  assert.equal(interviews.length, 20);
  for (const item of students) {
    assert.equal('score' in item, false);
    assert.equal('status' in item, false);
    assert.ok(interviews.filter(interview => interview.studentId === item.id).length <= 4);
  }
  assert.ok(students.some(item => !interviews.some(interview => interview.studentId === item.id)));
  const summary = employmentSummary(students);
  assert.equal(summary.total, students.length);
  assert.equal(summary.signed + summary.seeking + summary.studying, students.length);
});
