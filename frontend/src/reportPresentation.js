export function reportScore(value) {
  if (!['string', 'number'].includes(typeof value) || String(value).trim() === '') return null;
  const score = Number(value);
  return Number.isFinite(score) && score >= 0 && score <= 100 ? score : null;
}

export function hasInterviewerEvaluation(item) {
  return reportScore(item.score) !== null && !/暂无关联单题评价|未记录到候选人回答|暂无评价/.test(item.comment || '');
}

export function reportEvidenceNote(timeline) {
  if (!timeline.length) return '本场没有已保存的回答，暂不足以形成能力判断。';
  const greetingsOnly = timeline.every((item) => /^(你好|您好|hello|hi|喂|测试|谢谢|好的|嗯)+$/i.test(String(item.answer || '').replace(/[\s，。！？、,.!?…]/g, '')));
  if (greetingsOnly) return '已保存的回答仅包含问候或简短确认，缺少对题目的实质作答。可在逐题复盘中查看原文。';
  if (timeline.length === 1) return '本场仅记录 1 条回答。建议完成更多问题后再判断整体能力。';
  return `本场共有 ${timeline.length} 条已保存回答，可在逐题复盘中查看。`;
}

export function isAbilityReport(report) {
  if (!report?.has_candidate_answer || visibleReportScore(report) === null) return false;
  if (report.scored_answer_count == null) return report.generation_status === 'succeeded' && !report.fallback;
  return ['succeeded', 'degraded'].includes(report.generation_status)
    && report.scored_answer_count > 0 && report.scored_answer_count === report.answer_count;
}

// 能力页采用后端选定的样本 ID，以免重新生成报告后，前端按更新时间挑到不同场次。
export function comparableReports(reports, stats) {
  if (Array.isArray(stats?.valid_report_ids)) {
    const byId = new Map(reports.map((report) => [report.id, report]));
    return stats.valid_report_ids.slice().reverse().map((id) => byId.get(id)).filter(Boolean);
  }
  const valid = reports.filter(isAbilityReport);
  const latest = valid[0];
  return valid.filter((report) => ['target_role', 'difficulty', 'prompt_version'].every((key) => report[key] === latest[key]));
}

export function abilitySampleStatus(reportCount) {
  const count = Math.max(0, Number(reportCount) || 0);
  if (count === 0) return { label: '暂无样本', tone: 'amber', progress: 0 };
  if (count === 1) return { label: '已建立基线', tone: 'blue', progress: 20 };
  if (count < 5) return { label: '持续积累', tone: 'blue', progress: count * 20 };
  return { label: '可查看趋势', tone: 'green', progress: 100 };
}

export function coverageLabel({ answer_count, scored_answer_count }) {
  if (!Number.isInteger(answer_count) || !Number.isInteger(scored_answer_count)
    || scored_answer_count < 0 || scored_answer_count > answer_count) return '';
  return `有效评分 ${scored_answer_count}/${answer_count} 题`;
}

// 先看状态和覆盖，再读数值，以区分有证据的零分和数据库中代表未出分的零。
export function visibleReportScore(report) {
  if (['pending_retry', 'insufficient_evidence', 'queued', 'failed'].includes(report.generation_status)
    || report.scored_answer_count === 0 || report.has_candidate_answer === 0 || report.has_candidate_answer === false) return null;
  return reportScore(report.total_score);
}

export function reportStatusText(report) {
  return ({
    queued: '生成中', failed: '生成失败', pending_retry: '待补评', insufficient_evidence: '证据不足',
    degraded: report.scored_answer_count == null ? '历史降级报告' : '报告文字已降级',
  })[report.generation_status] || (visibleReportScore(report) === null ? '未评分' : '已评分');
}

export function roundAssessment(item) {
  const status = item.evaluation_status || item.generation_status;
  const label = ({ pending_retry: '待补评', degraded: '历史降级评价', failed: '评价失败', insufficient_evidence: '证据不足' })[status];
  const score = label ? null : reportScore(item.score);
  let evidence = item.dimension_evidence;
  if (typeof evidence === 'string') {
    try { evidence = JSON.parse(evidence); } catch { evidence = null; }
  }
  return {
    score, scoreLabel: label || (score === null ? '未评分' : `${score} 分`),
    retryId: item.message_id && ['pending_retry', 'failed', 'degraded'].includes(status) ? item.message_id : null,
    evidence: evidence && typeof evidence === 'object' && !Array.isArray(evidence)
      ? Object.entries(evidence).filter(([, quote]) => typeof quote === 'string' && quote.trim()) : [],
  };
}

export const dimensionLabels = {
  technical_accuracy: '技术准确性',
  technical_depth: '技术深度',
  expression_clarity: '表达清晰度',
  business_understanding: '业务理解',
  tradeoff_reasoning: '权衡决策',
  risk_awareness: '风险意识',
  result_quantification: '结果量化',
  role_fit: '岗位匹配度',
};
