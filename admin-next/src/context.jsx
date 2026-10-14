import { createContext, useContext, useState } from 'react';
import * as data from './data.js';
import { roles, scopeStudents, scopeClasses, scopeColleges, scopeInterviews, scopePlans, canManagePlan } from './roles.js';
import { STORAGE_KEYS } from './constants.js';
import { readStorage } from './utils.js';

const AppContext = createContext(null);
export function AppProvider({ children }) {
  const [roleId, setRoleId] = useState(() => readStorage(STORAGE_KEYS.role, 'school'));
  const [userPlans, setUserPlans] = useState(() => {
    const stored = readStorage(STORAGE_KEYS.plans, []);
    return Array.isArray(stored) ? stored.filter(plan => plan?.id && plan.target && Array.isArray(plan.target.ids)) : [];
  });
  const [localFollowUps, setLocalFollowUps] = useState(() => {
    const stored = readStorage(STORAGE_KEYS.followUps, []);
    return Array.isArray(stored) ? stored.filter(item => item?.studentId && item.updatedAt && ['pending', 'scheduled', 'done'].includes(item.status)) : [];
  });
  const [compact, setCompact] = useState(() => readStorage(STORAGE_KEYS.preferences, {}).compact === true);
  const [toast, notify] = useState('');
  const role = roles.find(item => item.id === roleId) ?? roles[0];
  const allPlans = [...data.plans.filter(plan => !userPlans.some(userPlan => userPlan.id === plan.id)), ...userPlans];
  const students = scopeStudents(role, data.students);
  const classes = scopeClasses(role);
  const colleges = scopeColleges(role);
  const interviews = scopeInterviews(role, data.interviews, data.students);
  const plans = scopePlans(role, allPlans);
  const studentIds = new Set(students.map(student => student.id));
  const followUps = [...data.followUps, ...localFollowUps].filter(item => studentIds.has(item.studentId));

  function persist(key, value, setter) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
      setter(value);
      return true;
    } catch {
      notify('浏览器无法保存数据，请检查本地存储空间或隐私设置。');
      return false;
    }
  }
  function changeRole(id) {
    setRoleId(id);
    try { localStorage.setItem(STORAGE_KEYS.role, JSON.stringify(id)); } catch { /* 角色切换仍可使用 */ }
  }
  function savePlan(plan) {
    if (!canManagePlan(role, plan)) {
      notify('目标范围超出当前演示角色权限。');
      return false;
    }
    const next = [...userPlans.filter(item => item.id !== plan.id), plan];
    const saved = persist(STORAGE_KEYS.plans, next, setUserPlans);
    if (saved) notify(plan.status === 'draft' ? '草稿已保存到本机。' : '训练计划已在原型内发布。');
    return saved;
  }
  function saveFollowUp(studentId, status, note) {
    if (!studentIds.has(studentId)) return false;
    const item = { id: crypto.randomUUID(), studentId, status, note: note.trim(), updatedAt: new Date().toISOString() };
    const saved = persist(STORAGE_KEYS.followUps, [...localFollowUps, item], setLocalFollowUps);
    if (saved) notify('辅导跟进已保存到本机。');
    return saved;
  }
  function saveCompact(value) {
    return persist(STORAGE_KEYS.preferences, { compact: value }, settings => setCompact(settings.compact));
  }
  return (
    <AppContext.Provider value={{ role, changeRole, students, classes, colleges, interviews, plans, followUps, compact, saveCompact, savePlan, saveFollowUp, toast, notify }}>
      {children}
    </AppContext.Provider>
  );
}
export function useApp() { return useContext(AppContext); }
