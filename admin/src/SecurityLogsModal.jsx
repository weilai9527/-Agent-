import React, { useEffect, useState } from 'react';
import { ShieldCheck, X } from 'lucide-react';
import { securityLogParams } from './securityLogQuery.js';

export default function SecurityLogsModal({ request, onClose }) {
  const [form, setForm] = useState({ event_type: '', request_id: '', actor_id: '', since: '', until: '' });
  const [query, setQuery] = useState({ offset: 0, until: new Date().toISOString() });
  const [payload, setPayload] = useState({ events: [], total: 0, hasMore: false });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    setSelected(null);
    const params = securityLogParams(query);
    request(`/api/admin/security-logs?${params}`, { signal: controller.signal })
      .then((data) => { if (!controller.signal.aborted) setPayload(data); })
      .catch((failure) => { if (!controller.signal.aborted) setError(failure.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [query, request]);

  function search(event) {
    event.preventDefault();
    setQuery({
      offset: 0,
      event_type: form.event_type.trim(), request_id: form.request_id.trim(), actor_id: form.actor_id.trim(),
      since: form.since ? new Date(form.since).toISOString() : '',
      until: form.until ? new Date(form.until).toISOString() : new Date().toISOString(),
    });
  }

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="安全审计" onClick={onClose}>
      <div className="modal-card clog-modal" onClick={(event) => event.stopPropagation()}>
        <header>
          <span><ShieldCheck size={18} />安全审计</span>
          <button className="icon-button" type="button" onClick={onClose} aria-label="关闭安全审计"><X size={15} /></button>
        </header>
        <div className="security-logs-content">
          <p className="form-hint">查看启用新审计后记录的账号操作、权限拒绝和操作异常。时间按本机时区显示。</p>
          <form className="security-log-filters" onSubmit={search}>
            {[
              ['event_type', '事件类型', '如 student.login'],
              ['request_id', '请求 ID', '精确匹配请求 ID'],
              ['actor_id', '操作者 ID', '精确匹配用户 ID'],
            ].map(([field, label, placeholder]) => (
              <label className="field-block" key={field}><span>{label}</span>
                <input value={form[field]} placeholder={placeholder} maxLength={field === 'request_id' ? 32 : 80}
                  onChange={(event) => setForm((current) => ({ ...current, [field]: event.target.value }))} />
              </label>
            ))}
            {['since', 'until'].map((field) => (
              <label className="field-block" key={field}><span>{field === 'since' ? '开始时间' : '结束时间'}</span>
                <input type="datetime-local" value={form[field]}
                  onChange={(event) => setForm((current) => ({ ...current, [field]: event.target.value }))} />
              </label>
            ))}
            <button className="primary-button" disabled={loading} type="submit">查询 / 刷新</button>
          </form>
          {error && <div className="page-message error" role="alert">{error}</div>}
          {loading && <p role="status">正在读取安全审计…</p>}
          {!loading && !error && <>
            <div className="table-wrap connection-log-table">
              <table><thead><tr><th>时间</th><th>事件</th><th>操作者</th><th>结果</th><th>来源 IP</th><th>详情</th></tr></thead>
                <tbody>{payload.events.map((item) => <tr key={item.event_id}>
                  <td>{new Date(item.occurred_at).toLocaleString('zh-CN', { hour12: false })}</td>
                  <td><strong>{item.event_type}</strong><small>{item.method} {item.route}</small></td>
                  <td>{item.actor_id || item.attempted_account || '未认证'}<small>{item.actor_type || ''}</small></td>
                  <td><span className={`connection-level ${item.success ? 'info' : 'error'}`}>{item.success ? '成功' : '失败'}</span><small>HTTP {item.status_code}</small></td>
                  <td>{item.client_ip}</td>
                  <td><button className="table-view-button" type="button" onClick={() => setSelected(item)}>详情</button></td>
                </tr>)}
                {payload.events.length === 0 && <tr><td colSpan="6">当前条件下暂无安全审计记录。</td></tr>}
                </tbody>
              </table>
            </div>
            <div className="security-log-pagination">
              <span>共 {payload.total} 条 · 第 {Math.floor(query.offset / 50) + 1} 页</span>
              <button className="secondary-button" type="button" disabled={query.offset === 0}
                onClick={() => setQuery((current) => ({ ...current, offset: Math.max(0, current.offset - 50) }))}>上一页</button>
              <button className="secondary-button" type="button" disabled={!payload.hasMore}
                onClick={() => setQuery((current) => ({ ...current, offset: current.offset + 50 }))}>下一页</button>
            </div>
            {selected && <section className="security-log-detail">
              <h3>审计详情</h3>
              <dl>{[
                ['请求 ID', selected.request_id], ['原因', selected.reason], ['服务', selected.service],
                ['处理耗时', `${selected.duration_ms} ms`], ['响应是否完整', selected.response_complete ? '是' : '否'],
                ['操作对象', selected.target_id || Object.values(selected.targets || {}).join('、') || '—'],
                ['异常类型', selected.error_type || '—'],
              ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
            </section>}
          </>}
        </div>
      </div>
    </div>
  );
}
