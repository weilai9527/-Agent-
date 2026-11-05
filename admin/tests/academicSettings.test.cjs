// 运行实际管理端入口，以独立的学校接口夹具验证登录、侧栏、授权和版本冲突。
const assert = require('node:assert/strict');
const { test } = require('node:test');
const path = require('node:path');
const { setTimeout: sleep } = require('node:timers/promises');
const { buildSync } = require('esbuild');
const { JSDOM } = require('jsdom');

const source = buildSync({
  entryPoints: [path.resolve(__dirname, '../src/main.jsx')], bundle: true, write: false, format: 'iife',
  loader: { '.css': 'empty', '.png': 'dataurl' },
  define: { 'import.meta.env': '{}', 'process.env.NODE_ENV': '"production"' },
}).outputFiles[0].text;

async function fixture(t, permissions, options = {}) {
  const dom = new JSDOM('<div id="root"></div>', { runScripts: 'outside-only', url: 'https://school.test/admin/' });
  const { window } = dom, doc = window.document;
  t.after(() => window.close());
  Object.defineProperty(doc, 'hidden', { value: false });
  const timers = new Map();
  const originalInterval = window.setInterval.bind(window);
  window.setInterval = (callback, delay, ...args) => {
    if (delay !== 30000) return originalInterval(callback, delay, ...args);
    const id = Symbol('poll');
    timers.set(id, callback);
    return id;
  };
  const clearInterval = window.clearInterval.bind(window);
  window.clearInterval = id => { if (!timers.delete(id)) clearInterval(id); };
  const calls = [], unexpected = [];
  const account = { id: 'operator', school_id: 'school-a', name: '教务员', actorType: options.staffRole || 'admin', role: options.staffRole || 'admin', permissions: [] };
  let loggedIn = false;
  const program = { id: 'p', college_id: 'c', name: '软件工程', jobs: [], revision: 3, canEdit: options.programEditable !== false };
  const job = { id: 'j', name: '软件开发', code: 'DEV', sourceMajor: '软件工程', competencies: [] };
  const config = { school_id: 'school-a', revision: 8, colleges: [{id:'c1', name:'原学院', majors:[{id:'m1', name:'原专业'}]}] };
  window.fetch = async (url, init) => {
    const method = init.method || 'GET', body = init.body && JSON.parse(init.body);
    calls.push({url, method, body});
    const reply = (data, status = 200) => ({ ok: status < 400, status, headers: new Headers(), json: async () => structuredClone(data) });
    if (url.startsWith('/api/admin/identity/v1/students?') && options.students) {
      return reply({ school_id:account.school_id, items:options.students, total:options.students.length });
    }
    if (url.startsWith('/api/admin/students/') && options.profile) {
      assert.equal(init.cache, 'no-store');
      const id = url.split('/')[4];
      const result = await options.profile(id, init.signal);
      return reply(result.body, result.status || 200);
    }
    switch (url) {
      case '/api/admin/auth/me': return reply({}, 401);
      case '/api/admin/auth/login':
        assert.deepEqual(body, {email:'editor@school.test', password:'Synthetic-Test-123'}); loggedIn = true; return reply({admin:account});
      case '/api/admin/snapshot':
        assert(loggedIn); return options.expired ? reply({}, 401) : reply({identityMode:'native', admin:account, permissions});
      case '/api/admin/campus/program-jobs':
        program.canEdit = options.programEditable !== false;
        return reply({school_id: options.wrongSchool ? 'b' : 'school-a', programs:options.removed ? [] : [program], colleges:[{id:'c', name:'工程学院'}], jobs:[job], canEdit:true});
      case '/api/admin/campus/programs/p/jobs':
        assert.equal(body.expectedRevision, program.revision);
        program.revision++; program.jobs = body.jobs.map(x => ({job_role_id:x.jobRoleId, priority:x.priority}));
        return reply({ok:true, school_id:'school-a', revision: program.revision, jobs:body.jobs});
      case '/api/admin/resume-form-settings':
        if (method === 'PUT') {
          if (options.conflict) { options.conflict = false; config.revision++; return reply({error:'配置已修改'}, 409); }
          assert.equal(body.expected_revision, config.revision);
          config.revision++; config.colleges = body.colleges;
        }
        return reply({...config, school_id: options.wrongSchool ? 'b' : 'school-a'});
      default: unexpected.push(url); return reply({error:'意外的读取'}, 404);
    }
  };
  window.eval(source);
  async function wait(fn) {
    for (let i=0; i<200; i++) { const value=fn(); if(value) return value; await sleep(10); }
    throw new Error('未出现预期控件：'+doc.body.textContent.slice(-700));
  }
  const button = text => [...doc.querySelectorAll('button')].find(el=>el.textContent.trim() === text);
  const click = async text => {
    const btn = await wait(()=>button(text)); assert(!btn.disabled, text); btn.click(); await sleep(10);
  };
  async function type(field, value) {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set.call(field,value);
    field.dispatchEvent(new window.Event('input',{bubbles:true})); await sleep(10);
  }
  await wait(()=>doc.querySelector('input[type=email]'));
  await type(doc.querySelector('input[type=email]'),'editor@school.test');
  await type(doc.querySelector('input[type=password]'),'Synthetic-Test-123');
  doc.querySelector('button[type=submit]').click();
  await wait(()=>doc.querySelector('.admin-nav') && doc.body.textContent.includes('集中处理学生待办'));
  t.after(()=>assert.deepEqual(unexpected, []));
  return { doc, calls, click, wait, type, button,
    poll: async () => { assert.equal(timers.size, 1); await [...timers.values()][0](); },
    refocus: () => doc.dispatchEvent(new window.Event('visibilitychange')),
  };
}

