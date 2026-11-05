import React, { useEffect, useRef, useState } from 'react';
import { localDate, readError } from './trainingUi.js';
import './training.css';

const endpoint = '/api/credentials';
const decisions = { pending: '待教师审核', approved: '审核通过', rejected: '申请已驳回' };

function verificationUrl(certificate) {
  const path = '/verify/' + certificate.id;
  const value = certificate.verification_url;
  if (!/^[0-9a-f]{32}$/.test(certificate.id) || typeof value !== 'string') return null;
  // 分享链接仅接受与证书序号匹配的验真路径。用普通链接打开，避免将校内 API 请求头发往外站。
  if (value !== path && !/^https?:\/\//.test(value)) return null;
  try {
    const url = new URL(value, window.location.origin);
    const local = ['localhost', '[::1]'].includes(url.hostname) || /^127(?:\.\d{1,3}){3}$/.test(url.hostname);
    const safe = url.protocol === 'https:' || (local && url.protocol === 'http:');
    return safe && !url.username && !url.password && !url.search && !url.hash && url.pathname === path
      ? url.href : null;
  } catch {
    return null;
  }
}

function downloadProof(certificate) {
  // 导出学校签名文件；申请详情和教师审核意见留在已登录页面。
  const file = new Blob([JSON.stringify(certificate.proof, null, 2)], { type: 'application/json' });
  const href = URL.createObjectURL(file);
  const link = document.createElement('a');
  link.href = href;
  link.download = 'teaching-credential-' + certificate.id + '.json';
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(href), 1000);
}

function Certificate({ certificate }) {
  const [notice, setNotice] = useState('');
  const href = verificationUrl(certificate);
  async function copy() {
    try {
      await navigator.clipboard.writeText(href);
      setNotice('验真链接已复制。');
    } catch {
      setNotice('请使用“公开验真链接”的复制链接功能。');
    }
  }
  return <section className="training-output training-stack">
    <h4>第 {certificate.generation} 版证书 · {certificate.revoked_at ? '已撤销' : '已签发'}</h4>
    <p>签发于 {localDate(certificate.issued_at)}{certificate.revoked_at && '，撤销于 ' + localDate(certificate.revoked_at)}</p>
    <div className="training-row">
      {href && <><a href={href} target="_blank" rel="noopener noreferrer">公开验真链接</a>
        <button type="button" onClick={copy}>复制链接</button></>}
      {certificate.proof && <button type="button" onClick={() => downloadProof(certificate)}>下载学校签名凭证（JSON）</button>}
    </div>
    {notice && <small role="status">{notice}</small>}
  </section>;
}

function Application({ item }) {
  return <li>
    <h3>报告 {item.evidence.report_id} · 第 {item.evidence.version} 版</h3>
    <p>{decisions[item.decision] || '审核状态待确认'} · 申请于 {localDate(item.created_at)}</p>
    {item.review_note && <p>审核意见：{item.review_note}</p>}
    {item.certificates.map((cert) => <Certificate key={cert.id} certificate={cert} />)}
  </li>;
}

// 父组件按登录身份设置 key，切换账号时清空申请列表和提交状态。
export default function TeachingCredentials({ request, reportId }) {
  const [input, setInput] = useState('');
  const [history, setHistory] = useState(['']);
  const [revision, setRevision] = useState(0);
  const [page, setPage] = useState(null);
  const [sending, setSending] = useState(false);
  const [feedback, setFeedback] = useState(null);
  const submission = useRef(null);
  const after = history[history.length - 1];
  const report = (reportId || input).trim();
  const active = page?.request === request && page.after === after && page.revision === revision ? page : null;

  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({ limit: '10', after });
    request(endpoint + '/me/applications?' + query, { signal: controller.signal })
      .then(({ items, next }) => {
        if (!controller.signal.aborted) setPage({ request, after, revision, items, next });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setPage({ request, after, revision, error: readError(error) });
      });
    return () => controller.abort();
  }, [request, after, revision]);

  useEffect(() => () => submission.current?.abort(), []);

  async function apply(event) {
    event.preventDefault();
    if (submission.current || !/^[a-zA-Z0-9_-]{1,128}$/.test(report)) return;
    const controller = new AbortController();
    submission.current = controller;
    setSending(true);
    setFeedback(null);
    try {
      const item = await request(endpoint + '/applications', {
        method: 'POST', signal: controller.signal, body: JSON.stringify({ report_id: report }),
      });
      if (controller.signal.aborted) return;
      setFeedback({ text: '报告 ' + item.evidence.report_id + ' 第 ' + item.evidence.version +
        ' 版的申请状态为“' + (decisions[item.decision] || '待确认') + '”。' });
      setHistory(['']);
      setRevision((n) => n + 1);
    } catch (error) {
      if (!controller.signal.aborted) setFeedback({ error: readError(error) });
    } finally {
      if (!controller.signal.aborted) setSending(false);
      submission.current = null;
    }
  }

  return <section className="training-page training-candidate">
    <header><h2>我的教学证书</h2>
      <p className="training-meta">完成模拟面试训练后，可用已发布的报告申请训练完成证明。</p></header>
    <form className="training-card" onSubmit={apply}>
      <label className="training-field">报告编号
        <input required value={reportId || input} onChange={(event) => setInput(event.target.value)}
          readOnly={Boolean(reportId)} maxLength={128} pattern="[a-zA-Z0-9_\-]{1,128}" placeholder="输入本人的报告编号" />
      </label>
      <p className="training-meta">同一版本重复申请会返回已有记录。更新后的报告须重新申请和审核。</p>
      <div><button className="training-primary" type="submit" disabled={sending || !report}>
        {sending ? '正在提交…' : '申请教学证书'}</button></div>
      {feedback && <p role={feedback.error ? 'alert' : 'status'}>{feedback.error || feedback.text}</p>}
    </form>
    <section className="training-card">
      <div className="training-row training-between"><h2>申请与签发记录</h2>
        <button type="button" onClick={() => setRevision((n) => n + 1)}>刷新记录</button></div>
      <p className="training-meta">公开验真链接显示当前有效或撤销状态。下载的签名凭证记录签发时的信息。</p>
      {!active ? <p role="status">正在读取申请…</p> : active.error ? <p role="alert">{active.error}</p>
        : active.items.length ? <ul className="training-list">{active.items.map((item) =>
          <Application key={item.id} item={item} />)}</ul> : <p>尚无证书申请。</p>}
      <div className="training-row" aria-label="申请分页">
        <button type="button" disabled={history.length === 1}
          onClick={() => setHistory((pages) => pages.slice(0, -1))}>上一页</button>
        <span>第 {history.length} 页</span>
        <button type="button" disabled={!active?.next}
          onClick={() => setHistory((pages) => [...pages, active.next])}>下一页</button>
      </div>
    </section>
  </section>;
}
