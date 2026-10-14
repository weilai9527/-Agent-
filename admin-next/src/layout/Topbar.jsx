import { Menu, Search, ChevronRight } from 'lucide-react';
import { useApp } from '../context.jsx';
import { roles } from '../roles.js';
import { navigate } from '../router.js';

export default function Topbar({ title, onMenu, onSearch }) {
  const { role, changeRole } = useApp();
  return (
    <header className="topbar">
      <div className="breadcrumb">
        <button className="icon-button mobile-toggle" aria-label="打开导航" onClick={onMenu}><Menu size={20} /></button>
        <button className="breadcrumb-home" onClick={() => navigate('/overview')}>首页</button>
        <ChevronRight size={14} /><strong>{title}</strong>
      </div>
      <button className="global-search-trigger" onClick={onSearch} aria-label="全局搜索">
        <Search size={18} /><span>搜索学生、班级、计划或功能</span><kbd>⌘ / Ctrl K</kbd>
      </button>
      <label className="role-switch"><span>演示角色</span>
        <select aria-label="切换演示角色" value={role.id} onChange={event => {
          changeRole(event.target.value);
          navigate('/overview');
        }}>
          {roles.map(item => <option key={item.id} value={item.id}>{item.label}（{item.id === 'counselor' ? '林老师' : item.scopeLabel}）</option>)}
        </select>
      </label>
    </header>
  );
}
