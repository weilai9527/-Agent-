import React, { useEffect, useState } from 'react';

const url = '/api/admin/usage/quota';
const resources = { text: '模型文字请求', media: '媒体操作准入' };

export default function SchoolUsagePage({ request, canManage }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    setData(null);
    request(url, { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) setData(value);
    }).catch(err => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [request, reload]);
  async function save(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError('');
    setBusy(true);
    try {
      const limits = Object.fromEntries(Object.keys(resources).map(key => [key, Number(form.get(key))]));
      setData(await request(url, { method: 'PUT', body: JSON.stringify(limits) }));
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return <section className="training-page"><div className="training-row"><h2>学校月度用量</h2>
    <button type="button" disabled={busy} onClick={() => setReload(n => n + 1)}>刷新</button></div>
    {error && <p role="alert">{error}</p>}
    {data ? <><p>{data.period} · 单位为已计量的请求及操作次数</p>
      <table><thead><tr><th>资源</th><th>月度额度</th><th>已用</th><th>预留</th><th>可用</th></tr></thead>
        <tbody>{Object.entries(resources).map(([k, label]) => <tr key={k}><th>{label}</th>
          {['limit', 'used', 'reserved', 'available'].map(field => <td key={field}>{data[k][field]}</td>)}</tr>)}</tbody></table>
      {canManage && <form onSubmit={save} className="training-card"><fieldset disabled={busy}><legend>调整月度额度</legend>
        {Object.entries(resources).map(([k, label]) => <label key={k}>{label}
          <input name={k} type="number" min="0" max="1000000000000" step="1" required defaultValue={data[k].limit} /></label>)}
        <button type="submit">保存额度</button></fieldset></form>}
    </> : !error && <p role="status">正在读取用量…</p>}
  </section>;
}
