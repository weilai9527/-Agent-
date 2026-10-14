import test from 'node:test';
import assert from 'node:assert/strict';
import { roles, scopeStudents, scopeClasses, scopeColleges, scopeInterviews, scopePlans, canManagePlan, canUseSystem } from './roles.js';
import { students, interviews, classes, plans, colleges } from './data.js';

const [school, college, counselor] = roles;
test('校级管理员可见全校实体及系统菜单', () => {
  assert.equal(scopeStudents(school, students).length, students.length);
  assert.equal(scopeClasses(school).length, classes.length);
  assert.equal(scopeColleges(school).length, colleges.length);
  assert.equal(scopeInterviews(school, interviews, students).length, interviews.length);
  assert.equal(scopePlans(school, plans).length, plans.length);
  assert.equal(canUseSystem(school), true);
});

test('学院管理员仅可见计算机学院，不能访问系统', () => {
  const scoped = scopeStudents(college, students);
  assert.ok(scoped.length > 0 && scoped.length < students.length);
  assert.ok(scoped.every(student => classes.find(item => item.id === student.classId).college === 'computer'));
  assert.deepEqual(scopeColleges(college).map(item => item.id), ['computer']);
  const ids = new Set(scoped.map(item => item.id));
  assert.ok(scopeInterviews(college, interviews, students).every(item => ids.has(item.studentId)));
  assert.equal(canUseSystem(college), false);
});

test('辅导员只能看到两个负责班级，不含同学院其他班', () => {
  assert.deepEqual(scopeClasses(counselor).map(item => item.id), ['software2301', 'cs2302']);
  assert.deepEqual(scopeStudents(counselor, students).map(item => item.id).sort(), ['2023010101', '2023010102', '2023010204', '2023010208']);
  assert.deepEqual(scopeColleges(counselor).map(item => item.id), ['computer']);
  assert.equal(canUseSystem(counselor), false);
});

test('计划可见范围按目标相交，草稿限拥有角色与校级', () => {
  const scoped = scopePlans(counselor, plans);
  assert.ok(scoped.some(item => item.id === 'demo-autumn'));
  assert.ok(scoped.some(item => item.id === 'demo-tech'));
  assert.ok(scoped.some(item => item.id === 'demo-draft'));
  assert.ok(!scoped.some(item => item.id === 'demo-intro'));
  assert.ok(!scopePlans(college, plans).some(item => item.id === 'demo-draft'));
});

test('计划管理禁止角色扩大目标范围', () => {
  assert.equal(canManagePlan(counselor, { target: { kind: 'all', ids: [] } }), false);
  assert.equal(canManagePlan(counselor, { target: { kind: 'colleges', ids: ['computer'] } }), false);
  assert.equal(canManagePlan(counselor, { target: { kind: 'classes', ids: ['software2301'] } }), true);
  assert.equal(canManagePlan(counselor, { target: { kind: 'classes', ids: ['software2301', 'network2301'] } }), false);
  assert.equal(canManagePlan(college, { target: { kind: 'colleges', ids: ['computer'] } }), true);
  assert.equal(canManagePlan(college, { target: { kind: 'colleges', ids: ['business'] } }), false);
});

test('未知角色默认不可见，不能扩大范围', () => {
  assert.deepEqual(scopeStudents({ id: 'unknown' }, students), []);
  assert.deepEqual(scopeInterviews({ id: 'unknown' }, interviews, students), []);
  assert.deepEqual(scopeColleges({ id: 'unknown' }), []);
  assert.equal(canUseSystem({ id: 'unknown' }), false);
});
