// 使用 node --test 运行；可通过 NODE_PATH 加载 jsdom。测试在内存中编译 JSX，以本地数据验证读取行为。
const assert = require('node:assert/strict');
const test = require('node:test');
const { JSDOM } = require('jsdom');
const { buildSync } = require('esbuild');
const { Module } = require('node:module');
const path = require('node:path');
const React = require('react');
const dom = new JSDOM('<div id="root"></div>');
global.window = dom.window;
global.document = dom.window.document;
global.FormData = dom.window.FormData;
global.IS_REACT_ACT_ENVIRONMENT = true;
const { createRoot } = require('react-dom/client');
const bundle = buildSync({
  entryPoints: [path.join(__dirname, '../src/NativeTeachingDashboard.jsx')],
  bundle: true, write: false, format: 'cjs', platform: 'node', external: ['react'],
  loader: { '.css': 'empty' },
});
const componentModule = new Module(__filename, module);
componentModule.paths = module.paths;
componentModule._compile(bundle.outputFiles[0].text, __filename);
const Dashboard = componentModule.exports.default;

const progress = { task_count: 2, enrolled_students: 9, assigned_students: 4, completed_students: 3,
  assigned_task_students: 7, completed_task_students: 5 };
const task = { task_id: 't', title: '软件工程训练', job_role: '开发', deadline: '2099-01-01T12:00:00Z', max_attempts: 3,
  class_ids: ['c'], questions: [{ question_id: 'q', prompt: '请说明回滚方式。' }] };
const training = { items: [task, { ...task, task_id: 't2', title: '复练' }], classes: [{ class_id: 'c', name: '软件班', ...progress }], summary: progress };
const coverage = { attempts: 4, completed_questions: 4, valid_attempts: 2, insufficient_attempts: 1, unknown_coverage_attempts: 1 };
const analytics = { ...coverage, by_class: [{ key: 'c', ...coverage }], class_weaknesses: [
  { class_id: 'c', dimension: '沟通', scored_questions: 4, weak_questions: 1, affected_students: 1, average_score: 78 }] };
const weak = { task_id: 't', attempt_id: 'a', question_id: 'q', student_id: 's', interview_id: 'i',
  question_text: '请说明回滚方式。', original_answer: '原始答复', dimension: '沟通', score: 52, version: 2 };
const normal = (url) => {
  if (url.endsWith('/tasks?view=workbench')) return training;
  if (url.endsWith('/summary')) return analytics;
  if (url.includes('/weaknesses?')) return { items: [weak] };
  if (url.endsWith('/interviews/i/report-reference')) return { report_id: 'r' };
  if (url.endsWith('/reports/r/history')) return { report: { id: 'r', version: 1 }, versions: [{ version: 1, snapshot: { summary: '仅此报告' } }], reviews: [] };
  throw Error('Unexpected URL ' + url);
};
async function fixture(t, handler, props = {}) {
  const root = createRoot(document.getElementById('root'));
  const host = document.getElementById('root');
  const reads = [];
  const request = async (url, options) => {
    assert.ok(options.signal);
    reads.push(url);
    return handler(url);
  };
  const render = (extra = {}) => React.act(async () => root.render(React.createElement(Dashboard, {
    canReadTraining: true, canReadAnalytics: true, request, ...props, ...extra,
  })));
  const click = async (label) => {
    const button = [...host.querySelectorAll('button')].find((b) => b.textContent === label);
    assert.ok(button, label);
    await React.act(async () => button.click());
  };
  t.after(() => React.act(async () => root.unmount()));
  await render();
  return { host, reads, render, click };
}
test.after(() => dom.window.close());

test('uses distinct server denominators, loads original evidence and checks report reference on demand', async (t) => {
  const { host, reads, click } = await fixture(t, normal, { permissions: { canReadTrainingReports: true } });
  assert.deepEqual(reads, ['/api/admin/training/tasks?view=workbench', '/api/admin/analytics/v1/teaching/summary']);
  assert.match(host.textContent, /应参加7人次已完成5人次/);
  assert.match(host.textContent, /有效样本2次覆盖不足1次/);
  assert.match(host.textContent, /其中 1 次缺少历史题目总数/);
  await click('定位原题');
  const url = new URL(reads.at(-1), 'http://fixture.local');
  assert.equal(url.searchParams.get('class_id'), 'c');
  assert.equal(url.searchParams.get('dimension'), '沟通');
  assert.match(host.textContent, /原始答复/);
  assert.match(host.textContent, /定位任务 · 软件工程训练/);
  await click('查看关联报告');
  assert.deepEqual(reads.slice(-2), ['/api/admin/interviews/i/report-reference', '/api/admin/reports/r/history']);
  assert.match(host.textContent, /仅此报告/);
});

