import React, { useEffect, useRef, useState } from 'react';

const endpoint = '/api/admin/identity/v1/staff';
const pageSize = 50;
const roleName = { teacher: '任课教师', admin: '管理员' };

// 可授予的操作由身份服务决定。这里的标签只说明当前学校服务返回的操作，
// 显示某个标签不会为账号授予相应权限。
const actionNames = {
  'interview.records.read': '查看面试记录',
  'report.read': '查看报告', 'report.review': '复核报告', 'report.export': '导出报告',
  'score.adjust': '调整评分', 'credential.read': '查看证书申请', 'credential.approve': '审批证书',
  'credential.issue': '签发证书', 'credential.revoke': '撤销证书', 'credential.reissue': '补发证书',
  'training.read': '查看教学任务', 'training.assign': '发布教学任务',
  'analytics.teaching.read': '查看教学分析', 'analytics.practice.assign': '布置针对性复练',
  'organization.read': '查看学校组织', 'organization.manage': '维护学校组织',
  'roster.import': '导入班级成员', 'student.read': '查看学生账号', 'staff.profile.write': '维护受管职员姓名', 'staff.password.reset': '重置受管职员密码',
  'registration.read': '查看登记名单', 'registration.export': '导出登记名单工作簿', 'registration.import': '导入或更新登记',
  'registration.issue': '开通登记账号', 'registration.status': '撤销开户和归档名单',
  'registration.reissue': '作废密码并补发', 'student.import': '创建学生账号',
  'student.reset': '重置学生密码', 'student.status': '启停学生账号',
  'permissions.manage': '管理教职工账号与授权', 'audit.read': '查看学校审计',
  'model.config.read': '查看模型配置', 'model.config.write': '修改模型配置',
  'program_jobs.read': '查看专业关联岗位', 'program_jobs.write': '配置专业关联岗位',
  'profile.student.read': '查看所管学生的教学档案摘要',
  'profile.settings.read': '查看简历表单学院和专业', 'profile.settings.write': '维护简历表单学院和专业',
  'catalog.admin.read': '查看岗位知识库', 'catalog.write': '编辑岗位知识库',
  'catalog.publish': '发布岗位知识库', 'catalog.import': '导入岗位知识库', 'catalog.review': '审核岗位建议',
  'posting.admin.read': '查看招聘岗位', 'posting.write': '编辑招聘岗位', 'posting.sync': '同步招聘岗位',
  'posting.import': '导入招聘岗位', 'posting.delete': '删除招聘岗位',
  'match.admin.read': '查看岗位匹配记录', 'jd.read': '查看职位描述', 'jd.write': '维护职位描述',
  'jd.delete': '删除职位描述', 'jd.approve': '审核职位描述',
  'usage.read': '查看学校用量', 'usage.configure': '调整学校额度',
};

export const staffActionName = action => actionNames[action] || action;
const strings = value => Array.isArray(value) && value.every(item => typeof item === 'string');
const validAccount = (row, schoolId) => row?.school_id === schoolId && typeof row.actor_id === 'string'
  && row.actor_id && typeof row.name === 'string' && typeof row.email === 'string'
  && Object.hasOwn(roleName, row.actor_type) && ['normal', 'disabled'].includes(row.status)
  && typeof row.school_wide === 'boolean' && strings(row.permissions)
  && typeof row.revision === 'string' && /^[a-f0-9]{64}$/.test(row.revision);

