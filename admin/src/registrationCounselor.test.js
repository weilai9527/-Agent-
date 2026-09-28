import assert from 'node:assert/strict';
import test from 'node:test';
import { resolveRegistrationCounselor } from './registrationCounselor.js';

const college = { id: 'college-1', name: '计算机学院' };
const selectedClass = { id: 'class-1', college_id: college.id, name: 'G22信息安全技术应用2班', advisor: null };
const student = { college: college.name, className: selectedClass.name, counselor: '王老师', activated: false };
const resolve = (registrations, classItem = selectedClass, classes = [classItem]) => (
  resolveRegistrationCounselor(college, classItem, classes, registrations)
);

test('未激活且其他信息不完整的名单也可提供辅导员', () => {
  assert.deepEqual(resolve([student]), { counselor: '王老师', source: 'registrations', error: '' });
});

test('优先使用组织配置，忽略名单中不同的辅导员', () => {
  assert.deepEqual(resolve([student], { ...selectedClass, advisor: ' 李老师 ' }), {
    counselor: '李老师', source: 'organization', error: '',
  });
});

test('按学院和班级同时匹配，处理空白、重复及激活状态', () => {
  const result = resolve([
    { ...student, college: ` ${college.name} `, className: ` ${selectedClass.name} `, counselor: ' 王老师 ' },
    { ...student, activated: true },
    { ...student, counselor: '   ' },
    { ...student, college: '其他学院', counselor: '李老师' },
    { ...student, className: '其他班级', counselor: '张老师' },
  ], { ...selectedClass, advisor: '  ' });
  assert.equal(result.counselor, '王老师');
  assert.equal(result.error, '');
});

test('同班辅导员冲突时不随意选取', () => {
  const result = resolve([student, { ...student, counselor: '李老师' }]);
  assert.equal(result.counselor, '');
  assert.match(result.error, /多个辅导员/);
});

test('缺少辅导员时给出准确提示，不借用其他学院或班级的信息', () => {
  const result = resolve([
    { ...student, counselor: null },
    { ...student, college: '其他学院' },
    { ...student, className: '其他班级' },
  ]);
  assert.equal(result.counselor, '');
  assert.match(result.error, /均未找到辅导员/);
});

test('同学院存在重名班级时需要配置辅导员', () => {
  const result = resolve([student], selectedClass, [selectedClass, { ...selectedClass, id: 'class-2' }]);
  assert.equal(result.counselor, '');
  assert.match(result.error, /多个名为/);
});

test('未选择学院或班级时不显示旧辅导员和错误', () => {
  for (const [selectedCollege, classItem] of [[null, selectedClass], [college, null]]) {
    assert.deepEqual(resolveRegistrationCounselor(selectedCollege, classItem, [selectedClass], [student]), {
      counselor: '', source: '', error: '',
    });
  }
});