test('denied scopes issue no HTTP calls and a report without a grant cannot be opened', async (t) => {
  const { host, reads, render, click } = await fixture(t, normal, { canReadTraining: false, canReadAnalytics: false });
  assert.deepEqual(reads, []);
  assert.match(host.textContent, /无权查看训练名单与进度/);
  await render({ canReadAnalytics: true });
  await click('定位原题');
  assert.match(host.textContent, /无权查看关联报告/);
  assert.ok(!reads.some((url) => url.includes('report-reference') || url.includes('/training/')));
  await render({ canReadAnalytics: false });
  assert.doesNotMatch(host.textContent, /原始答复/);
});

test('a revoked grant, service error or old API never becomes a zero count', async (t) => {
  let status = 503;
  const { host, render } = await fixture(t, () => { throw Object.assign(new Error(), { status }); });
  assert.match(host.textContent, /评分覆盖暂不可用/);
  assert.doesNotMatch(host.textContent, /有效样本0次/);
  status = 403;
  await render({ revision: 2 });
  assert.match(host.textContent, /无权查看评分覆盖/);
  await render({ revision: 3, request: async () => ({ items: [] }) });
  assert.match(host.textContent, /训练名单与进度暂不可用/);
});

test('successful empty projections explicitly distinguish no tasks, no scores and no findings', async (t) => {
  const zeros = (obj) => Object.fromEntries(Object.keys(obj).map((k) => [k, 0]));
  const { host } = await fixture(t, (url) => url.includes('/training/')
    ? { summary: zeros(progress), items: [], classes: [] }
    : { ...zeros(coverage), by_class: [], class_weaknesses: [] });
  assert.match(host.textContent, /尚未布置任务/);
  assert.match(host.textContent, /尚无已投递的评分样本/);
  assert.match(host.textContent, /尚无法判断薄弱项/);
});

test('changes of class suppress old evidence while the previous detail read is in flight', async (t) => {
  let finish;
  const secondClass = { class_id: 'second', name: '新班', ...progress, task_count: 0, assigned_task_students: 0, completed_task_students: 0 };
  const { host, click } = await fixture(t, (url) => {
    if (url.includes('/weaknesses?')) return new Promise((resolve) => { finish = resolve; });
    if (url.includes('/training/')) return { ...training, classes: [...training.classes, secondClass] };
    return normal(url);
  });
  await click('定位原题');
  assert.match(host.textContent, /正在读取薄弱项原题/);
  await React.act(async () => {
    const select = host.querySelector('select');
    select.value = 'second';
    select.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  });
  await React.act(async () => finish({ items: [weak] }));
  assert.doesNotMatch(host.textContent, /原始答复/);
  assert.match(host.textContent, /尚无已投递的评分样本/);
});

const account = { school_id: 'school', scope: 'school', accounts: 14, normal_accounts: 13, disabled_accounts: 1,
  must_change_password: 4, assigned_accounts: 12, unassigned_accounts: 2, unassigned_normal_accounts: 1 };
const pending = { pending_accounts: 11, items: [{ name: '待开户学生', student_no: 'stu003' }] };
const interview = { id: 'i1', name: '学生甲', student_id: 's1', kind: 'training', college_id: 'd1', college_name: '工程学院',
  class_id: 'c1', class_name: '软件一班', status: 'running', target_role: '开发', updated_at: '2026-01-12 08:03:00' };
const report = { ...interview, id: 'r1', interview_id: 'i1', created_at: '2026-01-11 07:00:00',
  generation_status: 'succeeded', review_status: 'pending', total_score: 80 };
const interviewStats = { total: 17, completed: 9, running: 6, completed_students: 4, visible_students: 8,
  by_status: { completed: 9, running: 6, draft: 2 }, by_kind: { practice: 4, training: 13 }, recent: [interview], running_items: [interview] };
const reportStats = { total: 13, eligible: 10, average_score: 77.5, by_generation: { succeeded: 10, degraded: 3 },
  by_review: { approved: 3, pending: 8, rejected: 2 }, quality: { pending_review: 8, partial_coverage: 2, zero_evidence: 1, unknown_coverage: 0 },
  score_bands: { gte90: 1, from80: 3, from70: 5, below70: 1 }, recent: [report], pending_items: [report] };

function ops(url) {
  const { pathname } = new URL(url, 'https://fixture.local');
  if (pathname.endsWith('/pending-summary')) return pending;
  if (pathname.endsWith('/student-accounts/summary')) return account;
  if (pathname.endsWith('/interview/v1/workbench')) return interviewStats;
  if (pathname.endsWith('/assessment/v1/workbench')) return reportStats;
  if (pathname.endsWith('/assessment/v1/records/r1')) return { ...report, summary: '报告一的摘要' };
  return normal(url);
}

const opsProps = { canReadTraining: false, canReadAnalytics: false,
  grants: ['student.read', 'interview.records.read', 'report.read'], permissions: { canUseRegistrationBook: true } };

