import assert from 'node:assert/strict';
import test from 'node:test';
import { claimRequestId, futureDeadline, keyedWrite, postJson, readError } from './trainingUi.js';

test('重试相同的提交时沿用原请求编号', () => {
  const draft = { question_id: 'q1', attempt_id: 'a1', max_attempts: 1 };
  const original = keyedWrite(null, draft);
  assert.equal(keyedWrite(original, { ...draft }).request_id, original.request_id);
  assert.notEqual(keyedWrite(original, { ...draft, max_attempts: 2 }).request_id, original.request_id);
});

test('相同已领取次数的两个标签页复用同一编号，下一次领取使用新编号', () => {
  assert.equal(claimRequestId(2), claimRequestId(2));
  assert.notEqual(claimRequestId(3), claimRequestId(2));
});

test('拒绝无效或过去的截止时间，保存绝对时间', () => {
  assert.throws(() => futureDeadline(''));
  assert.throws(() => futureDeadline('2001-02-03T04:00'));
  assert.equal(futureDeadline('2100-01-02T03:04:05+08:00'), '2100-01-01T19:04:05.000Z');
});

test('请求身份和凭据由网关决定', async () => {
  const input = { attempt_id: 'a', question_id: 'q', request_id: 'r' };
  const response = await postJson(async (path, init) => ({ path, init }), '/practice', input);
  assert.deepEqual(response, { path: '/practice', init: { method: 'POST', body: JSON.stringify(input) } });
  assert.equal(readError({ message: '请求失败', data: { detail: 'Deadline passed' } }), 'Deadline passed');
});
