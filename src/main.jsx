import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  AlertTriangle,
  Award,
  BarChart3,
  Bot,
  BriefcaseBusiness,
  CheckCircle2,
  ChevronDown,
  CircleDot,
  Clock3,
  Download,
  FileText,
  Headphones,
  Layers3,
  MessageSquareText,
  Mic,
  Phone,
  PhoneOff,
  Radio,
  Send,
  ShieldCheck,
  Sparkles,
  UserRound,
  Volume2,
  Wrench,
} from 'lucide-react';
import './styles.css';

const report = {
  candidate: '林致远',
  role: '高级前端开发工程师',
  level: 'P6 / Senior',
  result: '建议录用',
  grade: 'A',
  score: 86,
  generatedAt: '2026-06-09 16:40',
  interviewId: 'INT-20260609-FE-027',
  radar: [
    { subject: '硬技能', value: 88 },
    { subject: '架构思维', value: 84 },
    { subject: '业务理解', value: 78 },
    { subject: '沟通表达', value: 90 },
    { subject: '稳定抗压', value: 82 },
    { subject: '学习迁移', value: 86 },
  ],
  metrics: [
    {
      label: '技术深度',
      value: 89,
      note: 'React Fiber、状态管理与性能优化回答完整，能解释底层机制与工程权衡。',
    },
    {
      label: '系统设计',
      value: 84,
      note: '组件边界、缓存策略、灰度发布思路清晰，异常链路还可继续量化。',
    },
    {
      label: '业务判断',
      value: 78,
      note: '能围绕转化与稳定性做取舍，但对指标拆解的主动性略弱。',
    },
    {
      label: '表达协作',
      value: 91,
      note: '回答结构稳定，能先给结论再展开，追问下仍能保持节奏。',
    },
  ],
  interviewers: [
    {
      name: '技术一面 Agent',
      decision: '通过',
      color: 'green',
      text: '候选人对现代前端工程体系理解成熟，能从调度、渲染和工程治理三个层面展开。',
    },
    {
      name: '架构二面 Agent',
      decision: '通过',
      color: 'blue',
      text: '有大型项目复杂度意识，方案表达克制，具备主导中型模块的能力。',
    },
    {
      name: 'HR Agent',
      decision: '待确认',
      color: 'amber',
      text: '职业动机稳定，薪资与到岗时间需在 offer 前进一步确认。',
    },
  ],
  timeline: [
    {
      type: 'tech',
      title: 'Q1: 谈谈你对 React Fiber 的理解',
      answer:
        'Fiber 是 React 为了解决同步渲染阻塞主线程而引入的数据结构和调度模型。它把渲染工作拆成可中断的小单元，并结合优先级调度，让高优先级任务可以更快响应。',
      review:
        '亮点：能抓住可中断渲染、优先级和用户体验之间的关系。不足：如果补充双缓存树、commit 阶段不可中断，以及 lane 模型的演进，会更接近资深候选人的完整答案。示范：可以先定义 Fiber，再按数据结构、调度流程、渲染阶段、实际收益四层展开。',
      score: 90,
    },
    {
      type: 'tech',
      title: 'Q2: 如何设计一个稳定的低代码表单渲染器',
      answer:
        '我会把 schema 解析、组件注册、联动规则和校验策略拆开。核心渲染层保持纯粹，复杂业务通过插件或 hook 注入，避免表单引擎被业务逻辑污染。',
      review:
        '亮点：边界意识好，提到了注册表、规则引擎和插件化。不足：缺少对运行时性能、版本兼容、灰度回滚的说明。示范：建议补充 schema version、字段依赖图、局部渲染、错误隔离和埋点观测。',
      score: 84,
    },
    {
      type: 'business',
      title: 'Q3: 如果排期与质量冲突，你如何推动决策',
      answer:
        '我会先把质量风险显性化，列出必须修复和可延期项，再和产品确认核心业务目标。如果风险会影响主链路，就推动缩范围而不是压测试。',
      review:
        '亮点：有风险分级和范围管理意识，态度稳。不足：可以更主动量化影响，例如故障概率、影响用户量、回滚成本。示范：先对齐目标，再给出三套方案和推荐路径，让决策者看到取舍。',
      score: 82,
    },
    {
      type: 'hr',
      title: 'Q4: 你为什么考虑这次机会',
      answer:
        '我希望参与更复杂的业务平台建设，也希望从单点功能负责人转向更完整的系统 owner 角色。',
      review:
        '亮点：动机与岗位成长路径匹配，表达真实。不足：可以补充对团队业务的具体理解。示范：把个人成长、岗位职责和公司业务阶段连接起来，会更有说服力。',
      score: 87,
    },
  ],
};

