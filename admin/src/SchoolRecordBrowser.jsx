import React, { useEffect, useState } from 'react';
import { localDate } from '../../frontend/src/trainingUi.js';

const labels = {
  training: '教学训练', practice: '自主练习', draft: '草稿', running: '进行中', completed: '已完成',
  queued: '排队中', succeeded: '生成完成', degraded: '部分降级', pending_retry: '等待补评',
  insufficient_evidence: '评分证据不足', failed: '生成失败', pending: '待复核', approved: '已复核',
  rejected: '复核未通过', question: '提问', follow_up: '追问', answer: '回答', transcript: '回答转写',
};
const display = value => labels[value] ?? value ?? '—';

function useRecordRequest(request, path, revision) {
  const [result, setResult] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    request(path, { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) setResult({ path, revision, data });
    }).catch(err => {
      if (!controller.signal.aborted) setResult({ path, revision, status: err.status || 503 });
    });
    return () => controller.abort();
  }, [request, path, revision]);
  return result?.path === path && result.revision === revision ? result : {};
}

function PageState({ reply, children }) {
  if (reply.status === 401 || reply.status === 403) return <p role="alert">当前账号已无权查看此范围。</p>;
  if (reply.status === 404) return <p role="alert">记录不存在或已离开当前可见范围。</p>;
  if (reply.status) return <p role="alert">读取失败，请刷新后重试。</p>;
  if (!reply.data) return <p role="status">正在读取…</p>;
  return children(reply.data);
}

function Pager({ pages, setPages, next }) {
  return <nav aria-label="记录翻页"><button type="button" disabled={pages.length < 2}
    onClick={() => setPages(pages.slice(0, -1))}>上一页</button>
    <span> 第 {pages.length} 页 </span><button type="button" disabled={!next}
      onClick={() => setPages([...pages, next])}>下一页</button></nav>;
}

function suggestions(value) {
  try {
    const parsed = JSON.parse(value);
    if (Array.isArray(parsed)) return parsed.filter(item => typeof item === 'string').join('\n');
  } catch { /* 历史报告可能以纯文本保存。 */ }
  return typeof value === 'string' ? value : '';
}

function Detail({ request, url, report, revision, close }) {
  const [pages, setPages] = useState(['']);
  const token = pages.at(-1);
  const reply = useRecordRequest(request, url + (token ? '?cursor=' + encodeURIComponent(token) : ''), revision);
  return <><button type="button" onClick={close}>返回记录列表</button>
    <PageState reply={reply}>{row => <article><h3>{row.name} · {row.target_role}</h3>
      <p>{display(row.kind)} · {row.class_name || '未分配班级'} · {localDate(row.created_at)}</p>
      <p>记录编号 {row.id}　学生编号 {row.student_id}</p>
      {report ? <>
        <p>得分 {row.total_score ?? '未评分'}　{display(row.generation_status)}　{display(row.review_status)}</p>
        <h4>报告摘要</h4><p>{row.summary || '暂无摘要'}</p>
        <h4>改进建议</h4><p style={{ whiteSpace: 'pre-line' }}>{suggestions(row.suggestions) || '暂无建议'}</p>
      </> : <>
        <h4>面试问答</h4>{row.turns.length ? <ol>{row.turns.map(item => <li key={item.id}>
          <strong>{display(item.message_type)}</strong><p style={{ whiteSpace: 'pre-wrap' }}>{item.content}</p>
        </li>)}</ol> : <p>尚无问答记录。</p>}
        <Pager pages={pages} setPages={setPages} next={row.next_cursor} />
      </>}
    </article>}</PageState></>;
}

export default function SchoolRecordBrowser({ request, owner, revision, initialFilter = '' }) {
  const incoming = new URLSearchParams(initialFilter);
  const allowed = ['college_id', 'class_id', 'start_date', 'end_date', 'kind', 'state'];
  if (owner === 'assessment') allowed.push('score_band');
  const preset = new URLSearchParams();
  // 预览条数和游标属于原查询，切换筛选范围时从新列表的第一页读取。
  for (const key of allowed) {
    const value = incoming.get(key);
    if (value) preset.set(key, value);
  }
  const filter = preset.toString();
  return <RecordList key={owner + '/' + filter} request={request} owner={owner} revision={revision} initialFilter={filter} />;
}

