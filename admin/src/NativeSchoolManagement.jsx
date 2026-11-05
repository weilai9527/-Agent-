import React, { useCallback, useEffect, useRef, useState } from 'react';
import { LockKeyhole, RefreshCw, School } from 'lucide-react';
import NativeSchoolOrganization from './NativeSchoolOrganization.jsx';
import NativeStudentAccounts from './NativeStudentAccounts.jsx';
import NativeStaffMaintenance from './NativeStaffMaintenance.jsx';
import NativeStaffGrants from './NativeStaffGrants.jsx';
import NativeRegistrationBook from './NativeRegistrationBook.jsx';
import NativePermissionRequests from './NativePermissionRequests.jsx';
import './nativeSchoolManagement.css';

const actions = {
  'student.import': '开通学生账号', 'student.status': '变更学生状态', 'student.reset': '重置学生密码',
  'student.login': '学生登录', 'student.password.change': '学生修改密码', 'staff.login': '教职工登录',
  'organization.class.staff.replace': '变更班级任课分配', 'student.grants.replace': '更新学生动作授权',
  'staff.create': '创建教职工', 'staff.grants.replace': '更新教职工授权', 'identity.cutover': '迁入历史账号',
  'organization.import': '导入组织结构', 'organization.import.class': '维护班级',
  'roster.import': '导入名册', 'roster.import.student': '变更学生归班',
};

function SessionHeader({ admin }) {
  return <header className="native-school-session">
    <span className="native-school-mark"><School size={24} aria-hidden="true" /></span>
    <div><span>当前学校</span><strong>{admin.school_id}</strong></div>
    <div><span>已登录</span><strong>{admin.name} · {admin.actorType === 'teacher' ? '教师' : '管理员'}</strong></div>
    <span className="native-school-tenant"><LockKeyhole size={14} aria-hidden="true" /> 教务操作仅限本校</span>
  </header>;
}

function AuditHistory({ request, schoolId }) {
  const [filters, setFilters] = useState({ action: '', actor: '' });
  const [page, setPage] = useState({ cursors: [''], index: 0 });
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({ limit: '30' });
    if (filters.action) query.set('action', filters.action);
    if (filters.actor) query.set('actor_id', filters.actor);
    if (page.cursors[page.index]) query.set('before', page.cursors[page.index]);
    setResult(null);
    setError('');
    request('/api/admin/identity/v1/audit?' + query, { signal: controller.signal }).then(data => {
      if (controller.signal.aborted) return;
      if (data.school_id !== schoolId || !Array.isArray(data.items)) throw new Error('审计结果与当前学校不匹配。');
      setResult(data);
    }).catch(err => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [request, schoolId, filters, page, revision]);

  function search(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setFilters({ action: form.get('action').trim(), actor: form.get('actor').trim() });
    setPage({ cursors: [''], index: 0 });
  }
  return <section aria-label="学校审计记录">
    <div className="native-school-line"><h2>学校审计记录</h2>
      <button type="button" onClick={() => setRevision(v => v + 1)}><RefreshCw size={14} /> 刷新记录</button></div>
    <form className="native-school-search" onSubmit={search}>
      <label>操作动作<input name="action" list="school-audit-actions" maxLength={128} placeholder="全部动作" /></label>
      <datalist id="school-audit-actions">{Object.entries(actions).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</datalist>
      <label>操作人 ID<input name="actor" maxLength={128} placeholder="全部操作人" /></label>
      <button type="submit">查询记录</button>
    </form>
    {error && <p role="alert">{error}</p>}
    {!error && !result && <p role="status">正在读取本校审计记录…</p>}
    {result && (result.items.length ? <><div className="native-school-scroll"><table><thead><tr>
      <th>时间</th><th>动作</th><th>操作人 / 对象</th><th>结果与记录</th>
    </tr></thead><tbody>{result.items.map(row => <tr key={row.id}>
      <td><time>{String(row.created_at).replace('T', ' ')}</time></td>
      <td>{actions[row.action] || row.action}{actions[row.action] && <small>{row.action}</small>}</td>
      <td>{row.actor_id || '未记录'}<small>{row.target_id || '无对象'}</small></td>
      <td>{row.success ? '成功' : '失败'}{row.summary && <details><summary>查看详情</summary><pre>{row.summary}</pre></details>}</td>
    </tr>)}</tbody></table></div>
    <div className="native-school-pages"><button type="button" disabled={!page.index} onClick={() => setPage(p => ({ ...p, index: p.index - 1 }))}>上一页</button>
      <span>第 {page.index + 1} 页</span>
      <button type="button" disabled={!result.next} onClick={() => setPage(p => ({ cursors: [...p.cursors.slice(0, p.index + 1), result.next], index: p.index + 1 }))}>下一页</button>
    </div></> : <p>当前筛选条件下没有审计记录。</p>)}
  </section>;
}

export default function NativeSchoolManagement({ request, admin, permissions, onExpired, initialTab = null }) {
  const tabs = [
    ['organization', '组织与名册', permissions.canReadOrganization || permissions.canManageNativeOrganization || permissions.canImportRoster, NativeSchoolOrganization],
    ['registrations', '注册名单与开通待办', permissions.canUseRegistrationBook, NativeRegistrationBook],
    ['students', '学生账号', permissions.canReadStudentProfile || permissions.canReadStudentAccounts || permissions.canImportStudentAccounts || permissions.canResetStudentPasswords || permissions.canSetStudentStatus || permissions.canManageStudentGrants, NativeStudentAccounts],
    ['staffMaintenance', '职员资料与密码', permissions.canMaintainStaffProfiles, NativeStaffMaintenance],
    ['staff', '教职工授权', permissions.canManageStaff, NativeStaffGrants],
    ['requests', '权限申请与审批', permissions.canRequestStaffAccess, NativePermissionRequests],
    ['audit', '学校审计', permissions.canReadIdentityAudit, AuditHistory],
  ].filter(([, , allowed]) => allowed);
  const [tab, setTab] = useState(initialTab);
  const active = tabs.find(([id]) => id === tab) || tabs[0];
  const expired = useRef(onExpired);
  useEffect(() => { expired.current = onExpired; }, [onExpired]);
  const checkedRequest = useCallback(async (...args) => {
    try { return await request(...args); }
    catch (error) {
      if (error.status === 401) expired.current();
      throw error;
    }
  }, [request]);
  if (!active) return null;
  const [id, label, , Panel] = active;
  return <div className="native-school"><SessionHeader admin={admin} />
    <nav aria-label="学校管理功能" className="native-school-nav">
      {tabs.map(([key, title]) => <button type="button" key={key} aria-current={id === key ? 'page' : undefined} onClick={() => setTab(key)}>{title}</button>)}
    </nav>
    <div className="native-school-body" key={id} role="region" aria-label={label}>
      <Panel request={checkedRequest} permissions={permissions} schoolId={admin.school_id} admin={admin} />
    </div>
  </div>;
}
