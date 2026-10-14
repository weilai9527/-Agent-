import React from 'react';
import './interviewerStrategy.css';

export default function InterviewerStrategyFields({ policy, loading, error, onRetry, form, onChange }) {
  return <section className="candidate-strategy" aria-label="面试官策略">
    <div><h3>你希望怎样练习？</h3><p>选择提问风格、考察重点与追问深度，评分标准保持统一。</p></div>
    {loading ? <p role="status">正在读取可选策略…</p> : error ? <div role="alert"><p>{error}</p><button type="button" className="secondary-action" onClick={onRetry}>重新读取策略</button></div> : policy && <>
      <div className="candidate-strategy-fields">{[['style', 'style', '面试官风格'], ['focus', 'focusArea', '考察重点'], ['depth', 'depth', '追问深度']].map(([key, field, label]) => <label key={key}><span>{label}</span><select aria-label={label} value={form[field]} disabled={!policy.studentCanChoose} onChange={event => onChange(field, event.target.value)}>{policy.allowed[key].map(value => <option key={value}>{value}</option>)}</select></label>)}</div>
      <div className="candidate-strategy-summary"><strong>本场策略：{form.style} · {form.focusArea} · {form.depth}</strong><span>{policy.studentCanChoose ? '选择会随本场面试保存，重新连接时继续使用。' : '本场使用管理员统一设置的策略。'}</span></div>
    </>}
  </section>;
}
