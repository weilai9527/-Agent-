import test from 'node:test';
import assert from 'node:assert/strict';
import { matchesRecordFilters, recordFilterOptions } from './recordFilters.js';

test('score ranges are disjoint and do not treat missing scores as zero', () => {
  for (const [score, band] of [[0, 'low'], [69, 'low'], [70, '70'], [79, '70'], [80, '80'], [89, '80'], [90, '90'], [100, '90']]) {
    assert.deepEqual(['low', '70', '80', '90'].filter((scoreBand) => matchesRecordFilters({ score }, { scoreBand })), [band]);
  }
  for (const score of [null, undefined, '', ' ', '无', -1, 101]) {
    assert.equal(matchesRecordFilters({ score }, { scoreBand: 'low' }), false);
  }
});

test('combined filters include the whole final day and reject missing dates', () => {
  const row = { college: '计算机学院', className: '一班', role: '前端工程师', score: 69, createdAt: '2026-10-13 23:59:59' };
  const filters = { college: '计算机学院', className: '一班', scoreBand: 'low', startDate: '2026-10-13', endDate: '2026-10-13' };
  assert.equal(matchesRecordFilters(row, filters, 'createdAt'), true);
  assert.equal(matchesRecordFilters({ ...row, college: '管理学院' }, filters, 'createdAt'), false);
  assert.equal(matchesRecordFilters({ ...row, createdAt: '2026-10-14 00:00:00' }, filters, 'createdAt'), false);
  assert.equal(matchesRecordFilters({ ...row, createdAt: null }, filters, 'createdAt'), false);
  assert.equal(matchesRecordFilters(row, { startDate: '2026-10-14', endDate: '2026-10-13' }, 'createdAt'), false);
  assert.equal(matchesRecordFilters(row, {}, 'createdAt'), true);
});

test('class options follow the selected college without depending on report status or score', () => {
  const rows = [{ college: '计算机学院', className: '软件班' }, { college: '计算机学院', className: '软件班' },
    { college: '管理学院', className: '管理班' }, { college: '计算机学院', className: '' }];
  assert.deepEqual(recordFilterOptions(rows, 'className', '计算机学院'), ['软件班']);
  assert.equal(recordFilterOptions(rows, 'className').length, 2);
});
