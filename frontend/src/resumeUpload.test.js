import test from 'node:test';
import assert from 'node:assert/strict';
import { uploadResume } from './resumeUpload.js';

test('上传前拒绝不支持的格式、空文件和超限文件', async () => {
  let calls = 0;
  const request = async () => { calls += 1; };
  for (const file of [{ name: 'resume.exe', size: 10 }, { name: 'resume.pdf', size: 0 }, { name: 'resume.pdf', size: 10485761 }]) {
    await assert.rejects(uploadResume('/upload', file, request));
  }
  assert.equal(calls, 0);
});

test('按 multipart 提交简历并携带会话，保留提取结果', async () => {
  const file = new File(['resume'], 'resume.PDF', { type: 'application/pdf' });
  const expected = { text: 'extracted resume', filename: 'resume.PDF', truncated: true, profile: { target_role: 'developer' } };
  const data = await uploadResume('/upload', file, async (url, options) => {
    assert.equal(url, '/upload');
    assert.equal(options.method, 'POST');
    assert.equal(options.credentials, 'include');
    assert.equal(options.headers, undefined); // 浏览器需要自行生成与表单一致的 multipart 边界。
    assert.equal(options.body.get('file').name, file.name);
    assert.equal(await options.body.get('file').text(), 'resume');
    return { ok: true, json: async () => expected };
  });
  assert.deepEqual(data, expected);
});

test('上传失败时区分解析错误和服务不可用', async () => {
  const file = new File(['resume'], 'resume.txt');
  await assert.rejects(uploadResume('/upload', file, async () => ({ ok: false, json: async () => ({ detail: '无法解析 PDF' }) })), /无法解析 PDF/);
  await assert.rejects(uploadResume('/upload', file, async () => ({ ok: false, json: async () => { throw new Error('HTML response'); } })), /暂时不可用/);
  await assert.rejects(uploadResume('/upload', file, async () => ({ ok: true, json: async () => ({ text: '' }) })), /未能提取/);
});
