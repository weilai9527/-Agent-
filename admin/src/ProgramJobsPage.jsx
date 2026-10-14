import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowRight, BookOpen, Check, CheckCircle2, ChevronRight, GraduationCap, Plus, RefreshCw, Save, Search, Trash2, X } from 'lucide-react';
import { programJobRows, programJobsChanged, programJobsPayload } from './programJobs.js';
import './programJobs.css';
import { usePageRefresh } from './PageRefreshContext.jsx';

export function CatalogModule({ request, permissions, renderLibrary }) {
  const [tab, setTab] = useState('programs');
  const [openedLibrary, setOpenedLibrary] = useState(false);
  const showLibrary = () => { setOpenedLibrary(true); setTab('library'); };
  return <div className="pj-module">
    <div className="pj-module-tabs" role="tablist" aria-label="岗位信息功能">
      <button type="button" role="tab" aria-selected={tab === 'programs'} aria-controls="program-jobs-panel" id="program-jobs-tab" className={tab === 'programs' ? 'active' : ''} onClick={() => setTab('programs')}><GraduationCap size={16} />专业岗位配置</button>
      {permissions.canViewCatalog && <button type="button" role="tab" aria-selected={tab === 'library'} aria-controls="catalog-library-panel" id="catalog-library-tab" className={tab === 'library' ? 'active' : ''} onClick={showLibrary}><BookOpen size={16} />岗位库维护</button>}
    </div>
    <div hidden={tab !== 'programs'} role="tabpanel" id="program-jobs-panel" aria-labelledby="program-jobs-tab"><ProgramJobsPage request={request} onLibrary={permissions.canViewCatalog ? showLibrary : undefined} active={tab === 'programs'} /></div>
    {openedLibrary && <div hidden={tab !== 'library'} role="tabpanel" id="catalog-library-panel" aria-labelledby="catalog-library-tab">
      <p className="pj-library-note">这里维护可供各专业选择的岗位及能力要求。关联已有岗位请返回“专业岗位配置”。</p>{renderLibrary(permissions, tab === 'library')}
    </div>}
  </div>;
}

