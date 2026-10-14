import test from 'node:test';
import assert from 'node:assert/strict';
import { feedbackView, timelineView, reviewScore } from './reportReview.js';

test('serialized feedback and decoded feedback preserve full comments and valid zero scores', () => {
  const records = [{ agent_id: 'internal-id', agent_name: '专业面试官', agent_type: 'technical', score: 0,
    comment: '完整评价。'.repeat(250), strengths: ['表达清楚', '能说明个人职责'] }];
  assert.deepEqual(feedbackView(JSON.stringify(records)), feedbackView(records));
  assert.equal(feedbackView(records).items[0].comment, records[0].comment);
  assert.equal(feedbackView(records).items[0].score, 0);
  assert.equal(feedbackView(records).items[0].role, '专业能力');
  assert.equal(feedbackView(records).items[0].strengths, '表达清楚\n能说明个人职责');
  for (const value of [null, undefined, '', ' ', '未知', true, -1, 101]) assert.equal(reviewScore(value), null);
});

test('demo question/answer and current preview format render equivalent rounds without truncation', () => {
  const question = '请说明项目方案。';
  const answer = '完整回答。'.repeat(250);
  const demo = timelineView(JSON.stringify([{ question, answer, score: 56, strengths: '表达清楚', issues: '量化不足', suggestions: '补充成果' }]));
  const current = timelineView([{ sender_type: 'candidate', question_preview: question, answer_preview: answer,
    score: 56, strengths: '表达清楚', issues: '量化不足', suggestions: '补充成果' }]);
  assert.deepEqual(demo.items, current.items);
  assert.equal(current.items[0].answer, answer);
});

test('legacy alternating messages pair each answer with its preceding question', () => {
  const records = [
    { sender_type: 'agent', message_type: 'question', agent_name: '技术面试官', content_preview: '问题一' },
    { sender_type: 'system', content_preview: '不可见系统消息' },
    { sender_type: 'candidate', content_preview: '回答一', score: null },
    { sender_type: 'candidate', content_preview: '回答二', score: 0 },
  ];
  const items = timelineView(records).items;
  assert.equal(items.length, 2);
  assert.equal(items[0].question, '问题一');
  assert.equal(items[0].name, '技术面试官');
  assert.equal(items[0].score, null);
  assert.equal(items[1].question, '');
  assert.equal(items[1].score, 0);
});

test('empty and damaged data are handled, while legacy plain text remains readable', () => {
  assert.equal(feedbackView('旧报告的文字评价').text, '旧报告的文字评价');
  assert.equal(timelineView('[{"question":"未结束的数据"').invalid, true);
  for (const value of [null, '', '[]', [], '{}']) assert.equal(timelineView(value).items.length, 0);
});