test('运营首页分别展示全量计数、登记队列、面试来源与质检分布，近期行可读取准确报告', async (t) => {
  const pages = [];
  const { host, reads, click } = await fixture(t, ops, { ...opsProps, onNavigate: (...args) => pages.push(args) });
  assert.equal(reads.length, 4);
  assert.ok(reads.includes('/api/admin/identity/v1/student-accounts/pending-summary'));
  assert.ok(reads.includes('/api/admin/interview/v1/workbench?limit=5'));
  assert.match(host.textContent, /待开通11人/);
  assert.match(host.textContent, /学生账号14个已启用未归班1人待改密4人/);
  assert.match(host.textContent, /面试总数17场进行中6场/);
  assert.match(host.textContent, /报告总数13份待质检8份/);
  assert.match(host.textContent, /平均 77.5 分/);
  await click('近期报告');
  const panel = [...host.querySelectorAll('section.nt-panel')].find((p) => p.querySelector('h2').textContent === '报告与质检');
  await React.act(async () => [...panel.querySelectorAll('button')].find((b) => b.textContent === '查看详情').click());
  assert.equal(reads.at(-1), '/api/admin/assessment/v1/records/r1');
  assert.match(panel.textContent, /报告一的摘要/);
  await click('查看全部报告记录');
  await click('查看学生账号');
  await click('查看登记开通名单');
  assert.deepEqual(pages, [['schoolReports', ''], ['nativeSchool', 'students'], ['nativeSchool', 'registrations']]);
});

test('运营过滤按各服务支持的口径发送，登记待办独立于学院和日期', async (t) => {
  const { host, reads } = await fixture(t, ops, opsProps);
  const form = host.querySelector('form[aria-label="运营统计范围"]');
  form.elements.college.value = 'd1';
  form.elements.class.value = 'c1';
  form.elements.period.value = '7';
  form.elements.kind.value = 'practice';
  await React.act(async () => form.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true })));
  const urls = reads.slice(4).map((s) => new URL(s, 'https://fixture.local'));
  assert.equal(urls.length, 3);
  for (const u of urls) {
    assert.equal(u.searchParams.get('college_id'), 'd1');
    assert.equal(u.searchParams.get('class_id'), 'c1');
    if (u.pathname.includes('/workbench')) {
      assert.match(u.searchParams.get('start_date'), /^\d{4}-\d{2}-\d{2}$/);
      assert.match(u.searchParams.get('end_date'), /^\d{4}-\d{2}-\d{2}$/);
      assert.equal(u.searchParams.get('kind'), 'practice');
      assert.equal(u.searchParams.get('limit'), '5');
    } else assert.deepEqual([...u.searchParams.keys()], ['college_id', 'class_id']);
  }
  assert.equal(reads.filter((s) => s.includes('pending-summary')).length, 1);
});

test('登记读权独立于学生导入，权限撤销、服务故障与真实空队列有不同呈现', async (t) => {
  let unavailable = true;
  const { host, reads, render } = await fixture(t, (url) => {
    if (url.includes('/assessment/')) throw Object.assign(Error('没有权限'), { status: 403 });
    if (url.includes('/interview/') && unavailable) throw Object.assign(Error('不可用'), { status: 503 });
    if (url.includes('pending-summary')) return { pending_accounts: 0, items: [] };
    return ops(url);
  }, { ...opsProps, permissions: { canImportStudentAccounts: true } });
  assert.ok(!reads.some((s) => s.includes('pending-summary')));
  assert.match(host.textContent, /无权查看登记开通待办/);
  assert.match(host.textContent, /无权查看学校报告统计/);
  assert.match(host.textContent, /学校面试统计暂不可用/);
  assert.match(host.textContent, /学生账号14个/);
  unavailable = false;
  await render({ revision: 2, permissions: { canUseRegistrationBook: true } });
  assert.match(host.textContent, /目前没有待开通的学生登记/);
  assert.match(host.textContent, /面试总数17场/);
  await render({ revision: 3, permissions: {}, grants: [] });
  assert.doesNotMatch(host.textContent, /面试总数17场|学生账号14个|待开通0人/);
  assert.match(host.textContent, /无权查看学校面试统计/);
});

