import assert from 'node:assert/strict';
import test from 'node:test';
import { createAnswerSubmission, postInterviewTurn } from './interviewTurn.js';

test('retrying the same text reuses its submission only on the original question', () => {
  const input = { questionId: 'q1', content: 'answer' };
  const previous = createAnswerSubmission(input);
  assert.equal(createAnswerSubmission({ ...input, previous }), previous);
  assert.notEqual(createAnswerSubmission({ ...input, previous, questionId: 'q2' }).submission_id, previous.submission_id);
});

test('a lost RTC response retries the identical persisted turn', async () => {
  const submission = createAnswerSubmission({ questionId: 'q1', content: 'voice answer', sourceRef: 'caption-1' });
  const attempts = [];
  const result = await postInterviewTurn(async body => {
    attempts.push(body);
    if (attempts.length === 1) throw new TypeError('network');
    return { duplicate: true };
  }, submission);
  assert.deepEqual(result, { duplicate: true });
  assert.deepEqual(attempts, [submission, submission]);
  assert.equal(submission.submission_id, 'caption-1');
});

test('a stale question goes straight to reconciliation', async () => {
  let calls = 0;
  await assert.rejects(postInterviewTurn(async () => {
    calls++;
    throw Object.assign(new Error('stale'), { status: 409 });
  }, {}), /stale/);
  assert.equal(calls, 1);
});

test('a failed RTC write retries before subsequent captions on transition', async () => {
  const { createRtcWriteQueue } = await import('./interviewTurn.js');
  const events = [];
  const queue = createRtcWriteQueue(error => events.push(error.message));
  let retry = false;
  queue.enqueue(async () => {
    events.push('answer');
    if (!retry) throw new Error('offline');
  });
  queue.enqueue(async () => events.push('question'));
  await assert.rejects(queue.drain(), /offline/);
  retry = true;
  await queue.drain();
  assert.deepEqual(events, ['answer', 'offline', 'answer', 'offline', 'answer', 'question']);
});

test('a truncated success response retries the same turn before updating progress', async () => {
  let attempts = 0;
  const saved = { answer: { id: 'a1' }, action: 'ask_follow_up' };
  const result = await postInterviewTurn(async () => ++attempts === 1 ? {} : saved,
    { submission_id: 's' }, response => response.answer?.id && response.action);
  assert.equal(result, saved);
  assert.equal(attempts, 2);
});

test('a queued turn polls with the same payload and validates only its final result', async () => {
  const submission = { question_id: 'q', submission_id: 's', content: 'answer' };
  const attempts = [], delays = [];
  let validations = 0;
  const result = await postInterviewTurn(async body => {
    attempts.push(body);
    return attempts.length < 3 ? { processing: true, retry_after_ms: 500 } : { answer: { id: 'a' } };
  }, submission, response => { validations++; return response.answer?.id; }, { delay: async ms => delays.push(ms) });
  assert.equal(result.answer.id, 'a');
  assert.deepEqual(attempts, [submission, submission, submission]);
  assert.deepEqual(delays, [500, 500]);
  assert.equal(validations, 1);
});

test('a queued turn eventually reports a retryable timeout', async () => {
  let calls = 0;
  await assert.rejects(postInterviewTurn(async () => { calls++; return { processing: true }; }, {}, undefined,
    { maxPendingAttempts: 1, delay: async () => {} }), error => error.status === 503);
  assert.equal(calls, 4);
});
