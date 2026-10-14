import { useState } from 'react';
import { useApp } from '../context.jsx';
import { navigate } from '../router.js';
import { canManagePlan } from '../roles.js';
import { todayISO } from '../selectors.js';
import { INTERVIEW_TYPES } from '../constants.js';
import PageHeading from '../components/PageHeading.jsx';
import MissingPage from './MissingPage.jsx';

export default function PlanFormPage({ id }) {
  const { role, plans, classes, colleges, savePlan } = useApp();
  const existing = id ? plans.find(plan => plan.id === id) : null;
  const initialTarget = role.id === 'school' ? { kind: 'all', ids: [] } :
    role.id === 'college' ? { kind: 'colleges', ids: [role.collegeId] } : { kind: 'classes', ids: [...role.classIds] };
  const [form, setForm] = useState(() => existing ?? {
    name: '', role: '', type: '综合面试', difficulty: '标准', style: '循循善诱',
    startDate: todayISO(), deadline: '', description: '', target: initialTarget,
  });
  const [error, setError] = useState('');
  if (id && (!existing || existing.status !== 'draft' || !canManagePlan(role, existing))) return <MissingPage />;
  const update = (key, value) => setForm(previous => ({ ...previous, [key]: value }));
  const options = form.target.kind === 'colleges' ? colleges : classes;
  function submit(event) {
    event.preventDefault();
    const status = event.nativeEvent.submitter?.value === 'draft' ? 'draft' : 'published';
    if (!form.name.trim() || !form.role.trim()) { setError('请填写计划名称和面试岗位。'); return; }
    if (form.target.kind !== 'all' && !form.target.ids.length) { setError('请至少选择一个目标学院或班级。'); return; }
    if (form.deadline < todayISO() || form.deadline < form.startDate) { setError('截止日期不能早于今天或开始日期。'); return; }
    const plan = { ...form, name: form.name.trim(), role: form.role.trim(), id: existing?.id ?? 'user-' + crypto.randomUUID(), ownerRoleId: existing?.ownerRoleId ?? role.id, status };
    if (savePlan(plan)) navigate('/plans/' + plan.id);
  }
  return (
    <>
      <PageHeading title={existing ? '编辑训练计划草稿' : '新建训练计划'} description="计划仅保存到当前浏览器；发布不会发送真实通知。">
        <button className="secondary" onClick={() => navigate(existing ? '/plans/' + existing.id : '/plans')}>取消</button>
      </PageHeading>
      <section className="panel content-pad">
        <form className="plan-editor" onSubmit={submit}>
          <div className="form-grid">
            <label>计划名称<input required maxLength={80} value={form.name} onChange={event => update('name', event.target.value)} /></label>
            <label>面试岗位<input required maxLength={80} value={form.role} onChange={event => update('role', event.target.value)} placeholder="例如：软件开发工程师" /></label>
            <label>目标范围<select value={form.target.kind} onChange={event => update('target', { kind: event.target.value, ids: [] })}>
              {role.id === 'school' && <option value="all">全校</option>}
              {role.id !== 'counselor' && <option value="colleges">学院多选</option>}
              <option value="classes">专业班级多选</option>
            </select></label>
            <label>面试类型<select value={form.type} onChange={event => update('type', event.target.value)}>
              {INTERVIEW_TYPES.map(type => <option key={type}>{type}</option>)}
            </select></label>
            <label>难度<select value={form.difficulty} onChange={event => update('difficulty', event.target.value)}>
              {['入门', '标准', '进阶'].map(value => <option key={value}>{value}</option>)}
            </select></label>
            <label>面试官风格<select value={form.style} onChange={event => update('style', event.target.value)}>
              {['温和鼓励', '循循善诱', '深入追问'].map(value => <option key={value}>{value}</option>)}
            </select></label>
            <label>开始日期<input type="date" required value={form.startDate} onChange={event => update('startDate', event.target.value)} /></label>
            <label>截止日期<input type="date" required min={form.startDate > todayISO() ? form.startDate : todayISO()} value={form.deadline} onChange={event => update('deadline', event.target.value)} /></label>
          </div>
          {form.target.kind !== 'all' && <fieldset className="target-options">
            <legend>选择{form.target.kind === 'colleges' ? '学院' : '班级'}（可多选）</legend>
            {options.map(item => <label key={item.id}>
              <input type="checkbox" checked={form.target.ids.includes(item.id)} onChange={event => update('target', {
                ...form.target, ids: event.target.checked ? [...form.target.ids, item.id] : form.target.ids.filter(id => id !== item.id),
              })} />{item.name}
            </label>)}
          </fieldset>}
          <label>说明<textarea maxLength={2000} rows={4} value={form.description} onChange={event => update('description', event.target.value)} /></label>
          {error && <p role="alert" className="info-banner">{error}</p>}
          <div className="modal-actions">
            <button className="secondary" type="submit" value="draft">保存草稿</button>
            <button className="primary" type="submit" value="published">发布</button>
          </div>
        </form>
      </section>
    </>
  );
}
