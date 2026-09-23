import test from 'node:test';
import assert from 'node:assert/strict';
import { mergeProfileIntoSetup } from './setupDefaults.js';

const easyPreset = {
  role: '',
  level: '应届',
  interviewType: '技术一面',
  companyScene: '校招 HR 面',
  focusArea: '八股基础',
  intensity: '轻松',
  style: '友好引导',
  brief: '',
};

const savedProfile = {
  target_role: '幼儿园行政助理',
  resume_text: '已保存的简历内容',
  experience_level: '中级',
  preferred_interview_type: '技术二面',
  preferred_difficulty: '严格',
  preferred_interviewer_style: '犀利追问',
};

test('guided difficulty keeps the selected preset while loading role and resume', () => {
  assert.deepEqual(mergeProfileIntoSetup(easyPreset, savedProfile, 'guided'), {
    ...easyPreset,
    role: '幼儿园行政助理',
    brief: '已保存的简历内容',
  });
});

test('custom setup can reuse saved interview preferences', () => {
  const result = mergeProfileIntoSetup(easyPreset, savedProfile, 'custom');
  assert.equal(result.level, '中级');
  assert.equal(result.interviewType, '技术二面');
  assert.equal(result.intensity, '严格');
  assert.equal(result.style, '犀利追问');
  assert.equal(result.companyScene, '校招 HR 面');
  assert.equal(result.focusArea, '八股基础');
});

test('an edited brief is never replaced by a delayed profile response', () => {
  const current = { ...easyPreset, brief: '用户刚刚输入的内容' };
  assert.equal(
    mergeProfileIntoSetup(current, savedProfile, 'guided', { preserveBrief: true }).brief,
    '用户刚刚输入的内容',
  );
});
