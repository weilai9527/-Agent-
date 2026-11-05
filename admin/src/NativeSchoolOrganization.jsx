import React, { useEffect, useRef, useState } from 'react';
import '../../frontend/src/training.css';
import { encodeSchoolFile } from './schoolWorkbookUpload.js';

const api = '/api/admin/identity';
const pageSize = 50;
const classPath = id => '/v1/classes/' + encodeURIComponent(id);
const detailLabels = { colleges: { code: '学院编码' }, programs: { direction: '培养方向', coordinator: '专业负责人', standard_major_code: '标准专业代码' },
  classes: { advisor: '辅导员姓名', graduation_year: '毕业年份', invite_code: '班级邀请码' } };
const unitLabels = { colleges: '学院', programs: '专业', classes: '班级' };

function identifier(value) {
  const id = String(value || '').trim();
  if (!id || id.length > 128 || /[\s\x00-\x1f\x7f/%\\]/u.test(id) || ['.', '..'].includes(id))
    throw new Error('编号必须为 1 至 128 个字符，不能含空格、斜线或百分号。');
  return id;
}
function idList(value) {
  return [...new Set(String(value || '').split(/[\s,，]+/u).filter(Boolean).map(identifier))];
}

function useRead(request, path, revision) {
  const [response, setResponse] = useState(null);
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    request(api + path, { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) setResponse({ path, revision, data });
    }).catch(err => {
      if (!controller.signal.aborted) setResponse({ path, revision, error: err.message || '读取失败。' });
    });
    return () => controller.abort();
  }, [path, request, revision]);
  return response?.path === path && response?.revision === revision ? response : {};
}

function Result({ result, children }) {
  if (result.error) return <p role="alert">{result.error}</p>;
  if (!result.data) return <p role="status">正在读取…</p>;
  if (!Array.isArray(result.data.items)) return <p role="alert">返回的名单格式无效，请刷新。</p>;
  return children(result.data);
}

function Pager({ offset, change, hasMore }) {
  return <div className="training-row">
    <button type="button" disabled={!offset} onClick={() => change(offset - pageSize)}>上一页</button>
    <span>第 {offset / pageSize + 1} 页</span>
    <button type="button" disabled={!hasMore} onClick={() => change(offset + pageSize)}>下一页</button>
  </div>;
}

function Search({ onSearch, label }) {
  return <form className="training-row" onSubmit={event => {
    event.preventDefault();
    onSearch(new FormData(event.currentTarget).get('q').trim());
  }}>
    <label>{label} <input name="q" maxLength={128} /></label>
    <button>查询</button>
  </form>;
}

