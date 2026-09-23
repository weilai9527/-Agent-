import test from 'node:test';
import assert from 'node:assert/strict';
import {
  abilitySampleStatus,
  hasInterviewerEvaluation,
  isAbilityReport,
  reportEvidenceNote,
  reportScore,
} from './reportPresentation.js';

test('report scores distinguish a real zero from missing evidence', () => {
  assert.equal(reportScore(0), 0);
  assert.equal(reportScore('0'), 0);
  for (const value of [null, undefined, '', 'invalid']) assert.equal(reportScore(value), null);
});
test('legacy default interviewer scores do not imply an evaluation', () => {
  assert.equal(hasInterviewerEvaluation({ score: 72, comment: '暂无关联单题评价，暂时无法形成可靠判断。' }), false);
  assert.equal(hasInterviewerEvaluation({ score: 0, comment: '本次回答没有回应问题。' }), true);
});
test('evidence caveats distinguish greetings, a single answer, and multiple answers', () => {
  assert.match(reportEvidenceNote([]), /没有已保存/);
  assert.match(reportEvidenceNote([{ answer: '你好！' }]), /缺少对题目的实质作答/);
  assert.match(reportEvidenceNote([{ answer: '你好，我使用 Docker 部署服务。' }]), /仅记录 1 条/);
  assert.match(reportEvidenceNote([{ answer: '项目介绍' }, { answer: '技术方案' }]), /2 条已保存/);
});

test('ability reports use the same successful-report definition as skill statistics', () => {
  assert.equal(isAbilityReport({ has_candidate_answer: 1, generation_status: 'succeeded', total_score: 0 }), true);
  assert.equal(isAbilityReport({ has_candidate_answer: 1, generation_status: 'degraded', total_score: 62 }), true);
  assert.equal(isAbilityReport({ has_candidate_answer: 1, generation_status: 'queued', total_score: 0 }), false);
  assert.equal(isAbilityReport({ has_candidate_answer: 1, generation_status: 'failed', total_score: 80 }), false);
  assert.equal(isAbilityReport({ has_candidate_answer: 0, generation_status: 'succeeded', total_score: 80 }), false);
});

test('sample status describes accumulation without claiming statistical confidence', () => {
  assert.deepEqual(abilitySampleStatus(0), { label: '暂无样本', tone: 'amber', progress: 0 });
  assert.equal(abilitySampleStatus(1).label, '已建立基线');
  assert.equal(abilitySampleStatus(3).label, '持续积累');
  assert.equal(abilitySampleStatus(5).label, '可查看趋势');
});