test('打开报告复核时保留意见草稿，普通自动刷新和撤回报告读权分别处理', async (t) => {
  const props = { canReadTraining: false, canReadAnalytics: false, permissions: {
    canReadSchoolReports: true, canReadTrainingReports: true, canReviewReports: true,
  } };
  const { host, click, render, reads } = await fixture(t, (url) => {
    if (url.endsWith('/reports/r1/history')) return { report: { id: 'r1', version: 1 },
      versions: [{ version: 1, snapshot: { summary: '审核期间的报告' } }], reviews: [] };
    return ops(url);
  }, props);
  await click('查看详情');
  await click('核验负责关系并查看版本');
  const textarea = host.querySelector('textarea');
  assert.ok(textarea);
  const count = reads.filter((url) => url.includes('workbench')).length;
  await render({ revision: 2 });
  assert.equal(host.querySelector('textarea'), textarea);
  assert.equal(reads.filter((url) => url.includes('workbench')).length, count);
  await render({ revision: 3, permissions: {} });
  assert.equal(host.querySelector('textarea'), null);
  assert.doesNotMatch(host.textContent, /审核期间的报告/);
});

test('从真实管理端工作台打开待办、近期及成绩分段，首个列表请求与表单一致', async (t) => {
  const page = new JSDOM('<div id="root"></div>', { runScripts: 'outside-only', url: 'https://school.test/admin/' });
  t.after(() => page.window.close());
  const { window } = page, doc = window.document;
  const calls = [];
  const unexpected = [];
  const admin = { id: 'staff', school_id: 'school', name: '教务员', actorType: 'admin', role: 'admin', permissions: opsProps.grants };
  window.fetch = async (path) => {
    const u = new URL(path, 'https://school.test');
    calls.push(u);
    let data;
    if (u.pathname.endsWith('/auth/me')) data = { admin };
    else if (u.pathname.endsWith('/snapshot')) data = { identityMode: 'native', admin,
      permissions: { canReadStudentAccounts: true, canReadSchoolReports: true, canReadSchoolInterviews: true } };
    else if (u.pathname.endsWith('/records')) data = { items: [], next_cursor: u.searchParams.has('cursor') ? null : 'next2' };
    else if (u.pathname.endsWith('/health')) data = {};
    else {
      try { data = ops(path); }
      catch { unexpected.push(path); data = {}; }
    }
    return { ok: true, status: 200, headers: new Headers(), json: async () => data };
  };
  const script = buildSync({ entryPoints: [path.join(__dirname, '../src/main.jsx')], bundle: true, write: false,
    format: 'iife', loader: { '.css': 'empty', '.png': 'dataurl' },
    define: { 'import.meta.env': '{}', 'process.env.NODE_ENV': '"production"' } }).outputFiles[0].text;
  window.eval(script);
  const button = name => [...doc.querySelectorAll('button')].find(b => (b.getAttribute('aria-label') || b.textContent.trim()) === name);
  async function until(read) {
    for (let i = 0; i < 250; i++) {
      const found = read();
      if (found) return found;
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    throw new Error('页面未出现预期状态：' + doc.body.textContent.slice(-300));
  }
  const click = async name => (await until(() => button(name))).click();
  for (const [name, owner, extra] of [
    ['查看全部待质检报告', 'assessment', { state: 'pending' }],
    ['查看全部进行中面试', 'interview', { state: 'running' }],
    ['查看80 至 89 分的报告', 'assessment', { score_band: 'from80' }],
    ['查看全部报告记录', 'assessment', {}],
  ]) {
    const firstCall = calls.length;
    const filters = await until(() => doc.querySelector('form[aria-label="运营统计范围"]'));
    filters.elements.college.value = 'd1';
    filters.elements.class.value = 'c1';
    filters.elements.period.value = '7';
    filters.elements.kind.value = 'training';
    filters.dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
    const source = await until(() => calls.slice(firstCall).find(u => u.pathname.endsWith('/' + owner + '/v1/workbench') && u.searchParams.get('college_id') === 'd1'));
    if (name === '查看全部报告记录') await click('近期报告');
    await click(name);
    const route = '/api/admin/' + owner + '/v1/records';
    const list = await until(() => calls.slice(firstCall).find(u => u.pathname === route));
    const expected = { ...Object.fromEntries(source.searchParams), ...extra };
    delete expected.limit;
    assert.deepEqual(Object.fromEntries(list.searchParams), expected);
    const form = await until(() => doc.querySelector('form input[name="q"]')?.form);
    for (const [key, value] of Object.entries(expected)) assert.equal(form.elements[key].value, value, key);
    assert.equal(form.elements.state.value, extra.state || '');
    if (owner === 'interview') assert.equal(form.elements.score_band, undefined);
    if (name === '查看全部待质检报告') {
      const next = await until(() => { const b = button('下一页'); return b && !b.disabled && b; });
      next.click();
      await until(() => calls.some(u => u.pathname === route && u.searchParams.get('cursor') === 'next2'));
      const priorSearch = calls.length;
      form.elements.state.value = 'approved';
      form.dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
      const changed = await until(() => calls.slice(priorSearch).find(u => u.pathname === route));
      assert.deepEqual(Object.fromEntries(changed.searchParams), { ...expected, state: 'approved' });
    }
    await click('工作台');
  }
  assert.deepEqual(unexpected, []);
});
