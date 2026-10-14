import { ChevronLeft, ChevronRight } from 'lucide-react';
import { PAGE_SIZE } from '../constants.js';

export default function Pagination({ total, page, onChange }) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  return (
    <nav className="pagination" aria-label="列表分页">
      <span>共 {total} 条 · 每页 {PAGE_SIZE} 条</span>
      <button aria-label="上一页" disabled={page <= 1} onClick={() => onChange(page - 1)}><ChevronLeft size={16} /></button>
      <span className="page-number">{page} / {pages}</span>
      <button aria-label="下一页" disabled={page >= pages} onClick={() => onChange(page + 1)}><ChevronRight size={16} /></button>
    </nav>
  );
}
