import React, { useEffect, useRef, useState } from 'react';
import ReportReviewSection from './ReportReviewSection.jsx';
import { coverageLabel, reportStatusText, visibleReportScore } from '../../frontend/src/reportPresentation.js';

const reviewLabels = { approved: '已通过', rejected: '未通过', pending: '待复核' };
const sourceLabels = { teacher: '教师改分', generated: '系统生成', legacy: '原始报告' };

export default function VersionedReportPanel({ reportId, canReview, canAdjust, request, onSaved }) {
  const [history, setHistory] = useState(null);
  const [version, setVersion] = useState(null);
  const [note, setNote] = useState('');
  const [score, setScore] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0);
  const active = useRef(false);
  const saving = useRef(false);
  const path = `/api/admin/reports/${encodeURIComponent(reportId)}`;

  function clearDraft() {
    setNote('');
    setScore('');
    setReason('');
  }

  useEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setHistory(null);
    clearDraft();
    setError('');
    request(`${path}/history`, { signal: controller.signal }).then(payload => {
      if (controller.signal.aborted) return;
      if (payload.report?.id !== reportId || !Array.isArray(payload.reviews)
          || !Array.isArray(payload.versions) || !payload.versions.some(v => v.version === payload.report.version)) {
        throw new Error('报告版本数据不完整，请重新读取。');
      }
      setVersion(payload.report.version);
      setHistory(payload);
    }).catch(failure => {
      if (!controller.signal.aborted) setError(failure.message || '报告历史暂时无法读取。');
    });
    return () => controller.abort();
  }, [path, reportId, request, refresh]);

  const entry = history?.versions.find(v => v.version === version);
  const current = entry && version === history.report.version;
  const snapshot = entry?.snapshot || {};
  const reviews = history?.reviews.filter(r => r.version === version) || [];

  async function submit(kind, status) {
    if (saving.current || !current) return;
    const isScore = kind === 'score';
    if (isScore ? !canAdjust : !canReview) return;
    const scoreValue = Number(score);
    if (isScore && (!/^\d{1,3}$/.test(score) || scoreValue > 100 || !reason.trim())) {
      setError('请填写 0–100 的整数总分和改分理由。');
      return;
    }
    if (!isScore && !note.trim()) {
      setError('请填写本版本的复核意见。');
      return;
    }
    saving.current = true;
    setBusy(true);
    setNotice('');
    setError('');
    try {
      const body = isScore ? { total_score: scoreValue, reason: reason.trim() } : { status, note: note.trim() };
      const result = await request(`${path}/${kind}`, {
        method: 'PATCH', body: JSON.stringify({ ...body, expected_version: version }),
      });
      if (!active.current) return;
      onSaved?.(result.report);
      setNotice(isScore ? '改分已保存，新版本待复核。' : '复核意见已保存。');
      setHistory(null);
      setRefresh(n => n + 1);
    } catch (failure) {
      if (!active.current) return;
      // 请求超时后，服务端可能已提交修改。重试前须重新读取服务端记录，
      // 不得自动重发写请求。
      setHistory(null);
      clearDraft();
      const conflict = failure.status === 409;
      setError(conflict ? `${failure.message} 请重新读取报告、核对证据后再提交。` : failure.message || '请重新读取报告确认保存结果。');
    } finally {
      saving.current = false;
      if (active.current) setBusy(false);
    }
  }

  return <section className="detail-block revision-panel" aria-label="报告版本与教师审核">
    <h3>报告版本与教师审核</h3>
    {error && <p role="alert" className="page-message error">{error}</p>}
    {notice && <p role="status" className="page-message success">{notice}</p>}
    {!entry ? error
      ? <button type="button" className="secondary-button" onClick={() => setRefresh(n => n + 1)}>重新读取报告</button>
      : <p role="status">正在核验访问权限并读取报告版本…</p>
      : <>
        <label className="field-block">查看报告版本
          <select value={version} disabled={busy} onChange={e => {
            setVersion(Number(e.target.value)); clearDraft(); setNotice(''); setError('');
          }}>
            {history.versions.map(v => <option key={v.version} value={v.version}>版本 {v.version} · {sourceLabels[v.source] || v.source}{v.version === history.report.version ? '（当前）' : ''}</option>)}
          </select>
        </label>
        <div className="detail-grid">
          <div><span>本版总分</span><strong>{visibleReportScore(snapshot) ?? '—'}</strong></div>
          <div><span>评分覆盖</span><strong>{coverageLabel(snapshot) || reportStatusText(snapshot)}</strong></div>
          <div><span>复核状态</span><strong>{reviewLabels[reviews[0]?.status || snapshot.review_status] || '待复核'}</strong></div>
          <div><span>版本时间</span><strong>{entry.created_at}</strong></div>
        </div>
        {entry.reason && <p><strong>改分依据</strong>　{entry.reason} · {entry.actor_id}</p>}
        {entry.evidence_version && <details><summary>证据版本标识</summary><code>{entry.evidence_version}</code></details>}
        {snapshot.summary && <p><strong>报告摘要</strong>　{snapshot.summary}</p>}
        {snapshot.suggestions && <p><strong>提升建议</strong>　{snapshot.suggestions}</p>}
        <ReportReviewSection kind="feedback" value={snapshot.agent_feedback} />
        <ReportReviewSection kind="timeline" value={snapshot.timeline_review} />
        <h4>本版复核记录</h4>
        {reviews.length ? <ol>{reviews.map(r => <li key={r.id}>
          <strong>{reviewLabels[r.status]}</strong> · {r.actor_id || '原记录未登记'} · {r.created_at}
          {r.note && <p>{r.note}</p>}
        </li>)}</ol> : <p>暂无复核记录。</p>}
        {!current && <p>历史版本只读。请切换到当前版本后操作。</p>}
        {current && canReview && <fieldset disabled={busy}><legend>对版本 {version} 提交意见</legend>
          <label className="field-block">复核意见<textarea rows={2} maxLength={2000} value={note} onChange={e => setNote(e.target.value)} /></label>
          <div className="revision-actions"><button type="button" className="secondary-button danger" disabled={!note.trim()} onClick={() => submit('review', 'rejected')}>标记未通过</button>
            <button type="button" className="primary-button" disabled={!note.trim()} onClick={() => submit('review', 'approved')}>通过复核</button></div>
        </fieldset>}
        {current && canAdjust && ['succeeded','degraded'].includes(snapshot.generation_status) && <fieldset disabled={busy}><legend>调整本场总分</legend>
          <label className="field-block">调整后总分<input type="number" min="0" max="100" step="1" value={score} onChange={e => setScore(e.target.value)} /></label>
          <label className="field-block">改分理由<textarea rows={2} maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></label>
          <button type="button" className="secondary-button" disabled={!reason.trim() || !score} onClick={() => submit('score')}>保存改分并建立新版</button>
        </fieldset>}
      </>}
  </section>;
}
