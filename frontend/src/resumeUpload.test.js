import test from 'node:test';
import assert from 'node:assert/strict';
import { uploadResume } from './resumeUpload.js';

test('resume upload rejects unsupported, empty, and oversized files before sending', async () => {
  let calls = 0;
  const request = async () => { calls += 1; };
  for (const file of [{ name: 'resume.exe', size: 10 }, { name: 'resume.pdf', size: 0 }, { name: 'resume.pdf', size: 10485761 }]) {
    await assert.rejects(uploadResume('/upload', file, request));
  }
  assert.equal(calls, 0);
});

test('resume upload sends multipart with session cookies and preserves extraction metadata', async () => {
  const file = new File(['resume'], 'resume.PDF', { type: 'application/pdf' });
  const expected = { text: 'extracted resume', filename: 'resume.PDF', truncated: true, profile: { target_role: 'developer' } };
  const data = await uploadResume('/upload', file, async (url, options) => {
    assert.equal(url, '/upload');
    assert.equal(options.method, 'POST');
    assert.equal(options.credentials, 'include');
    assert.equal(options.headers, undefined); // Browser must supply the multipart boundary.
    assert.equal(options.body.get('file').name, file.name);
    assert.equal(await options.body.get('file').text(), 'resume');
    return { ok: true, json: async () => expected };
  });
  assert.deepEqual(data, expected);
});

test('resume upload surfaces extraction failures and unavailable service', async () => {
  const file = new File(['resume'], 'resume.txt');
  await assert.rejects(uploadResume('/upload', file, async () => ({ ok: false, json: async () => ({ detail: '无法解析 PDF' }) })), /无法解析 PDF/);
  await assert.rejects(uploadResume('/upload', file, async () => ({ ok: false, json: async () => { throw new Error('HTML response'); } })), /暂时不可用/);
  await assert.rejects(uploadResume('/upload', file, async () => ({ ok: true, json: async () => ({ text: '' }) })), /未能提取/);
});
