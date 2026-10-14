/* Local UI regression test. All API requests are intercepted with synthetic data. */
const { createRequire } = require('node:module');
const { createServer } = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const policyFixture = require('./interviewer-policy-fixture.cjs');
const runtimeRequire = process.env.PLAYWRIGHT_MODULE_ROOT
  ? createRequire(path.join(process.env.PLAYWRIGHT_MODULE_ROOT, 'package.json')) : require;
const { chromium } = runtimeRequire('playwright');
const root = path.resolve(__dirname, '..');
const dist = path.join(root, 'admin', 'dist');
const output = path.join(root, 'outputs', 'admin-workbench-check');
fs.mkdirSync(output, { recursive: true });

const admin = { id: 'test-admin', name: '界面测试管理员', email: 'admin@example.test', role: 'super_admin' };
const permissions = Object.fromEntries(['canViewCandidates', 'canViewInterviews', 'canViewReports', 'canViewAgents', 'canManageStudents', 'canManageOrganization', 'canManageSettings', 'canViewCatalog', 'canViewProgramJobs', 'canViewJobPostings'].map(key => [key, true]));
const interviews = [
  { id: 'training-complete-001', candidate: '测试学生甲', role: '前端工程师', type: '技术面试', status: '已完成', agents: 2, qaCount: 2, updatedAt: '2026-10-12 10:30' },
  { id: 'training-running-002', candidate: '测试学生乙', role: '产品经理', type: '综合面试', status: '进行中', agents: 1, qaCount: 0, updatedAt: '2026-10-12 11:30' },
];
const campus = {
  colleges: [{ id: 'c1', name: '计算机学院' }, { id: 'c2', name: '管理学院' }],
  programs: [{ id: 'p1', college_id: 'c1', name: '软件工程' }, { id: 'p2', college_id: 'c2', name: '工商管理' }],
  classes: [{ id: 'cl1', college_id: 'c1', program_id: 'p1', name: '软件一班', advisor: '测试辅导员' }, { id: 'cl2', college_id: 'c2', program_id: 'p2', name: '管理一班', advisor: '测试老师' }],
  students: [
    { id: 's1', name: '测试学生甲', studentNo: '20260001', email: 'a@example.test', targetRole: '前端工程师', collegeId: 'c1', programId: 'p1', classId: 'cl1', college: '计算机学院', className: '软件一班', readiness: 82, interviews: 3, growthStatus: '表现稳定' },
    { id: 's2', name: '测试学生乙', studentNo: '20260002', email: 'b@example.test', targetRole: '产品经理', collegeId: 'c2', programId: 'p2', classId: 'cl2', college: '管理学院', className: '管理一班', readiness: 0, interviews: 0, growthStatus: '尚未训练' },
  ], pendingStudents: [], summary: { students: 2 },
};
const registrations = [{ id: 'reg1', name: '测试学生甲', studentNo: '20260001', college: '计算机学院', className: '软件一班', gender: '男', counselor: '测试辅导员', activated: true, missing: [], assignmentStatus: 'assigned' }];
let reviewStatus = 'pending';
let failReview = false;
let failDetail = false;
let registrationPayload;
const settings = { reportOpenaiModel: 'test-report-model', reportQwenModel: 'test-qwen-model', reportProviderOrder: 'openai,qwen', reportTimeout: 60, reportRetries: 1, evaluationProviderOrder: 'qwen,openai', evaluationTimeout: 12, evaluationRetries: 0, openaiRealtimeModel: 'test-realtime', openaiVoice: 'marin', qwenOmniModel: 'test-omni', qwenOmniVoice: 'Tina', qwenTtsModel: 'test-tts', qwenTtsVoice: 'voice', reportOpenaiApiKeyConfigured: true, reportOpenaiApiKeyMasked: 'sk-t...test' };
const modelWrites = [];
let failModelSave = false;
const reviewWrites = [];
const errors = [];
const unhandledRequests = [];
let extraReports = [];
let failSnapshot = false;
let syncConfigured = false;
let syncedPostings = [];
let runningText = '';

