const { test } = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');
const path = require('node:path');
const { buildSync } = require('esbuild');
const React = require('react');

const filename = path.join(__dirname, 'SchoolRecordBrowser.jsx');
const code = buildSync({ entryPoints: [filename], bundle: true, write: false, platform: 'node',
  format: 'cjs', external: ['react'] }).outputFiles[0].text;
const component = new Module(filename, module);
component.paths = module.paths;
component._compile(code, filename);
const Records = component.exports.default;
let jsdom;
try { jsdom = require.resolve('jsdom'); } catch {}

test('a reader can search, page through empty cohorts, open a read-only report and return to their filter',
  { skip: !jsdom && 'Requires the jsdom UI test runtime' }, async () => {
    const { JSDOM } = require(jsdom);
    const dom = new JSDOM('<main></main>', { url: 'https://school.test' });
    Object.assign(globalThis, { window: dom.window, document: dom.window.document, FormData: dom.window.FormData,
      IS_REACT_ACT_ENVIRONMENT: true });
    const root = require('react-dom/client').createRoot(document.querySelector('main'));
    const urls = [];
    let access = true;
    const row = { id: 'R', student_id: 'S', name: '王同学', student_no: '1000', target_role: '工程师',
      class_name: '班级一', kind: 'practice', total_score: 0, created_at: '2021-01-02T08:00:00Z',
      summary: '历史报告正文', suggestions: '["写明结果"]', generation_status: 'succeeded', review_status: 'pending' };
    const request = async (path, options) => {
      const url = new URL(path, 'https://school.test');
      urls.push(url);
      assert.equal(options.method || 'GET', 'GET');
      if (!access) throw Object.assign(new Error('Forbidden'), { status: 403 });
      if (url.pathname.endsWith('/R')) return row;
      return url.searchParams.get('cursor') === 'second'
        ? { items: [row], next_cursor: null } : { items: [], next_cursor: 'second' };
    };
    const render = revision => React.act(async () => root.render(React.createElement(Records,
      { owner: 'assessment', request, revision })));
    const click = text => React.act(async () => {
      const button = [...document.querySelectorAll('button')].find(item => item.textContent === text);
      assert.ok(button && !button.disabled, text);
      button.click();
    });
    try {
      await render(1);
      const form = document.querySelector('form');
      form.elements.q.value = '王';
      await React.act(async () => form.dispatchEvent(new dom.window.Event('submit', { bubbles:true, cancelable:true })));
      assert.equal(urls.at(-1).searchParams.get('q'), '王');
      await click('下一页');
      assert.equal(urls.at(-1).searchParams.get('cursor'), 'second');
      await click('查看详情');
      assert.match(document.body.textContent, /历史报告正文/);
      assert.match(document.body.textContent, /得分 0/);
      assert.doesNotMatch(document.body.textContent, /改分|调整成绩|审核通过/);
      await click('返回记录列表');
      assert.equal(document.querySelector('form').elements.q.value, '王');
      access = false;
      await render(2);
      assert.match(document.body.textContent, /无权/);
      assert.doesNotMatch(document.body.textContent, /王同学|历史报告正文/);
    } finally {
      await React.act(async () => root.unmount());
      dom.window.close();
    }
  });
