/** 独立的职员维护流程。先按精确编号核对目标，变更时回送同一次查询取得的版本。 */
import React, { useEffect, useRef, useState } from 'react';

export default function NativeStaffMaintenance({ request, admin }) {
  const grants = new Set(admin.permissions);
  const [op, setOp] = useState(grants.has('staff.profile.write') ? 'profile' : 'password-reset');
  const [id, setId] = useState('');
  const [row, setRow] = useState(null);
  const [name, setName] = useState('');
  const [secret, setSecret] = useState('');
  const [message, tell] = useState('');
  const [busy, setBusy] = useState(false);
  const epoch = useRef(0);
  useEffect(() => () => { epoch.current += 1; }, []);
  useEffect(() => {
    if (!secret) return;
    const timer = setTimeout(() => setSecret(''), 5 * 60 * 1000);
    return () => clearTimeout(timer);
  }, [secret]);

  function clear() {
    epoch.current += 1; setRow(null); setSecret(''); tell(''); setName('');
  }
  function path() {
    if (!id.trim() || /[\s/%\\]/u.test(id) || ['.', '..'].includes(id)) throw new Error('职员编号格式无效。');
    return '/api/admin/identity/v1/staff/' + encodeURIComponent(id) + '/' + op;
  }
  async function act(write) {
    if (busy) return;
    if (write && !window.confirm('已核对 '+row.name+'（'+row.email+'）及本次操作？')) return;
    setBusy(true); tell(''); setSecret('');
    const stamp = ++epoch.current;
    try {
      const params = !write ? {} : { method: op === 'profile' ? 'PATCH' : 'POST',
        body: JSON.stringify({ expected_revision: row.revision, ...(op === 'profile' ? { name: name.trim() } : {}) }) };
      const data = await request(path(), params);
      if (epoch.current !== stamp) return;
      if (write && op === 'password-reset') { setRow(null); setSecret(data.temporary_password); tell('旧会话已撤销，职员下次登录必须先改密。'); }
      else { setRow(data); setName(data.name); if (write) tell('职员资料已更新。'); }
    } catch (err) { if (epoch.current === stamp) { setRow(null); tell(err.message); } }
    finally { if (epoch.current === stamp) setBusy(false); }
  }
  return <section className="training-card"><h3>职员资料与密码维护</h3>
    <form onSubmit={e => { e.preventDefault(); act(false); }}><fieldset disabled={busy}>
      <label>办理事项 <select value={op} onChange={e => { clear(); setOp(e.target.value); }}>
        {grants.has('staff.profile.write') && <option value="profile">修改姓名</option>}
        {grants.has('staff.password.reset') && <option value="password-reset">强制重置密码</option>}
      </select></label>
      <label>本校职员编号 <input required maxLength={128} value={id} onChange={e => { clear(); setId(e.target.value); }}/></label>
      <button>核对职员</button>
    </fieldset></form>
    {row && <form onSubmit={e => { e.preventDefault(); act(true); }}><fieldset disabled={busy}>
      <legend>{row.name} · {row.email} · {row.actor_id}</legend>
      {op === 'profile' && <label>新姓名 <input required maxLength={160} value={name} onChange={e => setName(e.target.value)}/></label>}
      <button>{op === 'profile' ? '保存姓名' : '撤销原会话并补发临时密码'}</button>
    </fieldset></form>}
    {message && <p role="status">{message}</p>}
    {secret && <p>本次临时密码 <code>{secret}</code> <button onClick={() => setSecret('')}>已发放，清除</button></p>}
  </section>;
}
