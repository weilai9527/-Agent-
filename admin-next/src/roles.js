import { classes as defaultClasses, colleges as defaultColleges } from './data.js';

export const roles = [
  { id: 'school', label: '校级管理员', scopeLabel: '全校', classIds: [], collegeId: null },
  { id: 'college', label: '学院管理员', scopeLabel: '计算机学院', classIds: [], collegeId: 'computer' },
  { id: 'counselor', label: '辅导员', scopeLabel: '林老师 · 软件工程 2301 班、计算机科学 2302 班', classIds: ['software2301', 'cs2302'], collegeId: 'computer' },
];
export function scopeClasses(role, classes = defaultClasses) {
  if (role.id === 'school') return classes;
  if (role.id === 'college') return classes.filter(item => item.college === role.collegeId);
  if (role.id === 'counselor') return classes.filter(item => role.classIds.includes(item.id));
  return [];
}
export function scopeStudents(role, students, classes = defaultClasses) {
  const ids = new Set(scopeClasses(role, classes).map(item => item.id));
  return students.filter(student => ids.has(student.classId));
}
export function scopeInterviews(role, interviews, students, classes = defaultClasses) {
  const ids = new Set(scopeStudents(role, students, classes).map(student => student.id));
  return interviews.filter(item => ids.has(item.studentId));
}
export function scopeColleges(role, colleges = defaultColleges, classes = defaultClasses) {
  const ids = new Set(scopeClasses(role, classes).map(item => item.college));
  return colleges.filter(item => ids.has(item.id));
}
export function scopePlans(role, plans, classes = defaultClasses) {
  if (!roles.some(item => item.id === role.id)) return [];
  const allowedClasses = scopeClasses(role, classes);
  return plans.filter(plan => {
    if (role.id === 'school') return true;
    if (plan.status === 'draft' && plan.ownerRoleId !== role.id) return false;
    return plan.target.kind === 'all' || allowedClasses.some(item =>
      plan.target.kind === 'classes' ? plan.target.ids.includes(item.id) : plan.target.ids.includes(item.college)
    );
  });
}
export function canManagePlan(role, plan, classes = defaultClasses) {
  if (role.id === 'school') return true;
  if (plan.ownerRoleId && plan.ownerRoleId !== role.id) return false;
  if (plan.target.kind === 'all') return false;
  if (plan.target.kind === 'colleges') return role.id === 'college' && plan.target.ids.every(id => id === role.collegeId);
  const allowed = new Set(scopeClasses(role, classes).map(item => item.id));
  return plan.target.ids.length > 0 && plan.target.ids.every(id => allowed.has(id));
}
export function canUseSystem(role) {
  return role.id === 'school';
}
