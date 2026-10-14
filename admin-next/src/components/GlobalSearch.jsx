import { useState } from 'react';
import { useApp } from '../context.jsx';
import { visibleNavigation } from '../navigation.js';
import { navigate } from '../router.js';
import { formatDate } from '../utils.js';
import Modal from './Modal.jsx';

export default function GlobalSearch({ onClose, onHelp }) {
  const [query, setQuery] = useState('');
  const { students, classes, plans, interviews, role } = useApp();
  const contains = text => text.toLowerCase().includes(query.trim().toLowerCase());
  const groups = [
    { title: '学生', items: students.map(student => ({ label: student.name, detail: student.id + ' · ' + student.targetRole, path: '/students/' + student.id })) },
    { title: '班级', items: classes.map(item => ({ label: item.name, detail: item.counselor, path: '/students', query: { class: item.id } })) },
    { title: '训练计划', items: plans.map(plan => ({ label: plan.name, detail: plan.role, path: '/plans/' + plan.id })) },
    { title: '面试报告', items: interviews.map(item => ({ label: students.find(student => student.id === item.studentId)?.name + ' · ' + item.role, detail: item.id + ' · ' + formatDate(item.startedAt), path: '/interviews/' + item.id })) },
    { title: '功能', items: [
      ...visibleNavigation(role).flatMap(group => group.items).map(item => ({ label: item.label, detail: item.description ?? '打开功能页面', path: item.path })),
      { label: '个人设置', detail: '紧凑表格与机构信息', path: '/settings' },
      { label: '使用帮助', detail: '品牌、角色与数据说明', help: true },
    ] },
  ].map(group => ({ ...group, items: group.items.filter(item => contains(item.label + ' ' + item.detail)) }));
  return (
    <Modal title="全局搜索" onClose={onClose}>
      <label className="global-search-input"><input aria-label="全局搜索关键词" value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索当前角色范围内的数据与功能" data-autofocus /></label>
      <p className="search-guidance">当前范围：{role.scopeLabel} · 使用制表键选择，回车打开</p>
      <div className="global-search-results">
        {groups.filter(group => group.items.length).map(group => <section key={group.title}>
          <h3>{group.title}</h3>
          {group.items.map((item, index) => <button key={item.path + '-' + index} onClick={() => {
            onClose();
            if (item.help) onHelp();
            else navigate(item.path, item.query);
          }}>
            <div><strong>{item.label}</strong><small>{item.detail}</small></div>
          </button>)}
        </section>)}
        {!groups.some(group => group.items.length) && <p className="empty-state">未找到匹配结果</p>}
      </div>
    </Modal>
  );
}
