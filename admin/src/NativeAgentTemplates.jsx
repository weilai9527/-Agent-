import React, { useEffect, useState } from 'react';

// 模板统计来自实际面试实例。仅具备面试记录读取权时请求逐场使用明细。
export default function NativeAgentTemplates({ request, canReadInterviews }) {
  const [student, setStudent] = useState('');
  const [query, setQuery] = useState({student_q: '', name: '', recent: false});
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const stop = new AbortController();
    setPayload(null); setError('');
    const params = new URLSearchParams({...query, recent: Boolean(canReadInterviews && query.recent)});
    request('/api/admin/agent-templates?' + params, {signal: stop.signal})
      .then(result => { if (!stop.signal.aborted) setPayload(result); })
      .catch(reason => { if (!stop.signal.aborted) setError(reason.message); });
    return () => stop.abort();
  }, [request, query, canReadInterviews]);
  return <section className="section-card"><h2>面试官模板与使用情况</h2>
    <p>使用次数按当前可见学生实际创建的面试官实例统计，每页列出使用最多的 20 项。</p>
    <form className="connection-log-toolbar" onSubmit={e => {e.preventDefault(); setQuery({student_q:student,name:'',recent:false});}}>
      <label>学生姓名或学号<input value={student} maxLength={128} onChange={e => setStudent(e.target.value)} /></label>
      <button type="submit">查询模板</button>
    </form>
    {error ? <p role="alert">{error}</p> : !payload ? <p role="status">正在读取模板…</p> : <>
      {query.name && <button onClick={() => setQuery({...query,name:'',recent:false})}>返回列表</button>}
      {!payload.items.length && <p>当前范围还没有面试官使用记录。</p>}
      <div className="table-wrap"><table><thead><tr><th>面试官名称</th><th>类型</th><th>职责</th>
        {query.name && <th>策略</th>}<th>使用次数</th></tr></thead><tbody>
        {payload.items.map(row => <tr key={JSON.stringify([row.name,row.type,row.focus,row.strategy])}>
          <td>{query.name ? row.name : <button onClick={() => setQuery({...query,name:row.name,recent:canReadInterviews})}>{row.name}</button>}</td>
          <td>{row.type}</td><td>{row.focus}</td>{query.name && <td>{row.strategy || '—'}</td>}<td>{row.usageCount}</td>
        </tr>)}</tbody></table></div>
      {query.name && canReadInterviews && <><h3>最近使用</h3>{payload.recentUsage.length ?
        <ul>{payload.recentUsage.map(row => <li key={row.instance_id}>{row.candidate} · {row.target_role} · {row.status} · {row.interview_id}</li>)}</ul>
        : <p>当前范围无使用明细。</p>}</>}
    </>}
  </section>;
}
