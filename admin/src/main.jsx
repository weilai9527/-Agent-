import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  ArrowUpDown,
  BarChart3,
  Bot,
  BookOpen,
  Building2,
  ChevronRight,
  CheckCircle2,
  ClipboardList,
  Copy,
  Download,
  Eye,
  FileText,
  Filter,
  GraduationCap,
  KeyRound,
  LayoutDashboard,
  Lightbulb,
  ListOrdered,
  LockKeyhole,
  LogOut,
  MousePointerClick,
  Network,
  Plus,
  RefreshCw,
  Rocket,
  Save,
  Search,
  School,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  UserCog,
  UserPlus,
  UsersRound,
  Upload,
  Wifi,
  X,
} from 'lucide-react';
import './styles.css';

const ADMIN_API_BASE_URL = import.meta.env.VITE_ADMIN_API_BASE_URL || 'http://127.0.0.1:3002';

const emptyAdminData = {
  metrics: [],
  candidates: [],
  interviews: [],
  reports: [],
  agents: [],
  auditLogs: [],
  adminUsers: [],
  admin: null,
  permissions: {
    canViewCandidates: false,
    canViewInterviews: false,
    canViewReports: true,
    canViewAgents: false,
    canViewConnectionLogs: false,
    canManageStudents: false,
    canManageOrganization: false,
    canManageCampus: false,
    canManageSettings: false,
    canViewAudit: false,
    canViewCatalog: false,
    canWriteCatalog: false,
    canImportCatalog: false,
    canPublishCatalog: false,
  },
  settings: {
    reportOpenaiModel: 'gpt-4o-mini',
    reportQwenModel: 'qwen-plus',
    reportProviderOrder: 'openai,qwen',
    reportTimeout: 60,
    reportRetries: 1,
    openaiRealtimeModel: '-',
    openaiVoice: '-',
    qwenTtsModel: '-',
    qwenTtsVoice: '-',
    qwenTtsRegion: 'beijing',
    qwenTtsWorkspaceId: '',
    qwenOmniModel: 'qwen3.5-omni-plus-realtime',
    qwenOmniVoice: 'Tina',
    qwenOmniRegion: 'beijing',
    qwenOmniWorkspaceId: '',
    qwenOmniEndpoint: '',
    reviewRule: '-',
  },
};

function adminApiUrl(path) {
  return `${ADMIN_API_BASE_URL.replace(/\/$/, '')}${path}`;
}

async function adminRequest(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const response = await fetch(adminApiUrl(path), {
    credentials: 'include',
    headers: { ...(isFormData ? {} : { 'Content-Type': 'application/json' }), ...options.headers },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const requestError = new Error(data.error || data.detail || '管理端后端请求失败。');
    requestError.status = response.status;
    throw requestError;
  }
  return data;
}

async function adminDownload(path, fallbackFilename) {
  const response = await fetch(adminApiUrl(path), { credentials: 'include' });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const requestError = new Error(data.error || data.detail || '文件下载失败。');
    requestError.status = response.status;
    throw requestError;
  }
  const blob = await response.blob();
  const disposition = response.headers.get('content-disposition') || '';
  const matchedFilename = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  const anchor = document.createElement('a');
  anchor.href = URL.createObjectURL(blob);
  anchor.download = matchedFilename || fallbackFilename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(anchor.href);
}

const navItems = [
  { key: 'dashboard', label: '工作台', icon: LayoutDashboard, group: '工作台' },
  { key: 'guide', label: '使用流程指引', icon: ListOrdered, group: '工作台' },
  { key: 'interviews', label: '训练记录', icon: ClipboardList, permission: 'canViewInterviews', group: '工作台' },
  { key: 'reports', label: '报告质检', icon: FileText, permission: 'canViewReports', group: '工作台' },
  { key: 'organization', label: '学生', icon: School, permission: 'canManageStudents', group: '学生成长' },
  { key: 'organizationConfig', label: '组织', icon: Network, permission: 'canManageOrganization', group: '学生成长' },
  { key: 'catalog', label: '岗位知识库', icon: BookOpen, permission: 'canViewCatalog', group: '训练内容' },
  { key: 'agents', label: '面试模型配置', icon: Bot, permission: 'canViewAgents', group: '训练内容' },
  { key: 'connectionLogs', label: '连接日志', icon: Wifi, permission: 'canViewConnectionLogs', group: '系统' },
  { key: 'permission', label: '权限管理', icon: ShieldCheck, group: '系统' },
  { key: 'settings', label: '系统管理', icon: Settings, permission: 'canManageSettings', group: '系统' },
];

const roleLabels = {
  super_admin: '超级管理员',
};

const statusTone = {
  正常: 'green',
  观察: 'amber',
  进行中: 'blue',
  已完成: 'green',
  草稿: 'gray',
  待抽检: 'blue',
  已复核: 'green',
  待复核: 'blue',
  复核未通过: 'red',
  需要复核: 'red',
  启用: 'green',
  已禁用: 'gray',
  未归班: 'gray',
  尚未训练: 'gray',
  训练中: 'blue',
  表现稳定: 'green',
  重点关注: 'red',
};

function AdminLogin({ onAuthenticated }) {
  const [form, setForm] = useState({ email: '', password: '' });
  const [submitting, setSubmitting] = useState(false);
  const [loginError, setLoginError] = useState('');

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setLoginError('');
    try {
      const data = await adminRequest('/api/admin/auth/login', {
        method: 'POST',
        body: JSON.stringify(form),
      });
      onAuthenticated(data.admin);
    } catch (requestError) {
      setLoginError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="admin-login-page">
      <form className="admin-login-card" onSubmit={handleSubmit}>
        <div className="admin-login-brand"><ShieldCheck size={28} /></div>
        <header>
          <span>Management Console</span>
          <h1>管理员登录</h1>
          <p>登录后可以查看学生成长、训练报告和系统配置。</p>
        </header>
        <label>
          <span>管理员邮箱</span>
          <input
            type="email"
            autoComplete="username"
            value={form.email}
            onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))}
            placeholder="admin@example.com"
            required
          />
        </label>
        <label>
          <span>密码</span>
          <input
            type="password"
            autoComplete="current-password"
            value={form.password}
            onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
            placeholder="请输入管理员密码"
            required
          />
        </label>
        {loginError && <p className="admin-login-error">{loginError}</p>}
        <button className="primary-button" type="submit" disabled={submitting}>
          {submitting ? '登录中...' : '进入管理端'}
        </button>
        <small>首次使用请先在管理后端环境变量中配置管理员初始化账号。</small>
      </form>
    </main>
  );
}

function StatusBadge({ children }) {
  return <span className={`status-badge ${statusTone[children] || 'blue'}`}>{children}</span>;
}

function EmptyState({ text = '暂无数据' }) {
  return <div className="empty-state">{text}</div>;
}

function SectionCard({ title, icon, action, children, className = '' }) {
  return (
    <section className={`section-card ${className}`.trim()}>
      <header>
        <div>
          {icon}
          <h2>{title}</h2>
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}

function CompactId({ value }) {
  const [copied, setCopied] = useState(false);
  const text = String(value || '-');
  const compact = text.length > 18 ? `${text.slice(0, 8)}…${text.slice(-5)}` : text;

  const copyId = async (event) => {
    event.stopPropagation();
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  };

  return (
    <span className="compact-id" title={text}>
      <code>{compact}</code>
      <button type="button" onClick={copyId} aria-label={`复制 ${text}`} title="复制完整 ID">
        {copied ? <CheckCircle2 size={14} /> : <Copy size={14} />}
      </button>
    </span>
  );
}

function AdminTable({ columns, rows, allRows, onView, sort, onSort }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} className={column.className || ''}>
                {column.sortable === false ? column.label : (
                  <button type="button" className={sort.key === column.key ? 'active' : ''} onClick={() => onSort(column.key)}>
                    {column.label}
                    <ArrowUpDown size={13} />
                  </button>
                )}
              </th>
            ))}
            <th aria-label="操作" />
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={columns.length + 1}>
                <EmptyState text="没有符合当前条件的数据" />
              </td>
            </tr>
          )}
          {rows.map((row) => (
            <tr
              key={row.id || row.name}
              className="data-row"
              tabIndex={0}
              onClick={() => onView?.(row, allRows)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  onView?.(row, allRows);
                }
              }}
            >
              {columns.map((column) => (
                <td key={column.key} className={column.className || ''}>{column.render ? column.render(row) : row[column.key] ?? '-'}</td>
              ))}
              <td className="row-action">
                <button type="button" tabIndex={-1} onClick={(event) => { event.stopPropagation(); onView?.(row, allRows); }} aria-label="查看详情">
                  <ChevronRight size={16} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DataWorkspace({
  title,
  icon,
  columns,
  rows,
  onView,
  query,
  onQueryChange,
  filterKey,
  filterLabel = '全部状态',
  presetFilter = '',
}) {
  const [filterValue, setFilterValue] = useState(presetFilter);
  const [sort, setSort] = useState({ key: '', direction: 'asc' });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(12);

  useEffect(() => {
    setFilterValue(presetFilter || '');
    setPage(1);
  }, [presetFilter]);

  const filterOptions = useMemo(
    () => [...new Set(rows.map((row) => row[filterKey]).filter(Boolean))],
    [rows, filterKey],
  );

  const filteredRows = useMemo(() => {
    const keyword = String(query || '').trim().toLowerCase();
    const filtered = rows.filter((row) => {
      const matchesFilter = !filterValue || row[filterKey] === filterValue;
      const searchableText = Object.values(row).filter((value) => typeof value !== 'object').join(' ').toLowerCase();
      return matchesFilter && (!keyword || searchableText.includes(keyword));
    });
    if (!sort.key) return filtered;
    return [...filtered].sort((left, right) => {
      const leftValue = left[sort.key] ?? '';
      const rightValue = right[sort.key] ?? '';
      const numericLeft = Number(leftValue);
      const numericRight = Number(rightValue);
      const comparison = Number.isFinite(numericLeft) && Number.isFinite(numericRight) && leftValue !== '' && rightValue !== ''
        ? numericLeft - numericRight
        : String(leftValue).localeCompare(String(rightValue), 'zh-CN', { numeric: true });
      return sort.direction === 'asc' ? comparison : -comparison;
    });
  }, [rows, query, filterKey, filterValue, sort]);

  useEffect(() => {
    setPage(1);
  }, [query, filterValue, pageSize]);

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const startIndex = (safePage - 1) * pageSize;
  const visibleRows = filteredRows.slice(startIndex, startIndex + pageSize);
  const hasFilters = Boolean(query || filterValue);

  const handleSort = (key) => {
    setSort((current) => current.key === key
      ? { key, direction: current.direction === 'asc' ? 'desc' : 'asc' }
      : { key, direction: 'asc' });
  };

  const resetFilters = () => {
    setFilterValue('');
    onQueryChange?.('');
    setSort({ key: '', direction: 'asc' });
  };

  return (
    <SectionCard
      title={title}
      icon={icon}
      className="data-workspace"
      action={<span className="record-count">{filteredRows.length} 条结果</span>}
    >
      <div className="table-toolbar">
        <div className="table-filter-group">
          <Filter size={15} />
          <select value={filterValue} onChange={(event) => setFilterValue(event.target.value)} aria-label={filterLabel}>
            <option value="">{filterLabel}</option>
            {filterOptions.map((option) => <option value={option} key={option}>{option}</option>)}
          </select>
          {hasFilters && <button type="button" className="clear-filter" onClick={resetFilters}>清空筛选</button>}
        </div>
        <span className="data-scope-note">列表内容来自当前管理端数据范围</span>
      </div>
      <AdminTable columns={columns} rows={visibleRows} allRows={filteredRows} onView={onView} sort={sort} onSort={handleSort} />
      <footer className="table-pagination">
        <span>
          {filteredRows.length === 0 ? '0' : `${startIndex + 1}–${Math.min(startIndex + pageSize, filteredRows.length)}`} / {filteredRows.length}
        </span>
        <label>
          每页
          <select value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))}>
            {[12, 20, 50].map((value) => <option value={value} key={value}>{value}</option>)}
          </select>
        </label>
        <div>
          <button type="button" disabled={safePage <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))} aria-label="上一页"><ArrowLeft size={15} /></button>
          <span>{safePage} / {totalPages}</span>
          <button type="button" disabled={safePage >= totalPages} onClick={() => setPage((current) => Math.min(totalPages, current + 1))} aria-label="下一页"><ArrowRight size={15} /></button>
        </div>
      </footer>
    </SectionCard>
  );
}

