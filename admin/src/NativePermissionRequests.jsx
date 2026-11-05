import React, { useEffect, useRef, useState } from 'react';
import { staffActionName } from './NativeStaffGrants.jsx';

const prefix = '/api/admin/identity/v1';
const statuses = { pending: '待审批', approved: '已通过', rejected: '未通过', stale: '授权已变更，须重新申请' };
const pageSize = 50;

export default function NativePermissionRequests({ request, admin, permissions, schoolId }) {
  const [mode, setMode] = useState('mine');
  const [filter, setFilter] = useState('pending');
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const pending = useRef(null);
  const retryKey = useRef(null);
  const manager = admin.actorType === 'admin' && permissions.canManageStaff;
  const review = mode === 'queue' && manager;
  const canRead = admin.school_id === schoolId && permissions.canRequestStaffAccess;
  const route = review ? '/permission-requests' : '/me/permission-requests';
  const pageKey = JSON.stringify([schoolId, admin.id, route, filter, offset, revision]);
  const result = data?.key === pageKey ? data.response : null;

  useEffect(() => {
    if (!canRead) return undefined;
    const controller = new AbortController();
    setError('');
    request(prefix + route + '?offset=' + offset + (review ? '&status=' + filter : ''), { signal: controller.signal })
      .then(response => {
        if (controller.signal.aborted) return;
        if (response.school_id !== schoolId || !Array.isArray(response.items)
            || response.items.some(row => row.school_id !== schoolId || (!review && row.applicant !== admin.id))
            || (!review && !Array.isArray(response.actions))) throw new Error('申请记录不属于当前账号或学校。');
        setData({ key: pageKey, response });
      }).catch(err => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [request, pageKey, route, review, filter, offset, canRead, schoolId, admin.id]);
  useEffect(() => () => pending.current?.abort(), []);

  async function submit(event, row, status) {
    event.preventDefault();
    if (pending.current || !result) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    let path;
    let body;
    if (row) {
      if (!review || row.applicant === admin.id || row.status !== 'pending') return;
      const note = fields.get('note').trim();
      if (!note) { setError('请填写审批意见。'); return; }
      path = prefix + '/permission-requests/' + encodeURIComponent(row.id) + '/decision';
      body = { status, note };
    } else {
      const actions = fields.getAll('action');
      const classes = [...new Set(String(fields.get('classes') || '').trim().split(/[\s,，]+/).filter(Boolean))];
      const reason = fields.get('reason').trim();
      if ((!actions.length && !classes.length) || !reason) { setError('请选择权限或填写班级编号，并说明申请原因。'); return; }
      path = prefix + '/me/permission-requests';
      const signature = JSON.stringify([actions, classes, reason]);
      if (retryKey.current?.signature !== signature) retryKey.current = { signature, id: crypto.randomUUID() };
      body = { actions, classes, reason, request_key: retryKey.current.id };
    }
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true); setNotice(''); setError('');
    try {
      await request(path, { method: 'POST', body: JSON.stringify(body), signal: controller.signal });
      if (controller.signal.aborted) return;
      retryKey.current = null;
      setNotice(row ? '审批结果已保存。' : '申请已提交。');
      setOffset(0); setRevision(n => n + 1);
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(err.message);
        // 写入被拒绝后，禁止控件继续按旧授权执行操作。
        if ([401, 403, 409].includes(err.status)) setData(null);
      }
    } finally {
      if (!controller.signal.aborted) setBusy(false);
      pending.current = null;
    }
  }

  if (!canRead) return null;
  return <section aria-label="职员权限申请">
    <div className="native-school-line"><h2>职员权限申请</h2><button type="button" disabled={busy} onClick={() => setRevision(n => n + 1)}>刷新申请</button></div>
    {manager && <label className="field-block">查看范围<select value={mode} disabled={busy} onChange={e => {
      setMode(e.target.value); setOffset(0); setNotice('');
    }}><option value="mine">我的申请</option><option value="queue">全校审批</option></select></label>}
    {review && <label className="field-block">处理状态<select disabled={busy} value={filter} onChange={e => {
      setFilter(e.target.value); setOffset(0);
    }}>{Object.entries(statuses).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>}
    {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
    {!result && !error && <p role="status">正在读取申请。</p>}
    {result && <>
      {!review && <form className="settings-form" onSubmit={e => submit(e)} key={revision}>
        <fieldset disabled={busy}><legend>提交权限申请</legend>
          <div className="permission-checklist">{result.actions.map(action => <label key={action} className="permission-check">
            <input type="checkbox" name="action" value={action} /><span>{staffActionName(action)}</span>
          </label>)}</div>
          {!result.school_wide && <label className="field-block">申请负责的班级编号<input name="classes" maxLength={1500} placeholder="填写学校提供的班级编号，多个编号用逗号分隔" /></label>}
          <label className="field-block">申请原因<textarea name="reason" required maxLength={1000} /></label>
          <button type="submit">提交申请</button>
        </fieldset>
      </form>}
      <h3>{review ? '本校记录' : '我的记录'}</h3>
      {result.items.length === 0 && <p>暂无申请记录。</p>}
      {result.items.map(row => <article key={row.id} className="detail-block">
        <strong>{statuses[row.status]}</strong> · {row.applicant_name || row.applicant} · {row.created_at}
        <p>申请动作　{row.actions.map(staffActionName).join('、') || '无'}</p>
        {row.classes.length > 0 && <p>班级编号　{row.classes.join('、')}</p>}
        <p>申请原因　{row.reason}</p>
        {row.reviewer && <p>审批人　{row.reviewer} · {row.decided_at} · {row.decision_note}</p>}
        {review && row.status === 'pending' && row.applicant !== admin.id && <form onSubmit={e => submit(e, row, e.nativeEvent.submitter?.value)}>
          <fieldset disabled={busy}><label className="field-block">审批意见<textarea name="note" maxLength={1000} required /></label>
            <button type="submit" value="rejected">驳回申请</button>
            <button type="submit" value="approved" disabled={row.classes.length > 0 && !permissions.canManageNativeOrganization}>批准申请</button>
          </fieldset>
        </form>}
      </article>)}
      <button type="button" disabled={busy || offset === 0} onClick={() => setOffset(n => n-pageSize)}>上一页</button>
      <button type="button" disabled={busy || !result.has_more} onClick={() => setOffset(n => n+pageSize)}>下一页</button>
    </>}
  </section>;
}
