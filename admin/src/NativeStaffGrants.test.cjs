// 使用 node --test 运行。界面测试环境可通过 NODE_PATH 提供 jsdom。
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const { transformSync } = require('esbuild');

const filename = path.join(__dirname, 'NativeStaffGrants.jsx');
const compiled = transformSync(fs.readFileSync(filename, 'utf8'), { loader: 'jsx', format: 'cjs' }).code;
const component = new Module(filename, module);
component.paths = module.paths;
component._compile(compiled, filename);
const Staff = component.exports.default;
const React = require('react');
const grants = ['report.read', 'report.review', 'score.adjust', 'permissions.manage'];
const admin = { id: 'manager', actorType: 'admin', school_id: 'test-school' };
const baseProps = { permissions: { canManageStaff: true }, admin, schoolId: admin.school_id };
const account = (id, role) => ({
  actor_id: id, name: id, email: id + '@example.test', school_id: admin.school_id, actor_type: role,
  school_wide: role === 'admin', status: 'normal', revision: 'a'.repeat(64), permissions: ['report.read'],
});
const result = items => ({ items, actions: grants, admin_only: ['permissions.manage'],
  teacher_only: ['score.adjust'], total: items.length, limit: 50, offset: 0 });

test('unauthorized, non-admin and mismatched school contexts have no manager controls', () => {
  const render = require('react-dom/server').renderToStaticMarkup;
  for (const props of [{ permissions: {} }, { admin: { ...admin, actorType: 'teacher' } }, { schoolId: 'another' }]) {
    const html = render(React.createElement(Staff, { ...baseProps, ...props }));
    assert.doesNotMatch(html, /<form|<button/);
  }
});

let jsdom;
try { jsdom = require.resolve('jsdom'); } catch {}
const domTest = (title, fn) => test(title, { skip: !jsdom && 'Requires the jsdom UI test runtime' }, fn);

async function mount(request) {
  const { JSDOM } = require(jsdom);
  const dom = new JSDOM('<main></main>', { url: 'https://identity.example.test' });
  Object.assign(globalThis, { window: dom.window, document: dom.window.document, FormData: dom.window.FormData,
    IS_REACT_ACT_ENVIRONMENT: true });
  const root = require('react-dom/client').createRoot(document.querySelector('main'));
  const render = props => React.act(async () => root.render(React.createElement(Staff, { request, ...baseProps, ...props })));
  await render();
  const click = (label, area = document) => React.act(async () => {
    const button = [...area.querySelectorAll('button')].find(el => el.textContent === label);
    assert.ok(button && !button.disabled, 'Available action: ' + label);
    button.click();
  });
  const submit = form => React.act(async () => form.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true })));
  const close = async () => {
    await React.act(async () => root.unmount());
    dom.window.close();
  };
  return { click, submit, close, render };
}

