import React, { useEffect, useState } from 'react';

const dimensions = { style: '交流风格', focus: '考察重点', depth: '追问深度' };
const roles = { technical: '技术面试官', architecture: '架构面试官', hr: 'HR 面试官' };

export default function InterviewerPolicyEditor({ request }) {
  const [policy, setPolicy] = useState(null);
  const [saved, setSaved] = useState(null);
  const [options, setOptions] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true); setError('');
    request('/api/admin/interviewer-policy').then(result => {
      if (live) { setPolicy(result.policy); setSaved(result.policy); setOptions(result.options); }
    }).catch(failure => { if (live) setError(failure.message); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [request, reload]);
  const dirty = JSON.stringify(policy) !== JSON.stringify(saved);
  function change(next) { setPolicy(next); setMessage(''); setError(''); }
  function toggle(key, item) {
    const allowed = policy.allowed[key].includes(item) ? policy.allowed[key].filter(value => value !== item) : [...policy.allowed[key], item];
    if (!allowed.length) { setError('每类策略至少保留一个选项。'); return; }
    change({ ...policy, allowed: { ...policy.allowed, [key]: allowed }, defaults: { ...policy.defaults, [key]: allowed.includes(policy.defaults[key]) ? policy.defaults[key] : allowed[0] } });
  }
  async function save(event) {
    event.preventDefault(); setSaving(true); setError(''); setMessage('');
    try {
      const result = await request('/api/admin/interviewer-policy', { method: 'PUT', body: JSON.stringify(policy) });
      setPolicy(result.policy); setSaved(result.policy); setMessage('策略已保存，新建面试立即使用；已有面试与评分标准保持不变。');
    } catch (failure) { setError(failure.message); }
    finally { setSaving(false); }
  }
  if (loading) return <p className="page-message">正在读取面试官策略…</p>;
  if (!policy) return <div className="settings-message error" role="alert">{error}<button className="secondary-button" type="button" onClick={() => setReload(value => value + 1)}>重新加载策略</button></div>;
  return <form className="interviewer-policy-editor settings-form" onSubmit={save}>
    <section className="provider-card"><div className="model-section-heading"><h3>学生可以怎样选择面试官</h3><p>设置默认风格与可选范围。策略在创建面试时保存到该场面试，重连与换轮次时继续使用。</p></div>
      <label className="policy-toggle"><input type="checkbox" checked={policy.studentCanChoose} disabled={saving} onChange={event => change({ ...policy, studentCanChoose: event.target.checked })} /><span>允许学生在面试前自主选择</span></label>
      {!policy.studentCanChoose && <p className="model-runtime-help">关闭后，客户端展示统一默认策略，学生不能修改。</p>}
      <div className="policy-dimensions">{Object.entries(dimensions).map(([key, label]) => <fieldset key={key} disabled={saving}><legend>{label}</legend><div className="policy-options">{options[key].map(item => <label key={item}><input type="checkbox" aria-label={`允许${label}：${item}`} checked={policy.allowed[key].includes(item)} onChange={() => toggle(key, item)} /><span>{item}</span></label>)}</div><label className="field-block"><span>默认{label}</span><select aria-label={`默认${label}`} value={policy.defaults[key]} onChange={event => change({ ...policy, defaults: { ...policy.defaults, [key]: event.target.value } })}>{policy.allowed[key].map(item => <option key={item}>{item}</option>)}</select></label></fieldset>)}</div>
    </section>
    <section className="provider-card"><div className="model-section-heading"><h3>各轮面试官的职责</h3><p>学生选择的风格与重点会在当前角色职责范围内应用，每次只问一个问题。</p></div><div className="policy-roles">{Object.entries(roles).map(([key, label]) => <fieldset key={key} disabled={saving}><legend>{label}</legend>{[['focus', '侧重点', 180], ['strategy', '提问策略', 240]].map(([field, name, limit]) => <label key={field} className="field-block"><span>{name}</span><textarea aria-label={`${label}${name}`} required maxLength={limit} rows={3} value={policy.roles[key][field]} onChange={event => change({ ...policy, roles: { ...policy.roles, [key]: { ...policy.roles[key], [field]: event.target.value } } })} /><small>最多 {limit} 字</small></label>)}</fieldset>)}</div></section>
    <div className="policy-preview"><strong>客户端默认效果</strong><p>{policy.defaults.style} · {policy.defaults.focus} · {policy.defaults.depth}</p><span>{policy.studentCanChoose ? '学生可在上面的范围内选择，开始面试后固定使用。' : '学生使用统一默认策略。'} 评分标准不随交流风格改变。</span></div>
    {error && <p className="settings-message error" role="alert">{error}</p>}
    {message && <p className="settings-message success" role="status">{message}</p>}
    <div className="model-save-bar"><span>{dirty ? '有未保存的策略修改' : '策略与已保存配置一致'}</span><div><button className="secondary-button" type="button" disabled={saving || !dirty} onClick={() => { change(saved); }}>撤销策略修改</button><button className="primary-button" type="submit" disabled={saving || !dirty}>{saving ? '保存中…' : '保存面试官策略'}</button></div></div>
  </form>;
}
