const assert = require('node:assert/strict');
const test = require('node:test');
const React = require('react');
const { JSDOM } = require('jsdom');
const { Module } = require('node:module');
const path = require('node:path');
const { buildSync } = require('esbuild');

const file = path.join(__dirname, '../src/NativePermissionRequests.jsx');
const output = buildSync({ entryPoints: [file], bundle: true, format: 'cjs', platform: 'node', external: ['react'], write: false });
const compiled = new Module(file, module);
compiled.paths = module.paths;
compiled._compile(output.outputFiles[0].text, file);

test('staff can request only own scope; reviewer decisions carry a note and never include caller identity', async () => {
  const dom = new JSDOM('<main></main>', { url: 'https://school.test' });
  Object.assign(globalThis, { window: dom.window, document: dom.window.document, FormData: dom.window.FormData, IS_REACT_ACT_ENVIRONMENT: true });
  const root = require('react-dom/client').createRoot(document.querySelector('main'));
  const rows = [];
  const writes = [];
  const request = async (url, options) => {
    if (options.method === 'POST') {
      const body = JSON.parse(options.body);
      writes.push({ url, body });
      if (url.endsWith('/decision')) Object.assign(rows[0], { status:body.status, decision_note:body.note });
      else rows.push({ ...body, id:'r1', applicant:'reader', school_id:'A', status:'pending' });
      return { id:'r1' };
    }
    return { school_id:'A', items:rows, actions:['report.read'], school_wide:false, has_more:false };
  };
  const render = props => React.act(async () => root.render(React.createElement(compiled.exports.default, { request, schoolId:'A', ...props })));
  const account = (id, role, manage) => ({ admin:{ school_id:'A', id, actorType:role },
    permissions:{ canRequestStaffAccess:true, canManageStaff:manage, canManageNativeOrganization:manage } });
  const setMode = async () => React.act(async () => {
    const select = document.querySelector('select');
    select.value = 'queue';
    select.dispatchEvent(new dom.window.Event('change', {bubbles:true}));
  });
  try {
    await render(account('reader','teacher',false));
    assert.equal(document.querySelector('select'), null);
    document.querySelector('[name=action]').checked = true;
    document.querySelector('[name=classes]').value = 'one，two';
    document.querySelector('[name=reason]').value = '指定训练';
    await React.act(async () => document.querySelector('button[type=submit]').click());
    assert.ok(writes[0].body.request_key);
    assert.deepEqual(writes[0].body, { actions:['report.read'], classes:['one','two'], reason:'指定训练', request_key:writes[0].body.request_key });
    await render(account('reader','admin',true));
    await setMode();
    assert.equal(document.querySelector('button[value=approved]'), null);
    await render(account('manager','admin',true));
    document.querySelector('[name=note]').value = '已核验';
    await React.act(async () => document.querySelector('button[value=approved]').click());
    assert.deepEqual(writes[1], { url:'/api/admin/identity/v1/permission-requests/r1/decision', body:{ status:'approved', note:'已核验' } });
    assert.match(document.body.textContent, /已通过/);
  } finally { await React.act(async () => root.unmount()); dom.window.close(); }
});
