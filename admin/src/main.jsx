import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  AlertCircle,
  BarChart3,
  Bot,
  BookOpen,
  ChevronRight,
  CheckCircle2,
  ClipboardList,
  FileText,
  Gauge,
  KeyRound,
  LayoutDashboard,
  LockKeyhole,
  LogOut,
  Plus,
  RefreshCw,
  Rocket,
  Search,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  UserCog,
  UsersRound,
  Upload,
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

const navItems = [
  { key: 'dashboard', label: '总览', icon: LayoutDashboard },
  { key: 'catalog', label: '职业目录', icon: BookOpen, permission: 'canViewCatalog' },
  { key: 'candidates', label: '用户与候选人', icon: UsersRound, permission: 'canViewCandidates' },
  { key: 'interviews', label: '面试运营', icon: ClipboardList, permission: 'canViewInterviews' },
  { key: 'reports', label: '报告与复核', icon: FileText, permission: 'canViewReports' },
  { key: 'agents', label: 'Agent 与模板', icon: Bot, permission: 'canViewAgents' },
  { key: 'settings', label: '系统与权限', icon: Settings, permission: 'canManageSettings' },
];

const roleLabels = {
  super_admin: '超级管理员',
  operations: '运营管理员',
  reviewer: '报告审核员',
};

