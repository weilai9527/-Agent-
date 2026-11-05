import React, { useEffect, useRef, useState } from 'react';
import { localDate, readError } from '../../frontend/src/trainingUi.js';
import '../../frontend/src/training.css';

const base = '/api/admin/credentials';
const applicationId = /^[a-f0-9]{64}$/;
const serialId = /^[a-f0-9]{32}$/;
const decisions = { pending: '待审核', approved: '已批准', rejected: '已驳回' };

function validApplication(item, studentId) {
  const e = item?.evidence;
  return typeof item?.id === 'string' && applicationId.test(item.id)
    && e?.student_id === studentId && Number.isSafeInteger(e.version) && e.version > 0
    && typeof e.digest === 'string' && applicationId.test(e.digest)
    && typeof e.report_id === 'string' && typeof e.training_id === 'string'
    && Object.hasOwn(decisions, item.decision)
    && Array.isArray(item.certificates)
    && item.certificates.every((c) => typeof c?.id === 'string' && serialId.test(c.id));
}

function Certificate({ cert, latest, canRevoke, canReissue, mutate }) {
  const [reason, setReason] = useState('');
  const path = '/certificates/' + cert.id;
  return <li>
    <strong>第 {cert.generation} 份证书 · {cert.revoked_at ? '已撤销' : '已签发'}</strong>
    <p>序列号 <code>{cert.id}</code> · 签发于 {localDate(cert.issued_at)}</p>
    {cert.revoked_at && <p>撤销于 {localDate(cert.revoked_at)}。原因：{cert.revocation_reason}</p>}
    {latest && !cert.revoked_at && canRevoke && <div className="training-row">
      <label>撤销原因 <input maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
      <button type="button" disabled={!reason.trim()} onClick={() =>
        mutate(path + '/revoke', { reason: reason.trim() }, '已撤销此证书。')}>撤销此证书</button>
    </div>}
    {latest && cert.revoked_at && canReissue && <button type="button" onClick={() =>
      mutate(path + '/reissue', {}, '已补发新证书。')}>补发新证书</button>}
  </li>;
}

function ApplicationCard({ row, scopes, mutate }) {
  const [note, setNote] = useState('');
  const e = row.evidence;
  const path = '/applications/' + row.id;
  // 向服务端提交教师正在查看的版本和摘要。遇到冲突只刷新列表，由教师再次作出决定。
  function review(decision) {
    mutate(path + '/review', { decision, version: e.version, digest: e.digest, note: note.trim() },
      decision === 'approved' ? '已批准此版本。' : '已驳回此版本。');
  }
  return <article className="training-card">
    <h4>报告 {e.report_id} · {decisions[row.decision]}</h4>
    <p>训练任务 {e.training_id} · 证据版本 {e.version}</p>
    <p>证据摘要 <code style={{ overflowWrap: 'anywhere' }}>{e.digest}</code></p>
    {row.reviewed_at && <p>审核于 {localDate(row.reviewed_at)} {row.review_note}</p>}
    {row.decision === 'pending' && scopes.has('credential.approve') && <div className="training-row">
      <label>审核意见 <input maxLength={500} value={note} onChange={(ev) => setNote(ev.target.value)} /></label>
      <button type="button" onClick={() => review('approved')}>批准此版本</button>
      <button type="button" onClick={() => review('rejected')}>驳回此版本</button>
    </div>}
    {row.decision === 'approved' && !row.certificates.length && scopes.has('credential.issue')
      && <button type="button" onClick={() => mutate(path + '/issue', {}, '已签发证书。')}>签发证书</button>}
    {row.certificates.length > 0 && <ul className="training-list">{row.certificates.map((cert, i) =>
      <Certificate key={cert.id} cert={cert} latest={i === row.certificates.length - 1}
        canRevoke={scopes.has('credential.revoke')} canReissue={scopes.has('credential.reissue')} mutate={mutate} />
    )}</ul>}
  </article>;
}

function StudentApplications({ request, studentId, scopes }) {
  const [cursors, setCursors] = useState(['']);
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState(null);
  const [notice, setNotice] = useState('');
  const [saving, setSaving] = useState(false);
  const writing = useRef(false);
  const cursor = cursors[cursors.length - 1];
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const path = '/students/' + encodeURIComponent(studentId) + '/applications?limit=20&after=' + cursor;
        const data = await request(base + path, { signal: controller.signal });
        if (!Array.isArray(data?.items) || !data.items.every((r) => validApplication(r, studentId))
            || (data.next != null && (typeof data.next !== 'string' || !applicationId.test(data.next)
                || data.next <= cursor))) {
          throw new Error('申请列表与当前学生或版本不符，请重新读取。');
        }
        if (!controller.signal.aborted) setResult({ cursor, revision, data });
      } catch (err) {
        if (!controller.signal.aborted) setResult({ cursor, revision, error: readError(err) });
      }
    }
    load();
    return () => controller.abort();
  }, [request, studentId, cursor, revision]);
  const page = result?.cursor === cursor && result.revision === revision ? result : null;

  async function mutate(path, body, success) {
    if (writing.current) return;
    writing.current = true;
    setSaving(true);
    setNotice('');
    try {
      await request(base + path, { method: 'POST', body: JSON.stringify(body) });
      setNotice(success);
    } catch (err) {
      setNotice(err.status === 409 ? '此申请、证据或证书的状态已变化，请核对刷新后的记录。' : readError(err));
    } finally {
      // 超时时服务端可能已提交。重新读取申请后再显示操作按钮，避免按旧状态重复操作。
      writing.current = false;
      setRevision((v) => v + 1);
      setSaving(false);
    }
  }

  return <section className="training-page" aria-label="教学证书管理">
    <header className="training-row"><h3>教学证书申请</h3><span>学生 {studentId}</span>
      <button type="button" disabled={saving} onClick={() => setRevision((v) => v + 1)}>刷新列表</button></header>
    {notice && <p role="status">{notice}</p>}
    {!page && <p role="status">正在读取申请…</p>}
    {page?.error && <p role="alert">{page.error}</p>}
    {page?.data && <fieldset disabled={saving} className="training-stack"><legend>当前页申请</legend>
      {!page.data.items.length && <p>暂无可查看的申请。</p>}
      {page.data.items.map((row) => <ApplicationCard key={row.id + ':' + row.evidence.digest}
        row={row} scopes={scopes} mutate={mutate} />)}
    </fieldset>}
    <nav aria-label="申请列表分页" className="training-row">
      {cursors.length > 1 && <button type="button" disabled={saving} onClick={() =>
        setCursors((old) => old.slice(0, -1))}>上一页</button>}
      {page?.data?.next && <button type="button" disabled={saving} onClick={() =>
        setCursors((old) => [...old, page.data.next])}>下一页</button>}
    </nav>
  </section>;
}

// 在已登录管理页使用 adminRequest 和当前会话的具体动作授权；服务端仍逐次核查权限。
export default function TeachingCredentialsPanel({ request, studentId, actions = [] }) {
  const scopes = new Set(actions);
  if (!scopes.has('credential.read')) return null;
  if (typeof studentId !== 'string' || !studentId || /[\s/\\%]/.test(studentId) || ['.', '..'].includes(studentId)) {
    return <p role="status">请选择学生以查看教学证书。</p>;
  }
  // 切换学生时重建面板，避免上一名学生的表单、延迟回包和操作结果出现在新页面。
  return <StudentApplications key={studentId} request={request} studentId={studentId} scopes={scopes} />;
}
