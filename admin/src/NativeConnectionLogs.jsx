import React, { useEffect, useState } from 'react';

// 每次翻页都经过服务端的实时名册授权。组件不保留已撤权的上一页或详情。
export default function NativeConnectionLogs({ request }) {
  const [filters, setFilters] = useState({student_q: '', interview_id: '', level: ''});
  const [query, setQuery] = useState({...filters, offset: 0, after_student: ''});
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const stop = new AbortController();
    setError(''); setResult(null);
    const params = new URLSearchParams(query);
    params.set('limit', '50');
    request('/api/admin/connection-logs?' + params, {signal: stop.signal})
      .then(data => { if (!stop.signal.aborted) setResult(data); })
      .catch(reason => { if (!stop.signal.aborted) setError(reason.message); });
    return () => stop.abort();
  }, [request, query]);
  function search(event) {
    event.preventDefault();
    setQuery({...filters, offset: 0, after_student: ''});
  }
  return <section className="section-card connection-logs-page"><h2>RTC 连接日志</h2>
    <p>按当前可见学生检索。会话使用匿名编号，诊断详情只记录连接状态。</p>
    <form onSubmit={search} className="connection-log-toolbar">
      <label>学生姓名、学号或编号<input value={filters.student_q} maxLength={128}
        onChange={event => setFilters({...filters, student_q: event.target.value})}/></label>
      <label>面试编号<input value={filters.interview_id} maxLength={64}
        onChange={event => setFilters({...filters, interview_id: event.target.value})}/></label>
      <label>严重程度<select value={filters.level} onChange={event => setFilters({...filters,level:event.target.value})}>
        <option value="">全部</option><option value="info">正常</option><option value="warning">警告</option>
        <option value="error">错误</option></select></label><button type="submit">查询</button>
    </form>
    {error ? <p role="alert">{error}</p> : !result ? <p role="status">正在查询…</p> : <>
      <p>{result.retentionDays ? `可检索最近 ${result.retentionDays} 天的记录。` : '包含已迁入的历史记录。'}</p>
      <div className="table-wrap"><table><thead><tr>{['时间','学生','面试编号','事件','级别','连接状态','匿名会话']
        .map(title => <th key={title}>{title}</th>)}</tr></thead><tbody>
        {result.logs.map(row => <tr key={row.id}>{[new Date(row.created_at).toLocaleString(),row.candidate,
          row.interview_id,row.event_type,row.level,[row.connection_state,row.ice_connection_state,row.signaling_state,
              row.data_channel_state].filter(Boolean).join(' / '),row.session_ref].map((field,i) =>
          <td key={i}>{field || '—'}</td>)}</tr>)}</tbody></table></div>
      {!result.logs.length && <p>当前名册页无匹配的诊断事件。</p>}
      <button disabled={query.offset===0} onClick={() => setQuery({...query,offset:query.offset-50})}>上一页事件</button>
      <button disabled={!result.hasMore} onClick={() => setQuery({...query,offset:query.offset+50})}>下一页事件</button>
      {result.nextStudents && <button onClick={() => setQuery({...query, offset:0, after_student:result.nextStudents})}>下一页学生</button>}
    </>}
  </section>;
}