test('从登录侧栏进入专业关联，选择岗位并保存当前专业版本', async t => {
  const ui = await fixture(t, {canReadProgramJobs:true, canManageProgramJobs:true});
  assert(!ui.button('简历表单配置'));
  await ui.click('专业关联岗位');
  await ui.click('添加岗位');
  ui.doc.querySelector('[role=dialog] input[type=checkbox]').click();
  await ui.click('完成选择');
  await ui.click('保存专业配置');
  await ui.wait(()=>ui.doc.body.textContent.includes('已保存 软件工程 的 1 个关联岗位'));
  assert.deepEqual(ui.calls.find(row=>row.method==='PUT').body, {jobs:[{jobRoleId:'j',priority:'recommended'}], expectedRevision:3});
});

test('表单配置保留学院与专业编号，冲突后重新读取再编辑', async t => {
  const ui = await fixture(t, {canReadResumeFormSettings:true, canManageResumeFormSettings:true}, {conflict:true});
  assert(!ui.button('专业关联岗位'));
  await ui.click('简历表单配置');
  const input = () => ui.doc.querySelector('section[aria-label="简历表单学院与专业"] fieldset input');
  await ui.wait(input);
  await ui.type(input(), '新学院'); await ui.click('保存表单配置');
  await ui.wait(()=>ui.doc.body.textContent.includes('其他管理员已更改配置'));
  assert(ui.button('保存表单配置').disabled);
  await ui.click('放弃草稿并重新读取'); await ui.wait(()=>input()?.value === '原学院');
  await ui.type(input(), '新学院'); await ui.click('保存表单配置');
  await ui.wait(()=>ui.doc.body.textContent.includes('已保存本校简历表单配置'));
  assert.deepEqual(ui.calls.filter(r=>r.method==='PUT').map(r=>r.body.expected_revision), [8,9]);
  assert.deepEqual(ui.calls.filter(r=>r.method==='PUT').at(-1).body.colleges,[{id:'c1',name:'新学院',majors:[{id:'m1',name:'原专业'}]}]);
});

test('只读账号可进入两个页面且没有编辑操作', async t => {
  const ui = await fixture(t, {canReadProgramJobs:true,canReadResumeFormSettings:true});
  await ui.click('专业关联岗位'); await ui.wait(()=>ui.doc.body.textContent.includes('软件工程 · 就业岗位'));
  assert(!ui.button('添加岗位')); assert(!ui.button('保存专业配置'));
  await ui.click('简历表单配置'); await ui.wait(()=>ui.doc.body.textContent.includes('原专业'));
  assert(!ui.button('保存表单配置')); assert(!ui.button('添加学院'));
  assert(!ui.calls.some(r=>r.method==='PUT'));
});

