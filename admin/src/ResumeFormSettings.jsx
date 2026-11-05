import React, { useEffect, useState } from 'react';
import { usePageRefresh } from './PageRefreshContext.jsx';
import './nativeSchoolManagement.css';

const path = '/api/admin/resume-form-settings';

// 改名时保留已有编号；新增项未指定编号，由服务端按名称生成。
function normalized(rows, label) {
  const names = new Set(), ids = new Set();
  return rows.map(row => {
    const name = row.name.trim();
    const id = row.id || name;
    if (!name || name.length > 160) throw new Error(`${label}名称须为 1 至 160 个字符。`);
    if (names.has(name) || ids.has(id)) throw new Error(`同级${label}的名称或编号重复：${name}`);
    names.add(name); ids.add(id);
    return { ...row, name };
  });
}

function checkedReply(result, schoolId) {
  const valid = item => typeof item?.id === 'string' && typeof item.name === 'string';
  if (result?.school_id !== schoolId || !Number.isSafeInteger(result.revision) || result.revision < 0
      || !Array.isArray(result.colleges) || !result.colleges.every(c => valid(c) && Array.isArray(c.majors) && c.majors.every(valid))) {
    throw new Error('表单配置与本校或当前版本不匹配。');
  }
  return result;
}

export default function ResumeFormSettings({ request, schoolId, canEdit }) {
  const [revision, setRevision] = useState(null);
  const [colleges, setColleges] = useState([]);
  const [dirty, setDirty] = useState(false);
  const [selected, setSelected] = useState(0);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [reload, setReload] = useState(0);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const college = colleges[selected];

  useEffect(() => {
    const controller = new AbortController();
    setRevision(null); setDirty(false); setConflict(false); setError(''); setNotice('');
    request(path, { signal: controller.signal }).then(reply => {
      if (controller.signal.aborted) return;
      const result = checkedReply(reply, schoolId);
      setRevision(result.revision); setColleges(result.colleges); setSelected(0);
    }).catch(err => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [request, schoolId, reload]);

  usePageRefresh(() => {
    if (dirty || saving) { setError('请先保存或放弃当前修改。'); return false; }
    setReload(n => n + 1);
    return true;
  });

  function update(next) {
    setColleges(next); setDirty(true); setError(''); setNotice('');
  }
  function updateCollege(changes) {
    update(colleges.map((item, i) => i === selected ? { ...item, ...changes } : item));
  }
  async function save(event) {
    event.preventDefault();
    if (!canEdit || saving || conflict || !dirty || revision === null) return;
    setError(''); setNotice(''); setSaving(true);
    try {
      const cleaned = normalized(colleges, '学院').map(c => ({ ...c, majors: normalized(c.majors, '专业') }));
      // 整份替换必须携带刚才读取的版本，冲突时保留草稿供对照。
      const reply = await request(path, { method: 'PUT', body: JSON.stringify({ colleges: cleaned, expected_revision: revision }) });
      const result = checkedReply(reply, schoolId);
      if (result.revision < revision) throw new Error('表单配置返回的版本已过期，请重新读取。');
      setRevision(result.revision); setColleges(result.colleges); setDirty(false); setNotice('已保存本校简历表单配置。');
    } catch (err) {
      if (err.status === 409) setConflict(true);
      setError(err.status === 409 ? '其他管理员已更改配置，请重新读取后编辑。' : err.message);
    } finally { setSaving(false); }
  }

  return <section className="section-card native-school" aria-label="简历表单学院与专业">
    <header className="native-school-line"><div><h2>简历表单学院与专业</h2>
      <p>学生填写简历时会看到学校组织、已发布职业目录和此处维护的补充选项。</p></div>
      <button type="button" disabled={saving || (dirty && !conflict)} onClick={() => setReload(n => n + 1)}>
        {conflict ? '放弃草稿并重新读取' : '重新读取配置'}</button></header>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {revision === null ? !error && <p role="status">正在读取本校配置…</p> :
      <form className="settings-form" onSubmit={save}>
        <p>自定义学院 {colleges.length} 个 · 版本 {revision}</p>
        <div className="training-row">
          {colleges.length > 0 && <label>选择学院 <select value={selected} onChange={e => setSelected(Number(e.target.value))}>
            {colleges.map((c, i) => <option key={i} value={i}>{c.name || '未命名学院'}</option>)}</select></label>}
          {canEdit && <button type="button" disabled={saving || conflict || colleges.length >= 200} onClick={() => {
            update([...colleges, { name: '', majors: [] }]); setSelected(colleges.length);
          }}>添加学院</button>}
        </div>
        {college ? <fieldset disabled={saving || conflict} className="training-stack"><legend>{college.name || '新学院'}</legend>
          {canEdit ? <div className="training-row"><label>学院名称 <input value={college.name} maxLength={160} required
            onChange={e => updateCollege({ name: e.target.value })} /></label>
            <button type="button" onClick={() => {
              update(colleges.filter((_, i) => i !== selected)); setSelected(Math.max(0, selected - 1));
            }}>移除学院及其专业</button></div> : <strong>{college.name}</strong>}
          {college.majors.length === 0 && <p>尚未配置专业。</p>}
          {college.majors.map((major, index) => <div key={index} className="training-row">
            {canEdit ? <><label>专业名称 <input value={major.name} required maxLength={160}
              onChange={e => updateCollege({ majors: college.majors.map((m, i) => i === index ? { ...m, name: e.target.value } : m) })} /></label>
              <button type="button" onClick={() => updateCollege({ majors: college.majors.filter((_, i) => i !== index) })}>移除专业</button>
            </> : <span>{major.name}</span>}</div>)}
          {canEdit && <button type="button" disabled={college.majors.length >= 500}
            onClick={() => updateCollege({ majors: [...college.majors, { name: '' }] })}>添加专业</button>}
        </fieldset> : <p>本校尚未配置自定义学院。</p>}
        {canEdit && <div className="training-row">
          <button type="submit" disabled={!dirty || saving || conflict}>{saving ? '正在保存…' : '保存表单配置'}</button>
          <button type="button" disabled={!dirty || saving} onClick={() => setReload(n => n + 1)}>放弃修改</button>
        </div>}
      </form>}
  </section>;
}
