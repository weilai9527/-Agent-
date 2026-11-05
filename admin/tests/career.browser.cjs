// 由职业管理浏览器验收脚本调用，使用新建的原生测试学校。
const assert = require('node:assert/strict');
const path = require('node:path');
const { createRequire } = require('node:module');
const load = process.env.PLAYWRIGHT_MODULE_ROOT ? createRequire(path.join(process.env.PLAYWRIGHT_MODULE_ROOT, 'package.json')) : require;
const { chromium } = load('playwright');
const base = process.env.CAREER_TEST_ORIGIN;
if (new URL(base).hostname !== '127.0.0.1') throw new Error('Only an isolated loopback gateway is supported');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.TEST_CHROME_PATH || undefined });
  const failures = [];
  try {
    async function login(user, label, recruitment = false) {
      const page = await browser.newPage();
      await page.route('**/*', route => new URL(route.request().url()).origin === base ? route.continue() : route.abort());
      page.on('pageerror', error => failures.push(error.message));
      page.on('response', res => {
        const url = new URL(res.url());
        if (res.status() >= 400 && url.pathname !== '/api/admin/auth/me') failures.push(res.status() + ' ' + url.pathname);
      });
      await page.goto(base + '/admin/');
      await page.locator('input[type=email]').fill(user + '@school.test');
      await page.locator('input[type=password]').fill('Synthetic-Career-Password-123!');
      await Promise.all([page.waitForResponse(res => res.url().endsWith('/api/admin/snapshot') && res.ok()),
        page.locator('button[type=submit]').click()]);
      const nav = page.getByRole('navigation', {name:'管理端导航'});
      const opener = page.getByRole('button', {name:'展开侧边栏'});
      if (await opener.isVisible()) await opener.click();
      if (recruitment) {
        const branch = nav.getByRole('button', {name:'招聘信息', exact:true});
        if (await branch.getAttribute('aria-expanded') !== 'true') await branch.click();
      }
      await nav.getByRole('button', {name:label, exact:true}).click();
      return page;
    }
    const importer = await login('importer', '招聘岗位', true);
    await importer.locator('input[type=file]').setInputFiles(process.env.CAREER_TEST_WORKBOOK);
    await importer.getByRole('button', {name:'上传并导入'}).click();
    await importer.getByText(/Excel 导入完成：新增 1 条/).waitFor();
    assert.equal(await importer.getByRole('button', {name:'新增岗位'}).count(), 0);
    assert.equal(await importer.getByRole('button', {name:'导出', exact:true}).count(), 0);
    await importer.close();

    const reader = await login('reader', '招聘岗位', true);
    await reader.getByText('Synthetic career posting', {exact:true}).waitFor();
    assert.equal(await reader.locator('input[type=file]').count(), 0);
    assert.equal(await reader.getByRole('button', {name:'删除',exact:true}).count(), 0);
    await reader.close();

    const review = await login('reviewer', '学生 JD 审核', true);
    await review.getByRole('button', {name:'审核入库'}).click();
    await review.getByText('审核通过，已写入招聘信息库岗位列表。').waitFor();
    assert.equal(await review.getByRole('button', {name:'新增记录'}).count(), 0);
    assert.equal(await review.getByRole('button', {name:'删除',exact:true}).count(), 0);
    await review.close();

    const author = await login('jd-author', '学生 JD 审核', true);
    await author.getByRole('button', {name:'新增记录'}).click();
    const form = author.getByRole('dialog', {name:'粘贴 JD 记录编辑'});
    await form.getByLabel('岗位名称 *').fill('Synthetic manual JD');
    await form.getByLabel('岗位描述（JD）').fill('Synthetic requirements used only in this disposable database.');
    await form.getByRole('button', {name:'保存记录'}).click();
    await author.getByText('粘贴 JD 记录已新增。').waitFor();
    assert.equal(await author.getByRole('button', {name:'审核入库'}).count(), 0);
    await author.close();

    const draftImporter = await login('catalog-importer', '岗位信息');
    await draftImporter.getByLabel('目标草稿 ID').fill('ui-draft');
    await draftImporter.locator('input[type=file]').setInputFiles(process.env.CAREER_TEST_CATALOG_BOOK);
    await draftImporter.getByRole('button', {name:'上传并导入'}).click();
    await draftImporter.getByText('Excel 导入成功，共写入 7 行。').waitFor();
    assert.equal(await draftImporter.getByRole('button', {name:'发布当前草稿'}).count(), 0);
    await draftImporter.close();

    const catalog = await login('catalog', '岗位信息');
    await catalog.getByText('职业能力目录', {exact:true}).first().waitFor();
    assert.equal(await catalog.getByRole('tab', {name:'专业岗位配置'}).count(), 0);
    await catalog.getByRole('button', {name:'驳回'}).click();
    await catalog.getByText('岗位建议已驳回。').waitFor();
    assert.equal(await catalog.getByRole('button', {name:'创建草稿'}).count(), 0);
    await catalog.close();
    assert.deepEqual(failures, []);
    console.log('PASS: native import-only, posting reader, JD approval, catalog review, draft import and manual JD entry via the sidebar; no unauthorized automatic reads');
  } finally {
    await browser.close();
  }
})().catch(err => { console.error(err); process.exitCode = 1; });
