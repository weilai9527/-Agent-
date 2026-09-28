import assert from 'node:assert/strict';
import test from 'node:test';
import { securityLogParams } from './securityLogQuery.js';

test('refresh without a start date omits empty filters and preserves page zero', () => {
  const params = securityLogParams({ offset: 0, since: '', until: '2026-09-28T06:00:00.000Z',
    event_type: '', request_id: '', actor_id: '' });
  assert.deepEqual(Object.fromEntries(params), {
    limit: '50', offset: '0', until: '2026-09-28T06:00:00.000Z',
  });
});

test('date range, identity filters and pagination survive URL encoding', () => {
  const query = { offset: 50, since: '2026-09-28T05:00:00+08:00',
    until: '2026-09-28T06:00:00.000Z', event_type: 'student.login', request_id: 'a'.repeat(32), actor_id: 'user-1' };
  const params = new URLSearchParams(securityLogParams(query).toString());
  for (const [key, value] of Object.entries(query)) assert.equal(params.get(key), String(value));
});
