// 渲染实际页面组件，模拟请求仅用于此测试。共享测试运行时可通过 NODE_PATH 指定 jsdom。
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { JSDOM } = require('jsdom');
const { buildSync } = require('esbuild');

(async () => {
  const tmp = mkdtempSync(path.join(os.tmpdir(), 'native-org-'));
  const dom = new JSDOM('<main></main>', { url: 'https://school.example' });
  const dir = path.resolve(__dirname, '../..');
  const bundle = path.join(tmp, 'module.cjs');
  try {
    buildSync({ stdin: { resolveDir: dir, contents: `
      export {default as Page} from './admin/src/NativeSchoolOrganization.jsx';
      export * as React from 'react'; export {createRoot} from 'react-dom/client';` },
      outfile: bundle, platform: 'node', format: 'cjs', bundle: true, loader: { '.css': 'empty' },
      define: { 'process.env.NODE_ENV': '"development"' } });
    for (const key of ['window', 'document', 'FormData', 'Event', 'HTMLElement']) global[key] = dom.window[key];
    global.IS_REACT_ACT_ENVIRONMENT = true;
    const { React, Page, createRoot } = require(bundle);
    const host = document.querySelector('main');
    const root = createRoot(host);
    const calls = [];
    let assigned = ['t1'];
    let people = [{ actor_id: 's1', student_no: '20260001', name: '许同学' }];
    let school = 'east';
    let conflict = false;
    const staff = [{ actor_id: 't1', name: '李老师', actor_type: 'teacher' },
                   { actor_id: 't2', name: '林老师', actor_type: 'teacher' }];
    const all = { canReadOrganization: true, canManageNativeOrganization: true, canImportRoster: true };
    async function request(address, init = {}) {
      const u = new URL(address, dom.window.location.href);
      assert(u.pathname.startsWith('/api/admin/identity/'));
      const p = u.pathname.slice('/api/admin/identity'.length);
      const body = init.body && JSON.parse(init.body);
      calls.push({ path: p, method: init.method || 'GET', body, q: u.searchParams.get('q') });
      if (p === '/v1/organization') return { school_id: school, colleges: [{ id: 'd', name: '工程学院' }],
        programs: [{ id: 'p', college_id: 'd', name: '软件工程' }],
        classes: [{ class_id: 'c', program_id: 'p', college_id: 'd', name: '软件一班' }] };
      if (p === '/v1/classes/c/roster') return { items: people, has_more: false };
      if (p === '/v1/organization/roster-candidates') return { items: [{ actor_id: 's2', name: '钟同学', student_no: '20260002' }] };
      if (p === '/v1/classes/c/roster/import') {
        people = [...people, { actor_id: 's2', name: '钟同学', student_no: '20260002' }];
        return { count: body.student_ids.length };
      }
      if (p === '/v1/classes/c/staff') {
        if (body) {
          if (conflict) throw Object.assign(Error('分配已变化'), { status: 409 });
          assigned = body.staff_ids; return { staff_ids: assigned };
        }
        return { items: staff, assigned: staff.filter(t => assigned.includes(t.actor_id)), has_more: false };
      }
      if (p === '/v1/organization/import')
        return Object.fromEntries(['colleges','programs','classes'].map(k => [k, body[k]?.length || 0]));
      throw Error(p);
    }
    const render = perms => React.act(async () => root.render(React.createElement(Page, { request, schoolId: school, permissions: perms })));
    function byText(text, selector = 'button') {
      const found = [...host.querySelectorAll(selector)].find(e => e.textContent === text);
      assert.ok(found, text); return found;
    }
    const click = element => React.act(async () => element.click());
    const submit = form => React.act(async () => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
    await render(all);
    await click(byText('软件一班 · c'));
    assert(host.textContent.includes('许同学'));
    let field = byText(' 林老师 · 教师 · t2', 'label').querySelector('input');
    await click(field); await click(byText('保存班级分配'));
    assert.deepEqual(calls.find(c => c.method === 'PUT').body, { expected_staff_ids: ['t1'], staff_ids: ['t1','t2'] });
    conflict = true;
    await click(byText(' 李老师 · 教师 · t1', 'label').querySelector('input'));
    await click(byText('保存班级分配'));
    assert(host.textContent.includes('分配已变化')); assert.deepEqual(assigned, ['t1','t2']);
    const form = byText('查找学生（学号或姓名） ', 'label').closest('form');
    form.elements.q.value = '钟'; await submit(form);
    const student = [...host.querySelectorAll('label')].find(el => el.textContent.includes('钟同学'));
    await click(student.querySelector('input'));
    await submit(byText('导入所选班级').closest('form'));
    assert.deepEqual(calls.find(c => c.path.endsWith('/roster/import')).body, { student_ids: ['s2'] });
    assert(host.textContent.includes('已完成归班，共 1 人。'));
    const node = byText('保存组织节点').closest('form');
    node.elements.id.value = 'eng'; node.elements.name.value = '新学院'; await submit(node);
    assert.deepEqual(calls.find(c => c.path === '/v1/organization/import').body, { colleges: [{id:'eng',name:'新学院'}] });
    const importCalls = () => calls.filter(c => c.path === '/v1/organization/import');
    const confirmImport = () => byText('确认批量导入');
    const pasted = host.querySelector('textarea[rows="5"]');
    const batch = {
      colleges: [{id:'d2',name:'第二学院'}],
      programs: [{id:'p2',name:'第二专业',college_id:'d2'}],
      classes: [{id:'c2',name:'二班',program_id:'p2'}, {id:'c3',name:'三班',program_id:'p2',status:'inactive'}],
    };
    async function checkPaste(value) {
      pasted.value = value;
      await click(byText('检查并预览'));
    }
    await checkPaste(JSON.stringify({
      school_id:'different', colleges:[{ id:'dup',name:' ' },{ id:'dup',name:'重复' }],
      programs:[{ id:'p',name:'专业' }], classes:[{ id:'c',name:'班级',program_id:'p',staff_ids:['unauthorized'] }],
    }));
    for (const issue of ['顶层字段 school_id','colleges[0].name','colleges[1].id',
                         'programs[0].college_id','classes[0].staff_ids'])
      assert(host.textContent.includes(issue), issue);
    assert(confirmImport().disabled);
    await checkPaste('{"colleges":'); assert(host.textContent.includes('JSON 格式错误'));
    await checkPaste('X'.repeat(1024 * 1024 + 1)); assert(host.textContent.includes('超过 1 MiB'));
    assert(confirmImport().disabled); assert.equal(importCalls().length, 1);
    await checkPaste(JSON.stringify(batch));
    assert(host.textContent.includes('本批学院 1 个 · 专业 1 个 · 班级 2 个'));
    await click(confirmImport());
    assert.deepEqual(importCalls().at(-1).body, batch);
    assert(host.textContent.includes('组织批量导入完成，学院 1 个、专业 1 个、班级 2 个。'));
    const upload = host.querySelector('input[type=file][accept*=json]');
    async function uploadJSON(file) {
      Object.defineProperty(upload, 'files', { configurable:true, value:[file] });
      await React.act(async () => {
        upload.dispatchEvent(new Event('change', { bubbles:true }));
        await new Promise(resolve => setTimeout(resolve, 25));
      });
    }
    await uploadJSON(new dom.window.File(['0'.repeat(1024*1024+1)], 'big.json'));
    assert(host.textContent.includes('JSON 文件超过 1 MiB')); assert(confirmImport().disabled);
    await uploadJSON(new dom.window.File([JSON.stringify(batch)], 'structure.json', {type:'application/json'}));
    assert(host.textContent.includes('本批学院 1 个 · 专业 1 个 · 班级 2 个'));
    assert.equal(importCalls().length, 2); // 选择文件只生成预览，确认后才会写入。
    await click(confirmImport()); assert.deepEqual(importCalls().at(-1).body, batch);
    assert.equal(importCalls().length, 3);
    await render({ canReadOrganization: true });
    assert(!host.textContent.includes('保存组织节点')); assert(!host.textContent.includes('批量归班'));
    assert(!host.textContent.includes('批量导入组织结构'));
    const before = calls.length;
    school = 'west';
    await render({ canImportRoster: true });
    assert(!host.textContent.includes('许同学')); assert(!host.textContent.includes('工程学院'));
    assert.equal(calls.length, before);
    const target = byText('选定班级').closest('form');
    target.elements.id.value = 'c'; await submit(target);
    assert(host.textContent.includes('粘贴学生账号编号')); assert(!host.textContent.includes('在册学生'));
    await submit(byText('导入所选班级').closest('form'));
    assert(host.textContent.includes('每次导入 1 至 2000')); assert.equal(calls.length, before);
    await React.act(async () => root.unmount());
    console.log('PASS named roster, multi-level JSON file/paste import with field and size validation, organization write, staff replacement/conflict, selection import, read-only and write-only school switch');
  } finally { dom.window.close(); rmSync(tmp, { recursive: true, force: true }); }
// JSDOM 的调度器可能保留 MessagePort；隔离进程完成断言后显式结束。
})().then(() => process.exit(0), err => { console.error(err); process.exit(1); });
