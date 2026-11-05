// 参数是临时 Vite 构建目录。页面、资源和 API 都通过进程内拦截提供，不访问真实账号或媒体。
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

async function run() {
  const dist = path.resolve(process.argv[2]);
  const origin = 'https://student.invalid';
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_BIN || undefined, headless: true,
    args: ['--disable-background-networking', '--no-first-run', '--no-proxy-server'],
  });
  try {
    const context = await browser.newContext({ serviceWorkers: 'block' });
    const user = { id: 'synthetic', studentNo: 'TEST01', name: '测试学生' };
    const interview = { id: 'session', user_id: user.id, target_role: '合成题目', status: 'running' };
    const agent = { id: 'agent', agent_name: '面试官', agent_type: 'technical', status: 'active' };
    const question = { id: 'question', agent_id: agent.id, sender_type: 'agent', message_type: 'question',
      order_index: 1, content: '请描述一次事务回滚。' };
    const room = '/api/interviews/' + interview.id;
    let sessionCheck = 0, logout = 0, finish = 0, video = 0, submission;
    const unexpected = [], crashes = [];
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url()), endpoint = url.pathname;
      const send = (status, json) => route.fulfill({ status, json });
      if (url.origin !== origin) { unexpected.push(url.origin); return route.abort(); }
      if (!endpoint.startsWith('/api/')) {
        const file = endpoint === '/' ? 'index.html' : endpoint.slice(1);
        const target = path.resolve(dist, file);
        if (!target.startsWith(dist + path.sep)) return route.abort();
        try { await fs.access(target); } catch { return route.fulfill({ status: 404 }); }
        return route.fulfill({ path: target });
      }
      if (endpoint === '/api/auth/me') return ++sessionCheck === 1
        ? send(503, { error: '合成身份服务暂不可用' }) : send(200, { user: null });
      if (endpoint === '/api/auth/login') return send(200, { user });
      if (endpoint === '/api/auth/logout') return ++logout === 1
        ? send(503, { error: '身份服务暂不可用' }) : send(200, {});
      if (endpoint === '/api/reports') return send(200, { reports: [] });
      if (endpoint === '/api/interviews') return send(200, { interviews: [interview] });
      if (endpoint === room) return send(200, { interview });
      if (endpoint === room + '/agents') return send(200, { agents: [agent] });
      if (endpoint === room + '/messages') return send(200, { messages: [question] });
      if (endpoint === room + '/current-question') return send(200, { question, active_agent: agent });
      if (endpoint === room + '/media/video/token') {
        video++; return send(503, { error: '合成视频服务暂不可用', fallback: 'text' });
      }
      if (endpoint === room + '/turns') {
        submission = request.postDataJSON();
        return send(200, { answer: { id: 'answer' }, action: 'finish_interview' });
      }
      if (endpoint === room + '/finish') { finish++; return send(200, {}); }
      if (endpoint === room + '/report') return send(404, { error: '未找到本次报告' });
      unexpected.push(endpoint);
      return send(404, { error: '未登记的测试接口' });
    });
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    page.on('pageerror', error => crashes.push(error.message));
    await page.goto(origin);
    await page.getByText('暂时无法确认登录状态').waitFor();
    assert.equal(await page.getByRole('button', { name: '使用学号登录' }).count(), 0);
    await page.getByRole('button', { name: '重试', exact: true }).click();
    await page.getByPlaceholder('请输入学校分配的学号').fill('TEST01');
    await page.getByPlaceholder('输入登录密码').fill('synthetic-password');
    await page.getByRole('button', { name: '使用学号登录' }).click();
    await page.getByRole('button', { name: '开启摄像头并录制本题' }).click();
    await page.getByText('媒体服务暂时不可用，可继续文字面试。').waitFor();
    const answer = '合成答案：检查事务版本再提交。';
    await page.getByRole('textbox', { name: '输入面试回答' }).fill(answer);
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await page.getByText('未找到本次报告').waitFor();
    assert.equal(video, 1);
    assert.equal(finish, 1);
    assert.equal(submission.question_id, question.id);
    assert.equal(submission.content, answer);
    assert.ok(submission.submission_id);
    const exit = page.getByRole('button', { name: '退出登录', exact: true });
    await exit.click();
    await page.getByText(/未能确认退出/).waitFor();
    await exit.click();
    await page.getByRole('button', { name: '使用学号登录' }).waitFor();
    assert.deepEqual(crashes, []);
    assert.deepEqual(unexpected, []);
    console.log('通过：身份 503 重试、原生登录、视频故障转文字、提交回合、报告 404、退出失败重试');
  } finally {
    await browser.close();
  }
}

run().catch(error => { console.error(error); process.exitCode = 1; });