test('跨校响应不渲染数据，也不开放保存', async t => {
  const ui = await fixture(t,{canReadProgramJobs:true,canManageProgramJobs:true,canReadResumeFormSettings:true,canManageResumeFormSettings:true},{wrongSchool:true});
  await ui.click('专业关联岗位'); await ui.wait(()=>ui.doc.body.textContent.includes('配置与当前学校或版本不匹配'));
  assert(!ui.doc.body.textContent.includes('软件工程 · 就业岗位'));
  await ui.click('简历表单配置'); await ui.wait(()=>ui.doc.body.textContent.includes('表单配置与本校或当前版本不匹配'));
  assert(!ui.doc.body.textContent.includes('原专业')); assert(!ui.button('保存表单配置'));
});

test('账号持有写权限时，仍须获得当前专业的编辑权', async t => {
  const ui = await fixture(t, {canReadProgramJobs:true, canManageProgramJobs:true}, {programEditable:false});
  await ui.click('专业关联岗位');
  await ui.wait(()=>ui.doc.body.textContent.includes('修改需要该专业的配置权限'));
  assert(!ui.button('添加岗位')); assert(!ui.button('保存专业配置'));
  assert(!ui.calls.some(r=>r.method==='PUT'));
});

test('专业授权撤回后定时快照清空旧页面，不能再从缓存切换', async t => {
  const grants = {canReadProgramJobs:true, canManageProgramJobs:true};
  const ui = await fixture(t, grants);
  await ui.click('专业关联岗位'); await ui.click('添加岗位');
  grants.canReadProgramJobs = false;
  await ui.poll();
  await ui.wait(()=>!ui.button('专业关联岗位') && !ui.doc.querySelector('.pj-page'));
  assert(!ui.doc.body.textContent.includes('软件工程'));
  assert(!ui.calls.some(r=>r.url.endsWith('/health')));
});

test('页面恢复可见时检查实际专业范围，丢弃失权专业和未保存草稿', async t => {
  const options = {};
  const ui = await fixture(t, {canReadProgramJobs:true,canManageProgramJobs:true}, options);
  await ui.click('专业关联岗位'); await ui.click('添加岗位');
  ui.doc.querySelector('[role=dialog] input[type=checkbox]').click();
  await ui.click('完成选择'); await ui.wait(()=>ui.doc.body.textContent.includes('有未保存修改'));
  const reads = () => ui.calls.filter(r=>r.url.endsWith('campus/program-jobs')).length;
  const before = reads();
  ui.refocus();
  await ui.wait(()=>reads() > before && ui.doc.body.textContent.includes('有未保存修改'));
  options.programEditable = false;
  await ui.poll(); await ui.wait(()=>!ui.button('保存专业配置'));
  assert(!ui.doc.body.textContent.includes('有未保存修改'));
  options.removed = true;
  ui.refocus(); await ui.wait(()=>!ui.doc.body.textContent.includes('软件工程'));
  assert(!ui.calls.some(r=>r.method==='PUT'));
});

test('简历设置会话失效后重返登录，已加载学校配置不再可见', async t => {
  const options = {};
  const ui = await fixture(t, {canReadResumeFormSettings:true,canManageResumeFormSettings:true}, options);
  await ui.click('简历表单配置'); await ui.wait(()=>ui.button('保存表单配置'));
  options.expired = true;
  ui.refocus();
  await ui.wait(()=>ui.doc.querySelector('input[type=email]'));
  assert(!ui.doc.body.textContent.includes('原学院'));
  assert(!ui.button('保存表单配置'));
  assert(!ui.calls.some(r=>r.url.endsWith('/health')));
});

const students = [
  {actor_id:'a', name:'甲同学', school_id:'school-a', student_no:'A01', status:'normal'},
  {actor_id:'b', name:'乙同学', school_id:'school-a', student_no:'B01', status:'normal'},
];
function dossier(id) {
  return {school_id:'school-a',student_id:id,version:3,profile:{target_role:'后端开发',skills:'SQL',
    education_level:'本科',project_experience:'合成课程设计',resume_summary:'合成教学摘要 '+id,
    resume_text:'测试用完整简历', email:'hidden@example.test'}};
}
const profileCalls = ui => ui.calls.filter(row => row.url.startsWith('/api/admin/students/'));