function ProgramJobsPage({ request, onLibrary, active }) {
  const [data, setData] = useState({ colleges: [], programs: [], jobs: [], canEdit: false });
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [collegeId, setCollegeId] = useState('');
  const [query, setQuery] = useState('');
  const [configuration, setConfiguration] = useState('all');
  const [drafts, setDrafts] = useState({});
  const [savingId, setSavingId] = useState('');
  const [saveError, setSaveError] = useState('');
  const [notice, setNotice] = useState('');
  const [picker, setPicker] = useState(false);
  const [jobQuery, setJobQuery] = useState('');
  const [jobMajor, setJobMajor] = useState('');
  const [inspectedJob, setInspectedJob] = useState(null);
  const pickerRef = useRef(null);
  const addButtonRef = useRef(null);
  const saving = Boolean(savingId);
  const dirty = Object.keys(drafts).length > 0;

  const load = async () => {
    setLoading(true); setLoadError('');
    try {
      const result = await request('/api/admin/campus/program-jobs');
      setData(result);
      const chosen = result.programs.find((item) => item.id === selectedId)
        || result.programs.find((item) => result.jobs.some((job) => job.sourceMajor === item.name)) || result.programs[0];
      setSelectedId(chosen?.id || '');
      if (!selectedId && chosen) setCollegeId(chosen.college_id);
    } catch (error) { setLoadError(error.message); return false; }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);
  usePageRefresh(async () => {
    if (dirty || saving) { setLoadError('请先保存或撤销修改，再刷新配置。'); return false; }
    return load();
  }, active);
  useEffect(() => {
    if (!dirty) return undefined;
    const warn = (event) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  useEffect(() => {
    if (!picker) return undefined;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    pickerRef.current?.querySelector('input')?.focus();
    const close = (event) => {
      if (event.key === 'Escape') { setPicker(false); addButtonRef.current?.focus(); }
      if (event.key === 'Tab') {
        const elements = [...(pickerRef.current?.querySelectorAll('button:not(:disabled), input, select') || [])];
        const first = elements[0], last = elements[elements.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener('keydown', close);
    return () => { document.body.style.overflow = oldOverflow; document.removeEventListener('keydown', close); };
  }, [picker]);

  const colleges = new Map(data.colleges.map((college) => [college.id, college]));
  const selected = data.programs.find((program) => program.id === selectedId);
  const saved = useMemo(() => programJobRows(selected, data.jobs), [selected, data.jobs]);
  const rows = drafts[selectedId] || saved;
  const changed = programJobsChanged(rows, saved);
  const unavailable = rows.some((item) => !item.available);
  const linkedCount = data.programs.filter((program) => program.jobs?.length).length;
  const visiblePrograms = data.programs.filter((program) => (!collegeId || program.college_id === collegeId)
    && [program.name, colleges.get(program.college_id)?.name].join(' ').toLowerCase().includes(query.trim().toLowerCase())
    && (configuration === 'all' || (configuration === 'configured' ? program.jobs?.length : !program.jobs?.length)));
  const visibleJobs = data.jobs.filter((job) => (!jobMajor || job.sourceMajor === jobMajor)
    && [job.name, job.description, ...(job.competencies || []).map((item) => item.name)].join(' ').toLowerCase().includes(jobQuery.trim().toLowerCase()));

  const updateRows = (next) => {
    setDrafts((current) => {
      const updated = { ...current };
      if (programJobsChanged(next, saved)) updated[selectedId] = next;
      else delete updated[selectedId];
      return updated;
    });
    setNotice(''); setSaveError('');
  };
  const toggleJob = (job) => {
    const exists = rows.some((item) => item.jobRoleId === job.id);
    if (!exists && rows.length >= 50) { setSaveError('一个专业最多关联 50 个岗位。'); return; }
    updateRows(exists ? rows.filter((item) => item.jobRoleId !== job.id)
      : [...rows, { jobRoleId: job.id, priority: 'recommended', job, available: true }]);
  };
  const selectProgram = (id) => { setSelectedId(id); setSaveError(''); setNotice(''); setInspectedJob(null); };
  const save = async () => {
    if (!selected || !changed || saving || unavailable) return;
    const programId = selected.id, submitted = rows;
    setSavingId(programId); setSaveError(''); setNotice('');
    try {
      const result = await request(`/api/admin/campus/programs/${encodeURIComponent(programId)}/jobs`,
        { method: 'PUT', body: JSON.stringify({ jobs: programJobsPayload(submitted) }) });
      setData((current) => ({ ...current, programs: current.programs.map((program) => program.id !== programId ? program : { ...program,
        jobs: result.jobs.map((item) => ({ job_role_id: item.jobRoleId, priority: item.priority,
          job_name: submitted.find((row) => row.jobRoleId === item.jobRoleId)?.job.name })) }) }));
      setDrafts((current) => { const updated = { ...current }; delete updated[programId]; return updated; });
      setNotice(`已保存 ${selected.name} 的 ${submitted.length} 个关联岗位。`);
    } catch (error) { setSaveError(error.message); }
    finally { setSavingId(''); }
  };
  const closePicker = () => { setPicker(false); addButtonRef.current?.focus(); };
  if (loading && !data.programs.length) return <div className="page-message" role="status"><RefreshCw size={17} className="spin" />正在读取学校专业与岗位库…</div>;
  if (loadError && !data.programs.length) return <div className="page-message error" role="alert">{loadError}<button type="button" onClick={load}>重试</button></div>;
  return <div className="pj-page">
    <div className="pj-intro"><div><span>学校专业 → 就业岗位</span><h2>为每个专业配置合适的就业方向</h2><p>先选择学校专业，再从已发布岗位库中选择岗位，设置推荐程度并保存。</p></div>
      <button type="button" className="secondary-button" disabled={loading || saving || dirty} onClick={load} title={dirty ? '请先保存或撤销修改，再刷新' : '重新读取配置'}><RefreshCw size={15} />刷新配置</button>
    </div>
    <div className="pj-summary"><span><strong>{data.colleges.length}</strong> 个学院</span><span><strong>{data.programs.length}</strong> 个专业</span><span><strong>{linkedCount}</strong> 个已配置</span><span><strong>{data.programs.length - linkedCount}</strong> 个待配置</span><small>{data.jobs.length} 个可选岗位 · {data.publishedVersion?.name || '暂无已发布岗位库'}</small></div>
    {loadError && <div className="page-message error" role="alert">{loadError}，当前显示上次读取的数据。</div>}
    <section className="pj-workspace">
      <aside className="pj-programs"><header><h3>选择学校专业</h3><span>{visiblePrograms.length} 个</span></header>
        <div className="pj-program-filters"><label className="pj-search"><Search size={15} /><input aria-label="搜索学校专业" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索学院或专业" /></label>
          <select aria-label="筛选学院" value={collegeId} disabled={saving || loading} onChange={(event) => { const id = event.target.value; setCollegeId(id); if (id && selected?.college_id !== id) selectProgram(data.programs.find((program) => program.college_id === id)?.id || ''); }}>
            <option value="">全部学院</option>{data.colleges.map((college) => <option key={college.id} value={college.id}>{college.name}</option>)}
          </select>
          <select aria-label="岗位配置状态" value={configuration} onChange={(event) => setConfiguration(event.target.value)}><option value="all">全部配置状态</option><option value="unconfigured">尚未配置岗位</option><option value="configured">已配置岗位</option></select>
        </div>
        <nav aria-label="学校专业列表" className="pj-program-list">{visiblePrograms.map((program) => <button type="button" key={program.id} disabled={saving || loading} className={program.id === selectedId ? 'active' : ''} aria-pressed={program.id === selectedId} onClick={() => selectProgram(program.id)}>
          <span><strong>{program.name}</strong><small>{colleges.get(program.college_id)?.name}</small></span><span className="pj-program-count">{drafts[program.id] ? '未保存' : program.jobs?.length ? `${program.jobs.length} 个岗位` : '待配置'}<ChevronRight size={13} /></span>
        </button>)}{!visiblePrograms.length && <p className="pj-empty-small">没有符合条件的专业，请调整筛选。</p>}</nav>
      </aside>
      <section className="pj-config" aria-label="专业关联岗位">
        {!selected ? <div className="pj-empty"><GraduationCap size={32} /><h3>先选择一个学校专业</h3><p>学校还没有专业时，请先到“组织管理”维护学院和专业。</p></div> : <>
          <header className="pj-config-header"><div><span>{colleges.get(selected.college_id)?.name} / {selected.name}</span><h3>{selected.name} · 就业岗位</h3><p>已关联 {rows.length} 个岗位，其中 {rows.filter((item) => item.priority === 'recommended').length} 个重点推荐。</p></div>
            {data.canEdit && <button type="button" ref={addButtonRef} className="primary-button" disabled={saving || !data.jobs.length} onClick={() => { setPicker(true); setJobQuery(''); setJobMajor(''); }}><Plus size={16} />添加岗位</button>}
          </header>
          <p className="pj-guidance">重点推荐：优先作为该专业的就业方向。一般推荐：作为可拓展的就业选择。</p>
          {!data.canEdit && <p className="pj-guidance">当前账号可以查看配置，修改需要“组织管理”权限。</p>}
          {notice && <p className="pj-feedback success" role="status"><CheckCircle2 size={16} />{notice}</p>}
          {saveError && <p className="pj-feedback error" role="alert">{saveError}</p>}
          {unavailable && <p className="pj-feedback warning" role="alert">存在已停用或已归档的关联岗位。请先移除该岗位，再从当前岗位库中选择。</p>}
          <div className="pj-job-list">{rows.map((item) => <article key={item.jobRoleId} className={item.available ? '' : 'unavailable'}>
            <div className="pj-job-symbol"><BookOpen size={19} /></div><div className="pj-job-copy"><h4>{item.job.name}{!item.available && <em>暂不可选</em>}</h4><p>{item.job.description || '暂无岗位说明，可在岗位库维护中补充。'}</p>
              <div className="pj-competency-tags">{(item.job.competencies || []).slice(0, 4).map((competency) => <span key={competency.id}>{competency.name}</span>)}{item.job.competencies?.length > 4 && <span>+{item.job.competencies.length - 4} 项能力</span>}</div>
              <button type="button" className="pj-text-button" onClick={() => setInspectedJob(inspectedJob?.id === item.job.id ? null : item.job)}>查看能力要求 <ChevronRight size={12} /></button>
            </div><div className="pj-job-actions"><label><span>推荐程度</span><select aria-label={`${item.job.name}推荐程度`} disabled={!data.canEdit || saving} value={item.priority} onChange={(event) => updateRows(rows.map((row) => row.jobRoleId === item.jobRoleId ? { ...row, priority: event.target.value } : row))}><option value="recommended">重点推荐</option><option value="optional">一般推荐</option></select></label>
              {data.canEdit && <button type="button" className="pj-remove" disabled={saving} onClick={() => updateRows(rows.filter((row) => row.jobRoleId !== item.jobRoleId))} aria-label={`移除${item.job.name}`}><Trash2 size={14} />移除关联</button>}
            </div>
          </article>)}
          {!rows.length && <div className="pj-empty"><GraduationCap size={34} /><h3>这个专业还没有关联岗位</h3><p>从岗位库中挑选适合的就业岗位，再明确推荐程度。</p>{data.canEdit && data.jobs.length > 0 && <button type="button" className="secondary-button" onClick={() => { setPicker(true); setJobQuery(''); setJobMajor(''); }}><Plus size={15} />选择第一个岗位</button>}</div>}
          </div>
          {inspectedJob && <section className="pj-ability-detail"><header><h4>{inspectedJob.name} · 能力要求</h4><button type="button" aria-label="收起能力要求" onClick={() => setInspectedJob(null)}><X size={15} /></button></header>
            {inspectedJob.competencies?.length ? <div className="pj-ability-table"><table><thead><tr><th>能力</th><th>类别</th><th>要求等级</th><th>权重</th></tr></thead><tbody>{inspectedJob.competencies.map((item) => <tr key={item.id}><td>{item.name}</td><td>{item.category || '通用能力'}</td><td>{item.required_level} / 5</td><td>{item.weight} / 5</td></tr>)}</tbody></table></div> : <p>岗位库中暂未配置能力要求。</p>}
          </section>}
          <footer className="pj-save-bar"><span>{changed ? '有未保存修改；切换专业会保留本页修改。' : '当前显示已保存的专业岗位配置。'}</span>{data.canEdit && <div><button type="button" className="secondary-button" disabled={!changed || saving} onClick={() => { setDrafts((current) => { const updated = { ...current }; delete updated[selectedId]; return updated; }); setSaveError(''); setNotice(''); }}>撤销修改</button><button type="button" className="primary-button" disabled={!changed || saving || unavailable} onClick={save}><Save size={15} />{saving ? '正在保存…' : '保存专业配置'}</button></div>}</footer>
        </>}
      </section>
    </section>
    {onLibrary && <div className="pj-library-tip"><BookOpen size={18} /><div><strong>没有找到适合的岗位？</strong><span>可以在岗位库维护中新增岗位和能力要求，发布后再回来关联。</span></div><button type="button" className="pj-text-button" onClick={onLibrary}>进入岗位库维护 <ArrowRight size={15} /></button></div>}
    {picker && <div className="pj-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) closePicker(); }}>
      <section className="pj-picker" ref={pickerRef} role="dialog" aria-modal="true" aria-labelledby="pj-picker-title"><header><div><h3 id="pj-picker-title">为{selected?.name}选择就业岗位</h3><p>勾选岗位后会加入当前配置，完成选择后点击“保存专业配置”生效。</p></div><button type="button" aria-label="关闭岗位选择" onClick={closePicker}><X size={19} /></button></header>
        <div className="pj-picker-filters"><label className="pj-search"><Search size={16} /><input aria-label="搜索可选岗位" placeholder="搜索岗位名称、说明或能力关键词" value={jobQuery} onChange={(event) => setJobQuery(event.target.value)} /></label><select aria-label="岗位方向" value={jobMajor} onChange={(event) => setJobMajor(event.target.value)}><option value="">全部岗位方向</option>{[...new Set(data.jobs.map((job) => job.sourceMajor))].map((name) => <option key={name}>{name}</option>)}</select></div>
        <div className="pj-picker-list">{visibleJobs.map((job) => { const checked = rows.some((item) => item.jobRoleId === job.id); return <label className={`pj-picker-job${checked ? ' selected' : ''}`} key={job.id}><input type="checkbox" checked={checked} onChange={() => toggleJob(job)} /><div><strong>{job.name}</strong><p>{job.description || '暂无岗位说明'}</p><small>{job.sourceMajor} · {job.competencies.length} 项能力要求</small><div className="pj-competency-tags">{job.competencies.slice(0, 4).map((item) => <span key={item.id}>{item.name}</span>)}</div></div>{checked && <Check size={17} />}</label>; })}{!visibleJobs.length && <p className="pj-empty-small">没有符合条件的岗位，试试其他关键词，或先在岗位库维护中补充岗位。</p>}</div>
        <footer><span>当前已选择 <strong>{rows.length}</strong> 个岗位</span><button type="button" className="primary-button" onClick={closePicker}>完成选择 <Check size={16} /></button></footer>
      </section>
    </div>}
  </div>;
}
