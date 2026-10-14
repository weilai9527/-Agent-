import { useEffect, useState } from 'react';
import { AppProvider, useApp } from './context.jsx';
import { useRoute } from './router.js';
import brand from './brand.js';
import { visibleNavigation } from './navigation.js';
import Sidebar from './layout/Sidebar.jsx';
import Topbar from './layout/Topbar.jsx';
import Modal from './components/Modal.jsx';
import GlobalSearch from './components/GlobalSearch.jsx';
import Toast from './components/Toast.jsx';
import PlaceholderPage from './components/PlaceholderPage.jsx';
import PageHeading from './components/PageHeading.jsx';
import OverviewPage from './pages/OverviewPage.jsx';
import StudentsPage from './pages/StudentsPage.jsx';
import StudentDetailPage from './pages/StudentDetailPage.jsx';
import InterviewsPage from './pages/InterviewsPage.jsx';
import ReportPage from './pages/ReportPage.jsx';
import ClassesPage from './pages/ClassesPage.jsx';
import PlansPage from './pages/PlansPage.jsx';
import PlanFormPage from './pages/PlanFormPage.jsx';
import PlanDetailPage from './pages/PlanDetailPage.jsx';
import EmploymentPage from './pages/EmploymentPage.jsx';
import SettingsPage from './pages/SettingsPage.jsx';
import MissingPage from './pages/MissingPage.jsx';
import './styles.css';
import './workspace.css';
import './refinements.css';

function Workspace() {
  const route = useRoute();
  const { role, compact, toast, notify } = useApp();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [dialog, setDialog] = useState(null);
  const parts = route.path.split('/').filter(Boolean);
  const entry = visibleNavigation(role).flatMap(group => group.items).find(item => item.path === '/' + parts[0]);
  const title = parts[0] === 'settings' ? '个人设置' : entry?.label ?? '页面提示';

  useEffect(() => { document.title = brand.name + ' · ' + title; }, [title]);
  useEffect(() => { window.scrollTo({ top: 0 }); }, [route.path]);
  useEffect(() => { setMobileOpen(false); setDialog(null); }, [role.id]);
  useEffect(() => {
    function shortcut(event) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setMobileOpen(false);
        setDialog('search');
      }
    }
    function resize() { if (window.innerWidth > 760) setMobileOpen(false); }
    window.addEventListener('keydown', shortcut);
    window.addEventListener('resize', resize);
    return () => {
      window.removeEventListener('keydown', shortcut);
      window.removeEventListener('resize', resize);
    };
  }, []);
  let content;
  if (parts.length === 1 && parts[0] === 'overview') content = <OverviewPage />;
  else if (parts.length === 1 && parts[0] === 'students') content = <StudentsPage route={route} />;
  else if (parts.length === 2 && parts[0] === 'students') content = <StudentDetailPage id={parts[1]} />;
  else if (parts.length === 1 && parts[0] === 'classes') content = <ClassesPage route={route} />;
  else if (parts.length === 1 && parts[0] === 'interviews') content = <InterviewsPage route={route} />;
  else if (parts.length === 2 && parts[0] === 'interviews') content = <ReportPage id={parts[1]} />;
  else if (parts.length === 1 && parts[0] === 'plans') content = <PlansPage route={route} />;
  else if (parts.length === 2 && parts[0] === 'plans' && parts[1] === 'new') content = <PlanFormPage />;
  else if (parts.length === 3 && parts[0] === 'plans' && parts[2] === 'edit') content = <PlanFormPage id={parts[1]} />;
  else if (parts.length === 2 && parts[0] === 'plans') content = <PlanDetailPage id={parts[1]} route={route} />;
  else if (parts.length === 1 && parts[0] === 'employment') content = <EmploymentPage route={route} />;
  else if (parts.length === 1 && parts[0] === 'settings') content = <SettingsPage />;
  else if (parts.length === 1 && entry?.points) content = <><PageHeading title={entry.label} /><PlaceholderPage page={entry} /></>;
  else content = <MissingPage />;
  return (
    <div className={'app ' + (compact ? 'compact' : '')}>
      <div inert={dialog ? true : undefined}>
        <Sidebar path={route.path} mobileOpen={mobileOpen} onClose={() => setMobileOpen(false)} onHelp={() => setDialog('help')} />
        <div className="main-shell" inert={mobileOpen ? true : undefined}>
          <Topbar title={title} onMenu={() => setMobileOpen(true)} onSearch={() => setDialog('search')} />
          <main id="main-content">
            <div key={role.id + route.path}>{content}</div>
            <footer className="page-footer"><span>{brand.name} · {brand.subtitle}</span><span>演示数据 · 仅保存在本机</span></footer>
          </main>
        </div>
      </div>
      {dialog === 'search' && <GlobalSearch onClose={() => setDialog(null)} onHelp={() => setDialog('help')} />}
      {dialog === 'help' && <Modal title={brand.name + '使用帮助'} onClose={() => setDialog(null)}>
        <div className="stack">
          <p>{brand.name}是高校面试训练管理平台，当前为纯前端演示原型。</p>
          <p>通过右上角“演示角色”切换全校、计算机学院或林老师负责的两个班级；页面和搜索随角色范围变化。</p>
          <p>学生档案提供面试历史与辅导跟进，训练计划支持草稿、发布和查看进度。数据保存在当前浏览器，清除本地存储后会重置。</p>
          <p>地址栏保存当前页面和筛选条件，支持刷新与浏览器后退。可通过快捷键打开搜索，按退出键关闭弹窗。</p>
          <p>就业去向为示意数据；功能占位页沿用现有管理端能力，尚未接入业务接口。</p>
        </div>
      </Modal>}
      <Toast message={toast} onClose={() => notify('')} />
    </div>
  );
}
export default function App() {
  return <AppProvider><Workspace /></AppProvider>;
}
