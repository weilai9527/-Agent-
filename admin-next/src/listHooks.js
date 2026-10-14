import { PAGE_SIZE } from './constants.js';
import { navigate } from './router.js';

export function useList(route, rows) {
  const page = Math.min(Math.max(1, Number.parseInt(route.query.page, 10) || 1), Math.max(1, Math.ceil(rows.length / PAGE_SIZE)));
  const change = patch => navigate(route.path, patch === null ? {} : { ...route.query, ...patch, page: undefined });
  const setPage = value => navigate(route.path, { ...route.query, page: value });
  return { page, change, setPage, pageRows: rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE) };
}
export function matchStudent(student, query, classes) {
  const classEntity = classes.find(item => item.id === student.classId);
  const text = [student.name, student.id, student.targetRole, classEntity?.name].join(' ').toLowerCase();
  return (!query.q || text.includes(query.q.toLowerCase())) &&
    (!query.college || classEntity?.college === query.college) &&
    (!query.class || student.classId === query.class);
}
