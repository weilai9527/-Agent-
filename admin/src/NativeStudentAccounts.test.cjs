const { test } = require('node:test');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { createInterface } = require('node:readline');
const path = require('node:path');
const Module = require('node:module');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const filename = path.join(__dirname, 'NativeStudentAccounts.jsx');
const compiled = require('esbuild').buildSync({ entryPoints:[filename], bundle:true, platform:'node', format:'cjs',
  write:false, loader:{'.css':'empty'}, external:['react','react-dom','react-dom/*'] }).outputFiles[0].text;
const component = new Module(filename, module);
component.paths = module.paths;
component.require = name => name.endsWith('.css') ? undefined : require(name);
component._compile(compiled, filename);
const Accounts = component.exports.default;
const full = { canReadStudentAccounts: true, canImportStudentAccounts: true, canResetStudentPasswords: true, canSetStudentStatus: true };

test('grant flags gate import, directory and manual-ID controls independently', () => {
  const html = (permissions, schoolId = 'UI-test') => renderToStaticMarkup(React.createElement(Accounts, { permissions, schoolId }));
  assert.doesNotMatch(html(full, ''), /<input|<button/);
  assert.doesNotMatch(html({}), /<form|<input|<button/);
  assert.match(html({ canImportStudentAccounts: true }), /待开通学生/);
  assert.doesNotMatch(html({ canImportStudentAccounts: true }), /学生名册|学生账号 ID/);
  assert.match(html({ canResetStudentPasswords: true }), /学生账号 ID/);
  assert.match(html({ canManageStudentGrants: true }), /学生账号 ID/);
  assert.doesNotMatch(html({ canSetStudentStatus: true }), /待开通学生|学生名册/);
  assert.doesNotMatch(html({ canReadStudentAccounts: true }), /账号维护|待开通学生/);
});

