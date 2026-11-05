// 由同名 Python 脚本启动。只连接其创建的临时回环服务。
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = new URL(process.env.QA_BASE);
assert.equal(origin.hostname, '127.0.0.1');
const grantPassword = 'Synthetic-teacher-secret-092';

async function run() {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_BIN || undefined,
    headless: true,
    args: ['--disable-background-networking', '--no-first-run', '--no-proxy-server'],
  });
  const pageErrors = [], failed = [];
  const startSession = async (email, password, newPassword) => {
    const context = await browser.newContext({ serviceWorkers: 'block' });
    // 拒绝外部连接。所有响应（含权限拒绝）均来自真实本地网关，禁止模拟业务结果。
    await context.route('**/*', route =>
      new URL(route.request().url()).origin === origin.origin ? route.continue() : route.abort());
    const page = await context.newPage();
    page.setDefaultTimeout(12000);
    page.on('pageerror', error => pageErrors.push(error.message));
    page.on('response', r => {
      if (r.status() >= 400 && new URL(r.url()).pathname.startsWith('/api/'))
        failed.push([r.request().method(), new URL(r.url()).pathname, r.status()]);
    });
    await page.goto(origin + 'admin/#/nativeSchool');
    await page.getByLabel('管理员邮箱').fill(email);
    await page.getByLabel('登录密码', { exact: true }).fill(password);
    await page.getByRole('button', { name: '登录管理端' }).click();
    if (newPassword) {
      await page.getByLabel('新密码（至少 12 位）', { exact: true }).fill(newPassword);
      await page.getByLabel('确认新密码', { exact: true }).fill(newPassword);
      await page.getByRole('button', { name: '登录管理端' }).click();
    }
    await page.locator('.native-school-session').waitFor();
    assert.match(await page.locator('.native-school-session').innerText(), /synthetic-school/);
    assert.equal(new URL(page.url()).hash, '#/nativeSchool');
    assert.ok((await context.cookies()).some(c => c.name === 'identity_staff_session' && c.httpOnly));
    return page;
  };
  const button = (scope, name) => scope.getByRole('button', { name, exact: true });
  const section = (page, title) => page.locator('section').filter({ has: page.getByRole('heading', { name: title, exact: true }) }).last();
  try {
    const admin = await startSession('qa@unit.test', process.env.QA_PASSWORD);
    console.log('PASS admin sign-in, native cookie, real school on /admin/#/nativeSchool');
    await button(admin, '教职工授权').click();
    await button(admin, '新增账号').click();
    const teacherForm = admin.locator('form.settings-form');
    await teacherForm.getByLabel('姓名', { exact: true }).fill('验收任课教师');
    await teacherForm.getByLabel('登录邮箱').fill('teacher@unit.test');
    await teacherForm.getByLabel('初始密码').fill(grantPassword);
    await teacherForm.locator('input[value="organization.read"]').check();
    await teacherForm.locator('input[value="student.read"]').check();
    await button(teacherForm, '创建账号').click();
    await admin.getByRole('cell', { name: /teacher@unit.test/ }).waitFor();
    const staffId = await admin.getByRole('row', { name: /teacher@unit.test/ }).getByLabel('职员编号').textContent();
    await button(admin, '组织与名册').click();
    await admin.getByLabel('组织 Excel 或 CSV').setInputFiles({
      name:'学校组织.csv',mimeType:'text/csv',buffer:Buffer.from('学院,专业,班级\n新学院,新专业,新一班\n')
    });
    await button(admin,'导入组织工作簿').click();
    await admin.getByText('组织导入完成，新增学院 1 个、专业 1 个、班级 1 个。').waitFor();
    await button(admin, '验收一班 · class-one').click();
    await admin.getByRole('checkbox', { name: /验收任课教师/ }).check();
    await button(admin, '保存班级分配').click();
    await admin.getByText('班级任课与管理范围已更新。').waitFor();
    console.log('PASS teacher creation, per-action grants and responsible class assignment');

    await button(admin, '学生账号').click();
    const studentForm = admin.getByRole('form', { name: '批量开通学生账号' });
    await studentForm.getByLabel('姓名 1').fill('验收学生');
    await studentForm.getByLabel('学号 1').fill('QA2026001');
    await studentForm.getByLabel('临时密码 1').fill('Test-student-secret-373');
    await button(studentForm, '开通 1 个账号').click();
    await admin.getByText('已开通 1 个账号', { exact: true }).waitFor();
    assert.equal(await studentForm.getByLabel('临时密码 1').inputValue(), '');
    await button(admin, '组织与名册').click();
    await button(admin, '验收一班 · class-one').click();
    const enroll = section(admin, '批量归班');
    await enroll.getByLabel('查找学生（学号或姓名）').fill('QA2026001');
    await button(enroll, '查询').click();
    await enroll.getByRole('checkbox', { name: /验收学生/ }).check();
    await button(enroll, '导入所选班级').click();
    await section(admin, '在册学生').getByRole('cell', { name: '验收学生', exact: true }).waitFor();
    await button(admin, '注册名单与开通待办').click();
    const registration = admin.locator('form').filter({ hasText: '新增或更新登记' });
    await registration.getByLabel('学号', { exact: true }).fill('BOOK123');
    await registration.getByLabel('姓名', { exact: true }).fill('登记验收学生');
    await button(registration, '保存登记').click();
    await admin.getByRole('checkbox', { name: '选择 BOOK123', exact: true }).check();
    admin.once('dialog', d => d.accept());
    await button(admin, '开通并生成发放单').click();
    await admin.getByRole('heading', { name: '一次性密码发放单' }).waitFor();
    await button(admin, '已发放，清除本页密码').click();
    await admin.getByRole('checkbox', { name: '选择 BOOK123', exact: true }).check();
    admin.once('dialog', d => d.accept());
    await button(admin, '撤销登录').click();
    await admin.getByRole('row', { name: /BOOK123.*待开通/ }).waitFor();
    console.log('PASS 原生登记、开通、一次性发放与撤销登录');
    await button(admin, '学校审计').click();
    await admin.getByText('staff.create', { exact: true }).waitFor();
    await admin.getByText('roster.import', { exact: true }).waitFor();
    await admin.getByText('student.import', { exact: true }).waitFor();
    console.log('PASS new student, confirmed roster membership, persisted audit rows in management UI');

    await button(admin, '职员资料与密码').click();
    await admin.getByLabel('本校职员编号').fill(staffId);
    await button(admin, '核对职员').click();
    await admin.getByLabel('新姓名').fill('新姓名教师');
    admin.once('dialog', d => d.accept());
    await button(admin, '保存姓名').click();
    await admin.getByText('职员资料已更新。').waitFor();
    await admin.getByLabel('办理事项').selectOption('password-reset');
    await button(admin, '核对职员').click();
    admin.once('dialog', d => d.accept());
    await button(admin, '撤销原会话并补发临时密码').click();
    await button(admin, '已发放，清除').waitFor();
    const once = await admin.getByRole('region', { name: '职员资料与密码' }).locator('code').textContent();
    await button(admin, '已发放，清除').click();
    const teacher = await startSession('teacher@unit.test', once, 'NewSyntheticTeacher-2026!');
    console.log('PASS 职员改名、强制重置、改密前无会话、首次改密后进入教务台');
    await button(teacher, '验收一班 · class-one').click();
    await section(teacher, '在册学生').getByRole('cell', { name: '验收学生', exact: true }).waitFor();
    assert.equal(await button(teacher, '学校审计').count(), 0);
    assert.equal(await button(teacher, '教职工授权').count(), 0);
    assert.equal(await button(teacher, '保存班级分配').count(), 0);
    await button(teacher, '学生账号').click();
    await teacher.getByRole('cell', { name: /验收学生.*QA2026001/ }).waitFor();
    assert.equal(await teacher.getByRole('form', { name: '批量开通学生账号' }).count(), 0);
    assert.equal(await button(teacher, '重置密码并撤销会话').count(), 0);
    const deny = await teacher.evaluate(async () => (await fetch('/api/admin/identity/v1/staff', { credentials: 'include' })).status);
    assert.equal(deny, 403);
    assert.deepEqual(pageErrors, []);
    console.log('PASS independent teacher session, assigned roster, hidden management actions, direct staff list 403');
  } catch (error) {
    console.error('Recent API denials (paths only)', failed.slice(-12), 'JS errors', pageErrors);
    throw error;
  } finally { await browser.close(); }
}
run().catch(error => { console.error(error); process.exitCode = 1; });