domTest('list is read-only, self is protected, edit retains legacy grants, disable and create reread the list', async () => {
  const self = account('manager', 'admin');
  const teacher = account('teacher', 'teacher');
  const items = [self, { ...teacher, permissions: ['report.read', 'permissions.manage'] }];
  const calls = [];
  let createFails = true;
  const ui = await mount(async (url, options) => {
    const method = options.method || 'GET';
    const body = options.body && JSON.parse(options.body);
    calls.push({ method, url, body });
    if (method === 'GET') return result(items);
    if (method === 'PUT') {
      assert.equal(url, '/api/admin/identity/v1/staff/teacher/grants');
      assert.deepEqual(body, { actor_type: 'teacher', status: 'disabled', school_wide: false,
        permissions: ['permissions.manage', 'report.review'], expected_revision: teacher.revision });
      items[1] = { ...items[1], ...body };
      return { ok: true };
    }
    assert.equal(url, '/api/admin/identity/v1/staff');
    assert.deepEqual(body, { actor_type: 'admin', status: 'normal', school_wide: true, permissions: ['report.read'],
      email: 'new@example.test', name: '新管理员', password: 'synthetic-test-password' });
    if (createFails) { createFails = false; throw new Error('邮箱已存在'); }
    items.push({ ...account('new-id', 'admin'), name: body.name, email: body.email });
    return { actor_id: 'new-id' };
  });
  try {
    assert.deepEqual(calls.map(c => c.method), ['GET']);
    assert.equal(document.querySelector('tbody tr:first-child button'), null);
    await ui.click('编辑');
    await ui.submit(document.querySelector('form.settings-form'));
    assert.deepEqual(calls.map(c => c.method), ['GET']);
    await ui.click('编辑');
    let form = document.querySelector('form.settings-form');
    assert.equal(form.querySelector('[value="permissions.manage"]'), null);
    form.querySelector('[value="report.read"]').checked = false;
    form.querySelector('[value="report.review"]').checked = true;
    form.elements.status.value = 'disabled';
    await ui.submit(form);
    assert.deepEqual(calls.map(c => c.method), ['GET', 'PUT', 'GET']);
    assert.match(document.querySelector('tbody tr:nth-child(2)').textContent, /已停用/);
    await ui.click('新增账号');
    form = document.querySelector('form.settings-form');
    form.elements.email.value = 'new@example.test';
    form.elements.name.value = '新管理员';
    form.elements.password.value = 'synthetic-test-password';
    const role = form.querySelector('select');
    await React.act(async () => {
      role.value = 'admin';
      role.dispatchEvent(new window.Event('change', { bubbles: true }));
    });
    assert.equal(form.querySelector('[value="score.adjust"]'), null);
    form.querySelector('[value="report.read"]').checked = true;
    form.elements.school_wide.checked = true;
    await ui.submit(form);
    assert.match(document.querySelector('[role="alert"]').textContent, /邮箱已存在/);
    await ui.submit(form);
    assert.equal(document.querySelector('[name="password"]'), null);
    assert.match(document.querySelector('[role="status"]').textContent, /已创建账号/);
    assert.match(document.querySelector('tbody').textContent, /new@example\.test/);
    assert.deepEqual(calls.map(c => c.method), ['GET', 'PUT', 'GET', 'POST', 'POST', 'GET']);
  } finally { await ui.close(); }
});

domTest('a revision conflict retires the stale form and requires a fresh read', async () => {
  let stale = true;
  const methods = [];
  const ui = await mount(async (_url, options) => {
    methods.push(options.method || 'GET');
    if (!options.method) return result([account('target', 'admin')]);
    if (stale) throw Object.assign(new Error('conflict'), { status: 409 });
    return { ok: true };
  });
  try {
    await ui.click('编辑');
    document.querySelector('form.settings-form [value="report.review"]').checked = true;
    await ui.submit(document.querySelector('form.settings-form'));
    assert.match(document.querySelector('[role="alert"]').textContent, /刷新列表/);
    assert.equal(document.querySelector('form.settings-form'), null);
    assert.deepEqual(methods, ['GET', 'PUT']);
    await ui.click('刷新列表');
    stale = false;
    await ui.click('编辑');
    document.querySelector('form.settings-form [value="report.review"]').checked = true;
    await ui.submit(document.querySelector('form.settings-form'));
    assert.deepEqual(methods, ['GET', 'PUT', 'GET', 'PUT', 'GET']);
  } finally { await ui.close(); }
});

domTest('switching schools aborts the old fetch and rejects mismatched account rows', async () => {
  let resolveOld, count = 0, signal;
  const ui = await mount((_url, options) => {
    if (count++ === 0) {
      signal = options.signal;
      return new Promise(done => { resolveOld = done; });
    }
    return Promise.resolve(result([account('private-old-school', 'admin')]));
  });
  try {
    await ui.render({ admin: { ...admin, school_id: 'new-school' }, schoolId: 'new-school' });
    assert.ok(signal.aborted);
    await React.act(async () => resolveOld(result([account('private-old-school', 'teacher')])));
    assert.match(document.querySelector('[role="alert"]').textContent, /学校/);
    assert.doesNotMatch(document.body.textContent, /private-old-school/);
    assert.equal(document.querySelector('tbody'), null);
  } finally { await ui.close(); }
});
