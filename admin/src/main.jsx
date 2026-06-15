import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  AlertCircle,
  BarChart3,
  Bot,
  ChevronRight,
  CheckCircle2,
  ClipboardList,
  FileText,
  Gauge,
  KeyRound,
  LayoutDashboard,
  LockKeyhole,
  Search,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  UserCog,
  UsersRound,
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
  settings: {
    openaiRealtimeModel: '-',
    openaiVoice: '-',
    qwenTtsModel: '-',
    qwenTtsVoice: '-',
    qwenTtsRegion: 'beijing',
    qwenTtsWorkspaceId: '',
    reviewRule: '-',
  },
};

function adminApiUrl(path) {
  return `${ADMIN_API_BASE_URL.replace(/\/$/, '')}${path}`;
}

async function adminRequest(path, options = {}) {
  const response = await fetch(adminApiUrl(path), {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || data.detail || '管理端后端请求失败。');
  }
  return data;
}

const navItems = [
  { key: 'dashboard', label: '总览', icon: LayoutDashboard },
  { key: 'candidates', label: '用户与候选人', icon: UsersRound },
  { key: 'interviews', label: '面试运营', icon: ClipboardList },
  { key: 'reports', label: '报告与复核', icon: FileText },
  { key: 'agents', label: 'Agent 与模板', icon: Bot },
  { key: 'settings', label: '系统与权限', icon: Settings },
];

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

function DetailModal({ detail, loading, error, onClose }) {
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
      title: `报告 · ${report.candidate || fallbackRow.candidate}`,
      rows: [
        { label: '候选人', value: report.candidate },
        { label: '邮箱', value: report.candidate_email },
        { label: '目标岗位', value: report.target_role || report.role },
        { label: '总分', value: report.total_score || report.score },
        { label: '等级', value: report.grade },
        { label: '录用建议', value: report.pass_recommendation || report.recommendation },
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

function SettingsPage({ data, onSettingsSaved }) {
  const settings = data.settings || emptyAdminData.settings;
  const [form, setForm] = useState({
    openaiApiKey: '',
    openaiRealtimeModel: settings.openaiRealtimeModel === '-' ? '' : settings.openaiRealtimeModel,
    openaiVoice: settings.openaiVoice === '-' ? '' : settings.openaiVoice,
    dashscopeApiKey: '',
    qwenTtsModel: settings.qwenTtsModel === '-' ? '' : settings.qwenTtsModel,
    qwenTtsVoice: settings.qwenTtsVoice === '-' ? '' : settings.qwenTtsVoice,
    qwenTtsRegion: settings.qwenTtsRegion || 'beijing',
    qwenTtsWorkspaceId: settings.qwenTtsWorkspaceId || '',
  });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [saveError, setSaveError] = useState('');
  const openaiReady = Boolean(settings.openaiApiKeyConfigured);
  const dashscopeReady = Boolean(settings.dashscopeApiKeyConfigured);

  useEffect(() => {
    setForm((current) => ({
      ...current,
      openaiRealtimeModel: settings.openaiRealtimeModel === '-' ? '' : settings.openaiRealtimeModel,
      openaiVoice: settings.openaiVoice === '-' ? '' : settings.openaiVoice,
      qwenTtsModel: settings.qwenTtsModel === '-' ? '' : settings.qwenTtsModel,
      qwenTtsVoice: settings.qwenTtsVoice === '-' ? '' : settings.qwenTtsVoice,
      qwenTtsRegion: settings.qwenTtsRegion || 'beijing',
      qwenTtsWorkspaceId: settings.qwenTtsWorkspaceId || '',
    }));
  }, [
    settings.openaiRealtimeModel,
    settings.openaiVoice,
    settings.qwenTtsModel,
    settings.qwenTtsVoice,
    settings.qwenTtsRegion,
    settings.qwenTtsWorkspaceId,
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
      setForm((current) => ({ ...current, openaiApiKey: '', dashscopeApiKey: '' }));
      onSettingsSaved(data.settings);
    } catch (requestError) {
      setSaveError(requestError.message);
    } finally {
      setSaving(false);
    }
  };
  return (
    <section className="content-grid">
      <SectionCard title="系统配置" icon={<Settings size={18} />}>
        <form className="settings-form" onSubmit={handleSave}>
          <div className="settings-overview">
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

          <div className="settings-note">
            <span>配置文件</span>
            <b>{settings.envPath}</b>
            <p>保存会写入用户端后端 .env；如用户端后端已经运行，请重启后端让新 API Key 完全生效。</p>
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
        <div className="audit-list">
          {data.auditLogs.length === 0 && <EmptyState text="审计日志表接入后展示" />}
          {data.auditLogs.map((log) => (
            <div key={`${log.action}-${log.time}`}>
              <span>{log.actor}</span>
              <strong>{log.action}</strong>
              <small>{log.target} · {log.time}</small>
            </div>
          ))}
        </div>
      </SectionCard>
    </section>
  );
}

function AdminApp() {
  const [activeView, setActiveView] = useState('dashboard');
  const [adminData, setAdminData] = useState(emptyAdminData);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const activeItem = useMemo(() => navItems.find((item) => item.key === activeView), [activeView]);

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
        if (mounted) setError(requestError.message);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

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

  const renderContent = () => {
    if (loading) return <div className="page-message">正在读取独立管理端后端数据</div>;
    if (error) return <div className="page-message error">{error}</div>;
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
          {navItems.map((item) => {
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
          <span>Admin Preview</span>
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
            <span>初始版本</span>
            <h2>先跑通运营视角，再接入真实后台权限与接口</h2>
            <p>当前为独立管理端前端应用，展示跨用户数据、面试运营、报告复核、Agent 模板和系统配置的第一版信息架构。</p>
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
        onClose={() => {
          setDetail(null);
          setDetailError('');
          setDetailLoading(false);
        }}
      />
    </main>
  );
}

createRoot(document.getElementById('root')).render(<AdminApp />);
