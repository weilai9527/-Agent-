export const scoreBands = [
  { value: 'low', label: '低于 70 分', min: 0, max: 70 },
  { value: '70', label: '70–79 分', min: 70, max: 80 },
  { value: '80', label: '80–89 分', min: 80, max: 90 },
  { value: '90', label: '90 分及以上', min: 90, max: 101 },
];

export function recordFilterOptions(rows, key, college = '') {
  return [...new Set(rows
    .filter((row) => key !== 'className' || !college || row.college === college)
    .map((row) => row[key]).filter((value) => value && value !== '-'))]
    .sort((left, right) => String(left).localeCompare(String(right), 'zh-CN', { numeric: true }));
}

// Date inputs use the same calendar date shown in the list, including the entire end day.
export function matchesRecordFilters(row, filters, dateKey) {
  if (['college', 'className', 'role', 'type', 'grade'].some((key) => filters[key] && row[key] !== filters[key])) return false;
  if (filters.scoreBand) {
    const band = scoreBands.find((item) => item.value === filters.scoreBand);
    const score = row.score == null || String(row.score).trim() === '' ? NaN : Number(row.score);
    if (!band || !Number.isFinite(score) || score < band.min || score >= band.max) return false;
  }
  if (filters.startDate || filters.endDate) {
    if (filters.startDate && filters.endDate && filters.startDate > filters.endDate) return false;
    const day = String(row[dateKey] || '').match(/^\d{4}-\d{2}-\d{2}/)?.[0];
    if (!day || (filters.startDate && day < filters.startDate) || (filters.endDate && day > filters.endDate)) return false;
  }
  return true;
}
