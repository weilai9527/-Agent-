import test from 'node:test';
import assert from 'node:assert/strict';
import {
  abilitySampleStatus, comparableReports, coverageLabel, roundAssessment, visibleReportScore,
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
  assert.equal(isAbilityReport({ has_candidate_answer: 1, generation_status: 'degraded', total_score: 62 }), false);
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

test('new reports distinguish partial and zero coverage from unrecorded historical coverage', () => {
  const report = { total_score: 0, answer_count: 2, scored_answer_count: 1, generation_status: 'degraded', has_candidate_answer: 1 };
  assert.equal(coverageLabel(report), '有效评分 1/2 题');
  assert.equal(visibleReportScore(report), 0);
  assert.equal(isAbilityReport(report), false);
  assert.equal(isAbilityReport({ ...report, scored_answer_count: 2 }), true);
  assert.equal(visibleReportScore({ ...report, scored_answer_count: 0 }), null);
  assert.equal(coverageLabel({ scored_answer_count: null, answer_count: null }), '');
  assert.equal(visibleReportScore({ generation_status: 'insufficient_evidence', total_score: 0 }), null);
});

test('timeline resolves statuses, zero and quoted evidence from JSON text or object', () => {
  const item = { message_id: 'a', score: 0, dimension_evidence: { technical_depth: '我测量了响应时间', role_fit: null } };
  assert.deepEqual(roundAssessment(item).evidence, [['technical_depth', '我测量了响应时间']]);
  assert.deepEqual(roundAssessment(item), roundAssessment({ ...item, dimension_evidence: JSON.stringify(item.dimension_evidence) }));
  assert.equal(roundAssessment(item).scoreLabel, '0 分');
  for (const status of ['pending_retry', 'degraded']) {
    const result = roundAssessment({ ...item, generation_status: status });
    assert.equal(result.score, null);
    assert.equal(result.retryId, 'a');
  }
  assert.equal(roundAssessment({ score: null }).scoreLabel, '未评分');
});

test('ability trend uses the backend cohort in the same chronology', () => {
  const reports = ['a', 'b', 'c'].map((id) => ({ id }));
  assert.deepEqual(comparableReports(reports, { valid_report_ids: ['a', 'c'] }), [reports[2], reports[0]]);
  assert.deepEqual(comparableReports(reports, { valid_report_ids: [] }), []);
});
