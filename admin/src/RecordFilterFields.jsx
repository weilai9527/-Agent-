import React from 'react';
import { recordFilterOptions, scoreBands } from './recordFilters.js';

export default function RecordFilterFields({ kind, rows, filters, onChange }) {
  const update = (key, value) => onChange({ ...filters, [key]: value, ...(key === 'college' ? { className: '' } : {}) });
  const fields = [['college', '学院'], ['className', '班级'], ['role', '目标岗位'],
    ...(kind === 'interviews' ? [['type', '训练类型']] : [['grade', '报告等级']])];
  const dateLabel = kind === 'interviews' ? '更新时间' : '生成时间';
  const invalidRange = filters.startDate && filters.endDate && filters.startDate > filters.endDate;
  return <>
    <div className="record-filter-fields">
      {fields.map(([key, label]) => <label key={key}><span>{label}</span>
        <select aria-label={label} value={filters[key] || ''} onChange={(event) => update(key, event.target.value)}>
          <option value="">全部{label}</option>
          {recordFilterOptions(rows, key, filters.college).map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </label>)}
      {kind === 'reports' && <label><span>分数段</span>
        <select aria-label="分数段" value={filters.scoreBand || ''} onChange={(event) => update('scoreBand', event.target.value)}>
          <option value="">全部分数</option>
          {scoreBands.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>}
      <label><span>{dateLabel}起</span><input type="date" aria-label={`${dateLabel}起`} value={filters.startDate || ''}
        max={filters.endDate || undefined} aria-invalid={Boolean(invalidRange)} onInput={(event) => update('startDate', event.currentTarget.value)} onChange={(event) => update('startDate', event.target.value)} /></label>
      <label><span>{dateLabel}止</span><input type="date" aria-label={`${dateLabel}止`} value={filters.endDate || ''}
        min={filters.startDate || undefined} aria-invalid={Boolean(invalidRange)} onInput={(event) => update('endDate', event.currentTarget.value)} onChange={(event) => update('endDate', event.target.value)} /></label>
    </div>
    {invalidRange && <p className="record-filter-error" role="alert">开始日期不能晚于结束日期，请调整日期范围。</p>}
  </>;
}