const liveInterview = {
  candidate: '林致远',
  role: '高级前端开发工程师',
  sessionId: 'LIVE-20260609-FE-027',
  duration: '18:42',
  currentAgent: '技术一面 Agent',
  currentQuestion: '请你结合最近一个复杂项目，说明你是如何定位并解决前端性能瓶颈的。',
  agents: [
    {
      name: '技术一面 Agent',
      role: '硬技能追问',
      status: '正在提问',
      tone: 'green',
      score: 88,
    },
    {
      name: '架构二面 Agent',
      role: '系统设计观察',
      status: '待接入',
      tone: 'blue',
      score: 0,
    },
    {
      name: 'HR Agent',
      role: '动机与稳定性',
      status: '待接入',
      tone: 'amber',
      score: 0,
    },
  ],
  transcript: [
    {
      speaker: '技术一面 Agent',
      time: '18:21',
      type: 'agent',
      text: '我们先从你最近负责的项目开始。请描述一下当时的性能问题、定位过程和最终收益。',
    },
    {
      speaker: '候选人',
      time: '18:35',
      type: 'candidate',
      text: '当时主要问题集中在首屏渲染和表格滚动卡顿。我先通过性能面板确认长任务来源，再用埋点拆分接口、渲染和资源加载耗时。',
    },
    {
      speaker: '技术一面 Agent',
      time: '18:42',
      type: 'agent live',
      text: '请继续补充：你如何判断优化动作真的带来了业务收益，而不是只改善了实验环境指标？',
    },
  ],
  signals: [
    { label: '语音清晰度', value: '96%', trend: '稳定' },
    { label: '回答完整度', value: '84%', trend: '上升' },
    { label: '追问深度', value: '3 层', trend: '进行中' },
  ],
  queue: [
    'React 渲染链路与状态更新',
    '大型表格性能治理',
    '异常监控与线上回滚',
    '团队协作与项目复盘',
  ],
};

const setupOptions = {
  roles: ['前端开发', '后端开发', 'AI Agent 工程师', '产品经理', '数据分析'],
  levels: ['应届', '初级', '中级', '高级'],
  interviewTypes: ['技术一面', '技术二面', 'HR 面', '综合模拟'],
  companyScenes: ['互联网大厂风格', '创业公司 CTO 面', '外企工程经理面', '校招 HR 面'],
  focusAreas: ['项目深挖', '系统设计', '八股基础', '行为面试', '压力面试'],
  intensity: ['轻松', '标准', '严格'],
  styles: ['友好引导', '正常克制', '犀利追问', '沉默压迫感'],
};

const interviewerProfile = {
  title: '互联网大厂风格技术二面面试官',
  company: '中大型 AI 工具平台技术团队',
  goal: '判断候选人是否具备独立负责核心前端模块、拆解复杂问题并推动工程落地的能力。',
  strategy: '先围绕简历项目建立上下文，再抓住性能治理、组件边界和线上稳定性连续追问。',
  pressure: '回答偏空泛时，会要求补充指标、具体方案、失败案例和复盘动作。',
  structure: [
    '自我介绍与项目背景 3 分钟',
    '项目复杂度深挖 12 分钟',
    '技术方案与工程取舍 15 分钟',
    '协作与复盘追问 8 分钟',
    '候选人反问 5 分钟',
  ],
  scoring: ['技术深度', '表达清晰度', '工程经验', '问题拆解', '反思能力'],
};