const server = createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname.replace(/^\/admin\/?/, '');
  const filename = pathname.startsWith('assets/') ? path.join(dist, pathname) : path.join(dist, 'index.html');
  const type = { '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.html': 'text/html' }[path.extname(filename)] || 'application/octet-stream';
  res.writeHead(200, { 'Content-Type': type });
  fs.createReadStream(filename).pipe(res);
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true, ...(process.env.TEST_CHROME_PATH ? { executablePath: process.env.TEST_CHROME_PATH } : {}) });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ['clipboard-read', 'clipboard-write'] });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/admin/**', async route => {
      const pathname = new URL(route.request().url()).pathname;
      const method = route.request().method();
      let body = {};
      if (pathname.endsWith('/auth/me')) body = { admin };
      else if (pathname.endsWith('/interviewer-policy')) body = policyFixture;
      else if (pathname.endsWith('/snapshot')) {
        if (failSnapshot) return route.fulfill({ status: 503, json: { error: '测试连接中断' } });
        body = { admin, permissions, settings, interviews, reports: [{ id: 'report1', candidate: '测试学生甲', score: 82, reviewStatus: reviewStatus === 'pending' ? '待复核' : '已复核' }, ...extraReports] };
      }
      else if (pathname.endsWith('/job-postings/sync')) {
        syncedPostings = [{ id: 'synced-job', title: '同步工程师', company: '测试公司', status: 'active', source: 'sync' }];
        body = { created: 1, updated: 0, skipped: 1, errors: ['第 2 条：缺少岗位名称 title。'] };
      }
      else if (pathname.endsWith('/job-postings')) body = { postings: syncedPostings, jobRoles: [], syncConfigured };
      else if (pathname.endsWith('/job-matches')) body = { matches: [], postings: [] };
      else if (pathname.endsWith('/jd-submissions')) body = { submissions: [] };
      else if (pathname.endsWith('/settings') && method === 'PATCH') {
        if (failModelSave) { failModelSave = false; return route.fulfill({ status: 500, json: { error: '测试模型保存失败' } }); }
        const payload = route.request().postDataJSON(); modelWrites.push(payload);
        Object.assign(settings, Object.fromEntries(Object.entries(payload).filter(([key]) => !key.endsWith('ApiKey'))));
        body = { settings, message: '配置已保存' };
      }
      else if (pathname.endsWith('/settings/report-providers/test')) body = { providers: [{ provider: 'openai', model: settings.reportOpenaiModel, status: 'ok', latency_ms: 12 }, { provider: 'qwen', model: settings.reportQwenModel, status: 'error', error: '测试供应商不可用' }] };
      else if (pathname.endsWith('/health')) body = { status: 'ok' };
      else if (pathname.includes('/interviews/')) {
        if (failDetail) { failDetail = false; return route.fulfill({ status: 503, json: { error: '测试详情读取失败' } }); }
        const row = interviews.find(item => pathname.endsWith(item.id));
        body = { interview: { ...row, target_role: row.role, candidate_email: 'a@example.test', interview_type: row.type, company_context: '互联网企业', started_at: '2026-10-12 10:00', completed_at: row.status === '已完成' ? '2026-10-12 10:30' : null }, agents: [{ id: 'agent1', agent_name: '技术面试官', agent_type: 'technical', status: 'completed', agent_role: '考察工程能力' }], messages: row.status === '已完成' ? [{ id: 'q1', sender_type: 'agent', message_type: 'question', agent_name: '技术面试官', content: '请介绍项目中的性能优化。', created_at: '10:01' }, { id: 'a1', sender_type: 'candidate', message_type: 'answer', content: '回答占位', transcript_text: '这是完整的回答。'.repeat(60) + '回答末尾核验标记', created_at: '10:02' }] : [], reviewReport: row.status === '已完成' ? { id: 'report1', review_status: reviewStatus } : null };
        if (row.status === '进行中' && runningText) body.messages = [{ id: 'live-message', sender_type: 'candidate', content: runningText, message_type: 'answer' }];
      } else if (pathname.endsWith('/reports/report1/review')) {
        if (failReview) { failReview = false; return route.fulfill({ status: 500, json: { error: '测试保存失败，请重试' } }); }
        reviewStatus = route.request().postDataJSON().status;
        reviewWrites.push(reviewStatus);
        body = { report: { id: 'report1', review_status: reviewStatus } };
      } else if (pathname.endsWith('/campus/overview') || pathname.endsWith('/organization/structure')) body = campus;
      else if (pathname.endsWith('/student-registrations')) {
        if (method === 'POST') {
          registrationPayload = route.request().postDataJSON();
          registrations.push({ id: 'reg2', ...registrationPayload, activated: false, missing: [] });
          body = { id: 'reg2', created: true };
        } else body = { registrations };
      } else unhandledRequests.push(`${method} ${pathname}`);
      return route.fulfill({ status: 200, json: body });
    });
    const url = `http://127.0.0.1:${server.address().port}/admin/`;
    await page.goto(`${url}#/interviews`);
    await page.getByRole('heading', { name: '训练记录', exact: true, level: 1 }).waitFor();
    assert.equal(await page.getByText('服务器已连接', { exact: true }).count(), 1);
    await page.getByLabel('全部状态', { exact: true }).selectOption('已完成');
    assert.equal(await page.locator('tr.data-row').count(), 1);
    await page.getByRole('button', { name: '复制 training-complete-001', exact: true }).click();
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), 'training-complete-001');
    assert.equal(await page.locator('.expanded-record').count(), 0);
    await page.locator('tr.data-row').click();
    await page.getByRole('heading', { name: '基本信息', exact: true }).waitFor();
    assert.equal(await page.locator('.interview-info-grid > div').count(), 8);
    assert.equal(await page.getByText('回答末尾核验标记', { exact: false }).count(), 0);
    await page.screenshot({ path: path.join(output, 'training-records.png'), fullPage: true });
    await page.getByRole('button', { name: '复核质检', exact: true }).click();
    assert.ok(page.url().endsWith('/review/training-complete-001'));
    await page.getByText('回答末尾核验标记', { exact: false }).waitFor();
    failReview = true;
    await page.getByRole('button', { name: '通过复核', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: '测试保存失败' }).waitFor();
    await page.getByRole('button', { name: '通过复核', exact: true }).click();
    await page.getByText('已通过复核，结果已保存', { exact: true }).waitFor();
    await page.getByRole('button', { name: '标记未通过', exact: true }).click();
    await page.getByText('已标记未通过，结果已保存', { exact: true }).waitFor();
    assert.deepEqual(reviewWrites, ['approved', 'rejected']);
    await page.screenshot({ path: path.join(output, 'review-detail.png'), fullPage: true });
    await page.getByRole('button', { name: '返回训练记录', exact: true }).click();
    assert.equal(await page.getByLabel('全部状态', { exact: true }).inputValue(), '已完成');
    await page.getByRole('button', { name: '复核质检', exact: true }).click();
    await page.reload();
    await page.getByText('回答末尾核验标记', { exact: false }).waitFor();
    await page.goBack();
    await page.getByRole('heading', { name: '训练记录', exact: true, level: 2 }).waitFor();
    await page.getByLabel('全部状态', { exact: true }).selectOption('进行中');
    failDetail = true;
    await page.locator('tr.data-row').click();
    await page.getByRole('alert').filter({ hasText: '测试详情读取失败' }).waitFor();
    await page.getByRole('button', { name: '重试', exact: true }).click();
    await page.getByRole('button', { name: '复核质检', exact: true }).click();
    assert.equal(await page.getByRole('button', { name: '通过复核', exact: true }).isDisabled(), true);
    const navigation = page.getByRole('navigation', { name: '管理端导航' });
    const academicMenu = navigation.getByRole('button', { name: '教务信息', exact: true });
    await academicMenu.click();
    assert.equal(await academicMenu.getAttribute('aria-expanded'), 'false');
    assert.equal(await navigation.getByRole('button', { name: '学生管理', exact: true }).isVisible(), false);
    await academicMenu.click();
    await navigation.getByRole('button', { name: '学生管理', exact: true }).click();
    await page.getByRole('heading', { name: '学生列表', exact: true }).waitFor();
    assert.equal(await page.locator('.registrations-page').count(), 0, 'Student list must not embed account management');
    await navigation.getByRole('button', { name: '学生账号', exact: true }).click();
    await page.getByText('已导入学生数量', { exact: true }).waitFor();
    assert.equal(await page.locator('.registration-summary article').count(), 5);
    await navigation.getByRole('button', { name: '学生管理', exact: true }).click();
    await page.getByLabel('按学院筛选', { exact: true }).selectOption('c1');
    await page.getByLabel('按专业筛选', { exact: true }).selectOption('p1');
    await page.getByLabel('按班级筛选', { exact: true }).selectOption('cl1');
    assert.equal(await page.locator('.campus-student-table tbody tr').count(), 1);
    await page.getByLabel('按学院筛选', { exact: true }).selectOption('c2');
    assert.equal(await page.getByLabel('按专业筛选', { exact: true }).inputValue(), '');
    assert.equal(await page.getByLabel('按班级筛选', { exact: true }).isDisabled(), true);
    await page.locator('.academic-organization-tree').getByRole('button', { name: '工商管理', exact: true }).click();
    await page.locator('.academic-organization-tree').getByRole('button', { name: '管理一班', exact: true }).click();
    assert.equal(await page.getByLabel('按班级筛选', { exact: true }).inputValue(), 'cl2');
    await page.getByPlaceholder('搜索姓名、学号、邮箱或目标岗位').fill('不存在');
    await page.getByText('当前范围没有学生', { exact: true }).waitFor();
    await page.getByPlaceholder('搜索姓名、学号、邮箱或目标岗位').fill('b@example.test');
    assert.equal(await page.locator('.campus-student-table tbody tr').count(), 1);
    await page.getByPlaceholder('搜索姓名、学号、邮箱或目标岗位').fill('');
    await page.screenshot({ path: path.join(output, 'academic-information.png'), fullPage: true });
    await page.getByRole('button', { name: '管理组织', exact: true }).click();
    await page.getByRole('heading', { name: '组织管理', exact: true, level: 1 }).waitFor();
    assert.equal(await page.getByRole('dialog').count(), 0);
    await page.getByRole('button', { name: '新增专业', exact: true }).click();
    await page.getByLabel('专业名称', { exact: true }).fill('不提交的测试专业');
    await page.reload();
    await page.getByRole('heading', { name: '组织管理', exact: true, level: 1 }).waitFor();
    await page.getByRole('button', { name: '新增班级', exact: true }).click();
    await page.getByLabel('班级名称', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(output, 'organization-page.png'), fullPage: true });
    await navigation.getByRole('button', { name: '学生账号', exact: true }).click();
    await page.getByRole('button', { name: '注册学生', exact: true }).click();
    await page.getByRole('heading', { name: '注册学生', exact: true, level: 1 }).waitFor();
    assert.equal(await page.getByRole('dialog').count(), 0);
    assert.equal(await page.getByRole('button', { name: '注册学生', exact: true }).count(), 0);
    await page.reload();
    const form = page.locator('.student-registration-form');
    await form.getByLabel(/^学院/).selectOption('c1');
    await form.getByLabel(/^班级/).selectOption('cl1');
    await form.getByLabel('辅导员 *', { exact: true }).fill('新辅导员');
    await form.getByLabel('学号 *', { exact: true }).fill('20269999');
    await form.getByLabel('姓名 *', { exact: true }).fill('测试新学生');
    await form.getByLabel(/^性别/).selectOption('女');
    await page.screenshot({ path: path.join(output, 'registration-page.png'), fullPage: true });
    await form.getByRole('button', { name: '提交并返回列表', exact: true }).click();
    await page.getByText('已添加学生信息：测试新学生（20269999），请在学生账号页核对激活状态', { exact: true }).waitFor();
    await page.getByRole('heading', { name: '学生账号', exact: true, level: 1 }).waitFor();
    await page.locator('tbody tr').filter({ hasText: '20269999' }).waitFor();
    assert.equal(registrationPayload.counselor, '新辅导员');
    assert.equal(registrationPayload.college, '计算机学院');
    await page.getByRole('button', { name: '注册学生', exact: true }).click();
    await page.getByRole('button', { name: '返回学生账号', exact: true }).click();
    await page.getByRole('heading', { name: '学生账号', exact: true, level: 1 }).waitFor();
    await navigation.getByRole('button', { name: '学生管理', exact: true }).click();
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.screenshot({ path: path.join(output, 'academic-tablet.png'), fullPage: true });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, 'Tablet layout must not overflow horizontally');
    await page.setViewportSize({ width: 1440, height: 1000 });
    await navigation.getByRole('button', { name: '报告与评分', exact: true }).click();
    await page.getByRole('heading', { name: '报告与评分', level: 1 }).waitFor();
    assert.equal(await page.getByText('权重 20%', { exact: true }).count(), 0);
    assert.equal(await page.getByRole('button', { name: '保存报告与评分配置', exact: true }).isDisabled(), true);
    await page.getByLabel('OpenAI 文本模型', { exact: true }).fill('edited-report-model');
    assert.equal(await page.getByRole('button', { name: '检测已保存的报告模型', exact: true }).isDisabled(), true);
    await page.getByRole('button', { name: '实时面试', exact: true }).click();
    await page.getByLabel('OpenAI 音色', { exact: true }).fill('new-voice');
    await page.getByRole('button', { name: '保存实时面试配置', exact: true }).click();
    await page.getByRole('status').filter({ hasText: '实时面试配置已保存' }).waitFor();
    assert.deepEqual(modelWrites[0], { openaiVoice: 'new-voice' });
    await page.getByRole('button', { name: '报告与评分', exact: true }).click();
    assert.equal(await page.getByLabel('OpenAI 文本模型', { exact: true }).inputValue(), 'edited-report-model', 'Other scenario drafts survive saving');
    await page.getByLabel('报告网络重试次数', { exact: true }).fill('0');
    await page.getByLabel('单题评分供应商顺序', { exact: true }).fill('openai');
    await page.getByLabel('OpenAI 文本 API Key', { exact: true }).fill('synthetic-api-key');
    failModelSave = true;
    await page.getByRole('button', { name: '保存报告与评分配置', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: '测试模型保存失败' }).waitFor();
    assert.equal(await page.getByLabel('OpenAI 文本 API Key', { exact: true }).inputValue(), 'synthetic-api-key');
    await page.getByRole('button', { name: '保存报告与评分配置', exact: true }).click();
    await page.getByRole('status').filter({ hasText: '报告与评分配置已保存' }).waitFor();
    assert.deepEqual(modelWrites[1], { reportOpenaiApiKey: 'synthetic-api-key', reportOpenaiModel: 'edited-report-model', reportRetries: '0', evaluationProviderOrder: 'openai' });
    assert.equal(await page.getByLabel('OpenAI 文本 API Key', { exact: true }).inputValue(), '');
    await page.getByRole('button', { name: '检测已保存的报告模型', exact: true }).click();
    await page.getByText('连接成功 · 12 ms', { exact: true }).waitFor();
    await page.getByText('测试供应商不可用', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(output, 'model-settings-text.png'), fullPage: true });
    await page.reload();
    await page.getByLabel('OpenAI 文本模型', { exact: true }).waitFor();
    assert.equal(await page.getByLabel('OpenAI 文本模型', { exact: true }).inputValue(), 'edited-report-model');
    await page.getByRole('button', { name: '实时面试', exact: true }).click();
    await page.screenshot({ path: path.join(output, 'model-settings-realtime.png'), fullPage: true });
    await page.getByRole('button', { name: '语音合成', exact: true }).click();
    await page.getByLabel('语音合成模型', { exact: true }).fill('unsaved-model');
    await page.getByRole('button', { name: '撤销修改', exact: true }).click();
    assert.equal(await page.getByLabel('语音合成模型', { exact: true }).inputValue(), 'test-tts');
    await page.setViewportSize({ width: 768, height: 1024 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await page.getByRole('button', { name: '报告与评分', exact: true }).click();
    await page.screenshot({ path: path.join(output, 'model-settings-tablet.png'), fullPage: true });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    // Verify actual filtering, polling recovery, and sync feedback with synthetic data.
    extraReports = [
      { id: 'low', candidate: '低分学生', score: 69, reviewStatus: '待复核' },
      { id: 'boundary', candidate: '边界学生', score: 70, reviewStatus: '待复核' },
      { id: 'missing', candidate: '缺失分数学生', score: null, reviewStatus: '待复核' },
      { id: 'zero', candidate: '零分学生', score: 0, reviewStatus: '待复核' },
    ];
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(`${url}#/dashboard`);
    await page.reload();
    await page.getByText('管理服务已连接', { exact: true }).waitFor();
    await page.getByRole('button').filter({ hasText: '低分报告' }).click();
    await page.getByLabel('全部报告', { exact: true }).waitFor();
    assert.equal(await page.getByLabel('全部报告', { exact: true }).inputValue(), '低于 70 分');
    assert.equal(await page.locator('tbody tr').count(), 2);
    assert.equal(await page.locator('tbody').getByText('边界学生').count(), 0);
    await page.getByRole('button', { name: '清空筛选', exact: true }).click();
    assert.equal(await page.locator('tbody tr').count(), 5);
    await page.clock.install();
    await page.reload();
    await page.getByLabel('全部报告', { exact: true }).waitFor();
    failSnapshot = true;
    await page.clock.runFor(30010);
    await page.getByText('数据自动更新失败，当前保留上次结果，将自动重试。', { exact: true }).waitFor();
    assert.equal(await page.locator('tbody tr').count(), 5);
    failSnapshot = false;
    extraReports.push({ id: 'new', candidate: '自动刷新学生', score: 68, reviewStatus: '待复核' });
    await page.clock.runFor(30010);
    await page.locator('tbody').getByText('自动刷新学生', { exact: true }).waitFor();
    await navigation.getByRole('button', { name: /^训练记录/ }).click();
    await page.locator('tbody tr').filter({ hasText: '测试学生乙' }).click();
    await page.getByText('页面可见时每 10 秒更新训练详情。', { exact: true }).waitFor();
    runningText = '轮询新增的训练回答';
    await page.clock.runFor(10010);
    await page.getByText(runningText, { exact: true }).waitFor();
    await navigation.getByRole('button', { name: '招聘岗位', exact: true }).click();
    await page.getByText('尚未配置招聘数据源，请联系系统维护人员接入。当前可使用手动录入或 Excel 导入。', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: '从数据源同步', exact: true }).isDisabled(), true);
    syncConfigured = true;
    await page.reload();
    await page.getByRole('button', { name: '从数据源同步', exact: true }).click();
    await page.getByText('同步完成：新增 1 条，更新 0 条，失败 1 条。', { exact: true }).waitFor();
    await page.getByText('第 2 条：缺少岗位名称 title。', { exact: true }).waitFor();
    await page.locator('tbody').getByText('同步工程师', { exact: true }).waitFor();
    await navigation.getByRole('button', { name: '报告与评分', exact: true }).click();
    permissions.canManageSettings = false;
    await page.reload();
    await page.getByRole('heading', { name: '模型配置由超级管理员维护', exact: true }).waitFor();
    assert.equal(await page.locator('input[type=password]').count(), 0);
    permissions.canViewReports = false;
    await page.goto(`${url}#/interviews/review/training-complete-001`);
    await page.reload();
    await page.getByText('当前账号没有复核权限', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: '通过复核', exact: true }).isDisabled(), true);
    assert.deepEqual(errors, []);
    assert.deepEqual(unhandledRequests, []);
    console.log('PASS: list filters, copy, eight detail fields, full transcript, review success/failure, history, refresh, retry, permissions, registration, organization cascade, search and tablet rendering.');
    console.log(`Screenshots: ${output}`);
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
