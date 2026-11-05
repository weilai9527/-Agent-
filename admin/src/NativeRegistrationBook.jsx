/** 学校名册只读当前学校。一次性发放凭据仅保存在组件内存，切换账号会卸载本组件。 */
import React, { useEffect, useRef, useState } from 'react';

import { encodeSchoolFile } from './schoolWorkbookUpload.js';

const base = '/api/admin/identity/v1/registrations';
const labels = { apply: '应用登记信息到现有账号', issue: '开通并生成发放单', reissue: '作废旧密码并补发', revoke: '撤销登录', archive: '归档名单', restore: '恢复名单' };

function downloadSheet(data) {
  const blob = new Blob([Uint8Array.from(atob(data.content), c => c.charCodeAt(0))],
    { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = data.filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function NativeRegistrationBook({ admin, request }) {
  const grants = new Set(admin.permissions || []);
  const canExport = grants.has('registration.export');
  const readable = grants.has('registration.read');
  const [filters, setFilters] = useState({ state: 'all', q: '', counselor: '' });
  const [page, setPage] = useState(0);
  const [revision, refresh] = useState(0);
  const [result, setResult] = useState(null);
  const [selected, select] = useState([]);
  const [busy, setBusy] = useState(false);
  const [message, tell] = useState('');
  const [error, fail] = useState('');
  const [handout, setHandout] = useState([]);
  const [file, setFile] = useState(null);
  const [reason, setReason] = useState('凭据遗失');
  const mounted = useRef(true);
  const running = useRef(false);
  const query = new URLSearchParams(filters).toString();
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    if (!readable) return;
    const controller = new AbortController();
    setResult(null); select([]); fail('');
    request(base+'?'+query+'&offset='+page*50, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setResult(data); })
      .catch(err => { if (!controller.signal.aborted) fail(err.message); });
    return () => controller.abort();
  }, [request, query, page, revision, readable]);

  useEffect(() => {
    if (!handout.length) return;
    // 凭据只留在当前页面内存中；超时、切换账号或关闭页签后不再展示。
    const timer = setTimeout(() => setHandout([]), 5 * 60 * 1000);
    return () => clearTimeout(timer);
  }, [handout]);

  async function run(fn) {
    if (running.current) return;
    running.current = true; setBusy(true); tell(''); fail('');
    try { await fn(); }
    catch (err) { if (mounted.current) fail(err.message || '操作失败，请刷新后核对。'); }
    finally { running.current = false; if (mounted.current) setBusy(false); }
  }
  function post(path, data) {
    return request(base + path, { method: 'POST', body: JSON.stringify(data) });
  }
  function change(op) {
    if (!selected.length || !window.confirm(labels[op] + '，共 ' + selected.length + ' 人。确认继续？')) return;
    run(async () => {
      const applied = await post('/'+op, { items: selected, ...(op === 'reissue' ? { reason } : {}) });
      if (!mounted.current) return;
      setHandout(applied.handout || []); tell('已处理 '+applied.changed+' 人。');
      refresh(n => n + 1);
    });
  }
  function toggle(row) {
    select(current => current.some(r => r.student_no === row.student_no)
      ? current.filter(r => r.student_no !== row.student_no)
      : [...current, { student_no: row.student_no, revision: row.revision }]);
  }

  return <section className="training-card"><h3>注册名单与开通待办</h3>
    {grants.has('registration.import') && <>
      <form onSubmit={e => {
        e.preventDefault();
        const form = e.currentTarget, row = Object.fromEntries(new FormData(form));
        run(async () => { await post('/import', { rows: [row] }); form.reset(); tell('已保存登记。'); refresh(n => n+1); });
      }}><fieldset disabled={busy}><legend>新增或更新登记</legend>
        <label>学号 <input name="student_no" required maxLength={40} /></label>
        <label>姓名 <input name="name" required maxLength={120} /></label>
        <label>班级编号 <input name="class_id" maxLength={128} /></label>
        <label>辅导员 <input name="counselor" maxLength={120} /></label><button>保存登记</button>
      </fieldset></form>
      <div><label>Excel 登记名单 <input type="file" accept=".xlsx,.csv" onChange={e => setFile(e.target.files[0])} /></label>
        <button disabled={busy || !file} onClick={() => run(async () => {
          const counts = await post('/import-xlsx', await encodeSchoolFile(file));
          tell('新增 '+counts.created+' 人，更新 '+counts.updated+' 人，原样保留 '+counts.unchanged+' 人。'); refresh(n => n+1);
        })}>增量导入 Excel 或 CSV</button>
        <p>首行必须含学号和姓名，可填学院、班级、班级编号、性别、辅导员、账号状态、学生状态。导入后在待开通列表发放账号。</p>
      </div></>}
    {(readable || canExport) && <><form onSubmit={e => {
      e.preventDefault(); setFilters(Object.fromEntries(new FormData(e.currentTarget))); setPage(0);
    }}>
      <label>状态 <select name="state"><option value="all">在册全部</option><option value="pending">待开通</option>
        <option value="opened">已开通</option><option value="archived">已归档</option></select></label>
      <label>学号、姓名、学院或班级 <input name="q" maxLength={160}/></label>
      <label>辅导员 <input name="counselor" maxLength={120}/></label><button>筛选</button>
    </form>
    {canExport && <button disabled={busy} onClick={() => run(async () => downloadSheet(await request(base+'/export?'+query)))}>导出筛选后的 XLSX</button>}</>}
    <p>归档只影响登记名单。撤销登录会立即清除学生会话，原有训练、成绩和证书继续关联同一学生。</p>
    {result && <><p>匹配 {result.total} 人</p><table><thead><tr>
      <th><input type="checkbox" aria-label="选择本页所有学生" checked={!!result.items.length && selected.length === result.items.length}
        onChange={e => select(e.target.checked ? result.items.map(r => ({ student_no: r.student_no, revision: r.revision })) : [])}/></th>
      {['学号','姓名','班级','辅导员','登记状态','账号'].map(s => <th key={s}>{s}</th>)}</tr></thead>
      <tbody>{result.items.map(row => <tr key={row.student_no}><td><input type="checkbox" aria-label={'选择 '+row.student_no}
        checked={selected.some(r => r.student_no === row.student_no)} onChange={() => toggle(row)} /></td>
        <td>{row.student_no}</td><td>{row.name}</td><td>{row.class_name || row.class_id}</td><td>{row.counselor}</td>
        <td>{row.state}</td><td>{row.login_status === 'normal' ? (row.must_change_password ? '待改初始密码' : '可登录') : row.login_status ? '已停用' : '未开户'}</td></tr>)}</tbody></table>
      <button disabled={!page || busy} onClick={() => setPage(p => p-1)}>上一页</button>
      <button disabled={(page+1)*50 >= result.total || busy} onClick={() => setPage(p => p+1)}>下一页</button></>}
    {grants.has('registration.reissue') && <label>补发原因 <select value={reason} onChange={e => setReason(e.target.value)}>
      <option>凭据遗失</option><option>发放失败</option></select></label>}
    <div>{Object.entries(labels).filter(([op]) => grants.has('registration.'+
      (['revoke','restore','archive','apply'].includes(op) ? 'status' : op))).map(([op, label]) =>
      <button key={op} disabled={busy || !selected.length || !!handout.length} onClick={() => change(op)}>{label}</button>)}</div>
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    {handout.length>0 && <section className="school-password-handout" aria-label="一次性密码发放单">
      <h4>一次性密码发放单</h4><p>发放单显示五分钟。办理人确认发放后请关闭。关闭后无法找回本批密码，遗失时请显式补发。</p>
      <table><thead><tr><th>学号</th><th>姓名</th><th>临时密码</th></tr></thead>
        <tbody>{handout.map(r => <tr key={r.student_no}><td>{r.student_no}</td><td>{r.name}</td><td>{r.temporary_password}</td></tr>)}</tbody></table>
      <button onClick={() => window.print()}>打印发放单</button> <button onClick={() => setHandout([])}>已发放，清除本页密码</button>
    </section>}
  </section>;
}