function DetailDrawer({ detail, loading, error, onClose, onReview, canReview, onMove, position, onRevealTemporaryPassword, onResetStudentPassword }) {
  const isOpen = Boolean(detail || loading || error);

  useEffect(() => {
    if (!isOpen) return undefined;
    const previousOverflow = document.body.style.overflow;
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onClose();
    };
    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;
  const title = detail?.title || '详情';
  const rows = detail?.rows || [];
  const blocks = detail?.blocks || [];
  return (
    <div className="drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="detail-drawer" role="dialog" aria-modal="true" aria-label={title}>
        <header>
          <div>
            <span>记录详情</span>
            <h2>{title}</h2>
          </div>
          <div className="drawer-header-actions">
            {position.total > 1 && (
              <div className="drawer-stepper">
                <button type="button" disabled={!position.hasPrevious || loading} onClick={() => onMove(-1)} aria-label="上一条"><ArrowLeft size={16} /></button>
                <span>{position.current} / {position.total}</span>
                <button type="button" disabled={!position.hasNext || loading} onClick={() => onMove(1)} aria-label="下一条"><ArrowRight size={16} /></button>
              </div>
            )}
            <button type="button" onClick={onClose} aria-label="关闭详情"><X size={18} /></button>
          </div>
        </header>
        {loading && <div className="drawer-loading"><RefreshCw size={18} className="spin" /> 正在读取详情</div>}
        {error && <div className="page-message error">{error}</div>}
        {!loading && !error && (
          <div className="detail-body">
            <div className="detail-grid">
              {rows.map((item) => (
                <div key={item.label}>
                  <span>{item.label}</span>
                  <strong>{item.value || '-'}</strong>
                </div>
              ))}
            </div>
            {blocks.map((block) => (
              <section className="detail-block" key={block.title}>
                <h3>{block.title}</h3>
                {block.items?.length > 0 ? (
                  <div className="detail-list">
                    {block.items.map((item, index) => (
                      <article key={item.id || `${block.title}-${index}`}>
                        <strong>{item.title}</strong>
                        <span>{item.meta}</span>
                        <p>{item.text}</p>
                      </article>
                    ))}
                  </div>
                ) : <p>{block.text || '暂无内容'}</p>}
              </section>
            ))}
          </div>
        )}
        {detail?.type === 'report' && canReview && !error && (
          <footer className="detail-actions">
            <span>复核结果会立即写入系统并记录操作人</span>
            <div>
              <button type="button" className="danger" disabled={loading} onClick={() => onReview('rejected')}>标记未通过</button>
              <button type="button" disabled={loading} onClick={() => onReview('approved')}>通过复核</button>
            </div>
          </footer>
        )}
        {detail?.type === 'candidate' && !error && (
          <footer className="detail-actions student-password-actions">
            <span>
              {detail.temporaryPassword
                ? <>当前临时密码：<code>{detail.temporaryPassword}</code></>
                : detail.mustChangePassword
                  ? '学生首次登录后必须修改临时密码'
                  : '该学生已完成首次改密，临时密码不可查看'}
            </span>
            <div>
              {detail.canViewTemporaryPassword && (
                <button type="button" disabled={loading} onClick={onRevealTemporaryPassword}><Eye size={15} />查看临时密码</button>
              )}
              <button type="button" className="danger" disabled={loading} onClick={onResetStudentPassword}><KeyRound size={15} />重置临时密码</button>
            </div>
          </footer>
        )}
      </section>
    </div>
  );
}

function compactText(value, maxLength = 360) {
  const text = String(value || '').trim();
  if (!text) return '-';
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

function formatDetail(type, payload, fallbackRow) {
  if (type === 'candidate') {
    const item = payload.candidate || fallbackRow;
    return {
      type: 'candidate',
      id: item.id || fallbackRow.id,
      title: `学生 · ${item.name || item.nickname || fallbackRow.name}`,
      mustChangePassword: Boolean(item.must_change_password ?? fallbackRow.canViewTemporaryPassword),
      canViewTemporaryPassword: Boolean(item.can_view_temp_password ?? fallbackRow.canViewTemporaryPassword),
      rows: [
        { label: '学号', value: item.student_no || item.studentNo },
        { label: '学院', value: item.college },
        { label: '班级', value: item.class_name || item.className },
        { label: '辅导员', value: item.counselor },
        { label: '学生状态', value: item.student_status },
        { label: '状态', value: item.status },
        { label: '激活状态', value: (item.must_change_password ?? fallbackRow.canViewTemporaryPassword) ? '待首次改密' : ((item.student_no || item.studentNo) ? '已激活' : '待绑定学号') },
        { label: '目标岗位', value: item.target_role || item.role },
        { label: '最后登录', value: item.last_login_at || item.lastLogin },
      ],
      blocks: [
        { title: '技能标签', text: item.skills },
        { title: '项目经历', text: compactText(item.project_experience, 900) },
        { title: '简历文本', text: compactText(item.resume_text, 900) },
      ],
    };
  }
  if (type === 'interview') {
    const interview = payload.interview || fallbackRow;
    return {
      type: 'interview',
      id: interview.id || fallbackRow.id,
      title: `训练 · ${interview.target_role || fallbackRow.role}`,
      rows: [
        { label: '候选人', value: interview.candidate },
        { label: '邮箱', value: interview.candidate_email },
        { label: '训练类型', value: interview.interview_type || fallbackRow.type },
        { label: '状态', value: interview.status || fallbackRow.status },
        { label: '难度', value: interview.difficulty },
        { label: '公司场景', value: interview.company_context },
        { label: '开始时间', value: interview.started_at },
        { label: '完成时间', value: interview.completed_at },
      ],
      blocks: [
        {
          title: 'Agent 队列',
          items: (payload.agents || []).map((agent) => ({
            id: agent.id,
            title: agent.agent_name,
            meta: `${agent.agent_type} · ${agent.status}`,
            text: agent.agent_role,
          })),
        },
        {
          title: '最近消息',
          items: (payload.messages || []).slice(-10).map((message) => ({
            id: message.id,
            title: message.agent_name || message.sender_type,
            meta: `${message.message_type} · ${message.created_at}`,
            text: compactText(message.content, 260),
          })),
        },
      ],
    };
  }
  if (type === 'report') {
    const report = payload.report || fallbackRow;
    return {
      type: 'report',
      id: report.id || fallbackRow.id,
      title: `报告 · ${report.candidate || fallbackRow.candidate}`,
      rows: [
        { label: '候选人', value: report.candidate },
        { label: '邮箱', value: report.candidate_email },
        { label: '目标岗位', value: report.target_role || report.role },
        { label: '总分', value: report.total_score || report.score },
        { label: '等级', value: report.grade },
        { label: '准备建议', value: report.pass_recommendation || report.recommendation },
        { label: '生成来源', value: report.fallback ? `本地兜底 · ${report.model || 'rules-v1'}` : `${report.provider || '-'} · ${report.model || '-'}` },
        { label: '复核状态', value: report.review_status || report.reviewStatus || 'pending' },
        { label: '生成时间', value: report.created_at || report.createdAt },
      ],
      blocks: [
        { title: '报告摘要', text: report.summary },
        { title: '提升建议', text: report.suggestions },
        { title: 'Agent 反馈', text: compactText(report.agent_feedback, 900) },
        { title: '时间线复盘', text: compactText(report.timeline_review, 900) },
      ],
    };
  }
  const agent = payload.agent || fallbackRow;
  return {
    type: 'agent',
    id: agent.agent_name || agent.name,
    title: `Agent · ${agent.agent_name || agent.name}`,
    rows: [
      { label: '类型', value: agent.agent_type || agent.type },
      { label: '状态', value: agent.status || fallbackRow.status },
      { label: '使用次数', value: agent.usage_count || fallbackRow.usageCount },
    ],
    blocks: [
      { title: '角色说明', text: agent.agent_role || fallbackRow.focus },
      { title: '面试策略', text: agent.strategy },
      {
        title: '近期使用',
        items: (payload.recentUsage || []).map((item) => ({
          id: item.interview_id,
          title: item.candidate,
          meta: `${item.target_role} · ${item.status}`,
          text: item.updated_at,
        })),
      },
    ],
  };
}

function Dashboard({ data, admin, onNavigate, onView }) {
  const reviewCount = data.reports.filter((report) => report.reviewStatus === '待复核').length;
  const runningCount = data.interviews.filter((interview) => interview.status === '进行中').length;
  const lowScoreCount = data.reports.filter((report) => Number(report.score) < 70).length;
  const averageScore = data.reports.length
    ? Math.round(data.reports.reduce((sum, item) => sum + Number(item.score || 0), 0) / data.reports.length)
    : 0;
  const highScoreCount = data.reports.filter((item) => Number(item.score) >= 85).length;
  const mediumScoreCount = data.reports.filter((item) => Number(item.score) >= 70 && Number(item.score) < 85).length;
  const queueReports = data.reports.filter((report) => report.reviewStatus === '待复核').slice(0, 5);
  const queueInterviews = data.interviews.filter((interview) => interview.status === '进行中').slice(0, 5);
  const queueItems = queueReports.length ? queueReports : queueInterviews;
  const queueType = queueReports.length ? 'report' : 'interview';

  const metrics = [
    { label: '待复核报告', value: reviewCount, note: '进入审核队列', tone: reviewCount ? 'red' : 'green', view: 'reports', filter: '待复核' },
    ...(data.permissions?.canViewInterviews ? [{ label: '进行中面试', value: runningCount, note: '查看实时进度', tone: 'blue', view: 'interviews', filter: '进行中' }] : []),
    { label: '低分报告', value: lowScoreCount, note: '低于 70 分', tone: lowScoreCount ? 'amber' : 'green', view: 'reports', filter: '' },
  ];

  return (
    <div className="dashboard-page">
      <section className="dashboard-welcome">
        <div>
          <span>{roleLabels[admin?.role] || '管理员'}工作台</span>
          <h2>先处理今天最需要关注的事项</h2>
          <p>指标卡和任务队列都可以直接进入对应记录。</p>
        </div>
        <span className="connection-pill"><i /> 服务正常</span>
      </section>

      <section className="metric-grid">
        {metrics.map((item) => (
          <button className={`metric-card ${item.tone}`} key={item.label} type="button" onClick={() => onNavigate(item.view, item.filter)}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
            <small>{item.note}<ChevronRight size={14} /></small>
          </button>
        ))}
      </section>

      <section className="content-grid">
        <SectionCard
          title="优先处理"
          icon={<Activity size={18} />}
          action={<button className="section-link" type="button" onClick={() => onNavigate(queueType === 'report' ? 'reports' : 'interviews', queueType === 'report' ? '待复核' : '进行中')}>查看全部 <ChevronRight size={14} /></button>}
        >
          <div className="task-queue">
            {queueItems.length === 0 && <EmptyState text="当前没有需要立即处理的任务" />}
            {queueItems.map((item) => (
              <button type="button" key={item.id} onClick={() => onView(queueType, item, queueItems)}>
                <span className={`task-dot ${queueType === 'report' ? 'amber' : 'blue'}`} />
                <span>
                  <strong>{item.candidate || item.name || '未命名记录'}</strong>
                  <small>{item.role || item.target_role || '-'} · {queueType === 'report' ? `${item.score || 0} 分` : item.status}</small>
                </span>
                <ChevronRight size={16} />
              </button>
            ))}
          </div>
        </SectionCard>

        <SectionCard title="报告质量概览" icon={<BarChart3 size={18} />}>
          <div className="score-overview">
            {data.reports.length === 0 ? <EmptyState text="生成报告后展示统计" /> : (
              <>
                <div className="average-score">
                  <div><span>平均分</span><strong>{averageScore}<small>/100</small></strong></div>
                  <div className="bar-track"><span style={{ width: `${Math.min(averageScore, 100)}%` }} /></div>
                </div>
                <div className="distribution-grid">
                  <div><strong>{highScoreCount}</strong><span>优秀（85+）</span></div>
                  <div><strong>{mediumScoreCount}</strong><span>合格（70–84）</span></div>
                  <div><strong>{lowScoreCount}</strong><span>需关注（&lt;70）</span></div>
                </div>
              </>
            )}
          </div>
        </SectionCard>
      </section>
    </div>
  );
}

function InterviewsPage({ data, onView, query, onQueryChange, presetFilter }) {
  const columns = [
    { key: 'id', label: '训练 ID', sortable: false, render: (row) => <CompactId value={row.id} /> },
    { key: 'candidate', label: '学生' },
    { key: 'role', label: '目标岗位' },
    { key: 'type', label: '训练类型' },
    { key: 'status', label: '状态', render: (row) => <StatusBadge>{row.status}</StatusBadge> },
    { key: 'agents', label: 'Agent' },
    { key: 'messages', label: '消息数' },
    { key: 'updatedAt', label: '更新时间' },
  ];
  return <DataWorkspace title="模拟训练记录" icon={<ClipboardList size={18} />} columns={columns} rows={data.interviews} query={query} onQueryChange={onQueryChange} filterKey="status" filterLabel="全部训练状态" presetFilter={presetFilter} onView={(row, rows) => onView('interview', row, rows)} />;
}

function ReportsPage({ data, onView, query, onQueryChange, presetFilter }) {
  const columns = [
    { key: 'id', label: '报告 ID', sortable: false, render: (row) => <CompactId value={row.id} /> },
    { key: 'candidate', label: '学生' },
    { key: 'role', label: '目标岗位' },
    { key: 'score', label: '总分', render: (row) => <strong className={Number(row.score) < 70 ? 'score-alert' : ''}>{row.score ?? '-'}</strong> },
    { key: 'grade', label: '等级' },
    { key: 'recommendation', label: '准备建议' },
    { key: 'reviewStatus', label: '复核状态', render: (row) => <StatusBadge>{row.reviewStatus}</StatusBadge> },
    { key: 'createdAt', label: '生成时间' },
  ];
  return <DataWorkspace title="成长报告质检" icon={<FileText size={18} />} columns={columns} rows={data.reports} query={query} onQueryChange={onQueryChange} filterKey="reviewStatus" filterLabel="全部质检状态" presetFilter={presetFilter} onView={(row, rows) => onView('report', row, rows)} />;
}

function AgentsPage({ data, onView, query, onQueryChange, presetFilter }) {
  const columns = [
    { key: 'name', label: 'Agent 名称' },
    { key: 'type', label: '类型' },
    { key: 'focus', label: '考察重点' },
    { key: 'usageCount', label: '使用次数' },
    { key: 'status', label: '状态', render: (row) => <StatusBadge>{row.status}</StatusBadge> },
  ];
  return (
    <section className="content-grid">
      <DataWorkspace title="AI 陪练角色" icon={<Bot size={18} />} columns={columns} rows={data.agents} query={query} onQueryChange={onQueryChange} filterKey="status" filterLabel="全部角色状态" presetFilter={presetFilter} onView={(row, rows) => onView('agent', row, rows)} />
      <SectionCard title="评分维度配置" icon={<SlidersHorizontal size={18} />}>
        <div className="config-list">
          {['技术深度', '表达清晰度', '业务理解', '架构思维', '稳定抗压'].map((item) => (
            <div key={item}><span>{item}</span><b>权重 20%</b></div>
          ))}
        </div>
      </SectionCard>
    </section>
  );
}

const connectionEventLabels = {
  call_start_requested: '开始连接',
  microphone_acquired: '麦克风已获取',
  ice_gathering_state_changed: 'ICE 收集状态',
  ice_connection_state_changed: 'ICE 连接状态',
  local_offer_ready: '本地 Offer 就绪',
  sdp_answer_received: '收到 SDP Answer',
  remote_description_applied: '远端描述已应用',
  connection_state_changed: '连接状态变化',
  data_channel_opened: '数据通道已打开',
  data_channel_closed: '数据通道已关闭',
  data_channel_error: '数据通道错误',
  session_created: '会话已创建',
  session_update_sent: '会话配置已发送',
  session_updated: '会话配置已生效',
  remote_audio_track_received: '收到远端音轨',
  remote_audio_playing: '远端音频播放中',
  remote_audio_play_failed: '远端音频播放失败',
  upstream_error: '千问上游错误',
  call_start_failed: '连接启动失败',
  call_stopped: '连接已停止',
};

const connectionLevelLabels = {
  info: '正常',
  warning: '警告',
  error: '错误',
};

function RegistrationsPage() {
  const [registrations, setRegistrations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState('');
  const [notice, setNotice] = useState('');
  const [query, setQuery] = useState('');
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState(null);
  const [deletingId, setDeletingId] = useState('');

  const loadRegistrations = async () => {
    setLoading(true);
    setPageError('');
    try {
      const data = await adminRequest('/api/admin/student-registrations');
      setRegistrations(data.registrations || []);
    } catch (requestError) {
      setPageError(requestError.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadRegistrations();
  }, []);

  const handleImport = async (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = '';
    if (!file) return;
    setImporting(true);
    setPageError('');
    setNotice('');
    setImportResult(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const data = await adminRequest('/api/admin/student-registrations/import', {
        method: 'POST',
        body: formData,
      });
      setImportResult(data);
      setNotice(`导入完成：新增 ${data.imported} 人，更新 ${data.updated} 人，跳过 ${data.skipped.length} 行`);
      await loadRegistrations();
    } catch (requestError) {
      setPageError(requestError.message);
    } finally {
      setImporting(false);
    }
  };

  const handleDelete = async (item) => {
    if (!window.confirm(`确认删除 ${item.name}（${item.studentNo}）的注册信息？该学生将无法再登录候选人端。`)) return;
    setDeletingId(item.id);
    setPageError('');
    setNotice('');
    try {
      await adminRequest(`/api/admin/student-registrations/${item.id}`, { method: 'DELETE' });
      setNotice(`已删除 ${item.name}（${item.studentNo}）的注册信息`);
      setRegistrations((current) => current.filter((entry) => entry.id !== item.id));
    } catch (requestError) {
      setPageError(requestError.message);
    } finally {
      setDeletingId('');
    }
  };

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return registrations;
    return registrations.filter((item) => [item.studentNo, item.name, item.importedBy]
      .join(' ').toLowerCase().includes(keyword));
  }, [registrations, query]);

  const activatedCount = useMemo(() => registrations.filter((item) => item.activated).length, [registrations]);

  return (
    <div className="registrations-page">
      <section className="connection-log-summary">
        <article><span>已导入学生</span><strong>{registrations.length}</strong></article>
        <article><span>已激活账号</span><strong>{activatedCount}</strong></article>
        <article><span>待激活</span><strong>{registrations.length - activatedCount}</strong></article>
      </section>

      <SectionCard
        title="学生注册"
        icon={<UserPlus size={18} />}
        action={<span className="record-count">候选人端凭学号 + 姓名登录</span>}
      >
        <div className="connection-log-toolbar">
          <label>
            <Search size={15} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索学号或姓名" />
          </label>
          <label className={`secondary-button import-button${importing ? ' disabled' : ''}`}>
            <Upload size={15} className={importing ? 'spin' : ''} />
            {importing ? '正在导入…' : '导入文档（CSV / Excel）'}
            <input type="file" accept=".csv,.xlsx,.xlsm" onChange={handleImport} disabled={importing} hidden />
          </label>
          <button className="secondary-button" type="button" onClick={loadRegistrations} disabled={loading}>
            <RefreshCw size={15} className={loading ? 'spin' : ''} />刷新
          </button>
        </div>

        <p className="form-hint">文档需包含「学号」「姓名」两列（支持中文或 student_no / name 列名），候选人端凭学号与姓名登录。</p>

        {pageError && <div className="page-message error"><AlertCircle size={18} />{pageError}</div>}
        {notice && <div className="page-message success"><CheckCircle2 size={18} />{notice}</div>}

        {importResult && importResult.skipped.length > 0 && (
          <div className="page-message warning">
            <AlertCircle size={18} />
            <div>
              <strong>以下 {importResult.skipped.length} 行被跳过：</strong>
              <ul>
                {importResult.skipped.map((item) => (
                  <li key={item.row}>第 {item.row} 行 {item.name || item.studentNo || '（空行）'}：{item.reason}</li>
                ))}
              </ul>
            </div>
          </div>
        )}

        {!pageError && loading && <div className="page-message loading-state"><RefreshCw size={18} className="spin" />正在读取注册信息</div>}
        {!pageError && !loading && filtered.length === 0 && (
          <div className="page-message">{query ? '没有匹配的注册信息。' : '尚未导入学生注册信息，请先导入文档。'}</div>
        )}
        {!pageError && !loading && filtered.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>学号</th>
                  <th>姓名</th>
                  <th>状态</th>
                  <th>导入人</th>
                  <th>导入时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((item) => (
                  <tr key={item.id}>
                    <td>{item.studentNo}</td>
                    <td>{item.name}</td>
                    <td><span className={`status-badge ${item.activated ? 'green' : 'gray'}`}>{item.activated ? '已激活' : '待激活'}</span></td>
                    <td>{item.importedBy || '-'}</td>
                    <td>{item.createdAt ? item.createdAt.slice(0, 19).replace('T', ' ') : '-'}</td>
                    <td>
                      <button
                        className="secondary-button danger"
                        type="button"
                        disabled={deletingId === item.id}
                        onClick={() => handleDelete(item)}
                      >
                        删除
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>
    </div>
  );
}

function ConnectionLogsPage() {
  const [payload, setPayload] = useState({
    logs: [],
    summary: { total: 0, errors: 0, warnings: 0, sessions: 0, latestAt: '-' },
    retentionDays: 14,
  });
  const [loading, setLoading] = useState(true);
  const [logsError, setLogsError] = useState('');
  const [query, setQuery] = useState('');
  const [level, setLevel] = useState('');
  const [eventType, setEventType] = useState('');
  const [selected, setSelected] = useState(null);

  const loadLogs = async () => {
    setLoading(true);
    setLogsError('');
    try {
      const data = await adminRequest('/api/admin/connection-logs?limit=500');
      setPayload(data);
      setSelected((current) => current
        ? data.logs.find((item) => item.id === current.id) || null
        : null);
    } catch (requestError) {
      setLogsError(requestError.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadLogs();
  }, []);

  const eventTypes = useMemo(
    () => [...new Set(payload.logs.map((item) => item.eventType).filter(Boolean))].sort(),
    [payload.logs],
  );
  const filteredLogs = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return payload.logs.filter((item) => {
      if (level && item.level !== level) return false;
      if (eventType && item.eventType !== eventType) return false;
      if (!keyword) return true;
      return [
        item.candidate,
        item.targetRole,
        item.sessionId,
        item.interviewId,
        item.eventType,
        item.message,
      ].join(' ').toLowerCase().includes(keyword);
    });
  }, [payload.logs, query, level, eventType]);

  return (
    <div className="connection-logs-page">
      <section className="connection-log-summary">
        <article><span>近 24 小时事件</span><strong>{payload.summary.total}</strong></article>
        <article className={payload.summary.errors ? 'danger' : ''}><span>错误</span><strong>{payload.summary.errors}</strong></article>
        <article className={payload.summary.warnings ? 'warning' : ''}><span>警告</span><strong>{payload.summary.warnings}</strong></article>
        <article><span>连接会话</span><strong>{payload.summary.sessions}</strong></article>
      </section>

      <SectionCard
        title="连接日志"
        icon={<Wifi size={18} />}
        action={<span className="record-count">自动保留 {payload.retentionDays} 天</span>}
        className="connection-log-card"
      >
        <div className="connection-log-toolbar">
          <label>
            <Search size={15} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索学生、面试、会话或错误信息" />
          </label>
          <select value={level} onChange={(event) => setLevel(event.target.value)}>
            <option value="">全部级别</option>
            <option value="error">错误</option>
            <option value="warning">警告</option>
            <option value="info">正常</option>
          </select>
          <select value={eventType} onChange={(event) => setEventType(event.target.value)}>
            <option value="">全部事件</option>
            {eventTypes.map((value) => <option key={value} value={value}>{connectionEventLabels[value] || value}</option>)}
          </select>
          <button className="secondary-button" type="button" onClick={loadLogs} disabled={loading}>
            <RefreshCw size={15} className={loading ? 'spin' : ''} />刷新
          </button>
        </div>

        {logsError && <div className="page-message error"><AlertCircle size={18} />{logsError}</div>}
        {!logsError && loading && <div className="page-message loading-state"><RefreshCw size={18} className="spin" />正在读取连接日志</div>}
        {!logsError && !loading && (
          <div className="connection-log-table table-wrap">
            <table>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>级别</th>
                  <th>事件</th>
                  <th>学生 / 岗位</th>
                  <th>连接状态</th>
                  <th>ICE 状态</th>
                  <th>会话</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filteredLogs.map((item) => (
                  <tr key={item.id} className={selected?.id === item.id ? 'selected' : ''}>
                    <td>{item.createdAt}</td>
                    <td><span className={`connection-level ${item.level}`}>{connectionLevelLabels[item.level] || item.level}</span></td>
                    <td><strong>{connectionEventLabels[item.eventType] || item.eventType}</strong>{item.message && <small>{item.message}</small>}</td>
                    <td><strong>{item.candidate}</strong><small>{item.targetRole}</small></td>
                    <td>{item.connectionState}</td>
                    <td>{item.iceConnectionState}</td>
                    <td><CompactId value={item.sessionId} /></td>
                    <td><button className="table-view-button" type="button" onClick={() => setSelected(item)}>详情</button></td>
                  </tr>
                ))}
                {filteredLogs.length === 0 && <tr><td colSpan="8"><EmptyState text="当前筛选条件下没有连接日志" /></td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      {selected && (
        <SectionCard
          title="连接事件详情"
          icon={<Activity size={18} />}
          action={<button className="icon-button" type="button" onClick={() => setSelected(null)} aria-label="关闭连接日志详情"><X size={15} /></button>}
          className="connection-log-detail"
        >
          <div className="connection-detail-grid">
            <div><span>事件</span><strong>{connectionEventLabels[selected.eventType] || selected.eventType}</strong></div>
            <div><span>级别</span><strong>{connectionLevelLabels[selected.level] || selected.level}</strong></div>
            <div><span>学生</span><strong>{selected.candidate}</strong></div>
            <div><span>目标岗位</span><strong>{selected.targetRole}</strong></div>
            <div><span>连接状态</span><strong>{selected.connectionState}</strong></div>
            <div><span>ICE 连接</span><strong>{selected.iceConnectionState}</strong></div>
            <div><span>ICE 收集</span><strong>{selected.iceGatheringState}</strong></div>
            <div><span>数据通道</span><strong>{selected.dataChannelState}</strong></div>
            <div><span>信令状态</span><strong>{selected.signalingState}</strong></div>
            <div><span>服务端时间</span><strong>{selected.createdAt}</strong></div>
          </div>
          {selected.message && <div className="connection-detail-message"><span>事件信息</span><p>{selected.message}</p></div>}
          <div className="connection-identifiers">
            <span>面试 ID <CompactId value={selected.interviewId} /></span>
            <span>连接会话 <CompactId value={selected.sessionId} /></span>
          </div>
          {Object.keys(selected.metadata || {}).length > 0 && (
            <div className="connection-metadata">
              <span>安全诊断字段</span>
              {Object.entries(selected.metadata).map(([key, value]) => <code key={key}>{key}: {String(value)}</code>)}
            </div>
          )}
        </SectionCard>
      )}
    </div>
  );
}

const emptyCampusData = {
  colleges: [],
  programs: [],
  classes: [],
  students: [],
  standardMajors: [],
  jobRoles: [],
  summary: { colleges: 0, programs: 0, classes: 0, students: 0, unassigned: 0, focus: 0 },
};

function OrganizationPage({ onView }) {
  const [campus, setCampus] = useState(emptyCampusData);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState('');
  const [studentQuery, setStudentQuery] = useState('');

  const loadCampus = async () => {
    setLoading(true);
    try {
      const data = await adminRequest('/api/admin/campus/overview');
      setCampus({ ...emptyCampusData, ...data, summary: { ...emptyCampusData.summary, ...(data.summary || {}) } });
      setError('');
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCampus();
  }, []);

  const filteredStudents = useMemo(() => {
    const keyword = studentQuery.trim().toLowerCase();
    if (!keyword) return campus.students;
    return campus.students.filter((student) => {
      const searchable = [student.name, student.email, student.studentNo, student.targetRole, student.program, student.className].join(' ').toLowerCase();
      return searchable.includes(keyword);
    });
  }, [campus.students, studentQuery]);

  const updateStudent = async (student, updates) => {
    setBusy(`student-${student.id}`);
    setError('');
    try {
      await adminRequest(`/api/admin/campus/students/${encodeURIComponent(student.id)}`, {
        method: 'PATCH',
        body: JSON.stringify(updates),
      });
      setMessage(updates.focus !== undefined ? (updates.focus ? '已标记为重点关注' : '已取消重点关注') : '学生归属已更新');
      await loadCampus();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy('');
    }
  };

  const openStudent = (student) => {
    const asCandidate = {
      ...student,
      role: student.targetRole,
      status: student.accountStatus,
      averageScore: student.readiness,
      lastLogin: student.lastLogin,
    };
    const context = filteredStudents.map((item) => ({
      ...item,
      role: item.targetRole,
      status: item.accountStatus,
      averageScore: item.readiness,
      lastLogin: item.lastLogin,
    }));
    onView('candidate', asCandidate, context);
  };

  if (loading && campus.students.length === 0) return <div className="page-message loading-state"><RefreshCw size={18} className="spin" />正在读取组织与学生数据</div>;

  return (
    <div className="campus-page">
      {(error || message) && <div className={`campus-feedback ${error ? 'error' : 'success'}`}>{error || message}</div>}

      <section className="campus-workspace">
        <SectionCard title="学生" icon={<UsersRound size={18} />} action={<span className="record-count">{filteredStudents.length} 名学生</span>} className="campus-students-card">
          <div className="campus-student-toolbar">
            <label><Search size={15} /><input value={studentQuery} onChange={(event) => setStudentQuery(event.target.value)} placeholder="搜索姓名、学号、邮箱或目标岗位" /></label>
          </div>
          <div className="table-wrap campus-student-table">
            <table>
              <thead><tr><th>学生</th><th>目标岗位</th><th>准备度</th><th>训练</th><th>成长状态</th><th>班级归属</th><th aria-label="关注" /></tr></thead>
              <tbody>
                {filteredStudents.length === 0 && <tr><td colSpan="7"><EmptyState text="当前范围没有学生" /></td></tr>}
                {filteredStudents.map((student) => (
                  <tr key={student.id} className="data-row" onClick={() => openStudent(student)}>
                    <td><div className="student-identity"><strong>{student.name}</strong><span>{student.studentNo !== '-' ? student.studentNo : student.email}</span></div></td>
                    <td>{student.targetRole}</td>
                    <td><strong className={student.readiness < 60 && student.interviews > 0 ? 'score-alert' : ''}>{student.interviews ? `${student.readiness}分` : '-'}</strong></td>
                    <td>{student.interviews} 次</td>
                    <td><StatusBadge>{student.growthStatus}</StatusBadge></td>
                    <td onClick={(event) => event.stopPropagation()}>
                      <select value={student.classId || ''} disabled={busy === `student-${student.id}`} onChange={(event) => updateStudent(student, { classId: event.target.value })} aria-label={`调整 ${student.name} 的班级`}>
                        <option value="">未归班</option>
                        {campus.classes.map((classItem) => <option key={classItem.id} value={classItem.id}>{classItem.program_name} · {classItem.name}</option>)}
                      </select>
                    </td>
                    <td onClick={(event) => event.stopPropagation()}>
                      <button type="button" className={`focus-student-button ${student.focus ? 'active' : ''}`} disabled={busy === `student-${student.id}`} onClick={() => updateStudent(student, { focus: !student.focus })}>{student.focus ? '已关注' : '关注'}</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>
      </section>
    </div>
  );
}

const catalogStatusLabels = { draft: '草稿', published: '已发布', archived: '已归档' };
const suggestionStatusLabels = { pending: '待审核', approved: '已批准', merged: '已合并', rejected: '已驳回' };
const catalogEntityLabels = {
  colleges: '学院',
  majors: '专业',
  training_directions: '培养方向',
  employment_directions: '就业方向',
  job_roles: '具体岗位',
  competencies: '能力项',
};
const catalogParentFields = {
  majors: 'college_id',
  training_directions: 'major_id',
  employment_directions: 'training_direction_id',
  job_roles: 'employment_direction_id',
};
const catalogParentGroups = {
  majors: 'colleges',
  training_directions: 'training_directions_parent',
  employment_directions: 'employment_directions_parent',
  job_roles: 'job_roles_parent',
};

function flattenCatalogJobs(tree) {
  return (tree?.colleges || []).flatMap((college) => college.majors)
    .flatMap((major) => major.training_directions)
    .flatMap((training) => training.employment_directions)
    .flatMap((employment) => employment.jobs);
}

function flattenCatalogEntities(tree) {
  const groups = {
    colleges: [],
    majors: [],
    training_directions: [],
    employment_directions: [],
    job_roles: [],
    competencies: tree?.competencies || [],
    training_directions_parent: [],
    employment_directions_parent: [],
    job_roles_parent: [],
  };
  (tree?.colleges || []).forEach((college) => {
    groups.colleges.push(college);
    (college.majors || []).forEach((major) => {
      const majorItem = { ...major, college_id: college.id, path_label: `${college.name} / ${major.name}` };
      groups.majors.push(majorItem);
      groups.training_directions_parent.push(majorItem);
      (major.training_directions || []).forEach((training) => {
        const trainingItem = { ...training, major_id: major.id, path_label: `${major.name} / ${training.name}` };
        groups.training_directions.push(trainingItem);
        groups.employment_directions_parent.push(trainingItem);
        (training.employment_directions || []).forEach((employment) => {
          const employmentItem = {
            ...employment,
            training_direction_id: training.id,
            path_label: `${training.name} / ${employment.name}`,
          };
          groups.employment_directions.push(employmentItem);
          groups.job_roles_parent.push(employmentItem);
          (employment.jobs || []).forEach((job) => {
            groups.job_roles.push({
              ...job,
              employment_direction_id: employment.id,
              path_label: `${employment.name} / ${job.name}`,
            });
          });
        });
      });
    });
  });
  return groups;
}

const emptyCatalogEntityForm = {
  parent_id: '',
  code: '',
  name: '',
  category: '',
  degree_type: '',
  description: '',
  sort_order: 0,
  enabled: true,
};

function CatalogDraftEditor({ version, tree, onSaved, onError }) {
  const groups = useMemo(() => flattenCatalogEntities(tree), [tree]);
  const [entityType, setEntityType] = useState('colleges');
  const [editingId, setEditingId] = useState('');
  const [form, setForm] = useState(emptyCatalogEntityForm);
  const [matrix, setMatrix] = useState({});
  const [saving, setSaving] = useState(false);
  const entities = groups[entityType] || [];
  const parentField = catalogParentFields[entityType];
  const parentOptions = parentField ? groups[catalogParentGroups[entityType]] || [] : [];

  const resetEditor = (nextType = entityType) => {
    const nextGroups = flattenCatalogEntities(tree);
    const nextParentField = catalogParentFields[nextType];
    const nextParents = nextParentField ? nextGroups[catalogParentGroups[nextType]] || [] : [];
    setEditingId('');
    setForm({ ...emptyCatalogEntityForm, parent_id: nextParents[0]?.id || '' });
    setMatrix({});
  };

  useEffect(() => {
    resetEditor(entityType);
  }, [entityType, version.id]);

  const selectEntity = (entityId) => {
    if (!entityId) {
      resetEditor(entityType);
      return;
    }
    const item = entities.find((entry) => entry.id === entityId);
    if (!item) return;
    setEditingId(item.id);
    setForm({
      parent_id: parentField ? item[parentField] || '' : '',
      code: item.code || '',
      name: item.name || '',
      category: item.category || '',
      degree_type: item.degree_type || '',
      description: item.description || '',
      sort_order: item.sort_order || 0,
      enabled: Boolean(item.enabled),
    });
    const currentMatrix = {};
    (item.competencies || []).forEach((competency) => {
      currentMatrix[competency.id] = {
        selected: true,
        required_level: competency.required_level || 3,
        weight: competency.weight || 3,
      };
    });
    setMatrix(currentMatrix);
  };

  const updateForm = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const updateMatrix = (competencyId, patch) => setMatrix((current) => ({
    ...current,
    [competencyId]: { selected: false, required_level: 3, weight: 3, ...(current[competencyId] || {}), ...patch },
  }));

  const saveEntity = async (event) => {
    event.preventDefault();
    setSaving(true);
    onError('');
    try {
      const payload = {
        code: form.code,
        name: form.name,
        description: form.description,
        sort_order: Number(form.sort_order),
        enabled: form.enabled,
      };
      if (parentField) payload[parentField] = form.parent_id;
      if (entityType === 'majors') payload.degree_type = form.degree_type;
      if (entityType === 'competencies') payload.category = form.category;
      const path = editingId
        ? `/api/admin/catalog/versions/${encodeURIComponent(version.id)}/entities/${entityType}/${encodeURIComponent(editingId)}`
        : `/api/admin/catalog/versions/${encodeURIComponent(version.id)}/entities/${entityType}`;
      const result = await adminRequest(path, {
        method: editingId ? 'PATCH' : 'POST',
        body: JSON.stringify(payload),
      });
      if (entityType === 'job_roles') {
        const competencies = Object.entries(matrix)
          .filter(([, value]) => value.selected)
          .map(([competencyId, value]) => ({
            competency_id: competencyId,
            required_level: Number(value.required_level),
            weight: Number(value.weight),
            required: true,
          }));
        await adminRequest(
          `/api/admin/catalog/versions/${encodeURIComponent(version.id)}/jobs/${encodeURIComponent(result.item.id)}/competencies`,
          { method: 'PUT', body: JSON.stringify({ competencies }) },
        );
      }
      await onSaved(`${catalogEntityLabels[entityType]}${editingId ? '已更新' : '已新增'}。`);
      resetEditor(entityType);
    } catch (requestError) {
      onError(requestError.message);
    } finally {
      setSaving(false);
    }
  };

  const deleteEntity = async () => {
    const item = entities.find((entry) => entry.id === editingId);
    if (!item || !window.confirm(`确认从当前草稿删除“${item.name}”吗？其下级数据也会一并删除。`)) return;
    setSaving(true);
    onError('');
    try {
      await adminRequest(
        `/api/admin/catalog/versions/${encodeURIComponent(version.id)}/entities/${entityType}/${encodeURIComponent(editingId)}`,
        { method: 'DELETE' },
      );
      await onSaved(`${catalogEntityLabels[entityType]}已删除。`);
      resetEditor(entityType);
    } catch (requestError) {
      onError(requestError.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="catalog-draft-editor">
      <div className="catalog-editor-heading">
        <div><strong>草稿直接编辑</strong><span>新增、修改、启停和排序，保存后立即写入当前草稿。</span></div>
        <StatusBadge>仅草稿可编辑</StatusBadge>
      </div>
      <form className="catalog-editor-form" onSubmit={saveEntity}>
        <label className="field-block"><span>数据类型</span><select value={entityType} onChange={(event) => setEntityType(event.target.value)}>{Object.entries(catalogEntityLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label className="field-block"><span>新建或选择现有数据</span><select value={editingId} onChange={(event) => selectEntity(event.target.value)}><option value="">+ 新建{catalogEntityLabels[entityType]}</option>{entities.map((item) => <option key={item.id} value={item.id}>{item.path_label || item.name} · {item.code}</option>)}</select></label>
        {parentField && <label className="field-block"><span>所属上级</span><select value={form.parent_id} onChange={(event) => updateForm('parent_id', event.target.value)} required><option value="">请选择上级目录</option>{parentOptions.map((item) => <option key={item.id} value={item.id}>{item.path_label || item.name}</option>)}</select></label>}
        <label className="field-block"><span>编码</span><input value={form.code} onChange={(event) => updateForm('code', event.target.value)} placeholder="仅字母、数字、点、下划线或短横线" required /></label>
        <label className="field-block"><span>名称</span><input value={form.name} onChange={(event) => updateForm('name', event.target.value)} required /></label>
        {entityType === 'majors' && <label className="field-block"><span>学位类型</span><input value={form.degree_type} onChange={(event) => updateForm('degree_type', event.target.value)} placeholder="例如：工学" /></label>}
        {entityType === 'competencies' && <label className="field-block"><span>能力类别</span><input value={form.category} onChange={(event) => updateForm('category', event.target.value)} placeholder="例如：工程能力" required /></label>}
        <label className="field-block"><span>排序</span><input type="number" value={form.sort_order} onChange={(event) => updateForm('sort_order', event.target.value)} /></label>
        <label className="catalog-enabled-field"><input type="checkbox" checked={form.enabled} onChange={(event) => updateForm('enabled', event.target.checked)} /><span>启用</span></label>
        <label className="field-block catalog-editor-description"><span>说明</span><textarea value={form.description} onChange={(event) => updateForm('description', event.target.value)} /></label>
        {entityType === 'job_roles' && (
          <div className="catalog-matrix-editor">
            <strong>岗位能力矩阵</strong>
            <span>勾选能力，并设置要求等级和权重（1-5）。</span>
            <div className="catalog-matrix-grid">
              {(tree.competencies || []).map((competency) => {
                const value = matrix[competency.id] || { selected: false, required_level: 3, weight: 3 };
                return (
                  <div key={competency.id} className={value.selected ? 'selected' : ''}>
                    <label><input type="checkbox" checked={value.selected} onChange={(event) => updateMatrix(competency.id, { selected: event.target.checked })} /><span>{competency.name}</span></label>
                    <select value={value.required_level} disabled={!value.selected} onChange={(event) => updateMatrix(competency.id, { required_level: event.target.value })}>{[1, 2, 3, 4, 5].map((level) => <option key={level} value={level}>等级 {level}</option>)}</select>
                    <select value={value.weight} disabled={!value.selected} onChange={(event) => updateMatrix(competency.id, { weight: event.target.value })}>{[1, 2, 3, 4, 5].map((weight) => <option key={weight} value={weight}>权重 {weight}</option>)}</select>
                  </div>
                );
              })}
              {(tree.competencies || []).length === 0 && <EmptyState text="请先新增能力项" />}
            </div>
          </div>
        )}
        <div className="catalog-editor-buttons">
          <button className="primary-button" disabled={saving}>{saving ? '保存中...' : editingId ? '保存修改' : `新增${catalogEntityLabels[entityType]}`}</button>
          {editingId && <button className="danger-outline-button" type="button" onClick={deleteEntity} disabled={saving}>删除</button>}
        </div>
      </form>
    </div>
  );
}

function CatalogTree({ tree }) {
  if (!tree?.colleges?.length) return <EmptyState text="当前版本尚未导入目录数据" />;
  return (
    <div className="catalog-tree">
      {tree.colleges.map((college) => (
        <details key={college.id} open>
          <summary><strong>{college.name}</strong><span>{college.code} · {college.majors.length} 个专业</span></summary>
          <div className="catalog-tree-level">
            {college.majors.map((major) => (
              <details key={major.id}>
                <summary><strong>{major.name}</strong><span>{major.code} · {major.training_directions.length} 个培养方向</span></summary>
                <div className="catalog-tree-level">
                  {major.training_directions.map((training) => (
                    <details key={training.id}>
                      <summary><strong>{training.name}</strong><span>{training.code}</span></summary>
                      <div className="catalog-tree-level">
                        {training.employment_directions.map((employment) => (
                          <section className="catalog-employment" key={employment.id}>
                            <header><strong>{employment.name}</strong><span>{employment.code}</span></header>
                            <div className="catalog-job-grid">
                              {employment.jobs.map((job) => (
                                <article key={job.id}>
                                  <div><strong>{job.name}</strong><span>{job.code}</span></div>
                                  <p>{job.description || '暂无岗位说明'}</p>
                                  <small>{job.competencies.length} 项能力要求</small>
                                </article>
                              ))}
                              {employment.jobs.length === 0 && <EmptyState text="暂无岗位" />}
                            </div>
                          </section>
                        ))}
                      </div>
                    </details>
                  ))}
                </div>
              </details>
            ))}
          </div>
        </details>
      ))}
    </div>
  );
}

function CatalogPage({ permissions }) {
  const [versions, setVersions] = useState([]);
  const [selectedCode, setSelectedCode] = useState('');
  const [tree, setTree] = useState(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const [catalogError, setCatalogError] = useState('');
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [versionForm, setVersionForm] = useState({ code: '', name: '', description: '' });
  const [file, setFile] = useState(null);
  const [mode, setMode] = useState('merge');
  const [suggestions, setSuggestions] = useState([]);
  const [publishedJobs, setPublishedJobs] = useState([]);
  const [suggestionStatus, setSuggestionStatus] = useState('pending');
  const [mergeTargets, setMergeTargets] = useState({});
  const [approvalForms, setApprovalForms] = useState({});
  const [suggestionBusy, setSuggestionBusy] = useState('');
  const selectedVersion = versions.find((item) => item.code === selectedCode) || null;
  const catalogGroups = useMemo(() => flattenCatalogEntities(tree), [tree]);
  const draftEmploymentDirections = catalogGroups.job_roles_parent || [];

  const loadTree = async (code) => {
    if (!code) { setTree(null); setLoading(false); return; }
    setLoading(true);
    try {
      setTree(await adminRequest(`/api/admin/catalog/tree?version=${encodeURIComponent(code)}`));
      setCatalogError('');
    } catch (requestError) {
      setCatalogError(requestError.message);
      setTree(null);
    } finally {
      setLoading(false);
    }
  };

  const loadVersions = async (preferredCode = '') => {
    const result = await adminRequest('/api/admin/catalog/versions');
    const nextVersions = result.versions || [];
    setVersions(nextVersions);
    const publishedVersion = nextVersions.find((item) => item.status === 'published');
    if (publishedVersion) {
      const publishedTree = await adminRequest(`/api/admin/catalog/tree?version=${encodeURIComponent(publishedVersion.code)}`);
      setPublishedJobs(flattenCatalogJobs(publishedTree));
    } else {
      setPublishedJobs([]);
    }
    const code = preferredCode || nextVersions.find((item) => item.status === 'published')?.code || nextVersions[0]?.code || '';
    setSelectedCode(code);
    return code;
  };

  const loadSuggestions = async (status = suggestionStatus) => {
    const result = await adminRequest(`/api/admin/catalog/job-suggestions${status === 'all' ? '' : `?status=${status}`}`);
    setSuggestions(result.suggestions || []);
  };

  useEffect(() => {
    loadVersions().then(loadTree).catch((requestError) => { setCatalogError(requestError.message); setLoading(false); });
    loadSuggestions().catch((requestError) => setCatalogError(requestError.message));
  }, []);

  useEffect(() => {
    if (selectedCode) loadTree(selectedCode);
  }, [selectedCode]);

  useEffect(() => {
    loadSuggestions(suggestionStatus).catch((requestError) => setCatalogError(requestError.message));
  }, [suggestionStatus]);

  const createDraft = async (event) => {
    event.preventDefault();
    setCreating(true); setMessage(''); setCatalogError('');
    try {
      const result = await adminRequest('/api/admin/catalog/versions', { method: 'POST', body: JSON.stringify(versionForm) });
      setVersionForm({ code: '', name: '', description: '' });
      await loadVersions(result.version.code);
      await loadTree(result.version.code);
      setMessage('草稿版本已创建，可以上传 Excel 导入学院、专业和岗位数据。');
    } catch (requestError) { setCatalogError(requestError.message); }
    finally { setCreating(false); }
  };

  const importExcel = async (event) => {
    event.preventDefault();
    if (!selectedVersion || !file) return;
    const formElement = event.currentTarget;
    setImporting(true); setMessage(''); setCatalogError('');
    const formData = new FormData();
    formData.append('file', file);
    try {
      const result = await adminRequest(`/api/admin/catalog/versions/${encodeURIComponent(selectedVersion.id)}/imports?mode=${mode}`, { method: 'POST', body: formData });
      await loadTree(selectedVersion.code);
      setFile(null);
      formElement.reset();
      setMessage(`Excel 导入成功，共写入 ${result.import_job.imported_rows} 行。`);
    } catch (requestError) { setCatalogError(requestError.message); }
    finally { setImporting(false); }
  };

  const publishDraft = async () => {
    if (!selectedVersion || !window.confirm(`确认发布“${selectedVersion.name}”吗？当前已发布版本会被归档。`)) return;
    setPublishing(true); setMessage(''); setCatalogError('');
    try {
      await adminRequest(`/api/admin/catalog/versions/${encodeURIComponent(selectedVersion.id)}/publish`, { method: 'POST' });
      await loadVersions(selectedVersion.code);
      await loadTree(selectedVersion.code);
      setMessage('目录版本已发布，候选人端现在可以读取该版本。');
    } catch (requestError) { setCatalogError(requestError.message); }
    finally { setPublishing(false); }
  };

  const reviewSuggestion = async (suggestion, status) => {
    setSuggestionBusy(suggestion.id); setMessage(''); setCatalogError('');
    try {
      await adminRequest(`/api/admin/catalog/job-suggestions/${encodeURIComponent(suggestion.id)}/review`, {
        method: 'POST', body: JSON.stringify({ status }),
      });
      await loadSuggestions();
      setMessage(status === 'approved' ? '岗位建议已批准，等待纳入下一目录草稿并补充能力矩阵。' : '岗位建议已驳回。');
    } catch (requestError) { setCatalogError(requestError.message); }
    finally { setSuggestionBusy(''); }
  };

  const mergeSuggestion = async (suggestion) => {
    const targetId = mergeTargets[suggestion.id] || suggestion.nearest_job_role_id || '';
    if (!targetId) { setCatalogError('请选择需要合并到的正式岗位。'); return; }
    setSuggestionBusy(suggestion.id); setMessage(''); setCatalogError('');
    try {
      await adminRequest(`/api/admin/catalog/job-suggestions/${encodeURIComponent(suggestion.id)}/merge`, {
        method: 'POST', body: JSON.stringify({ job_role_id: targetId }),
      });
      await loadSuggestions();
      setMessage('岗位建议已合并，并自动登记为正式岗位别名。');
    } catch (requestError) { setCatalogError(requestError.message); }
    finally { setSuggestionBusy(''); }
  };

  const openSuggestionApproval = (suggestion) => {
    if (selectedVersion?.status !== 'draft') {
      setCatalogError('请先在上方选择一个草稿版本，再批准新增岗位。');
      return;
    }
    setCatalogError('');
    setApprovalForms((current) => ({
      ...current,
      [suggestion.id]: current[suggestion.id] || {
        code: '',
        name: suggestion.suggested_name,
        employment_direction_id: draftEmploymentDirections[0]?.id || '',
        competency_ids: [],
      },
    }));
  };

  const updateApprovalForm = (suggestionId, key, value) => setApprovalForms((current) => ({
    ...current,
    [suggestionId]: { ...current[suggestionId], [key]: value },
  }));

  const toggleApprovalCompetency = (suggestionId, competencyId, checked) => {
    const currentIds = approvalForms[suggestionId]?.competency_ids || [];
    const nextIds = checked
      ? [...new Set([...currentIds, competencyId])]
      : currentIds.filter((item) => item !== competencyId);
    updateApprovalForm(suggestionId, 'competency_ids', nextIds);
  };

  const approveSuggestionToDraft = async (event, suggestion) => {
    event.preventDefault();
    const form = approvalForms[suggestion.id];
    if (!selectedVersion || selectedVersion.status !== 'draft') {
      setCatalogError('请选择目录草稿。');
      return;
    }
    if (!form?.competency_ids?.length) {
      setCatalogError('请至少选择一项岗位能力。');
      return;
    }
    setSuggestionBusy(suggestion.id); setMessage(''); setCatalogError('');
    try {
      await adminRequest(`/api/admin/catalog/job-suggestions/${encodeURIComponent(suggestion.id)}/approve-to-draft`, {
        method: 'POST',
        body: JSON.stringify({
          version_id: selectedVersion.id,
          employment_direction_id: form.employment_direction_id,
          code: form.code,
          name: form.name,
          competencies: form.competency_ids.map((competencyId) => ({
            competency_id: competencyId,
            required_level: 4,
            weight: 3,
            required: true,
          })),
        }),
      });
      setApprovalForms((current) => {
        const next = { ...current };
        delete next[suggestion.id];
        return next;
      });
      await loadTree(selectedVersion.code);
      await loadSuggestions(suggestionStatus);
      setMessage(`“${form.name}”已写入草稿 ${selectedVersion.name}，可在草稿编辑区继续调整能力等级和权重。`);
    } catch (requestError) {
      setCatalogError(requestError.message);
    } finally {
      setSuggestionBusy('');
    }
  };

  return (
    <div className="catalog-page">
      <SectionCard title="职业能力目录" icon={<BookOpen size={18} />} action={<button className="secondary-button" type="button" onClick={() => loadTree(selectedCode)}><RefreshCw size={15} />刷新</button>}>
        <div className="catalog-toolbar">
          <label className="field-block"><span>查看目录版本</span><select value={selectedCode} onChange={(event) => setSelectedCode(event.target.value)}>{versions.map((version) => <option value={version.code} key={version.id}>{version.name} · {catalogStatusLabels[version.status]}</option>)}</select></label>
          {selectedVersion && <div className="catalog-version-meta"><StatusBadge>{catalogStatusLabels[selectedVersion.status] || selectedVersion.status}</StatusBadge><span>编码：{selectedVersion.code}</span><span>修订：V{selectedVersion.revision}</span></div>}
        </div>
        {message && <p className="settings-message success catalog-message">{message}</p>}
        {catalogError && <p className="settings-message error catalog-message">{catalogError}</p>}
        {loading ? <div className="page-message">正在读取目录</div> : <CatalogTree tree={tree} />}
        {permissions.canWriteCatalog && selectedVersion?.status === 'draft' && tree && (
          <CatalogDraftEditor
            version={selectedVersion}
            tree={tree}
            onError={setCatalogError}
            onSaved={async (nextMessage) => {
              await loadTree(selectedVersion.code);
              setMessage(nextMessage);
            }}
          />
        )}
      </SectionCard>
      <SectionCard title="AI 岗位建议池" icon={<Bot size={18} />} action={<select className="compact-select" value={suggestionStatus} onChange={(event) => setSuggestionStatus(event.target.value)}><option value="pending">待审核</option><option value="approved">已批准</option><option value="merged">已合并</option><option value="rejected">已驳回</option><option value="all">全部</option></select>}>
        <div className="suggestion-list">
          {suggestions.length === 0 && <EmptyState text="当前没有该状态的岗位建议" />}
          {suggestions.map((suggestion) => (
            <article key={suggestion.id}>
              <div className="suggestion-copy">
                <div><strong>{suggestion.suggested_name}</strong><StatusBadge>{suggestionStatusLabels[suggestion.review_status] || suggestion.review_status}</StatusBadge></div>
                <span>出现 {suggestion.occurrence_count} 次 · 来源 {suggestion.last_provider || suggestion.source_type}</span>
                <small>{suggestion.nearest_job_name ? `最接近正式岗位：${suggestion.nearest_job_name}（名称相似度 ${suggestion.match_confidence}%）` : '暂未找到接近的正式岗位'}</small>
                {suggestion.draft_version_code && <small className="suggestion-draft-link">已纳入草稿：{suggestion.draft_version_code} / {suggestion.draft_job_name}</small>}
              </div>
              {permissions.canWriteCatalog && suggestion.review_status === 'pending' && (
                <div className="suggestion-actions">
                  <select value={mergeTargets[suggestion.id] || suggestion.nearest_job_role_id || ''} onChange={(event) => setMergeTargets((current) => ({ ...current, [suggestion.id]: event.target.value }))}>
                    <option value="">选择正式岗位</option>
                    {publishedJobs.map((job) => <option key={job.id} value={job.id}>{job.name}</option>)}
                  </select>
                  <button type="button" onClick={() => mergeSuggestion(suggestion)} disabled={suggestionBusy === suggestion.id}>合并为别名</button>
                  <button type="button" className="approve" onClick={() => openSuggestionApproval(suggestion)} disabled={suggestionBusy === suggestion.id || selectedVersion?.status !== 'draft'} title={selectedVersion?.status === 'draft' ? '写入当前草稿' : '请先选择草稿版本'}>纳入当前草稿</button>
                  <button type="button" className="reject" onClick={() => reviewSuggestion(suggestion, 'rejected')} disabled={suggestionBusy === suggestion.id}>驳回</button>
                </div>
              )}
              {approvalForms[suggestion.id] && (
                <form className="suggestion-approval-form" onSubmit={(event) => approveSuggestionToDraft(event, suggestion)}>
                  <div className="suggestion-approval-heading"><strong>批准并写入：{selectedVersion?.name}</strong><button type="button" onClick={() => setApprovalForms((current) => ({ ...current, [suggestion.id]: undefined }))}>取消</button></div>
                  <label className="field-block"><span>岗位编码</span><input value={approvalForms[suggestion.id].code} onChange={(event) => updateApprovalForm(suggestion.id, 'code', event.target.value)} placeholder="例如：LLM-APP-ENGINEER" required /></label>
                  <label className="field-block"><span>岗位名称</span><input value={approvalForms[suggestion.id].name} onChange={(event) => updateApprovalForm(suggestion.id, 'name', event.target.value)} required /></label>
                  <label className="field-block"><span>所属就业方向</span><select value={approvalForms[suggestion.id].employment_direction_id} onChange={(event) => updateApprovalForm(suggestion.id, 'employment_direction_id', event.target.value)} required><option value="">请选择就业方向</option>{draftEmploymentDirections.map((item) => <option key={item.id} value={item.id}>{item.path_label || item.name}</option>)}</select></label>
                  <div className="suggestion-competency-picker">
                    <strong>初始能力矩阵</strong><span>先选择能力，写入后可在草稿编辑区调整等级和权重。</span>
                    <div>{(tree?.competencies || []).map((competency) => <label key={competency.id}><input type="checkbox" checked={approvalForms[suggestion.id].competency_ids.includes(competency.id)} onChange={(event) => toggleApprovalCompetency(suggestion.id, competency.id, event.target.checked)} /><span>{competency.name}</span></label>)}</div>
                  </div>
                  <button className="primary-button" disabled={suggestionBusy === suggestion.id}>{suggestionBusy === suggestion.id ? '写入中...' : '确认写入草稿'}</button>
                </form>
              )}
            </article>
          ))}
        </div>
      </SectionCard>
      <section className="catalog-actions-grid">
        {permissions.canWriteCatalog && <SectionCard title="新建草稿版本" icon={<Plus size={18} />}><form className="catalog-action-form" onSubmit={createDraft}><label className="field-block"><span>版本编码</span><input value={versionForm.code} onChange={(event) => setVersionForm((current) => ({ ...current, code: event.target.value }))} placeholder="school-catalog-v2" required /></label><label className="field-block"><span>版本名称</span><input value={versionForm.name} onChange={(event) => setVersionForm((current) => ({ ...current, name: event.target.value }))} placeholder="全校职业能力目录 V2" required /></label><label className="field-block"><span>说明</span><textarea value={versionForm.description} onChange={(event) => setVersionForm((current) => ({ ...current, description: event.target.value }))} /></label><button className="primary-button" disabled={creating}>{creating ? '创建中...' : '创建草稿'}</button></form></SectionCard>}
        {permissions.canImportCatalog && <SectionCard title="导入学院、专业与岗位" icon={<Upload size={18} />}><form className="catalog-action-form" onSubmit={importExcel}><p>选择草稿版本，上传包含七个规定工作表的 `.xlsx` 文件，可一次批量添加岗位和能力矩阵。</p><label className="field-block"><span>Excel 文件</span><input type="file" accept=".xlsx" onChange={(event) => setFile(event.target.files?.[0] || null)} required /></label><label className="field-block"><span>导入模式</span><select value={mode} onChange={(event) => setMode(event.target.value)}><option value="merge">合并更新</option><option value="replace">替换草稿数据</option></select></label><button className="primary-button" disabled={importing || selectedVersion?.status !== 'draft' || !file}>{importing ? '导入中...' : '上传并导入'}</button>{selectedVersion?.status !== 'draft' && <small>已发布版本不可修改，请先新建草稿版本。</small>}</form></SectionCard>}
        {permissions.canPublishCatalog && <SectionCard title="审核与发布" icon={<Rocket size={18} />}><div className="catalog-action-form"><p>发布前会校验完整层级与岗位能力矩阵；发布后原版本自动归档。</p><button className="primary-button" type="button" onClick={publishDraft} disabled={publishing || selectedVersion?.status !== 'draft'}>{publishing ? '发布中...' : '发布当前草稿'}</button></div></SectionCard>}
      </section>
    </div>
  );
}

function SettingsPage({ data, onSettingsSaved }) {
  const settings = data.settings || emptyAdminData.settings;
  const [form, setForm] = useState({
    reportOpenaiApiKey: '',
    reportOpenaiModel: settings.reportOpenaiModel || 'gpt-4o-mini',
    reportQwenApiKey: '',
    reportQwenModel: settings.reportQwenModel || 'qwen-plus',
    reportProviderOrder: settings.reportProviderOrder || 'openai,qwen',
    reportTimeout: settings.reportTimeout || 60,
    reportRetries: settings.reportRetries ?? 1,
    openaiApiKey: '',
    openaiRealtimeModel: settings.openaiRealtimeModel === '-' ? '' : settings.openaiRealtimeModel,
    openaiVoice: settings.openaiVoice === '-' ? '' : settings.openaiVoice,
    dashscopeApiKey: '',
    qwenTtsModel: settings.qwenTtsModel === '-' ? '' : settings.qwenTtsModel,
    qwenTtsVoice: settings.qwenTtsVoice === '-' ? '' : settings.qwenTtsVoice,
    qwenTtsRegion: settings.qwenTtsRegion || 'beijing',
    qwenTtsWorkspaceId: settings.qwenTtsWorkspaceId || '',
    qwenOmniModel: settings.qwenOmniModel || 'qwen3.5-omni-plus-realtime',
    qwenOmniVoice: settings.qwenOmniVoice || 'Tina',
    qwenOmniRegion: settings.qwenOmniRegion || 'beijing',
    qwenOmniWorkspaceId: settings.qwenOmniWorkspaceId || '',
    qwenOmniEndpoint: settings.qwenOmniEndpoint || '',
  });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [saveError, setSaveError] = useState('');
  const [testingProviders, setTestingProviders] = useState(false);
  const [providerTestResults, setProviderTestResults] = useState([]);
  const [providerTestError, setProviderTestError] = useState('');
  const openaiReady = Boolean(settings.openaiApiKeyConfigured);
  const reportOpenaiReady = Boolean(settings.reportOpenaiApiKeyConfigured);
  const reportQwenReady = Boolean(settings.reportQwenApiKeyConfigured);
  const dashscopeReady = Boolean(settings.dashscopeApiKeyConfigured);
  const qwenOmniReady = Boolean(settings.qwenOmniApiKeyConfigured);

  useEffect(() => {
    setForm((current) => ({
      ...current,
      reportOpenaiModel: settings.reportOpenaiModel || 'gpt-4o-mini',
      reportQwenModel: settings.reportQwenModel || 'qwen-plus',
      reportProviderOrder: settings.reportProviderOrder || 'openai,qwen',
      reportTimeout: settings.reportTimeout || 60,
      reportRetries: settings.reportRetries ?? 1,
      openaiRealtimeModel: settings.openaiRealtimeModel === '-' ? '' : settings.openaiRealtimeModel,
      openaiVoice: settings.openaiVoice === '-' ? '' : settings.openaiVoice,
      qwenTtsModel: settings.qwenTtsModel === '-' ? '' : settings.qwenTtsModel,
      qwenTtsVoice: settings.qwenTtsVoice === '-' ? '' : settings.qwenTtsVoice,
      qwenTtsRegion: settings.qwenTtsRegion || 'beijing',
      qwenTtsWorkspaceId: settings.qwenTtsWorkspaceId || '',
      qwenOmniModel: settings.qwenOmniModel || 'qwen3.5-omni-plus-realtime',
      qwenOmniVoice: settings.qwenOmniVoice || 'Tina',
      qwenOmniRegion: settings.qwenOmniRegion || 'beijing',
      qwenOmniWorkspaceId: settings.qwenOmniWorkspaceId || '',
      qwenOmniEndpoint: settings.qwenOmniEndpoint || '',
    }));
  }, [
    settings.reportOpenaiModel,
    settings.reportQwenModel,
    settings.reportProviderOrder,
    settings.reportTimeout,
    settings.reportRetries,
    settings.openaiRealtimeModel,
    settings.openaiVoice,
    settings.qwenTtsModel,
    settings.qwenTtsVoice,
    settings.qwenTtsRegion,
    settings.qwenTtsWorkspaceId,
    settings.qwenOmniModel,
    settings.qwenOmniVoice,
    settings.qwenOmniRegion,
    settings.qwenOmniWorkspaceId,
    settings.qwenOmniEndpoint,
  ]);

  const updateForm = (key, value) => setForm((current) => ({ ...current, [key]: value }));

  const handleSave = async (event) => {
    event.preventDefault();
    setSaving(true);
    setMessage('');
    setSaveError('');
    try {
      const data = await adminRequest('/api/admin/settings', {
        method: 'PATCH',
        body: JSON.stringify(form),
      });
      setMessage(data.message || '配置已保存。');
      setForm((current) => ({
        ...current,
        reportOpenaiApiKey: '',
        reportQwenApiKey: '',
        openaiApiKey: '',
        dashscopeApiKey: '',
      }));
      onSettingsSaved(data.settings);
    } catch (requestError) {
      setSaveError(requestError.message);
    } finally {
      setSaving(false);
    }
  };
  const testReportProviders = async () => {
    setTestingProviders(true);
    setProviderTestResults([]);
    setProviderTestError('');
    try {
      const result = await adminRequest('/api/admin/settings/report-providers/test', { method: 'POST' });
      setProviderTestResults(result.providers || []);
    } catch (requestError) {
      setProviderTestError(requestError.message);
    } finally {
      setTestingProviders(false);
    }
  };
  return (
    <section className="content-grid">
      <SectionCard title="系统配置" icon={<Settings size={18} />}>
        <form className="settings-form" onSubmit={handleSave}>
          <div className="settings-overview">
            <div className={`settings-status ${reportOpenaiReady || reportQwenReady ? 'ready' : 'missing'}`}>
              {reportOpenaiReady || reportQwenReady ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
              <div>
                <strong>复盘报告 AI</strong>
                <span>OpenAI {reportOpenaiReady ? settings.reportOpenaiApiKeyMasked : '未配置'} · 千问 {reportQwenReady ? settings.reportQwenApiKeyMasked : '未配置'}</span>
              </div>
            </div>
            <div className={`settings-status ${openaiReady ? 'ready' : 'missing'}`}>
              {openaiReady ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
              <div>
                <strong>OpenAI 实时语音</strong>
                <span>{openaiReady ? `已配置 ${settings.openaiApiKeyMasked}` : '待配置 API Key'}</span>
              </div>
            </div>
            <div className={`settings-status ${dashscopeReady ? 'ready' : 'missing'}`}>
              {dashscopeReady ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
              <div>
                <strong>千问语音合成</strong>
                <span>{dashscopeReady ? `已配置 ${settings.dashscopeApiKeyMasked}` : '待配置 DashScope Key'}</span>
              </div>
            </div>
            <div className={`settings-status ${qwenOmniReady && (form.qwenOmniWorkspaceId || form.qwenOmniEndpoint) ? 'ready' : 'missing'}`}>
              {qwenOmniReady && (form.qwenOmniWorkspaceId || form.qwenOmniEndpoint) ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
              <div>
                <strong>Qwen Omni WebRTC</strong>
                <span>{qwenOmniReady ? `密钥已配置 ${settings.qwenOmniApiKeyMasked}` : '待配置 DashScope Key'}</span>
              </div>
            </div>
          </div>

          <div className="provider-card">
            <div className="provider-card-header">
              <div>
                <KeyRound size={18} />
                <div>
                  <h3>OpenAI Realtime</h3>
                  <p>控制用户端电话面试、实时转写和 AI 面试官语音回复。</p>
                </div>
              </div>
              <span className={`provider-pill ${openaiReady ? 'ready' : 'missing'}`}>{openaiReady ? '可用' : '未配置'}</span>
            </div>
            <label className="field-block">
              <span>API Key</span>
              <input
                type="password"
                value={form.openaiApiKey}
                onChange={(event) => updateForm('openaiApiKey', event.target.value)}
                placeholder={openaiReady ? `保留当前：${settings.openaiApiKeyMasked}` : 'sk-...'}
              />
              <small>留空不会覆盖已有密钥；只在需要替换时填写。</small>
            </label>
            <div className="field-grid">
              <label className="field-block">
                <span>Realtime 模型</span>
                <input value={form.openaiRealtimeModel} onChange={(event) => updateForm('openaiRealtimeModel', event.target.value)} placeholder="gpt-realtime-2" />
              </label>
              <label className="field-block">
                <span>输出音色</span>
                <input value={form.openaiVoice} onChange={(event) => updateForm('openaiVoice', event.target.value)} placeholder="marin" />
              </label>
            </div>
          </div>

          <div className="provider-card">
            <div className="provider-card-header">
              <div>
                <KeyRound size={18} />
                <div>
                  <h3>DashScope / 千问流式 TTS</h3>
                  <p>面向文本追问转语音播放：AI 已生成文本后，服务端用 CosyVoice 流式合成音频并返回用户端播放。</p>
                </div>
              </div>
              <span className={`provider-pill ${dashscopeReady ? 'ready' : 'missing'}`}>{dashscopeReady ? '可用' : '未配置'}</span>
            </div>
            <label className="field-block">
              <span>API Key</span>
              <input
                type="password"
                value={form.dashscopeApiKey}
                onChange={(event) => updateForm('dashscopeApiKey', event.target.value)}
                placeholder={dashscopeReady ? `保留当前：${settings.dashscopeApiKeyMasked}` : 'sk-...'}
              />
              <small>留空不会覆盖已有密钥；用于服务端连接 DashScope CosyVoice 流式语音合成。</small>
            </label>
            <div className="field-grid">
              <label className="field-block">
                <span>TTS 模型</span>
                <input value={form.qwenTtsModel} onChange={(event) => updateForm('qwenTtsModel', event.target.value)} placeholder="cosyvoice-v3-flash" />
              </label>
              <label className="field-block">
                <span>TTS 音色</span>
                <input value={form.qwenTtsVoice} onChange={(event) => updateForm('qwenTtsVoice', event.target.value)} placeholder="longanyang" />
              </label>
            </div>
            <div className="field-grid">
              <label className="field-block">
                <span>TTS 地域</span>
                <input value={form.qwenTtsRegion} onChange={(event) => updateForm('qwenTtsRegion', event.target.value)} placeholder="beijing" />
                <small>默认使用北京：beijing；新加坡可填 singapore 或 ap-southeast-1。</small>
              </label>
              <label className="field-block">
                <span>Workspace ID</span>
                <input value={form.qwenTtsWorkspaceId} onChange={(event) => updateForm('qwenTtsWorkspaceId', event.target.value)} placeholder="新加坡地域必填，北京地域可留空" />
                <small>仅新加坡地域需要，用来拼接专属 WebSocket 接入地址。</small>
              </label>
            </div>
          </div>

          <div className="provider-card report-provider-card">
            <div className="provider-card-header">
              <div>
                <KeyRound size={18} />
                <div>
                  <h3>复盘报告 / 单题评价模型</h3>
                  <p>为综合复盘报告和单题评分配置独立文本模型密钥，不再依赖实时语音密钥。</p>
                </div>
              </div>
              <span className={`provider-pill ${reportOpenaiReady || reportQwenReady ? 'ready' : 'missing'}`}>
                {reportOpenaiReady || reportQwenReady ? '已配置' : '未配置'}
              </span>
            </div>
            <div className="field-grid">
              <label className="field-block">
                <span>OpenAI 文本 API Key</span>
                <input type="password" autoComplete="new-password" value={form.reportOpenaiApiKey} onChange={(event) => updateForm('reportOpenaiApiKey', event.target.value)} placeholder={reportOpenaiReady ? `保留当前：${settings.reportOpenaiApiKeyMasked}` : 'sk-...'} />
                <small>写入 OPENAI_API_KEY；留空不会覆盖已有密钥。</small>
              </label>
              <label className="field-block">
                <span>OpenAI 报告模型</span>
                <input value={form.reportOpenaiModel} onChange={(event) => updateForm('reportOpenaiModel', event.target.value)} placeholder="gpt-4o-mini" />
              </label>
            </div>
            <div className="field-grid">
              <label className="field-block">
                <span>千问文本 API Key</span>
                <input type="password" autoComplete="new-password" value={form.reportQwenApiKey} onChange={(event) => updateForm('reportQwenApiKey', event.target.value)} placeholder={reportQwenReady ? `保留当前：${settings.reportQwenApiKeyMasked}` : 'sk-...'} />
                <small>写入 QWEN_API_KEY；不会再把语音 Key 当作报告专用配置。</small>
              </label>
              <label className="field-block">
                <span>千问报告模型</span>
                <input value={form.reportQwenModel} onChange={(event) => updateForm('reportQwenModel', event.target.value)} placeholder="qwen-plus" />
              </label>
            </div>
            <div className="field-grid report-runtime-grid">
              <label className="field-block">
                <span>供应商优先顺序</span>
                <select value={form.reportProviderOrder} onChange={(event) => updateForm('reportProviderOrder', event.target.value)}>
                  <option value="openai,qwen">OpenAI 优先，千问备用</option>
                  <option value="qwen,openai">千问优先，OpenAI 备用</option>
                  <option value="openai">仅 OpenAI</option>
                  <option value="qwen">仅千问</option>
                </select>
              </label>
              <label className="field-block">
                <span>单供应商超时（秒）</span>
                <input type="number" min="10" max="180" value={form.reportTimeout} onChange={(event) => updateForm('reportTimeout', event.target.value)} />
              </label>
              <label className="field-block">
                <span>网络重试次数</span>
                <input type="number" min="0" max="4" value={form.reportRetries} onChange={(event) => updateForm('reportRetries', event.target.value)} />
              </label>
            </div>
            <div className="provider-test-actions">
              <button className="secondary-button" type="button" onClick={testReportProviders} disabled={testingProviders}>{testingProviders ? '检测中...' : '检测报告模型连通性'}</button>
              <span>请先保存配置，再执行检测；检测会发送一个最小 JSON 请求。</span>
            </div>
            {providerTestError && <p className="settings-message error">{providerTestError}</p>}
            {providerTestResults.length > 0 && (
              <div className="provider-test-results">
                {providerTestResults.map((item) => (
                  <div className={item.status === 'ok' ? 'ready' : 'missing'} key={item.provider}>
                    <strong>{item.provider.toUpperCase()} · {item.model}</strong>
                    <span>{item.status === 'ok' ? `连接成功 · ${item.latency_ms} ms` : item.error || '检测失败'}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="provider-card">
            <div className="provider-card-header">
              <div>
                <KeyRound size={18} />
                <div>
                  <h3>Qwen-Omni Realtime WebRTC</h3>
                  <p>浏览器与千问实时模型直连音频，后端仅代理 SDP 鉴权和会话配置。</p>
                </div>
              </div>
              <span className={`provider-pill ${qwenOmniReady && (form.qwenOmniWorkspaceId || form.qwenOmniEndpoint) ? 'ready' : 'missing'}`}>
                {qwenOmniReady && (form.qwenOmniWorkspaceId || form.qwenOmniEndpoint) ? '可联调' : '缺少配置'}
              </span>
            </div>
            <div className="field-grid">
              <label className="field-block">
                <span>Realtime 模型</span>
                <input value={form.qwenOmniModel} onChange={(event) => updateForm('qwenOmniModel', event.target.value)} placeholder="qwen3.5-omni-plus-realtime" />
              </label>
              <label className="field-block">
                <span>输出音色</span>
                <input value={form.qwenOmniVoice} onChange={(event) => updateForm('qwenOmniVoice', event.target.value)} placeholder="Tina" />
              </label>
            </div>
            <div className="field-grid">
              <label className="field-block">
                <span>地域</span>
                <input value={form.qwenOmniRegion} onChange={(event) => updateForm('qwenOmniRegion', event.target.value)} placeholder="beijing" />
                <small>支持 beijing/cn 或 singapore/ap-southeast-1。</small>
              </label>
              <label className="field-block">
                <span>Workspace ID</span>
                <input value={form.qwenOmniWorkspaceId} onChange={(event) => updateForm('qwenOmniWorkspaceId', event.target.value)} placeholder="百炼业务空间 ID" />
                <small>后端会根据地域自动生成官方 WebRTC Endpoint。</small>
              </label>
            </div>
            <label className="field-block">
              <span>自定义 WebRTC Endpoint（可选）</span>
              <input value={form.qwenOmniEndpoint} onChange={(event) => updateForm('qwenOmniEndpoint', event.target.value)} placeholder="https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api/v1/webrtc/realtime" />
              <small>仅代理、自定义域名或特殊部署需要填写；常规接入留空即可。</small>
            </label>
          </div>

          <div className="settings-note">
            <span>配置文件</span>
            <b>{settings.envPath}</b>
            <p>保存会写入用户端后端 .env；复盘报告文本模型会在下一次请求时热加载，实时语音配置仍需重启用户端后端。</p>
          </div>
          {message && <p className="settings-message success">{message}</p>}
          {saveError && <p className="settings-message error">{saveError}</p>}
          <div className="settings-actions">
            <button className="primary-button" type="submit" disabled={saving}>
              {saving ? '保存中...' : '保存 AI 配置'}
            </button>
            <span>保存后密钥输入框会自动清空，页面只显示脱敏状态。</span>
          </div>
        </form>
      </SectionCard>
    </section>
  );
}

const PERMISSION_OPTIONS = [
  { key: 'manageCatalog', label: '岗位知识库', desc: '维护目标岗位、专业方向与能力模型，含发布与导入' },
  { key: 'manageStudents', label: '学生管理', desc: '查看与维护学生信息、归班与重点关注，需选择数据范围' },
  { key: 'manageOrganization', label: '组织管理', desc: '维护学院、专业、班级组织结构' },
  { key: 'manageModelConfig', label: '面试模型配置', desc: '查看与配置 AI 陪练角色' },
  { key: 'viewInterviews', label: '查看训练记录', desc: '查看学生模拟训练进度与详情' },
  { key: 'viewReports', label: '报告质检', desc: '查看成长报告并执行质量复核' },
];

const permissionLabel = (key) => (PERMISSION_OPTIONS.find((option) => option.key === key) || {}).label || key;

function scopeCovers(entries, collegeId, programId, classId) {
  return (entries || []).some(
    (entry) =>
      entry.college === collegeId &&
      (!entry.program || entry.program === programId) &&
      (!entry.class || entry.class === classId),
  );
}

function ScopeTree({ colleges, programs, classes, value, onChange }) {
  const programsByCollege = useMemo(() => {
    const map = {};
    (programs || []).forEach((program) => {
      (map[program.college_id] = map[program.college_id] || []).push(program);
    });
    return map;
  }, [programs]);
  const classesByProgram = useMemo(() => {
    const map = {};
    (classes || []).forEach((classItem) => {
      (map[classItem.program_id] = map[classItem.program_id] || []).push(classItem);
    });
    return map;
  }, [classes]);

  const toggle = (entry, add) => {
    const next = (value || []).filter(
      (item) =>
        !(
          item.college === entry.college &&
          (!entry.program || item.program === entry.program) &&
          (!entry.class || item.class === entry.class)
        ),
    );
    if (add) next.push(entry);
    onChange(next);
  };

  if (!(colleges || []).length) {
    return <p className="settings-message">暂无组织结构数据，请先在「组织」页维护学院、专业与班级。</p>;
  }

  return (
    <div className="scope-tree">
      {(colleges || []).map((college) => {
        const collegeCovered = scopeCovers(value, college.id, null, null);
        const collegePrograms = programsByCollege[college.id] || [];
        return (
          <div className="scope-tree-college" key={college.id}>
            <label>
              <input
                type="checkbox"
                checked={collegeCovered}
                onChange={(event) => toggle({ college: college.id, program: '', class: '' }, event.target.checked)}
              />
              <strong>{college.name}</strong>
              <small>（整个学院）</small>
            </label>
            {!collegeCovered &&
              collegePrograms.map((program) => {
                const programCovered = scopeCovers(value, college.id, program.id, null);
                const programClasses = classesByProgram[program.id] || [];
                return (
                  <div className="scope-tree-program" key={program.id}>
                    <label>
                      <input
                        type="checkbox"
                        checked={programCovered}
                        onChange={(event) => toggle({ college: college.id, program: program.id, class: '' }, event.target.checked)}
                      />
                      {program.name}
                      <small>（整个专业）</small>
                    </label>
                    {!programCovered &&
                      programClasses.map((classItem) => (
                        <label className="scope-tree-class" key={classItem.id}>
                          <input
                            type="checkbox"
                            checked={scopeCovers(value, college.id, program.id, classItem.id)}
                            onChange={(event) => toggle({ college: college.id, program: program.id, class: classItem.id }, event.target.checked)}
                          />
                          {classItem.name}
                        </label>
                      ))}
                  </div>
                );
              })}
          </div>
        );
      })}
    </div>
  );
}

function PermissionChecklist({ options, value, onChange }) {
  return (
    <div className="permission-checklist">
      {options.map((option) => (
        <label className="permission-check" key={option.key}>
          <input
            type="checkbox"
            checked={(value || []).includes(option.key)}
            onChange={(event) => {
              const next = (value || []).filter((key) => key !== option.key);
              if (event.target.checked) next.push(option.key);
              onChange(next);
            }}
          />
          <span>
            <strong>{option.label}</strong>
            <small>{option.desc}</small>
          </span>
        </label>
      ))}
    </div>
  );
}

const PERMISSION_STATUS_LABELS = { pending: '待审核', approved: '已通过', rejected: '已驳回' };

function PermissionPage({ data }) {
  const isSuper = data.admin?.role === 'super_admin';
  const [tab, setTab] = useState(isSuper ? 'admins' : 'requests');
  const [adminUsers, setAdminUsers] = useState(data.adminUsers || []);
  const [requests, setRequests] = useState([]);
  const [org, setOrg] = useState({ colleges: [], programs: [], classes: [] });
  const [adminForm, setAdminForm] = useState({ email: '', name: '', password: '', role: '' });
  const [adminPermissions, setAdminPermissions] = useState([]);
  const [adminScope, setAdminScope] = useState([]);
  const [adminMessage, setAdminMessage] = useState('');
  const [adminError, setAdminError] = useState('');
  const [adminSaving, setAdminSaving] = useState(false);
  const [reqPermissions, setReqPermissions] = useState([]);
  const [reqScope, setReqScope] = useState([]);
  const [reqReason, setReqReason] = useState('');
  const [reqMessage, setReqMessage] = useState('');
  const [reqError, setReqError] = useState('');
  const [reqSaving, setReqSaving] = useState(false);
  const [reviewing, setReviewing] = useState('');
  const [editingAdmin, setEditingAdmin] = useState(null);
  const [editPermissions, setEditPermissions] = useState([]);
  const [editScope, setEditScope] = useState([]);
  const [editMessage, setEditMessage] = useState('');
  const [editError, setEditError] = useState('');
  const [editSaving, setEditSaving] = useState(false);

  useEffect(() => {
    adminRequest('/api/admin/organization/structure')
      .then((structure) => setOrg({ colleges: structure.colleges || [], programs: structure.programs || [], classes: structure.classes || [] }))
      .catch(() => {});
    adminRequest('/api/admin/permission-requests')
      .then((result) => setRequests(result.requests || []))
      .catch(() => {});
  }, []);

  const refreshRequests = async () => {
    const result = await adminRequest('/api/admin/permission-requests');
    setRequests(result.requests || []);
  };

  const createAdmin = async (event) => {
    event.preventDefault();
    setAdminSaving(true);
    setAdminMessage('');
    setAdminError('');
    try {
      const result = await adminRequest('/api/admin/users', {
        method: 'POST',
        body: JSON.stringify({
          ...adminForm,
          permissions: adminPermissions,
          studentScope: adminScope,
        }),
      });
      setAdminUsers((current) => [...current, result.admin]);
      setAdminForm({ email: '', name: '', password: '', role: '' });
      setAdminPermissions([]);
      setAdminScope([]);
      setAdminMessage('管理员账号已创建。');
    } catch (requestError) {
      setAdminError(requestError.message);
    } finally {
      setAdminSaving(false);
    }
  };

  const toggleAdminStatus = async (item) => {
    setAdminMessage('');
    setAdminError('');
    try {
      const result = await adminRequest(`/api/admin/users/${encodeURIComponent(item.id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: item.status === 'normal' ? 'disabled' : 'normal' }),
      });
      setAdminUsers((current) => current.map((adminItem) => (adminItem.id === item.id ? result.admin : adminItem)));
      setAdminMessage(`管理员 ${item.email} 状态已更新。`);
    } catch (requestError) {
      setAdminError(requestError.message);
    }
  };

  const openEdit = (item) => {
    setEditingAdmin(item);
    setEditPermissions(item.permissions || []);
    setEditScope(item.student_scope || []);
    setEditMessage('');
    setEditError('');
  };

  const closeEdit = () => {
    setEditingAdmin(null);
    setEditMessage('');
    setEditError('');
  };

  const saveEdit = async (event) => {
    event.preventDefault();
    setEditSaving(true);
    setEditMessage('');
    setEditError('');
    try {
      const result = await adminRequest(`/api/admin/users/${encodeURIComponent(editingAdmin.id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ permissions: editPermissions, studentScope: editScope }),
      });
      setAdminUsers((current) => current.map((adminItem) => (adminItem.id === result.admin.id ? result.admin : adminItem)));
      setEditingAdmin(null);
      setAdminMessage(`已更新 ${editingAdmin.email} 的权限。`);
    } catch (requestError) {
      setEditError(requestError.message);
    } finally {
      setEditSaving(false);
    }
  };

  const submitRequest = async (event) => {
    event.preventDefault();
    setReqSaving(true);
    setReqMessage('');
    setReqError('');
    try {
      await adminRequest('/api/admin/permission-requests', {
        method: 'POST',
        body: JSON.stringify({ permissions: reqPermissions, studentScope: reqScope, reason: reqReason }),
      });
      setReqPermissions([]);
      setReqScope([]);
      setReqReason('');
      setReqMessage('权限申请已提交，等待超级管理员审核。');
      await refreshRequests();
    } catch (requestError) {
      setReqError(requestError.message);
    } finally {
      setReqSaving(false);
    }
  };

  const reviewRequest = async (item, action) => {
    setAdminMessage('');
    setAdminError('');
    setReviewing(item.id);
    try {
      await adminRequest(`/api/admin/permission-requests/${encodeURIComponent(item.id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ action }),
      });
      await refreshRequests();
      const usersResult = await adminRequest('/api/admin/users');
      setAdminUsers(usersResult.admins || []);
      setAdminMessage(`已${action === 'approve' ? '通过' : '驳回'} ${item.requesterEmail} 的权限申请。`);
    } catch (requestError) {
      setAdminError(requestError.message);
    } finally {
      setReviewing('');
    }
  };

  const scopeText = (scope) => {
    if (!scope || scope.length === 0) return '全部';
    return scope
      .map((entry) => {
        const classItem = org.classes.find((item) => item.id === entry.class);
        if (classItem) return classItem.name;
        const program = org.programs.find((item) => item.id === entry.program);
        const college = org.colleges.find((item) => item.id === entry.college);
        if (program) return `${college?.name || ''} / ${program.name}`;
        return college?.name || entry.college;
      })
      .join('、');
  };

  return (
    <section className="settings-page">
      <div className="perm-tabs">
        {isSuper && (
          <button type="button" className={tab === 'admins' ? 'active' : ''} onClick={() => setTab('admins')}>
            <UserCog size={16} />管理员管理
          </button>
        )}
        <button type="button" className={tab === 'requests' ? 'active' : ''} onClick={() => setTab('requests')}>
          <KeyRound size={16} />权限申请
        </button>
        {isSuper && (
          <button type="button" className={tab === 'review' ? 'active' : ''} onClick={() => setTab('review')}>
            <ShieldCheck size={16} />申请审核
          </button>
        )}
      </div>

      {tab === 'admins' && (
        <SectionCard title="管理员管理" icon={<UserCog size={18} />}>
          <form className="admin-account-form" onSubmit={createAdmin}>
            <h3>创建管理员</h3>
            <div className="field-grid">
              <label className="field-block">
                <span>姓名</span>
                <input value={adminForm.name} onChange={(event) => setAdminForm((current) => ({ ...current, name: event.target.value }))} required />
              </label>
              <label className="field-block">
                <span>邮箱</span>
                <input type="email" value={adminForm.email} onChange={(event) => setAdminForm((current) => ({ ...current, email: event.target.value }))} required />
              </label>
            </div>
            <div className="field-grid">
              <label className="field-block">
                <span>初始密码</span>
                <input type="password" minLength={12} value={adminForm.password} onChange={(event) => setAdminForm((current) => ({ ...current, password: event.target.value }))} required />
                <small>至少 12 位，创建后请通过安全渠道交付。</small>
              </label>
              <label className="field-block">
                <span>角色名称</span>
                <input value={adminForm.role} onChange={(event) => setAdminForm((current) => ({ ...current, role: event.target.value }))} placeholder="例如 系统管理员 / 报告审核员" />
                <small>角色名称仅作展示标签，权限由下方权限点决定。</small>
              </label>
            </div>
            <div className="field-block">
              <span>授予权限</span>
              <PermissionChecklist options={PERMISSION_OPTIONS} value={adminPermissions} onChange={setAdminPermissions} />
            </div>
            <div className="field-block">
              <span>学生数据范围</span>
              <small className="field-hint">勾选「学生管理」权限时，需指定该管理员可管理的学院 / 专业 / 班级（可多选，跨范围）。</small>
              <ScopeTree colleges={org.colleges} programs={org.programs} classes={org.classes} value={adminScope} onChange={setAdminScope} />
            </div>
            {adminMessage && <p className="settings-message success">{adminMessage}</p>}
            {adminError && <p className="settings-message error">{adminError}</p>}
            <button className="primary-button" type="submit" disabled={adminSaving}>
              {adminSaving ? '创建中...' : '创建管理员'}
            </button>
          </form>
          <div className="admin-account-list">
            <h3>管理员账号（{adminUsers.length}）</h3>
            {adminUsers.length === 0 && <EmptyState text="暂无管理员账号" />}
            {adminUsers.map((item) => (
              <article key={item.id}>
                <div>
                  <strong>{item.name}</strong>
                  <span>{item.email}</span>
                  <small>
                    {item.role || '管理员'} · {item.status === 'normal' ? '正常' : '已禁用'}
                  </small>
                  <small className="perm-badge">
                    {(item.permissions || []).map(permissionLabel).join('、') || '无权限'}
                  </small>
                  <small className="perm-badge">范围：{scopeText(item.student_scope)}</small>
                </div>
                <div className="admin-row-actions">
                  <button
                    className="edit-perm-btn"
                    type="button"
                    disabled={item.email === data.admin?.email}
                    onClick={() => openEdit(item)}
                  >
                    编辑权限
                  </button>
                  <button
                    type="button"
                    disabled={item.email === data.admin?.email}
                    onClick={() => toggleAdminStatus(item)}
                  >
                    {item.status === 'normal' ? '禁用' : '启用'}
                  </button>
                </div>
              </article>
            ))}
          </div>
          <h3 className="audit-title">最近审计记录</h3>
          <div className="audit-list">
            {data.auditLogs.length === 0 && <EmptyState text="暂无审计记录" />}
            {data.auditLogs.map((log) => (
              <div key={log.id || `${log.action}-${log.time}`}>
                <span>{log.actor}</span>
                <strong>{log.action}</strong>
                <small>{log.target} · {log.time}</small>
                {log.summary && <small>{log.summary}</small>}
              </div>
            ))}
          </div>
        </SectionCard>
      )}

      {tab === 'requests' && (
        <SectionCard title="权限申请" icon={<KeyRound size={18} />}>
          {!isSuper && (
            <p className="settings-message">
              作为下级管理员，你可以提交权限与数据范围申请，由超级管理员审核后生效。
            </p>
          )}
          <form className="admin-account-form" onSubmit={submitRequest}>
            <h3>申请权限或数据范围</h3>
            <div className="field-block">
              <span>申请权限</span>
              <PermissionChecklist options={PERMISSION_OPTIONS} value={reqPermissions} onChange={setReqPermissions} />
            </div>
            <div className="field-block">
              <span>申请数据范围</span>
              <small className="field-hint">仅当申请「学生管理」相关能力时填写。</small>
              <ScopeTree colleges={org.colleges} programs={org.programs} classes={org.classes} value={reqScope} onChange={setReqScope} />
            </div>
            <label className="field-block">
              <span>申请理由</span>
              <textarea rows={3} maxLength={500} value={reqReason} onChange={(event) => setReqReason(event.target.value)} placeholder="请说明为什么需要这些权限，便于超级管理员审核。" />
            </label>
            {reqMessage && <p className="settings-message success">{reqMessage}</p>}
            {reqError && <p className="settings-message error">{reqError}</p>}
            <button className="primary-button" type="submit" disabled={reqSaving || (reqPermissions.length === 0 && reqScope.length === 0)}>
              {reqSaving ? '提交中...' : '提交申请'}
            </button>
          </form>
          <div className="admin-account-list">
            <h3>我的申请记录</h3>
            {requests.length === 0 && <EmptyState text="暂无申请记录" />}
            {requests.map((item) => (
              <article key={item.id}>
                <div>
                  <strong>{item.requesterName || item.requesterEmail}</strong>
                  <small>
                    {(item.permissions || []).map(permissionLabel).join('、') || '无权限'} · 范围：
                    {scopeText(item.studentScope) || '全部'}
                  </small>
                  {item.reason && <small>{item.reason}</small>}
                  <small>{item.createdAt} · {item.reviewedBy ? `审核人：${item.reviewedBy}` : ''}</small>
                </div>
                <b className={`perm-status ${item.status}`}>{PERMISSION_STATUS_LABELS[item.status] || item.status}</b>
              </article>
            ))}
          </div>
        </SectionCard>
      )}

      {tab === 'review' && (
        <SectionCard title="申请审核" icon={<ShieldCheck size={18} />}>
          {(adminMessage || adminError) && (
            <p className={`settings-message ${adminError ? 'error' : 'success'}`}>{adminError || adminMessage}</p>
          )}
          <div className="admin-account-list">
            <h3>待审核申请</h3>
            {requests.filter((item) => item.status === 'pending').length === 0 && (
              <EmptyState text="暂无待审核的权限申请" />
            )}
            {requests
              .filter((item) => item.status === 'pending')
              .map((item) => (
                <article key={item.id}>
                  <div>
                    <strong>{item.requesterName || item.requesterEmail}</strong>
                    <span>{item.requesterEmail}</span>
                    <small>
                      {(item.permissions || []).map(permissionLabel).join('、') || '无权限'} · 范围：
                      {scopeText(item.studentScope) || '全部'}
                    </small>
                    {item.reason && <small>{item.reason}</small>}
                    <small>{item.createdAt}</small>
                  </div>
                  <div className="review-actions">
                    <button type="button" disabled={reviewing === item.id} onClick={() => reviewRequest(item, 'approve')}>
                      {reviewing === item.id ? '处理中...' : '通过'}
                    </button>
                    <button type="button" disabled={reviewing === item.id} onClick={() => reviewRequest(item, 'reject')}>
                      驳回
                    </button>
                  </div>
                </article>
              ))}
          </div>
          <div className="admin-account-list">
            <h3>已处理申请</h3>
            {requests.filter((item) => item.status !== 'pending').length === 0 && <EmptyState text="暂无已处理的申请" />}
            {requests
              .filter((item) => item.status !== 'pending')
              .map((item) => (
                <article key={item.id}>
                  <div>
                    <strong>{item.requesterName || item.requesterEmail}</strong>
                    <small>
                      {(item.permissions || []).map(permissionLabel).join('、') || '无权限'} · 范围：
                      {scopeText(item.studentScope) || '全部'}
                    </small>
                    <small>{item.createdAt} · 审核人：{item.reviewedBy || '-'} · {item.reviewedAt}</small>
                  </div>
                  <b className={`perm-status ${item.status}`}>{PERMISSION_STATUS_LABELS[item.status] || item.status}</b>
                </article>
              ))}
          </div>
        </SectionCard>
      )}

      {editingAdmin && (
        <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="编辑管理员权限" onClick={closeEdit}>
          <div className="modal-card perm-edit-modal" onClick={(event) => event.stopPropagation()}>
            <header>
              <span><ShieldCheck size={18} />编辑权限 · {editingAdmin.email}</span>
              <button className="icon-button" type="button" title="关闭" onClick={closeEdit}><X size={17} /></button>
            </header>
            <p>取消勾选权限点即可回收对应权限，调整学生数据范围；保存后立即生效。</p>
            <form className="admin-account-form" onSubmit={saveEdit}>
              <div className="field-block">
                <span>授予权限</span>
                <PermissionChecklist options={PERMISSION_OPTIONS} value={editPermissions} onChange={setEditPermissions} />
              </div>
              <div className="field-block">
                <span>学生数据范围</span>
                <small className="field-hint">仅当勾选「学生管理」权限时生效。</small>
                <ScopeTree colleges={org.colleges} programs={org.programs} classes={org.classes} value={editScope} onChange={setEditScope} />
              </div>
              {editMessage && <p className="settings-message success">{editMessage}</p>}
              {editError && <p className="settings-message error">{editError}</p>}
              <footer>
                <button type="button" onClick={closeEdit}>取消</button>
                <button className="primary-button" type="submit" disabled={editSaving}>
                  {editSaving ? '保存中...' : '保存权限'}
                </button>
              </footer>
            </form>
          </div>
        </div>
      )}
    </section>
  );
}

const pageDescriptions = {
  dashboard: '集中处理今天最需要关注的任务',
  guide: '按步骤了解管理端从初始化到日常运营的完整流程',
  interviews: '查看学生模拟训练进度与 AI 陪练运行情况',
  reports: '抽检成长报告的准确性与建议质量',
  organization: '维护学院、专业、班级和学生组织归属',
  organizationConfig: '组织结构一览，从用户注册导入表一键生成组织结构',
  registrations: '学生注册：导入学生，候选人端凭学号与姓名登录',
  catalog: '维护目标岗位、专业方向与能力模型',
  agents: '查看 AI 陪练角色及使用情况',
  connectionLogs: '排查千问 WebRTC 的 ICE、SDP、数据通道和音频链路',
  settings: '管理服务配置、管理员与审计记录',
  permission: '创建下级管理员、分配权限与数据范围，审核下级权限申请',
};

const searchableViews = new Set(['interviews', 'reports', 'agents']);

const roleCapabilityHints = {
  super_admin: '（超级管理员）可访问本页全部模块，负责系统初始化与全局配置',
};

const guideFlow = [
  {
    key: 'setup',
    title: '第一步 · 系统初始化',
    icon: 'Lightbulb',
    desc: '在上线前先把基础配置、组织结构和账号体系准备好，候选人才有可用的登录与训练环境。',
    steps: [
      { view: 'settings', text: '在「系统管理」中配置报告大模型 / 供应商，以及质检相关规则。' },
      { view: 'organization', text: '在「组织与学生」中维护学院、专业、班级等组织归属，保证学生归班准确。' },
      { view: 'registrations', text: '在「学生」页点击「学生注册」导入学生，候选人端凭学号与姓名即可登录。' },
    ],
  },
  {
    key: 'content',
    title: '第二步 · 搭建训练内容',
    icon: 'BookOpen',
    desc: '训练内容决定学生练什么、AI 以什么角色陪练，是训练质量的基础。',
    steps: [
      { view: 'catalog', text: '在「岗位与能力」中维护目标岗位、专业方向与能力模型。' },
      { view: 'agents', text: '在「AI 陪练角色」中查看陪练角色配置与实际使用情况。' },
    ],
  },
  {
    key: 'operation',
    title: '第三步 · 日常运营',
    icon: 'Activity',
    desc: '上线后每天从工作台入口开始，跟进训练进度与报告质量。',
    steps: [
      { view: 'dashboard', text: '在「工作台」集中处理今日待办：待复核报告、进行中的面试。' },
      { view: 'interviews', text: '在「训练记录」查看学生模拟训练进度与 AI 陪练运行情况。' },
      { view: 'reports', text: '在「报告质检」抽检成长报告的准确性与建议质量。' },
    ],
  },
  {
    key: 'maintain',
    title: '第四步 · 系统维护',
    icon: 'Wifi',
    desc: '出现链路异常或需要审计时，在系统模块定位和排查问题。',
    steps: [
      { view: 'connectionLogs', text: '在「连接日志」排查千问 WebRTC 的 ICE、SDP、数据通道和音频链路。' },
      { view: 'settings', text: '在「系统管理」管理全局配置、管理员账号并查看审计记录。' },
    ],
  },
];

function GuidePage({ onNavigate, admin }) {
  return (
    <div className="guide-page">
      <section className="dashboard-welcome guide-welcome">
        <div>
          <span><ListOrdered size={16} /> 使用流程指引</span>
          <h2>管理端完整使用流程</h2>
          <p>从系统初始化到日常运营，按步骤完成即可顺畅运行 AI 面试陪练平台。{roleCapabilityHints[admin?.role] || ''}</p>
        </div>
        <span className="connection-pill"><i /> 流程概览</span>
      </section>

      <div className="guide-flow">
        {guideFlow.map((phase) => {
          const Icon = phase.icon === 'Lightbulb' ? Lightbulb : phase.icon === 'BookOpen' ? BookOpen : phase.icon === 'Activity' ? Activity : Wifi;
          return (
            <section className="guide-phase" key={phase.key}>
              <header className="guide-phase-header">
                <div className="guide-phase-icon"><Icon size={18} /></div>
                <div>
                  <h3>{phase.title}</h3>
                  <p>{phase.desc}</p>
                </div>
              </header>
              <div className="guide-steps">
                {phase.steps.map((step) => (
                  <button
                    className="guide-step"
                    key={step.view}
                    type="button"
                    onClick={() => onNavigate(step.view)}
                    title={`前往「${step.view}」`}
                  >
                    <span className="guide-step-index"><MousePointerClick size={14} /></span>
                    <span className="guide-step-text">{step.text}</span>
                    <ChevronRight size={15} className="guide-step-arrow" />
                  </button>
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}

const emptyOrgStructure = {
  colleges: [],
  programs: [],
  classes: [],
  standardMajors: [],
  summary: { colleges: 0, programs: 0, classes: 0, students: 0, unassigned: 0, focus: 0 },
};

function OrganizationConfigPage({ onNavigate }) {
  const [structure, setStructure] = useState(emptyOrgStructure);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState('');
  const [notice, setNotice] = useState('');
  const [creator, setCreator] = useState('college');
  const [collegeForm, setCollegeForm] = useState({ code: '', name: '' });
  const [programForm, setProgramForm] = useState({ collegeId: '', standardMajorCode: '', name: '', direction: '', coordinator: '' });
  const [classForm, setClassForm] = useState({ programId: '', name: '', graduationYear: '', advisor: '', inviteCode: '' });
  const [configBusy, setConfigBusy] = useState('');

  const loadStructure = async () => {
    setLoading(true);
    setPageError('');
    try {
      const data = await adminRequest('/api/admin/organization/structure');
      setStructure({
        colleges: data.colleges || [],
        programs: data.programs || [],
        classes: data.classes || [],
        standardMajors: data.standardMajors || [],
        summary: { ...emptyOrgStructure.summary, ...(data.summary || {}) },
      });
    } catch (requestError) {
      setPageError(requestError.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStructure();
  }, []);

  const createOrganizationItem = async (event) => {
    event.preventDefault();
    const config = {
      college: { path: '/api/admin/campus/colleges', body: collegeForm, label: '学院' },
      program: { path: '/api/admin/campus/programs', body: programForm, label: '专业' },
      class: { path: '/api/admin/campus/classes', body: classForm, label: '班级' },
    }[creator];
    setConfigBusy(`create-${creator}`);
    setPageError('');
    setNotice('');
    try {
      await adminRequest(config.path, { method: 'POST', body: JSON.stringify(config.body) });
      setCollegeForm({ code: '', name: '' });
      setProgramForm({ collegeId: '', standardMajorCode: '', name: '', direction: '', coordinator: '' });
      setClassForm({ programId: '', name: '', graduationYear: '', advisor: '', inviteCode: '' });
      setNotice(`${config.label}创建成功`);
      await loadStructure();
    } catch (requestError) {
      setPageError(requestError.message);
    } finally {
      setConfigBusy('');
    }
  };

  const { colleges, programs, classes } = structure;

  return (
    <div className="org-page">
      <SectionCard
        title="组织结构"
        icon={<Network size={18} />}
        action={<button className="section-link" type="button" onClick={() => onNavigate('organization')}>进入学生管理 <ChevronRight size={14} /></button>}
      >
        {loading ? (
          <div className="page-message loading-state"><RefreshCw size={18} className="spin" />正在读取组织结构</div>
        ) : pageError ? (
          <div className="page-message error"><AlertCircle size={18} />{pageError}<button type="button" onClick={loadStructure}>重新加载</button></div>
        ) : colleges.length === 0 ? (
          <div className="page-message">当前还没有组织结构，请先导入用户注册表一键生成。</div>
        ) : (
          <div className="campus-tree">
            <button type="button" className="active">
              <span><UsersRound size={15} />全部学生</span><b>{structure.summary.students}</b>
            </button>
            <button type="button" className="warning">
              <span><AlertCircle size={15} />未归班</span><b>{structure.summary.unassigned}</b>
            </button>
            {colleges.map((college) => (
              <div className="campus-college-node" key={college.id}>
                <button type="button">
                  <span><Building2 size={15} />{college.name}</span><b>{college.studentCount || 0}</b>
                </button>
                <div>
                  {programs.filter((program) => program.college_id === college.id).map((program) => (
                    <div className="campus-program-node" key={program.id}>
                      <button type="button">
                        <span><GraduationCap size={14} />{program.name}{program.direction ? ` · ${program.direction}` : ''}</span><b>{program.studentCount || 0}</b>
                      </button>
                      <div>
                        {classes.filter((classItem) => classItem.program_id === program.id).map((classItem) => (
                          <button type="button" key={classItem.id}>
                            <span>{classItem.graduation_year ? `${classItem.graduation_year}届 · ` : ''}{classItem.name}</span><b>{classItem.studentCount || 0}</b>
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      <section className="org-config-single">
        <SectionCard title="组织配置" icon={<Plus size={18} />}>
          <div className="campus-config-tabs">
            {[['college', '添加学院'], ['program', '添加专业'], ['class', '添加班级']].map(([key, label]) => <button type="button" key={key} className={creator === key ? 'active' : ''} onClick={() => setCreator(key)}>{label}</button>)}
          </div>
          <form className="campus-create-form" onSubmit={createOrganizationItem}>
            {creator === 'college' && (
              <>
                <label className="field-block"><span>学院编码</span><input value={collegeForm.code} onChange={(event) => setCollegeForm((current) => ({ ...current, code: event.target.value }))} placeholder="例如 CS" required /></label>
                <label className="field-block"><span>学院名称</span><input value={collegeForm.name} onChange={(event) => setCollegeForm((current) => ({ ...current, name: event.target.value }))} placeholder="例如 计算机学院" required /></label>
              </>
            )}
            {creator === 'program' && (
              <>
                <label className="field-block"><span>所属学院</span><select value={programForm.collegeId} onChange={(event) => setProgramForm((current) => ({ ...current, collegeId: event.target.value }))} required><option value="">请选择学院</option>{structure.colleges.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
                <label className="field-block"><span>标准专业</span><select value={programForm.standardMajorCode} onChange={(event) => { const major = structure.standardMajors.find((item) => item.code === event.target.value); setProgramForm((current) => ({ ...current, standardMajorCode: event.target.value, name: major?.name || current.name })); }}><option value="">自定义专业</option>{structure.standardMajors.map((item) => <option value={item.code} key={item.id}>{item.name} · {item.code}</option>)}</select></label>
                <label className="field-block"><span>学校专业名称</span><input value={programForm.name} onChange={(event) => setProgramForm((current) => ({ ...current, name: event.target.value }))} placeholder="例如 软件工程" required /></label>
                <label className="field-block"><span>培养方向</span><input value={programForm.direction} onChange={(event) => setProgramForm((current) => ({ ...current, direction: event.target.value }))} placeholder="例如 Java 开发" /></label>
                <label className="field-block"><span>专业负责人</span><input value={programForm.coordinator} onChange={(event) => setProgramForm((current) => ({ ...current, coordinator: event.target.value }))} placeholder="姓名" /></label>
              </>
            )}
            {creator === 'class' && (
              <>
                <label className="field-block"><span>所属专业</span><select value={classForm.programId} onChange={(event) => setClassForm((current) => ({ ...current, programId: event.target.value }))} required><option value="">请选择专业</option>{structure.programs.map((item) => <option value={item.id} key={item.id}>{item.college_name} · {item.name}</option>)}</select></label>
                <label className="field-block"><span>班级名称</span><input value={classForm.name} onChange={(event) => setClassForm((current) => ({ ...current, name: event.target.value }))} placeholder="例如 软件工程1班" required /></label>
                <label className="field-block"><span>毕业年份</span><input type="number" min="2000" max="2100" value={classForm.graduationYear} onChange={(event) => setClassForm((current) => ({ ...current, graduationYear: event.target.value }))} placeholder="2026" /></label>
                <label className="field-block"><span>辅导员</span><input value={classForm.advisor} onChange={(event) => setClassForm((current) => ({ ...current, advisor: event.target.value }))} placeholder="姓名" /></label>
                <label className="field-block"><span>邀请码（可选）</span><input value={classForm.inviteCode} onChange={(event) => setClassForm((current) => ({ ...current, inviteCode: event.target.value }))} placeholder="留空自动生成" /></label>
              </>
            )}
            <button className="primary-button" type="submit" disabled={configBusy === `create-${creator}`}>{configBusy === `create-${creator}` ? '创建中…' : '确认创建'}</button>
          </form>
        </SectionCard>
      </section>
    </div>
  );
}

function initialAdminView() {
  const hashView = window.location.hash.replace(/^#\/?/, '').split('?')[0];
  return navItems.some((item) => item.key === hashView) ? hashView : 'dashboard';
}

function AdminApp({ admin, onSignedOut }) {
  const [activeView, setActiveView] = useState(initialAdminView);
  const [adminData, setAdminData] = useState(emptyAdminData);
  const [registrationsOpen, setRegistrationsOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [lastUpdated, setLastUpdated] = useState(null);
  const [searchByView, setSearchByView] = useState({});
  const [viewPreset, setViewPreset] = useState({ view: '', value: '' });
  const [detail, setDetail] = useState(null);
  const [detailContext, setDetailContext] = useState({ type: '', rows: [], currentKey: '' });
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [notice, setNotice] = useState('');
  const visibleNavItems = useMemo(
    () => navItems.filter((item) => !item.permission || adminData.permissions?.[item.permission]),
    [adminData.permissions],
  );
  const activeItem = useMemo(() => visibleNavItems.find((item) => item.key === activeView), [activeView, visibleNavItems]);
  const pendingReportCount = adminData.reports.filter((report) => report.reviewStatus === '待复核').length;
  const runningInterviewCount = adminData.interviews.filter((interview) => interview.status === '进行中').length;
  const currentQuery = searchByView[activeView] || '';

  const setCurrentQuery = (value) => {
    setSearchByView((current) => ({ ...current, [activeView]: value }));
  };

  const navigateTo = (view, filter = '') => {
    setActiveView(view);
    setViewPreset({ view, value: filter });
    window.history.replaceState(null, '', `#/${view}`);
  };

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    adminRequest('/api/admin/snapshot')
      .then((data) => {
        if (mounted) {
          setAdminData({ ...emptyAdminData, ...data });
          setError('');
          setLastUpdated(new Date());
        }
      })
      .catch((requestError) => {
        if (!mounted) return;
        if (requestError.status === 401) {
          onSignedOut(false);
          return;
        }
        setError(requestError.message);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [onSignedOut]);

  useEffect(() => {
    const syncViewFromHash = () => {
      const nextView = initialAdminView();
      if (visibleNavItems.some((item) => item.key === nextView)) setActiveView(nextView);
    };
    window.addEventListener('hashchange', syncViewFromHash);
    return () => window.removeEventListener('hashchange', syncViewFromHash);
  }, [visibleNavItems]);

  useEffect(() => {
    if (!loading && !visibleNavItems.some((item) => item.key === activeView)) navigateTo('dashboard');
  }, [activeView, loading, visibleNavItems]);

  useEffect(() => {
    if (!notice) return undefined;
    const timer = window.setTimeout(() => setNotice(''), 2800);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const refreshSnapshot = async () => {
    setRefreshing(true);
    try {
      const data = await adminRequest('/api/admin/snapshot');
      setAdminData({ ...emptyAdminData, ...data });
      setError('');
      setLastUpdated(new Date());
      setNotice('数据已刷新');
    } catch (requestError) {
      if (requestError.status === 401) onSignedOut(false);
      else setError(requestError.message);
    } finally {
      setRefreshing(false);
    }
  };

  const openDetail = async (type, row, contextRows = [row]) => {
    const paths = {
      candidate: `/api/admin/candidates/${encodeURIComponent(row.id)}`,
      interview: `/api/admin/interviews/${encodeURIComponent(row.id)}`,
      report: `/api/admin/reports/${encodeURIComponent(row.id)}`,
      agent: `/api/admin/agents/${encodeURIComponent(row.name)}`,
    };
    const currentKey = type === 'agent' ? row.name : row.id;
    setDetailContext({ type, rows: contextRows, currentKey });
    setDetail(formatDetail(type, {}, row));
    setDetailLoading(true);
    setDetailError('');
    try {
      const payload = await adminRequest(paths[type]);
      setDetail(formatDetail(type, payload, row));
    } catch (requestError) {
      setDetailError(requestError.message);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleSettingsSaved = (settings) => {
    setAdminData((current) => ({
      ...current,
      settings: { ...current.settings, ...settings },
    }));
  };

  const closeDetail = () => {
    setDetail(null);
    setDetailContext({ type: '', rows: [], currentKey: '' });
    setDetailError('');
    setDetailLoading(false);
  };

  const detailIndex = detailContext.rows.findIndex((row) => (detailContext.type === 'agent' ? row.name : row.id) === detailContext.currentKey);
  const detailPosition = {
    current: detailIndex >= 0 ? detailIndex + 1 : 1,
    total: detailContext.rows.length || 1,
    hasPrevious: detailIndex > 0,
    hasNext: detailIndex >= 0 && detailIndex < detailContext.rows.length - 1,
  };

  const moveDetail = (offset) => {
    const nextRow = detailContext.rows[detailIndex + offset];
    if (nextRow) openDetail(detailContext.type, nextRow, detailContext.rows);
  };

  const reviewReport = async (status) => {
    if (!detail?.id) return;
    setDetailLoading(true);
    setDetailError('');
    try {
      const payload = await adminRequest(`/api/admin/reports/${encodeURIComponent(detail.id)}/review`, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      });
      setDetail(formatDetail('report', payload, payload.report || {}));
      setAdminData((current) => ({
        ...current,
        reports: current.reports.map((item) => item.id === detail.id
          ? { ...item, reviewStatus: status === 'approved' ? '已复核' : status === 'rejected' ? '复核未通过' : '待复核' }
          : item),
      }));
      setNotice(status === 'approved' ? '报告已通过复核' : status === 'rejected' ? '报告已标记为未通过' : '报告已退回待复核');
    } catch (requestError) {
      setDetailError(requestError.message);
    } finally {
      setDetailLoading(false);
    }
  };

  const revealTemporaryPassword = async () => {
    if (!detail?.id) return;
    setDetailLoading(true);
    setDetailError('');
    try {
      const payload = await adminRequest(`/api/admin/student-accounts/${encodeURIComponent(detail.id)}/temporary-password`);
      setDetail((current) => ({ ...current, temporaryPassword: payload.temporaryPassword }));
    } catch (requestError) {
      setDetailError(requestError.message);
    } finally {
      setDetailLoading(false);
    }
  };

  const resetStudentPassword = async () => {
    if (!detail?.id || !window.confirm('重置后学生当前密码和全部登录状态都会失效，确定继续吗？')) return;
    setDetailLoading(true);
    setDetailError('');
    try {
      const payload = await adminRequest(`/api/admin/student-accounts/${encodeURIComponent(detail.id)}/reset-password`, { method: 'POST' });
      setDetail((current) => ({
        ...current,
        mustChangePassword: true,
        canViewTemporaryPassword: true,
        temporaryPassword: payload.temporaryPassword,
        rows: current.rows.map((row) => row.label === '激活状态' ? { ...row, value: '待首次改密' } : row),
      }));
      setNotice('已生成新的临时密码并撤销学生原有登录状态');
      const data = await adminRequest('/api/admin/snapshot');
      setAdminData({ ...emptyAdminData, ...data });
    } catch (requestError) {
      setDetailError(requestError.message);
    } finally {
      setDetailLoading(false);
    }
  };

  const renderContent = () => {
    if (loading) return <div className="page-message loading-state"><RefreshCw size={18} className="spin" />正在读取管理数据</div>;
    if (error) return <div className="page-message error"><AlertCircle size={18} />{error}<button type="button" onClick={refreshSnapshot}>重新加载</button></div>;
    if (activeView === 'guide') return <GuidePage onNavigate={navigateTo} admin={admin} />;
    if (activeView === 'catalog') return <CatalogPage permissions={adminData.permissions || {}} />;
    if (activeView === 'organization') return <OrganizationPage onView={openDetail} />;
    if (activeView === 'organizationConfig') return <OrganizationConfigPage onNavigate={navigateTo} />;
    const listProps = {
      data: adminData,
      onView: openDetail,
      query: currentQuery,
      onQueryChange: setCurrentQuery,
      presetFilter: viewPreset.view === activeView ? viewPreset.value : '',
    };
    if (activeView === 'candidates') return <CandidatesPage {...listProps} onAccountsChanged={refreshSnapshot} />;
    if (activeView === 'interviews') return <InterviewsPage {...listProps} />;
    if (activeView === 'reports') return <ReportsPage {...listProps} />;
    if (activeView === 'agents') return <AgentsPage {...listProps} />;
    if (activeView === 'connectionLogs') return <ConnectionLogsPage />;
    if (activeView === 'permission') return <PermissionPage data={adminData} />;
    if (activeView === 'settings') return <SettingsPage data={adminData} onSettingsSaved={handleSettingsSaved} />;
    return <Dashboard data={adminData} admin={admin} onNavigate={navigateTo} onView={openDetail} />;
  };

  return (
    <main className="admin-shell">
      <aside className="admin-sidebar">
        <div className="admin-user">
          <LockKeyhole size={16} />
          <span>
            <strong>{admin?.name || admin?.email}</strong>
            {roleLabels[admin?.role] || admin?.role}
          </span>
          <button type="button" aria-label="退出管理端" title="退出管理端" onClick={() => onSignedOut(true)}>
            <LogOut size={15} />
          </button>
        </div>

        <nav className="admin-nav" aria-label="管理端导航">
          {visibleNavItems.map((item) => {
            const Icon = item.icon;
            const badge = item.key === 'reports' ? pendingReportCount : item.key === 'interviews' ? runningInterviewCount : 0;
            return (
              <button
                className={activeView === item.key ? 'active' : ''}
                key={item.key}
                type="button"
                onClick={() => navigateTo(item.key)}
              >
                <Icon size={17} />
                <span>{item.label}</span>
                {badge > 0 && <b>{badge}</b>}
              </button>
            );
          })}
        </nav>
      </aside>

      <section className="admin-main">
        <header className="admin-topbar">
          <div className="page-heading">
            <p>Management Console / {activeItem?.group || '工作台'}</p>
            <h1>{activeItem?.label || '工作台'}</h1>
            <span>{pageDescriptions[activeView]}</span>
          </div>
          <div className="topbar-actions">
            {activeView === 'organization' && (
              <button className="primary-button" type="button" onClick={() => setRegistrationsOpen(true)}><UserPlus size={15} />学生注册</button>
            )}
            {searchableViews.has(activeView) && (
              <label className="admin-search">
                <Search size={16} />
                <input value={currentQuery} onChange={(event) => setCurrentQuery(event.target.value)} placeholder={`搜索当前${activeItem?.label || '页面'}`} />
                {currentQuery && <button type="button" onClick={() => setCurrentQuery('')} aria-label="清空搜索"><X size={14} /></button>}
              </label>
            )}
            <span className={`topbar-connection ${error ? 'error' : ''}`} title={ADMIN_API_BASE_URL}>
              <i />{error ? '连接异常' : '服务正常'}
            </span>
            <button className="icon-button" type="button" disabled={refreshing} onClick={refreshSnapshot} aria-label="刷新数据" title={lastUpdated ? `上次更新 ${lastUpdated.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}` : '刷新数据'}>
              <RefreshCw size={17} className={refreshing ? 'spin' : ''} />
            </button>
          </div>
        </header>

        {renderContent()}
      </section>
      {notice && <div className="admin-toast" role="status"><CheckCircle2 size={17} />{notice}</div>}
      <DetailDrawer
        detail={detail}
        loading={detailLoading}
        error={detailError}
        onReview={reviewReport}
canReview={adminData.permissions?.canViewReports}
onRevealTemporaryPassword={revealTemporaryPassword}
onResetStudentPassword={resetStudentPassword}
onClose={closeDetail}
onMove={moveDetail}
position={detailPosition}
/>
        onClose={closeDetail}
        onMove={moveDetail}
        position={detailPosition}
      />

      {registrationsOpen && (
        <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="学生注册" onClick={() => setRegistrationsOpen(false)}>
          <div className="modal-card resg-modal" onClick={(event) => event.stopPropagation()}>
            <header>
              <span><UserPlus size={18} />学生注册</span>
              <button className="icon-button" type="button" title="关闭" onClick={() => setRegistrationsOpen(false)}><X size={17} /></button>
            </header>
            <RegistrationsPage />
          </div>
        </div>
      )}
    </main>
  );
}

function AdminRoot() {
  const [admin, setAdmin] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);

  useEffect(() => {
    let mounted = true;
    adminRequest('/api/admin/auth/me')
      .then((data) => {
        if (mounted) setAdmin(data.admin || null);
      })
      .catch(() => {
        if (mounted) setAdmin(null);
      })
      .finally(() => {
        if (mounted) setCheckingSession(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const handleSignedOut = async (notifyServer = true) => {
    if (notifyServer) {
      await adminRequest('/api/admin/auth/logout', { method: 'POST' }).catch(() => {});
    }
    setAdmin(null);
  };

  if (checkingSession) {
    return <div className="admin-session-loading">正在验证管理员登录状态</div>;
  }
  if (!admin) {
    return <AdminLogin onAuthenticated={setAdmin} />;
  }
  return <AdminApp admin={admin} onSignedOut={handleSignedOut} />;
}

createRoot(document.getElementById('root')).render(<AdminRoot />);
