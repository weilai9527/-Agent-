// 检查构建后的管理前端。拦截浏览器请求，使用合成报告模拟授权、撤权和版本冲突。
const assert = require('node:assert/strict');
const path = require('node:path');
const { createRequire } = require('node:module');
const load = process.env.PLAYWRIGHT_MODULE_ROOT
  ? createRequire(path.join(process.env.PLAYWRIGHT_MODULE_ROOT, 'package.json')) : require;
const { chromium } = load('playwright');

const dist = path.resolve(process.env.ADMIN_TEST_DIST || path.join(__dirname, '../dist'));

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.TEST_CHROME_PATH || undefined });
  try {
    const page = await browser.newPage();
    const admin = { id: 't1', name: '测试教师', role: 'teacher', actorType: 'teacher' };
    const permissions = { canViewReports: true, canReviewReports: true, canAdjustScores: true };
    const report = { id: 'r1', candidate: '测试学生', review_status: 'pending', total_score: 71, grade: 'B',
      generation_status: 'succeeded', scored_answer_count: 1, answer_count: 1, summary: '该版评分说明',
      timeline_review: [{ question: '请说明事务边界', answer: '按回合提交', score: 71 }], version: 1 };
    const versions = [{ version: 1, snapshot: { ...report }, source: 'generated', evidence_version: 'ev1' }];
    const reviews = [];
    const writes = [];
    const errors = [];
    let deny = false;
    let conflict = false;
    let versioned = true;
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', async route => {
      const pathname = new URL(route.request().url()).pathname;
      const json = body => route.fulfill({ json: body });
      if (pathname.endsWith('/auth/me')) return json({ admin });
      if (pathname.endsWith('/snapshot')) return json({
        admin, permissions, assessmentVersioned: versioned,
        reports: [{ ...report, score: report.total_score, reviewStatus: '待复核' }],
        interviews: [], metrics: [], auditLogs: [], candidates: [],
      });
      if (pathname.endsWith('/history')) {
        if (deny) return route.fulfill({ status: 403, json: { detail: '当前教师不负责此面试。' } });
        return json({ report, versions, reviews });
      }
      if (pathname.endsWith('/score') || pathname.endsWith('/review')) {
        const payload = route.request().postDataJSON();
        writes.push(payload);
        if (deny) return route.fulfill({ status: 403, json: { detail: '权限已收回' } });
        if (conflict) {
          conflict = false;
          return route.fulfill({ status: 409, json: { detail: '报告版本已变化' } });
        }
        if (pathname.endsWith('/score')) {
          report.version += 1;
          report.total_score = payload.total_score;
          report.review_status = 'pending';
          versions.unshift({ version: report.version, snapshot: { ...report }, actor_id: 't1',
            source: 'teacher', reason: payload.reason, evidence_version: 'ev1' });
        } else {
          report.review_status = payload.status;
          reviews.unshift({ version: report.version, status: payload.status, note: payload.note, id: 'note1', actor_id: 't1' });
        }
        return json({ report });
      }
      if (pathname.endsWith('/reports/r1')) return json({ report });
      if (pathname.startsWith('/api/')) return json({});
      if (!pathname.startsWith('/admin/')) return route.abort();
      const rel = pathname.slice('/admin/'.length);
      return route.fulfill({ path: path.join(dist, rel.startsWith('assets/') ? rel : 'index.html') });
    });
    const open = async () => {
      await page.goto('http://admin.test/admin/#/reports');
      await page.reload();
      await page.getByRole('button', { name: '查看详情' }).first().click();
    };
    const panel = page.getByRole('region', { name: '报告版本与教师审核' });
    await open();
    await panel.getByText('按回合提交', { exact: true }).waitFor();
    assert(await panel.getByRole('button', { name: '通过复核' }).isDisabled());
    await panel.getByLabel('复核意见').fill('已核对原回答');
    await panel.getByRole('button', { name: '通过复核' }).click();
    await panel.getByText('已核对原回答', { exact: true }).waitFor();
    assert.deepEqual(writes.at(-1), { status: 'approved', note: '已核对原回答', expected_version: 1 });
    await panel.getByLabel('调整后总分').fill('83');
    await panel.getByLabel('改分理由').fill('补充项目证据');
    await panel.getByRole('button', { name: '保存改分并建立新版' }).click();
    await panel.getByLabel('查看报告版本').getByRole('option', { name: '版本 2 · 教师改分（当前）' }).waitFor({ state: 'attached' });
    assert.deepEqual(writes.at(-1), { total_score: 83, reason: '补充项目证据', expected_version: 1 });
    await panel.getByLabel('查看报告版本').selectOption('1');
    await panel.getByText('已核对原回答', { exact: true }).waitFor();
    assert.equal(await panel.getByLabel('调整后总分').count(), 0);
    await panel.getByLabel('查看报告版本').selectOption('2');
    await panel.getByLabel('复核意见').fill('版本冲突用例');
    conflict = true;
    await panel.getByRole('button', { name: '通过复核' }).click();
    await panel.getByRole('alert').waitFor();
    assert.equal(await panel.getByLabel('复核意见').count(), 0);
    assert.equal(writes.length, 3);
    await panel.getByRole('button', { name: '重新读取报告' }).click();
    await panel.getByLabel('复核意见').fill('授权收回用例');
    deny = true;
    await panel.getByRole('button', { name: '通过复核' }).click();
    await panel.getByText('权限已收回').waitFor();
    assert.equal(await panel.getByText('按回合提交', { exact: true }).count(), 0);
    await panel.getByRole('button', { name: '重新读取报告' }).click();
    await panel.getByText('当前教师不负责此面试。').waitFor();
    deny = false; permissions.canAdjustScores = false; permissions.canReviewReports = false;
    await open();
    await panel.getByLabel('查看报告版本').waitFor();
    assert.equal(await panel.getByLabel('调整后总分').count(), 0);
    assert.equal(await panel.getByLabel('复核意见').count(), 0);
    versioned = false;
    await open();
    assert.equal(await panel.count(), 0);
    assert.equal(await page.getByRole('button', { name: '通过复核' }).count(), 0);
    permissions.canReviewReports = true;
    await open();
    await page.getByRole('button', { name: '通过复核' }).click();
    await page.getByText('报告已通过复核').waitFor();
    assert.deepEqual(writes.at(-1), { status: 'approved' });
    assert.deepEqual(errors, []);
    console.log('PASS report versions, evidence, teacher changes, conflict, revoked access, read-only and legacy review');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