let domRuntime;
try { domRuntime = require.resolve('jsdom'); } catch {}
// 将 IDENTITY_TEST_PYTHON 指向已安装 services/requirements.txt 依赖的 Python。
// 本测试的请求只发往临时搭建的本地 FastAPI 服务和 SQLite 测试库。
test('mounted form writes real accounts and rereads status, search and reset state', {
  skip: (!domRuntime || !process.env.IDENTITY_TEST_PYTHON) && 'Requires jsdom and IDENTITY_TEST_PYTHON',
}, async (t) => {
  const { JSDOM } = require(domRuntime);
  const dom = new JSDOM('<main></main>', { url: 'https://admin.example.test' });
  Object.assign(globalThis, { window: dom.window, document: dom.window.document, FormData: dom.window.FormData,
    IS_REACT_ACT_ENVIRONMENT: true });
  const root = require('react-dom/client').createRoot(document.querySelector('main'));
  const bridge = spawn(process.env.IDENTITY_TEST_PYTHON, ['-u', '-m', 'services.identity.tests.student_ui_fixture'],
    { cwd:path.resolve(__dirname, '../..'), stdio:['pipe','pipe','inherit'] });
  const waiting = [];
  createInterface({input:bridge.stdout}).on('line', line => {
    const reply = JSON.parse(line);
    const {resolve,reject} = waiting.shift();
    if (reply.status >= 400) reject(Object.assign(new Error(reply.data.detail), {status:reply.status})); else resolve(reply.data);
  });
  bridge.on('exit', () => waiting.splice(0).forEach(({reject}) => reject(new Error('Fixture stopped'))));
  t.after(async () => {
    await React.act(async () => root.unmount());
    bridge.stdin.end();
    dom.window.close();
  });
  const requests = [];
  function request(url, options = {}) {
    requests.push([options.method || 'GET', url]);
    return new Promise((resolve,reject) => {
      waiting.push({ resolve,reject });
      bridge.stdin.write(JSON.stringify({ url, method: options.method || 'GET',
        body: options.body ? JSON.parse(options.body) : null }) + '\n');
    });
  }
  const render = permissions => React.act(async () => root.render(React.createElement(Accounts, { permissions, schoolId:'UI-test', request })));
  const submit = form => React.act(async () => form.dispatchEvent(new dom.window.Event('submit', { bubbles:true, cancelable:true })));
  const click = text => React.act(async () => {
    const button = [...document.querySelectorAll('button')].find(el => el.textContent === text);
    assert.ok(button && !button.disabled, text); button.click();
  });
  async function until(condition) {
    const end = Date.now() + 15000;
    while (!condition()) {
      if (Date.now() > end) assert.fail('Timed out: ' + document.body.textContent);
      await React.act(async () => new Promise(r => setTimeout(r, 15)));
    }
  }
  await render(full);
  await until(() => document.body.textContent.includes('没有匹配的学生'));
  await click('添加学生');
  const form = document.querySelector('form[aria-label="批量开通学生账号"]');
  for (const [i,name] of ['测试甲','测试乙'].entries()) {
    form.elements['name-'+i].value = name;
    form.elements['number-'+i].value = 'UI101'+i;
    form.elements['password-'+i].value = 'TestInitial4321!';
  }
  await submit(form);
  await until(() => document.querySelectorAll('tbody tr').length === 2);
  assert.deepEqual(requests.map(([method]) => method), ['GET','POST','GET']);
  assert.equal(form.querySelector('input[type=password]').value, '');
  const studentId = document.querySelector('tbody tr small').textContent;
  await click('选择 测试甲');
  document.querySelector('select[name=status]').value = 'disabled';
  await submit(document.querySelector('form[data-action=status]'));
  await until(() => document.querySelector('tbody tr')?.textContent.includes('停用'));
  const reset = document.querySelector('form[data-action=reset]');
  reset.elements.temporary_password.value = 'ChangedSecret827!';
  await submit(reset);
  await until(() => document.querySelector('form[data-action=reset] input')?.value === '' &&
    document.body.textContent.includes('已重置 测试甲'));
  assert.deepEqual(requests.map(([method]) => method), ['GET','POST','GET','PATCH','GET','POST','GET']);
  const search = document.querySelector('input[name=q]');
  search.value = '1011'; await submit(search.form);
  await until(() => document.querySelectorAll('tbody tr').length === 1);
  assert.match(document.querySelector('tbody').textContent,/测试乙/);
  const before = requests.length;
  await render({canImportStudentAccounts:true});
  assert.equal(document.querySelector('table'),null);
  assert.equal(requests.length,before);
  await render({canResetStudentPasswords:true});
  assert.equal(document.querySelector('table'),null);
  const manual = document.querySelector('input');
  await React.act(async () => {
    Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype,'value').set.call(manual,studentId);
    manual.dispatchEvent(new dom.window.Event('input',{bubbles:true}));
  });
  const manualReset = document.querySelector('form[data-action=reset]');
  assert.ok(manualReset);
  assert.equal(document.querySelector('form[data-action=status]'),null);
  manualReset.elements.temporary_password.value = 'UpdatedOnce739!';
  await submit(manualReset);
  await until(() => document.body.textContent.includes('已重置 ' + studentId));
  assert.deepEqual(requests.slice(before).map(([method]) => method), ['POST']);
  await render({canManageStudentGrants:true});
  const known = document.querySelector('input');
  await React.act(async () => {
    Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype,'value').set.call(known,studentId);
    known.dispatchEvent(new dom.window.Event('input',{bubbles:true}));
  });
  await click('读取学生授权');
  await until(() => document.body.textContent.includes('当前沿用默认学生权限'));
  assert.equal(document.querySelector('table'),null);
  await click('清空选择');
  await submit(document.querySelector('form[data-action=grants]'));
  await until(() => document.body.textContent.includes('已配置个人授权 · 版本 1'));
  await click('重新读取授权');
  await until(() => document.body.textContent.includes('已选择 0 项'));
  assert.equal(document.querySelectorAll('[data-action=grants] input:checked').length,0);
  assert.deepEqual(requests.slice(before).map(([method]) => method), ['POST','GET','PUT','GET']);
});
