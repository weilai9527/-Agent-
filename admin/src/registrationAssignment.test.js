import test from 'node:test';
import assert from 'node:assert/strict';
import { registrationAssignmentCounts, registrationAssignmentLabel } from './registrationAssignment.js';

test('missing assignment status is unknown, not unassigned', () => {
  const registrations = Array.from({ length: 1404 }, () => ({ activated: true }));
  assert.deepEqual(registrationAssignmentCounts(registrations), { unassigned: 0, unknown: 1404 });
  assert.equal(registrationAssignmentLabel(registrations[0]), '待核对');
  assert.equal(registrationAssignmentLabel({ activated: true, classAssigned: null }), '待核对');
});

test('only confirmed unassigned active accounts count toward the warning', () => {
  const registrations = [
    { activated: true, classAssigned: true },
    { activated: true, classAssigned: false },
    { activated: true },
    { activated: false, classAssigned: false },
  ];
  assert.deepEqual(registrationAssignmentCounts(registrations), { unassigned: 1, unknown: 1 });
  assert.deepEqual(registrations.map(registrationAssignmentLabel), ['已归班', '未归班', '待核对', '-']);
});
