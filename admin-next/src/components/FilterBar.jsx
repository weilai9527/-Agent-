import { Search } from 'lucide-react';

export default function FilterBar({ query, onChange, colleges, classes, children, placeholder = '搜索姓名、学号或目标岗位' }) {
  return (
    <div className="filters">
      <label className="search-box">
        <Search size={17} aria-hidden="true" />
        <input aria-label="搜索列表" value={query.q ?? ''} placeholder={placeholder} onChange={event => onChange({ q: event.target.value })} />
      </label>
      {colleges && <select aria-label="筛选学院" value={query.college ?? ''} onChange={event => onChange({ college: event.target.value, class: '' })}>
        <option value="">全部可见学院</option>
        {colleges.map(college => <option value={college.id} key={college.id}>{college.name}</option>)}
      </select>}
      {classes && <select aria-label="筛选班级" value={query.class ?? ''} onChange={event => onChange({ class: event.target.value })}>
        <option value="">全部可见班级</option>
        {classes.filter(item => !query.college || item.college === query.college).map(item => <option value={item.id} key={item.id}>{item.name}</option>)}
      </select>}
      {children}
      <button className="text-button" onClick={() => onChange(null)}>重置筛选</button>
    </div>
  );
}
