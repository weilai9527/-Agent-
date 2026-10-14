import { useRef } from 'react';
import { GraduationCap, Building2, Settings2, CircleHelp, X } from 'lucide-react';
import brand from '../brand.js';
import { visibleNavigation } from '../navigation.js';
import { navigate } from '../router.js';
import { useApp } from '../context.jsx';
import { useFocusTrap } from '../components/Modal.jsx';

export default function Sidebar({ path, mobileOpen, onClose, onHelp }) {
  const { role } = useApp();
  const ref = useRef(null);
  useFocusTrap(ref, mobileOpen, onClose);
  function go(path) { onClose(); navigate(path); }
  return (
    <>
      {mobileOpen && <button className="nav-scrim" aria-label="关闭导航" onClick={onClose} tabIndex={-1} />}
      <aside className={'sidebar ' + (mobileOpen ? 'open' : '')} ref={ref} tabIndex={-1} role={mobileOpen ? 'dialog' : undefined} aria-modal={mobileOpen || undefined} aria-label="主导航">
        <button className="icon-button drawer-close" onClick={onClose} aria-label="关闭导航"><X size={20} /></button>
        <a className="brand" href="#/overview" onClick={onClose}>
          <span className="brand-symbol"><GraduationCap size={25} /></span>
          <span>{brand.name}<span className="brand-en">高校面试训练平台</span></span>
        </a>
        <div className="workspace">
          <Building2 size={19} /><span><strong>{brand.organization}</strong><small>演示管理空间</small></span>
        </div>
        <nav aria-label="功能导航">
          {visibleNavigation(role).map(group => <div className="nav-group" key={group.label}>
            <div className="nav-label">{group.label}</div>
            {group.items.map(item => {
              const Icon = item.icon;
              const active = path === item.path || path.startsWith(item.path + '/');
              return <button className={'nav-item ' + (active ? 'active' : '')} key={item.path} onClick={() => go(item.path)} aria-current={active ? 'page' : undefined}>
                <Icon size={18} /><span>{item.label}</span>
              </button>;
            })}
          </div>)}
        </nav>
        <div className="sidebar-bottom">
          <button className={'nav-item ' + (path === '/settings' ? 'active' : '')} onClick={() => go('/settings')}><Settings2 size={18} />个人设置</button>
          <button className="nav-item" onClick={() => { onClose(); onHelp(); }}><CircleHelp size={18} />使用帮助</button>
          <div className="sidebar-footer">{brand.name}<span>界面预览</span></div>
        </div>
      </aside>
    </>
  );
}