function StatusTag({ children, tone = 'blue' }) {
  return <span className={`status-tag ${tone}`}>{children}</span>;
}

function Card({ title, icon, action, children, className = '' }) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-header">
        <div className="panel-title">
          {icon}
          <h2>{title}</h2>
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}

function ProgressMetric({ item }) {
  return (
    <div className="metric-row">
      <div className="metric-topline">
        <strong>{item.label}</strong>
        <span>{item.value}/100</span>
      </div>
      <div className="progress-track" aria-label={`${item.label} ${item.value} 分`}>
        <div className="progress-fill" style={{ width: `${item.value}%` }} />
      </div>
      <p>{item.note}</p>
    </div>
  );
}

function CompetencyRadar({ data }) {
  const size = 300;
  const center = size / 2;
  const radius = 104;
  const levels = [0.25, 0.5, 0.75, 1];
  const angleStep = (Math.PI * 2) / data.length;
  const pointAt = (index, scale = 1) => {
    const angle = -Math.PI / 2 + index * angleStep;
    return [
      center + Math.cos(angle) * radius * scale,
      center + Math.sin(angle) * radius * scale,
    ];
  };
  const polygon = data
    .map((item, index) => pointAt(index, item.value / 100).join(','))
    .join(' ');

  return (
    <svg className="radar-svg" viewBox={`0 0 ${size} ${size}`} role="img" aria-label="核心能力雷达图">
      {levels.map((level) => (
        <polygon
          key={level}
          points={data.map((_, index) => pointAt(index, level).join(',')).join(' ')}
          className="radar-grid"
        />
      ))}
      {data.map((_, index) => {
        const [x, y] = pointAt(index);
        return <line key={index} x1={center} y1={center} x2={x} y2={y} className="radar-axis" />;
      })}
      <polygon points={polygon} className="radar-area" />
      {data.map((item, index) => {
        const [x, y] = pointAt(index, 1.2);
        return (
          <text
            key={item.subject}
            x={x}
            y={y}
            textAnchor={x > center + 8 ? 'start' : x < center - 8 ? 'end' : 'middle'}
            dominantBaseline="middle"
            className="radar-label"
          >
            {item.subject}
          </text>
        );
      })}
      {data.map((item, index) => {
        const [x, y] = pointAt(index, item.value / 100);
        return <circle key={item.subject} cx={x} cy={y} r="3.5" className="radar-dot" />;
      })}
    </svg>
  );
}

function TimelineItem({ item, index }) {
  const [open, setOpen] = useState(index === 0);
  const Icon = item.type === 'hr' ? BriefcaseBusiness : item.type === 'business' ? MessageSquareText : Wrench;

  return (
    <article className={`timeline-item ${open ? 'open' : ''}`}>
      <div className="timeline-marker">
        <Icon size={15} />
      </div>
      <button className="timeline-toggle" onClick={() => setOpen(!open)}>
        <span>
          <small>第 {index + 1} 轮</small>
          <strong>{item.title}</strong>
        </span>
        <span className="timeline-score">{item.score} 分</span>
        <ChevronDown className="chevron" size={18} />
      </button>
      {open && (
        <div className="timeline-body">
          <div className="answer-block">
            <h3>候选人回答</h3>
            <p>{item.answer}</p>
          </div>
          <div className="review-block">
            <h3>AI 导师复盘意见</h3>
            <p>{item.review}</p>
          </div>
        </div>
      )}
    </article>
  );
}

function ViewSwitch({ view, onChange }) {
  return (
    <div className="view-switch" aria-label="页面视图切换">
      <button className={view === 'setup' ? 'active' : ''} onClick={() => onChange('setup')}>
        <Layers3 size={15} />
        面试配置
      </button>
      <button className={view === 'phone' ? 'active' : ''} onClick={() => onChange('phone')}>
        <Phone size={15} />
        电话面试
      </button>
      <button className={view === 'report' ? 'active' : ''} onClick={() => onChange('report')}>
        <FileText size={15} />
        复盘报告
      </button>
    </div>
  );
}