function RecordList({ request, owner, revision, initialFilter }) {
  const report = owner === 'assessment';
  const base = '/api/admin/' + owner + '/v1/records';
  const [filter, setFilter] = useState(initialFilter);
  const [pages, setPages] = useState(['']);
  const [selected, setSelected] = useState(null);
  const query = new URLSearchParams(filter);
  if (pages.at(-1)) query.set('cursor', pages.at(-1));
  const [refresh, setRefresh] = useState(0);
  const reply = useRecordRequest(request, base + '?' + query, revision + '/' + refresh);

  function search(event) {
    event.preventDefault();
    const params = new URLSearchParams();
    new FormData(event.currentTarget).forEach((value, key) => {
      if (value.trim()) params.set(key, value.trim());
    });
    setFilter(params.toString());
    setRefresh(value => value + 1);
    setPages(['']);
  }

  return <section className="training-page">
    <h2>学校{report ? '报告' : '面试'}记录</h2>
    <p>可查看当前授权学生的自主练习和教学训练。记录按学生编号和记录编号排列。</p>
    {selected ? <Detail key={selected} report={report} request={request} url={base + '/' + encodeURIComponent(selected)}
      revision={revision} close={() => { setSelected(null); setRefresh(value => value + 1); }} /> : <>
      <form onSubmit={search} className="training-row">
        <label>姓名或学号 <input defaultValue={query.get('q') || ''} name="q" maxLength={128} placeholder="全部学生" /></label>
        <label>班级名称 <input defaultValue={query.get('class_name') || ''} name="class_name" maxLength={160} placeholder="全部可见班级" /></label>
        <label>学院编号 <input defaultValue={query.get('college_id') || ''} name="college_id" maxLength={128} placeholder="全部可见学院" /></label>
        <label>班级编号 <input defaultValue={query.get('class_id') || ''} name="class_id" maxLength={128} placeholder="全部可见班级" /></label>
        <label>{report ? '报告创建' : '面试更新'}起始日（上海） <input defaultValue={query.get('start_date') || ''} name="start_date" type="date" /></label>
        <label>{report ? '报告创建' : '面试更新'}截止日（上海） <input defaultValue={query.get('end_date') || ''} name="end_date" type="date" /></label>
        <label>{report ? '质检状态' : '面试状态'} <select name="state" defaultValue={query.get('state') || ''}><option value="">全部状态</option>
          {(report ? ['pending', 'approved', 'rejected'] : ['draft', 'running', 'completed']).map((key) => <option key={key} value={key}>{display(key)}</option>)}
        </select></label>
        {report && <label>有效成绩区间 <select name="score_band" defaultValue={query.get('score_band') || ''}>
          <option value="">全部成绩</option><option value="gte90">90 分及以上</option><option value="from80">80 至 89 分</option>
          <option value="from70">70 至 79 分</option><option value="below70">低于 70 分</option>
        </select></label>}
        <label>来源 <select name="kind" defaultValue={query.get('kind') || ''}><option value="">全部</option>
          <option value="practice">自主练习</option><option value="training">教学训练</option></select></label>
        <button type="submit">查询</button>
      </form>
      <PageState reply={reply}>{data => <>
        {data.items.length ? <div className="table-wrap"><table><thead><tr>
          <th>学生 / 班级</th><th>岗位</th><th>来源</th><th>创建时间</th><th>{report ? '得分' : '状态'}</th><th>操作</th>
        </tr></thead><tbody>{data.items.map(row => <tr key={row.id}>
          <td>{row.name}（{row.student_no}） / {row.class_name || '未分班'}</td><td>{row.target_role}</td><td>{display(row.kind)}</td>
          <td>{localDate(row.created_at)}</td><td>{report ? (row.total_score ?? '未评分') : display(row.status)}</td>
          <td><button type="button" onClick={() => setSelected(row.id)}>查看详情</button></td>
        </tr>)}</tbody></table></div> : <p>{data.next_cursor ? '本页学生没有匹配记录，可继续翻页。' : '当前范围没有更多匹配记录。'}</p>}
        <Pager pages={pages} setPages={setPages} next={data.next_cursor} />
      </>}</PageState>
    </>}
  </section>;
}