function StaffForm({ row, data, saving, onCancel, onSubmit }) {
  const [role, setRole] = useState(row?.actor_type || 'teacher');
  const excluded = role === 'admin' ? data.teacher_only : data.admin_only;
  const available = data.actions.filter(action => !excluded.includes(action));
  // PUT 会替换整个权限集合。提交时保留编辑器无法修改的历史授权和当前角色不适用的授权，
  // 即使取消了界面上所有勾选项也要保留。
  const retained = (row?.permissions || []).filter(action => !available.includes(action));

  function submit(event) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const payload = {
      actor_type: role,
      permissions: [...new Set([...retained, ...fields.getAll('permission').filter(action => available.includes(action))])],
      school_wide: role === 'admin' && fields.has('school_wide'),
      status: row ? fields.get('status') : 'normal',
    };
    if (row) {
      payload.expected_revision = row.revision;
    } else {
      payload.name = fields.get('name').trim();
      payload.email = fields.get('email').trim();
      payload.password = fields.get('password');
    }
    onSubmit(row, payload);
  }

  return <form className="settings-form" onSubmit={submit}>
    <fieldset disabled={saving}>
      <legend>{row ? '编辑账号 · ' + row.name : '创建教职工账号'}</legend>
      {row ? <p>{row.email} · {roleName[role]}</p> : <>
        <div className="field-grid">
          <label className="field-block">姓名<input name="name" required maxLength={160} pattern=".*\S.*" /></label>
          <label className="field-block">登录邮箱<input name="email" type="email" required maxLength={254} /></label>
        </div>
        <div className="field-grid">
          <label className="field-block">初始密码<input name="password" type="password" required minLength={12} maxLength={1024} autoComplete="new-password" /></label>
          <label className="field-block">业务身份<select value={role} onChange={e => setRole(e.target.value)}>
            <option value="teacher">任课教师</option><option value="admin">管理员</option>
          </select></label>
        </div>
      </>}
      {row && <label className="field-block">账号状态<select name="status" defaultValue={row.status}>
        <option value="normal">启用</option><option value="disabled">停用</option>
      </select></label>}
      {role === 'admin' ? <label className="permission-check"><input type="checkbox" name="school_wide" defaultChecked={row?.school_wide || false} /> 全校数据范围</label>
        : <p className="field-hint">教师的数据范围由负责班级和教学任务决定。</p>}
      <fieldset key={role}><legend>按动作授权</legend>
        <div className="permission-checklist">{available.map(action => <label className="permission-check" key={action} title={action}>
          <input type="checkbox" name="permission" value={action} defaultChecked={row?.permissions.includes(action) || false} />
          <span><strong>{staffActionName(action)}</strong><small>{action}</small></span>
        </label>)}</div>
      </fieldset>
      {retained.length > 0 && <p className="field-hint">保留的历史授权 · {retained.map(staffActionName).join('、')}</p>}
      {row && <p className="field-hint">保存后，此账号的现有登录会话将失效。</p>}
      <button type="submit" className="primary-button" disabled={saving}>{saving ? '正在保存…' : row ? '保存设置' : '创建账号'}</button>
      <button type="button" className="secondary-button" onClick={onCancel}>取消</button>
    </fieldset>
  </form>;
}

