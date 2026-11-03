/* All API traffic is mocked; no live credentials, student records or model calls. */
const { createRequire } = require('node:module');
const { createServer } = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const runtimeRequire = process.env.PLAYWRIGHT_MODULE_ROOT ? createRequire(path.join(process.env.PLAYWRIGHT_MODULE_ROOT, 'package.json')) : require;
const { chromium } = runtimeRequire('playwright');
const fixture = require('./interviewer-policy-fixture.cjs');
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'outputs/interviewer-policy-check');
fs.mkdirSync(output, { recursive: true });
const server = createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  const app = pathname.startsWith('/admin/') ? 'admin' : 'frontend';
  const relative = pathname.replace(/^\/admin\//, '/');
  const filename = path.join(root, app, 'dist', relative.startsWith('/assets/') ? relative.slice(1) : 'index.html');
  const mime = { '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.html': 'text/html' }[path.extname(filename)] || 'application/octet-stream';
  res.writeHead(200, { 'Content-Type': mime }); fs.createReadStream(filename).pipe(res);
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL });
  const errors = [], unhandled = [];
  let policy = structuredClone(fixture.policy), failSave = true, failRead = false, interview, submitted, resumeRunning = false;
  const agent = { id: 'a1', agent_name: '技术面试官', agent_type: 'technical', status: 'active', agent_role: '项目实践', strategy: '核对具体经历' };
  const opening = { id: 'm1', sender_type: 'agent', agent_id: 'a1', content: '请介绍你的项目。', message_type: 'question' };
  const next = { ...opening, id: 'q3', content: '为什么选择这个方案？' };
  const history = [opening];
  const secondAgent = { ...agent, id: 'a2', agent_name: '业务面试官' };
  const handoffQuestion = { ...opening, agent_id: secondAgent.id, id: 'q4', content: '你怎样衡量业务效果？' };
  let active = agent;
  let finishes = 0;
  let question = opening;
  let firstAttempt;
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    context.on('page', page => page.on('pageerror', error => errors.push(error.message)));
    await context.route('**/api/**', async route => {
      const url = new URL(route.request().url()), method = route.request().method(), p = url.pathname;
      let body = {};
      if (p === '/api/admin/auth/me') body = { admin: { id: 'admin', name: '测试管理员', email: 'admin@example.test', role: 'super_admin' } };
      else if (p === '/api/admin/health') body = { status: 'ok' };
      else if (p === '/api/admin/snapshot') body = { settings: {}, permissions: { canViewAgents: true, canManageSettings: true } };
      else if (p === '/api/admin/interviewer-policy') {
        if (method === 'PUT') {
          if (failSave) { failSave = false; return route.fulfill({ status: 500, json: { error: '模拟保存失败' } }); }
          policy = route.request().postDataJSON();
        }
        body = { policy, options: fixture.options };
      } else if (p === '/api/auth/me') body = { user: { id: 'student', name: '测试学生', email: 'student@example.test' } };
      else if (p === '/api/reports') body = { reports: [] };
      else if (p === '/api/profile') body = { profile: { target_role: '前端工程师', preferred_interviewer_style: '沉默压迫感' } };
      else if (p === '/api/profile/resume-analysis') body = { resume_analysis: { analysis: { recommended_directions: [] } } };
      else if (p === '/api/interviewer-policy') {
        if (failRead) { failRead = false; return route.fulfill({ status: 503, json: { error: '模拟策略读取失败' } }); }
        body = { policy };
      } else if (p === '/api/interviews') {
        if (method === 'POST') {
          submitted = route.request().postDataJSON();
          interview = { id: 'test-interview', ...submitted, status: 'running', interviewer_strategy: { version: 1, selection: submitted.interviewer_strategy, roles: structuredClone(policy.roles) } };
          body = { interview, agents: [agent] };
        } else body = { interviews: resumeRunning && interview ? [interview] : [] };
      } else if (p === '/api/interviews/test-interview' || p.endsWith('/start')) body = { interview };
      else if (p.endsWith('/agents')) body = { agents: [active] };
      else if (p.endsWith('/messages')) body = { messages: history };
      else if (p.endsWith('/current-question') && method === 'POST') {
        body = { question, active_agent: active, action: question === opening ? null : 'ask_follow_up', pending_spoken_submission_id: null };
      } else if (p.endsWith('/turns') && method === 'POST') {
        const submission = route.request().postDataJSON();
        if (!firstAttempt) {
          assert.equal(submission.question_id, opening.id);
          assert.equal(submission.source, 'text');
          firstAttempt = submission;
          // Another tab has already answered q2 when this client retries.
          question = next;
          history.push({ id: 'answer1', sender_type: 'candidate', content: submission.content },
            { ...opening, id: 'q2', content: '你的个人贡献是什么？' },
            { id: 'answer2', sender_type: 'candidate', content: '另一个标签页的回答' }, next);
          return route.abort('connectionreset');
        }
        if (submission.submission_id === firstAttempt.submission_id) {
          assert.deepEqual(submission, firstAttempt);
          body = { duplicate: true, answer: history[1], question: history[2], active_agent: agent, action: 'ask_follow_up' };
        } else {
          assert.equal(submission.question_id, question.id);
          const answer = { id: submission.submission_id, sender_type: 'candidate', content: submission.content };
          history.push(answer);
          if (active === agent) {
            active = secondAgent;
            question = handoffQuestion;
            history.push(question);
            body = { answer, question, active_agent: active, action: 'switch_agent', duplicate: false };
          } else {
            question = null;
            body = { answer, question, active_agent: null, action: 'finish_interview', duplicate: false };
          }
        }
      } else if (p.endsWith('/finish')) {
        finishes++;
        interview.status = 'completed';
        body = { interview };
      } else if (p.endsWith('/report')) {
        body = { report: null };
      } else if (p.endsWith('/evaluations')) body = { evaluation: {} };
      else unhandled.push(`${method} ${p}`);
      await route.fulfill({ status: 200, json: body });
    });
    const base = `http://127.0.0.1:${server.address().port}`;
    const adminPage = await context.newPage();
    await adminPage.goto(`${base}/admin/#/agents`);
    await adminPage.getByRole('button', { name: '面试官策略', exact: true }).click();
    await adminPage.getByLabel('默认交流风格', { exact: true }).selectOption('友好引导');
    await adminPage.getByLabel('允许交流风格：压力面试', { exact: true }).uncheck();
    await adminPage.getByLabel('技术面试官侧重点', { exact: true }).fill('关注项目实践与个人贡献');
    await adminPage.getByRole('button', { name: '保存面试官策略', exact: true }).click();
    await adminPage.getByRole('alert').filter({ hasText: '模拟保存失败' }).waitFor();
    assert.equal(await adminPage.getByLabel('技术面试官侧重点', { exact: true }).inputValue(), '关注项目实践与个人贡献');
    await adminPage.getByRole('button', { name: '保存面试官策略', exact: true }).click();
    await adminPage.getByRole('status').filter({ hasText: '策略已保存' }).waitFor();
    assert.equal(policy.defaults.style, '友好引导');
    assert.equal(policy.allowed.style.includes('压力面试'), false);
    await adminPage.reload();
    await adminPage.getByRole('button', { name: '面试官策略', exact: true }).click();
    await adminPage.getByLabel('默认交流风格', { exact: true }).waitFor();
    assert.equal(await adminPage.getByLabel('默认交流风格', { exact: true }).inputValue(), '友好引导');
    await adminPage.screenshot({ path: path.join(output, 'admin-strategy.png'), fullPage: true });
    await adminPage.setViewportSize({ width: 768, height: 1024 });
    assert.equal(await adminPage.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await adminPage.screenshot({ path: path.join(output, 'admin-strategy-tablet.png'), fullPage: true });

    async function openSetup(page, custom = false) {
      await page.goto(`${base}/`);
      await page.getByRole('button', { name: '开始电话面试 ↗', exact: true }).click();
      if (custom) await page.locator('.v4-choice-custom').click();
      else await page.getByRole('button', { name: /中等/ }).click();
    }
    const studentPage = await context.newPage();
    await openSetup(studentPage);
    await studentPage.getByLabel('面试官风格', { exact: true }).waitFor();
    assert.equal(await studentPage.getByLabel('面试官风格', { exact: true }).inputValue(), '友好引导');
    assert.deepEqual(await studentPage.getByLabel('面试官风格', { exact: true }).locator('option').allTextContents(), ['友好引导', '专业严谨']);
    await studentPage.getByLabel('面试官风格', { exact: true }).selectOption('专业严谨');
    await studentPage.getByLabel('考察重点', { exact: true }).selectOption('沟通表达');
    await studentPage.getByLabel('追问深度', { exact: true }).selectOption('连续深挖');
    await studentPage.screenshot({ path: path.join(output, 'student-strategy.png'), fullPage: true });
    await studentPage.getByRole('button', { name: '开始电话面试 ↗', exact: true }).click();
    await studentPage.locator('.session-strategy-summary').waitFor();
    assert.deepEqual(submitted.interviewer_strategy, { style: '专业严谨', focus: '沟通表达', depth: '连续深挖' });
    assert.ok((await studentPage.locator('.session-strategy-summary').innerText()).includes('连续深挖'));
    await studentPage.getByLabel('输入面试回答').fill('我负责设计索引');
    await studentPage.getByRole('button', { name: '发送' }).click();
    await studentPage.getByText(next.content, { exact: true }).waitFor();
    await studentPage.getByRole('button', { name: /转语音/ }).click();
    assert.equal(await studentPage.locator('.v4-voice-question p').innerText(), next.content);
    await studentPage.getByRole('button', { name: /转聊天框/ }).click();
    await studentPage.getByLabel('输入面试回答').waitFor();
    resumeRunning = true;
    await studentPage.reload();
    await studentPage.locator('.session-strategy-summary').waitFor();
    assert.ok((await studentPage.locator('.session-strategy-summary').innerText()).includes('连续深挖'));
    await studentPage.getByText(next.content, { exact: true }).waitFor();
    await studentPage.getByLabel('输入面试回答').fill('方案具备可验证的指标');
    await studentPage.getByRole('button', { name: '发送' }).click();
    await studentPage.getByText(handoffQuestion.content, { exact: true }).waitFor();
    assert.equal(await studentPage.locator('.v4-text-interview-head strong').innerText(), secondAgent.agent_name);
    await studentPage.getByLabel('输入面试回答').fill('转化率提升');
    await Promise.all([
      studentPage.waitForResponse(response => response.url().endsWith('/report')),
      studentPage.getByRole('button', { name: '发送' }).click(),
    ]);
    assert.equal(finishes, 1);
    resumeRunning = false;
    await adminPage.getByLabel('允许学生在面试前自主选择', { exact: true }).uncheck();
    await adminPage.getByRole('button', { name: '保存面试官策略', exact: true }).click();
    await adminPage.getByRole('status').filter({ hasText: '策略已保存' }).waitFor();
    await openSetup(studentPage, true);
    await studentPage.getByLabel('面试官风格', { exact: true }).waitFor();
    assert.equal(await studentPage.getByLabel('面试官风格', { exact: true }).isDisabled(), true);
    assert.equal(await studentPage.getByLabel('考察重点', { exact: true }).isDisabled(), true);
    assert.equal(await studentPage.getByLabel('追问深度', { exact: true }).isDisabled(), true);
    await studentPage.setViewportSize({ width: 390, height: 844 });
    await studentPage.locator('.candidate-strategy').screenshot({ path: path.join(output, 'student-strategy-mobile.png') });
    assert.equal(await studentPage.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    failRead = true;
    await openSetup(studentPage);
    await studentPage.getByRole('alert').filter({ hasText: '模拟策略读取失败' }).waitFor();
    assert.equal(await studentPage.getByRole('button', { name: '开始电话面试 ↗', exact: true }).isDisabled(), true);
    await studentPage.getByRole('button', { name: '重新读取策略', exact: true }).click();
    await studentPage.getByLabel('面试官风格', { exact: true }).waitFor();
    assert.equal(await studentPage.getByLabel('面试官风格', { exact: true }).isDisabled(), true);
    assert.deepEqual(errors, []);
    assert.deepEqual(unhandled, []);
    console.log('PASS: admin defaults/ranges/role editing, save failure/retry, student choices and payload, lost response replay, authoritative question, text/voice switch, reload, role handoff, finish, locked policy, loading failure/retry, responsive layouts.');
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
