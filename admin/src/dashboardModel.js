import { matchesRecordFilters } from './recordFilters.js';
import { reviewScore } from './reportReview.js';

export function dashboardRange(period, now = new Date()) {
  if (period === 'all') return {};
  const endDate = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(now);
  const [year, month, day] = endDate.split('-').map(Number);
  const days = period === 'today' ? 1 : Number(period);
  const startDate = new Date(Date.UTC(year, month - 1, day - days + 1)).toISOString().slice(0, 10);
  return { startDate, endDate };
}

const studentKey = (row) => row.userId || row.studentNo || null;
const oldestFirst = (left, right) => String(left.createdAt || left.updatedAt || '').localeCompare(String(right.createdAt || right.updatedAt || ''));

export function dashboardModel(data, filters, now = new Date()) {
  const scope = { college: filters.college || '', className: filters.className || '' };
  const range = dashboardRange(filters.period || 'all', now);
  const roster = Array.isArray(data.dashboardRoster) ? data.dashboardRoster.filter((row) => matchesRecordFilters(row, scope)) : null;
  const reports = data.permissions?.canViewReports ? (data.reports || []).filter((row) => matchesRecordFilters(row, { ...scope, ...range }, 'createdAt')) : [];
  const interviews = data.permissions?.canViewInterviews ? (data.interviews || []).filter((row) => matchesRecordFilters(row, { ...scope, ...range }, 'updatedAt')) : [];
  const scored = reports.filter((row) => reviewScore(row.score) !== null);
  const completed = interviews.filter((row) => row.status === '已完成');
  const active = (roster || []).filter((row) => row.activated);
  const trainedKeys = new Set(completed.map(studentKey).filter(Boolean));
  const completedStudents = roster ? active.filter((row) => trainedKeys.has(studentKey(row))).length : null;
  return {
    roster, reports, interviews, scored, completedStudents,
    pending: roster ? roster.filter((row) => !row.activated).sort(oldestFirst) : null,
    unassigned: roster ? roster.filter((row) => row.activated && !row.classAssigned).sort(oldestFirst) : null,
    review: reports.filter((row) => row.reviewStatus === '待复核').sort(oldestFirst),
    running: interviews.filter((row) => row.status === '进行中'),
    recent: [...interviews].sort((a, b) => String(b.updatedAt).localeCompare(String(a.updatedAt))),
    average: scored.length ? Math.round(scored.reduce((sum, row) => sum + Number(row.score), 0) / scored.length) : null,
    participation: active.length ? Math.round(completedStudents / active.length * 100) : null,
    completion: interviews.length ? Math.round(completed.length / interviews.length * 100) : null,
    activeCount: active.length,
    bands: [scored.filter((row) => Number(row.score) >= 90).length,
      scored.filter((row) => Number(row.score) >= 80 && Number(row.score) < 90).length,
      scored.filter((row) => Number(row.score) >= 70 && Number(row.score) < 80).length,
      scored.filter((row) => Number(row.score) < 70).length],
    scope, range,
  };
}

export function waitingLabel(value, now = new Date()) {
  if (!value) return '等待处理';
  const timestamp = Date.parse(/(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${String(value).replace(' ', 'T')}Z`);
  if (!Number.isFinite(timestamp)) return '等待处理';
  const days = Math.floor(Math.max(0, now.getTime() - timestamp) / 86400000);
  return days ? `等待 ${days} 天` : '今日新增';
}
