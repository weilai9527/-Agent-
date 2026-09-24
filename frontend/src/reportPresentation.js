export function reportScore(value) {
  if (value === null || value === undefined || value === '') return null;
  const score = Number(value);
  return Number.isFinite(score) ? Math.min(100, Math.max(0, score)) : null;
}

export function hasInterviewerEvaluation(item) {
  return reportScore(item.score) !== null && !/暂无关联单题评价|未记录到候选人回答|暂无评价/.test(item.comment || '');
}

export function reportEvidenceNote(timeline) {
  if (!timeline.length) return '本场没有已保存的回答，暂不足以形成能力判断。';
  const greetingsOnly = timeline.every((item) => /^(你好|您好|hello|hi|喂|测试|谢谢|好的|嗯)+$/i.test(String(item.answer || '').replace(/[\s，。！？、,.!?…]/g, '')));
  if (greetingsOnly) return '已保存的回答仅包含问候或简短确认，缺少对题目的实质作答。下方为原始作答评分，不足以判断完整岗位能力。';
  if (timeline.length === 1) return '本场仅记录 1 条回答。评分仅反映本次作答，建议完成更多问题后再判断整体能力。';
  return `评分基于本场 ${timeline.length} 条已保存回答，供练习复盘参考。`;
}

export function isAbilityReport(report) {
  return Boolean(report?.has_candidate_answer)
    && ['succeeded', 'degraded'].includes(report?.generation_status)
    && reportScore(report?.total_score) !== null;
}

export function abilitySampleStatus(reportCount) {
  const count = Math.max(0, Number(reportCount) || 0);
  if (count === 0) return { label: '暂无样本', tone: 'amber', progress: 0 };
  if (count === 1) return { label: '已建立基线', tone: 'blue', progress: 20 };
  if (count < 5) return { label: '持续积累', tone: 'blue', progress: count * 20 };
  return { label: '可查看趋势', tone: 'green', progress: 100 };
}