test('从学校管理选择学生后按需查看教学摘要，换人、撤权清除旧档案', async t => {
  const grants = {canUseSchoolManagement:true,canReadStudentAccounts:true,canReadStudentProfile:true};
  const ui = await fixture(t, grants, {students, profile: async id => ({body:dossier(id)})});
  await ui.click('学校管理');
  await ui.click('选择 甲同学');
  assert.equal(profileCalls(ui).length, 0);
  await ui.click('查看教学档案');
  await ui.wait(()=>ui.doc.body.textContent.includes('合成教学摘要 a'));
  assert(!ui.doc.body.textContent.includes('测试用完整简历'));
  assert(!ui.doc.body.textContent.includes('hidden@example.test'));
  await ui.click('选择 乙同学');
  assert(!ui.doc.body.textContent.includes('合成教学摘要 a'));
  assert.deepEqual(profileCalls(ui).map(r=>r.url), ['/api/admin/students/a/profile']);
  await ui.click('查看教学档案');
  await ui.wait(()=>ui.doc.body.textContent.includes('合成教学摘要 b'));
  grants.canReadStudentProfile = false;
  await ui.poll();
  await ui.wait(()=>!ui.doc.body.textContent.includes('合成教学摘要 b') && !ui.button('查看教学档案'));
  assert.equal(profileCalls(ui).length, 2);
});

test('教学档案独立授权不获取名册，错误学校、错误学生与拒绝响应均不展示私有文本', async t => {
  const grants = {canUseSchoolManagement:true,canReadStudentProfile:true};
  const options = {staffRole:'teacher', profile:async id => ({body:{...dossier(id),school_id:'other-school'}})};
  const ui = await fixture(t, grants, options);
  await ui.click('学校管理');
  const input = await ui.wait(()=>ui.doc.querySelector('input[maxlength="128"]'));
  await ui.type(input, 'a');
  await ui.click('查看教学档案'); await ui.wait(()=>ui.doc.querySelector('[role=alert]'));
  assert(!ui.doc.body.textContent.includes('合成教学摘要'));
  options.profile = async id => ({body:{...dossier(id),student_id:'other-student'}});
  await ui.click('查看教学档案');
  assert(!ui.doc.body.textContent.includes('合成教学摘要'));
  for (const [status, message] of [[403,'当前账号无权'],[404,'当前学生暂无'],[503,'暂时无法核验']]) {
    options.profile = async () => ({status, body:{error:'不得显示的原文'}});
    await ui.click('查看教学档案'); await ui.wait(()=>ui.doc.querySelector('[role=alert]')?.textContent.includes(message));
    assert(!ui.doc.body.textContent.includes('不得显示的原文'));
  }
  assert(!ui.calls.some(row=>row.url.startsWith('/api/admin/identity/v1/students?')));
});

test('换人后迟到的旧请求不会展开档案，也不会预取下一人的档案', async t => {
  let resolve, signal;
  const ui = await fixture(t, {canUseSchoolManagement:true,canReadStudentAccounts:true,canReadStudentProfile:true},
    {students,profile:(id, currentSignal) => { signal = currentSignal; return new Promise(done=>{resolve=done;}); }});
  await ui.click('学校管理'); await ui.click('选择 甲同学'); await ui.click('查看教学档案');
  await ui.click('选择 乙同学'); assert(signal.aborted);
  resolve({body:dossier('a')});
  await sleep(10);
  assert(!ui.doc.body.textContent.includes('合成教学摘要'));
  assert.equal(profileCalls(ui).length, 1);
});

test('仅持名册读取权限的教师无教学档案入口且不会访问档案服务', async t => {
  const ui = await fixture(t, {canUseSchoolManagement:true,canReadStudentAccounts:true}, {students,staffRole:'teacher'});
  await ui.click('学校管理');
  await ui.wait(()=>ui.doc.body.textContent.includes('甲同学'));
  assert(!ui.button('查看教学档案')); assert(!ui.button('选择 甲同学'));
  assert.equal(profileCalls(ui).length, 0);
});