function OptionGroup({ label, options, value, onChange }) {
  return (
    <label className="option-group">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function SetupPage({ onStart }) {
  const [form, setForm] = useState({
    role: setupOptions.roles[0],
    level: setupOptions.levels[2],
    interviewType: setupOptions.interviewTypes[1],
    companyScene: setupOptions.companyScenes[0],
    focusArea: setupOptions.focusAreas[0],
    intensity: setupOptions.intensity[1],
    style: setupOptions.styles[2],
    brief:
      '负责过中后台性能优化、低代码表单搭建和组件库治理，希望重点练习项目深挖与架构表达。',
  });

  const updateForm = (key, value) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  return (
    <section className="setup-page">
      <div className="setup-hero">
        <div>
          <p className="eyebrow">Personalized Interview Coach</p>
          <h1>生成本场专属 AI 面试官</h1>
          <span>
            先用少量关键信息确定训练目标，再生成面试官策略、追问方式和评分标准。
          </span>
        </div>
        <button className="primary-action" onClick={onStart}>
          <Phone size={17} />
          开始电话面试
        </button>
      </div>

      <section className="setup-grid">
        <Card title="面试前配置" icon={<Layers3 size={18} />}>
          <div className="setup-form">
            <OptionGroup
              label="目标岗位"
              options={setupOptions.roles}
              value={form.role}
              onChange={(value) => updateForm('role', value)}
            />
            <OptionGroup
              label="当前水平"
              options={setupOptions.levels}
              value={form.level}
              onChange={(value) => updateForm('level', value)}
            />
            <OptionGroup
              label="面试类型"
              options={setupOptions.interviewTypes}
              value={form.interviewType}
              onChange={(value) => updateForm('interviewType', value)}
            />
            <OptionGroup
              label="公司场景"
              options={setupOptions.companyScenes}
              value={form.companyScene}
              onChange={(value) => updateForm('companyScene', value)}
            />
            <OptionGroup
              label="练习重点"
              options={setupOptions.focusAreas}
              value={form.focusArea}
              onChange={(value) => updateForm('focusArea', value)}
            />
            <OptionGroup
              label="面试强度"
              options={setupOptions.intensity}
              value={form.intensity}
              onChange={(value) => updateForm('intensity', value)}
            />
            <OptionGroup
              label="面试官风格"
              options={setupOptions.styles}
              value={form.style}
              onChange={(value) => updateForm('style', value)}
            />
            <label className="brief-field">
              <span>简历 / 项目简介</span>
              <textarea value={form.brief} onChange={(event) => updateForm('brief', event.target.value)} />
            </label>
          </div>
        </Card>

        <Card title="本场面试官档案" icon={<Bot size={18} />}>
          <div className="profile-card">
            <div className="profile-head">
              <AgentAvatar name="技术一面 Agent" active />
              <div>
                <strong>{interviewerProfile.title}</strong>
                <span>{form.companyScene} · {form.interviewType} · {form.intensity}强度</span>
              </div>
            </div>

            <div className="profile-section">
              <span>面试目标</span>
              <p>{interviewerProfile.goal}</p>
            </div>
            <div className="profile-section">
              <span>提问策略</span>
              <p>{interviewerProfile.strategy}</p>
            </div>
            <div className="profile-section">
              <span>风险追问</span>
              <p>{interviewerProfile.pressure}</p>
            </div>

            <div className="profile-split">
              <div>
                <span>面试结构</span>
                {interviewerProfile.structure.map((item) => (
                  <p key={item}>{item}</p>
                ))}
              </div>
              <div>
                <span>评分维度</span>
                <div className="score-tags">
                  {interviewerProfile.scoring.map((item) => (
                    <StatusTag key={item} tone="blue">{item}</StatusTag>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </Card>
      </section>
    </section>
  );
}

function AgentAvatar({ name, active }) {
  const initial = name.includes('技术') ? 'T' : name.includes('架构') ? 'A' : 'H';

  return (
    <div className={`agent-avatar ${active ? 'active' : ''}`} aria-hidden="true">
      <Bot size={20} />
      <span>{initial}</span>
    </div>
  );
}

function AgentRoster({ agents, currentAgent }) {
  return (
    <div className="agent-roster">
      {agents.map((agent) => {
        const active = agent.name === currentAgent;
        return (
          <div className={`agent-row ${active ? 'active' : ''}`} key={agent.name}>
            <AgentAvatar name={agent.name} active={active} />
            <div>
              <strong>{agent.name}</strong>
              <span>{agent.role}</span>
            </div>
            <StatusTag tone={agent.tone}>{agent.status}</StatusTag>
          </div>
        );
      })}
    </div>
  );
}

function TranscriptMessage({ item }) {
  const isCandidate = item.type === 'candidate';

  return (
    <article className={`transcript-message ${isCandidate ? 'candidate' : 'agent'}`}>
      <div className="message-meta">
        <strong>{item.speaker}</strong>
        <span>{item.time}</span>
      </div>
      <p>{item.text}</p>
    </article>
  );
}

function PhoneInterviewPage() {
  return (
    <section className="phone-page">
      <div className="phone-hero">
        <div className="call-stage">
          <div className="call-status">
            <span className="live-dot" />
            AI 电话面试进行中
          </div>

          <div className="caller-card">
            <div className="caller-orbit">
              <div className="voice-ring ring-one" />
              <div className="voice-ring ring-two" />
              <div className="caller-avatar">
                <Headphones size={42} />
              </div>
            </div>
            <div className="caller-copy">
              <p className="eyebrow">当前接入</p>
              <h1>{liveInterview.currentAgent}</h1>
              <span>正在围绕项目复杂度进行追问</span>
            </div>
          </div>

          <div className="call-question">
            <div>
              <Sparkles size={16} />
              <strong>当前问题</strong>
            </div>
            <p>{liveInterview.currentQuestion}</p>
          </div>

          <div className="call-controls" aria-label="电话面试控制">
            <button className="control-button">
              <Mic size={20} />
            </button>
            <button className="control-button primary">
              <Volume2 size={20} />
            </button>
            <button className="control-button danger">
              <PhoneOff size={20} />
            </button>
          </div>
        </div>

        <aside className="call-sidebar">
          <div className="session-card">
            <span>通话时长</span>
            <strong>{liveInterview.duration}</strong>
            <p>{liveInterview.candidate} · {liveInterview.role}</p>
          </div>
          <div className="signal-grid">
            {liveInterview.signals.map((signal) => (
              <div className="signal-card" key={signal.label}>
                <span>{signal.label}</span>
                <strong>{signal.value}</strong>
                <small>{signal.trend}</small>
              </div>
            ))}
          </div>
        </aside>
      </div>

      <section className="phone-grid">
        <Card title="面试官接入队列" icon={<Radio size={18} />}>
          <AgentRoster agents={liveInterview.agents} currentAgent={liveInterview.currentAgent} />
        </Card>

        <Card title="实时语音转写" icon={<MessageSquareText size={18} />}>
          <div className="transcript-list">
            {liveInterview.transcript.map((item) => (
              <TranscriptMessage item={item} key={`${item.speaker}-${item.time}`} />
            ))}
          </div>
          <div className="reply-box">
            <span>候选人正在回答，系统持续记录语义片段</span>
            <button>
              <Send size={15} />
            </button>
          </div>
        </Card>

        <Card title="追问路线" icon={<CircleDot size={18} />} className="question-route-panel">
          <div className="question-route">
            {liveInterview.queue.map((item, index) => (
              <div className={index === 1 ? 'current' : ''} key={item}>
                <span>{String(index + 1).padStart(2, '0')}</span>
                <strong>{item}</strong>
              </div>
            ))}
          </div>
        </Card>
      </section>
    </section>
  );
}

function ReportPage() {
  return (
    <section className="report-page">
      <header className="summary-panel">
        <div className="candidate-block">
          <div className="avatar">
            <UserRound size={34} />
          </div>
          <div>
            <div className="eyebrow">综合复盘报告</div>
            <h1>AI 智能面试综合复盘报告</h1>
            <dl className="candidate-meta">
              <div>
                <dt>候选人</dt>
                <dd>{report.candidate}</dd>
              </div>
              <div>
                <dt>应聘岗位</dt>
                <dd>{report.role}</dd>
              </div>
              <div>
                <dt>目标职级</dt>
                <dd>{report.level}</dd>
              </div>
              <div>
                <dt>报告编号</dt>
                <dd>{report.interviewId}</dd>
              </div>
            </dl>
          </div>
        </div>
        <div className="decision-badge">
          <span>{report.result}</span>
          <strong>{report.grade}</strong>
          <small>综合评分 {report.score}/100</small>
        </div>
      </header>

      <section className="kpi-grid">
        <div className="kpi-item">
          <CircleDot size={16} />
          <span>面试轮次</span>
          <strong>4</strong>
        </div>
        <div className="kpi-item">
          <CheckCircle2 size={16} />
          <span>通过 Agent</span>
          <strong>2/3</strong>
        </div>
        <div className="kpi-item">
          <Clock3 size={16} />
          <span>生成时间</span>
          <strong>{report.generatedAt}</strong>
        </div>
        <div className="kpi-item">
          <Award size={16} />
          <span>人才画像</span>
          <strong>稳健型专家</strong>
        </div>
      </section>

      <section className="dashboard-grid">
        <Card title="核心能力模型" icon={<BarChart3 size={18} />}>
          <div className="radar-wrap">
            <CompetencyRadar data={report.radar} />
          </div>
        </Card>

        <Card title="逐项得分指标" icon={<FileText size={18} />}>
          <div className="metrics-list">
            {report.metrics.map((item) => (
              <ProgressMetric key={item.label} item={item} />
            ))}
          </div>
        </Card>
      </section>

      <section className="dashboard-grid secondary">
        <Card title="面试官综合评价" icon={<MessageSquareText size={18} />}>
          <div className="review-list">
            {report.interviewers.map((item) => (
              <div className="review-card" key={item.name}>
                <div>
                  <strong>{item.name}</strong>
                  <StatusTag tone={item.color}>{item.decision}</StatusTag>
                </div>
                <p>{item.text}</p>
              </div>
            ))}
          </div>
        </Card>

        <Card title="录用风险提示" icon={<AlertTriangle size={18} />}>
          <div className="risk-table">
            <div>
              <span>业务指标拆解</span>
              <StatusTag tone="amber">中风险</StatusTag>
              <p>建议终面追问增长指标、监控口径和复盘案例。</p>
            </div>
            <div>
              <span>架构 owner 经验</span>
              <StatusTag tone="blue">可培养</StatusTag>
              <p>具备模块治理能力，需确认跨团队推进深度。</p>
            </div>
            <div>
              <span>到岗稳定性</span>
              <StatusTag tone="green">低风险</StatusTag>
              <p>职业动机与岗位方向匹配，表达稳定。</p>
            </div>
          </div>
        </Card>
      </section>

      <Card title="面试深度对线复盘" icon={<Clock3 size={18} />} className="timeline-panel">
        <div className="timeline">
          {report.timeline.map((item, index) => (
            <TimelineItem key={item.title} item={item} index={index} />
          ))}
        </div>
      </Card>
    </section>
  );
}

function App() {
  const [view, setView] = useState('setup');

  return (
    <main className="app-shell">
      <div className="workspace-page">
        <div className="topbar">
          <div className="brand-mark">
            <ShieldCheck size={20} />
          </div>
          <div>
            <strong>AI Interview Intelligence</strong>
            <span>多 Agent 面试评估系统</span>
          </div>
          <ViewSwitch view={view} onChange={setView} />
          <button className="icon-button" aria-label="下载报告">
            <Download size={18} />
          </button>
        </div>

        {view === 'setup' && <SetupPage onStart={() => setView('phone')} />}
        {view === 'phone' && <PhoneInterviewPage />}
        {view === 'report' && <ReportPage />}
      </div>
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);
