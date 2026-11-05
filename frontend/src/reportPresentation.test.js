import test from 'node:test';
import assert from 'node:assert/strict';
import {
  abilitySampleStatus, comparableReports, coverageLabel, roundAssessment, visibleReportScore,
  hasInterviewerEvaluation,
  isAbilityReport,
  reportEvidenceNote,
  reportScore,
} from './reportPresentation.js';

test('报告分数区分真实零分和缺少依据', () => {
  assert.equal(reportScore(0), 0);
  assert.equal(reportScore('0'), 0);
  for (const value of [null, undefined, '', 'invalid']) assert.equal(reportScore(value), null);
});
test('旧默认面试官分数不代表已经评价', () => {
  assert.equal(hasInterviewerEvaluation({ score: 72, comment: '暂无关联单题评价，暂时无法形成可靠判断。' }), false);
  assert.equal(hasInterviewerEvaluation({ score: 0, comment: '本次回答没有回应问题。' }), true);
});
test('按问候、只有一道回答和多道回答提示可用依据', () => {
  assert.match(reportEvidenceNote([]), /没有已保存/);
  assert.match(reportEvidenceNote([{ answer: '你好！' }]), /缺少对题目的实质作答/);
  assert.match(reportEvidenceNote([{ answer: '你好，我使用 Docker 部署服务。' }]), /仅记录 1 条/);
  assert.match(reportEvidenceNote([{ answer: '项目介绍' }, { answer: '技术方案' }]), /2 条已保存/);
});

test('能力画像采用与后端统计相同的有效报告条件', () => {
  assert.equal(isAbilityReport({ has_candidate_answer: 1, generation_status: 'succeeded', total_score: 0 }), true);
  assert.equal(isAbilityReport({ has_candidate_answer: 1, generation_status: 'degraded', total_score: 62 }), false);
  assert.equal(isAbilityReport({ has_candidate_answer: 1, generation_status: 'queued', total_score: 0 }), false);
  assert.equal(isAbilityReport({ has_candidate_answer: 1, generation_status: 'failed', total_score: 80 }), false);
  assert.equal(isAbilityReport({ has_candidate_answer: 0, generation_status: 'succeeded', total_score: 80 }), false);
});

test('样本状态只说明积累进度', () => {
  assert.deepEqual(abilitySampleStatus(0), { label: '暂无样本', tone: 'amber', progress: 0 });
  assert.equal(abilitySampleStatus(1).label, '已建立基线');
  assert.equal(abilitySampleStatus(3).label, '持续积累');
  assert.equal(abilitySampleStatus(5).label, '可查看趋势');
});

test('新报告区分部分覆盖、零覆盖与历史未记录的覆盖数', () => {
  const report = { total_score: 0, answer_count: 2, scored_answer_count: 1, generation_status: 'degraded', has_candidate_answer: 1 };
  assert.equal(coverageLabel(report), '有效评分 1/2 题');
  assert.equal(visibleReportScore(report), 0);
  assert.equal(isAbilityReport(report), false);
  assert.equal(isAbilityReport({ ...report, scored_answer_count: 2 }), true);
  assert.equal(visibleReportScore({ ...report, scored_answer_count: 0 }), null);
  assert.equal(coverageLabel({ scored_answer_count: null, answer_count: null }), '');
  assert.equal(visibleReportScore({ generation_status: 'insufficient_evidence', total_score: 0 }), null);
});

test('时间线从 JSON 文本和对象读取评价状态、零分与引文', () => {
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

test('能力趋势按后端确定的样本和时间顺序显示', () => {
  const reports = ['a', 'b', 'c'].map((id) => ({ id }));
  assert.deepEqual(comparableReports(reports, { valid_report_ids: ['a', 'c'] }), [reports[2], reports[0]]);
  assert.deepEqual(comparableReports(reports, { valid_report_ids: [] }), []);
});