function StaffDirectory({ request, schoolId, actorId }) {
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [data, setData] = useState(null);
  const [editor, setEditor] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [saving, setSaving] = useState(false);
  const writing = useRef(null);

  useEffect(() => () => writing.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setEditor(null);
    setError('');
    const params = new URLSearchParams({ q: query, limit: String(pageSize), offset: String(offset) });
    request(endpoint + '?' + params, { signal: controller.signal }).then(result => {
      if (controller.signal.aborted) return;
      if (!Array.isArray(result?.items) || !result.items.every(item => validAccount(item, schoolId))
          || !Number.isSafeInteger(result.total) || result.total < 0 || result.offset !== offset
          || !strings(result.actions) || !strings(result.admin_only) || !strings(result.teacher_only)) {
        throw new Error('账号列表与当前学校或接口格式不匹配。');
      }
      setData(result);
    }).catch(err => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [request, schoolId, query, offset, refresh]);

  async function save(row, payload) {
    if (writing.current || !data || row && (row.actor_id === actorId || !data.items.includes(row))) return;
    if (row && row.status === payload.status && row.school_wide === payload.school_wide
        && row.permissions.length === payload.permissions.length
        && row.permissions.every(action => payload.permissions.includes(action))) {
      // 每次 PUT 成功都会使目标账号的会话失效，因此没有变更时跳过提交。
      setEditor(null);
      setError('');
      setNotice('账号设置没有变更。');
      return;
    }
    const controller = new AbortController();
    writing.current = controller;
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const path = row ? endpoint + '/' + encodeURIComponent(row.actor_id) + '/grants' : endpoint;
      await request(path, { method: row ? 'PUT' : 'POST', body: JSON.stringify(payload), signal: controller.signal });
      if (controller.signal.aborted) return;
      setEditor(null);
      setData(null);
      setNotice(row ? '已更新 ' + row.email + ' 的账号设置。' : '已创建账号 ' + payload.email + '。');
      setRefresh(value => value + 1);
    } catch (err) {
      if (!controller.signal.aborted) {
        if (err.status === 401 || err.status === 403) {
          setEditor(null);
          setData(null);
          setError('当前会话或管理权限已失效，请重新登录或刷新授权。');
        } else if (row && err.status === 409) {
          setEditor(null);
          setData(null);
          setError('此账号的授权已变更。请刷新列表，重新核对后再编辑。');
        } else {
          setError(err.message);
        }
      }
    } finally {
      if (!controller.signal.aborted) setSaving(false);
      writing.current = null;
    }
  }

  function search(event) {
    event.preventDefault();
    setQuery(new FormData(event.currentTarget).get('q').trim());
    setOffset(0);
    setRefresh(value => value + 1);
  }

  return <section className="settings-panel">
    <h2>教职工账号与权限</h2>
    <p>学校 {schoolId} · 查看账号的业务身份、数据范围与授权。</p>
    {notice && <p role="status" className="settings-message success">{notice}</p>}
    {error && <p role="alert" className="settings-message error">{error}</p>}
    <div hidden={editor !== null}>
      <form onSubmit={search} className="native-school-search">
        <label className="field-block">查找教职工<input type="search" name="q" maxLength={120} placeholder="姓名或登录邮箱" /></label>
        <button className="secondary-button" type="submit" disabled={saving}>查询</button>
      </form>
      <div className="native-school-line">
        <button type="button" onClick={() => setRefresh(value => value + 1)} disabled={saving}>刷新列表</button>
        <button type="button" className="primary-button" disabled={!data || saving} onClick={() => { setNotice(''); setEditor({}); }}>新增账号</button>
      </div>
      {data ? <>
        <p>共 {data.total} 个账号{data.items.length > 0 && ' · 当前显示 ' + (offset + 1) + ' 至 ' + (offset + data.items.length)}</p>
        <div className="table-wrap"><table><thead><tr><th>教职工</th><th>身份与范围</th><th>状态</th><th>已授权动作</th><th>操作</th></tr></thead>
          <tbody>{data.items.map(row => <tr key={row.actor_id}>
            <td>{row.name}<br /><small>{row.email}</small><br /><code aria-label="职员编号">{row.actor_id}</code></td>
            <td>{roleName[row.actor_type]} · {row.school_wide ? '全校' : '指定班级'}</td>
            <td>{row.status === 'normal' ? '已启用' : '已停用'}</td>
            <td>{row.permissions.length ? <details><summary>{row.permissions.length} 项授权</summary>{row.permissions.map(staffActionName).join('、')}</details> : '无'}</td>
            <td>{row.actor_id === actorId ? '当前账号' : <button type="button" onClick={() => { setNotice(''); setEditor({ row }); }}>编辑</button>}</td>
          </tr>)}</tbody></table></div>
        {!data.items.length && <p>没有匹配的教职工账号。</p>}
        <div className="native-school-pages">
          <button type="button" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - pageSize))}>上一页</button>
          <span>第 {Math.floor(offset / pageSize) + 1} 页</span>
          <button type="button" disabled={offset + pageSize >= data.total} onClick={() => setOffset(offset + pageSize)}>下一页</button>
        </div>
      </> : !error && <p role="status">正在读取账号…</p>}
    </div>
    {editor && data && <StaffForm data={data} row={editor.row} saving={saving} onSubmit={save} onCancel={() => { setEditor(null); setError(''); }} />}
  </section>;
}

export default function NativeStaffGrants({ request, permissions, schoolId, admin }) {
  const actorId = admin?.id;
  if (!permissions?.canManageStaff || !actorId || !schoolId || admin.school_id !== schoolId || admin.actorType !== 'admin') {
    return <p>此页面仅对本校具有教职工授权权限的全校管理员开放。</p>;
  }
  // 学校或操作账号变化时重新挂载整个名录，避免把原学校尚未返回的请求结果、
  // 密码输入或编辑草稿带入新页面。
  return <StaffDirectory key={JSON.stringify([schoolId, actorId])} request={request} schoolId={schoolId} actorId={actorId} />;
}
