import assert from 'node:assert/strict';
import test from 'node:test';
import { createAnswerSubmission, postInterviewTurn } from './interviewTurn.js';

test('同一题重发相同文字时沿用提交编号', () => {
  const input = { questionId: 'q1', content: 'answer' };
  const previous = createAnswerSubmission(input);
  assert.equal(createAnswerSubmission({ ...input, previous }), previous);
  assert.notEqual(createAnswerSubmission({ ...input, previous, questionId: 'q2' }).submission_id, previous.submission_id);
});

test('RTC 回执丢失时重发相同的已保存回合', async () => {
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

test('过期题目直接重新同步进度', async () => {
  let calls = 0;
  await assert.rejects(postInterviewTurn(async () => {
    calls++;
    throw Object.assign(new Error('stale'), { status: 409 });
  }, {}), /stale/);
  assert.equal(calls, 1);
});

test('切题前先重试失败的 RTC 字幕，再写后续字幕', async () => {
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

test('成功回执不完整时，重试原回合后再更新进度', async () => {
  let attempts = 0;
  const saved = { answer: { id: 'a1' }, action: 'ask_follow_up' };
  const result = await postInterviewTurn(async () => ++attempts === 1 ? {} : saved,
    { submission_id: 's' }, response => response.answer?.id && response.action);
  assert.equal(result, saved);
  assert.equal(attempts, 2);
});
