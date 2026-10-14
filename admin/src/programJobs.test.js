import test from 'node:test';
import assert from 'node:assert/strict';
import { programJobRows, programJobsChanged, programJobsPayload } from './programJobs.js';

test('archived mappings remain visible instead of silently disappearing', () => {
  const program = { jobs: [{ job_role_id: 'old', job_name: '原岗位', priority: 'optional' },
    { job_role_id: 'current', job_name: '旧名称', priority: 'recommended' }] };
  const rows = programJobRows(program, [{ id: 'current', name: '当前岗位' }]);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].available, false);
  assert.equal(rows[0].job.name, '原岗位');
  assert.equal(rows[1].available, true);
  assert.equal(rows[1].job.name, '当前岗位');
});

test('recommendation changes are meaningful, presentation order is not', () => {
  const saved = [{ jobRoleId: 'a', priority: 'optional' }, { jobRoleId: 'b', priority: 'recommended' }];
  assert.equal(programJobsChanged([...saved].reverse(), saved), false);
  assert.equal(programJobsChanged([{ ...saved[0], priority: 'recommended' }, saved[1]], saved), true);
  assert.equal(programJobsChanged([], saved), true);
  assert.deepEqual(programJobsPayload([{ ...saved[0], job: { name: '显示信息' }, available: true }]), [saved[0]]);
  assert.deepEqual(saved.map((row) => row.jobRoleId), ['a', 'b']);
});
