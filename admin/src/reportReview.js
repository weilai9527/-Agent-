const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

export function reviewText(value) {
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number') return String(value);
  if (Array.isArray(value)) return value.map(reviewText).filter(Boolean).join('\n');
  return '';
}

export function reviewScore(value) {
  if (!['string', 'number'].includes(typeof value) || String(value).trim() === '') return null;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 && number <= 100 ? number : null;
}

function readSection(value) {
  if (typeof value === 'string') {
    const text = value.trim();
    if (!text) return { items: [], text: '', invalid: false };
    try { return readSection(JSON.parse(text)); }
    catch {
      // Never show a damaged serialized report as a wall of implementation fields.
      return /^[\[{]/.test(text) ? { items: [], text: '', invalid: true } : { items: [], text, invalid: false };
    }
  }
  if (Array.isArray(value)) return { items: value, text: '', invalid: false };
  if (isRecord(value)) return { items: [value], text: '', invalid: false };
  return { items: [], text: '', invalid: false };
}

const roleLabels = { technical: '专业能力', architecture: '方案与架构', hr: '沟通与职业素养' };

export function feedbackView(value) {
  const section = readSection(value);
  return { ...section, items: section.items.map((item, index) => {
    if (!isRecord(item)) return { id: `feedback-${index}`, name: `面试官 ${index + 1}`, comment: reviewText(item), score: null };
    return {
      id: item.agent_id || `feedback-${index}`,
      name: reviewText(item.agent_name || item.name) || `面试官 ${index + 1}`,
      role: roleLabels[item.agent_type] || '',
      score: reviewScore(item.score),
      comment: reviewText(item.comment || item.feedback || item.summary),
      strengths: reviewText(item.strengths), issues: reviewText(item.issues),
      suggestions: reviewText(item.suggestions || item.suggestion),
    };
  }).filter((item) => item.comment || item.strengths || item.issues || item.suggestions || item.score !== null) };
}

export function timelineView(value) {
  const section = readSection(value);
  const items = [];
  let question = null;
  for (const item of section.items) {
    if (!isRecord(item)) {
      if (reviewText(item)) items.push({ id: `round-${items.length}`, answer: reviewText(item), score: null });
      continue;
    }
    if (item.sender_type === 'agent') {
      if (item.message_type !== 'system') question = item;
      continue;
    }
    if (item.sender_type && item.sender_type !== 'candidate') continue;
    items.push({
      id: item.message_id || `round-${items.length}`,
      name: reviewText(item.agent_name || question?.agent_name) || '面试官',
      question: reviewText(item.question || item.question_preview || question?.content || question?.content_preview),
      answer: reviewText(item.answer || item.answer_preview || item.content || item.content_preview),
      score: reviewScore(item.score), strengths: reviewText(item.strengths),
      issues: reviewText(item.issues), suggestions: reviewText(item.suggestions || item.suggestion),
    });
    question = null;
  }
  return { ...section, items: items.filter((item) => item.question || item.answer || item.strengths || item.issues || item.suggestions || item.score !== null) };
}
