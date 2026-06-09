import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  AlertTriangle,
  Award,
  BarChart3,
  BriefcaseBusiness,
  CheckCircle2,
  ChevronDown,
  CircleDot,
  Clock3,
  Download,
  FileText,
  MessageSquareText,
  ShieldCheck,
  UserRound,
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

function App() {
  return (
    <main className="app-shell">
      <section className="report-page">
        <div className="topbar">
          <div className="brand-mark">
            <ShieldCheck size={20} />
          </div>
          <div>
            <strong>AI Interview Intelligence</strong>
            <span>多 Agent 面试评估系统</span>
          </div>
          <button className="icon-button" aria-label="下载报告">
            <Download size={18} />
          </button>
        </div>

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
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);
