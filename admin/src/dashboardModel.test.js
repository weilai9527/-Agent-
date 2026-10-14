import test from 'node:test';
import assert from 'node:assert/strict';
import { dashboardModel, dashboardRange } from './dashboardModel.js';

const now = new Date('2026-10-14T03:00:00Z');
const data = {
  permissions: { canViewReports: true, canViewInterviews: true },
  dashboardRoster: [
    { userId: 'a', studentNo: '1', college: '学院甲', activated: true, classAssigned: true },
    { userId: 'b', studentNo: '2', college: '学院甲', activated: true, classAssigned: false },
    { id: 'pending', college: '学院甲', activated: false, missing: ['辅导员'], createdAt: '2026-01-01' },
  ],
  interviews: [{ id: 'i1', userId: 'a', college: '学院甲', status: '已完成', updatedAt: '2026-10-14 01:00:00' },
    { id: 'i2', userId: 'a', college: '学院甲', status: '已完成', updatedAt: '2026-10-13 01:00:00' }],
  reports: [{ id: 'r1', college: '学院甲', score: 0, reviewStatus: '待复核', createdAt: '2026-10-14 01:00:00' },
    { id: 'r2', college: '学院甲', score: null, reviewStatus: '待复核', createdAt: '2026-10-13 01:00:00' }],
};

test('a student with multiple completed interviews only counts once', () => {
  const result = dashboardModel(data, { period: 'all' }, now);
  assert.equal(result.completedStudents, 1);
  assert.equal(result.participation, 50);
  assert.equal(result.completion, 100);
  assert.equal(result.average, 0);
  assert.deepEqual(result.bands, [0, 0, 0, 1]);
});

test('date range filters training but keeps historical student tasks', () => {
  const result = dashboardModel(data, { period: 'today', college: '学院甲' }, now);
  assert.equal(result.interviews.length, 1);
  assert.equal(result.reports.length, 1);
  assert.equal(result.pending.length, 1);
  assert.equal(result.pending[0].missing[0], '辅导员');
  assert.equal(result.unassigned.length, 1);
  const outside = dashboardModel(data, { period: 'all', college: '不存在的学院' }, now);
  assert.equal(outside.reports.length, 0);
  assert.equal(outside.average, null);
  assert.equal(outside.participation, null);
});

test('missing roster and missing permission never produce invented counts', () => {
  const result = dashboardModel({ ...data, dashboardRoster: null, permissions: {} }, { period: 'all' }, now);
  assert.equal(result.pending, null);
  assert.equal(result.unassigned, null);
  assert.equal(result.completedStudents, null);
  assert.equal(result.reports.length, 0);
  assert.equal(result.interviews.length, 0);
});

test('calendar ranges use Shanghai dates across UTC midnight', () => {
  assert.deepEqual(dashboardRange('7', new Date('2026-10-13T18:00:00Z')), { startDate: '2026-10-08', endDate: '2026-10-14' });
  assert.deepEqual(dashboardRange('all', now), {});
});