const statusTone = {
  正常: 'green',
  观察: 'amber',
  进行中: 'blue',
  已完成: 'green',
  草稿: 'gray',
  待抽检: 'blue',
  已复核: 'green',
  需要复核: 'red',
  启用: 'green',
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
          <p>登录后才能查看候选人、面试报告和系统配置。</p>
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

function AdminTable({ columns, rows, onView }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
            <th aria-label="操作" />
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={columns.length + 1}>
                <EmptyState />
              </td>
            </tr>
          )}
          {rows.map((row) => (
            <tr key={row.id || row.name}>
              {columns.map((column) => (
                <td key={column.key}>{column.render ? column.render(row) : row[column.key]}</td>
              ))}
              <td className="row-action">
                <button type="button" onClick={() => onView?.(row)}>
                  查看
                  <ChevronRight size={15} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DetailModal({ detail, loading, error, onClose, onReview, canReview }) {
  if (!detail && !loading && !error) return null;
  const title = detail?.title || '详情';
  const rows = detail?.rows || [];
  const blocks = detail?.blocks || [];
  return (
    <div className="modal-backdrop" role="presentation">
      <section className="detail-modal" role="dialog" aria-modal="true" aria-label={title}>
        <header>
          <div>
            <span>Detail</span>
            <h2>{title}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="关闭详情">
            <X size={18} />
          </button>
        </header>
        {loading && <div className="page-message">正在读取详情</div>}
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
                ) : (
                  <p>{block.text || '暂无内容'}</p>
                )}
              </section>
            ))}
            {detail?.type === 'report' && canReview && (
              <div className="detail-actions">
                <button type="button" onClick={() => onReview('approved')}>通过复核</button>
                <button type="button" className="danger" onClick={() => onReview('rejected')}>标记未通过</button>
              </div>
            )}
          </div>
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
      title: `候选人 · ${item.name || item.nickname || fallbackRow.name}`,
      rows: [
        { label: '邮箱', value: item.email },
        { label: '状态', value: item.status },
        { label: '目标岗位', value: item.target_role || item.role },
        { label: '经验水平', value: item.experience_level },
        { label: '目标城市', value: item.target_city },
        { label: '期望薪资', value: item.expected_salary },
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
      title: `面试 · ${interview.target_role || fallbackRow.role}`,
      rows: [
        { label: '候选人', value: interview.candidate },
        { label: '邮箱', value: interview.candidate_email },
        { label: '面试类型', value: interview.interview_type || fallbackRow.type },
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
        { label: '录用建议', value: report.pass_recommendation || report.recommendation },
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

function SectionCard({ title, icon, action, children }) {
  return (
    <section className="section-card">
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

function Dashboard({ data }) {
  const reviewCount = data.reports.filter((report) => report.reviewStatus !== '已复核').length;
  const runningCount = data.interviews.filter((interview) => interview.status === '进行中').length;
  const lowScoreCount = data.reports.filter((report) => Number(report.score) < 70).length;
  const scoreRows = data.reports.length
    ? [
        ['报告平均分', Math.round(data.reports.reduce((sum, item) => sum + Number(item.score || 0), 0) / data.reports.length)],
        ['高分报告', data.reports.filter((item) => Number(item.score) >= 85).length],
        ['待复核报告', reviewCount],
        ['低分报告', lowScoreCount],
      ]
    : [];

  return (
    <>
      <section className="metric-grid">
        {data.metrics.map((item) => (
          <article className={`metric-card ${item.tone}`} key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
            <small>{item.note}</small>
          </article>
        ))}
      </section>

      <section className="content-grid">
        <SectionCard title="今日运营队列" icon={<Activity size={18} />}>
          <div className="ops-list">
            <div><strong>{reviewCount}</strong><span>报告需要人工复核或抽检</span></div>
            <div><strong>{runningCount}</strong><span>进行中的面试需要监控稳定性</span></div>
            <div><strong>{lowScoreCount}</strong><span>低分报告建议进入复核池</span></div>
          </div>
        </SectionCard>

        <SectionCard title="能力分布概览" icon={<BarChart3 size={18} />}>
          <div className="score-bars">
            {scoreRows.length === 0 && <EmptyState text="生成报告后展示统计" />}
            {scoreRows.map(([label, value]) => (
              <div className="score-row" key={label}>
                <div><span>{label}</span><b>{value}/100</b></div>
                <div className="bar-track"><span style={{ width: `${Math.min(Number(value), 100)}%` }} /></div>
              </div>
            ))}
          </div>
        </SectionCard>
      </section>
    </>
  );
}

function CandidatesPage({ data, onView }) {
  const columns = [
    { key: 'name', label: '候选人' },
    { key: 'email', label: '邮箱' },
    { key: 'role', label: '目标岗位' },
    { key: 'status', label: '状态', render: (row) => <StatusBadge>{row.status}</StatusBadge> },
    { key: 'interviews', label: '面试数' },
    { key: 'averageScore', label: '均分' },
    { key: 'lastLogin', label: '最后登录' },
  ];
  return <SectionCard title="用户与候选人" icon={<UsersRound size={18} />}><AdminTable columns={columns} rows={data.candidates} onView={(row) => onView('candidate', row)} /></SectionCard>;
}

function InterviewsPage({ data, onView }) {
  const columns = [
    { key: 'id', label: '面试 ID' },
    { key: 'candidate', label: '候选人' },
    { key: 'role', label: '目标岗位' },
    { key: 'type', label: '面试类型' },
    { key: 'status', label: '状态', render: (row) => <StatusBadge>{row.status}</StatusBadge> },
    { key: 'agents', label: 'Agent' },
    { key: 'messages', label: '消息数' },
    { key: 'updatedAt', label: '更新时间' },
  ];
  return <SectionCard title="面试运营" icon={<ClipboardList size={18} />}><AdminTable columns={columns} rows={data.interviews} onView={(row) => onView('interview', row)} /></SectionCard>;
}

function ReportsPage({ data, onView }) {
  const columns = [
    { key: 'id', label: '报告 ID' },
    { key: 'candidate', label: '候选人' },
    { key: 'role', label: '目标岗位' },
    { key: 'score', label: '总分' },
    { key: 'grade', label: '等级' },
    { key: 'recommendation', label: '建议' },
    { key: 'reviewStatus', label: '复核状态', render: (row) => <StatusBadge>{row.reviewStatus}</StatusBadge> },
    { key: 'createdAt', label: '生成时间' },
  ];
  return <SectionCard title="报告与复核" icon={<FileText size={18} />}><AdminTable columns={columns} rows={data.reports} onView={(row) => onView('report', row)} /></SectionCard>;
}

function AgentsPage({ data, onView }) {
  const columns = [
    { key: 'name', label: 'Agent 名称' },
    { key: 'type', label: '类型' },
    { key: 'focus', label: '考察重点' },
    { key: 'usageCount', label: '使用次数' },
    { key: 'status', label: '状态', render: (row) => <StatusBadge>{row.status}</StatusBadge> },
  ];
  return (
    <section className="content-grid">
      <SectionCard title="Agent 模板" icon={<Bot size={18} />}>
        <AdminTable columns={columns} rows={data.agents} onView={(row) => onView('agent', row)} />
      </SectionCard>
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
  const [adminUsers, setAdminUsers] = useState(data.adminUsers || []);
  const [adminForm, setAdminForm] = useState({ email: '', name: '', password: '', role: 'reviewer' });
  const [adminMessage, setAdminMessage] = useState('');
  const [adminError, setAdminError] = useState('');
  const [adminSaving, setAdminSaving] = useState(false);
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
  const updateAdminForm = (key, value) => setAdminForm((current) => ({ ...current, [key]: value }));

  const createAdmin = async (event) => {
    event.preventDefault();
    setAdminSaving(true);
    setAdminMessage('');
    setAdminError('');
    try {
      const result = await adminRequest('/api/admin/users', {
        method: 'POST',
        body: JSON.stringify(adminForm),
      });
      setAdminUsers((current) => [...current, result.admin]);
      setAdminForm({ email: '', name: '', password: '', role: 'reviewer' });
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
      <SectionCard title="管理员与审计" icon={<UserCog size={18} />}>
        <form className="admin-account-form" onSubmit={createAdmin}>
          <h3>创建管理员</h3>
          <div className="field-grid">
            <label className="field-block">
              <span>姓名</span>
              <input value={adminForm.name} onChange={(event) => updateAdminForm('name', event.target.value)} required />
            </label>
            <label className="field-block">
              <span>邮箱</span>
              <input type="email" value={adminForm.email} onChange={(event) => updateAdminForm('email', event.target.value)} required />
            </label>
          </div>
          <div className="field-grid">
            <label className="field-block">
              <span>初始密码</span>
              <input type="password" minLength={12} value={adminForm.password} onChange={(event) => updateAdminForm('password', event.target.value)} required />
              <small>至少 12 位，创建后请通过安全渠道交付。</small>
            </label>
            <label className="field-block">
              <span>角色</span>
              <select value={adminForm.role} onChange={(event) => updateAdminForm('role', event.target.value)}>
                <option value="reviewer">报告审核员</option>
                <option value="operations">运营管理员</option>
                <option value="super_admin">超级管理员</option>
              </select>
            </label>
          </div>
          {adminMessage && <p className="settings-message success">{adminMessage}</p>}
          {adminError && <p className="settings-message error">{adminError}</p>}
          <button className="primary-button" type="submit" disabled={adminSaving}>
            {adminSaving ? '创建中...' : '创建管理员'}
          </button>
        </form>
        <div className="admin-account-list">
          {adminUsers.map((item) => (
            <article key={item.id}>
              <div>
                <strong>{item.name}</strong>
                <span>{item.email}</span>
                <small>{roleLabels[item.role] || item.role} · {item.status === 'normal' ? '正常' : '已禁用'}</small>
              </div>
              <button
                type="button"
                disabled={item.id === data.admin?.id}
                onClick={() => toggleAdminStatus(item)}
              >
                {item.status === 'normal' ? '禁用' : '启用'}
              </button>
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
    </section>
  );
}

function AdminApp({ admin, onSignedOut }) {
  const [activeView, setActiveView] = useState('dashboard');
  const [adminData, setAdminData] = useState(emptyAdminData);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const visibleNavItems = useMemo(
    () => navItems.filter((item) => !item.permission || adminData.permissions?.[item.permission]),
    [adminData.permissions],
  );
  const activeItem = useMemo(() => visibleNavItems.find((item) => item.key === activeView), [activeView, visibleNavItems]);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    adminRequest('/api/admin/snapshot')
      .then((data) => {
        if (mounted) {
          setAdminData({ ...emptyAdminData, ...data });
          setError('');
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

  const openDetail = async (type, row) => {
    const paths = {
      candidate: `/api/admin/candidates/${encodeURIComponent(row.id)}`,
      interview: `/api/admin/interviews/${encodeURIComponent(row.id)}`,
      report: `/api/admin/reports/${encodeURIComponent(row.id)}`,
      agent: `/api/admin/agents/${encodeURIComponent(row.name)}`,
    };
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
    } catch (requestError) {
      setDetailError(requestError.message);
    } finally {
      setDetailLoading(false);
    }
  };

  const renderContent = () => {
    if (loading) return <div className="page-message">正在读取独立管理端后端数据</div>;
    if (error) return <div className="page-message error">{error}</div>;
    if (activeView === 'catalog') return <CatalogPage permissions={adminData.permissions || {}} />;
    if (activeView === 'candidates') return <CandidatesPage data={adminData} onView={openDetail} />;
    if (activeView === 'interviews') return <InterviewsPage data={adminData} onView={openDetail} />;
    if (activeView === 'reports') return <ReportsPage data={adminData} onView={openDetail} />;
    if (activeView === 'agents') return <AgentsPage data={adminData} onView={openDetail} />;
    if (activeView === 'settings') return <SettingsPage data={adminData} onSettingsSaved={handleSettingsSaved} />;
    return <Dashboard data={adminData} />;
  };

  return (
    <main className="admin-shell">
      <aside className="admin-sidebar">
        <div className="admin-brand">
          <div><ShieldCheck size={22} /></div>
          <section>
            <strong>AI Interview Admin</strong>
            <span>多 Agent 面试管理端</span>
          </section>
        </div>

        <nav className="admin-nav" aria-label="管理端导航">
          {visibleNavItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={activeView === item.key ? 'active' : ''}
                key={item.key}
                type="button"
                onClick={() => setActiveView(item.key)}
              >
                <Icon size={17} />
                {item.label}
              </button>
            );
          })}
        </nav>

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
      </aside>

      <section className="admin-main">
        <header className="admin-topbar">
          <div>
            <p>Management Console</p>
            <h1>{activeItem?.label || '总览'}</h1>
          </div>
          <label className="admin-search">
            <Search size={16} />
            <input placeholder="搜索用户、面试、报告 ID" />
          </label>
        </header>

        <section className="admin-hero">
          <div>
            <span>安全管理控制台</span>
            <h2>管理端已启用独立登录与角色权限</h2>
            <p>当前账号为{roleLabels[admin?.role] || admin?.role}，页面仅展示该角色允许访问的数据和操作。</p>
          </div>
          <div className="hero-status">
            <Gauge size={22} />
            <strong>{loading ? '连接中' : error ? '后端异常' : '真实后端'}</strong>
            <small>{ADMIN_API_BASE_URL}</small>
          </div>
        </section>

        {renderContent()}
      </section>
      <DetailModal
        detail={detail}
        loading={detailLoading}
        error={detailError}
        onReview={reviewReport}
        canReview={admin?.role === 'super_admin' || admin?.role === 'reviewer'}
        onClose={() => {
          setDetail(null);
          setDetailError('');
          setDetailLoading(false);
        }}
      />
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