function NodeForm({ data, save, busy }) {
  const [kind, setKind] = useState('colleges');
  const [edit, setEdit] = useState('');
  const units = data?.[kind] || [];
  const nodeId = node => node.id || node.class_id;
  const node = units.find(unit => nodeId(unit) === edit);
  const parentName = kind === 'classes' ? '专业' : '学院';
  const parentField = kind === 'classes' ? 'program_id' : 'college_id';
  const parents = kind === 'classes' ? data?.programs : data?.colleges;
  return <section className="training-card"><h3>维护组织节点</h3>
    <form className="training-stack" onSubmit={event => {
      event.preventDefault();
      const form = event.currentTarget;
      const fields = new FormData(form);
      const retiring = event.nativeEvent.submitter?.value === 'inactive';
      if (retiring && !window.confirm('确认停用此组织节点？停用前请移交在用的下级、教师和学生。')) return;
      save(async write => {
        const id = identifier(fields.get('id'));
        const name = fields.get('name').trim();
        if (!name) throw new Error('请填写节点名称。');
        if (data && !node && units.some(unit => nodeId(unit) === id))
          throw new Error('编号已存在，请选择该节点再修改。');
        const item = retiring ? { id, name, status: 'inactive' } : { id, name };
        const details = Object.fromEntries(Object.keys(detailLabels[kind]).filter(key => fields.get(key) || node?.details?.[key])
          .map(key => [key, String(fields.get(key) || '').trim()]));
        if (Object.keys(details).length) item.details = details;
        if (kind !== 'colleges') item[parentField] = identifier(fields.get('parent'));
        await write('/v1/organization/import', 'POST', { [kind]: [item] });
        form.reset(); setEdit('');
        return retiring ? '组织节点已停用。' : '组织节点已保存。';
      });
    }}>
      <fieldset disabled={busy} className="training-stack"><legend>学院、专业与班级</legend>
        <label>节点类型 <select value={kind} onChange={e => { setKind(e.target.value); setEdit(''); }}>
          {Object.entries(unitLabels).map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select></label>
        {data && <label>操作对象 <select value={edit} onChange={e => setEdit(e.target.value)}>
          <option value="">新增{unitLabels[kind]}</option>
          {units.map(unit => <option key={nodeId(unit)} value={nodeId(unit)}>{unit.name} · {nodeId(unit)}</option>)}
        </select></label>}
        <div key={kind + edit} className="training-stack">
          <label>节点编号 <input name="id" required maxLength={128} readOnly={!!node} defaultValue={edit} /></label>
          <label>节点名称 <input name="name" required maxLength={160} defaultValue={node?.name || ''} /></label>
          {Object.entries(detailLabels[kind]).map(([key, title]) => <label key={key}>{title}
            <input name={key} defaultValue={node?.details?.[key] || ''} maxLength={160} /></label>)}
          {kind !== 'colleges' && <label>所属{parentName} {parents ? <select name="parent" required defaultValue={node?.[parentField] || ''}>
            <option value="">请选择</option>{parents.map(p => <option key={p.id} value={p.id}>{p.name} · {p.id}</option>)}
          </select> : <input name="parent" required placeholder={parentName + '编号'} />}</label>}
        </div>
        <div><button className="training-primary">保存组织节点</button>
          {node && <button type="submit" value="inactive">停用当前节点</button>}</div>
      </fieldset>
    </form>
  </section>;
}

const maxImportBytes = 1024 * 1024;
const importLimits = { colleges: 500, programs: 1000, classes: 2000 };
const parentKeys = { programs: 'college_id', classes: 'program_id' };

function inspectBatch(text) {
  const issues = [];
  let totalErrors = 0;
  function issue(message) {
    totalErrors += 1;
    if (issues.length < 10) issues.push(message);
  }
  const counts = { colleges: 0, programs: 0, classes: 0 };
  let payload;
  try {
    if (text.length > maxImportBytes || new TextEncoder().encode(text).length > maxImportBytes)
      throw new Error('JSON 文档超过 1 MiB。');
    payload = JSON.parse(text.replace(/^\uFEFF/u, ''));
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('顶层必须为 JSON 对象。');
    for (const key of Object.keys(payload))
      if (!Object.hasOwn(importLimits, key)) issue(`顶层字段 ${key} 不受支持。`);
    for (const [kind, limit] of Object.entries(importLimits)) {
      if (!Object.hasOwn(payload, kind)) continue;
      const nodes = payload[kind];
      if (!Array.isArray(nodes)) { issue(`${kind} 必须为数组。`); continue; }
      counts[kind] = nodes.length;
      if (nodes.length > limit) { issue(`${kind} 最多可提交 ${limit} 条。`); continue; }
      const parent = parentKeys[kind];
      const keys = ['id', 'name', 'status', ...(parent ? [parent] : [])];
      const seen = new Set();
      nodes.forEach((row, i) => {
        const field = `${kind}[${i}]`;
        if (!row || typeof row !== 'object' || Array.isArray(row)) { issue(`${field} 必须为节点对象。`); return; }
        for (const key of Object.keys(row)) {
          if (!keys.includes(key)) issue(key === 'staff_ids'
            ? `${field}.staff_ids 请在班级职员分配中单独维护。` : `${field}.${key} 不受支持。`);
        }
        for (const key of parent ? ['id', parent] : ['id']) {
          try {
            if (typeof row[key] !== 'string' || row[key] !== identifier(row[key])) throw new Error();
          } catch { issue(`${field}.${key} 请填写有效编号。`); }
        }
        if (typeof row.id === 'string') {
          if (seen.has(row.id)) issue(`${field}.id 在当前层级重复。`);
          seen.add(row.id);
        }
        if (typeof row.name !== 'string' || !row.name.trim() || [...row.name.trim()].length > 160)
          issue(`${field}.name 需为 1 至 160 个字符的名称。`);
        if (Object.hasOwn(row, 'status') && !['active', 'inactive'].includes(row.status))
          issue(`${field}.status 只支持 active 或 inactive。`);
      });
    }
    if (!Object.values(counts).some(Boolean)) issue('请至少提供一个组织节点。');
  } catch (err) {
    issue(err instanceof SyntaxError ? 'JSON 格式错误，请检查引号、逗号和括号。' : err.message);
  }
  return { counts, issues, totalErrors, payload: totalErrors ? null : payload };
}

function BatchForm({ save, busy }) {
  const [preview, setPreview] = useState(null);
  const [reading, setReading] = useState(false);
  const input = useRef(null);
  const sequence = useRef(0);
  async function loadFile(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    const version = ++sequence.current;
    setPreview(null); input.current.value = '';
    setReading(true);
    try {
      if (!file.name.toLowerCase().endsWith('.json')) throw new Error('请选择 .json 文件。');
      if (file.size > maxImportBytes) throw new Error('JSON 文件超过 1 MiB。');
      const text = await file.text();
      if (version !== sequence.current || !input.current) return;
      input.current.value = text;
      setPreview(inspectBatch(text));
    } catch (err) {
      if (version === sequence.current) setPreview({ issues: [err.message || '无法读取 JSON 文件。'] });
    } finally {
      if (version === sequence.current) setReading(false);
    }
  }
  return <section className="training-card"><h3>批量导入组织结构</h3>
    <p>每批最多 500 个学院、1000 个专业、2000 个班级，文件或粘贴内容上限 1 MiB。相同编号会更新已有节点，省略 status 时按 active 保存。</p>
    <p>顶层可包含 colleges、programs、classes 数组。各节点填写 id 和 name，专业另填 college_id，班级另填 program_id。上级节点应已存在或包含在本批中。</p>
    <fieldset className="training-stack" disabled={busy}><legend>文件或粘贴 JSON</legend>
      <label>选择组织 JSON 文件 <input type="file" accept=".json,application/json" onChange={loadFile} /></label>
      <label>粘贴组织 JSON <textarea rows={5} ref={input} onChange={() => {
        sequence.current++; setReading(false); setPreview(null);
      }} /></label>
      <div><button type="button" disabled={reading} onClick={() => setPreview(inspectBatch(input.current.value))}>检查并预览</button></div>
      {reading && <p role="status">正在读取文件…</p>}
      {preview?.counts && <p role="status">本批学院 {preview.counts.colleges} 个 · 专业 {preview.counts.programs} 个 · 班级 {preview.counts.classes} 个</p>}
      {!!preview?.issues.length && <div role="alert"><ul>{preview.issues.map((issue, i) => <li key={i}>{issue}</li>)}</ul>
        {preview.totalErrors > preview.issues.length && <p>另有 {preview.totalErrors - preview.issues.length} 个字段错误。</p>}</div>}
      <div><button type="button" className="training-primary" disabled={reading || !preview?.payload} onClick={() => {
        // 提交时重新校验输入框的实际文本，以覆盖浏览器自动填充的情况。
        const checked = inspectBatch(input.current.value);
        setPreview(checked);
        if (!checked.payload || JSON.stringify(checked.payload) !== JSON.stringify(preview.payload)) return;
        save(async write => {
          const result = await write('/v1/organization/import', 'POST', checked.payload);
          if (input.current) input.current.value = '';
          setPreview(null);
          return `组织批量导入完成，学院 ${result.colleges} 个、专业 ${result.programs} 个、班级 ${result.classes} 个。`;
        });
      }}>确认批量导入</button></div>
    </fieldset>
  </section>;
}

function Roster({ request, classId, revision }) {
  const [offset, setOffset] = useState(0);
  const result = useRead(request, classPath(classId) + '/roster?offset=' + offset, revision);
  return <section className="training-card"><h3>在册学生</h3><Result result={result}>{data => <>
    {!data.items.length ? <p>本页没有在册学生。</p> : <div className="training-scroll"><table>
      <thead><tr><th>学生姓名</th><th>学号</th><th>账号编号</th></tr></thead>
      <tbody>{data.items.map(s => <tr key={s.actor_id}><td>{s.name}</td><td>{s.student_no || '未登记'}</td><td>{s.actor_id}</td></tr>)}</tbody>
    </table></div>}
    <Pager offset={offset} change={setOffset} hasMore={data.has_more} />
  </>}</Result></section>;
}

function Assignment({ request, classId, revision, readable, save, busy }) {
  const [q, setQ] = useState('');
  const [offset, setOffset] = useState(0);
  const [changes, setChanges] = useState(new Map());
  const path = classPath(classId) + '/staff';
  const result = useRead(request, readable && path + '?' + new URLSearchParams({ q, offset }), revision);
  const label = person => person.name + ' · ' + (person.actor_type === 'teacher' ? '教师' : '管理员')
    + ' · ' + person.actor_id + (person.status === 'disabled' ? '（已停用）' : '');
  function submit(previous, next) {
    return save(async write => {
      if (next.length > 200) throw new Error('每班最多分配 200 位职员。');
      await write(path, 'PUT', { expected_staff_ids: previous, staff_ids: next });
      setChanges(new Map());
      return '班级任课与管理范围已更新。';
    });
  }
  return <section className="training-card"><h3>分配班级职员</h3>
    {readable ? <>
      <Search label="职员姓名或编号" onSearch={value => { setQ(value); setOffset(0); }} />
      <Result result={result}>{({ items, assigned, has_more }) => {
        if (!Array.isArray(assigned)) return <p role="alert">未取得当前分配，请刷新。</p>;
        const previous = assigned.map(p => p.actor_id);
        const users = new Map([...assigned, ...items].map(p => [p.actor_id, p]));
        const active = id => changes.get(id) ?? previous.includes(id);
        const next = new Set(previous);
        for (const [id, enabled] of changes) enabled ? next.add(id) : next.delete(id);
        return <><p className="training-meta">原分配 {previous.length} 人，保存后 {next.size} 人。取消勾选将收回该班范围。</p>
          <fieldset className="training-stack" disabled={busy}><legend>当前分配与搜索结果</legend>
            {[...users.values()].map(p => <label key={p.actor_id}><input type="checkbox" checked={active(p.actor_id)}
              onChange={e => setChanges(prev => new Map(prev).set(p.actor_id, e.target.checked))} /> {label(p)}</label>)}
            {!users.size && <p>没有匹配的职员。</p>}
          </fieldset><Pager offset={offset} change={setOffset} hasMore={has_more} />
          <div><button disabled={busy || !changes.size} onClick={() => submit(previous, [...next])}>保存班级分配</button></div>
        </>;
      }}</Result>
    </> : <form onSubmit={event => {
      event.preventDefault();
      const f = new FormData(event.currentTarget);
      save(async write => {
        const staff_ids = idList(f.get('next'));
        if (staff_ids.length > 200) throw new Error('每班最多分配 200 位职员。');
        await write(path, 'PUT', { expected_staff_ids: idList(f.get('previous')), staff_ids });
        return '班级职员已更新。';
      });
    }}><fieldset disabled={busy} className="training-stack"><legend>按已知账号编号替换任课分配</legend>
      <label>当前全部职员编号 <textarea name="previous" rows={2} /></label>
      <label>更新后全部职员编号 <textarea name="next" rows={2} /></label>
      <p>编号用空格或换行分隔。清空更新后列表会撤销该班全部分配。</p><button>保存班级分配</button>
    </fieldset></form>}
  </section>;
}

function Enroll({ request, classId, revision, readable, save, busy }) {
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [selection, setSelection] = useState([]);
  const [text, setText] = useState('');
  const result = useRead(request, readable && query && '/v1/organization/roster-candidates?' + new URLSearchParams({ q: query, offset }), revision);
  return <section className="training-card"><h3>批量归班</h3>
    <p>名单中的学生将转入所选班级，原班级归属随之更新。</p>
    {readable && <Search label="查找学生（学号或姓名）" onSearch={value => { setQuery(value); setOffset(0); }} />}
    {readable && query && <Result result={result}>{data => <>
      <fieldset className="training-stack" disabled={busy}><legend>可归班学生</legend>
        {data.items.map(s => <label key={s.actor_id}><input type="checkbox" checked={selection.includes(s.actor_id)}
          onChange={e => setSelection(old => e.target.checked ? [...old, s.actor_id] : old.filter(id => id !== s.actor_id))} />
          {' '}{s.name} · {s.student_no || s.actor_id} · {s.class_name || '未分班'}</label>)}
        {!data.items.length && <p>当前范围没有匹配的学生。</p>}
      </fieldset><Pager offset={offset} change={setOffset} hasMore={data.has_more} />
    </>}</Result>}
    <form onSubmit={event => {
      event.preventDefault();
      save(async write => {
        const student_ids = [...new Set([...selection, ...idList(text)])];
        if (!student_ids.length || student_ids.length > 2000) throw new Error('每次导入 1 至 2000 个不同学生账号编号。');
        const data = await write(classPath(classId) + '/roster/import', 'POST', { student_ids });
        setSelection([]); setText(''); setQuery('');
        return '已完成归班，共 ' + data.count + ' 人。';
      });
    }}><fieldset className="training-stack" disabled={busy}><legend>导入名单</legend>
      <label>粘贴学生账号编号 <textarea value={text} onChange={e => setText(e.target.value)} rows={3} placeholder="每行一个账号编号，也可用逗号分隔" /></label>
      <span>已勾选 {selection.length} 人</span><div><button className="training-primary">导入所选班级</button></div>
    </fieldset></form>
  </section>;
}

function School({ request, schoolId, permissions }) {
  const readable = !!permissions.canReadOrganization;
  const manage = !!permissions.canManageNativeOrganization;
  const enroll = !!permissions.canImportRoster;
  const [revision, refresh] = useState(0);
  const [chosen, choose] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const structure = useRead(request, readable && '/v1/organization', revision);
  const data = readable && structure.data?.school_id === schoolId
    && ['colleges', 'programs', 'classes'].every(key => Array.isArray(structure.data[key])) ? structure.data : null;
  // 读取响应返回时，须同时核对当前会话的学校和版本。
  const current = readable ? data?.classes.find(c => c.class_id === chosen)?.class_id : chosen;
  async function save(operation) {
    if (busy) return;
    setMessage(null); setBusy(true);
    try {
      const text = await operation((path, method, body) => request(api + path, { method, body: JSON.stringify(body) }));
      setMessage({ text }); refresh(v => v + 1);
    } catch (err) {
      setMessage({ text: err.message || '保存失败。', error: true });
      if ([401, 403, 409].includes(err.status)) refresh(v => v + 1);
    } finally { setBusy(false); }
  }
  return <section className="training-page" aria-label="学校组织与班级名册">
    <header className="training-card"><h2>学校组织与班级名册</h2><div className="training-row"><span>学校编号 {schoolId}</span>
      <button disabled={busy} onClick={() => refresh(v => v + 1)}>刷新数据</button></div></header>
    {message && <p className="training-output" role={message.error ? 'alert' : 'status'}>{message.text}</p>}
    {readable && <section className="training-card"><h3>组织结构</h3>
      {data ? <>{data.colleges.length ? <ul className="training-list">{data.colleges.map(d => <li key={d.id}>
        <strong>{d.name} · {d.id}</strong>
        {data.programs.filter(p => p.college_id === d.id).map(p => <div key={p.id}><span>{p.name} · {p.id}</span>
          <div className="training-row">{data.classes.filter(c => c.program_id === p.id).map(c =>
            <button type="button" aria-pressed={chosen === c.class_id} disabled={busy} key={c.class_id}
              onClick={() => choose(c.class_id)}>{c.name} · {c.class_id}</button>)}</div>
        </div>)}
      </li>)}</ul> : <p>当前范围暂无组织节点。</p>}</> :
        structure.error || structure.data ? <p role="alert">{structure.error || '学校身份或组织结构数据无效。'}</p> : <p role="status">正在读取组织…</p>}
    </section>}
    {!readable && (manage || enroll) && <section className="training-card"><p>账号未获组织查看权限。可使用已有组织和账号编号提交已授权的变更。</p>
      <form onSubmit={event => { event.preventDefault(); try { choose(identifier(new FormData(event.currentTarget).get('id'))); }
        catch (err) { setMessage({ text: err.message, error: true }); } }}>
        <label>目标班级编号 <input required name="id" maxLength={128} /></label> <button disabled={busy}>选定班级</button>
      </form></section>}
    {!readable && !manage && !enroll && <p>当前账号没有组织或名册操作权限。</p>}
    {manage && (!readable || data) && <NodeForm data={data} save={save} busy={busy} />}
    {manage && <section className="training-card"><h3>从校方工作簿导入组织</h3>
      <form onSubmit={event => {
        event.preventDefault();
        const file = new FormData(event.currentTarget).get('structure');
        save(async write => {
          const result = await write('/v1/organization/import-workbook', 'POST', await encodeSchoolFile(file));
          return `组织导入完成，新增学院 ${result.colleges} 个、专业 ${result.programs} 个、班级 ${result.classes} 个。`;
        });
      }}><label>组织 Excel 或 CSV <input name="structure" type="file" accept=".xlsx,.csv" required /></label>
      <button disabled={busy}>导入组织工作簿</button></form>
      <p>支持整行学院、专业、班级或 Excel 分表。已有节点不覆盖，导入不会授予任何教职工权限。</p>
    </section>}
    {manage && <BatchForm save={save} busy={busy} />}
    {current && <div key={current} className="training-stack"><h3>当前班级 · {current}</h3>
      {readable && <Roster request={request} classId={current} revision={revision} />}
      {manage && <Assignment request={request} classId={current} revision={revision} readable={readable} save={save} busy={busy} />}
      {enroll && <Enroll request={request} classId={current} revision={revision} readable={readable} save={save} busy={busy} />}
    </div>}
    {readable && data?.classes.length > 0 && !current && <p>选择班级后可查看名册。</p>}
  </section>;
}

export default function NativeSchoolOrganization({ request, permissions = {}, schoolId }) {
  if (!schoolId) return <p role="alert">未取得当前学校身份。</p>;
  return <School key={schoolId} request={request} permissions={permissions} schoolId={schoolId} />;
}
