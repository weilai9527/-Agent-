import React, { useEffect, useRef, useState } from 'react';
import NativeStudentGrants from './NativeStudentGrants.jsx';
import StudentTeachingProfile from './StudentTeachingProfile.jsx';
import '../../frontend/src/training.css';
import { readStudentTsv } from './nativeStudentImport.js';

const base = '/api/admin/identity';
const pageSize = 25;

function ImportStudents({ request, onSaved }) {
  const [rows, setRows] = useState([0]);
  const [importedRows, setImportedRows] = useState({});
  const nextRow = useRef(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [created, setCreated] = useState([]);
  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const values = new FormData(form);
    const students = rows.map((id) => ({
      name: values.get('name-' + id).trim(),
      student_no: values.get('number-' + id).trim(),
      temporary_password: values.get('password-' + id),
    }));
    setBusy(true);
    setError('');
    setCreated([]);
    try {
      const reply = await request(base + '/students/import', { method: 'POST', body: JSON.stringify({ students }) });
      if (!Array.isArray(reply.students)) throw new Error('开户结果格式无效，请核对名单后再操作。');
      setCreated(reply.students);
      setImportedRows({});
      form.reset();
      setRows([nextRow.current++]);
      onSaved();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return <form className="training-card" onSubmit={submit} aria-label="批量开通学生账号">
    <header><h3>批量开通学生账号</h3><p className="training-meta">每批最多 100 人。为每位学生分发独立临时密码，首次登录时须修改。</p></header>
    <fieldset disabled={busy} className="training-stack"><legend>待开通学生</legend>
      <details><summary>从文件载入待开通名单</summary>
        <p>选择 UTF-8 制表符分隔文本（.tsv 或 .txt），表头依次为学号、姓名、临时密码。载入后替换待提交行，核对后点击开通。</p>
        <label className="training-field">载入名单文件<input type="file" accept=".tsv,.txt" onChange={async event => {
          const file = event.target.files?.[0];
          event.target.value = '';
          if (!file) return;
          setBusy(true); setError(''); setCreated([]);
          try {
            const batch = await readStudentTsv(file);
            const ids = batch.map(() => nextRow.current++);
            setImportedRows(Object.fromEntries(ids.map((id, index) => [id, batch[index]])));
            setRows(ids);
          } catch (err) { setError(err.message); }
          finally { setBusy(false); }
        }} /></label>
      </details>
      {rows.map((id, i) => <div className="training-row" key={id}>
        <label className="training-field">姓名 {i + 1}<input name={'name-' + id} defaultValue={importedRows[id]?.name || ''} maxLength={120} required /></label>
        <label className="training-field">学号 {i + 1}<input name={'number-' + id} defaultValue={importedRows[id]?.student_no || ''} minLength={3} maxLength={40} required /></label>
        <label className="training-field">临时密码 {i + 1}<input type="password" autoComplete="new-password" name={'password-' + id} defaultValue={importedRows[id]?.temporary_password || ''} minLength={8} maxLength={256} required /></label>
        {rows.length > 1 && <button type="button" onClick={() => setRows(rows.filter((v) => v !== id))}>移除第 {i + 1} 行</button>}
      </div>)}
      <div className="training-row"><button type="button" disabled={rows.length >= 100} onClick={() => setRows([...rows, nextRow.current++])}>添加学生</button>
        <button className="training-primary">开通 {rows.length} 个账号</button></div>
    </fieldset>
    {error && <p role="alert">{error}</p>}
    {created.length > 0 && <div role="status"><p>已开通 {created.length} 个账号</p>
      <ul>{created.map((row) => <li key={row.actor_id}>{row.student_no} · 账号 ID {row.actor_id}</li>)}</ul></div>}
  </form>;
}

function AccountActions({ request, schoolId, studentId, label, permissions, status, onSaved }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event) {
    event.preventDefault();
    if (busy || !studentId) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const reset = form.dataset.action === 'reset';
    const payload = reset ? { temporary_password: data.get('temporary_password') } : { status: data.get('status') };
    if (!reset && !['normal', 'disabled'].includes(payload.status)) return;
    // 账号标识必须位于单个路径段内。拒绝可能跳转到其他路径的输入，
    // 包括在 URI 解码后才改变路径的值。
    if (['.', '..'].includes(studentId) || /[/%\\\s\x00-\x1f]/.test(studentId)) {
      setError('请输入有效的学生账号 ID。'); return;
    }
    setBusy(true); setError('');
    try {
      const path = base + '/v1/students/' + encodeURIComponent(studentId) + (reset ? '/reset-password' : '/status');
      await request(path, { method: reset ? 'POST' : 'PATCH', body: JSON.stringify(payload) });
      form.reset();
      onSaved(reset ? '已重置 ' + label + ' 的临时密码。' : '已更新 ' + label + ' 的账号状态。');
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return <div className="training-stack"><h4>操作对象：{label}</h4>
    {permissions.canReadStudentProfile && <StudentTeachingProfile request={request} permissions={permissions}
      schoolId={schoolId} studentId={studentId} />}
    {permissions.canManageStudentGrants && <NativeStudentGrants request={request} schoolId={schoolId} studentId={studentId} />}
    {permissions.canResetStudentPasswords && <form data-action="reset" onSubmit={submit}>
      <fieldset disabled={busy} className="training-row"><legend>重置临时密码</legend>
        <label className="training-field">新临时密码<input type="password" autoComplete="new-password" name="temporary_password" minLength={8} maxLength={256} required /></label>
        <button type="submit">重置密码并撤销会话</button></fieldset></form>}
    {permissions.canSetStudentStatus && <form data-action="status" onSubmit={submit}>
      <fieldset disabled={busy} className="training-row"><legend>启用或停用账号</legend>
        <label className="training-field">目标状态<select name="status" defaultValue="" required>
          <option value="" disabled>请选择</option>{status !== 'normal' && <option value="normal">启用</option>}
          {status !== 'disabled' && <option value="disabled">停用</option>}</select></label>
        <button type="submit">更新状态并撤销会话</button></fieldset></form>}
    {error && <p role="alert">{error}</p>}
  </div>;
}

function SchoolStudents({ request, permissions, schoolId }) {
  const [q, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [reply, setReply] = useState(null);
  const [selected, setSelected] = useState('');
  const [receipt, setReceipt] = useState('');
  const [manual, setManual] = useState('');
  const read = permissions.canReadStudentAccounts;
  const mutate = permissions.canSetStudentStatus || permissions.canResetStudentPasswords || permissions.canManageStudentGrants;
  const showDetails = mutate || permissions.canReadStudentProfile;
  const path = base + '/v1/students?' + new URLSearchParams({ q, limit: pageSize, offset });
  useEffect(() => {
    if (!read) return;
    const controller = new AbortController();
    request(path, { signal: controller.signal }).then((result) => {
      if (!Array.isArray(result.items) || !Number.isInteger(result.total)) throw new Error('学生名册格式无效。');
      if (result.school_id !== schoolId || result.items.some(row => !row || (row.school_id != null && row.school_id !== schoolId))) {
        throw new Error('读取的名册与当前学校不符。');
      }
      if (!controller.signal.aborted) setReply({ path, revision, result });
    }).catch((err) => { if (!controller.signal.aborted) setReply({ path, revision, error: err.message }); });
    return () => controller.abort();
  }, [read, path, revision, request, schoolId]);
  const response = reply?.path === path && reply?.revision === revision ? reply : null;
  const data = response?.result;
  const student = data?.items.find((r) => r.actor_id === selected);
  function refresh(message) {
    setReceipt(message || '');
    setRevision((v) => v + 1);
  }
  function search(event) {
    event.preventDefault();
    setQuery(new FormData(event.currentTarget).get('q').trim()); setOffset(0); setSelected(''); setReceipt('');
  }
  return <section className="training-page" aria-label="学生账号管理">
    <header><h2>学生账号</h2></header>
    {permissions.canImportStudentAccounts && <ImportStudents request={request} onSaved={() => refresh()} />}
    {read && <section className="training-card"><h3>学生名册</h3>
      <form className="training-row" onSubmit={search}>
        <label className="training-field">姓名、学号或账号 ID<input name="q" maxLength={128} /></label>
        <button>查询</button><button type="button" onClick={() => refresh()}>刷新名册</button></form>
      {response?.error ? <p role="alert">{response.error}</p> : !data ? <p role="status">正在读取学生名册…</p> :
        <><div className="training-scroll"><table><thead><tr><th>姓名 / 学号</th><th>院系与班级</th><th>账号状态</th>{showDetails && <th>操作对象</th>}</tr></thead>
          <tbody>{data.items.map((r) => <tr key={r.actor_id}>
            <td>{r.name} · {r.student_no || '未登记学号'}<br /><small>{r.actor_id}</small></td>
            <td>{[r.college,r.program,r.class_name].filter(Boolean).join(' / ') || '未归班'}</td>
            <td>{r.status === 'normal' ? '启用' : '停用'}{r.must_change_password && ' · 待首次改密'}</td>
            {showDetails && <td><button type="button" aria-pressed={selected === r.actor_id} onClick={() => {setSelected(r.actor_id); setReceipt('');}}>选择 {r.name}</button></td>}
          </tr>)}</tbody></table></div>
          {!data.items.length && <p>没有匹配的学生。</p>}
          <div className="training-row"><span>共 {data.total} 人</span>
            <button type="button" disabled={!offset} onClick={() => {setOffset(Math.max(0,offset - pageSize)); setSelected('');}}>上一页</button>
            <button type="button" disabled={offset + pageSize >= data.total} onClick={() => {setOffset(offset + pageSize); setSelected('');}}>下一页</button></div></>}
    </section>}
    {showDetails && <section className="training-card"><h3>{mutate ? '账号维护' : '学生详情'}</h3>
      {!read && <label className="training-field">学生账号 ID<input maxLength={128} value={manual} onChange={(e) => {setManual(e.target.value); setReceipt('');}} /></label>}
      {read && !student && <p>在本页名册选择要操作的学生。</p>}
      {(student || (!read && manual.trim())) && <AccountActions key={student?.actor_id || manual.trim()} request={request}
        studentId={student?.actor_id || manual.trim()} label={student ? student.name + '（' + (student.student_no || student.actor_id) + '）' : manual.trim()}
        schoolId={schoolId} status={student?.status} permissions={permissions} onSaved={refresh} />}
    </section>}
    {receipt && <p role="status">{receipt}</p>}
    {!read && !showDetails && !permissions.canImportStudentAccounts && <p>当前账号没有学生账号管理权限。</p>}
  </section>;
}

export default function NativeStudentAccounts({ request, permissions = {}, schoolId }) {
  if (!schoolId) return <p role="status">学校身份尚未就绪。</p>;
  // 切换学校或权限变化时清空已加载的记录、选择和密码输入，并忽略旧请求的响应。
  // 同校账号权限降低时也要清理这些状态。
  const flags = ['canReadStudentAccounts','canImportStudentAccounts','canResetStudentPasswords','canSetStudentStatus','canManageStudentGrants','canReadStudentProfile'];
  const key = JSON.stringify([schoolId, ...flags.map((flag) => Boolean(permissions[flag]))]);
  return <SchoolStudents key={key} request={request} permissions={permissions} schoolId={schoolId} />;
}
