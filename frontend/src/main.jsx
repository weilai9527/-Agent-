import React, { useEffect, useRef, useState } from 'react';
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
  FolderOpen,
  Languages,
  FileText,
  GraduationCap,
  KeyRound,
  LockKeyhole,
  LogIn,
  LogOut,
  Layers3,
  MessageSquareText,
  Mic,
  Phone,
  PhoneOff,
  Radio,
  Plus,
  Save,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Trash2,
  Target,
  TrendingUp,
  Trophy,
  Upload,
  UserRound,
  Wrench,
  X,
  Zap,
} from 'lucide-react';
import {
  createAliyunRtcAudioSession,
  handoffAliyunRtcSession,
  createAliyunRtcTranscriptAssembler,
  extractQuestionFromAgentTranscript,
  formatAliyunRtcStartError,
  findLatestInterviewQuestion,
  shouldPersistAliyunAgentTurn,
} from './aliyunRtc';
import { V4Brand, V4Logo, V4PageHeading } from './V4Shell';
import { uploadResume } from './resumeUpload';
import {
  abilitySampleStatus,
  hasInterviewerEvaluation,
  isAbilityReport,
  reportEvidenceNote,
  reportScore,
} from './reportPresentation';
import { mergeProfileIntoSetup } from './setupDefaults';
import './styles.css';
import './v4.css';

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
  levels: ['应届', '初级', '中级', '高级'],
  interviewTypes: ['技术一面', '技术二面', 'HR 面', '综合模拟'],
  companyScenes: ['互联网大厂风格', '创业公司 CTO 面', '外企工程经理面', '校招 HR 面'],
  focusAreas: ['项目深挖', '系统设计', '八股基础', '行为面试', '压力面试'],
  intensity: ['轻松', '标准', '严格'],
  styles: ['友好引导', '正常克制', '犀利追问', '沉默压迫感'],
};

// 难度快捷模板：每种难度就是一套预设的面试前配置。
// 后续调整难度只需修改这里的 overrides，字段与 setupOptions 中的可选项一一对应。
const difficultyPresets = [
  {
    key: 'easy',
    label: '简单',
    summary: '友好引导 · 八股基础 · 校招场景',
    description: '适合首次模拟，先熟悉面试节奏',
    overrides: {
      level: '应届',
      interviewType: '技术一面',
      companyScene: '校招 HR 面',
      focusArea: '八股基础',
      intensity: '轻松',
      style: '友好引导',
    },
  },
  {
    key: 'normal',
    label: '普通',
    summary: '标准强度 · 项目深挖 · 大厂风格',
    description: '接近真实技术面试，适合日常训练',
    overrides: {
      level: '中级',
      interviewType: '技术二面',
      companyScene: '互联网大厂风格',
      focusArea: '项目深挖',
      intensity: '标准',
      style: '犀利追问',
    },
  },
  {
    key: 'hard',
    label: '困难',
    summary: '严格追问 · 压力面试 · CTO 面',
    description: '高压连续追问，挑战临场抗压',
    overrides: {
      level: '高级',
      interviewType: '技术二面',
      companyScene: '创业公司 CTO 面',
      focusArea: '压力面试',
      intensity: '严格',
      style: '沉默压迫感',
    },
  },
];

const defaultDifficultyPreset = difficultyPresets.find((preset) => preset.key === 'normal') || difficultyPresets[0];

function buildInterviewerProfile(form) {
  const role = String(form?.role || '').trim();
  const normalizedRole = role.toLowerCase();
  const includesAny = (...keywords) => keywords.some((keyword) => normalizedRole.includes(keyword));
  let domain = {
    goal: `判断候选人是否具备胜任${role || '目标岗位'}所需的专业基础、问题拆解能力和工程落地意识。`,
    strategy: '先围绕简历中的真实项目建立上下文，再追问职责边界、方案取舍、结果指标和复盘动作。',
    scoring: ['岗位匹配', '技术深度', '表达清晰度', '问题拆解', '反思能力'],
  };

  if (includesAny('安全', '渗透', '攻防', 'soc', '红队', '蓝队')) {
    domain = {
      goal: `判断候选人是否具备胜任${role}所需的安全分析、风险研判、攻击验证和防护闭环能力。`,
      strategy: '从简历中的安全实践和工具使用切入，连续追问攻击面、漏洞证据、风险定级、修复方案与复测结果。',
      scoring: ['安全基础', '风险研判', '实战证据', '应急处置', '复盘能力'],
    };
  } else if (includesAny('人工智能', 'ai', '大模型', '机器学习', '深度学习', '算法', 'rag', 'agent', 'nlp', '视觉')) {
    domain = {
      goal: `判断候选人是否具备胜任${role}所需的数据理解、模型应用、效果评估和 AI 工程化能力。`,
      strategy: '从真实 AI 项目的数据与指标切入，追问模型选型、提示或检索策略、评测方法、成本延迟和失败兜底。',
      scoring: ['模型理解', '评测设计', '工程落地', '效果优化', '风险意识'],
    };
  } else if (includesAny('全栈', 'fullstack', 'full-stack')) {
    domain = {
      goal: `判断候选人是否具备胜任${role}所需的端到端交付、系统设计和跨层排障能力。`,
      strategy: '围绕一个完整项目拆解前端、接口、数据、部署与监控链路，追问边界设计、性能瓶颈、安全风险和发布取舍。',
      scoring: ['端到端设计', '前后端能力', '数据建模', '工程质量', '故障排查'],
    };
  } else if (includesAny('前端', 'web', 'h5', 'react', 'vue')) {
    domain = {
      goal: `判断候选人是否具备胜任${role}所需的前端架构、交互实现、性能治理和稳定性保障能力。`,
      strategy: '从真实页面和组件职责切入，追问状态管理、组件边界、性能指标、异常监控和线上回滚。',
      scoring: ['前端基础', '组件设计', '性能治理', '工程质量', '用户体验'],
    };
  } else if (includesAny('后端', '服务端', 'java', 'golang', '微服务')) {
    domain = {
      goal: `判断候选人是否具备胜任${role}所需的接口设计、数据建模、高并发处理和服务稳定性能力。`,
      strategy: '从真实服务和数据链路切入，追问接口契约、事务一致性、缓存并发、可观测性和故障恢复。',
      scoring: ['后端基础', '系统设计', '数据一致性', '性能稳定', '故障排查'],
    };
  } else if (includesAny('数据工程', '大数据', '数据开发', '数仓', 'etl', '数据分析')) {
    domain = {
      goal: `判断候选人是否具备胜任${role}所需的数据建模、管道建设、质量治理和任务稳定性能力。`,
      strategy: '从数据来源与业务口径切入，追问模型分层、增量处理、质量校验、资源调优和异常补数。',
      scoring: ['数据建模', '管道设计', '质量治理', '性能优化', '业务理解'],
    };
  } else if (includesAny('devops', '运维', 'sre', '云计算', '基础设施')) {
    domain = {
      goal: `判断候选人是否具备胜任${role}所需的自动化交付、可观测性、容量治理和故障恢复能力。`,
      strategy: '从部署与运维实践切入，追问流水线、容器编排、监控告警、容量规划、故障止损与复盘。',
      scoring: ['交付自动化', '可观测性', '稳定性', '故障处置', '成本意识'],
    };
  }

  return {
    title: `${form?.companyScene || '企业场景'}${form?.interviewType || '技术面试'}面试官`,
    goal: domain.goal,
    strategy: `${domain.strategy}${form?.focusArea ? ` 本场重点关注“${form.focusArea}”。` : ''}`,
    pressure: form?.intensity === '轻松'
      ? '回答信息不足时，会先给出提示，再要求补充具体场景、个人动作和结果。'
      : '回答偏空泛时，会要求补充指标、具体方案、失败案例和复盘动作。',
    structure: [
      '自我介绍与项目背景 3 分钟',
      '项目复杂度深挖 12 分钟',
      '技术方案与工程取舍 15 分钟',
      '协作与复盘追问 8 分钟',
      '候选人反问 5 分钟',
    ],
    scoring: domain.scoring,
  };
}

const resumeAnalysis = {
  matchScore: 86,
  targetRole: '等待分析后确认',
  summary:
    '系统会结合专业、技能、项目与实践经历推荐多个就业方向，并保留学生自主确认或自定义目标岗位的权利。',
  parsedSections: [
    { label: '基础信息', value: '已识别姓名、联系方式、目标岗位' },
    { label: '技能栈', value: 'React、Node.js、性能优化、工程治理' },
    { label: '项目经历', value: '低代码表单、组件库、中后台性能治理' },
    { label: '求职意向', value: '高级前端 / AI 工具平台 / 中大型团队' },
  ],
  highlights: [
    '有完整的中后台性能优化经验，适合展开指标拆解、瓶颈定位和收益验证。',
    '低代码表单项目能体现抽象能力，可重点讲 schema、插件化、联动规则和版本兼容。',
    '组件库治理经历能支撑工程 owner 能力表达，适合补充规范制定和推广过程。',
  ],
  risks: [
    '项目结果需要进一步量化，例如首屏耗时、长任务占比、转化率或缺陷率变化。',
    '架构 owner 经验描述偏隐性，建议补充跨团队协作、方案评审和灰度发布案例。',
    'AI Agent 相关经验如果作为目标方向，需要补充真实场景、工具链或落地边界。',
  ],
  questions: [
    '你在最近一次性能优化中，如何判断瓶颈来自渲染、接口还是资源加载？',
    '低代码表单的 schema 如何做版本兼容和灰度回滚？',
    '组件库治理如何推动业务团队采用，而不是停留在工具建设？',
    '如果线上优化指标变好但业务指标没有变化，你会如何复盘？',
  ],
  suggestions: [
    '把每段项目经历改成“背景-职责-技术难点-结果指标”的结构。',
    '为核心项目补充 2-3 个可被追问的技术细节，避免只写宏观职责。',
    '把“参与/负责”改成更明确的动作，例如设计、落地、推动、复盘。',
  ],
  recommendedSetup: [
    { label: '面试类型', value: '技术二面' },
    { label: '面试难度', value: '严格' },
    { label: '练习重点', value: '项目深挖' },
    { label: '面试官风格', value: '犀利追问' },
  ],
};

function hasAnyKeyword(text, keywords) {
  const lowerText = text.toLowerCase();
  return keywords.some((keyword) => lowerText.includes(keyword.toLowerCase()));
}

function buildResumeAnalysis(text, fileName = '') {
  const normalizedText = String(text || '').trim();
  const sourceName = fileName || '粘贴文本';
  const hasFrontend = hasAnyKeyword(normalizedText, ['react', 'vue', '前端', '组件', '性能', 'vite']);
  const hasBackend = hasAnyKeyword(normalizedText, ['node', 'java', 'go', '后端', '接口', '数据库', 'express']);
  const hasAgent = hasAnyKeyword(normalizedText, ['agent', 'ai', 'llm', 'rag', '大模型', '智能体']);
  const hasMetrics = /(\d+%|\d+\s*(ms|秒|分钟|万|k|K)|提升|降低|减少|增长)/.test(normalizedText);
  const hasProjects = hasAnyKeyword(normalizedText, ['项目', '负责', '主导', '设计', '落地', '优化']);
  const targetRole = '等待分析后确认';
  const matchScore = Math.min(
    95,
    45 +
      (hasFrontend ? 10 : 0) +
      (hasBackend ? 7 : 0) +
      (hasAgent ? 8 : 0) +
      (hasProjects ? 8 : 0) +
      (hasMetrics ? 7 : 0) +
      Math.min(8, Math.floor(normalizedText.length / 350))
  );
  const skills = [
    hasFrontend && '前端工程化 / 组件化',
    hasBackend && '后端接口 / 数据库',
    hasAgent && 'AI Agent / 大模型应用',
    hasMetrics && '结果指标表达',
  ].filter(Boolean);

  return {
    matchScore,
    targetRole,
    scoreLabel: '证据完整度',
    directions: [],
    summary: normalizedText
      ? `已基于“${sourceName}”解析 ${normalizedText.length} 个字符。当前分数仅表示简历证据完整度；点击“开始分析”后会生成多个就业方向，再由你确认目标岗位。`
      : resumeAnalysis.summary,
    parsedSections: [
      { label: '来源文件', value: sourceName },
      { label: '文本规模', value: normalizedText ? `${normalizedText.length} 个字符` : '暂无简历文本' },
      { label: '识别技能', value: skills.length ? skills.join('、') : '建议补充技术栈、项目职责和业务结果' },
      { label: '目标方向', value: '尚未确认，不会自动覆盖个人意愿' },
    ],
    highlights: [
      hasProjects
        ? '简历中出现了项目职责和落地描述，适合在面试中继续展开背景、动作和结果。'
        : '建议补充 1-2 个完整项目案例，突出你承担的角色和关键动作。',
      hasMetrics
        ? '简历中包含量化表达，可继续把指标和业务收益讲得更完整。'
        : '目前量化结果偏少，建议补充耗时、转化率、稳定性、缺陷率或效率提升等指标。',
      skills.length
        ? `当前可围绕 ${skills.slice(0, 2).join('、')} 设计追问。`
        : '技能关键词不够集中，建议补充核心技术栈和熟悉程度。',
    ],
    risks: [
      hasMetrics
        ? '需要准备好指标口径，避免面试官追问时无法解释数据来源。'
        : '项目结果缺少量化指标，容易被追问“具体收益是什么”。',
      '如果只描述参与事项，不说明个人决策和取舍，资深度会显得不足。',
      hasAgent
        ? '简历出现了 AI 相关证据，但不会仅凭一个关键词直接判定为 AI 岗位。'
        : '当前会结合专业、技能和项目证据推荐多个方向，而不是强制归类。',
    ],
    questions: [
      '请挑一个最复杂的项目，说明你的职责边界、核心难点和最终结果。',
      '你如何判断这个方案是最优解，而不是只满足当时需求？',
      hasMetrics
        ? '简历中的量化指标是如何采集和验证的？'
        : '如果让你补充项目指标，你会选择哪些指标证明价值？',
      '结合你的就业意愿，你希望优先验证哪个方向？为什么？',
    ],
    suggestions: [
      '把核心经历整理成“背景-任务-动作-结果-复盘”的结构。',
      '每个重点项目准备 2-3 个可被深入追问的技术细节。',
      '把“参与、负责”改成更具体的动作，例如设计、拆解、推动、优化、复盘。',
    ],
    recommendedSetup: [
      { label: '面试类型', value: hasProjects ? '技术二面' : '技术一面' },
      { label: '面试难度', value: matchScore >= 82 ? '严格' : '标准' },
      { label: '练习重点', value: hasMetrics ? '项目深挖' : '指标表达' },
      { label: '面试官风格', value: matchScore >= 82 ? '犀利追问' : '友好引导' },
    ],
  };
}

function normalizeAnalysisList(value, limit = 4) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item || '').trim()).filter(Boolean).slice(0, limit);
}

function normalizeRecommendedDirections(value) {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item) => item && typeof item === 'object' && String(item.name || '').trim())
    .map((item) => ({
      name: String(item.name).trim(),
      score: Math.max(1, Math.min(100, Number(item.score) || 1)),
      reasons: normalizeAnalysisList(item.reasons, 4),
      gaps: normalizeAnalysisList(item.gaps, 4),
      evidence: normalizeAnalysisList(item.evidence, 5),
      catalogStatus: item.catalog_status === 'matched' ? 'matched' : 'external',
      catalogJobId: String(item.catalog_job_id || '').trim(),
      catalogJobName: String(item.catalog_job_name || '').trim(),
      catalogVersion: String(item.catalog_version || '').trim(),
      matchMethod: String(item.match_method || '').trim(),
      matchConfidence: Math.max(0, Math.min(100, Number(item.match_confidence) || 0)),
      suggestionStatus: String(item.suggestion_status || '').trim(),
      nearestCatalogJobName: String(item.nearest_catalog_job_name || '').trim(),
      abilityMatrix: Array.isArray(item.ability_matrix) ? item.ability_matrix : [],
    }))
    .sort((left, right) => right.score - left.score || left.name.localeCompare(right.name, 'zh-CN'))
    .slice(0, 4);
}

function normalizeCandidateSummary(value, fallback) {
  if (typeof value !== 'string') return fallback;
  const summary = value.trim();
  if (!summary || /^\s*[\[{]/.test(summary)) return fallback;
  return summary
    .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, '[邮箱已隐藏]')
    .replace(/(?:\+?86[-\s]?)?1[3-9]\d{9}/g, '[手机号已隐藏]');
}

function normalizeResumeAnalysisMeta(record) {
  if (!record || typeof record !== 'object') return null;
  const provider = String(record.provider || 'local').trim().toLowerCase();
  const rawError = String(record.error_message || '').trim();
  let errorSummary = '';
  if (/ssl|eof|certificate/i.test(rawError)) errorSummary = '模型服务的 SSL 连接被中断';
  else if (/timeout|timed out/i.test(rawError)) errorSummary = '模型服务连接超时';
  else if (/429|rate limit/i.test(rawError)) errorSummary = '模型服务请求频率受限';
  else if (rawError) errorSummary = '模型服务本次调用失败';
  return {
    provider,
    isLocal: provider === 'local',
    errorSummary,
  };
}

function buildResumeAnalysisFromStructured(text, fileName, structured, confirmedRole = '') {
  const base = buildResumeAnalysis(text, fileName);
  if (!structured || typeof structured !== 'object') return base;

  const directions = normalizeRecommendedDirections(structured.recommended_directions);
  const primaryDirection = directions[0];
  const projects = Array.isArray(structured.projects) ? structured.projects.filter((item) => item && typeof item === 'object') : [];
  const projectHighlights = projects.flatMap((project) => normalizeAnalysisList(project.highlights, 3));
  const questions = projects.flatMap((project) => normalizeAnalysisList(project.possible_questions, 3));
  const coreSkills = normalizeAnalysisList(structured.core_skills, 8);
  const riskPoints = normalizeAnalysisList(structured.risk_points, 6);
  const primaryReasons = primaryDirection?.reasons || [];
  const primaryGaps = primaryDirection?.gaps || [];
  const targetRole = primaryDirection?.name || confirmedRole || '等待确认目标方向';

  return {
    ...base,
    matchScore: primaryDirection?.score || base.matchScore,
    scoreLabel: primaryDirection ? '方向匹配度' : base.scoreLabel,
    targetRole,
    directions,
    summary: normalizeCandidateSummary(structured.candidate_summary, base.summary),
    parsedSections: [
      { label: '来源文件', value: fileName || '已保存简历' },
      { label: '文本规模', value: `${String(text || '').trim().length} 个字符` },
      { label: '分析依据', value: '仅使用当前上传或粘贴的简历正文，不混入旧项目文本和已确认岗位' },
      { label: '核心技能', value: coreSkills.length ? coreSkills.join('、') : '待补充技能证据' },
      { label: '学生确认', value: confirmedRole || '尚未确认，可从推荐方向中选择或自定义' },
    ],
    highlights: [...primaryReasons, ...projectHighlights].slice(0, 4).length
      ? [...primaryReasons, ...projectHighlights].slice(0, 4)
      : base.highlights,
    risks: [...riskPoints, ...primaryGaps].slice(0, 5).length
      ? [...riskPoints, ...primaryGaps].slice(0, 5)
      : base.risks,
    questions: questions.length ? questions.slice(0, 5) : base.questions,
  };
}

function buildBriefFromResumeAnalysis(analysis) {
  if (!analysis || typeof analysis !== 'object') return '';

  const sections = [];
  const summary = String(analysis.candidate_summary || '').trim();
  const skills = normalizeAnalysisList(analysis.core_skills, 6);
  const risks = normalizeAnalysisList(analysis.risk_points, 3);
  const directions = normalizeRecommendedDirections(analysis.recommended_directions);
  const projects = Array.isArray(analysis.projects) ? analysis.projects.filter((item) => item && typeof item === 'object').slice(0, 2) : [];
  const questions = projects.flatMap((project) => normalizeAnalysisList(project.possible_questions, 2)).slice(0, 4);

  if (summary) sections.push(`候选人概述：${summary}`);
  if (directions.length) {
    sections.push(`推荐方向：${directions.map((item) => `${item.name}（${item.score}分）`).join('、')}`);
  }
  if (skills.length) sections.push(`核心技能：${skills.join('、')}`);
  if (projects.length) {
    const projectText = projects
      .map((project) => {
        const name = String(project.name || '核心项目').trim();
        const role = String(project.role || '').trim();
        const highlights = normalizeAnalysisList(project.highlights, 3);
        return `${name}${role ? `（${role}）` : ''}${highlights.length ? `：${highlights.join('、')}` : ''}`;
      })
      .join('；');
    sections.push(`重点项目：${projectText}`);
  }
  if (questions.length) sections.push(`建议追问：${questions.join('；')}`);
  if (risks.length) sections.push(`待验证点：${risks.join('、')}`);

  return sections.join('\n');
}

function hasResumeAnalysisSource(profile) {
  if (!profile || typeof profile !== 'object') return false;
  return [
    'target_role',
    'experience_level',
    'years_of_experience',
    'education_level',
    'skills',
    'project_keywords',
    'resume_text',
    'project_experience',
  ].some((field) => String(profile[field] || '').trim());
}

const defaultProfile = {
  nickname: '',
  avatar_url: '',
  target_role: '',
  experience_level: '',
  company_type: '',
  target_city: '',
  expected_salary: '',
  years_of_experience: '',
  education_level: '',
  skills: '',
  project_keywords: '',
  resume_filename: '',
  resume_text: '',
  project_experience: '',
  portfolio_links: '',
  preferred_interview_type: '',
  preferred_difficulty: '',
  preferred_interviewer_style: '',
};

const dimensionLabels = {
  technical_accuracy: '技术准确性',
  technical_depth: '技术深度',
  expression_clarity: '表达清晰度',
  business_understanding: '业务理解',
  tradeoff_reasoning: '权衡决策',
  risk_awareness: '风险意识',
  result_quantification: '结果量化',
  role_fit: '岗位匹配度',
};

const dimensionTrainingCopy = {
  technical_accuracy: '选择一道近期技术题，先给出明确结论，再补充适用边界和反例验证。',
  technical_depth: '围绕一个真实项目，补齐原理、方案取舍、异常链路和工程落地四层回答。',
  expression_clarity: '使用“结论—背景—行动—结果”结构完成一次 3 分钟限时表达训练。',
  business_understanding: '为近期项目补充业务目标、核心指标、用户影响和最终收益。',
  tradeoff_reasoning: '准备两套备选方案，对比成本、风险、收益并说明最终选择依据。',
  risk_awareness: '复盘一次线上变更，补齐监控、灰度、止损和回滚触发条件。',
  result_quantification: '为项目成果补充基线、统计口径和至少一个可验证的量化结果。',
  role_fit: '对照目标岗位职责，整理三个最能证明胜任力的项目证据。',
};

const recommendationLabels = {
  strong_pass: '强烈建议通过',
  pass: '建议通过',
  borderline: '谨慎推进',
  no_pass: '暂不通过',
  insufficient_evidence: '证据不足',
};

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
const OPENAI_REALTIME_AUDIO_CONSTRAINTS = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
};

function apiUrl(path) {
  return `${apiBaseUrl}${path}`;
}

function apiWsUrl(path) {
  if (apiBaseUrl.startsWith('https://')) return `${apiBaseUrl.replace(/^https:/, 'wss:')}${path}`;
  if (apiBaseUrl.startsWith('http://')) return `${apiBaseUrl.replace(/^http:/, 'ws:')}${path}`;
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}${path}`;
}

function parseJsonValue(value, fallback) {
  if (!value) return fallback;
  if (typeof value !== 'string') return value;

  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

function formatDateTime(value) {
  if (!value) return '暂无';
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function createInitialQuestion(interview, agent) {
  const role = interview?.target_role || '目标岗位';
  const focus = interview?.focus_areas || '项目经历';
  return `我们先从你的${focus}开始。请结合一次真实经历，说明你在${role}相关工作中遇到的关键问题、你的行动以及最终结果。`;
}

function includesAny(text, keywords) {
  return keywords.some((keyword) => text.includes(keyword));
}

function pickMentionedTopic(text) {
  const topics = [
    'React',
    'Vue',
    'Node',
    '性能',
    '低代码',
    '表单',
    '组件库',
    '架构',
    '缓存',
    '数据库',
    '接口',
    '监控',
    '灰度',
    '回滚',
    '埋点',
    '虚拟滚动',
    '懒加载',
    '状态管理',
    '团队协作',
  ];
  return topics.find((topic) => text.includes(topic)) || '这个项目';
}

function pickUnusedQuestion(candidates, askedQuestions) {
  return candidates.find((question) => !askedQuestions.some((asked) => asked.includes(question.slice(0, 16)))) || candidates[0];
}

function analyzeAnswerCoverage(answer) {
  const text = String(answer || '');
  return {
    background: includesAny(text, ['背景', '业务', '场景', '目标', '问题']),
    responsibility: includesAny(text, ['负责', '我做', '我来', '主导', '推进', 'owner', 'Owner']),
    solution: /方案|设计|实现|改造|优化|拆分|封装|接入|建设|React|Vue|Node|Schema|schema/.test(text),
    tradeoff: includesAny(text, ['取舍', '权衡', '备选', '为什么', '成本', '复杂度', '边界']),
    metrics: /指标|数据|百分比|耗时|成本|收益|成功率|转化率|P95|PV|UV|QPS|ms|秒|提升|降低/.test(text),
    risk: includesAny(text, ['风险', '线上', '故障', '异常', '回滚', '灰度', '监控', '报警', '稳定性']),
    collaboration: includesAny(text, ['协作', '推动', '沟通', '团队', '评审', '对齐', '产品', '业务方']),
    reflection: includesAny(text, ['复盘', '沉淀', '规范', '推广', '重新', '改进', '方法论']),
  };
}

function summarizeCoverage(messages, nextAnswer = '') {
  const answers = [
    ...messages.filter((item) => item.sender_type === 'candidate').map((item) => item.content || item.text || ''),
    nextAnswer,
  ].filter(Boolean);

  return answers.reduce(
    (summary, answer) => {
      const coverage = analyzeAnswerCoverage(answer);
      Object.entries(coverage).forEach(([key, value]) => {
        summary[key] = summary[key] || value;
      });
      return summary;
    },
    {
      background: false,
      responsibility: false,
      solution: false,
      tradeoff: false,
      metrics: false,
      risk: false,
      collaboration: false,
      reflection: false,
    }
  );
}

function countCovered(coverage, keys) {
  return keys.filter((key) => coverage[key]).length;
}

function getAgentRound(messages, agent) {
  if (!agent) return 0;
  const lastOtherAgentMessageIndex = messages.reduce((matchedIndex, item, index) => {
    return item.sender_type === 'agent' && item.agent_id && item.agent_id !== agent.id ? index : matchedIndex;
  }, -1);
  return messages.slice(lastOtherAgentMessageIndex + 1).filter((item) => item.sender_type === 'candidate').length;
}

function createAgentOpeningQuestion(nextAgent, interview, coverage) {
  const role = interview?.target_role || '目标岗位';
  if (nextAgent?.agent_type === 'architecture') {
    const missing = !coverage.risk
      ? '灰度、回滚和观测体系'
      : !coverage.tradeoff
        ? '模块边界和方案取舍'
        : '长期演进和复杂度治理';
    return `技术一面先了解到这里，接下来进入架构二面。我们换一个视角：如果这个项目要支撑更多业务线，你会如何设计${missing}？`;
  }
  if (nextAgent?.agent_type === 'hr') {
    return `架构二面先到这里，接下来进入 HR 面。我想了解一下你的职业动机：你现在选择${role}相关机会时，最看重团队和岗位的哪些因素？`;
  }
  return `我们进入下一轮面试。请结合${role}要求，补充一个最能体现你能力的真实经历。`;
}

function createAgentClosing(agent, nextAgent, coverage) {
  if (agent?.agent_type === 'technical') {
    return `技术一面我先了解到这里。你已经覆盖了项目背景、方案实现和部分结果验证，当前信息足够进入下一轮；剩下的系统边界和长期治理，我会交给${nextAgent?.agent_name || '架构二面 Agent'}继续追问。`;
  }
  if (agent?.agent_type === 'architecture') {
    return `架构二面我先了解到这里。系统设计、复杂度治理和风险意识已经有了基本判断，接下来切到${nextAgent?.agent_name || 'HR Agent'}，看一下动机、协作和稳定性。`;
  }
  return '这一轮我先了解到这里。';
}

function decideNextInterviewAction({ interview, agents, messages, activeAgent, lastAnswer }) {
  const coverage = summarizeCoverage(messages, lastAnswer);
  const round = getAgentRound(messages, activeAgent) + 1;
  const askedQuestions = messages.filter((item) => item.sender_type === 'agent').map((item) => item.content || '');
  const nextAgent = agents.find((agent) => agent.order_index > (activeAgent?.order_index ?? 0) && agent.status !== 'completed');
  const agentType = activeAgent?.agent_type || 'technical';

  if (agentType === 'technical') {
    const enoughCoverage = countCovered(coverage, ['background', 'responsibility', 'solution', 'tradeoff', 'metrics', 'risk']) >= 4;
    if ((round >= 5 && enoughCoverage) || round >= 7) {
      return nextAgent
        ? {
            action: 'switch_agent',
            closing: createAgentClosing(activeAgent, nextAgent, coverage),
            nextAgent,
            opening: createAgentOpeningQuestion(nextAgent, interview, coverage),
          }
        : { action: 'finish_interview', closing: '技术一面的信息已经足够，我会结束本场模拟并生成报告。' };
    }
  }

  if (agentType === 'architecture') {
    const enoughCoverage = countCovered(coverage, ['solution', 'tradeoff', 'metrics', 'risk', 'reflection']) >= 4;
    if ((round >= 4 && enoughCoverage) || round >= 6) {
      return nextAgent
        ? {
            action: 'switch_agent',
            closing: createAgentClosing(activeAgent, nextAgent, coverage),
            nextAgent,
            opening: createAgentOpeningQuestion(nextAgent, interview, coverage),
          }
        : { action: 'finish_interview', closing: '架构面的信息已经足够，我会结束本场模拟并生成报告。' };
    }
  }

  if (agentType === 'hr' && round >= 3) {
    return {
      action: 'finish_interview',
      closing: 'HR 面我先了解到这里。这场模拟面试的信息已经足够，接下来可以生成综合报告。',
    };
  }

  return {
    action: 'ask_follow_up',
    question: createFollowUpQuestion(lastAnswer, interview, messages, activeAgent),
    askedQuestions,
  };
}

function createFollowUpQuestion(answer, interview, messages = [], activeAgent = null) {
  const text = String(answer || '');
  const targetRole = interview?.target_role || '目标岗位';
  const candidateRound = getAgentRound(messages, activeAgent) + 1;
  const askedQuestions = messages
    .filter((item) => item.sender_type === 'agent')
    .map((item) => item.content || '');
  const topic = pickMentionedTopic(text);
  const hasMetric = /指标|数据|百分比|耗时|成本|收益|成功率|转化率|P95|PV|UV|QPS|ms|秒/.test(text);
  const hasTradeoff = /取舍|权衡|边界|风险|限制|方案|设计|架构|模块/.test(text);
  const hasCollaboration = /协作|推动|沟通|团队|评审|对齐|产品|业务方/.test(text);
  const hasIncident = /线上|故障|异常|回滚|灰度|监控|报警|稳定性/.test(text);
  const agentType = activeAgent?.agent_type || 'technical';

  if (agentType === 'architecture') {
    const architectureQuestions = [
      [
        `从架构角度看，如果${topic}要支撑多个业务线，你会如何拆分核心模块和扩展点？`,
        `你会如何定义 schema、渲染器、组件协议和业务插件之间的边界？`,
      ],
      [
        `如果历史页面已经接入旧协议，你会怎么做版本兼容、迁移和灰度？`,
        `哪些能力应该沉淀到平台，哪些逻辑必须留在业务侧？你怎么判断？`,
      ],
      [
        hasIncident
          ? '你刚才提到线上风险，架构层面会设计哪些观测指标、降级策略和回滚开关？'
          : '如果平台能力出问题会影响多个业务线，你会怎么设计监控、降级和止损链路？',
        '这个系统最容易失控的复杂度在哪里？你会用什么治理机制长期控制？',
      ],
      [
        `如果让你作为${targetRole} owner 推进半年路线图，你会优先做哪三件事？为什么？`,
        '你如何衡量这个平台架构是否成功？除了性能指标，还会看哪些工程和业务指标？',
      ],
    ];
    return pickUnusedQuestion(architectureQuestions[Math.min(candidateRound - 1, architectureQuestions.length - 1)], askedQuestions);
  }

  if (agentType === 'hr') {
    const hrQuestions = [
      [
        `你为什么会考虑${targetRole}这个方向？它和你下一阶段的成长目标怎么匹配？`,
        '你在选择团队时最看重什么？业务空间、技术深度、团队氛围还是成长节奏？',
      ],
      [
        hasCollaboration
          ? '你刚才提到协作，能讲一个你和业务方或同事目标不一致但最后推进成功的例子吗？'
          : '如果你和产品、后端或测试对优先级判断不一致，你通常怎么处理？',
        '过去一段经历里，什么样的管理方式最能激发你的状态？什么方式会明显消耗你？',
      ],
      [
        '如果入职后发现项目历史包袱比预期重，你会怎么调整预期并建立短期成果？',
        '你希望面试官通过这场面试记住你的哪三个关键词？',
      ],
    ];
    return pickUnusedQuestion(hrQuestions[Math.min(candidateRound - 1, hrQuestions.length - 1)], askedQuestions);
  }

  const stageQuestions = [
    [
      `你刚才提到${topic}，先把项目背景讲实一点：当时业务目标是什么，你个人负责到哪一层？`,
      `如果只看你负责的部分，${topic}里面最难解决的一个点是什么？为什么它不是常规开发能顺手解决的？`,
      `这个项目在开始前有哪些约束，比如时间、人力、历史包袱或线上风险？你是怎么判断优先级的？`,
    ],
    [
      hasTradeoff
        ? `你提到了方案设计，我想继续追一下取舍：当时至少有哪些备选方案，为什么最后选了这一种？`
        : `你刚才更多讲了做法，能不能补一下方案选择过程：你排除过哪些方案，它们的问题分别是什么？`,
      `围绕${topic}，如果让你画一张模块关系图，核心链路会怎么拆？哪些部分必须隔离？`,
      `这个方案有没有引入新的复杂度？比如维护成本、学习成本、兼容成本，你当时怎么控制？`,
    ],
    [
      hasMetric
        ? `你提到了指标，我追一下数据口径：这些数据从哪里采集，如何排除缓存、网络和样本差异的影响？`
        : `这里我还缺少结果验证。上线前后你看了哪些指标，怎么证明优化真的有效？`,
      `如果优化后技术指标变好了，但业务方感知不明显，你会怎么复盘这个结果？`,
      `有没有一个具体数字能说明收益？比如耗时、错误率、人效、投诉量或交付周期的变化。`,
    ],
    [
      hasIncident
        ? `你提到了线上风险，那灰度和回滚方案具体怎么设计？什么情况下会触发回滚？`
        : `如果这个改动上线后出现性能回退或兼容问题，你会怎么监控、止损和定位？`,
      `这个项目有没有失败或反复的地方？如果重新做一遍，你会提前改变哪一个决策？`,
      `站在${targetRole}的要求看，这个项目最能证明你能力的一点是什么？有没有可复用的方法论沉淀下来？`,
    ],
    [
      hasCollaboration
        ? `你提到了协作，我想听一个具体冲突：谁和谁的目标不一致，你怎么推动大家接受方案？`
        : `这个方案落地时依赖哪些角色配合？如果业务团队不愿意改接入方式，你会怎么推动？`,
      `后续有没有把这套能力推广到其他页面或团队？推广过程中遇到的最大阻力是什么？`,
      `如果让你带一个同学继续维护这块，你会沉淀哪些规范、工具或检查机制？`,
    ],
  ];

  const stageIndex = Math.min(candidateRound - 1, stageQuestions.length - 1);
  return pickUnusedQuestion(stageQuestions[stageIndex], askedQuestions);
}

function reportToViewModel(reportData, user) {
  const abilityRadar = parseJsonValue(reportData?.ability_radar, {});
  const agentFeedback = parseJsonValue(reportData?.agent_feedback, []);
  const timelineReview = parseJsonValue(reportData?.timeline_review, []);
  const suggestions = String(reportData?.suggestions || '')
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean);
  const timeline = [];
  let latestQuestion = null;
  timelineReview.forEach((item) => {
    if (item.sender_type === 'agent' && item.message_type !== 'system') {
      latestQuestion = item;
      return;
    }
    if (item.sender_type !== 'candidate') return;
    const question = item.question_preview || latestQuestion?.content_preview || '未记录对应问题';
    const interviewer = item.agent_name || latestQuestion?.agent_name || '面试官';
    timeline.push({
      id: item.message_id || `${item.order_index}-${timeline.length}`,
      type: interviewer.includes('HR') ? 'hr' : 'tech',
      title: `${interviewer} · 问答复盘`,
      question,
      answer: item.answer_preview || item.content_preview,
      review: reportScore(item.score) !== null ? `本题得分 ${item.score}/100。建议结合报告中的能力维度和训练任务继续优化。` : '本题暂无单独评分。',
      score: reportScore(item.score),
      strengths: item.strengths || '',
      issues: item.issues || '',
      suggestion: item.suggestions || '',
    });
    latestQuestion = null;
  });

  // Older reports may have been saved as "succeeded" even though no candidate
  // answer existed. The deterministic timeline is the evidence source of truth.
  const hasEvidence = reportData?.generation_status !== 'insufficient_evidence' && timeline.length > 0;

  return {
    candidate: user?.name || '候选人',
    role: reportData?.target_role || '目标岗位',
    result: hasEvidence ? (recommendationLabels[reportData?.pass_recommendation] || '待判断') : '证据不足',
    grade: hasEvidence ? (reportData?.grade || '-') : '-',
    score: hasEvidence ? (reportData?.total_score || 0) : 0,
    generatedAt: formatDateTime(reportData?.updated_at || reportData?.created_at),
    interviewId: reportData?.interview_id || '-',
    provider: reportData?.provider || 'local',
    model: reportData?.model || 'rules-v1',
    promptVersion: reportData?.prompt_version || 'legacy-local-v1',
    generationStatus: reportData?.generation_status || 'succeeded',
    reviewStatus: reportData?.review_status || 'pending',
    fallback: Boolean(reportData?.fallback),
    hasEvidence,
    generationError: reportData?.generation_error || '',
    summary: hasEvidence ? (reportData?.summary || '暂无报告摘要。') : '本次面试未记录到候选人回答，缺少可用于评分和复盘的证据，因此不生成综合评分、能力指标或推进建议。',
    suggestions: hasEvidence ? suggestions : [],
    radar: (hasEvidence ? Object.entries(abilityRadar) : []).filter(([, value]) => reportScore(value) !== null).map(([key, value]) => ({
      subject: dimensionLabels[key] || key,
      value: reportScore(value),
    })),
    metrics: (hasEvidence ? Object.entries(abilityRadar) : []).map(([key, value]) => ({
      label: dimensionLabels[key] || key,
      value: reportScore(value),
      note: `本场${dimensionLabels[key] || key}表现为 ${Number(value) || 0}/100，综合单题回答证据生成。`,
    })),
    interviewers: agentFeedback.map((item) => {
      const hasScore = hasInterviewerEvaluation(item);
      return {
        name: item.agent_name,
        evaluated: hasEvidence && hasScore,
        decision: hasEvidence && hasScore ? (item.score >= 80 ? '表现稳定' : item.score >= 70 ? '继续观察' : '需要加强') : '证据不足',
        color: hasEvidence && hasScore ? (item.score >= 80 ? 'green' : item.score >= 70 ? 'blue' : 'amber') : 'blue',
        text: hasEvidence ? item.comment : '未记录到候选人回答，无法形成可靠评价。',
      };
    }),
    timeline,
  };
}

async function apiRequest(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  });
  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    const requestError = new Error(data.error || '请求失败，请稍后再试。');
    requestError.status = response.status;
    requestError.data = data;
    throw requestError;
  }

  return data;
}

const QWEN_TTS_MIME_TYPE = 'audio/mpeg';
const OMNI_PCM_SAMPLE_RATE = Number(import.meta.env.VITE_QWEN_OMNI_PCM_SAMPLE_RATE || 24000);

async function apiAudioResponse(path, body, signal) {
  const response = await fetch(apiUrl(path), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || data.detail || '语音合成失败，请稍后再试。');
  }

  return response;
}

function getMediaSourceConstructor() {
  return window.MediaSource || window.ManagedMediaSource;
}

function normalizeQwenAudioMimeType(value) {
  const mediaType = String(value || QWEN_TTS_MIME_TYPE).split(';')[0].trim().toLowerCase();
  if (mediaType === 'audio/mpeg' || mediaType === 'audio/mp3') return 'audio/mpeg';
  if (mediaType === 'audio/ogg') return 'audio/ogg; codecs=opus';
  if (mediaType === 'audio/wav' || mediaType === 'audio/wave') return 'audio/wav';
  if (mediaType === 'audio/pcm') return 'audio/pcm';
  return QWEN_TTS_MIME_TYPE;
}

function canStreamAudioWithMediaSource(mediaType = QWEN_TTS_MIME_TYPE) {
  const MediaSourceConstructor = getMediaSourceConstructor();
  return Boolean(
    MediaSourceConstructor &&
      MediaSourceConstructor.isTypeSupported &&
      MediaSourceConstructor.isTypeSupported(mediaType)
  );
}

function concatArrayBuffers(chunks) {
  const totalLength = chunks.reduce((sum, chunk) => sum + chunk.byteLength, 0);
  const bytes = new Uint8Array(totalLength);
  let offset = 0;
  chunks.forEach((chunk) => {
    const view = chunk instanceof ArrayBuffer ? new Uint8Array(chunk) : new Uint8Array(chunk.buffer || chunk);
    bytes.set(view, offset);
    offset += view.byteLength;
  });
  return bytes;
}

function textHeader(bytes, length = 4) {
  return String.fromCharCode(...bytes.slice(0, length));
}

function buildWavBlobFromPcm16(pcmBytes, sampleRate = OMNI_PCM_SAMPLE_RATE) {
  const header = new ArrayBuffer(44);
  const view = new DataView(header);
  const writeText = (offset, text) => {
    for (let index = 0; index < text.length; index += 1) {
      view.setUint8(offset + index, text.charCodeAt(index));
    }
  };

  writeText(0, 'RIFF');
  view.setUint32(4, 36 + pcmBytes.byteLength, true);
  writeText(8, 'WAVE');
  writeText(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeText(36, 'data');
  view.setUint32(40, pcmBytes.byteLength, true);
  return new Blob([header, pcmBytes], { type: 'audio/wav' });
}

function buildOmniAudioBlob(chunks) {
  const bytes = concatArrayBuffers(chunks);
  const header = textHeader(bytes);
  if (header === 'RIFF') return new Blob([bytes], { type: 'audio/wav' });
  if (header === 'OggS') return new Blob([bytes], { type: 'audio/ogg' });
  if (header === 'ID3' || (bytes[0] === 0xff && (bytes[1] & 0xe0) === 0xe0)) {
    return new Blob([bytes], { type: 'audio/mpeg' });
  }
  return buildWavBlobFromPcm16(bytes);
}

function toUint8Array(chunk) {
  if (chunk instanceof Uint8Array) return chunk;
  if (chunk instanceof ArrayBuffer) return new Uint8Array(chunk);
  if (chunk?.buffer instanceof ArrayBuffer) {
    return new Uint8Array(chunk.buffer, chunk.byteOffset || 0, chunk.byteLength || chunk.buffer.byteLength);
  }
  return new Uint8Array(chunk || []);
}

function isEncodedAudioBytes(bytes) {
  const header = textHeader(bytes);
  return header === 'RIFF' || header === 'OggS' || header === 'ID3' || (bytes[0] === 0xff && (bytes[1] & 0xe0) === 0xe0);
}

function createPcm16AudioBuffer(audioContext, chunk, sampleRate = OMNI_PCM_SAMPLE_RATE) {
  const bytes = toUint8Array(chunk);
  const alignedLength = bytes.byteLength - (bytes.byteLength % 2);
  const sampleCount = alignedLength / 2;
  const audioBuffer = audioContext.createBuffer(1, sampleCount, sampleRate);
  const output = audioBuffer.getChannelData(0);
  const view = new DataView(bytes.buffer, bytes.byteOffset, alignedLength);

  for (let index = 0; index < sampleCount; index += 1) {
    const sample = view.getInt16(index * 2, true);
    output[index] = Math.max(-1, Math.min(1, sample / 32768));
  }

  return audioBuffer;
}

function getSpeechRecognitionConstructor() {
  return window.SpeechRecognition || window.webkitSpeechRecognition;
}

function waitForMediaSourceOpen(mediaSource) {
  return new Promise((resolve, reject) => {
    if (mediaSource.readyState === 'open') {
      resolve();
      return;
    }

    const cleanup = () => {
      mediaSource.removeEventListener('sourceopen', handleOpen);
      mediaSource.removeEventListener('sourceended', handleEnded);
      mediaSource.removeEventListener('sourceclose', handleClose);
    };
    const handleOpen = () => {
      cleanup();
      resolve();
    };
    const handleEnded = () => {
      cleanup();
      reject(new Error('音频流已结束，无法开始播放。'));
    };
    const handleClose = () => {
      cleanup();
      reject(new Error('音频流已关闭，无法开始播放。'));
    };

    mediaSource.addEventListener('sourceopen', handleOpen, { once: true });
    mediaSource.addEventListener('sourceended', handleEnded, { once: true });
    mediaSource.addEventListener('sourceclose', handleClose, { once: true });
  });
}

function appendAudioChunk(sourceBuffer, chunk) {
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      sourceBuffer.removeEventListener('updateend', handleUpdateEnd);
      sourceBuffer.removeEventListener('error', handleError);
      sourceBuffer.removeEventListener('abort', handleAbort);
    };
    const handleUpdateEnd = () => {
      cleanup();
      resolve();
    };
    const handleError = () => {
      cleanup();
      reject(new Error('追加千问音频片段失败。'));
    };
    const handleAbort = () => {
      cleanup();
      reject(new DOMException('千问音频追加已取消。', 'AbortError'));
    };
    sourceBuffer.addEventListener('updateend', handleUpdateEnd, { once: true });
    sourceBuffer.addEventListener('error', handleError, { once: true });
    sourceBuffer.addEventListener('abort', handleAbort, { once: true });
    sourceBuffer.appendBuffer(chunk.buffer.slice(chunk.byteOffset, chunk.byteOffset + chunk.byteLength));
  });
}

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
        <span>{item.value === null ? '未评估' : `${item.value}/100`}</span>
      </div>
      {item.value !== null && <div className="progress-track" aria-label={`${item.label} ${item.value} 分`}>
        <div className="progress-fill" style={{ width: `${item.value}%` }} />
      </div>}
      {item.note && <p>{item.note}</p>}
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
  const [open, setOpen] = useState(false);
  const Icon = item.type === 'hr' ? BriefcaseBusiness : item.type === 'business' ? MessageSquareText : Wrench;

  return (
    <article className={`timeline-item ${open ? 'open' : ''}`}>
      <div className="timeline-marker">
        <Icon size={15} />
      </div>
      <button type="button" className="timeline-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span>
          <small>第 {index + 1} 题 · {item.title.replace(' · 问答复盘', '')}</small>
          <strong className="report-question-preview">{item.question || '未记录对应问题'}</strong>
        </span>
        <span className="timeline-score">{item.score !== null && item.score !== undefined ? `${item.score} 分` : '未评分'}</span>
        <ChevronDown className="chevron" size={18} />
      </button>
      {open && (
        <div className="timeline-body">
          <div className="answer-block question-block">
            <h3>面试问题</h3>
            <p>{item.question || '未记录对应问题'}</p>
          </div>
          <div className="answer-block">
            <h3>候选人回答</h3>
            <p>{item.answer}</p>
          </div>
          <div className="review-block">
            <h3>AI 导师复盘意见</h3>
            {item.strengths || item.issues || item.suggestion ? (
              <div className="review-evidence">
                {item.strengths && <p><strong>回答亮点</strong><span>{item.strengths}</span></p>}
                {item.issues && <p><strong>主要问题</strong><span>{item.issues}</span></p>}
                {item.suggestion && <p><strong>改进建议</strong><span>{item.suggestion}</span></p>}
              </div>
            ) : <p>{item.review}</p>}
          </div>
        </div>
      )}
    </article>
  );
}

function AuthInput({ icon, label, type = 'text', value, onChange, placeholder }) {
  return (
    <label className="auth-field">
      <span>{label}</span>
      <div>
        {icon}
        <input
          type={type}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
        />
      </div>
    </label>
  );
}

function LoginPage({ onAuthenticated }) {
  const initialResetToken = '';
  const [mode, setMode] = useState('login');
  const [resetToken, setResetToken] = useState(initialResetToken);
  const [resetTokenStatus, setResetTokenStatus] = useState(initialResetToken ? 'verifying' : 'idle');
  const [form, setForm] = useState({
    studentNo: '',
    password: '',
    confirmPassword: '',
  });
  const [authError, setAuthError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const updateForm = (key, value) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const removeResetTokenFromUrl = () => {
    const url = new URL(window.location.href);
    url.searchParams.delete('reset_token');
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
  };

  const switchMode = (nextMode) => {
    setMode(nextMode);
    setAuthMessage('');
    setAuthError('');
    if (nextMode !== 'reset-confirm' && resetToken) {
      setResetToken('');
      setResetTokenStatus('idle');
      removeResetTokenFromUrl();
    }
  };

  const isRegister = false;
  const isResetRequest = false;
  const isResetConfirm = false;
  const isReset = isResetRequest || isResetConfirm;
  const title = isResetConfirm
    ? '设置新的登录密码'
    : isResetRequest
      ? '重置登录密码'
      : isRegister
        ? '创建个人训练账号'
        : '使用学号登录';
  const subtitle = isResetConfirm
    ? '重置链接只能使用一次；完成后，所有旧设备上的登录状态都会失效。'
    : isResetRequest
      ? '输入注册邮箱后，系统会发送一次性的密码重置链接。'
      : '账号由学校统一创建。首次登录请使用辅导员发放的临时密码。';

  const handleSubmit = async (event) => {
    event.preventDefault();
    setAuthError('');
    setSubmitting(true);
    try {
      if (isResetRequest) {
        const data = await apiRequest('/api/auth/password-reset/request', {
          method: 'POST',
          body: JSON.stringify({ email: form.email }),
        });
        if (data.devResetToken) {
          setResetToken(data.devResetToken);
          setResetTokenStatus('valid');
          setMode('reset-confirm');
          setAuthMessage('开发环境已生成一次性重置凭证，请设置新密码。');
          return;
        }
        setAuthMessage('如果邮箱存在，我们会发送密码重置链接。');
        return;
      }

      if (isResetConfirm) {
        const data = await apiRequest('/api/auth/password-reset/confirm', {
          method: 'POST',
          body: JSON.stringify({
            token: resetToken,
            password: form.password,
            confirm_password: form.confirmPassword,
          }),
        });
        setResetToken('');
        setResetTokenStatus('idle');
        setMode('login');
        setForm((current) => ({ ...current, password: '', confirmPassword: '' }));
        removeResetTokenFromUrl();
        setAuthMessage(data.message || '密码已重置，请使用新密码登录。');
        return;
      }

      const data = await apiRequest('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          student_no: form.studentNo,
          password: form.password,
        }),
      });
      onAuthenticated(data.user);
    } catch (error) {
      setAuthError(error.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="auth-shell v4-auth-shell">
      <section className="auth-page">
        <div className="auth-brand-panel">
          <V4Brand />
          <div className="v4-auth-orbit"><div className="v4-orbit v4-orbit-one" /><div className="v4-orbit v4-orbit-two" /><V4Logo /></div>
          <div className="auth-copy">
            <p className="eyebrow">THE NEXT CHAPTER STARTS HERE</p>
            <h1>准备充分，<br />自信发生。</h1>
            <p>你的专属 AI 面试空间</p>
          </div>
          <small className="v4-auth-credit">ASTRAINTERVIEW © 2026</small>
        </div>

        <form className="auth-card" onSubmit={handleSubmit}>
          <V4Brand />
          <div className="auth-card-head">
            <div>
              <h2>欢迎回来</h2>
              <p>为每一次机会，做好准备。</p>
            </div>
          </div>

          <div className="auth-form">
            {!isResetConfirm && (
              <AuthInput
                icon={<GraduationCap size={17} />}
                label="学号"
                value={form.studentNo}
                onChange={(value) => updateForm('studentNo', value)}
                placeholder="请输入学校分配的学号"
              />
            )}
            {!isResetRequest && (
              <AuthInput
                icon={<LockKeyhole size={17} />}
                label="密码"
                type="password"
                value={form.password}
                onChange={(value) => updateForm('password', value)}
                placeholder={isResetConfirm ? '输入至少 8 位的新密码' : '输入登录密码'}
              />
            )}
            {(isRegister || isResetConfirm) && (
              <AuthInput
                icon={<LockKeyhole size={17} />}
                label="确认密码"
                type="password"
                value={form.confirmPassword}
                onChange={(value) => updateForm('confirmPassword', value)}
                placeholder="再次输入密码"
              />
            )}
          </div>

          {!isReset && (
            <div className="auth-options">
              <label>
                <input type="checkbox" defaultChecked />
                保持登录状态
              </label>
            <span>忘记密码请联系辅导员或系统管理员</span>
            </div>
          )}

          {isReset && (
            <div className="auth-options">
              <span>{isResetConfirm && resetTokenStatus === 'verifying' ? '正在校验重置链接...' : '记起密码了？'}</span>
              <button type="button" onClick={() => switchMode('login')}>
                返回登录
              </button>
            </div>
          )}

          {authError && <p className="auth-alert error">{authError}</p>}

          <button
            className="auth-submit"
            type="submit"
            disabled={submitting || (isResetConfirm && resetTokenStatus !== 'valid')}
          >
            {submitting
              ? '处理中...'
              : isResetConfirm
                ? '确认修改密码'
                : isResetRequest
                  ? '发送重置链接'
                  : isRegister
                    ? '创建账号并进入'
                    : '使用学号登录'}
          </button>
        </form>
      </section>
    </main>
  );
}

function InitialPasswordChangePage({ user, onChanged, onLogout }) {
  const [form, setForm] = useState({ password: '', confirmPassword: '' });
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState('');

  const handleSubmit = async (event) => {
    event.preventDefault();
    setFormError('');
    if (form.password !== form.confirmPassword) {
      setFormError('两次输入的密码不一致。');
      return;
    }
    setSubmitting(true);
    try {
      const data = await apiRequest('/api/auth/change-initial-password', {
        method: 'POST',
        body: JSON.stringify({ password: form.password, confirm_password: form.confirmPassword }),
      });
      onChanged(data.user);
    } catch (error) {
      setFormError(error.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="auth-shell v4-auth-shell">
      <section className="auth-page">
        <div className="auth-brand-panel">
          <V4Brand />
          <div className="v4-auth-orbit"><div className="v4-orbit v4-orbit-one" /><div className="v4-orbit v4-orbit-two" /><V4Logo /></div>
          <div className="auth-copy">
            <p className="eyebrow">FIRST LOGIN SECURITY</p>
            <h1>从这里，<br />开始新的旅程。</h1>
            <p>临时密码仅用于首次身份确认。完成改密后，管理员将无法再查看原临时密码。</p>
          </div>
          <small className="v4-auth-credit">ASTRAINTERVIEW © 2026</small>
        </div>
        <form className="auth-card" onSubmit={handleSubmit}>
          <V4Brand />
          <div className="auth-card-head">
            <div><h2>首次登录修改密码</h2><p>学号：{user.studentNo} · {user.name}</p></div>
          </div>
          <div className="auth-form">
            <AuthInput icon={<LockKeyhole size={17} />} label="新密码" type="password" value={form.password} onChange={(value) => setForm((current) => ({ ...current, password: value }))} placeholder="请输入至少 8 位的新密码" />
            <AuthInput icon={<LockKeyhole size={17} />} label="确认新密码" type="password" value={form.confirmPassword} onChange={(value) => setForm((current) => ({ ...current, confirmPassword: value }))} placeholder="再次输入新密码" />
          </div>
          {formError && <p className="auth-alert error">{formError}</p>}
          <button className="auth-submit" type="submit" disabled={submitting}>{submitting ? '正在保存...' : '修改密码并进入系统'}</button>
          <button className="auth-secondary-action" type="button" onClick={onLogout}>退出当前账号</button>
          <p className="auth-notice">密码修改成功后，临时密码立即失效，且无法由管理员恢复查看。</p>
        </form>
      </section>
    </main>
  );
}

function OptionGroup({ label, options, value, onChange }) {
  return (
    <label className="option-group">
      <span>{label}</span>
      <select value={value || ''} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function TextField({ label, value, onChange, placeholder, type = 'text', disabled = false }) {
  return (
    <label className="profile-field">
      <span>{label}</span>
      <input
        type={type}
        value={value || ''}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        disabled={disabled}
      />
    </label>
  );
}

function TextAreaField({ label, value, onChange, placeholder }) {
  return (
    <label className="profile-field wide">
      <span>{label}</span>
      <textarea value={value || ''} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
    </label>
  );
}

function ProfilePage({ user, onUserUpdate, onLogout }) {
  const [profile, setProfile] = useState(defaultProfile);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let mounted = true;

    apiRequest('/api/profile')
      .then((data) => {
        if (mounted) {
          setProfile({ ...defaultProfile, ...(data.profile || {}), nickname: data.profile?.nickname || user.name });
        }
      })
      .catch((requestError) => {
        if (mounted) {
          setError(requestError.message);
        }
      })
      .finally(() => {
        if (mounted) {
          setLoading(false);
        }
      });

    return () => {
      mounted = false;
    };
  }, [user.name]);

  const updateProfile = (key, value) => {
    setProfile((current) => ({ ...current, [key]: value }));
    setMessage('');
    setError('');
  };

  const handleSave = async (event) => {
    event.preventDefault();
    setSaving(true);
    setMessage('');
    setError('');

    try {
      const data = await apiRequest('/api/profile', {
        method: 'PUT',
        body: JSON.stringify(profile),
      });
      setProfile({ ...defaultProfile, ...(data.profile || {}) });
      onUserUpdate({ ...user, name: data.profile?.nickname || user.name });
      setMessage('个人资料已保存，新的面试配置会优先参考这些信息。');
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <section className="profile-page">
        <div className="profile-loading">正在读取个人训练档案</div>
      </section>
    );
  }

  return (
    <form className="profile-page v4-profile-page" onSubmit={handleSave}>
      <V4PageHeading eyebrow="YOUR PERSONAL ARCHIVE" title="个人资料" description="整理求职目标与项目经历，让每场面试更贴近你的方向。" />
      <section className="profile-hero">
        <div className="profile-identity">
          <div className="profile-avatar">
            {profile.avatar_url ? <img src={profile.avatar_url} alt="" /> : <UserRound size={34} />}
          </div>
          <div>
            <p className="eyebrow">PERSONAL INTERVIEW PROFILE</p>
            <h2>{profile.nickname || user.name}</h2>
            <span>你的信息会用于生成面试官策略与复盘建议。</span>
          </div>
        </div>
        <button className="primary-action" type="submit" disabled={saving}>
          <Save size={17} />
          {saving ? '保存中' : '保存资料'}
        </button>
      </section>

      {(message || error) && (
        <div className={`profile-message ${error ? 'error' : 'success'}`}>{error || message}</div>
      )}

      <section className="profile-layout">
        <aside className="profile-sidebar">
          <div className="profile-summary">
            <strong>{profile.nickname || user.name}</strong>
            <span>{user.email}</span>
            <p>{profile.target_role || '还没有设置目标岗位'}</p>
          </div>
          <div className="profile-anchor-list">
            <a href="#basic">基础资料</a>
            <a href="#target">求职目标</a>
            <a href="#background">技能背景</a>
            <a href="#resume">简历资料</a>
            <a href="#preference">面试偏好</a>
            <a href="#security">账号安全</a>
          </div>
        </aside>

        <div className="profile-content">
          <Card title="基础资料" icon={<UserRound size={18} />} className="profile-section-card">
            <div className="profile-form-grid" id="basic">
              <TextField label="昵称" value={profile.nickname} onChange={(value) => updateProfile('nickname', value)} />
              <TextField label="邮箱" value={user.email} onChange={() => {}} disabled />
              <TextField label="头像链接" value={profile.avatar_url} onChange={(value) => updateProfile('avatar_url', value)} placeholder="https://..." />
            </div>
          </Card>

          <Card title="我的目标" icon={<BriefcaseBusiness size={18} />} className="profile-section-card">
            <div className="profile-form-grid" id="target">
              <TextField label="目标岗位" value={profile.target_role} onChange={(value) => updateProfile('target_role', value)} placeholder="前端开发 / AI Agent 工程师" />
              <TextField label="经验水平" value={profile.experience_level} onChange={(value) => updateProfile('experience_level', value)} placeholder="应届 / 初级 / 中级 / 高级" />
              <TextField label="目标公司类型" value={profile.company_type} onChange={(value) => updateProfile('company_type', value)} placeholder="大厂 / 创业公司 / 外企" />
              <TextField label="目标城市" value={profile.target_city} onChange={(value) => updateProfile('target_city', value)} placeholder="上海 / 北京 / 远程" />
              <TextField label="期望薪资" value={profile.expected_salary} onChange={(value) => updateProfile('expected_salary', value)} placeholder="例如 25k-35k" />
            </div>
          </Card>

          <Card title="技能背景" icon={<Wrench size={18} />} className="profile-section-card">
            <div className="profile-form-grid" id="background">
              <TextField label="工作年限" value={profile.years_of_experience} onChange={(value) => updateProfile('years_of_experience', value)} placeholder="例如 3 年" />
              <TextField label="学历背景" value={profile.education_level} onChange={(value) => updateProfile('education_level', value)} placeholder="本科 / 硕士 / 自学转行" />
              <TextField label="技能标签" value={profile.skills} onChange={(value) => updateProfile('skills', value)} placeholder="React, Node.js, SQL, Agent" />
              <TextField label="项目关键词" value={profile.project_keywords} onChange={(value) => updateProfile('project_keywords', value)} placeholder="低代码、性能优化、RAG、支付链路" />
            </div>
          </Card>

          <Card title="简历资料" icon={<FileText size={18} />} className="profile-section-card">
            <div className="profile-form-grid" id="resume">
              <TextAreaField label="简历文本" value={profile.resume_text} onChange={(value) => updateProfile('resume_text', value)} placeholder="粘贴你的简历核心内容，AI 会用于项目深挖和追问。" />
              <TextAreaField label="项目经历" value={profile.project_experience} onChange={(value) => updateProfile('project_experience', value)} placeholder="写下最想被练习的项目背景、职责、难点和结果。" />
              <TextField label="作品链接" value={profile.portfolio_links} onChange={(value) => updateProfile('portfolio_links', value)} placeholder="GitHub / 博客 / 作品集链接" />
              <div className="privacy-note">
                <ShieldCheck size={16} />
                <span>简历和面试记录仅用于生成你的模拟面试与复盘报告，不会展示给其他用户。</span>
              </div>
            </div>
          </Card>

          <Card title="面试偏好" icon={<Sparkles size={18} />} className="profile-section-card">
            <div className="profile-form-grid" id="preference">
              <TextField label="默认面试类型" value={profile.preferred_interview_type} onChange={(value) => updateProfile('preferred_interview_type', value)} placeholder="技术一面 / HR 面 / 综合模拟" />
              <TextField label="默认难度" value={profile.preferred_difficulty} onChange={(value) => updateProfile('preferred_difficulty', value)} placeholder="轻松 / 标准 / 严格" />
              <TextField label="面试官风格" value={profile.preferred_interviewer_style} onChange={(value) => updateProfile('preferred_interviewer_style', value)} placeholder="友好引导 / 犀利追问" />
            </div>
          </Card>

          <Card title="账号安全" icon={<KeyRound size={18} />} className="profile-section-card">
            <div className="security-panel" id="security">
              <div>
                <strong>最近登录时间</strong>
                <span>{user.lastLoginAt || '暂无记录'}</span>
              </div>
              <div>
                <strong>登录账号</strong>
                <span>{user.email}</span>
              </div>
              <button type="button" className="secondary-action" onClick={onLogout}>
                <LogOut size={16} />
                退出登录
              </button>
            </div>
          </Card>
        </div>
      </section>
    </form>
  );
}

const RESUME_FORM_FIELDS = [
  ['professional_skills', '职业技能与经验', '描述你的专业能力、岗位技能和相关实践经验'],
  ['advantages', '我的优势', '你相比其他候选人的核心竞争力'],
  ['education', '教育经验', '学校、学历、专业及主要课程或学习成果'],
  ['honors', '在校荣誉/职务', '奖学金、荣誉称号、学生会或社团职务等'],
  ['projects', '项目经历', '参与过的项目、职责、技术方案与成果数据'],
  ['languages', '语言', '掌握的语言及熟练程度'],
  ['works', '个人作品', '作品集、GitHub、博客或可展示的成果链接'],
  ['skills', '技能', '技能关键词，例如：Python、MySQL、数据分析'],
  ['certificates', '证书', '专业证书、语言证书或竞赛证书'],
  ['bonus', '加分项', '其他能体现你优势的经历或特长'],
];
const EMPTY_RESUME_FORM = Object.fromEntries(RESUME_FORM_FIELDS.map(([field]) => [field, '']));

/* ================= Resume form entry pickers ================= */

function SkillModal({ title, description, onClose, footer, wide, children }) {
  return (
    <div className="skill-modal-mask" onClick={onClose}>
      <div className={`skill-modal ${wide ? 'skill-modal-wide' : ''}`} onClick={(event) => event.stopPropagation()}>
        <div className="skill-modal-body">
          <h3>{title}</h3>
          {description && <p className="skill-modal-desc">{description}</p>}
          {children}
        </div>
        {footer && <div className="skill-modal-footer">{footer}</div>}
      </div>
    </div>
  );
}

function EntryButton({ icon, title, progress, onClick }) {
  return (
    <button className="skill-entry-card skill-entry-full" type="button" onClick={onClick}>
      <span className="skill-entry-head">{icon} {title}</span>
      <span className="skill-entry-progress">{progress}</span>
    </button>
  );
}

function SkillTagButton({ label, active, muted, onClick }) {
  return (
    <button
      type="button"
      className={`skill-tag ${active ? 'active' : ''} ${muted ? 'muted' : ''}`}
      onClick={onClick}
    >
      {label}
    </button>
  );
}

/* 已填写计数通用工具：返回 [是否已填, 展示文本] */
function filledText(hasData, countText) {
  return hasData ? countText : '未填写';
}

function SectionBlock({ title, children }) {
  return (
    <div className="skill-question">
      <h4>{title}</h4>
      {children}
    </div>
  );
}

/* ---------- 1. 职业技能与经验 ---------- */
const ROLE_PRESETS = {
  '前端': ['React', 'Vue', 'Angular', 'TypeScript', 'Webpack', 'Vite', '小程序', 'HTML/CSS', '前端性能优化'],
  'Java': ['Java', 'Spring Boot', 'MySQL', 'Redis', 'MyBatis', '微服务', '分布式', 'JVM'],
  'Python': ['Python', 'Django', 'Flask', 'FastAPI', 'Pandas', 'NumPy', '爬虫', '数据处理'],
  '测试': ['功能测试', '接口测试', '自动化测试', 'Selenium', 'Postman', 'JMeter', '测试用例设计'],
  '数据': ['SQL', '数据分析', 'Tableau', 'Power BI', '数据可视化', 'Excel', '统计学'],
  '运维': ['Linux', 'Docker', 'Nginx', 'CI/CD', 'Shell', 'Kubernetes', '云服务'],
  '产品': ['Axure', '需求分析', 'PRD', '用户调研', '原型设计', '竞品分析', '项目管理'],
};
const DEFAULT_PRESETS = ['团队协作', '沟通表达', '学习能力', '问题解决', '责任心', '抗压能力'];

function ProfessionalSkillsPicker({ value, onChange, role }) {
  const [open, setOpen] = useState(false);
  const [skillTags, setSkillTags] = useState(() => parseTagList(value, '技能/工具'));
  const [advantageTags, setAdvantageTags] = useState(() => parseTagList(value, '优势经验'));
  const [customSkill, setCustomSkill] = useState('');
  const [customAdvantage, setCustomAdvantage] = useState('');

  const preset = Object.keys(ROLE_PRESETS).find((key) => String(role || '').includes(key));
  const techPresets = preset ? ROLE_PRESETS[preset] : ['React', 'Vue', 'TypeScript', 'Node.js', 'Webpack', 'Vite'];

  const toggleSkill = (label) => toggleTag(skillTags, setSkillTags, label);
  const toggleAdvantage = (label) => toggleTag(advantageTags, setAdvantageTags, label);
  const addSkill = () => {
    const next = customSkill.trim();
    if (!next) return;
    setSkillTags((tags) => {
      const withoutNone = tags.filter((t) => t !== '暂无');
      return withoutNone.includes(next) ? withoutNone : [...withoutNone, next];
    });
    setCustomSkill('');
  };
  const addAdvantage = () => {
    const next = customAdvantage.trim();
    if (!next) return;
    setAdvantageTags((tags) => {
      const withoutNone = tags.filter((t) => t !== '暂无');
      return withoutNone.includes(next) ? withoutNone : [...withoutNone, next];
    });
    setCustomAdvantage('');
  };

  // 已添加的自定义标签（不在预设列表里），逐个展示并支持删除
  const customSkills = skillTags.filter((t) => t !== '暂无' && !techPresets.includes(t));
  const customAdvantages = advantageTags.filter((t) => t !== '暂无' && !DEFAULT_PRESETS.includes(t));
  const hasCustomSkill = customSkills.length > 0;
  const hasCustomAdvantage = customAdvantages.length > 0;

  const skillFilled = skillTags.length > 0;
  const advantageFilled = advantageTags.length > 0;
  const filled = [skillFilled, advantageFilled].filter(Boolean).length;

  const handleSave = () => {
    const lines = [];
    if (skillTags.length) lines.push(`技能/工具：${skillTags.join('、')}`);
    if (advantageTags.length) lines.push(`优势经验：${advantageTags.join('、')}`);
    onChange(lines.join('\n'));
    setOpen(false);
  };

  return (
    <>
      <EntryButton
        icon={<Target size={18} />}
        title="职业技能与经验"
        progress={filled ? `已填写 ${filled}/2` : '未填写'}
        onClick={() => setOpen(true)}
      />
      {open && (
        <SkillModal
          title="职业技能与经验"
          description="选择或添加你的专业技能与个人优势，将用于岗位能力匹配分析。"
          onClose={() => setOpen(false)}
          footer={
            <>
              <span>{filled ? `已选择 ${filled} 个模块` : '尚未选择任何模块'}</span>
              <button className="primary-action" type="button" onClick={handleSave}>保存</button>
            </>
          }
        >
          <SectionBlock title="技能/工具">
            <div className="skill-tag-group">
              {techPresets.map((tag) => (
                <SkillTagButton key={tag} label={tag} active={skillTags.includes(tag)} onClick={() => toggleSkill(tag)} />
              ))}
              <SkillTagButton label="暂无" muted active={skillTags.includes('暂无')} onClick={() => toggleSkill('暂无')} />
              {hasCustomSkill && customSkills.map((tag) => (
                <SkillTagButton key={`${tag}-custom`} label={`${tag} ×`} active onClick={() => toggleSkill(tag)} />
              ))}
              <span className="skill-tag skill-tag-custom">
                <input placeholder="自定义" value={customSkill} onChange={(e) => setCustomSkill(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addSkill(); } }} />
                <button type="button" className="skill-tag-add" onClick={addSkill}>＋</button>
              </span>
            </div>
          </SectionBlock>
          <SectionBlock title="优势经验">
            <div className="skill-tag-group">
              {DEFAULT_PRESETS.map((tag) => (
                <SkillTagButton key={tag} label={tag} active={advantageTags.includes(tag)} onClick={() => toggleAdvantage(tag)} />
              ))}
              <SkillTagButton label="暂无" muted active={advantageTags.includes('暂无')} onClick={() => toggleAdvantage('暂无')} />
              {hasCustomAdvantage && customAdvantages.map((tag) => (
                <SkillTagButton key={`${tag}-custom`} label={`${tag} ×`} active onClick={() => toggleAdvantage(tag)} />
              ))}
              <span className="skill-tag skill-tag-custom">
                <input placeholder="自定义" value={customAdvantage} onChange={(e) => setCustomAdvantage(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addAdvantage(); } }} />
                <button type="button" className="skill-tag-add" onClick={addAdvantage}>＋</button>
              </span>
            </div>
          </SectionBlock>
        </SkillModal>
      )}
    </>
  );
}

/* ---------- 2. 我的优势 ---------- */
function AdvantagePicker({ value, onChange }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const count = draft.length;
  return (
    <>
      <EntryButton
        icon={<Award size={18} />}
        title="我的优势"
        progress={filledText(Boolean(value && value.trim()), `${count || value?.trim().length || 0}/2000`)}
        onClick={() => { setDraft(value); setOpen(true); }}
      />
      {open && (
        <SkillModal
          title="我的优势"
          description="简述你相比其他候选人的核心竞争力，例如项目成果、奖项背书、独特经历等。"
          onClose={() => setOpen(false)}
          footer={
            <>
              <span>{count}/2000</span>
              <button className="primary-action" type="button" onClick={() => { onChange(draft); setOpen(false); }}>保存</button>
            </>
          }
        >
          <div className="advantage-editor">
            <textarea rows={6} maxLength={2000} placeholder="描述你的核心竞争力，例如项目成果、奖项背书、独特经历等" value={draft} onChange={(e) => setDraft(e.target.value)} />
          </div>
        </SkillModal>
      )}
    </>
  );
}

/* ---------- 3. 加分项 ---------- */
function BonusPicker({ value, onChange }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const count = draft.length;
  return (
    <>
      <EntryButton
        icon={<Sparkles size={18} />}
        title="加分项"
        progress={value && value.trim() ? '已填写' : '未填写'}
        onClick={() => { setDraft(value); setOpen(true); }}
      />
      {open && (
        <SkillModal
          title="加分项"
          description="其他能体现你优势的经历或特长，例如竞赛获奖、社团领导、公益实践、自媒体影响力等。"
          onClose={() => setOpen(false)}
          footer={
            <>
              <span>{count}/1000</span>
              <button className="primary-action" type="button" onClick={() => { onChange(draft); setOpen(false); }}>保存</button>
            </>
          }
        >
          <div className="advantage-editor">
            <textarea rows={6} maxLength={1000} placeholder="加分项内容" value={draft} onChange={(e) => setDraft(e.target.value)} />
          </div>
        </SkillModal>
      )}
    </>
  );
}

/* ---------- 4. 教育经历 ---------- */
function EducationPicker({ value, onChange }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(() => parseEducation(value));
  const filled = ['school', 'duration', 'major'].filter((k) => draft[k]).length;
  const handleSave = () => {
    const clean = {};
    ['school', 'duration', 'major'].forEach((k) => { if (draft[k] && draft[k].trim()) clean[k] = draft[k].trim(); });
    onChange(Object.entries(clean).map(([k, v]) => `${EDU_LABELS[k]}：${v}`).join(' / '));
    setOpen(false);
  };
  return (
    <>
      <EntryButton
        icon={<GraduationCap size={18} />}
        title="教育经历"
        progress={filled ? `已填写 ${filled}/3` : '未填写'}
        onClick={() => { setDraft(parseEducation(value)); setOpen(true); }}
      />
      {open && (
        <SkillModal
          title="编辑教育经历"
          description="填写学校、在校时间与专业，用于生成专业的岗位匹配。"
          onClose={() => setOpen(false)}
          footer={
            <>
              <span>{filled ? `已填写 ${filled}/3` : '尚未填写'}</span>
              <button className="primary-action" type="button" onClick={handleSave}>保存</button>
            </>
          }
        >
          <div className="education-editor">
            {['school', 'duration', 'major'].map((key) => (
              <label className="education-field" key={key}>
                <span>{EDU_LABELS[key]}</span>
                <input
                  value={draft[key]}
                  placeholder={EDU_PLACEHOLDERS[key]}
                  onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
                />
              </label>
            ))}
          </div>
        </SkillModal>
      )}
    </>
  );
}

/* ---------- 5. 在校荣誉/职务 ---------- */
function HonorsPicker({ value, onChange }) {
  const [open, setOpen] = useState(false);
  const [honor, setHonor] = useState('');
  const [position, setPosition] = useState('');
  const filled = [honor, position].filter(Boolean).length;
  return (
    <>
      <EntryButton
        icon={<Trophy size={18} />}
        title="在校荣誉/职务"
        progress={filled ? `已填写 ${filled}/2` : '未填写'}
        onClick={() => { setHonor(parseHonor(value).honor); setPosition(parseHonor(value).position); setOpen(true); }}
      />
      {open && (
        <SkillModal
          title="在校荣誉/职务"
          description="填写奖学金、荣誉称号，或学生会、社团等担任的职务。"
          onClose={() => setOpen(false)}
          footer={
            <>
              <span>{filled ? `已填写 ${filled}/2` : '尚未填写'}</span>
              <button className="primary-action" type="button" onClick={() => {
                const clean = [];
                if (honor.trim()) clean.push(`校内荣誉：${honor.trim()}`);
                if (position.trim()) clean.push(`校内职务：${position.trim()}`);
                onChange(clean.join(' / '));
                setOpen(false);
              }}>保存</button>
            </>
          }
        >
          <div className="honors-editor">
            <div className="honors-module">
              <h4>校内荣誉</h4>
              <textarea rows={3} placeholder="例如：国家奖学金、校级三好学生" value={honor} onChange={(e) => setHonor(e.target.value)} />
            </div>
            <div className="honors-module">
              <h4>校内职务</h4>
              <textarea rows={3} placeholder="例如：学生会主席、社团负责人" value={position} onChange={(e) => setPosition(e.target.value)} />
            </div>
          </div>
        </SkillModal>
      )}
    </>
  );
}

/* ---------- 通用：多项目列表弹窗 ---------- */
function ProjectsPicker({ value, onChange }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null); // null | {index, item}
  const [items, setItems] = useState(() => parseProjects(value));
  const addNew = () => setEditing({ index: -1, item: { name: '', time: '', belong: '', desc: '' } });
  const handleSaveEntry = (item) => {
    setItems((list) => {
      if (editing.index >= 0) {
        return list.map((it, i) => (i === editing.index ? item : it));
      }
      return [...list, item];
    });
    setEditing(null);
  };
  const handleSave = () => {
    onChange(items.map(serializeProject).join('\n---\n'));
    setOpen(false);
  };
  return (
    <>
      <EntryButton
        icon={<Wrench size={18} />}
        title="项目经历"
        progress={`${items.length} 个项目`}
        onClick={() => setOpen(true)}
      />
      {open && (
        <SkillModal
          title="项目经历"
          description="添加参与过的项目，包括职责、技术方案与成果数据。"
          wide
          onClose={() => setOpen(false)}
          footer={
            <>
              <span>已添加 {items.length} 个项目经历</span>
              <button className="primary-action" type="button" onClick={handleSave}>保存</button>
            </>
          }
        >
          {items.length ? (
            <div className="project-list">
              {items.map((item, index) => (
                <div className="project-item" key={index} onClick={() => setEditing({ index, item: { ...item } })} style={{ cursor: 'pointer' }}>
                  <div className="project-item-head">
                    <strong>{item.name || `项目 ${index + 1}`}</strong>
                    <span className="project-item-head-right">
                      <span>{item.time}</span>
                      <button
                        className="project-item-delete"
                        type="button"
                        onClick={(e) => { e.stopPropagation(); setItems((list) => list.filter((_, i) => i !== index)); }}
                      >删除</button>
                    </span>
                  </div>
                  {item.belong && <span className="project-item-time">{item.belong}</span>}
                  <p>{item.desc}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="project-empty">还没有项目经历，点击下方按钮添加。</p>
          )}
          <button className="secondary-action project-add" type="button" onClick={addNew}>
            <Plus size={16} /> 添加项目
          </button>
        </SkillModal>
      )}
      {editing && (
        <ProjectEditor
          initial={editing.item}
          editing={editing.index >= 0}
          onCancel={() => setEditing(null)}
          onSave={handleSaveEntry}
        />
      )}
    </>
  );
}

function ProjectEditor({ initial, editing, onCancel, onSave }) {
  const [item, setItem] = useState({ ...initial });
  const fields = [
    { key: 'name', label: '项目名称' },
    { key: 'time', label: '项目时间' },
    { key: 'belong', label: '所属' },
    { key: 'desc', label: '项目描述', textarea: true },
  ];
  return (
    <SkillModal
      title={editing ? '编辑项目' : '添加项目'}
      wide
      onClose={onCancel}
      footer={
        <>
          <button className="secondary-action" type="button" onClick={onCancel}>取消</button>
          <button className="primary-action" type="button" onClick={() => onSave(item)}>保存</button>
        </>
      }
    >
      <div className="project-editor">
        {fields.map((f) => (
          <label className="education-field" key={f.key}>
            <span>{f.label}</span>
            {f.textarea ? (
              <textarea rows={4} value={item[f.key] || ''} placeholder={`${f.label}示例`} onChange={(e) => setItem((it) => ({ ...it, [f.key]: e.target.value }))} />
            ) : (
              <input value={item[f.key] || ''} placeholder={`${f.label}示例`} onChange={(e) => setItem((it) => ({ ...it, [f.key]: e.target.value }))} />
            )}
          </label>
        ))}
      </div>
    </SkillModal>
  );
}

/* ---------- 7. 语言 ---------- */
const LANGUAGE_OPTIONS = ['英语', '日语', '韩语', '德语', '法语', '西班牙语', '俄语', '意大利语'];
const PROFICIENCY_OPTIONS = ['简单沟通读写', '读写熟练', '听说读写流利'];
const CERT_MAP = {
  英语: ['大学英语四级（CET-4）', '大学英语六级（CET-6）', '雅思（IELTS）', '托福（TOEFL）', 'BEC'],
  日语: ['日语N1', '日语N2', '日语N3'],
  韩语: ['TOPIK高级', 'TOPIK中级'],
  德语: ['德语欧标B2', '德语欧标C1'],
  法语: ['法语欧标B1', '法语欧标B2'],
  西班牙语: ['西语欧标B1', '西语欧标B2'],
  俄语: ['俄语欧标B1', '俄语欧标B2'],
  意大利语: ['意语欧标B1', '意语欧标B2'],
};

function LanguagePicker({ value, onChange }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(() => parseLanguage(value));
  const [showOptions, setShowOptions] = useState(false);
  const filled = [draft.language, draft.proficiency, draft.cert].filter(Boolean).length;

  const handleSave = () => {
    const parts = [];
    if (draft.language) parts.push(`语种：${draft.language}`);
    if (draft.proficiency) parts.push(`熟练程度：${draft.proficiency}`);
    if (draft.cert) parts.push(`证书：${draft.cert}`);
    onChange(parts.join(' / '));
    setOpen(false);
  };

  return (
    <>
      <EntryButton
        icon={<Languages size={18} />}
        title="语言"
        progress={filled ? `已填写 ${filled}/3` : '未填写'}
        onClick={() => { setDraft(parseLanguage(value)); setShowOptions(false); setOpen(true); }}
      />
      {open && (
        <SkillModal
          title="语言能力"
          description="选择掌握的语言并填写熟练程度与相关证书。"
          onClose={() => setOpen(false)}
          footer={
            <>
              {filled < 3 && <span>可补充熟练程度与证书</span>}
              <button className="primary-action" type="button" onClick={handleSave}>保存</button>
            </>
          }
        >
          <div className="education-editor">
            <div className="skill-question">
              <h4>掌握的语言</h4>
              {!draft.language && (
                <div className="skill-tag-group">
                  {LANGUAGE_OPTIONS.map((lang) => (
                    <SkillTagButton key={lang} label={lang} onClick={() => { setDraft((d) => ({ ...d, language: lang, proficiency: '', cert: '' })); setShowOptions(true); }} />
                  ))}
                </div>
              )}
              {draft.language && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <SkillTagButton label={draft.language} active />
                  <button className="secondary-action" type="button" style={{ minWidth: 0 }} onClick={() => { setDraft((d) => ({ language: '', proficiency: '', cert: '' })); setShowOptions(false); }}>点击更换</button>
                </div>
              )}
            </div>
            {draft.language && (
              <div className="skill-question">
                <h4>熟练程度</h4>
                <div className="skill-tag-group">
                  {PROFICIENCY_OPTIONS.map((p) => (
                    <SkillTagButton key={p} label={p} active={draft.proficiency === p} onClick={() => setDraft((d) => ({ ...d, proficiency: p }))} />
                  ))}
                </div>
              </div>
            )}
            {draft.proficiency && (
              <div className="skill-question">
                <h4>证书</h4>
                <div className="skill-tag-group">
                  {(CERT_MAP[draft.language] || []).map((c) => (
                    <SkillTagButton key={c} label={c} active={draft.cert === c} onClick={() => setDraft((d) => ({ ...d, cert: d.cert === c ? '' : c }))} />
                  ))}
                </div>
              </div>
            )}
          </div>
        </SkillModal>
      )}
    </>
  );
}

/* ---------- 8. 技能 ---------- */
function GenericListPicker({ icon, title, fieldKey, itemFields, value, onChange }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [items, setItems] = useState(() => parseKeyValueList(value, itemFields));
  const addNew = () => setEditing({ index: -1, item: Object.fromEntries(itemFields.map((f) => [f.key, ''])) });
  const handleSaveEntry = (item) => {
    setItems((list) => {
      if (editing.index >= 0) return list.map((it, i) => (i === editing.index ? item : it));
      return [...list, item];
    });
    setEditing(null);
  };
  const handleSave = () => {
    onChange(items.map((it) => itemFields.map((f) => (it[f.key] ? `${f.label}：${it[f.key]}` : '')).filter(Boolean).join(' / ')).join('\n---\n'));
    setOpen(false);
  };
  return (
    <>
      <EntryButton
        icon={icon}
        title={title}
        progress={`${items.length} 项`}
        onClick={() => setOpen(true)}
      />
      {open && (
        <SkillModal
          title={title}
          wide
          onClose={() => setOpen(false)}
          footer={
            <>
              <span>已添加 {items.length} 项</span>
              <button className="primary-action" type="button" onClick={handleSave}>保存</button>
            </>
          }
        >
          {items.length ? (
            <div className="project-list">
              {items.map((item, index) => (
                <div className="project-item" key={index} onClick={() => setEditing({ index, item: { ...item } })} style={{ cursor: 'pointer' }}>
                  <div className="project-item-head">
                    <strong>{item[itemFields[0].key] || `${title} ${index + 1}`}</strong>
                    <span className="project-item-head-right">
                      <button className="project-item-delete" type="button" onClick={(e) => { e.stopPropagation(); setItems((list) => list.filter((_, i) => i !== index)); }}>删除</button>
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="project-empty">尚未添加，点击下方按钮添加。</p>
          )}
          <button className="secondary-action project-add" type="button" onClick={addNew}>
            <Plus size={16} /> 添加
          </button>
        </SkillModal>
      )}
      {editing && (
        <SkillModal
          title={editing.index >= 0 ? `编辑${title}` : `添加${title}`}
          wide
          onClose={() => setEditing(null)}
          footer={
            <>
              <button className="secondary-action" type="button" onClick={() => setEditing(null)}>取消</button>
              <button className="primary-action" type="button" onClick={() => handleSaveEntry(editing.item)}>保存</button>
            </>
          }
        >
          <div className="project-editor">
            {itemFields.map((f) => (
              <label className="education-field" key={f.key}>
                <span>{f.label}</span>
                <input
                  value={editing.item[f.key]}
                  placeholder={`${f.label}示例`}
                  onChange={(e) => setEditing((ed) => ({ ...ed, item: { ...ed.item, [f.key]: e.target.value } }))}
                />
              </label>
            ))}
          </div>
        </SkillModal>
      )}
    </>
  );
}

/* 简历表单 Picker 序列化工具 */
const EDU_LABELS = { school: '学校', duration: '在校时间', major: '专业' };
const EDU_PLACEHOLDERS = { school: '例如：上海交通大学', duration: '例如：2022.09 - 2026.06', major: '例如：软件工程' };

function parseTagLine(text, key) {
  const block = (text || '').split('\n').map((l) => l.trim()).find((l) => l.startsWith(`${key}：`));
  if (!block) return [];
  return block.slice(key.length + 1).split(/、|，/).map((s) => s.trim()).filter(Boolean);
}

function parseTagList(text, key) {
  const value = parseTagLine(text, key);
  if (!value.length) return [];
  if (value.includes('暂无')) return ['暂无'];
  return value;
}

function toggleTag(tags, setTags, label) {
  setTags((current) => {
    if (label === '暂无') return current.includes('暂无') ? [] : ['暂无'];
    const withoutNone = current.filter((t) => t !== '暂无');
    return withoutNone.includes(label) ? withoutNone : [...withoutNone, label];
  });
}

function parseEducation(text) {
  const out = { school: '', duration: '', major: '' };
  (text || '').split(' / ').forEach((part) => {
    const [key, value] = splitKV(part);
    if (key) {
      const field = Object.keys(EDU_LABELS).find((k) => EDU_LABELS[k] === key);
      if (field) out[field] = (value || '').trim();
    }
  });
  return out;
}

function splitKV(part) {
  const idx = part.indexOf('：');
  if (idx < 0) return ['', part];
  return [part.slice(0, idx), part.slice(idx + 1)];
}

function parseHonor(text) {
  let honor = '';
  let position = '';
  (text || '').split(' / ').forEach((part) => {
    const [key, value] = splitKV(part);
    if (key === '校内荣誉') honor = (value || '').trim();
    if (key === '校内职务') position = (value || '').trim();
  });
  return { honor, position };
}

function parseProjects(text) {
  return (text || '').split('\n---\n').map(parseProject).filter((p) => p.name || p.time || p.belong || p.desc);
}

function parseProject(block) {
  const item = { name: '', time: '', belong: '', desc: '' };
  const clean = (block || '').split('\n').map((l) => l.trim()).filter(Boolean);
  const descLines = [];
  clean.forEach((line) => {
    const [key, value] = splitKV(line);
    if (key === '项目名称') item.name = (value || '').trim();
    else if (key === '项目时间') item.time = (value || '').trim();
    else if (key === '所属') item.belong = (value || '').trim();
    else if (key === '项目描述') item.desc = (value || '').trim();
    else if (!key) descLines.push(line);
  });
  if (descLines.length && !item.desc) item.desc = descLines.join('\n');
  return item;
}

function serializeProject(item) {
  const lines = [];
  if (item.name) lines.push(`项目名称：${item.name}`);
  if (item.time) lines.push(`项目时间：${item.time}`);
  if (item.belong) lines.push(`所属：${item.belong}`);
  if (item.desc) lines.push(`项目描述：${item.desc}`);
  return lines.join('\n');
}

function parseLanguage(text) {
  const out = { language: '', proficiency: '', cert: '' };
  (text || '').split(' / ').forEach((part) => {
    const [key, value] = splitKV(part);
    if (key === '语种') out.language = (value || '').trim();
    if (key === '熟练程度') out.proficiency = (value || '').trim();
    if (key === '证书') out.cert = (value || '').trim();
  });
  return out;
}

function parseKeyValueList(text, fields) {
  return (text || '').split('\n---\n').map((block) => {
    const item = Object.fromEntries(fields.map((f) => [f.key, '']));
    (block || '').split('\n').forEach((line) => {
      const [key, value] = splitKV(line.trim());
      const field = fields.find((f) => f.label === key);
      if (field) item[field.key] = (value || '').trim();
    });
    return item;
  }).filter((it) => Object.values(it).some(Boolean));
}

function ResumeDownloader({ text, name }) {
  const [ready, setReady] = useState(true);
  const handleDownload = () => {
    try {
      const blob = new Blob([text || ''], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${name || '简历'}-简历.md`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } finally {
      // noop
    }
  };
  return (
    <button className="primary-action" type="button" onClick={handleDownload} disabled={!ready || !text}>
      <Download size={16} />
      {ready ? '下载文本' : '准备中...'}
    </button>
  );
}

const JOB_MATCH_STATUS_LABELS = { satisfied: '已满足', partial: '部分满足', missing: '未体现' };

function JobMatchResult({ result }) {
  const detail = result?.result || {};
  return (
    <>
      <div className="jcmp-result">
        <div className={`jcmp-score ${detail.matchScore >= 75 ? 'high' : detail.matchScore >= 55 ? 'mid' : 'low'}`}>
          <span>{detail.scoreLabel || '岗位匹配度'}</span>
          <strong>{detail.matchScore ?? result.match_score}</strong>
          <small>/100</small>
        </div>
        <div className="jcmp-result-copy">
          <div className="jcmp-result-tags">
            <StatusTag tone={result.source === 'library' ? 'blue' : 'amber'}>{result.source === 'library' ? '招聘信息库岗位' : '粘贴 JD'}</StatusTag>
            <StatusTag tone={result.provider && result.provider !== 'local' ? 'green' : 'blue'}>
              {result.provider && result.provider !== 'local' ? `AI 建议 · ${result.provider}` : '规则引擎打分'}
            </StatusTag>
          </div>
          <h3>{result.job_title || '岗位'}{result.company ? ` · ${result.company}` : ''}</h3>
          <p>{detail.summary || '已完成对比，请在下方查看分维度结果。'}</p>
        </div>
      </div>

      {(detail.dimensions || []).length > 0 && (
        <div className="jcmp-dimensions">
          {detail.dimensions.map((dimension) => (
            <div className="jcmp-dimension" key={dimension.label}>
              <div className="jcmp-dimension-top">
                <strong>{dimension.label}</strong>
                <span>{dimension.score} 分 · 权重 {dimension.weight}</span>
              </div>
              <div className="jcmp-bar"><i style={{ width: `${Math.max(0, Math.min(100, dimension.score))}%` }} /></div>
            </div>
          ))}
        </div>
      )}

      <div className="jcmp-columns">
        <div className="jcmp-column">
          <h4>已具备技能（{detail.matchedSkills?.length || 0}）</h4>
          <div className="jcmp-chips">
            {(detail.matchedSkills || []).map((skill) => <b className="hit" key={skill}>{skill}</b>)}
            {!detail.matchedSkills?.length && <span className="jcmp-hint">暂未匹配到明确技能，建议补充技术关键词。</span>}
          </div>
        </div>
        <div className="jcmp-column">
          <h4>待补充技能（{detail.missingSkills?.length || 0}）</h4>
          <div className="jcmp-chips">
            {(detail.missingSkills || []).map((skill) => <b className="miss" key={skill}>{skill}</b>)}
            {!detail.missingSkills?.length && <span className="jcmp-hint">岗位要求的技能已全部覆盖。</span>}
          </div>
        </div>
      </div>

      {(detail.matrices || []).length > 0 && (
        <div className="jcmp-block">
          <h4>任职要求逐条比对</h4>
          <div className="jcmp-matrix">
            {detail.matrices.map((item, index) => (
              <article key={`${item.requirement}-${index}`}>
                <StatusTag tone={item.status === 'satisfied' ? 'green' : item.status === 'partial' ? 'amber' : 'blue'}>
                  {JOB_MATCH_STATUS_LABELS[item.status] || item.status}
                </StatusTag>
                <div>
                  <strong>{item.requirement}</strong>
                  {item.matched?.length > 0 && <small>命中关键词：{item.matched.join('、')}</small>}
                  {item.evidence && <small>简历依据：{item.evidence}</small>}
                </div>
              </article>
            ))}
          </div>
        </div>
      )}

      <div className="jcmp-columns">
        <div className="jcmp-column">
          <h4><CheckCircle2 size={15} />优势</h4>
          <ul className="jcmp-points">{(detail.strengths || []).map((item, index) => <li key={`s-${index}`}>{item}</li>)}</ul>
        </div>
        <div className="jcmp-column">
          <h4><AlertTriangle size={15} />差距</h4>
          <ul className="jcmp-points">{(detail.gaps || []).map((item, index) => <li key={`g-${index}`}>{item}</li>)}</ul>
        </div>
        <div className="jcmp-column">
          <h4><TrendingUp size={15} />改进建议</h4>
          <ul className="jcmp-points">{(detail.suggestions || []).map((item, index) => <li key={`t-${index}`}>{item}</li>)}</ul>
        </div>
        <div className="jcmp-column">
          <h4><MessageSquareText size={15} />面试关注点</h4>
          <ul className="jcmp-points">{(detail.interviewFocus || []).map((item, index) => <li key={`f-${index}`}>{item}</li>)}</ul>
        </div>
      </div>
    </>
  );
}

function ResumeJobCompare() {
  const [mode, setMode] = useState('library');
  const [postings, setPostings] = useState([]);
  const [loadingPostings, setLoadingPostings] = useState(true);
  const [postingKeyword, setPostingKeyword] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [jdForm, setJdForm] = useState({ job_title: '', company: '', jd_text: '' });
  const [matching, setMatching] = useState(false);
  const [result, setResult] = useState(null);
  const [compareError, setCompareError] = useState('');
  const [compareMessage, setCompareMessage] = useState('');

  useEffect(() => {
    let mounted = true;
    apiRequest('/api/job-postings')
      .then((data) => { if (mounted) setPostings(data.postings || []); })
      .catch(() => { if (mounted) setPostings([]); })
      .finally(() => { if (mounted) setLoadingPostings(false); });
    return () => { mounted = false; };
  }, []);

  const visiblePostings = postings.filter((posting) => {
    const needle = postingKeyword.trim().toLowerCase();
    if (!needle) return true;
    return [posting.title, posting.company, posting.job_category, posting.city]
      .filter(Boolean).join(' ').toLowerCase().includes(needle);
  });

  const selectedPosting = postings.find((posting) => posting.id === selectedId) || null;

  const startCompare = async () => {
    setCompareError('');
    setCompareMessage('');
    if (mode === 'library' && !selectedId) {
      setCompareError('请先选择一个招聘岗位。');
      return;
    }
    if (mode === 'pasted' && jdForm.jd_text.trim().length < 20) {
      setCompareError('请粘贴岗位描述（JD），内容不少于 20 字。');
      return;
    }
    setMatching(true);
    try {
      const payload = mode === 'library'
        ? { job_posting_id: selectedId }
        : { job_title: jdForm.job_title.trim() || '自定义岗位', company: jdForm.company.trim(), jd_text: jdForm.jd_text.trim() };
      const data = await apiRequest('/api/job-matches', { method: 'POST', body: JSON.stringify(payload) });
      setResult(data.job_match || null);
      setCompareMessage('已完成对比，结果已保存，可在“复盘报告 → 岗位对比”中再次查看。');
    } catch (requestError) {
      setCompareError(requestError.message);
    } finally {
      setMatching(false);
    }
  };

  return (
    <section className="job-compare-section">
      <Card title="简历与招聘岗位对比" icon={<BriefcaseBusiness size={18} />}>
        <div className="jcmp-body">
          <div className="jcmp-mode">
            <button type="button" className={mode === 'library' ? 'active' : ''} onClick={() => setMode('library')}>从招聘信息库选择</button>
            <button type="button" className={mode === 'pasted' ? 'active' : ''} onClick={() => setMode('pasted')}>粘贴岗位描述（JD）</button>
          </div>

          {mode === 'library' ? (
            <div className="jcmp-library">
              <label className="jcmp-search">
                <Search size={15} />
                <input value={postingKeyword} onChange={(event) => setPostingKeyword(event.target.value)} placeholder="搜索岗位名称、公司、类别或城市" />
              </label>
              {loadingPostings ? (
                <p className="jcmp-hint">正在读取招聘信息库…</p>
              ) : visiblePostings.length === 0 ? (
                <p className="jcmp-hint">当前没有可对比的招聘岗位，可切换到“粘贴岗位描述”方式，或联系就业指导老师录入岗位。</p>
              ) : (
                <div className="jcmp-posting-list">
                  {visiblePostings.map((posting) => (
                    <button
                      type="button"
                      key={posting.id}
                      className={`jcmp-posting ${selectedId === posting.id ? 'selected' : ''}`}
                      onClick={() => setSelectedId(posting.id)}
                    >
                      <div className="jcmp-posting-head">
                        <strong>{posting.title}</strong>
                        {posting.city && <span>{posting.city}</span>}
                      </div>
                      <small>{[posting.company, posting.job_category, posting.graduation_year, posting.salary].filter(Boolean).join(' · ') || '未填写更多信息'}</small>
                      {posting.skillList?.length > 0 && (
                        <div className="jcmp-posting-skills">
                          {posting.skillList.slice(0, 6).map((skill) => <em key={skill}>{skill}</em>)}
                        </div>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="jcmp-paste">
              <div className="jcmp-paste-row">
                <label className="brief-field">
                  <span>岗位名称</span>
                  <input value={jdForm.job_title} onChange={(event) => setJdForm((current) => ({ ...current, job_title: event.target.value }))} placeholder="例如：前端开发工程师" />
                </label>
                <label className="brief-field">
                  <span>公司（可选）</span>
                  <input value={jdForm.company} onChange={(event) => setJdForm((current) => ({ ...current, company: event.target.value }))} placeholder="例如：某某科技有限公司" />
                </label>
              </div>
              <label className="brief-field">
                <span>岗位描述 / 任职要求</span>
                <textarea
                  rows={8}
                  value={jdForm.jd_text}
                  onChange={(event) => setJdForm((current) => ({ ...current, jd_text: event.target.value }))}
                  placeholder="把招聘网站上的岗位职责与任职要求粘贴到这里，建议保留原文分行，便于逐条比对。"
                />
              </label>
            </div>
          )}

          {selectedPosting && mode === 'library' && (
            <div className="jcmp-selected-note">
              <strong>已选择：{selectedPosting.title}</strong>
              <span>{[selectedPosting.company, selectedPosting.employment_type, selectedPosting.education_requirement].filter(Boolean).join(' · ') || '暂无更多岗位信息'}</span>
            </div>
          )}

          <div className="jcmp-actions">
            <button className="primary-action" type="button" onClick={startCompare} disabled={matching}>
              <Sparkles size={16} />
              {matching ? '对比中…' : '开始对比'}
            </button>
            <span className="jcmp-actions-note">对比使用“简历分析”中已保存的简历内容，结果会同步到管理端。</span>
          </div>

          {compareError && <div className="profile-message error">{compareError}</div>}
          {compareMessage && <div className="profile-message success">{compareMessage}</div>}
        </div>
      </Card>

      {result && (
        <Card title="对比结果" icon={<Target size={18} />}>
          <JobMatchResult result={result} />
        </Card>
      )}
    </section>
  );
}

function JobComparePage() {
  return (
    <section className="job-compare-page">
      <ResumeJobCompare />
    </section>
  );
}

function JobMatchHistoryPage() {
  const [matches, setMatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [activeMatch, setActiveMatch] = useState(null);
  const [error, setError] = useState('');

  const loadMatches = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await apiRequest('/api/job-matches');
      setMatches(data.matches || []);
    } catch (requestError) {
      setError(requestError.message);
      setMatches([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMatches();
  }, []);

  const openMatch = async (match) => {
    setError('');
    setLoadingDetail(true);
    try {
      const data = await apiRequest(`/api/job-matches/${encodeURIComponent(match.id)}`);
      setActiveMatch(data.job_match || null);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoadingDetail(false);
    }
  };

  if (activeMatch) {
    return (
      <section className="job-match-history-page">
        <button type="button" className="secondary-action report-back-action" onClick={() => setActiveMatch(null)}>
          ← 返回岗位对比记录
        </button>
        <Card title="对比结果" icon={<Target size={18} />}>
          <JobMatchResult result={activeMatch} />
        </Card>
      </section>
    );
  }

  return (
    <section className="job-match-history-page">
      <div className="resume-hero">
        <div>
          <p className="eyebrow">Job Match History</p>
          <h1>简历与招聘岗位对比记录</h1>
          <span>这里读取 `GET /api/job-matches`，展示你在“简历分析”中发起过的岗位对比，点击即可回看完整结论。</span>
        </div>
      </div>

      {error && <div className="profile-message error">{error}</div>}

      {loading ? (
        <div className="profile-loading">正在读取岗位对比记录</div>
      ) : matches.length === 0 ? (
        <div className="empty-state">
          <strong>暂无岗位对比记录</strong>
          <span>在“简历分析 → 简历与招聘岗位对比”中选择岗位或粘贴 JD，即可生成第一条对比记录。</span>
        </div>
      ) : (
        <div className="history-list">
          {matches.map((match) => (
            <article className="history-item" key={match.id}>
              <div>
                <strong>{match.job_title || '岗位'}</strong>
                <span>{[match.company, formatDateTime(match.created_at)].filter(Boolean).join(' · ')}</span>
                <span>
                  {match.source === 'library' ? '招聘信息库岗位' : '粘贴 JD'} · {match.provider && match.provider !== 'local' ? `AI 建议 · ${match.provider}` : '规则引擎打分'}
                </span>
              </div>
              <div className="history-score">
                <strong>{match.match_score}</strong>
                <span>岗位匹配度</span>
                <button className="secondary-action" type="button" onClick={() => openMatch(match)} disabled={loadingDetail}>
                  {loadingDetail ? '读取中…' : '查看对比'}
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function ResumeAnalysisPage() {
  const [resumeText, setResumeText] = useState('');
  const [fileName, setFileName] = useState('');
  const [analysis, setAnalysis] = useState(() => buildResumeAnalysis(resumeText));
  const [analyzed, setAnalyzed] = useState(false);
  const [profile, setProfile] = useState(null);
  const [structuredAnalysis, setStructuredAnalysis] = useState(null);
  const [analysisMeta, setAnalysisMeta] = useState(null);
  const [customRole, setCustomRole] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [form, setForm] = useState(EMPTY_RESUME_FORM);
  const [collegeOptions, setCollegeOptions] = useState([]);
  const [studentInfo, setStudentInfo] = useState({ name: '', studentNo: '', college: '' });
  const [savingForm, setSavingForm] = useState(false);
  const [editorMode, setEditorMode] = useState('document');
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [savingText, setSavingText] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const fileInput = useRef(null);
  const busy = loading || uploading || analyzing || savingForm || savingText || confirming;
  const hasResult = analyzed && !!structuredAnalysis;
  const invalidateAnalysis = () => {
    setAnalyzed(false);
    setMessage('');
    setError('');
  };


  useEffect(() => {
    let mounted = true;

    apiRequest('/api/profile')
      .then(async (data) => {
        if (!mounted) return;
        const currentProfile = { ...defaultProfile, ...(data.profile || {}) };
        const savedResume = currentProfile.resume_text || currentProfile.project_experience;
        setProfile(currentProfile);
        setCustomRole(currentProfile.target_role || '');
        setFileName(currentProfile.resume_filename || '');

        if (savedResume) {
          setResumeText(savedResume);
          setAnalysis(buildResumeAnalysis(savedResume, currentProfile.resume_filename));

          let analysisData = await apiRequest('/api/profile/resume-analysis');

          if (!mounted) return;
          const savedRecord = analysisData.resume_analysis;
          const savedAnalysis = savedRecord?.analysis;
          if (savedAnalysis && !analysisData.stale) {
            setAnalyzed(true);
            setAnalysisMeta(normalizeResumeAnalysisMeta(savedRecord));
            setStructuredAnalysis(savedAnalysis);
            setAnalysis(buildResumeAnalysisFromStructured(savedResume, currentProfile.resume_filename, savedAnalysis, currentProfile.target_role));
          }
        }
      })
      .catch(() => {
        if (mounted) {
          setError('简历资料读取失败，请刷新页面重试。');
        }
      }).finally(() => { if (mounted) setLoading(false); });

    apiRequest('/api/resume-form/settings')
      .then((data) => {
        if (mounted) setCollegeOptions(data.colleges || []);
      })
      .catch(() => {});

    apiRequest('/api/resume-form')
      .then((data) => {
        if (!mounted) return;
        if (data.form && Object.keys(data.form).length) {
          setForm({ ...EMPTY_RESUME_FORM, college: data.college || '', ...data.form });
        } else {
          setForm((current) => ({ ...current, college: data.college || current.college }));
        }
        setStudentInfo({ name: data.name || '', studentNo: data.student_no || '', college: data.college || '' });
      })
      .catch(() => {});

    return () => {
      mounted = false;
    };
  }, []);

  const handleFormChange = (field, value) => {
    invalidateAnalysis();
    setForm((current) => {
      if (field === 'college') {
        const next = { ...current, college: value, major: '' };
        const college = collegeOptions.find((item) => item.name === value);
        if (college?.majors?.length === 1) next.major = college.majors[0].name;
        return next;
      }
      return { ...current, [field]: value };
    });
    setMessage('');
    setError('');
  };

  const handleSaveForm = async () => {
    setSavingForm(true);
    setMessage('');
    setError('');
    try {
      const data = await apiRequest('/api/resume-form', {
        method: 'PUT',
        body: JSON.stringify(form),
      });
      const savedForm = data.form || form;
      setForm(savedForm);
      const nextText = data.resume_text || resumeText;
      setResumeText(nextText);
      setFileName('');
      setAnalysis(buildResumeAnalysis(nextText));
      setStructuredAnalysis(null);
      setAnalysisMeta(null);
      setAnalyzed(false);
      setProfile((current) => ({ ...current, resume_text: nextText, resume_filename: '' }));
      setMessage('填写内容已保存为当前简历，可以开始分析了。');
      return nextText;
    } catch (requestError) {
      setError(requestError.message);
      return null;
    } finally {
      setSavingForm(false);
    }
  };

  const handleUpload = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || busy) return;
    setError('');
    setMessage('');
    setUploading(true);
    try {
      const data = await uploadResume(apiUrl('/api/profile/resume-upload'), file);
      setProfile({ ...defaultProfile, ...data.profile });
      setResumeText(data.text);
      setFileName(data.filename);
      setEditorMode('document');
      setStructuredAnalysis(null);
      setAnalysisMeta(null);
      setAnalyzed(false);
      setMessage(data.truncated ? '已提取并保存前 12,000 字，请检查内容后开始分析。' : '简历已提取并保存，请检查内容后开始分析。');
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setUploading(false);
    }
  };

  const handleSaveText = async () => {
    setSavingText(true);
    setError('');
    setMessage('');
    try {
      const data = await apiRequest('/api/profile', {
        method: 'PUT',
        body: JSON.stringify({ ...(profile || defaultProfile), resume_text: resumeText, resume_filename: fileName }),
      });
      setProfile({ ...defaultProfile, ...data.profile });
      setMessage('简历内容已保存。');
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSavingText(false);
    }
  };

  const selectedCollege = collegeOptions.find((item) => item.name === form.college);
  const majorOptions = selectedCollege?.majors || [];

  const handleAnalyze = async () => {
    setAnalyzing(true);
    setMessage('');
    setError('');

    try {
      const textToAnalyze = editorMode === 'form' ? await handleSaveForm() : resumeText;
      if (!textToAnalyze?.trim()) {
        if (textToAnalyze !== null) setError('请先上传或填写简历内容。');
        return;
      }
      const nextFileName = editorMode === 'form' ? '' : fileName;
      const nextAnalysis = buildResumeAnalysis(textToAnalyze, nextFileName);
      const currentProfile = profile || defaultProfile;
      const data = await apiRequest('/api/profile', {
        method: 'PUT',
        body: JSON.stringify({
          ...currentProfile,
          resume_text: textToAnalyze,
          resume_filename: nextFileName,
          project_experience: currentProfile.project_experience || textToAnalyze,
          target_role: currentProfile.target_role || '',
          preferred_interview_type: currentProfile.preferred_interview_type || nextAnalysis.recommendedSetup[0].value,
          preferred_difficulty: currentProfile.preferred_difficulty || nextAnalysis.recommendedSetup[1].value,
          preferred_interviewer_style: currentProfile.preferred_interviewer_style || nextAnalysis.recommendedSetup[3].value,
        }),
      });
      const savedProfile = { ...defaultProfile, ...(data.profile || {}) };
      setProfile(savedProfile);

      const analysisData = await apiRequest('/api/profile/resume-analysis', {
        method: 'POST',
        body: JSON.stringify({ force: true }),
      });
      const nextStructuredAnalysis = analysisData.resume_analysis?.analysis;
      setAnalysisMeta(normalizeResumeAnalysisMeta(analysisData.resume_analysis));
      setStructuredAnalysis(nextStructuredAnalysis || null);
      setAnalysis(buildResumeAnalysisFromStructured(textToAnalyze, nextFileName, nextStructuredAnalysis, savedProfile.target_role));
      setAnalyzed(true);
      setMessage('已生成多个就业方向及依据。系统不会自动替你定岗，请确认一个方向或输入自己的目标岗位。');
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleConfirmDirection = async (role) => {
    const nextRole = String(role || '').trim();
    if (!nextRole) {
      setError('请选择推荐方向或输入目标岗位。');
      return;
    }

    setConfirming(true);
    setMessage('');
    setError('');
    try {
      const currentProfile = profile || defaultProfile;
      const data = await apiRequest('/api/profile', {
        method: 'PUT',
        body: JSON.stringify({
          ...currentProfile,
          target_role: nextRole,
        }),
      });
      const savedProfile = { ...defaultProfile, ...(data.profile || {}) };
      setProfile(savedProfile);
      setCustomRole(nextRole);
      setAnalysis(buildResumeAnalysisFromStructured(resumeText, fileName, structuredAnalysis, nextRole));
      setMessage(`已确认“${nextRole}”为本阶段训练目标，面试配置会优先使用该方向。`);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setConfirming(false);
    }
  };

  return (
    <section className="resume-page v4-resume-page resume-studio">
      <V4PageHeading eyebrow="YOUR STORY, WELL PRESENTED" title="我的简历" description="整理经历，让每一份潜力被看见。" />

      {(message || error) && (
        <div className={`profile-message ${error ? 'error' : 'success'}`}>{error || message}</div>
      )}

      <section className="resume-import" aria-label="上传简历">
        <div className="resume-import-icon"><FileText size={30} strokeWidth={1.4} /></div>
        <div className="resume-import-copy">
          <span className="resume-kicker">从一份简历开始</span>
          <h2>{uploading ? '正在提取简历内容…' : '上传简历，发现适合你的方向'}</h2>
          <p>支持 PDF、DOCX、TXT、MD · 最大 10 MB · 上传后提取并保存文字</p>
          <span className="resume-file-status"><CheckCircle2 size={14} />{loading ? '正在读取简历…' : fileName || (resumeText ? '已有简历内容，可继续编辑' : '也可以在下方粘贴内容或手动填写')}</span>
        </div>
        <button className="primary-action" type="button" onClick={() => fileInput.current?.click()} disabled={busy}><Upload size={16} />{resumeText ? '上传新简历' : '选择简历文件'}</button>
        <input ref={fileInput} type="file" hidden accept=".pdf,.docx,.txt,.md" aria-label="选择简历文件" onChange={handleUpload} disabled={busy} />
      </section>

      <section className="resume-grid">
        <section className="resume-editor">
          <div className="resume-editor-head">
            <div className="resume-editor-tabs" aria-label="简历编辑方式">
              <button type="button" aria-pressed={editorMode === 'document'} disabled={busy} onClick={() => setEditorMode('document')}>简历内容</button>
              <button type="button" aria-pressed={editorMode === 'form'} disabled={busy} onClick={() => setEditorMode('form')}>手动填写</button>
            </div>
            <span>{hasResult ? '分析已完成' : '待分析'}</span>
          </div>
          {editorMode === 'document' ? (
            <div className="resume-document">
              <div className="resume-document-heading"><h2>{fileName || '我的简历内容'}</h2><span>{resumeText.length.toLocaleString()} / 12,000 字</span></div>
              <p>检查提取的内容，也可以直接粘贴或补充你的经历。</p>
              <textarea aria-label="简历内容" value={resumeText} maxLength={12000} disabled={busy} placeholder="在这里粘贴简历，描述你的教育背景、专业技能、项目经历和成果…" onChange={(event) => { setResumeText(event.target.value); invalidateAnalysis(); }} />
            </div>
          ) : (
          <fieldset className="resume-form-panel" disabled={busy}>
            <p className="resume-form-hint">没有现成简历？按模块填写，保存后将作为当前简历进行分析。</p>
            <div className="resume-form-basic">
              <label className="brief-field">
                <span>姓名</span>
                <input value={studentInfo.name} disabled placeholder="登录后自动填写" />
              </label>
              <label className="brief-field">
                <span>学号</span>
                <input value={studentInfo.studentNo} disabled placeholder="登录后自动填写" />
              </label>
              <label className="brief-field">
                <span>学院</span>
                <input value={studentInfo.college || form.college || ''} disabled placeholder="登录后自动填写" />
              </label>
              <label className="brief-field">
                <span>专业</span>
                <select
                  value={form.major || ''}
                  onChange={(event) => handleFormChange('major', event.target.value)}
                  disabled={!form.college}
                >
                  <option value="">{form.college ? '请选择专业' : '请先选择学院'}</option>
                  {majorOptions.map((major) => (
                    <option key={major.id || major.name} value={major.name}>{major.name}</option>
                  ))}
                </select>
              </label>
            </div>

            <div className="resume-form-fields">
              <ProfessionalSkillsPicker value={form.professional_skills} role={profile?.target_role || analysis.targetRole} onChange={(value) => handleFormChange('professional_skills', value)} />
              <AdvantagePicker value={form.advantages} onChange={(value) => handleFormChange('advantages', value)} />
              <EducationPicker value={form.education} onChange={(value) => handleFormChange('education', value)} />
              <BonusPicker value={form.bonus} onChange={(value) => handleFormChange('bonus', value)} />
              <HonorsPicker value={form.honors} onChange={(value) => handleFormChange('honors', value)} />
              <ProjectsPicker value={form.projects} onChange={(value) => handleFormChange('projects', value)} />
              <LanguagePicker value={form.languages} onChange={(value) => handleFormChange('languages', value)} />
              <GenericListPicker
                icon={<Zap size={18} />}
                title="技能"
                itemFields={[{ key: 'skill', label: '技能' }, { key: 'level', label: '熟练程度' }]}
                value={form.skills}
                onChange={(value) => handleFormChange('skills', value)}
              />
              <GenericListPicker
                icon={<FolderOpen size={18} />}
                title="个人作品"
                itemFields={[{ key: 'name', label: '作品集' }, { key: 'link', label: '作品链接' }]}
                value={form.works}
                onChange={(value) => handleFormChange('works', value)}
              />
              <GenericListPicker
                icon={<ShieldCheck size={18} />}
                title="证书"
                itemFields={[{ key: 'name', label: '证书名称' }, { key: 'certNo', label: '证书编号' }]}
                value={form.certificates}
                onChange={(value) => handleFormChange('certificates', value)}
              />
            </div>

          </fieldset>
          )}
          <div className="resume-editor-footer">
            <div className="resume-form-actions">
              <button className="secondary-action" type="button" onClick={editorMode === 'form' ? handleSaveForm : handleSaveText} disabled={busy || (editorMode === 'document' && !resumeText.trim())}><Save size={15} />{savingForm || savingText ? '保存中…' : '保存简历'}</button>
              <ResumeDownloader text={resumeText} name={studentInfo.name || '简历'} />
            </div>
            <button className="primary-action" type="button" onClick={handleAnalyze} disabled={busy || (editorMode === 'document' && !resumeText.trim())}><Sparkles size={16} />{analyzing ? '正在分析…' : editorMode === 'form' ? '保存并分析' : '开始分析'}</button>
          </div>
        </section>

        <aside className="resume-insight">
          <span className="resume-kicker">CAREER INSIGHT / 岗位匹配</span>
          {hasResult ? <>
            <div className="resume-score-line"><strong>{analysis.matchScore}<small>/ 100</small></strong><span>{analysisMeta?.isLocal ? '规则证据分' : (analysis.scoreLabel || '方向匹配度')}</span></div>
            <div className="resume-score-track"><span style={{ width: `${Math.min(100, Math.max(0, Number(analysis.matchScore) || 0))}%` }} /></div>
            <span className="resume-insight-label">优先探索的方向</span>
            <h2>{analysis.targetRole}</h2>
            <p>{analysis.summary}</p>
            <div className="resume-analysis-footnote">{analysisMeta?.isLocal ? '本地规则辅助分析 · 分数为证据匹配程度，并非录用概率。' : 'AI 根据简历中的技能、职责与成果生成，供你选择方向时参考。'}</div>
          </> : <div className="resume-insight-empty"><Target size={36} strokeWidth={1.2} /><h2>{analyzing ? '正在发现你的优势' : '你的下一步，从这里出发'}</h2><p>{analyzing ? '正在结合你的经历分析岗位方向，请稍候。' : '完善简历后开始分析，查看匹配方向、推荐依据和需要补强的能力。'}</p></div>}
          <div className="resume-current-target"><span>当前训练目标</span><strong>{profile?.target_role || '尚未选择'}</strong><small>可在下方确认推荐方向，或填写自己的目标。</small></div>
        </aside>
      </section>

      <section className="direction-panel">
        <Card title="推荐就业方向" icon={<Target size={18} />}>
          {hasResult && analysis.directions?.length ? (
            <div className="direction-grid">
              {analysis.directions.map((direction, index) => {
                const confirmed = profile?.target_role === direction.name;
                return (
                  <article className={`direction-card ${confirmed ? 'confirmed' : ''}`} key={direction.name}>
                    <div className="direction-card-head">
                      <span className="direction-rank">方向 0{index + 1}</span>
                      <strong>{direction.score} 分</strong>
                    </div>
                    <h3>{direction.name}</h3>
                    <span className="resume-catalog-label">{direction.catalogStatus === 'matched' ? '岗位库已收录' : 'AI 拓展方向'}</span>
                    <div className="direction-evidence">
                      <span>推荐依据</span>
                      <p>{direction.reasons.join('；') || '结合简历中的技能、项目和学习经历综合推荐。'}</p>
                    </div>
                    <div className="direction-evidence gap">
                      <span>需要补强</span>
                      <p>{direction.gaps.join('；') || '建议通过模拟面试继续验证岗位能力。'}</p>
                    </div>
                    <button
                      type="button"
                      className={confirmed ? 'secondary-action' : 'primary-action'}
                      onClick={() => handleConfirmDirection(direction.name)}
                      disabled={confirmed || busy}
                    >
                      {confirmed ? '已确认该方向' : '确认作为训练目标'}
                    </button>
                  </article>
                );
              })}
            </div>
          ) : (
            <p className="direction-empty">点击“开始分析”后，系统会结合专业、技能、项目和实践经历推荐多个方向。</p>
          )}

          <div className="custom-role-confirm">
            <label htmlFor="custom-target-role">推荐结果不合适？输入自己的目标岗位</label>
            <div>
              <input
                id="custom-target-role"
                value={customRole}
                onChange={(event) => setCustomRole(event.target.value)}
                placeholder="例如：网络安全工程师"
              />
              <button type="button" className="secondary-action" disabled={busy || !customRole.trim()} onClick={() => handleConfirmDirection(customRole)}>
                确认自定义方向
              </button>
            </div>
          </div>
        </Card>
      </section>

      {!analyzed && !!resumeText && <div className="resume-draft-note">简历内容已更新，点击“开始分析”刷新分析结果。</div>}
    </section>
  );
}

function SetupPage({ onStart, mode = 'guided', presetKey = defaultDifficultyPreset.key }) {
  const initialPreset = difficultyPresets.find((preset) => preset.key === presetKey) || defaultDifficultyPreset;
  const defaultBrief = '';
  const [form, setForm] = useState({
    role: '',
    ...initialPreset.overrides,
    brief: defaultBrief,
  });
  const [showAdvanced, setShowAdvanced] = useState(mode === 'custom');
  const [activeDimension, setActiveDimension] = useState(0);
  const [loadingProfile, setLoadingProfile] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');
  const [recommendedRoles, setRecommendedRoles] = useState([]);
  const briefTouchedRef = useRef(false);
  const customDimensions = [
    { label: '面试类型', key: 'interviewType', options: setupOptions.interviewTypes },
    { label: '公司场景', key: 'companyScene', options: setupOptions.companyScenes },
    { label: '练习重点', key: 'focusArea', options: setupOptions.focusAreas },
    { label: '面试强度', key: 'intensity', options: setupOptions.intensity },
    { label: '面试官风格', key: 'style', options: setupOptions.styles },
  ];
  const selectedLevelIndex = Math.max(0, setupOptions.levels.indexOf(form.level));
  const activeOptions = customDimensions[activeDimension].options;
  const selectedOptionIndex = Math.max(0, activeOptions.indexOf(form[customDimensions[activeDimension].key]));

  useEffect(() => {
    let mounted = true;

    async function loadSetupDefaults() {
      try {
        const data = await apiRequest('/api/profile');
        if (!mounted) return;
        const profile = data.profile || {};
        const profileBrief = profile.project_experience || profile.resume_text || defaultBrief;

        setForm((current) => mergeProfileIntoSetup(
          current,
          { ...profile, project_experience: profileBrief },
          mode,
          { preserveBrief: briefTouchedRef.current },
        ));

        if (hasResumeAnalysisSource(profile)) {
          const analysisData = await apiRequest('/api/profile/resume-analysis', { method: 'POST' });
          if (!mounted) return;
          const resumeAnalysisData = analysisData.resume_analysis?.analysis;
          const analysisBrief = buildBriefFromResumeAnalysis(resumeAnalysisData);
          const directions = normalizeRecommendedDirections(resumeAnalysisData?.recommended_directions);
          setRecommendedRoles(directions);
          setForm((current) => ({
            ...current,
            role: profile.target_role || directions[0]?.name || current.role,
            brief: analysisBrief && !briefTouchedRef.current ? analysisBrief : current.brief,
          }));
        }
      } catch (requestError) {
        if (mounted) setError(requestError.message);
      } finally {
        if (mounted) setLoadingProfile(false);
      }
    }

    loadSetupDefaults();

    return () => {
      mounted = false;
    };
  }, []);

  const updateForm = (key, value) => {
    setForm((current) => ({ ...current, [key]: value }));
    setError('');
  };

  const handleStart = async () => {
    setError('');
    if (!form.role.trim()) {
      setError('请先确认或输入目标岗位，再开始面试。');
      return;
    }
    setStarting(true);

    try {
      const data = await apiRequest('/api/interviews', {
        method: 'POST',
        body: JSON.stringify({
          target_role: form.role,
          experience_level: form.level,
          interview_type: form.interviewType,
          company_context: form.companyScene,
          focus_areas: form.focusArea,
          resume_context: form.brief,
          difficulty: form.intensity,
          interviewer_style: form.style,
        }),
      });
      await apiRequest(`/api/interviews/${data.interview.id}/start`, { method: 'POST' });
      onStart(data.interview.id);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setStarting(false);
    }
  };

  return (
    <section className="setup-page v4-setup-page">
      <V4PageHeading
        eyebrow={mode === 'custom' ? 'DESIGN YOUR CHALLENGE' : 'GUIDED SESSION'}
        title={mode === 'custom' ? '构建你的专属面试。' : '确认本场面试。'}
        description={mode === 'custom' ? '从经验层级出发，设置面试场景、练习重点与面试官风格。' : `已选择${initialPreset.label}难度，确认目标岗位后即可开始。`}
      />

      {error && <div className="profile-message error">{error}</div>}

      <section className="setup-grid">
        <Card title="本场面试配置" icon={<Layers3 size={18} />} className="v4-setup-card">
          <div className="setup-form">
            {mode === 'guided' && <div className="v4-selected-preset"><span className="v4-eyebrow">01 / GUIDED SESSION</span><strong>{initialPreset.label}难度</strong><p>{initialPreset.summary}。{initialPreset.description}</p></div>}
            {mode === 'custom' && <div className="v4-section-intro"><span className="v4-eyebrow">01 / EXPERIENCE & SCENARIO</span><h3>自主难度设置</h3><p>选择适合这次练习的各项参数，配置会用于真实面试。</p></div>}
            <div className="role-input-group">
              <label htmlFor="setup-target-role">{mode === 'custom' ? '02' : '01'} / 目标岗位</label>
              <input
                id="setup-target-role"
                value={form.role}
                onChange={(event) => updateForm('role', event.target.value)}
                placeholder="从推荐方向选择，或输入任意目标岗位"
              />
              {recommendedRoles.length > 0 && (
                <div className="role-recommendations">
                  <div className="role-recommendations-heading">
                    <span><Sparkles size={13} />简历推荐方向</span>
                    <small>点击即可切换</small>
                  </div>
                  <div className="role-suggestions">
                    {recommendedRoles.map((direction) => {
                      const isActive = form.role === direction.name;
                      return (
                        <button
                          type="button"
                          className={isActive ? 'active' : ''}
                          aria-pressed={isActive}
                          key={direction.name}
                          onClick={() => updateForm('role', direction.name)}
                        >
                          <span className="role-suggestion-name">{direction.name}</span>
                          <span className="role-suggestion-score">匹配度 <strong>{direction.score}</strong></span>
                          {isActive && <CheckCircle2 className="role-suggestion-check" size={14} />}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
              <small>推荐方向仅供参考，学生可以按真实求职意愿修改。</small>
            </div>

            {mode === 'guided' && <button
              type="button"
              className="secondary-action advanced-toggle"
              onClick={() => setShowAdvanced((current) => !current)}
              aria-expanded={showAdvanced}
            >
              <Wrench size={15} />
              {showAdvanced ? '收起更多设置' : '展开更多设置'}
              <ChevronDown size={14} className={showAdvanced ? 'advanced-toggle-icon open' : 'advanced-toggle-icon'} />
            </button>}

            {mode === 'custom' && (
              <div className="v4-neural-board">
                <div className="v4-neural-labels"><span>01 / 经验层级</span><span>02 / 配置维度</span><span>03 / 场景选项</span></div>
                <div className="v4-neural-columns">
                  <svg className="v4-neural-wires" viewBox="0 0 1000 355" preserveAspectRatio="none" aria-hidden="true">
                    {customDimensions.map((dimension, index) => (
                      <path
                        key={`level-${dimension.key}`}
                        className={activeDimension === index ? 'active' : ''}
                        d={`M 230 ${28 + selectedLevelIndex * 97} C 305 ${28 + selectedLevelIndex * 97}, 315 ${28 + index * 66}, 390 ${28 + index * 66}`}
                      />
                    ))}
                    {activeOptions.map((option, index) => (
                      <path
                        key={`option-${option}`}
                        className={selectedOptionIndex === index ? 'active' : ''}
                        d={`M 610 ${28 + activeDimension * 66} C 690 ${28 + activeDimension * 66}, 690 ${28 + index * 66}, 770 ${28 + index * 66}`}
                      />
                    ))}
                  </svg>
                  <div className="v4-neural-levels">
                    {setupOptions.levels.map((level, index) => (
                      <button key={level} type="button" className={`v4-network-node${form.level === level ? ' chosen' : ''}`} onClick={() => updateForm('level', level)} aria-pressed={form.level === level}>
                        <small>0{index + 1}</small><b>{level}</b><span>→</span>
                      </button>
                    ))}
                  </div>
                  <div className="v4-neural-dimensions">
                    {customDimensions.map((dimension, index) => (
                      <button key={dimension.key} type="button" className={`v4-network-node${activeDimension === index ? ' focused' : ''}`} onClick={() => setActiveDimension(index)} aria-pressed={activeDimension === index}>
                        <b>{dimension.label}</b><span>✓</span>
                      </button>
                    ))}
                  </div>
                  <div className="v4-neural-values">
                    {activeOptions.map((option) => (
                      <button key={option} type="button" className={`v4-network-node${form[customDimensions[activeDimension].key] === option ? ' chosen' : ''}`} onClick={() => updateForm(customDimensions[activeDimension].key, option)} aria-pressed={form[customDimensions[activeDimension].key] === option}>
                        <b>{option}</b><span>{form[customDimensions[activeDimension].key] === option ? '✓' : '○'}</span>
                      </button>
                    ))}
                  </div>
                </div>
                <div className="v4-neural-summary">
                  <span className="v4-eyebrow">YOUR CONFIGURATION / 5 OF 5</span>
                  <div>{customDimensions.map((dimension, index) => <button key={dimension.key} type="button" onClick={() => setActiveDimension(index)}><small>{dimension.label}</small><b>{form[dimension.key]}</b></button>)}</div>
                </div>
                <label className="brief-field v4-neural-brief">
                  <span>简历 / 项目简介（最多 12,000 字）</span>
                  <textarea value={form.brief} maxLength={12000} placeholder="可填写你的简历摘要、核心项目、希望重点练习的方向" onChange={(event) => { briefTouchedRef.current = true; updateForm('brief', event.target.value); }} />
                  <small>{form.brief.length.toLocaleString()} / 12,000</small>
                </label>
              </div>
            )}

            {mode === 'guided' && showAdvanced && (
              <div className="advanced-panel">
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
                  <span>简历 / 项目简介（最多 12,000 字）</span>
                  <textarea
                    value={form.brief}
                    maxLength={12000}
                    placeholder="可填写你的简历摘要、核心项目、希望重点练习的方向"
                    onChange={(event) => {
                      briefTouchedRef.current = true;
                      updateForm('brief', event.target.value);
                    }}
                  />
                  <small>{form.brief.length.toLocaleString()} / 12,000</small>
                </label>
              </div>
            )}
          </div>
        </Card>

        <button className="primary-action start-interview" onClick={handleStart} disabled={starting || loadingProfile}>
          <Phone size={17} />
          {starting ? '创建中' : '开始电话面试'}
        </button>

      </section>
      <div className="v4-setup-launch">
        <div><span className="v4-eyebrow">READY FOR YOUR SESSION</span><strong>{form.role.trim() || '请先确认目标岗位'}</strong><small>{form.interviewType} · {form.intensity} · {form.style}</small></div>
        <button className="primary-action" onClick={handleStart} disabled={starting || loadingProfile}>
          <Phone size={17} />
          {starting ? '正在创建面试…' : '开始电话面试 ↗'}
        </button>
      </div>
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
        const name = agent.agent_name || agent.name;
        const role = agent.agent_role || agent.role;
        const active = name === currentAgent;
        const statusText = active ? '正在提问' : agent.status === 'completed' ? '已完成' : '待接入';
        return (
          <div className={`agent-row ${active ? 'active' : ''}`} key={agent.id || name}>
            <AgentAvatar name={name} active={active} />
            <div>
              <strong>{name}</strong>
              <span>{role}</span>
            </div>
            <StatusTag tone={active ? 'green' : 'blue'}>{statusText}</StatusTag>
          </div>
        );
      })}
    </div>
  );
}

function TranscriptMessage({ item }) {
  const isCandidate = item.sender_type === 'candidate' || item.type === 'candidate';
  const speaker = item.agent_name || item.speaker || (isCandidate ? '候选人' : 'Agent');
  const time = item.created_at ? formatDateTime(item.created_at) : item.time;
  const text = item.content || item.text;

  return (
    <article className={`transcript-message ${isCandidate ? 'candidate' : 'agent'}`}>
      <div className="message-meta">
        <strong>{speaker}</strong>
        <span>{time}</span>
      </div>
      <p>{text}</p>
    </article>
  );
}

function PhoneInterviewPage({ interviewId, onReportReady, onBackToSetup }) {
  const [interview, setInterview] = useState(null);
  const [agents, setAgents] = useState([]);
  const [messages, setMessages] = useState([]);
  const [answer, setAnswer] = useState('');
  const [loading, setLoading] = useState(Boolean(interviewId));
  const [submitting, setSubmitting] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [error, setError] = useState('');
  const [processingStage, setProcessingStage] = useState('');
  const [processingSeconds, setProcessingSeconds] = useState(0);
  const [interviewMode, setInterviewMode] = useState('text');
  const [voiceProvider] = useState('aliyun-rtc');
  const [voiceStatus, setVoiceStatus] = useState('idle');
  const [voiceMessage, setVoiceMessage] = useState('点击麦克风开始真实语音通话');
  const [qwenStatus, setQwenStatus] = useState('idle');
  const [qwenMessage, setQwenMessage] = useState('提交文本回答后自动播放千问语音追问');
  const [omniStatus, setOmniStatus] = useState('idle');
  const [omniMessage, setOmniMessage] = useState('连接 Qwen-Omni API、网关或官方 WebRTC 后开始通话');
  const [omniAudioUrl, setOmniAudioUrl] = useState('');
  const [omniSignals, setOmniSignals] = useState({ text: false, audioField: false, playableAudio: false });
  const [aliyunRtcStatus, setAliyunRtcStatus] = useState('idle');
  const [aliyunRtcMessage, setAliyunRtcMessage] = useState('点击麦克风加入阿里云 RTC 面试频道');
  const [aliyunRtcRemoteUsers, setAliyunRtcRemoteUsers] = useState(0);
  const [aliyunAgentStatus, setAliyunAgentStatus] = useState('disabled');
  const [aliyunAgentTranscript, setAliyunAgentTranscript] = useState(null);
  const [aliyunSpokenQuestion, setAliyunSpokenQuestion] = useState('');
  const [aliyunRtcSwitching, setAliyunRtcSwitching] = useState(false);

  useEffect(() => {
    if (!processingStage) {
      setProcessingSeconds(0);
      return undefined;
    }
    setProcessingSeconds(0);
    const timer = window.setInterval(() => setProcessingSeconds((seconds) => seconds + 1), 1000);
    return () => window.clearInterval(timer);
  }, [processingStage]);

  const peerConnectionRef = useRef(null);
  const dataChannelRef = useRef(null);
  const localStreamRef = useRef(null);
  const remoteAudioRef = useRef(null);
  const openaiOpeningPlaybackRef = useRef(false);
  const openaiOpeningMicRestoreTimerRef = useRef(null);
  const omniSocketRef = useRef(null);
  const omniRecorderRef = useRef(null);
  const omniStreamRef = useRef(null);
  const omniAudioChunksRef = useRef([]);
  const omniAudioUrlRef = useRef('');
  const omniAudioElementRef = useRef(null);
  const omniAudioContextRef = useRef(null);
  const omniPlaybackTimeRef = useRef(0);
  const omniPlaybackSourcesRef = useRef([]);
  const omniPlaybackTimerRef = useRef(null);
  const omniPlaybackQueuedRef = useRef(false);
  const omniRecognitionRef = useRef(null);
  const omniRecognitionActiveRef = useRef(false);
  const omniTranscriptRef = useRef('');
  const omniInterimTranscriptRef = useRef('');
  const omniTranscriptSavedRef = useRef(false);
  const omniWebrtcPeerRef = useRef(null);
  const omniWebrtcStreamRef = useRef(null);
  const omniWebrtcSessionIdRef = useRef('');
  const omniWebrtcDataChannelRef = useRef(null);
  const omniWebrtcRemoteAudioRef = useRef(null);
  const omniWebrtcAudioSenderRef = useRef(null);
  const omniWebrtcAudioTrackRef = useRef(null);
  const omniWebrtcSessionUpdateRef = useRef(null);
  const omniWebrtcSessionUpdatedRef = useRef(false);
  const omniWebrtcOpeningRequestedRef = useRef(false);
  const omniWebrtcCandidateTranscriptRef = useRef('');
  const omniWebrtcAgentTranscriptRef = useRef('');
  const qwenAudioRef = useRef(null);
  const qwenStreamRef = useRef(null);
  const qwenRecognitionRef = useRef(null);
  const qwenRecognitionActiveRef = useRef(false);
  const qwenRecognitionSubmittedRef = useRef(false);
  const savedRealtimeEventsRef = useRef(new Set());
  const aliyunRtcSessionRef = useRef(null);
  const aliyunRtcAttemptRef = useRef(0);
  const aliyunRtcChannelRef = useRef('');
  const aliyunRtcAgentTaskRef = useRef('');
  const aliyunRtcHeartbeatIntervalRef = useRef(15000);
  const aliyunRtcTranscriptAssemblerRef = useRef(null);
  if (!aliyunRtcTranscriptAssemblerRef.current) {
    aliyunRtcTranscriptAssemblerRef.current = createAliyunRtcTranscriptAssembler();
  }
  const aliyunRtcProcessedTurnsRef = useRef(new Set());
  const aliyunRtcSubmissionQueueRef = useRef(Promise.resolve());
  const aliyunRtcAgentSubmissionQueueRef = useRef(Promise.resolve());
  const aliyunRtcSubmissionErrorRef = useRef(null);
  const aliyunRtcNextActionRef = useRef('ask_follow_up');
  const pendingEvaluationRequestsRef = useRef(new Set());
  const activeAgentRef = useRef(null);
  const handleSubmitAnswerRef = useRef(null);

  const enqueueAliyunRtcCandidateTurn = (turn) => {
    if (!turn?.text || turn.speaker !== 'candidate' || !turn.end) return;
    const processedKey = `candidate:${turn.turnId}`;
    if (aliyunRtcProcessedTurnsRef.current.has(processedKey)) return;
    aliyunRtcProcessedTurnsRef.current.add(processedKey);
    aliyunRtcNextActionRef.current = 'pending';
    setAliyunRtcMessage('已识别到回答，正在保存并生成下一题');
    recordAliyunRtcDiagnostic('candidate_turn_finalized', {
      message: 'RTC 候选人转写已收口，开始提交业务回答',
      metadata: { text_length: turn.text.length },
    });
    aliyunRtcSubmissionQueueRef.current = aliyunRtcSubmissionQueueRef.current
      .then(() => handleSubmitAnswerRef.current?.(turn.text, {
        source: 'aliyun_rtc',
        sourceRef: turn.turnId,
        transcriptText: turn.text,
      }))
      .then(() => {
        aliyunRtcSubmissionErrorRef.current = null;
      })
      .catch((submitError) => {
        aliyunRtcProcessedTurnsRef.current.delete(processedKey);
        aliyunRtcSubmissionErrorRef.current = submitError;
        aliyunRtcNextActionRef.current = 'error';
        setError(submitError.message || 'RTC 语音回答保存失败');
        setAliyunRtcMessage('RTC 回答保存失败，请先不要结束面试');
      });
  };

  const enqueueAliyunRtcAgentTurn = (turn) => {
    if (!turn?.text || turn.speaker !== 'agent' || !turn.end) return;
    if (aliyunRtcNextActionRef.current === 'opening') return;
    const processedKey = `agent:${turn.turnId}`;
    if (aliyunRtcProcessedTurnsRef.current.has(processedKey)) return;
    aliyunRtcProcessedTurnsRef.current.add(processedKey);
    const candidateSubmission = aliyunRtcSubmissionQueueRef.current;
    const agentId = activeAgentRef.current?.id || '';
    const callAttempt = aliyunRtcAttemptRef.current;
    aliyunRtcAgentSubmissionQueueRef.current = aliyunRtcAgentSubmissionQueueRef.current
      .then(async () => {
        // Cloud speech can finish before the candidate answer has committed.
        // Wait so the actual question keeps the right message order. Evaluation
        // continues independently and must not delay the next spoken question.
        await candidateSubmission;
        if (aliyunRtcAttemptRef.current !== callAttempt) return;
        const latestMessages = await reloadMessages();
        if (aliyunRtcAttemptRef.current !== callAttempt || activeAgentRef.current?.id !== agentId) return;
        const latestQuestion = findLatestInterviewQuestion(latestMessages);
        if (!shouldPersistAliyunAgentTurn(
          turn,
          latestQuestion,
          aliyunRtcNextActionRef.current
        )) return;
        if (!agentId) throw new Error('无法确定 RTC 面试官，实际追问未保存');
        const spokenQuestion = extractQuestionFromAgentTranscript(turn.text);
        await apiRequest(`/api/interviews/${interviewId}/messages`, {
          method: 'POST',
          body: JSON.stringify({
            agent_id: agentId,
            sender_type: 'agent',
            message_type: 'follow_up',
            content: spokenQuestion,
            transcript_text: turn.text,
            source: 'aliyun_rtc',
            source_ref: `agent:${turn.turnId}`,
          }),
        });
        await reloadMessages();
        recordAliyunRtcDiagnostic('agent_turn_persisted', {
          message: 'RTC AI 实际追问已同步到当前问题',
          metadata: { text_length: spokenQuestion.length },
        });
      })
      .catch((submitError) => {
        aliyunRtcProcessedTurnsRef.current.delete(processedKey);
        setError(submitError.message || 'RTC AI 实际追问同步失败');
        recordAliyunRtcDiagnostic('agent_turn_persist_failed', {
          level: 'warning',
          message: 'RTC AI 实际追问未能同步到消息流',
          metadata: { error_name: submitError?.name || 'Error' },
        });
      });
  };

  const recordOmniWebrtcDiagnostic = (eventType, {
    level = 'info',
    message = '',
    peerConnection = omniWebrtcPeerRef.current,
    dataChannel = omniWebrtcDataChannelRef.current,
    metadata = {},
  } = {}) => {
    const sessionId = omniWebrtcSessionIdRef.current;
    if (!interviewId || !sessionId) return;
    void apiRequest(`/api/interviews/${interviewId}/webrtc-events`, {
      method: 'POST',
      body: JSON.stringify({
        provider: 'qwen-omni-realtime-webrtc',
        session_id: sessionId,
        event_type: eventType,
        level,
        connection_state: peerConnection?.connectionState || '',
        ice_connection_state: peerConnection?.iceConnectionState || '',
        ice_gathering_state: peerConnection?.iceGatheringState || '',
        signaling_state: peerConnection?.signalingState || '',
        data_channel_state: dataChannel?.readyState || '',
        message,
        metadata,
        client_created_at: new Date().toISOString(),
      }),
    }).catch(() => {
      // Diagnostics must never interrupt the interview flow.
    });
  };

  const recordAliyunRtcDiagnostic = (eventType, {
    level = 'info',
    message = '',
    connectionState = '',
    metadata = {},
  } = {}) => {
    if (!interviewId) return;
    void apiRequest(`/api/interviews/${interviewId}/webrtc-events`, {
      method: 'POST',
      body: JSON.stringify({
        provider: 'aliyun-rtc-web',
        session_id: aliyunRtcChannelRef.current,
        event_type: eventType,
        level,
        connection_state: connectionState,
        message,
        metadata,
        client_created_at: new Date().toISOString(),
      }),
    }).catch(() => {
      // Diagnostics must never interrupt the interview flow.
    });
  };

  const stopAliyunRtcAgentTask = async (_taskId) => {
    if (!interviewId) return null;
    try {
      let result = await apiRequest(`/api/interviews/${interviewId}/rtc/agent/stop`, {
        method: 'POST',
        body: JSON.stringify({}),
      });
      // A concurrent server-side finish may observe the persisted stop intent
      // before StopAgent returns. Wait briefly for the authoritative terminal
      // state instead of navigating away while the Agent is still speaking.
      for (let poll = 0; result.status !== 'stopped' && poll < 12; poll += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 500));
        const statusResult = await apiRequest(`/api/interviews/${interviewId}/rtc/session`);
        result = {
          ...result,
          status: statusResult.rtc_session?.state || result.status,
          rtc_session: statusResult.rtc_session || result.rtc_session,
        };
      }
      recordAliyunRtcDiagnostic(
        result.status === 'stopped' ? 'ai_agent_stopped' : 'ai_agent_stop_deferred',
        {
          level: result.status === 'stopped' ? 'info' : 'warning',
          message: result.status === 'stopped' ? 'RTC AI 智能体已停止' : 'RTC AI 智能体停止请求已持久化',
          metadata: { phase: result.status || 'unknown' },
        }
      );
      if (result.status !== 'stopped') {
        setAliyunRtcMessage('已退出通话，服务端正在回收 RTC 智能体');
      }
      return result;
    } catch (stopError) {
      recordAliyunRtcDiagnostic('ai_agent_stop_request_failed', {
        level: 'warning',
        message: 'RTC AI 智能体停止请求未送达，服务端将按心跳超时回收',
        metadata: { error_name: stopError?.name || 'Error' },
      });
      return null;
    }
  };

  const stopAliyunRtcCall = async (message = '阿里云 RTC 通话已断开', { flushCandidate = true } = {}) => {
    // Some provider sessions do not emit a final end=true caption. Preserve
    // any buffered candidate speech before pausing or leaving the channel.
    if (flushCandidate) {
      enqueueAliyunRtcCandidateTurn(aliyunRtcTranscriptAssemblerRef.current.finalize('candidate'));
    }
    aliyunRtcAttemptRef.current += 1;
    const agentTaskId = aliyunRtcAgentTaskRef.current;
    aliyunRtcAgentTaskRef.current = '';
    const session = aliyunRtcSessionRef.current;
    aliyunRtcSessionRef.current = null;
    setAliyunRtcStatus('idle');
    setAliyunRtcMessage(message);
    setAliyunRtcRemoteUsers(0);
    setAliyunAgentStatus('disabled');
    setAliyunAgentTranscript(null);
    const leavePromise = session ? session.leave() : Promise.resolve();
    const stopPromise = stopAliyunRtcAgentTask(agentTaskId);
    const [, stopped] = await Promise.allSettled([leavePromise, stopPromise]);
    if (session) {
      recordAliyunRtcDiagnostic('call_stopped', { message: '用户已退出阿里云 RTC 频道' });
    }
    aliyunRtcChannelRef.current = '';
    aliyunRtcTranscriptAssemblerRef.current.reset();
    return stopped.status === 'fulfilled' ? stopped.value : null;
  };

  const waitForAliyunRtcAgentActive = async (initialSession, attempt) => {
    let rtcSession = initialSession?.rtc_session || initialSession;
    for (let poll = 0; poll < 75; poll += 1) {
      if (aliyunRtcAttemptRef.current !== attempt) {
        throw new Error('RTC 启动已取消');
      }
      if (rtcSession?.state === 'active') {
        return {
          task_id: rtcSession.task_id,
          status: rtcSession.state,
          rtc_session: rtcSession,
        };
      }
      if (['start_failed', 'stop_requested', 'stopping', 'stop_failed', 'stopped'].includes(rtcSession?.state)) {
        throw new Error(rtcSession.last_error || `RTC AI 智能体状态异常：${rtcSession.state}`);
      }
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      const statusResult = await apiRequest(`/api/interviews/${interviewId}/rtc/session`);
      rtcSession = statusResult.rtc_session;
    }
    throw new Error('RTC AI 智能体启动确认超时，请断开后重试');
  };

  const startAliyunRtcCall = async ({ afterHandoff = false } = {}) => {
    if (!interviewId || interview?.status === 'completed') {
      setAliyunRtcStatus('idle');
      setAliyunRtcMessage('本场面试已结束，不能重新加入 RTC 频道');
      setError('本场面试已结束，请在复盘报告中查看结果。');
      return;
    }

    if (!afterHandoff && (aliyunRtcStatus === 'connected' || aliyunRtcStatus === 'connecting')) {
      await stopAliyunRtcCall();
      return;
    }

    stopRealtimeCall();
    stopOmniRealtimeCall('已切换到阿里云 RTC');
    stopOmniWebrtcCall('已切换到阿里云 RTC');
    stopQwenRecognition();
    stopQwenSpeech();

    const attempt = aliyunRtcAttemptRef.current + 1;
    aliyunRtcAttemptRef.current = attempt;
    setError('');
    setAliyunRtcStatus('connecting');
    setAliyunRtcMessage('正在申请面试频道 Token');
    setAliyunRtcRemoteUsers(0);
    setAliyunAgentStatus('disabled');
    setAliyunAgentTranscript(null);
    setAliyunSpokenQuestion('');
    aliyunRtcTranscriptAssemblerRef.current.reset();
    aliyunRtcProcessedTurnsRef.current.clear();
    aliyunRtcSubmissionErrorRef.current = null;
    aliyunRtcNextActionRef.current = 'opening';

    let startupPhase = 'messages';
    const startupStartedAt = Date.now();
    try {
      // A reconnect must use the database-backed question instead of the
      // messages captured by the render that created this callback.
      const latestMessages = await reloadMessages();
      const latestQuestion = findLatestInterviewQuestion(latestMessages);
      startupPhase = 'token';
      const credentials = await apiRequest(`/api/interviews/${interviewId}/rtc/token`, {
        method: 'POST',
      });
      if (aliyunRtcAttemptRef.current !== attempt) return;
      aliyunRtcChannelRef.current = credentials.channel_id;
      aliyunRtcHeartbeatIntervalRef.current = Math.max(
        5000,
        Number(credentials.rtc_session?.heartbeat_interval_seconds || 15) * 1000
      );
      recordAliyunRtcDiagnostic('token_issued', {
        message: '已获取当前面试的 RTC 短期 Token',
        metadata: { expires_in: credentials.expires_in },
      });

      startupPhase = 'sdk';
      setAliyunRtcMessage('正在连接阿里云 RTC 频道');
      const session = await createAliyunRtcAudioSession({
        credentials,
        isCancelled: () => aliyunRtcAttemptRef.current !== attempt,
        onStartupStage: (phase) => {
          if (aliyunRtcAttemptRef.current !== attempt) return;
          startupPhase = phase;
          const messages = {
            join: '正在连接阿里云 RTC 频道',
            join_retry: '语音网络连接失败，正在自动重试（1/1）',
            messaging: '正在建立语音字幕通道',
            microphone: '正在请求麦克风权限',
            publish: '正在连接麦克风音频',
          };
          setAliyunRtcMessage(messages[phase] || '正在准备语音连接');
          recordAliyunRtcDiagnostic('startup_stage_changed', {
            message: messages[phase] || '正在准备语音连接',
            metadata: { phase, elapsed_ms: Date.now() - startupStartedAt },
          });
        },
        onConnectionState: ({ state, message }) => {
          if (aliyunRtcAttemptRef.current !== attempt) return;
          if (state === 'connected') setAliyunRtcStatus('connected');
          if (state === 'reconnecting') setAliyunRtcStatus('connecting');
          if (state === 'disconnected') setAliyunRtcStatus('error');
          setAliyunRtcMessage(message);
          recordAliyunRtcDiagnostic('connection_state_changed', {
            level: state === 'disconnected' ? 'warning' : 'info',
            message: '阿里云 RTC 连接状态变更',
            connectionState: state,
          });
        },
        onRemoteAudio: (remoteUser) => {
          if (aliyunRtcAttemptRef.current !== attempt) return;
          setAliyunRtcMessage(`正在播放 ${remoteUser.userName || '远端面试官'} 的语音`);
          recordAliyunRtcDiagnostic('remote_audio_playing', {
            message: '已订阅并播放远端音频',
          });
        },
        onRemoteUserCount: (count) => {
          if (aliyunRtcAttemptRef.current === attempt) setAliyunRtcRemoteUsers(count);
        },
        onAgentMessagingReady: (ready) => {
          if (aliyunRtcAttemptRef.current !== attempt) return;
          recordAliyunRtcDiagnostic(
            ready ? 'ai_agent_messaging_ready' : 'ai_agent_messaging_unavailable',
            {
              level: ready ? 'info' : 'error',
              message: ready
                ? 'RTC AI 字幕通道已就绪'
                : 'RTC AI 字幕通道未就绪',
            }
          );
        },
        onAgentStatus: (status) => {
          if (aliyunRtcAttemptRef.current !== attempt) return;
          if (['thinking', 'processing', 'responding'].includes(status)) {
            enqueueAliyunRtcCandidateTurn(
              aliyunRtcTranscriptAssemblerRef.current.finalize('candidate')
            );
          }
          setAliyunAgentStatus(status);
          const statusMessages = {
            listening: 'AI 面试官正在聆听',
            thinking: 'AI 面试官正在思考',
            processing: 'AI 面试官正在思考',
            responding: 'AI 面试官正在回答',
          };
          setAliyunRtcMessage(statusMessages[status] || `AI 面试官状态：${status}`);
          recordAliyunRtcDiagnostic('ai_agent_status_changed', {
            message: 'RTC AI 智能体状态变更',
            metadata: { phase: status },
          });
        },
        onAgentMessage: (message) => {
          if (aliyunRtcAttemptRef.current !== attempt) return;
          recordAliyunRtcDiagnostic('transcription_received', {
            message: 'RTC AI 智能体字幕回调',
            metadata: {
              speaker: message?.userType || 'unknown',
              end: Boolean(message?.end),
              reasoning: Boolean(message?.reasoning),
              text_length: String(message?.message || '').trim().length,
            },
          });
          if (message?.userType === 'agent' && !message?.reasoning) {
            enqueueAliyunRtcCandidateTurn(
              aliyunRtcTranscriptAssemblerRef.current.finalize('candidate')
            );
          }
          const turn = aliyunRtcTranscriptAssemblerRef.current.consume(message);
          if (!turn) return;
          setAliyunAgentTranscript({
            text: turn.text,
            speaker: turn.speaker === 'candidate' ? '候选人' : 'AI 面试官',
            end: turn.end,
          });
          if (turn.speaker === 'agent') {
            setAliyunSpokenQuestion(extractQuestionFromAgentTranscript(turn.text));
            enqueueAliyunRtcAgentTurn(turn);
          }
          enqueueAliyunRtcCandidateTurn(turn);
        },
      });

      if (aliyunRtcAttemptRef.current !== attempt) {
        await session.leave();
        return;
      }
      aliyunRtcSessionRef.current = session;
      setAliyunRtcStatus('connected');
      if (credentials.ai_agent?.enabled) {
        startupPhase = 'agent_start';
        setAliyunAgentStatus('starting');
        setAliyunRtcMessage('已加入 RTC，正在启动 AI 面试官');
        let agentSession;
        try {
          agentSession = await apiRequest(`/api/interviews/${interviewId}/rtc/agent/start`, {
            method: 'POST',
          });
        } catch (startError) {
          const awaitingCloudConfirmation = startError.status === 502
            && String(startError.message || '').includes('启动结果待确认');
          if (!awaitingCloudConfirmation) throw startError;
          setAliyunRtcMessage('AI 面试官启动响应较慢，正在自动核对云端状态');
          setAliyunAgentStatus('starting');
          const statusResult = await apiRequest(`/api/interviews/${interviewId}/rtc/session`);
          agentSession = await waitForAliyunRtcAgentActive(statusResult, attempt);
        }
        if (agentSession.status !== 'active') {
          setAliyunRtcMessage('智能体任务已提交，正在确认云端状态');
          agentSession = await waitForAliyunRtcAgentActive(agentSession, attempt);
        }
        if (aliyunRtcAttemptRef.current !== attempt) {
          stopAliyunRtcAgentTask(agentSession.task_id);
          await session.leave();
          return;
        }
        aliyunRtcAgentTaskRef.current = agentSession.task_id;
        setAliyunAgentStatus(agentSession.status || 'starting');
        setAliyunRtcMessage('AI 面试官正在进入频道');
        recordAliyunRtcDiagnostic('ai_agent_started', {
          message: 'RTC AI 智能体启动请求成功',
        });
        // A newly created provider task receives the current question as its
        // StartAgent greeting from the backend. Only an already-running task
        // needs an explicit replay when the browser reconnects.
        if (agentSession.idempotent && latestQuestion?.id) {
          void apiRequest(`/api/interviews/${interviewId}/rtc/agent/notify`, {
            method: 'POST',
            body: JSON.stringify({ message_id: latestQuestion.id }),
          }).catch((notifyError) => {
            setAliyunRtcMessage(notifyError.message || 'RTC 当前问题播报失败');
          });
        }
      } else {
        setAliyunAgentStatus('disabled');
        setAliyunRtcMessage('已加入 RTC；配置模板和 RAM 密钥后会自动启动 AI 面试官');
      }
    } catch (requestError) {
      if (aliyunRtcAttemptRef.current !== attempt) return;
      const session = aliyunRtcSessionRef.current;
      aliyunRtcSessionRef.current = null;
      if (session) await session.leave();
      const agentTaskId = aliyunRtcAgentTaskRef.current;
      aliyunRtcAgentTaskRef.current = '';
      stopAliyunRtcAgentTask(agentTaskId);
      setAliyunRtcStatus('error');
      setAliyunAgentStatus('error');
      const startErrorMessage = formatAliyunRtcStartError(requestError);
      setAliyunRtcMessage(startErrorMessage);
      setError(startErrorMessage);
      recordAliyunRtcDiagnostic('call_start_failed', {
        level: 'error',
        message: '阿里云 RTC 启动失败',
        metadata: {
          phase: requestError.rtcStage || startupPhase,
          elapsed_ms: Date.now() - startupStartedAt,
          error_name: requestError.name || 'Error',
          error_code: String(requestError.code || requestError.status || ''),
          browser_online: navigator.onLine,
          reason: startErrorMessage,
        },
      });
    }
  };

  useEffect(() => {
    if (!interviewId || aliyunRtcStatus !== 'connected') return undefined;
    let cancelled = false;

    const heartbeat = () => {
      void apiRequest(`/api/interviews/${interviewId}/rtc/session/heartbeat`, {
        method: 'POST',
      }).then((result) => {
        if (cancelled) return;
        const serverState = result.rtc_session?.state;
        if (serverState && !['starting', 'active'].includes(serverState)) {
          setAliyunRtcMessage(`RTC 服务端状态：${serverState}`);
        }
      }).catch((heartbeatError) => {
        if (cancelled) return;
        recordAliyunRtcDiagnostic('session_heartbeat_failed', {
          level: 'warning',
          message: 'RTC 会话心跳失败',
          metadata: { error_name: heartbeatError?.name || 'Error' },
        });
      });
    };

    heartbeat();
    const timer = window.setInterval(heartbeat, aliyunRtcHeartbeatIntervalRef.current);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [interviewId, aliyunRtcStatus]);

  const activeAgent = agents.find((agent) => agent.status === 'active') || agents.find((agent) => agent.status !== 'completed') || agents[0] || null;
  activeAgentRef.current = activeAgent;
  const currentAgentName = activeAgent?.agent_name || liveInterview.currentAgent;
  const latestInterviewQuestion = findLatestInterviewQuestion(messages);
  const persistedQuestion = latestInterviewQuestion?.content || createInitialQuestion(interview, activeAgent);
  const currentQuestion = voiceProvider === 'aliyun-rtc' && aliyunSpokenQuestion
    ? aliyunSpokenQuestion
    : persistedQuestion;

  const reloadMessages = async () => {
    console.info('reloadMessages', {
      interviewId,
      currentMessageCount: messages.length,
      activeAgentId: activeAgent?.id || null,
    });
    const data = await apiRequest(`/api/interviews/${interviewId}/messages`);
    setMessages(data.messages || []);
    return data.messages || [];
  };

  const reloadAgents = async () => {
    const data = await apiRequest(`/api/interviews/${interviewId}/agents`);
    setAgents(data.agents || []);
    return data.agents || [];
  };

  const updateAgentStatus = async (agent, status) => {
    if (!agent?.id) return null;
    return apiRequest(`/api/interviews/${interviewId}/agents/${agent.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
  };

  const setRealtimeMicrophoneEnabled = (enabled) => {
    localStreamRef.current?.getAudioTracks().forEach((track) => {
      track.enabled = enabled;
    });
  };

  const restoreRealtimeMicrophoneAfterOpening = (delayMs = 800) => {
    if (!openaiOpeningPlaybackRef.current) return;

    if (openaiOpeningMicRestoreTimerRef.current) {
      window.clearTimeout(openaiOpeningMicRestoreTimerRef.current);
    }

    openaiOpeningMicRestoreTimerRef.current = window.setTimeout(() => {
      if (!openaiOpeningPlaybackRef.current) return;
      openaiOpeningPlaybackRef.current = false;
      openaiOpeningMicRestoreTimerRef.current = null;
      setRealtimeMicrophoneEnabled(true);
      setVoiceMessage('首问已播放，请开始回答');
    }, delayMs);
  };

  const buildOpenaiOpeningInstructions = () => [
    '你正在接通一场中文电话面试。',
    '请只朗读下面的当前问题，不要额外开场、不要解释规则、不要自我介绍、不要补充其他问题。',
    `当前问题：${currentQuestion}`,
    '读完后立刻停止，等待候选人回答。',
  ].join('\n');

  const stopRealtimeCall = () => {
    if (openaiOpeningMicRestoreTimerRef.current) {
      window.clearTimeout(openaiOpeningMicRestoreTimerRef.current);
    }
    openaiOpeningPlaybackRef.current = false;
    openaiOpeningMicRestoreTimerRef.current = null;
    dataChannelRef.current?.close();
    peerConnectionRef.current?.close();
    localStreamRef.current?.getTracks().forEach((track) => track.stop());
    if (remoteAudioRef.current) {
      remoteAudioRef.current.srcObject = null;
      remoteAudioRef.current.remove();
    }

    dataChannelRef.current = null;
    peerConnectionRef.current = null;
    localStreamRef.current = null;
    remoteAudioRef.current = null;
    setVoiceStatus('idle');
    setVoiceMessage('语音通话已断开，可再次点击麦克风重连');
  };

  const stopOmniPlayback = ({ closeContext = false } = {}) => {
    if (omniPlaybackTimerRef.current) {
      window.clearTimeout(omniPlaybackTimerRef.current);
      omniPlaybackTimerRef.current = null;
    }
    omniPlaybackSourcesRef.current.forEach((source) => {
      try {
        source.stop();
      } catch {
        // Source may have already finished.
      }
      source.disconnect();
    });
    omniPlaybackSourcesRef.current = [];
    omniPlaybackTimeRef.current = 0;
    omniPlaybackQueuedRef.current = false;
    if (omniAudioElementRef.current) {
      omniAudioElementRef.current.pause();
      omniAudioElementRef.current.currentTime = 0;
    }
    if (closeContext && omniAudioContextRef.current) {
      omniAudioContextRef.current.close().catch(() => {});
      omniAudioContextRef.current = null;
    }
  };

  const ensureOmniAudioContext = async () => {
    const AudioContextConstructor = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextConstructor) return null;

    if (!omniAudioContextRef.current || omniAudioContextRef.current.state === 'closed') {
      omniAudioContextRef.current = new AudioContextConstructor();
      omniPlaybackTimeRef.current = 0;
    }

    if (omniAudioContextRef.current.state === 'suspended') {
      await omniAudioContextRef.current.resume();
    }

    return omniAudioContextRef.current;
  };

  const queueOmniPcmPlayback = async (chunk) => {
    const bytes = toUint8Array(chunk);
    if (!bytes.byteLength || isEncodedAudioBytes(bytes)) return false;

    const audioContext = await ensureOmniAudioContext();
    if (!audioContext) return false;

    const audioBuffer = createPcm16AudioBuffer(audioContext, bytes);
    if (!audioBuffer.duration) return false;

    const source = audioContext.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(audioContext.destination);
    const startAt = Math.max(audioContext.currentTime + 0.04, omniPlaybackTimeRef.current || 0);
    source.start(startAt);
    omniPlaybackTimeRef.current = startAt + audioBuffer.duration;
    omniPlaybackQueuedRef.current = true;
    omniPlaybackSourcesRef.current.push(source);
    source.addEventListener('ended', () => {
      omniPlaybackSourcesRef.current = omniPlaybackSourcesRef.current.filter((item) => item !== source);
      source.disconnect();
    });
    setOmniStatus('speaking');
    setOmniMessage('正在流式播放 Qwen-Omni 返回的音频');
    return true;
  };

  const scheduleOmniPlaybackComplete = () => {
    if (omniPlaybackTimerRef.current) {
      window.clearTimeout(omniPlaybackTimerRef.current);
    }

    const audioContext = omniAudioContextRef.current;
    if (!omniPlaybackQueuedRef.current) {
      setOmniStatus('connected');
      setOmniMessage('Omni 音频已生成，请点击下方播放器播放');
      return;
    }

    const remainingMs = audioContext
      ? Math.max(350, (omniPlaybackTimeRef.current - audioContext.currentTime) * 1000 + 250)
      : 350;

    omniPlaybackTimerRef.current = window.setTimeout(() => {
      omniPlaybackTimerRef.current = null;
      setOmniStatus('connected');
      setOmniMessage('Omni 本轮播放完成，可继续说话');
    }, remainingMs);
  };

  const playOmniAudioChunks = () => {
    if (!omniAudioChunksRef.current.length) return;
    const blob = buildOmniAudioBlob(omniAudioChunksRef.current);
    omniAudioChunksRef.current = [];
    if (omniAudioUrlRef.current) {
      URL.revokeObjectURL(omniAudioUrlRef.current);
    }
    const objectUrl = URL.createObjectURL(blob);
    omniAudioUrlRef.current = objectUrl;
    setOmniAudioUrl(objectUrl);
    setOmniSignals((current) => ({ ...current, playableAudio: true }));
  };

  const waitForPeerIceGathering = (connection) => {
    if (connection.iceGatheringState === 'complete') return Promise.resolve('complete');
    return new Promise((resolve) => {
      let settled = false;
      const finish = (result) => {
        if (settled) return;
        settled = true;
        connection.removeEventListener('icegatheringstatechange', handleStateChange);
        resolve(result);
      };
      const timeoutId = window.setTimeout(() => finish('timeout'), 3000);
      const handleStateChange = () => {
        if (connection.iceGatheringState === 'complete') {
          window.clearTimeout(timeoutId);
          finish('complete');
        }
      };
      connection.addEventListener('icegatheringstatechange', handleStateChange);
    });
  };

  const stopOmniRecognition = () => {
    omniRecognitionActiveRef.current = false;
    if (omniRecognitionRef.current) {
      try {
        omniRecognitionRef.current.stop();
      } catch {
        // Recognition can already be stopped by the browser.
      }
    }
    omniRecognitionRef.current = null;
  };

  const saveOmniCandidateTranscript = () => {
    const transcript = (omniTranscriptRef.current || omniInterimTranscriptRef.current || '').trim();
    if (!transcript || omniTranscriptSavedRef.current) return;
    omniTranscriptSavedRef.current = true;
    saveRealtimeMessage({
      senderType: 'candidate',
      messageType: 'transcript',
      content: transcript,
    })
      .then(() => setAnswer(''))
      .catch((requestError) => setError(requestError.message));
  };

  const startOmniRecognition = () => {
    const SpeechRecognition = getSpeechRecognitionConstructor();
    omniTranscriptRef.current = '';
    omniInterimTranscriptRef.current = '';
    omniTranscriptSavedRef.current = false;
    if (!SpeechRecognition) return;

    stopOmniRecognition();
    omniRecognitionActiveRef.current = true;

    const recognition = new SpeechRecognition();
    omniRecognitionRef.current = recognition;
    recognition.lang = 'zh-CN';
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event) => {
      let finalText = '';
      let interimText = '';
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        const transcript = result[0]?.transcript || '';
        if (result.isFinal) {
          finalText += transcript;
        } else {
          interimText += transcript;
        }
      }

      if (finalText.trim()) {
        omniTranscriptRef.current = `${omniTranscriptRef.current} ${finalText}`.trim();
      }
      omniInterimTranscriptRef.current = interimText.trim();

      const visibleText = (omniTranscriptRef.current || omniInterimTranscriptRef.current).trim();
      if (visibleText) {
        setAnswer(visibleText);
      }
    };

    recognition.onerror = (event) => {
      if (event.error !== 'no-speech') {
        setOmniMessage(event.error === 'not-allowed' ? '麦克风语音识别权限被拒绝，仍会提交录音给 Omni' : '本地语音转写失败，仍会提交录音给 Omni');
      }
    };

    recognition.onend = () => {
      if (omniRecognitionRef.current === recognition) {
        omniRecognitionRef.current = null;
      }
      if (omniRecognitionActiveRef.current && omniRecorderRef.current?.state === 'recording') {
        try {
          recognition.start();
          omniRecognitionRef.current = recognition;
        } catch {
          // Chrome may throttle immediate restarts; keep the audio submission path alive.
        }
      }
    };

    try {
      recognition.start();
    } catch {
      omniRecognitionActiveRef.current = false;
      omniRecognitionRef.current = null;
    }
  };

  const stopOmniRealtimeCall = (message = '千问 Omni 自部署通话已断开') => {
    omniRecorderRef.current?.stop();
    stopOmniRecognition();
    omniStreamRef.current?.getTracks().forEach((track) => track.stop());
    omniSocketRef.current?.close();
    stopOmniPlayback({ closeContext: true });
    omniRecorderRef.current = null;
    omniStreamRef.current = null;
    omniSocketRef.current = null;
    omniAudioChunksRef.current = [];
    if (omniAudioUrlRef.current) {
      URL.revokeObjectURL(omniAudioUrlRef.current);
    }
    omniAudioUrlRef.current = '';
    setOmniAudioUrl('');
    setOmniSignals({ text: false, audioField: false, playableAudio: false });
    setOmniStatus('idle');
    setOmniMessage(message);
  };

  const stopOmniWebrtcCall = (message = 'Qwen-Omni WebRTC 已断开', { resetAudio = false } = {}) => {
    recordOmniWebrtcDiagnostic('call_stopped', {
      message,
      metadata: { reason: resetAudio ? 'reset_audio' : 'manual_or_provider_switch' },
    });
    stopOmniRecognition();
    omniWebrtcDataChannelRef.current?.close();
    omniWebrtcStreamRef.current?.getTracks().forEach((track) => track.stop());
    if (omniWebrtcRemoteAudioRef.current) {
      omniWebrtcRemoteAudioRef.current.pause();
      omniWebrtcRemoteAudioRef.current.srcObject = null;
      omniWebrtcRemoteAudioRef.current.remove();
    }
    omniWebrtcPeerRef.current?.close();
    omniWebrtcStreamRef.current = null;
    omniWebrtcPeerRef.current = null;
    omniWebrtcDataChannelRef.current = null;
    omniWebrtcRemoteAudioRef.current = null;
    omniWebrtcAudioSenderRef.current = null;
    omniWebrtcAudioTrackRef.current = null;
    omniWebrtcSessionUpdateRef.current = null;
    omniWebrtcSessionUpdatedRef.current = false;
    omniWebrtcOpeningRequestedRef.current = false;
    omniWebrtcCandidateTranscriptRef.current = '';
    omniWebrtcAgentTranscriptRef.current = '';
    omniWebrtcSessionIdRef.current = '';
    if (resetAudio) {
      stopOmniPlayback({ closeContext: true });
      omniAudioChunksRef.current = [];
      if (omniAudioUrlRef.current) {
        URL.revokeObjectURL(omniAudioUrlRef.current);
      }
      omniAudioUrlRef.current = '';
      setOmniAudioUrl('');
      setOmniSignals({ text: false, audioField: false, playableAudio: false });
    }
    setOmniStatus('idle');
    setOmniMessage(message);
  };

  const finishOmniRecording = () => {
    if (!omniRecorderRef.current || omniRecorderRef.current.state === 'inactive') return;
    omniRecorderRef.current.stop();
    stopOmniRecognition();
    window.setTimeout(saveOmniCandidateTranscript, 250);
    omniStreamRef.current?.getTracks().forEach((track) => track.stop());
    omniRecorderRef.current = null;
    omniStreamRef.current = null;
    setOmniStatus('connecting');
    setOmniMessage('录音已停止，正在提交给 Qwen-Omni');
  };

  const handleOmniPayload = (payload) => {
    if (payload.type === 'error') {
      setOmniStatus('error');
      setOmniMessage(payload.message || '千问 Omni 实时网关返回错误');
      setError(payload.message || '千问 Omni 实时网关返回错误');
      return;
    }
    if (payload.type === 'status') {
      setOmniMessage(payload.message || '千问 Omni 实时网关已连接');
      return;
    }
    if (payload.type === 'text') {
      if (payload.text || payload.content) {
        setOmniSignals((current) => ({ ...current, text: true }));
      }
      return;
    }
    if (payload.type === 'transcript') {
      const content = payload.text || payload.content || '';
      if (content) {
        setOmniSignals((current) => ({ ...current, text: true }));
        saveRealtimeMessage({
          senderType: payload.role === 'candidate' ? 'candidate' : 'agent',
          messageType: payload.role === 'candidate' ? 'transcript' : 'follow_up',
          content,
        }).catch((requestError) => setError(requestError.message));
      }
      return;
    }
    if (payload.type === 'audio_delta' && payload.data) {
      setOmniSignals((current) => ({ ...current, audioField: true }));
      const cleanData = String(payload.data).startsWith('data:') ? String(payload.data).split(',', 2)[1] : payload.data;
      const binary = atob(cleanData);
      const bytes = new Uint8Array(binary.length);
      for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
      const audioBuffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
      omniAudioChunksRef.current.push(audioBuffer);
      queueOmniPcmPlayback(audioBuffer).catch(() => {
        setOmniMessage('已收到 Qwen-Omni 音频，可点击播放器回放');
      });
      setOmniStatus('speaking');
      setOmniMessage('正在接收并播放 Qwen-Omni 音频');
      return;
    }
    if (payload.type === 'audio_done') {
      playOmniAudioChunks();
      scheduleOmniPlaybackComplete();
    }
  };

  const handleOmniRealtimeMessage = (event) => {
    if (event.data instanceof Blob) {
      event.data.arrayBuffer().then((buffer) => {
        omniAudioChunksRef.current.push(buffer);
        queueOmniPcmPlayback(buffer).catch(() => {
          setOmniMessage('已收到自部署 Qwen-Omni 音频，可点击播放器回放');
        });
      });
      return;
    }

    if (event.data instanceof ArrayBuffer) {
      omniAudioChunksRef.current.push(event.data);
      queueOmniPcmPlayback(event.data).catch(() => {
        setOmniMessage('已收到自部署 Qwen-Omni 音频，可点击播放器回放');
      });
      return;
    }

    try {
      handleOmniPayload(JSON.parse(event.data));
    } catch {
      setOmniMessage('收到一条无法解析的千问 Omni 事件');
    }
  };

  const startOmniRealtimeCall = async () => {
    if (!interviewId || omniStatus === 'connecting') return;

    if (omniStatus === 'listening') {
      finishOmniRecording();
      return;
    }

    if (omniStatus === 'speaking') {
      return;
    }

    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setOmniStatus('error');
      setOmniMessage('当前浏览器不支持 MediaRecorder 录音，无法测试 Omni 语音模式');
      return;
    }

    stopRealtimeCall();
    stopQwenRecognition();
    stopQwenSpeech();
    stopOmniPlayback();
    if (omniAudioUrlRef.current) {
      URL.revokeObjectURL(omniAudioUrlRef.current);
    }
    omniAudioUrlRef.current = '';
    setOmniAudioUrl('');
    setOmniSignals({ text: false, audioField: false, playableAudio: false });
    setVoiceProvider('omni');
    setOmniStatus('connecting');
    setOmniMessage('正在连接 Qwen-Omni API/网关');
    setError('');

    try {
      await ensureOmniAudioContext();
      let socket = omniSocketRef.current;
      if (!socket || socket.readyState === WebSocket.CLOSED || socket.readyState === WebSocket.CLOSING) {
        socket = new WebSocket(apiWsUrl(`/ws/interviews/${interviewId}/qwen/omni-realtime`));
        socket.binaryType = 'arraybuffer';
        omniSocketRef.current = socket;

        await new Promise((resolve, reject) => {
          socket.addEventListener('open', resolve, { once: true });
          socket.addEventListener('error', () => reject(new Error('无法连接千问 Omni 实时网关')), { once: true });
        });

        socket.addEventListener('message', handleOmniRealtimeMessage);
        socket.addEventListener('close', () => {
          if (omniSocketRef.current === socket) {
            omniSocketRef.current = null;
            omniRecorderRef.current?.stop();
            omniStreamRef.current?.getTracks().forEach((track) => track.stop());
            omniRecorderRef.current = null;
            omniStreamRef.current = null;
            setOmniStatus('idle');
            setOmniMessage('千问 Omni 实时网关连接已关闭');
          }
        });
      }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      omniStreamRef.current = stream;
      const preferredType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm';
      const recorder = new MediaRecorder(stream, { mimeType: preferredType });
      omniRecorderRef.current = recorder;
      startOmniRecognition();

      socket.send(JSON.stringify({
        type: 'start',
        mimeType: preferredType,
        sampleRate: 48000,
        currentQuestion,
        activeAgent: currentAgentName,
      }));

      recorder.addEventListener('dataavailable', async (event) => {
        if (event.data.size > 0 && socket.readyState === WebSocket.OPEN) {
          socket.send(await event.data.arrayBuffer());
        }
      });
      recorder.addEventListener('stop', () => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'stop' }));
        }
      });
      recorder.start(250);
      setOmniStatus('listening');
      setOmniMessage('Qwen-Omni 通话已接通，正在发送麦克风音频');
    } catch (requestError) {
      stopOmniRealtimeCall('千问 Omni 自部署通话启动失败');
      setOmniStatus('error');
      setOmniMessage(requestError.message);
      setError(requestError.message);
    }
  };

  const normalizeSdp = (sdp) => {
    const normalized = String(sdp || '').trim().replace(/\r?\n/g, '\r\n');
    return normalized.endsWith('\r\n') ? normalized : `${normalized}\r\n`;
  };

  const extractResponseDoneText = (event) => {
    const directText = event.transcript || event.text || event.output_text;
    if (directText) return String(directText);

    const outputItems = event.response?.output || event.output || [];
    const textParts = [];
    outputItems.forEach((item) => {
      (item.content || []).forEach((part) => {
        const value = part.transcript || part.text || part.output_text;
        if (value) textParts.push(String(value));
      });
    });
    return textParts.join('').trim();
  };

  const sendOmniWebrtcSessionUpdate = (channel) => {
    if (omniWebrtcSessionUpdatedRef.current || !channel || channel.readyState !== 'open') return;
    const sessionUpdate = omniWebrtcSessionUpdateRef.current;
    if (!sessionUpdate) return;

    channel.send(JSON.stringify(sessionUpdate));
    omniWebrtcSessionUpdatedRef.current = true;
    if (omniWebrtcAudioTrackRef.current) {
      omniWebrtcAudioTrackRef.current.enabled = true;
    }
    setOmniStatus('connected');
    setOmniMessage('Qwen-Omni WebRTC 已接通，请直接说话');
    recordOmniWebrtcDiagnostic('session_update_sent', { dataChannel: channel });
  };

  const sendOmniWebrtcOpening = (channel) => {
    if (omniWebrtcOpeningRequestedRef.current || !channel || channel.readyState !== 'open') return;
    channel.send(JSON.stringify({
      event_id: `event_${Date.now()}`,
      type: 'response.create',
      response: {
        modalities: ['text', 'audio'],
        instructions: `请用一句自然的中文电话面试开场白开始，并提出当前问题：${currentQuestion}`,
      },
    }));
    omniWebrtcOpeningRequestedRef.current = true;
  };

  const handleOmniWebrtcEvent = (event, channel) => {
    if (event.type === 'session.created') {
      omniWebrtcDataChannelRef.current = channel;
      recordOmniWebrtcDiagnostic('session_created', { dataChannel: channel });
      sendOmniWebrtcSessionUpdate(channel);
      return;
    }

    if (event.type === 'session.updated') {
      omniWebrtcDataChannelRef.current = channel;
      recordOmniWebrtcDiagnostic('session_updated', { dataChannel: channel });
      sendOmniWebrtcOpening(channel);
      setOmniStatus('connected');
      setOmniMessage('Qwen-Omni 会话配置已生效，请直接说话');
      return;
    }

    if (event.type === 'input_audio_buffer.speech_started') {
      setOmniStatus('listening');
      setOmniMessage('Qwen-Omni 正在聆听候选人回答');
      return;
    }

    if (event.type === 'input_audio_buffer.speech_stopped' || event.type === 'input_audio_buffer.committed') {
      setOmniStatus('connected');
      setOmniMessage('候选人回答已提交，正在生成追问');
      return;
    }

    if (event.type === 'conversation.item.input_audio_transcription.delta') {
      const delta = String(event.delta || '');
      const preview = delta
        ? `${omniWebrtcCandidateTranscriptRef.current}${delta}`
        : `${event.text || ''}${event.stash || ''}`;
      if (preview) {
        omniWebrtcCandidateTranscriptRef.current = preview;
        setAnswer(omniWebrtcCandidateTranscriptRef.current.trim());
        setOmniSignals((current) => ({ ...current, text: true }));
      }
      return;
    }

    if (event.type === 'conversation.item.input_audio_transcription.completed') {
      const content = String(event.transcript || event.text || omniWebrtcCandidateTranscriptRef.current || '').trim();
      omniWebrtcCandidateTranscriptRef.current = '';
      if (content) {
        setAnswer(content);
        setOmniSignals((current) => ({ ...current, text: true }));
        saveRealtimeMessage({
          senderType: 'candidate',
          messageType: 'transcript',
          content,
        }).catch((requestError) => setError(requestError.message));
      }
      return;
    }

    if (
      event.type === 'response.audio_transcript.delta' ||
      event.type === 'response.text.delta' ||
      event.type === 'response.output_text.delta'
    ) {
      const delta = event.delta || event.text || event.transcript || '';
      if (delta) {
        omniWebrtcAgentTranscriptRef.current = `${omniWebrtcAgentTranscriptRef.current}${delta}`;
        setOmniSignals((current) => ({ ...current, text: true }));
      }
      return;
    }

    if (
      event.type === 'response.audio_transcript.done' ||
      event.type === 'response.text.done' ||
      event.type === 'response.output_text.done'
    ) {
      const content = String(event.transcript || event.text || omniWebrtcAgentTranscriptRef.current || '').trim();
      omniWebrtcAgentTranscriptRef.current = '';
      if (content) {
        setOmniSignals((current) => ({ ...current, text: true }));
        saveRealtimeMessage({
          senderType: 'agent',
          messageType: 'follow_up',
          content,
        }).catch((requestError) => setError(requestError.message));
      }
      setOmniStatus('connected');
      setOmniMessage('Qwen-Omni 已完成本轮追问，可继续回答');
      return;
    }

    if (event.type === 'response.created') {
      setOmniStatus('speaking');
      setOmniMessage('Qwen-Omni 正在生成面试官回复');
      return;
    }

    if (event.type === 'response.done') {
      const content = extractResponseDoneText(event);
      if (content) {
        saveRealtimeMessage({
          senderType: 'agent',
          messageType: 'follow_up',
          content,
        }).catch((requestError) => setError(requestError.message));
      }
      setOmniStatus('connected');
      setOmniMessage('Qwen-Omni 本轮回复完成，可继续说话');
      return;
    }

    if (event.type === 'error') {
      const message = event.error?.message || event.message || 'Qwen-Omni WebRTC 会话发生错误';
      recordOmniWebrtcDiagnostic('upstream_error', {
        level: 'error',
        message,
        dataChannel: channel,
        metadata: { error_name: String(event.error?.type || event.error?.code || 'upstream_error') },
      });
      setOmniStatus('error');
      setOmniMessage(message);
      setError(message);
    }
  };

  const handleOmniWebrtcDataChannelMessage = (event, channel) => {
    try {
      const payload = JSON.parse(event.data);
      handleOmniWebrtcEvent(payload, channel);
    } catch {
      setOmniMessage('收到一条无法解析的 Qwen-Omni WebRTC 事件');
    }
  };

  const startOmniWebrtcCall = async () => {
    if (!interviewId || omniStatus === 'connecting') return;

    if (omniStatus === 'connected' || omniStatus === 'listening' || omniStatus === 'speaking') {
      stopOmniWebrtcCall('Qwen-Omni WebRTC 已断开', { resetAudio: true });
      return;
    }

    if (!navigator.mediaDevices?.getUserMedia || !window.RTCPeerConnection) {
      setOmniStatus('error');
      setOmniMessage('当前浏览器不支持 WebRTC 麦克风采集');
      return;
    }

    stopRealtimeCall();
    stopQwenRecognition();
    stopQwenSpeech();
    stopOmniRealtimeCall('已切换到 Qwen 官方 WebRTC');
    stopOmniPlayback();
    if (omniAudioUrlRef.current) {
      URL.revokeObjectURL(omniAudioUrlRef.current);
    }
    omniAudioUrlRef.current = '';
    setOmniAudioUrl('');
    setOmniSignals({ text: false, audioField: false, playableAudio: false });
    setVoiceProvider('omni-webrtc');
    setOmniStatus('connecting');
    setOmniMessage('正在建立 Qwen-Omni WebRTC 直连会话');
    setError('');

    try {
      const peerConnection = new RTCPeerConnection({ iceServers: [] });
      omniWebrtcPeerRef.current = peerConnection;
      omniWebrtcSessionIdRef.current = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      recordOmniWebrtcDiagnostic('call_start_requested', {
        peerConnection,
        metadata: { browser_online: navigator.onLine },
      });

      peerConnection.onconnectionstatechange = () => {
        recordOmniWebrtcDiagnostic('connection_state_changed', {
          level: peerConnection.connectionState === 'failed'
            ? 'error'
            : peerConnection.connectionState === 'disconnected'
              ? 'warning'
              : 'info',
          peerConnection,
          message: `connectionState=${peerConnection.connectionState}`,
        });
        if (peerConnection.connectionState === 'connected') {
          setOmniStatus('connected');
          setOmniMessage('Qwen-Omni WebRTC 已连接，请直接说话');
          return;
        }
        if (peerConnection.connectionState === 'failed') {
          stopOmniWebrtcCall('Qwen-Omni WebRTC 连接失败', { resetAudio: true });
          setOmniStatus('error');
          setError('Qwen-Omni WebRTC 连接失败。');
        }
        if (peerConnection.connectionState === 'disconnected') {
          setOmniMessage('Qwen-Omni WebRTC 连接暂时中断，正在等待恢复');
        }
      };

      peerConnection.oniceconnectionstatechange = () => {
        recordOmniWebrtcDiagnostic('ice_connection_state_changed', {
          level: ['failed', 'disconnected'].includes(peerConnection.iceConnectionState) ? 'warning' : 'info',
          peerConnection,
          message: `iceConnectionState=${peerConnection.iceConnectionState}`,
        });
      };

      peerConnection.onicegatheringstatechange = () => {
        recordOmniWebrtcDiagnostic('ice_gathering_state_changed', {
          peerConnection,
          message: `iceGatheringState=${peerConnection.iceGatheringState}`,
        });
      };

      peerConnection.ontrack = async (event) => {
        const remoteStream = event.streams[0];
        if (!remoteStream) return;
        recordOmniWebrtcDiagnostic('remote_audio_track_received', {
          peerConnection,
          metadata: { remote_track_count: remoteStream.getAudioTracks().length },
        });
        const remoteAudio = document.createElement('audio');
        remoteAudio.autoplay = true;
        remoteAudio.playsInline = true;
        remoteAudio.srcObject = remoteStream;
        remoteAudio.style.display = 'none';
        document.body.appendChild(remoteAudio);
        omniWebrtcRemoteAudioRef.current = remoteAudio;
        setOmniSignals((current) => ({ ...current, audioField: true }));
        try {
          await remoteAudio.play();
          setOmniSignals((current) => ({ ...current, playableAudio: true }));
          recordOmniWebrtcDiagnostic('remote_audio_playing', { peerConnection });
        } catch (playError) {
          recordOmniWebrtcDiagnostic('remote_audio_play_failed', {
            level: 'warning',
            message: playError.message || '浏览器拒绝自动播放远端音频',
            peerConnection,
            metadata: { error_name: playError.name || 'play_error' },
          });
          setOmniMessage('已收到 Qwen-Omni 远端音频轨道，请检查浏览器自动播放权限');
        }
      };

      const attachDataChannel = (channel) => {
        channel.addEventListener('message', (event) => handleOmniWebrtcDataChannelMessage(event, channel));
        channel.addEventListener('open', () => {
          omniWebrtcDataChannelRef.current = channel;
          recordOmniWebrtcDiagnostic('data_channel_opened', {
            dataChannel: channel,
            metadata: { data_channel_label: channel.label || '' },
          });
        });
        channel.addEventListener('close', () => {
          recordOmniWebrtcDiagnostic('data_channel_closed', {
            level: 'warning',
            dataChannel: channel,
            metadata: { data_channel_label: channel.label || '' },
          });
          if (omniWebrtcDataChannelRef.current === channel) {
            omniWebrtcDataChannelRef.current = null;
          }
        });
        channel.addEventListener('error', (channelError) => {
          recordOmniWebrtcDiagnostic('data_channel_error', {
            level: 'error',
            message: channelError.message || 'WebRTC 数据通道发生错误',
            dataChannel: channel,
            metadata: { data_channel_label: channel.label || '' },
          });
        });
      };

      attachDataChannel(peerConnection.createDataChannel('oai-events'));
      peerConnection.ondatachannel = (event) => attachDataChannel(event.channel);

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      omniWebrtcStreamRef.current = stream;
      recordOmniWebrtcDiagnostic('microphone_acquired', {
        peerConnection,
        metadata: { audio_track_count: stream.getAudioTracks().length },
      });
      stream.getAudioTracks().forEach((track) => peerConnection.addTrack(track, stream));
      omniWebrtcAudioSenderRef.current = peerConnection.getSenders().find((sender) => sender.track?.kind === 'audio') || null;
      omniWebrtcAudioTrackRef.current = omniWebrtcAudioSenderRef.current?.track || stream.getAudioTracks()[0] || null;
      if (omniWebrtcAudioTrackRef.current) {
        omniWebrtcAudioTrackRef.current.enabled = false;
      }

      const offer = await peerConnection.createOffer({
        offerToReceiveAudio: true,
        offerToReceiveVideo: false,
      });
      await peerConnection.setLocalDescription(offer);
      const iceGatheringResult = await waitForPeerIceGathering(peerConnection);
      recordOmniWebrtcDiagnostic('local_offer_ready', {
        level: iceGatheringResult === 'timeout' ? 'warning' : 'info',
        peerConnection,
        message: iceGatheringResult === 'timeout'
          ? 'ICE 候选收集等待 3 秒后超时，继续交换 SDP'
          : 'ICE 候选收集完成',
        metadata: { phase: iceGatheringResult },
      });

      const sdpStartedAt = Date.now();
      const data = await apiRequest(`/api/interviews/${interviewId}/qwen/omni-realtime/sdp`, {
        method: 'POST',
        body: JSON.stringify({
          sdp: peerConnection.localDescription.sdp,
          type: peerConnection.localDescription.type,
          currentQuestion,
          activeAgent: currentAgentName,
        }),
      });
      recordOmniWebrtcDiagnostic('sdp_answer_received', {
        peerConnection,
        metadata: { elapsed_ms: Date.now() - sdpStartedAt },
      });

      omniWebrtcSessionUpdateRef.current = data.session_update;
      await peerConnection.setRemoteDescription({
        type: data.answer?.type || 'answer',
        sdp: normalizeSdp(data.answer?.sdp),
      });
      recordOmniWebrtcDiagnostic('remote_description_applied', { peerConnection });
      setOmniMessage(`Qwen-Omni WebRTC SDP 已交换，等待 ${data.model || '实时模型'} 会话创建`);
    } catch (requestError) {
      recordOmniWebrtcDiagnostic('call_start_failed', {
        level: 'error',
        message: requestError.message || 'Qwen-Omni WebRTC 启动失败',
        metadata: {
          error_name: requestError.name || 'start_error',
          browser_online: navigator.onLine,
        },
      });
      stopOmniWebrtcCall('Qwen-Omni WebRTC 启动失败', { resetAudio: true });
      setOmniStatus('error');
      setOmniMessage(requestError.message);
      setError(requestError.message);
    }
  };

  const stopQwenSpeech = () => {
    if (qwenStreamRef.current) {
      qwenStreamRef.current.controller?.abort();
      if (qwenStreamRef.current.objectUrl) {
        URL.revokeObjectURL(qwenStreamRef.current.objectUrl);
      }
    }
    if (qwenAudioRef.current) {
      qwenAudioRef.current.pause();
      if (qwenAudioRef.current.src?.startsWith('blob:')) {
        URL.revokeObjectURL(qwenAudioRef.current.src);
      }
      qwenAudioRef.current.removeAttribute('src');
      qwenAudioRef.current.load();
    }
    qwenStreamRef.current = null;
    qwenAudioRef.current = null;
    setQwenStatus('idle');
    setQwenMessage('千问语音播放已停止');
  };

  const stopQwenRecognition = (message = '千问语音听写已停止') => {
    qwenRecognitionActiveRef.current = false;
    if (qwenRecognitionRef.current) {
      qwenRecognitionRef.current.stop();
    }
    qwenRecognitionRef.current = null;
    if (qwenStatus === 'listening') {
      setQwenStatus('idle');
      setQwenMessage(message);
    }
  };

  const playQwenSpeech = async (text) => {
    const content = String(text || '').trim();
    if (!content || !interviewId) return;
    
    // 自动切换到千问模式（如果未切换）
    if (voiceProvider !== 'qwen') {
      setVoiceProvider('qwen');
      // 等待状态更新
      await new Promise(resolve => setTimeout(resolve, 50));
    }

    stopQwenSpeech();
    setQwenStatus('connecting');
    setQwenMessage('正在请求千问 CosyVoice 流式合成');
    setError('');

    const controller = new AbortController();
    const streamState = { controller, objectUrl: '', mediaSource: null };
    qwenStreamRef.current = streamState;
    const isCurrentStream = () => qwenStreamRef.current === streamState;

    const audio = new Audio();
    qwenAudioRef.current = audio;

    const finishQwenPlayback = (message = '千问语音播放完成') => {
      if (!isCurrentStream()) return;
      if (streamState.objectUrl) {
        URL.revokeObjectURL(streamState.objectUrl);
      }
      qwenStreamRef.current = null;
      qwenAudioRef.current = null;
      setQwenStatus('idle');
      setQwenMessage(message);
    };

    const failQwenPlayback = (message = '千问语音播放失败') => {
      if (!isCurrentStream()) return;
      if (streamState.objectUrl) {
        URL.revokeObjectURL(streamState.objectUrl);
      }
      qwenStreamRef.current = null;
      qwenAudioRef.current = null;
      setQwenStatus('error');
      setQwenMessage(message);
    };

    audio.addEventListener('ended', () => finishQwenPlayback());
    audio.addEventListener('error', () => failQwenPlayback());

    try {
      const response = await apiAudioResponse(`/api/interviews/${interviewId}/qwen/speech`, { text: content, provider: 'auto' }, controller.signal);
      const qwenAudioMimeType = normalizeQwenAudioMimeType(response.headers.get('content-type'));

      if (!response.body || !canStreamAudioWithMediaSource(qwenAudioMimeType)) {
        const blob = await response.blob();
        if (!isCurrentStream()) return;
        streamState.objectUrl = URL.createObjectURL(blob);
        audio.src = streamState.objectUrl;
        setQwenStatus('speaking');
        setQwenMessage('正在播放千问实时语音追问');
        await audio.play();
        return;
      }

      const MediaSourceConstructor = getMediaSourceConstructor();
      const mediaSource = new MediaSourceConstructor();
      streamState.mediaSource = mediaSource;
      streamState.objectUrl = URL.createObjectURL(mediaSource);
      audio.src = streamState.objectUrl;

      await waitForMediaSourceOpen(mediaSource);
      if (!isCurrentStream()) return;

      const sourceBuffer = mediaSource.addSourceBuffer(qwenAudioMimeType);
      const reader = response.body.getReader();
      let playbackStarted = false;
      let resolvePlaybackStart;
      let rejectPlaybackStart;
      const playbackStart = new Promise((resolve, reject) => {
        resolvePlaybackStart = resolve;
        rejectPlaybackStart = reject;
      });

      const streamAudio = async () => {
        try {
          while (isCurrentStream()) {
            const { done, value } = await reader.read();
            if (done) break;
            if (!value?.byteLength || mediaSource.readyState !== 'open') continue;

            await appendAudioChunk(sourceBuffer, value);
            if (!playbackStarted && isCurrentStream()) {
              setQwenStatus('speaking');
              setQwenMessage('正在流式播放千问实时语音追问');
              await audio.play();
              playbackStarted = true;
              resolvePlaybackStart();
            }
          }

          if (isCurrentStream() && mediaSource.readyState === 'open') {
            if (sourceBuffer.updating) {
              await new Promise((resolve) => sourceBuffer.addEventListener('updateend', resolve, { once: true }));
            }
            mediaSource.endOfStream();
          }
          if (!playbackStarted && isCurrentStream()) {
            rejectPlaybackStart(new Error('千问语音没有返回可播放音频。'));
          }
        } catch (streamError) {
          if (streamError.name === 'AbortError') {
            if (!playbackStarted) resolvePlaybackStart();
            return;
          }
          if (!playbackStarted) {
            rejectPlaybackStart(streamError);
          } else {
            failQwenPlayback('千问语音流式播放中断');
            setError(streamError.message);
          }
        } finally {
          reader.releaseLock();
          if (!playbackStarted && !isCurrentStream()) {
            resolvePlaybackStart();
          }
        }
      };

      streamAudio();
      await playbackStart;
    } catch (requestError) {
      if (requestError.name === 'AbortError' || !isCurrentStream()) return;
      failQwenPlayback('千问语音合成失败');
      setQwenStatus('error');
      setQwenMessage('千问语音合成失败，请检查 DASHSCOPE_API_KEY');
      setError(requestError.message);
    }
  };

  const saveRealtimeMessage = async ({ senderType, messageType, content }) => {
    const text = String(content || '').trim();
    if (!text || !interviewId) return;

    const eventKey = `${senderType}:${messageType}:${text}`;
    if (savedRealtimeEventsRef.current.has(eventKey)) return;
    savedRealtimeEventsRef.current.add(eventKey);

    const messageData = await apiRequest(`/api/interviews/${interviewId}/messages`, {
      method: 'POST',
      body: JSON.stringify({
        agent_id: senderType === 'agent' ? activeAgent?.id : undefined,
        sender_type: senderType,
        message_type: messageType,
        content: text,
        transcript_text: text,
      }),
    });

    if (senderType === 'candidate') {
      evaluateAnswerInBackground(messageData.message.id);
    }

    await reloadMessages();
  };

  const handleRealtimeEvent = (event) => {
    if (event.type === 'response.created') {
      if (openaiOpeningPlaybackRef.current) {
        setVoiceMessage('AI 面试官正在朗读当前问题');
      }
      return;
    }

    if (event.type === 'input_audio_buffer.speech_started') {
      setVoiceMessage('正在聆听候选人回答');
      return;
    }

    if (event.type === 'input_audio_buffer.speech_stopped') {
      setVoiceMessage('候选人回答结束，正在生成追问');
      return;
    }

    if (event.type === 'conversation.item.input_audio_transcription.completed') {
      saveRealtimeMessage({
        senderType: 'candidate',
        messageType: 'transcript',
        content: event.transcript,
      }).catch((requestError) => setError(requestError.message));
      return;
    }

    if (event.type === 'response.audio_transcript.done' || event.type === 'response.text.done' || event.type === 'response.output_text.done') {
      if (openaiOpeningPlaybackRef.current) {
        setVoiceMessage('AI 面试官正在收尾，准备聆听回答');
        restoreRealtimeMicrophoneAfterOpening(1200);
      } else {
        saveRealtimeMessage({
          senderType: 'agent',
          messageType: 'follow_up',
          content: event.transcript || event.text,
        }).catch((requestError) => setError(requestError.message));
        setVoiceMessage('AI 面试官已完成本轮追问');
      }
      return;
    }

    if (event.type === 'response.done') {
      restoreRealtimeMicrophoneAfterOpening(600);
      return;
    }

    if (event.type === 'error') {
      const message = event.error?.message || event.message || '实时语音会话发生错误。';
      openaiOpeningPlaybackRef.current = false;
      if (openaiOpeningMicRestoreTimerRef.current) {
        window.clearTimeout(openaiOpeningMicRestoreTimerRef.current);
        openaiOpeningMicRestoreTimerRef.current = null;
      }
      setRealtimeMicrophoneEnabled(false);
      setError(message);
      setVoiceMessage(message);
      setVoiceStatus('error');
    }
  };

  const startRealtimeCall = async () => {
    if (!interviewId || voiceStatus === 'connecting') return;

    if (voiceStatus === 'connected') {
      stopRealtimeCall();
      return;
    }

    if (!navigator.mediaDevices?.getUserMedia) {
      setError('当前浏览器不支持麦克风采集。');
      setVoiceStatus('error');
      return;
    }

    setVoiceStatus('connecting');
    setVoiceMessage('正在请求麦克风权限并建立实时语音连接');
    setError('');

    try {
      const peerConnection = new RTCPeerConnection();
      peerConnectionRef.current = peerConnection;

      const remoteAudio = document.createElement('audio');
      remoteAudio.autoplay = true;
      remoteAudio.playsInline = true;
      remoteAudio.style.display = 'none';
      remoteAudioRef.current = remoteAudio;
      peerConnection.ontrack = (event) => {
        remoteAudio.srcObject = event.streams[0];
        if (!remoteAudio.isConnected) {
          document.body.appendChild(remoteAudio);
        }
        void remoteAudio.play().catch(() => {
          setVoiceMessage('已收到 OpenAI 远端音频，请检查浏览器自动播放权限');
        });
      };

      const localStream = await navigator.mediaDevices.getUserMedia({ audio: OPENAI_REALTIME_AUDIO_CONSTRAINTS });
      localStreamRef.current = localStream;
      setRealtimeMicrophoneEnabled(false);
      localStream.getAudioTracks().forEach((track) => peerConnection.addTrack(track, localStream));

      const dataChannel = peerConnection.createDataChannel('oai-events');
      dataChannelRef.current = dataChannel;
      dataChannel.addEventListener('open', () => {
        openaiOpeningPlaybackRef.current = true;
        setRealtimeMicrophoneEnabled(false);
        setVoiceStatus('connected');
        setVoiceMessage('语音通话已接通，AI 面试官正在开场');
        dataChannel.send(JSON.stringify({
          type: 'response.create',
          response: {
            instructions: buildOpenaiOpeningInstructions(),
          },
        }));
      });
      dataChannel.addEventListener('message', (event) => {
        try {
          handleRealtimeEvent(JSON.parse(event.data));
        } catch {
          setVoiceMessage('收到一条无法解析的实时事件');
        }
      });

      const offer = await peerConnection.createOffer();
      await peerConnection.setLocalDescription(offer);
      const sdpOffer = peerConnection.localDescription?.sdp || offer.sdp;
      if (!sdpOffer?.trim()) {
        throw new Error('浏览器没有生成有效 SDP offer，请重新点击麦克风或检查浏览器 WebRTC 支持。');
      }

      const response = await fetch(apiUrl(`/api/interviews/${interviewId}/realtime/sdp`), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/sdp' },
        body: sdpOffer,
      });
      const responseBody = await response.text();

      if (!response.ok) {
        let message = responseBody || '实时语音连接失败。';
        try {
          message = JSON.parse(responseBody).error || message;
        } catch {
          // Keep the raw server message.
        }
        throw new Error(message);
      }

      await peerConnection.setRemoteDescription({ type: 'answer', sdp: responseBody });
      setVoiceMessage('语音通话连接中，等待数据通道打开');
    } catch (requestError) {
      stopRealtimeCall();
      setVoiceStatus('error');
      const fallbackMessage = requestError.name === 'NotAllowedError'
        ? '麦克风权限被拒绝，请允许浏览器录音后重试'
        : '语音通话连接失败，请检查麦克风权限和 OPENAI_API_KEY';
      const detailMessage = requestError.message || fallbackMessage;
      setError(detailMessage);
      setVoiceMessage(detailMessage);
    }
  };

  const startQwenVoiceConversation = () => {
    if (!interviewId || submitting) return;

    if (qwenStatus === 'listening') {
      stopQwenRecognition('已停止聆听候选人回答');
      return;
    }

    const SpeechRecognition = getSpeechRecognitionConstructor();
    if (!SpeechRecognition) {
      setQwenStatus('error');
      setQwenMessage('当前浏览器不支持语音识别，请使用 Chrome 或先输入文本回答');
      return;
    }

    stopRealtimeCall();
    stopQwenSpeech();
    qwenRecognitionActiveRef.current = true;
    qwenRecognitionSubmittedRef.current = false;
    setVoiceProvider('qwen');
    setQwenStatus('listening');
    setQwenMessage('正在聆听候选人回答，说完后会自动生成追问');
    setError('');

    const recognition = new SpeechRecognition();
    qwenRecognitionRef.current = recognition;
    recognition.lang = 'zh-CN';
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event) => {
      let finalText = '';
      let interimText = '';
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        const transcript = result[0]?.transcript || '';
        if (result.isFinal) {
          finalText += transcript;
        } else {
          interimText += transcript;
        }
      }

      const visibleText = (finalText || interimText).trim();
      if (visibleText) {
        setAnswer(visibleText);
      }

      if (finalText.trim() && !qwenRecognitionSubmittedRef.current) {
        qwenRecognitionSubmittedRef.current = true;
        qwenRecognitionActiveRef.current = false;
        recognition.stop();
        setQwenStatus('connecting');
        setQwenMessage('已识别候选人回答，正在生成追问');
        handleSubmitAnswer(finalText.trim());
      }
    };

    recognition.onerror = (event) => {
      qwenRecognitionActiveRef.current = false;
      qwenRecognitionRef.current = null;
      setQwenStatus('error');
      setQwenMessage(event.error === 'not-allowed' ? '麦克风权限被拒绝，请允许浏览器录音' : '语音识别失败，请重试或输入文本回答');
    };

    recognition.onend = () => {
      qwenRecognitionRef.current = null;
      if (qwenRecognitionActiveRef.current && !qwenRecognitionSubmittedRef.current) {
        qwenRecognitionActiveRef.current = false;
        setQwenStatus('idle');
        setQwenMessage('没有识别到完整回答，请再说一次或输入文本回答');
      }
    };

    recognition.start();
  };

  useEffect(() => {
    let mounted = true;

    const loadInterview = async () => {
      if (!interviewId) {
        setLoading(false);
        return;
      }

      setLoading(true);
      setError('');

      try {
        const [interviewData, agentData, messageData] = await Promise.all([
          apiRequest(`/api/interviews/${interviewId}`),
          apiRequest(`/api/interviews/${interviewId}/agents`),
          apiRequest(`/api/interviews/${interviewId}/messages`),
        ]);

        if (!mounted) return;
        if (interviewData.interview?.status === 'completed') {
          onReportReady(interviewId);
          return;
        }

        setInterview(interviewData.interview);
        setAgents(agentData.agents || []);

        let nextMessages = messageData.messages || [];
        if (nextMessages.length === 0 && agentData.agents?.[0]) {
          let openingQuestion = createInitialQuestion(interviewData.interview, agentData.agents[0]);
          try {
            const opening = await apiRequest(`/api/interviews/${interviewId}/opening-question`, {
              method: 'POST',
            });
            if (opening.question) {
              openingQuestion = opening.question;
            }
          } catch (openingError) {
            setQwenMessage('AI 首问生成失败，已使用本地首问兜底');
          }
          const created = await apiRequest(`/api/interviews/${interviewId}/messages`, {
            method: 'POST',
            body: JSON.stringify({
              agent_id: agentData.agents[0].id,
              sender_type: 'agent',
              message_type: 'question',
              content: openingQuestion,
            }),
          });
          nextMessages = [created.message];
        }

        if (mounted) setMessages(nextMessages);
      } catch (requestError) {
        if (mounted) setError(requestError.message);
      } finally {
        if (mounted) setLoading(false);
      }
    };

    loadInterview();

    return () => {
      mounted = false;
    };
  }, [interviewId]);

  useEffect(() => () => {
    void stopAliyunRtcCall();
    stopRealtimeCall();
    stopOmniRealtimeCall();
    stopOmniWebrtcCall();
    stopQwenRecognition();
    stopQwenSpeech();
  }, []);

  useEffect(() => {
    if (voiceProvider === 'aliyun-rtc') {
      stopOmniRealtimeCall('已切换到阿里云 RTC');
      stopOmniWebrtcCall('已切换到阿里云 RTC');
      stopRealtimeCall();
      stopQwenRecognition();
      stopQwenSpeech();
      setAliyunRtcMessage('点击麦克风加入阿里云 RTC 面试频道');
    } else if (voiceProvider === 'openai') {
      void stopAliyunRtcCall('已切换到 OpenAI 实时通话');
      stopOmniRealtimeCall('已切换到 OpenAI 实时通话');
      stopOmniWebrtcCall('已切换到 OpenAI 实时通话');
      stopQwenRecognition();
      stopQwenSpeech();
      setVoiceMessage('点击麦克风开始真实语音通话');
    } else if (voiceProvider === 'qwen') {
      void stopAliyunRtcCall('已切换到千问 CosyVoice 对话');
      stopOmniRealtimeCall('已切换到千问 CosyVoice 对话');
      stopOmniWebrtcCall('已切换到千问 CosyVoice 对话');
      stopRealtimeCall();
      setQwenMessage('点击麦克风说出回答，或提交文本回答');
    } else if (voiceProvider === 'omni') {
      void stopAliyunRtcCall('已切换到 Qwen-Omni API 录音');
      stopOmniWebrtcCall('已切换到 Qwen-Omni API 录音');
      stopRealtimeCall();
      stopQwenRecognition();
      stopQwenSpeech();
      setOmniMessage('连接 Qwen-Omni API/网关后开始录音提交');
    } else {
      void stopAliyunRtcCall('已切换到 Qwen 官方 WebRTC');
      stopOmniRealtimeCall('已切换到 Qwen 官方 WebRTC');
      stopRealtimeCall();
      stopQwenRecognition();
      stopQwenSpeech();
      setOmniMessage('点击麦克风开始 Qwen 官方 WebRTC 通话');
    }
  }, [voiceProvider]);

  const playQwenSpeechInBackground = (content) => {
    if (voiceProvider !== 'qwen' || !content) return;
    void playQwenSpeech(content).catch((speechError) => {
      setQwenStatus('error');
      setQwenMessage('千问语音合成失败，请检查 DASHSCOPE_API_KEY');
      setError(speechError.message || '千问语音合成失败');
    });
  };

  const speakAliyunRtcMessage = async (message) => {
    const taskId = aliyunRtcAgentTaskRef.current;
    if (voiceProvider !== 'aliyun-rtc' || !taskId || !message?.id) return;
    try {
      await apiRequest(`/api/interviews/${interviewId}/rtc/agent/notify`, {
        method: 'POST',
        body: JSON.stringify({ message_id: message.id }),
      });
    } catch (notifyError) {
      setAliyunRtcMessage(notifyError.message || 'RTC 面试问题播报失败');
      recordAliyunRtcDiagnostic('ai_agent_notify_failed', {
        level: 'warning',
        message: 'RTC AI 智能体问题播报失败',
        metadata: { error_name: notifyError?.name || 'Error' },
      });
    }
  };

  const evaluateAnswerInBackground = (messageId) => {
    let trackedRequest;
    trackedRequest = apiRequest(`/api/interviews/${interviewId}/evaluations`, {
      method: 'POST',
      body: JSON.stringify({ message_id: messageId }),
    })
      .catch((evaluationError) => {
        // A missing per-question evaluation should not hold the candidate on
        // the current screen. The final report still waits for tracked work,
        // and the backend supplies a local fallback for provider failures.
        console.warn('Background answer evaluation failed:', evaluationError);
        return null;
      })
      .finally(() => pendingEvaluationRequestsRef.current.delete(trackedRequest));
    pendingEvaluationRequestsRef.current.add(trackedRequest);
    return trackedRequest;
  };

  const waitForPendingEvaluations = async () => {
    while (pendingEvaluationRequestsRef.current.size) {
      await Promise.all([...pendingEvaluationRequestsRef.current]);
    }
  };

  const handleSubmitAnswer = async (submittedAnswer = null, options = {}) => {
    const content = typeof submittedAnswer === 'string' ? submittedAnswer.trim() : answer.trim();
    if (!content || !interviewId || (submitting && options.source !== 'aliyun_rtc')) return;

    setSubmitting(true);
    setError('');
    setProcessingStage('正在保存本轮回答');

    try {
      const answerData = await apiRequest(`/api/interviews/${interviewId}/messages`, {
        method: 'POST',
        body: JSON.stringify({
          sender_type: 'candidate',
          message_type: 'answer',
          content,
          transcript_text: options.transcriptText || '',
          source: options.source || 'text',
          source_ref: options.sourceRef || '',
        }),
      });
      if (answerData.duplicate) setProcessingStage('本轮语音回答已保存，正在继续生成下一题');
      const evaluationRequest = evaluateAnswerInBackground(answerData.message.id);
      const nextAction = decideNextInterviewAction({
        interview,
        agents,
        messages,
        activeAgent,
        lastAnswer: content,
      });
      if (options.source === 'aliyun_rtc') {
        aliyunRtcNextActionRef.current = nextAction.action;
      }

      if (nextAction.action === 'ask_follow_up' && activeAgent) {
        if (options.source === 'aliyun_rtc') {
          // Alibaba's cloud Agent is already generating and speaking this
          // follow-up. Its final caption is the source of truth and is saved by
          // enqueueAliyunRtcAgentTurn; creating another question here caused
          // the card and the actual voice to diverge.
          setProcessingStage('正在等待 RTC AI 面试官的实际追问');
        } else {
          setProcessingStage('正在生成下一条智能追问');
          let followUpQuestion = nextAction.question;
          try {
            const followUp = await apiRequest(`/api/interviews/${interviewId}/follow-up`, {
              method: 'POST',
              body: JSON.stringify({ last_answer: content }),
            });
            if (followUp.question) {
              followUpQuestion = followUp.question;
            }
          } catch (followUpError) {
            setQwenMessage('Kimi 追问生成失败，已使用本地追问兜底');
          }
          const followUpData = await apiRequest(`/api/interviews/${interviewId}/messages`, {
            method: 'POST',
            body: JSON.stringify({
              agent_id: activeAgent.id,
              sender_type: 'agent',
              message_type: 'follow_up',
              content: followUpQuestion,
            }),
          });
          if (voiceProvider === 'qwen') {
            playQwenSpeechInBackground(followUpData.message.content);
          }
          if (voiceProvider === 'aliyun-rtc') {
            await speakAliyunRtcMessage(followUpData.message);
          }
        }
      }
      if (nextAction.action === 'switch_agent' && activeAgent && nextAction.nextAgent) {
        const prepareNextAgent = async () => {
          setProcessingStage(`正在切换到${nextAction.nextAgent.agent_name || '下一位面试官'}`);
          await apiRequest(`/api/interviews/${interviewId}/messages`, {
            method: 'POST',
            body: JSON.stringify({
              agent_id: activeAgent.id,
              sender_type: 'agent',
              message_type: 'system',
              content: nextAction.closing,
            }),
          });
          await updateAgentStatus(activeAgent, 'completed');
          await updateAgentStatus(nextAction.nextAgent, 'active');
          const openingData = await apiRequest(`/api/interviews/${interviewId}/messages`, {
            method: 'POST',
            body: JSON.stringify({
              agent_id: nextAction.nextAgent.id,
              sender_type: 'agent',
              message_type: 'question',
              content: nextAction.opening,
            }),
          });
          await reloadAgents();
          await reloadMessages();
          if (voiceProvider === 'qwen') playQwenSpeechInBackground(openingData.message.content);
        };
        if (voiceProvider === 'aliyun-rtc' && aliyunRtcSessionRef.current) {
          setAliyunRtcSwitching(true);
          aliyunRtcNextActionRef.current = 'switch_agent';
          // stop increments the generation once; further stop/navigation cancels
          // reconnect. A fresh client also fences out the old Agent's captions.
          const handoffAttempt = aliyunRtcAttemptRef.current + 1;
          try {
            setProcessingStage('正在结束上一位语音面试官的对话');
            await handoffAliyunRtcSession({
              // The answer triggering this handoff is already saved. Do not
              // submit late partial captions as an answer to the new role.
              stop: () => stopAliyunRtcCall('正在切换语音面试官', { flushCandidate: false }),
              prepare: prepareNextAgent,
              isCancelled: () => aliyunRtcAttemptRef.current !== handoffAttempt,
              start: () => startAliyunRtcCall({ afterHandoff: true }),
            });
          } finally {
            setAliyunRtcSwitching(false);
          }
        } else {
          await prepareNextAgent();
        }
      }
      if (nextAction.action === 'finish_interview') {
        setProcessingStage('三轮面试已完成，正在收尾评价');
        await evaluationRequest;
        await waitForPendingEvaluations();
        setProcessingStage('正在生成综合报告');
        await stopAliyunRtcCall('面试已完成');
        stopRealtimeCall();
        stopOmniRealtimeCall();
        stopOmniWebrtcCall();
        stopQwenRecognition();
        stopQwenSpeech();
        if (activeAgent) {
          await apiRequest(`/api/interviews/${interviewId}/messages`, {
            method: 'POST',
            body: JSON.stringify({
              agent_id: activeAgent.id,
              sender_type: 'agent',
              message_type: 'system',
              content: nextAction.closing,
            }),
          });
          await updateAgentStatus(activeAgent, 'completed');
        }
        await apiRequest(`/api/interviews/${interviewId}/finish`, { method: 'POST' });
        onReportReady(interviewId);
        return;
      }
      setAnswer('');
      await reloadMessages();
    } catch (requestError) {
      setError(requestError.message);
      if (options.source === 'aliyun_rtc') throw requestError;
    } finally {
      setSubmitting(false);
      setProcessingStage('');
    }
  };
  handleSubmitAnswerRef.current = handleSubmitAnswer;

  const handleFinish = async () => {
    if (!interviewId || finishing) return;
    setFinishing(true);
    setError('');
    setProcessingStage('正在保存最后一条回答');

    try {
      if (voiceProvider === 'aliyun-rtc') {
        const pendingTurn = aliyunRtcTranscriptAssemblerRef.current.finalize('candidate');
        enqueueAliyunRtcCandidateTurn(pendingTurn);
        await aliyunRtcSubmissionQueueRef.current;
        if (aliyunRtcSubmissionErrorRef.current) throw aliyunRtcSubmissionErrorRef.current;
      }
      await stopAliyunRtcCall();
      stopRealtimeCall();
      stopOmniRealtimeCall();
      stopOmniWebrtcCall();
      stopQwenRecognition();
      stopQwenSpeech();
      const finalMessages = await reloadMessages();
      if (!finalMessages.some((item) => item.sender_type === 'candidate' && String(item.content || '').trim())) {
        throw new Error('未识别到候选人回答，本次面试尚未完成。请重新接通阿里云 RTC 并确认页面出现实时转写后再结束。');
      }
      if (pendingEvaluationRequestsRef.current.size) {
        setProcessingStage('正在完成最后的单题评价');
        await waitForPendingEvaluations();
      }
      setProcessingStage('正在结束面试并生成综合报告');
      await apiRequest(`/api/interviews/${interviewId}/finish`, { method: 'POST' });
      onReportReady(interviewId);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setFinishing(false);
      setProcessingStage('');
    }
  };

  const interviewQuestions = messages.filter((item) => (
    item.sender_type === 'agent'
    && item.message_type !== 'system'
    && String(item.content || '').trim()
  ));
  const savedAnswerCount = messages.filter((item) => (
    item.sender_type === 'candidate' && String(item.content || '').trim()
  )).length;
  const currentQuestionNumber = Math.max(1, interviewQuestions.length);
  const providerStatus = voiceProvider === 'aliyun-rtc'
    ? aliyunRtcStatus
    : voiceProvider === 'openai'
      ? voiceStatus
      : voiceProvider === 'qwen'
        ? qwenStatus
        : omniStatus;
  const voiceConnected = ['connected', 'listening', 'speaking'].includes(providerStatus);
  const voiceAction = voiceProvider === 'aliyun-rtc'
    ? startAliyunRtcCall
    : voiceProvider === 'openai'
      ? startRealtimeCall
      : voiceProvider === 'qwen'
        ? startQwenVoiceConversation
        : voiceProvider === 'omni-webrtc'
          ? startOmniWebrtcCall
          : startOmniRealtimeCall;
  const voiceActionDisabled = finishing
    || aliyunRtcSwitching
    || interview?.status === 'completed'
    || (voiceProvider === 'openai' && voiceStatus === 'connecting')
    || (voiceProvider === 'qwen' && (qwenStatus === 'connecting' || submitting))
    || (!['aliyun-rtc', 'openai', 'qwen'].includes(voiceProvider) && omniStatus === 'connecting');
  const voiceStatusLabel = voiceProvider === 'aliyun-rtc'
    ? aliyunRtcStatus === 'connected' ? '阿里云 RTC 已接通' : aliyunRtcStatus === 'connecting' ? '正在连接阿里云 RTC' : aliyunRtcStatus === 'error' ? '阿里云 RTC 连接失败' : '语音通话待接入'
    : voiceProvider === 'openai'
      ? voiceStatus === 'connected' ? '实时语音已接通' : voiceStatus === 'connecting' ? '正在连接实时语音' : voiceStatus === 'error' ? '实时语音连接失败' : '语音通话待接入'
      : voiceProvider === 'qwen'
        ? qwenStatus === 'listening' ? '正在聆听回答' : qwenStatus === 'speaking' ? '面试官正在提问' : qwenStatus === 'connecting' ? '正在建立语音对话' : qwenStatus === 'error' ? '语音对话失败' : '语音通话待接入'
        : omniStatus === 'listening' ? '正在聆听回答' : omniStatus === 'speaking' ? '面试官正在提问' : omniStatus === 'connecting' ? '正在连接语音通话' : omniStatus === 'error' ? '语音通话连接失败' : omniStatus === 'connected' ? '语音通话已接通' : '语音通话待接入';
  const voiceStatusMessage = voiceProvider === 'aliyun-rtc'
    ? aliyunRtcMessage
    : voiceProvider === 'openai'
      ? voiceMessage
      : voiceProvider === 'qwen'
        ? qwenMessage
        : omniMessage;

  const processingNotice = processingStage && (
    <div className="interview-processing v4-interview-processing" role="status" aria-live="polite">
      <Clock3 size={18} />
      <div>
        <strong>{processingStage}</strong>
        <span>
          已等待 {processingSeconds} 秒
          {processingSeconds >= 12 ? '，AI 服务响应较慢，系统正在继续处理。' : '，请不要重复提交。'}
        </span>
      </div>
    </div>
  );

  if (!interviewId) {
    return (
      <section className="phone-page">
        <div className="empty-state">
          <strong>还没有进行中的面试</strong>
          <span>请先在面试配置页创建一场真实面试。</span>
          <button className="primary-action" onClick={onBackToSetup}>去配置面试</button>
        </div>
      </section>
    );
  }

  if (loading) {
    return <div className="profile-loading">正在读取真实面试、Agent 和消息流</div>;
  }

  return (
    <section className={`phone-page v4-phone-page v4-interview-page ${interviewMode}-mode`}>
      <div className="v4-interview-modebar">
        <span>{interviewMode === 'text' ? '01 / 文字面试' : '02 / VOICE INTERVIEW'}</span>
        <span>{interviewMode === 'text' ? '对话与回答实时保存' : '语音与文字共享本场面试进度'}</span>
      </div>
      <V4PageHeading
        eyebrow={interviewMode === 'text' ? 'A CONVERSATION FOR GROWTH' : ''}
        title={interviewMode === 'text' ? '专注此刻，自信表达。' : '听见问题，从容作答。'}
        description={interviewMode === 'text' ? `${interview?.target_role || '面试练习'} · ${interview?.interview_type || '综合模拟'} · 本场内容实时保存` : undefined}
        action={interviewMode === 'text' ? <button className="v4-outline-action" type="button" onClick={handleFinish} disabled={finishing || submitting}>{finishing ? '正在结束…' : '结束面试 ↗'}</button> : <button className="v4-outline-action" type="button" onClick={() => setInterviewMode('text')}>转聊天框 ▤</button>}
      />
      {error && <div className="profile-message error">{error}</div>}

      {interviewMode === 'text' ? (
        <section className="v4-text-interview" aria-label="文字面试">
          <header className="v4-text-interview-head">
            <div>
              <span className="v4-interview-live-dot" />
              <strong>{currentAgentName}</strong>
              <small>/ {interview?.experience_level || '标准'} · {interview?.interview_type || '综合模拟'}</small>
            </div>
            <button className="v4-outline-action" type="button" onClick={() => setInterviewMode('voice')}>转语音 ♪</button>
          </header>
          <div className="v4-chat-messages">
            {messages.map((item) => {
              const isCandidate = item.sender_type === 'candidate' || item.type === 'candidate';
              const text = item.content || item.text;
              if (!String(text || '').trim()) return null;
              return (
                <article className={`v4-chat-message ${isCandidate ? 'candidate' : 'agent'}`} key={item.id || `${item.created_at}-${text}`}>
                  <div className="v4-chat-avatar">{isCandidate ? '我' : <V4Logo />}</div>
                  <div>
                    <span>{isCandidate ? '我的回答' : item.agent_name || item.speaker || 'Astra 面试官'}</span>
                    <p>{text}</p>
                  </div>
                </article>
              );
            })}
            {!messages.length && <div className="v4-chat-empty">面试官正在准备第一个问题…</div>}
          </div>
          <div className="v4-chat-compose">
            <textarea
              aria-label="输入面试回答"
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              placeholder="输入你的回答，让面试官了解你的思考…"
            />
            <button type="button" onClick={handleSubmitAnswer} disabled={submitting || finishing || !answer.trim()}>
              <span>发送</span><Send size={16} />
            </button>
          </div>
          {processingNotice}
        </section>
      ) : (
        <div className="v4-voice-interview-layout">
          <section className="v4-voice-stage" aria-label="语音面试">
            <div className="v4-voice-stage-top">
              <span><i />独立语音面试</span>
              <span>第 {currentQuestionNumber} 题 · 已保存 {savedAnswerCount} 个回答</span>
            </div>
            <div className={`v4-voice-avatar ${voiceConnected ? 'active' : ''}`}><V4Logo /></div>
            <h2>{currentAgentName}</h2>
            <p className="v4-voice-subtitle">{voiceStatusLabel}</p>
            <div className={`v4-sound-wave ${voiceConnected ? 'active' : ''}`} aria-hidden="true">
              {Array.from({ length: 23 }, (_, index) => <i key={index} style={{ '--wave-index': index }} />)}
            </div>
            <div className="v4-voice-question">
              <span>本轮问题</span>
              <p>{currentQuestion}</p>
            </div>
            <div className="v4-voice-controls" aria-label="语音面试控制">
              <button
                className={voiceConnected ? 'danger' : 'primary'}
                type="button"
                onClick={voiceConnected ? handleFinish : voiceAction}
                disabled={voiceConnected ? finishing || submitting : voiceActionDisabled}
              >
                <span>{voiceConnected || providerStatus === 'connecting' ? <PhoneOff size={21} /> : <Mic size={21} />}</span>
                {voiceConnected ? finishing ? '正在结束' : '结束面试' : providerStatus === 'connecting' ? '取消接入' : '开始回答'}
              </button>
            </div>
            <p className="v4-voice-status-copy">{voiceStatusMessage}</p>
            {processingNotice}

            <details className="v4-live-caption">
              <summary>实时字幕 <span>{messages.length ? `最近 ${Math.min(messages.length, 6)} 条` : '等待语音内容'}</span></summary>
              <div>
                {messages.slice(-6).map((item) => <TranscriptMessage item={item} key={item.id} />)}
                {!messages.length && <p>接通语音后，识别到的问答会显示在这里。</p>}
              </div>
            </details>

            <details className="v4-voice-settings">
              <summary>连接详情 <ChevronDown size={16} /></summary>
              <div className="v4-voice-settings-body">
                <strong>阿里云 RTC 实时语音</strong>
                <small>{voiceStatusLabel}</small>
                {aliyunRtcStatus === 'connected' && <small>远端成员 {aliyunRtcRemoteUsers} · AI 面试官 {aliyunAgentStatus}</small>}
                {aliyunAgentTranscript?.text && <small>{aliyunAgentTranscript.speaker}：{aliyunAgentTranscript.text}{!aliyunAgentTranscript.end ? '…' : ''}</small>}
              </div>
            </details>
          </section>

          <aside className="v4-voice-progress">
            <p className="eyebrow">SESSION NOTES</p>
            <h2>你的语音进度</h2>
            <p>文字与语音共享本场面试，切换模式会保留已保存的回答。</p>
            <div className="v4-agent-progress">
              {agents.map((agent, index) => {
                const name = agent.agent_name || agent.name;
                const active = name === currentAgentName;
                const completed = agent.status === 'completed';
                return (
                  <div className={`v4-agent-progress-item ${active ? 'current' : ''} ${completed ? 'completed' : ''}`} key={agent.id || name}>
                    <span>{completed ? '✓' : String(index + 1).padStart(2, '0')}</span>
                    <div><strong>{name}</strong><small>{active ? '当前面试官' : completed ? '已完成' : '待接入'}</small></div>
                  </div>
                );
              })}
            </div>
            {!agents.length && <div className="v4-voice-tip">面试官队列加载完成后会显示在这里。</div>}
            <div className="v4-voice-tip">点击“开始回答”接入实时语音，说完后系统会保存回答并继续追问。</div>
          </aside>
        </div>
      )}
    </section>
  );
}

function ReportPage({ interviewId, user, onBackToList }) {
  const [reportData, setReportData] = useState(null);
  const [loading, setLoading] = useState(Boolean(interviewId));
  const [error, setError] = useState('');
  const [regenerating, setRegenerating] = useState(false);
  const [retryError, setRetryError] = useState('');

  useEffect(() => {
    let mounted = true;
    let refreshTimer;

    if (!interviewId) {
      setLoading(false);
      return () => {
        mounted = false;
      };
    }

    setLoading(true);
    setError('');
    const loadReport = () => {
      apiRequest(`/api/interviews/${interviewId}/report`)
        .then((data) => {
          if (!mounted) return;
          setReportData(data.report);
          setLoading(false);
          if (data.report?.generation_status === 'queued') {
            refreshTimer = window.setTimeout(loadReport, 2000);
          }
        })
        .catch((requestError) => {
          if (mounted) {
            setError(requestError.message);
            setLoading(false);
          }
        });
    };
    loadReport();

    return () => {
      mounted = false;
      window.clearTimeout(refreshTimer);
    };
  }, [interviewId]);

  const regenerateReport = async () => {
    if (!interviewId || regenerating) return;
    setRegenerating(true);
    setRetryError('');
    try {
      const data = await apiRequest(`/api/interviews/${interviewId}/report`, { method: 'POST' });
      setReportData(data.report);
    } catch (requestError) {
      setRetryError(requestError.message);
    } finally {
      setRegenerating(false);
    }
  };

  if (!interviewId) {
    return (
      <section className="report-page">
        <div className="empty-state">
          <strong>还没有可查看的真实报告</strong>
          <span>完成一场面试后，可在历史记录中查看复盘。</span>
        </div>
      </section>
    );
  }

  if (loading) {
    return <div className="profile-loading">正在读取真实面试报告</div>;
  }

  if (error) {
    return <div className="profile-message error">{error}</div>;
  }

  if (reportData?.generation_status === 'queued') {
    return <div className="v4-report-wait" role="status"><Clock3 size={24} /><strong>面试已结束，正在生成复盘报告</strong><span>报告完成后会自动显示。你可以返回历史记录，稍后再查看。</span>{onBackToList && <button type="button" className="secondary-action" onClick={onBackToList}>返回历史记录</button>}</div>;
  }

  if (reportData?.generation_status === 'failed') {
    return <div className="v4-report-wait" role="alert"><AlertTriangle size={24} /><strong>报告生成失败</strong><span>面试记录已经保存，可以重试生成报告。</span><button type="button" className="primary-action" onClick={regenerateReport} disabled={regenerating}>{regenerating ? '重试中…' : '重新生成报告'}</button>{retryError && <span>{retryError}</span>}</div>;
  }

  const currentReport = reportToViewModel(reportData, user);
  const radarData = currentReport.radar;
  const metrics = currentReport.metrics;
  const reportStatusLabel = !currentReport.hasEvidence
    ? '证据不足，未评分'
    : currentReport.generationStatus === 'degraded'
    ? '已降级为本地规则'
    : currentReport.generationStatus === 'succeeded'
      ? (currentReport.fallback ? '已生成（兜底）' : 'AI 已生成')
      : currentReport.generationStatus;

  const evaluatedInterviewers = currentReport.interviewers.filter((item) => item.evaluated);
  const unevaluatedInterviewers = currentReport.interviewers.filter((item) => !item.evaluated);
  const evidenceNote = reportEvidenceNote(currentReport.timeline);

  return (
    <section className="report-page v4-report-page report-studio">
      <V4PageHeading
        eyebrow="REFLECT. REFINE. REPEAT."
        title="本场面试复盘"
        description="看见这一次的表现，找到下一次的练习方向。"
        action={onBackToList && <button type="button" className="secondary-action" onClick={onBackToList}>← 返回历史记录</button>}
      />

      <header className="report-overview">
        <div className="report-overview-copy">
          <span className="report-kicker">YOUR INTERVIEW REVIEW</span>
          <h2>{currentReport.role}</h2>
          <div className="report-session-meta"><span>{currentReport.candidate}</span><span>{currentReport.generatedAt}</span><span>{reportStatusLabel}</span></div>
          <p className="report-lead">{currentReport.summary}</p>
          <div className="report-evidence-note"><CircleDot size={15} /><span>{evidenceNote}</span></div>
        </div>
        <div className="report-score-card">
          <span>本次作答评分</span>
          <div><strong>{currentReport.hasEvidence ? currentReport.score : '—'}</strong>{currentReport.hasEvidence && <small>/ 100</small>}</div>
          <span className="report-grade">{currentReport.hasEvidence ? `等级 ${currentReport.grade} · ${currentReport.result}` : '证据不足 · 未评分'}</span>
          <p>{currentReport.timeline.length} 条已保存回答 · {evaluatedInterviewers.length} 位面试官有评价</p>
        </div>
      </header>

      {currentReport.fallback && <div className="report-fallback-notice"><div><strong>当前为本地规则评分</strong><span>AI 服务暂时不可用，可保留本次复盘或重新生成。</span></div><button type="button" onClick={regenerateReport} disabled={regenerating}>{regenerating ? '正在重新生成…' : '重新尝试 AI 生成'}</button></div>}
      {retryError && <p className="profile-message error">{retryError}</p>}

      <section className="report-next-steps" aria-label="下一步练习建议">
        <div className="report-section-heading"><div><span className="report-kicker">01 / NEXT STEPS</span><h2>下一次，重点练什么</h2></div><span>从一个具体改进开始</span></div>
        <div className="report-task-grid">
          {currentReport.suggestions.length ? currentReport.suggestions.slice(0, 3).map((item, index) => <article className="report-task" key={index}><span className="report-task-number">0{index + 1}</span><div><h3>{['优先练习', '继续补强', '进一步提升'][index]}</h3><p>{item}</p></div></article>) : <div className="report-no-tasks"><Sparkles size={20} /><p>完成一次包含具体经历、行动和结果的回答，再查看针对性的训练建议。</p></div>}
        </div>
        {currentReport.suggestions.length > 3 && <details className="report-more"><summary>查看其余 {currentReport.suggestions.length - 3} 条建议</summary><ul>{currentReport.suggestions.slice(3).map((item, index) => <li key={index}>{item}</li>)}</ul></details>}
      </section>

      <section className="report-abilities">
        <div className="report-section-heading"><div><span className="report-kicker">02 / ABILITY PROFILE</span><h2>本次能力表现</h2></div><span>结合具体回答阅读评分</span></div>
        <div className="report-ability-grid">
          <div className="report-radar">
            {radarData.length >= 3 ? <CompetencyRadar data={radarData} /> : <div className="report-no-tasks"><BarChart3 size={28} /><p>已评分维度不足，暂不展示能力雷达。</p></div>}
            <p>雷达图仅展示本场报告给出的评分维度。</p>
          </div>
          <div className="report-dimensions">
            <h3>能力维度评分</h3>
            {metrics.length ? <>
              {metrics.slice(0, 4).map((item) => <ProgressMetric key={item.label} item={{ ...item, note: null }} />)}
              {metrics.length > 4 && <details className="report-more"><summary>展开全部 {metrics.length} 个维度</summary><div>{metrics.slice(4).map((item) => <ProgressMetric key={item.label} item={{ ...item, note: null }} />)}</div></details>}
            </> : <p className="report-muted">暂无能力评分，补充作答后再进行评估。</p>}
          </div>
        </div>
      </section>

      <section className="report-feedback-section">
        <div className="report-section-heading"><div><span className="report-kicker">03 / INTERVIEWER NOTES</span><h2>面试官反馈</h2></div><span>{evaluatedInterviewers.length} 位已形成评价</span></div>
        <div className="report-feedback-grid">
          {evaluatedInterviewers.map((item, index) => <article className="report-feedback" key={item.name}><div className="report-feedback-head"><span className="report-agent-icon"><UserRound size={19} /></span><h3>{item.name}</h3><span className="report-feedback-decision">{item.decision}</span></div><p>{item.text}</p></article>)}
          {!evaluatedInterviewers.length && <p className="report-muted">暂无基于单题回答形成的面试官评价。</p>}
        </div>
        {!!unevaluatedInterviewers.length && <div className="report-unassessed"><span>暂无评价</span>{unevaluatedInterviewers.map((item) => <span key={item.name}>{item.name}</span>)}<small>未关联单题评价，不作表现判断。</small></div>}
      </section>

      <section className="report-rounds">
        <div className="report-section-heading"><div><span className="report-kicker">04 / CONVERSATION REVIEW</span><h2>逐题复盘</h2></div><span>共 {currentReport.timeline.length} 题 · 点击展开</span></div>
        <div className="timeline">
          {currentReport.timeline.length ? currentReport.timeline.map((item, index) => <TimelineItem key={item.id || index} item={item} index={index} />) : <p className="report-muted">本场没有已保存的问答记录。</p>}
        </div>
      </section>

      <details className="report-details">
        <summary>报告详情 <span>来源与编号</span><ChevronDown size={15} /></summary>
        <dl><div><dt>报告编号</dt><dd>{currentReport.interviewId}</dd></div><div><dt>生成来源</dt><dd>{currentReport.provider} · {currentReport.model}</dd></div><div><dt>生成状态</dt><dd>{reportStatusLabel}</dd></div>{['approved', 'rejected'].includes(currentReport.reviewStatus) && <div><dt>人工复核</dt><dd>{currentReport.reviewStatus === 'approved' ? '已通过复核' : '复核未通过'}</dd></div>}</dl>
      </details>
    </section>
  );
}

function HistoryPage({ onOpenReport }) {
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let mounted = true;

    apiRequest('/api/reports')
      .then((data) => {
        if (mounted) setReports(data.reports || []);
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

  if (loading) return <div className="profile-loading">正在读取历史报告</div>;
  if (error) return <div className="profile-message error">{error}</div>;

  return (
    <section className="history-page v4-history-page">
      <V4PageHeading eyebrow="EVERY PRACTICE COUNTS" title="我的历史" description="回顾已经完成的面试，查看每一次真实复盘。" />

      {reports.length === 0 ? (
        <div className="empty-state">
          <strong>暂无报告</strong>
          <span>完成一次面试并生成报告后，历史记录会出现在这里。</span>
        </div>
      ) : (
        <div className="history-list" aria-label="历史面试报告">
          {reports.map((item) => (
            <article className="history-item" key={item.id}>
              <div>
                <strong>{item.target_role}</strong>
                <span>{item.interview_type || '综合模拟'} · {formatDateTime(item.updated_at || item.created_at)}</span>
                <span>
                  提问 {item.question_count ?? 0} · 回答 {item.candidate_answer_count ?? 0} · 单轮评价 {item.evaluation_count ?? 0}
                </span>
                <p>{item.summary}</p>
              </div>
              <div className="history-score">
                <strong>{item.generation_status === 'queued' ? '…' : item.has_candidate_answer ? item.total_score : '—'}</strong>
                <span>{item.generation_status === 'queued' ? '生成中' : item.generation_status === 'failed' ? '生成失败' : item.has_candidate_answer ? item.grade : '未评分'}</span>
                <button className="secondary-action" onClick={() => onOpenReport(item.interview_id)}>
                  查看报告
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function formatChartDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

function ScoreTrendChart({ reports }) {
  const data = [...reports].reverse().slice(-8);
  const width = 520;
  const height = 236;
  const padding = { top: 20, right: 20, bottom: 42, left: 38 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const xAt = (index) => padding.left + (data.length === 1 ? chartWidth / 2 : (chartWidth * index) / (data.length - 1));
  const yAt = (value) => padding.top + ((100 - Number(value || 0)) / 100) * chartHeight;
  const points = data.map((item, index) => `${xAt(index)},${yAt(item.total_score)}`).join(' ');

  if (data.length === 0) {
    return (
      <div className="stats-chart-empty">
        <TrendingUp size={28} />
        <strong>完成首次面试后生成趋势</strong>
        <span>系统会保留每次报告的总分，用于观察长期变化。</span>
      </div>
    );
  }

  return (
    <div className="score-trend-wrap">
      <svg className="score-trend-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="历次面试总分趋势图">
        <defs>
          <linearGradient id="scoreTrendArea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#1677ff" stopOpacity="0.2" />
            <stop offset="100%" stopColor="#1677ff" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[50, 75, 100].map((value) => (
          <g key={value}>
            <line
              x1={padding.left}
              y1={yAt(value)}
              x2={width - padding.right}
              y2={yAt(value)}
              className={value === 75 ? 'score-target-line' : 'score-grid-line'}
            />
            <text x={padding.left - 9} y={yAt(value) + 4} textAnchor="end" className="score-axis-label">{value}</text>
          </g>
        ))}
        <text x={width - padding.right} y={yAt(75) - 7} textAnchor="end" className="score-target-label">建议目标 75</text>
        {data.length > 1 && (
          <polygon
            points={`${points} ${xAt(data.length - 1)},${height - padding.bottom} ${xAt(0)},${height - padding.bottom}`}
            className="score-trend-area"
          />
        )}
        {data.length > 1 && <polyline points={points} className="score-trend-line" />}
        {data.map((item, index) => (
          <g key={item.id}>
            <circle cx={xAt(index)} cy={yAt(item.total_score)} r="5" className="score-trend-dot" />
            <text x={xAt(index)} y={yAt(item.total_score) - 12} textAnchor="middle" className="score-value-label">
              {item.total_score}
            </text>
            <text x={xAt(index)} y={height - 15} textAnchor="middle" className="score-date-label">
              {formatChartDate(item.updated_at || item.created_at)}
            </text>
          </g>
        ))}
      </svg>
      <div className="score-trend-legend">
        <span><i className="legend-current" />历次面试得分</span>
        <span><i className="legend-target" />建议目标线</span>
      </div>
    </div>
  );
}

function DimensionChange({ value = 0, emptyLabel = '基线' }) {
  if (value === null || value === undefined || value === '') {
    return <span className="dimension-change stable">{emptyLabel}</span>;
  }
  const change = Number(value) || 0;
  const tone = change > 0 ? 'up' : change < 0 ? 'down' : 'stable';
  return (
    <span className={`dimension-change ${tone}`}>
      {change > 0 ? `+${change}` : change < 0 ? `${change}` : '持平'}
    </span>
  );
}

function StatsPage({ onStartTraining, onOpenReport }) {
  const [stats, setStats] = useState(null);
  const [dimensions, setDimensions] = useState([]);
  const [reports, setReports] = useState([]);
  const [latestReport, setLatestReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let mounted = true;

    const loadStats = async () => {
      try {
        const [statsData, dimensionData, reportsData] = await Promise.all([
          apiRequest('/api/stats/me'),
          apiRequest('/api/stats/me/dimensions'),
          apiRequest('/api/reports'),
        ]);
        if (!mounted) return;
        const reportItems = (reportsData.reports || []).filter(isAbilityReport);
        setStats(statsData.stats);
        setDimensions(dimensionData.dimensions || []);
        setReports(reportItems);

        if (reportItems[0]?.id) {
          const detail = await apiRequest(`/api/reports/${reportItems[0].id}`).catch(() => null);
          if (mounted && detail?.report) setLatestReport(detail.report);
        }
      } catch (requestError) {
        if (mounted) setError(requestError.message);
      } finally {
        if (mounted) setLoading(false);
      }
    };

    loadStats();

    return () => {
      mounted = false;
    };
  }, []);

  if (loading) return <div className="profile-loading">正在读取长期能力画像</div>;
  if (error) return <div className="profile-message error">{error}</div>;

  const validDimensions = dimensions.filter((item) => Number(item.evidence_count) > 0);
  const rankedDimensions = [...validDimensions].sort((a, b) => Number(b.average_score) - Number(a.average_score));
  const strongestDimension = rankedDimensions[0];
  const priorityDimensions = [...validDimensions]
    .sort((a, b) => Number(a.average_score) - Number(b.average_score))
    .slice(0, 3);
  const overallScore = Number(stats?.average_total_score) || 0;
  const completedCount = Number(stats?.completed_interviews) || 0;
  const validReportCount = reports.length;
  const latestScore = reports[0] ? reportScore(reports[0].total_score) : null;
  const previousScore = reports[1] ? reportScore(reports[1].total_score) : null;
  const scoreDelta = latestScore !== null && previousScore !== null ? latestScore - previousScore : null;
  const targetGap = Math.max(0, 75 - overallScore);
  const sampleStatus = abilitySampleStatus(validReportCount);
  const interviewTypeCount = new Set(reports.map((item) => item.interview_type).filter(Boolean)).size;
  const coverage = Math.min(100, Math.round((validDimensions.length / Object.keys(dimensionLabels).length) * 100));
  const latestEvidence = parseJsonValue(latestReport?.timeline_review, [])
    .filter((item) => item.sender_type === 'candidate' && (item.issues || item.suggestions))
    .slice(-2)
    .reverse();
  const reportSuggestions = String(latestReport?.suggestions || '')
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean);
  const trainingTasks = (priorityDimensions.length > 0 ? priorityDimensions : dimensions.slice(0, 3)).map((item, index) => ({
    key: item.key,
    title: `${item.label}专项`,
    score: Number(item.average_score) || 0,
    text: reportSuggestions[index] || dimensionTrainingCopy[item.key] || '围绕近期面试反馈完成一次结构化回答训练。',
  }));
  const heroTitle = validReportCount === 0
    ? '完成首次有效作答，建立你的能力基线'
    : overallScore === 0
      ? '能力基线已建立，继续积累回答证据'
    : targetGap > 0
      ? `距离建议目标还有 ${targetGap} 分`
      : '当前综合表现已达到建议目标';

  return (
    <section className="stats-page v4-stats-page">
      <V4PageHeading eyebrow="A CLEARER PICTURE OF YOU" title="让成长，有迹可循。" description="从已经完成的面试中，查看能力变化与训练方向。" />
      <section className="stats-overview">
        <div className="stats-score-ring" style={{ '--score': overallScore }} aria-label={`综合能力 ${overallScore} 分`}>
          <div>
            <strong>{overallScore}</strong>
            <span>/ 100</span>
          </div>
        </div>
        <div className="stats-overview-copy">
          <p className="eyebrow">LONG-TERM SKILL PROFILE</p>
          <h1>{heroTitle}</h1>
          <p>
            已完成 {completedCount} 场面试，其中 {validReportCount} 份报告包含可评分回答。画像只使用生成成功或本地降级完成的有效报告。
          </p>
          <div className="stats-overview-meta">
            <span><Target size={14} />目标岗位：{stats?.recent_training_focus || '待设置'}</span>
            <span><ShieldCheck size={14} />样本积累：{sampleStatus.label}</span>
            <span><Clock3 size={14} />更新于：{formatChartDate(stats?.updated_at)}</span>
          </div>
        </div>
        <button type="button" className="stats-primary-action" onClick={onStartTraining}>
          <Sparkles size={17} />
          {completedCount > 0 ? '开始专项训练' : '开始首次面试'}
        </button>
      </section>

      <section className="stats-kpi-grid">
        <article>
          <div className="stats-kpi-icon"><CheckCircle2 size={17} /></div>
          <div><span>已完成面试</span><strong>{completedCount} 场</strong></div>
          <small>{validReportCount} 份有效能力报告</small>
        </article>
        <article>
          <div className="stats-kpi-icon"><TrendingUp size={17} /></div>
          <div><span>最近一份有效报告</span><strong>{latestScore === null ? '—' : `${latestScore} 分`}</strong></div>
          <DimensionChange value={scoreDelta} />
        </article>
        <article>
          <div className="stats-kpi-icon"><Award size={17} /></div>
          <div><span>稳定优势</span><strong>{strongestDimension?.label || '待发现'}</strong></div>
          <small>{strongestDimension ? `${strongestDimension.average_score} 分 · ${strongestDimension.evidence_count} 次证据` : '完成面试后识别'}</small>
        </article>
        <article>
          <div className="stats-kpi-icon warning"><Target size={17} /></div>
          <div><span>优先提升</span><strong>{priorityDimensions[0]?.label || '待识别'}</strong></div>
          <small>{priorityDimensions[0] ? `${priorityDimensions[0].average_score} 分 · 建议优先训练` : '暂无有效维度数据'}</small>
        </article>
      </section>

      <section className="stats-main-grid">
        <Card
          title="能力矩阵"
          icon={<BarChart3 size={18} />}
          action={<span className="panel-caption">均分 · 较上次变化 · 目标 75</span>}
          className="ability-matrix-panel"
        >
          {validDimensions.length === 0 ? (
            <div className="stats-chart-empty compact">
              <BarChart3 size={28} />
              <strong>暂无维度数据</strong>
              <span>生成报告后，这里会展示完整能力矩阵。</span>
            </div>
          ) : (
            <div className="ability-matrix">
              {validDimensions.map((item) => (
                <div className="ability-matrix-row" key={item.key}>
                  <div className="ability-row-heading">
                    <div>
                      <strong>{item.label}</strong>
                      <span>{item.evidence_count} 次报告证据</span>
                    </div>
                    <div>
                      <DimensionChange value={item.change} />
                      <strong>{item.average_score}</strong>
                    </div>
                  </div>
                  <div className="ability-score-track" aria-label={`${item.label}平均 ${item.average_score} 分`}>
                    <span className="ability-score-fill" style={{ width: `${item.average_score}%` }} />
                    <i className="ability-target-marker" />
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <div className="stats-side-stack">
          <Card title="成长趋势" icon={<TrendingUp size={18} />} action={<span className="panel-caption">最近 8 场</span>}>
            <ScoreTrendChart reports={reports} />
          </Card>
          <Card title="样本积累情况" icon={<ShieldCheck size={18} />}>
            <div className="data-quality-card">
              <div>
                <span>当前阶段</span>
                <StatusTag tone={sampleStatus.tone}>{sampleStatus.label}</StatusTag>
              </div>
              <div className="data-quality-bar"><i style={{ width: `${sampleStatus.progress}%` }} /></div>
              <dl>
                <div><dt>能力覆盖</dt><dd>{validDimensions.length}/{Object.keys(dimensionLabels).length} 维 · {coverage}%</dd></div>
                <div><dt>有效报告</dt><dd>{validReportCount} 份</dd></div>
                <div><dt>面试类型</dt><dd>{interviewTypeCount} 类</dd></div>
              </dl>
              <p>这里展示样本积累进度，不代表统计置信度。增加有效回答、能力维度和面试类型后，再结合趋势判断。</p>
            </div>
          </Card>
        </div>
      </section>

      <section className="stats-lower-grid">
        <Card title="最近判断依据" icon={<FileText size={18} />} action={latestReport ? <StatusTag tone="blue">可追溯</StatusTag> : null}>
          <div className="evidence-panel">
            {reports[0] ? (
              <>
                <header>
                  <div>
                    <span>最近报告 · {formatChartDate(reports[0].updated_at || reports[0].created_at)}</span>
                    <strong>{reports[0].target_role}</strong>
                  </div>
                  <b>{reports[0].total_score}<small>/100</small></b>
                </header>
                <p className="evidence-summary">{latestReport?.summary || reports[0].summary}</p>
                <div className="evidence-list">
                  {latestEvidence.length > 0 ? latestEvidence.map((item, index) => (
                    <article key={item.message_id || index}>
                      <span>证据 {index + 1}</span>
                      <p>{item.issues || item.suggestions}</p>
                      <small>{item.agent_name || 'AI 面试官'} · 本题 {reportScore(item.score) === null ? '未评分' : `${reportScore(item.score)} 分`}</small>
                    </article>
                  )) : (
                    <article>
                      <span>报告依据</span>
                      <p>当前结论来自最近报告的能力评分、逐题评价和综合摘要。</p>
                      <small>打开完整报告可查看逐题回答与评价</small>
                    </article>
                  )}
                </div>
                <button type="button" className="evidence-action" onClick={() => onOpenReport(reports[0].interview_id)}>
                  查看完整报告 <span>→</span>
                </button>
              </>
            ) : (
              <div className="training-empty">
                <strong>暂无可追溯证据</strong>
                <span>完成面试并生成报告后，可以从画像直接回到原始评价。</span>
              </div>
            )}
          </div>
        </Card>
      </section>
    </section>
  );
}

function V4HomePage({ user, onNavigate, onOpenReport }) {
  const [recent, setRecent] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    let mounted = true;
    apiRequest('/api/reports')
      .then((data) => { if (mounted) setRecent((data.reports || []).slice(0, 3)); })
      .catch((error) => { if (mounted) setLoadError(error.message); })
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, []);

  return (
    <section className="v4-home">
      <div className="v4-home-heading">
        <div><span className="v4-eyebrow">ASTRAINTERVIEW / PERSONAL STUDIO</span><h1>准备，从这里开始。</h1><p>{user.name}，把每一次对话，变成下一次的底气。</p></div>
        <span className="v4-edition">04 <small>FOURTH EDITION</small></span>
      </div>
      <div className="v4-home-grid">
        <section className="v4-stage">
          <div className="v4-stage-top"><span>◉ TELEPHONE INTERVIEW</span><span>01 — PRACTICE</span></div>
          <div className="v4-stage-art"><div className="v4-orbit v4-orbit-one" /><div className="v4-orbit v4-orbit-two" /><V4Logo /></div>
          <div className="v4-stage-copy"><span className="v4-eyebrow">你的下一场，值得认真准备</span><h2>进入状态。<br />让实力被听见。</h2><p>从第一句自我介绍，到最后一次深度追问。<br />在真实场景中练习属于你的表达。</p><button className="v4-primary" type="button" onClick={() => onNavigate('phone-choice')}>开始电话面试 <span>↗</span></button></div>
          <div className="v4-stage-bottom"><span>场景定制 / 多维复盘 / 持续进阶</span><span>AI INTERVIEW STUDIO</span></div>
        </section>
        <div className="v4-home-side">
          <button className="v4-feature" type="button" onClick={() => onNavigate('stats')}><span className="v4-eyebrow">02 / INSIGHTS</span><BarChart3 size={36} /><h2>看见你的能力轮廓</h2><p>优势与短板，都有迹可循。</p><strong>探索能力画像 ↗</strong></button>
          <button className="v4-feature" type="button" onClick={() => onNavigate('me')}><span className="v4-eyebrow">03 / ARCHIVE</span><UserRound size={36} /><h2>积累，属于你的答案</h2><p>一份简历，每一场练习。</p><strong>进入我的空间 ↗</strong></button>
        </div>
      </div>
      <div className="v4-recent-heading"><h2>最近练习</h2><button type="button" onClick={() => onNavigate('report')}>全部记录 ↗</button></div>
      <div className="v4-recent">
        {loading ? <p>正在读取练习记录…</p> : loadError ? <p role="alert">练习记录暂时无法读取：{loadError}</p> : recent.length ? recent.map((item) => (
          <button type="button" className="v4-recent-row" key={item.id} onClick={() => onOpenReport(item.interview_id)}>
            <Phone size={18} /><span><strong>{item.target_role || '面试练习'}</strong><small>{formatDateTime(item.updated_at || item.created_at)}</small></span><em>{item.interview_type || '综合模拟'}</em><b>{item.generation_status === 'queued' ? '…' : item.has_candidate_answer ? item.total_score : '—'}</b><span aria-hidden="true">↗</span>
          </button>
        )) : <p>还没有面试报告。完成第一场面试后，记录会显示在这里。</p>}
      </div>
    </section>
  );
}

function V4PhoneChoicePage({ onSelect }) {
  return (
    <section className="v4-phone-choice">
      <V4PageHeading
        eyebrow="CHOOSE YOUR PACE"
        title="选择一种方式，进入面试。"
        description="一次充分的准备，从适合你的难度开始。"
      />
      <div className="v4-choice-grid">
        <section className="v4-choice-card v4-choice-guided">
          <span className="v4-eyebrow">01 / GUIDED SESSION</span>
          <Phone size={43} strokeWidth={1.25} />
          <h2>默认难度设置</h2>
          <p>让面试官带你进入状态。<br />从基础热身，到更有深度的对话。</p>
          <span className="v4-choice-label">选择难度 ↓</span>
          <div className="v4-choice-levels">
            {difficultyPresets.map((preset, index) => (
              <button key={preset.key} type="button" onClick={() => onSelect(preset.key, 'guided')}>
                <small>0{index + 1}</small> {preset.key === 'normal' ? '中等' : preset.label} ↗
              </button>
            ))}
          </div>
        </section>
        <button className="v4-choice-card v4-choice-custom" type="button" onClick={() => onSelect(defaultDifficultyPreset.key, 'custom')}>
          <span className="v4-eyebrow">02 / PRESSURE CHAMBER</span>
          <span className="v4-choice-badge">挑战模式</span>
          <h2>自主难度设置</h2>
          <p>设定场景，直面追问。<br />把舒适区的边界，再推远一点。</p>
          <strong>构建专属挑战 <span>↗</span></strong>
        </button>
      </div>
    </section>
  );
}

function V4MePage({ onNavigate }) {
  return (
    <section className="v4-me">
      <div className="v4-home-heading"><div><span className="v4-eyebrow">YOUR PERSONAL ARCHIVE</span><h1>我的，每一步积累。</h1><p>简历是起点，练习是过程，成长是你的答案。</p></div></div>
      <div className="v4-me-grid">
        <button type="button" className="v4-feature" onClick={() => onNavigate('resume')}><span className="v4-eyebrow">01 / RESUME</span><FileText size={36} /><h2>我的简历</h2><p>管理简历，查看真实分析结果与就业方向。</p><strong>进入查看 ↗</strong></button>
        <button type="button" className="v4-feature" onClick={() => onNavigate('report')}><span className="v4-eyebrow">02 / HISTORY</span><Phone size={36} /><h2>我的历史</h2><p>回顾面试记录与真实复盘报告。</p><strong>进入查看 ↗</strong></button>
        <button type="button" className="v4-feature" onClick={() => onNavigate('jobcompare')}><span className="v4-eyebrow">03 / CAREER</span><BriefcaseBusiness size={36} /><h2>招聘对比</h2><p>将简历与招聘岗位对比，查看匹配情况和改进建议。</p><strong>开始对比 ↗</strong></button>
      </div>
    </section>
  );
}

function App() {
  const [user, setUser] = useState(undefined);
  const [view, setView] = useState('home');
  const [setupMode, setSetupMode] = useState('guided');
  const [setupPresetKey, setSetupPresetKey] = useState(defaultDifficultyPreset.key);
  const [activeInterviewId, setActiveInterviewId] = useState('');
  const [runningInterviewId, setRunningInterviewId] = useState('');
  const [reportMode, setReportMode] = useState('list');
  const [reportTab, setReportTab] = useState('interview');

  useEffect(() => {
    let mounted = true;

    apiRequest('/api/auth/me')
      .then((data) => {
        if (mounted) {
          setUser(data.user);
        }
        if (!data.user || data.user.mustChangePassword) return null;
        return apiRequest('/api/interviews?status=running')
          .then((interviewData) => {
            if (!mounted) return;
            const runningInterview = interviewData.interviews?.[0];
            if (runningInterview?.id) {
              setActiveInterviewId(runningInterview.id);
              setRunningInterviewId(runningInterview.id);
              setView('phone');
            }
          })
          .catch(() => {});
      })
      .catch(() => {
        if (mounted) {
          setUser(null);
        }
      });

    return () => {
      mounted = false;
    };
  }, []);

  const handleLogout = async () => {
    await apiRequest('/api/auth/logout', { method: 'POST' }).catch(() => {});
    setUser(null);
    setView('home');
    setActiveInterviewId('');
    setRunningInterviewId('');
  };

  const handleStartInterview = (interviewId) => {
    setActiveInterviewId(interviewId);
    setRunningInterviewId(interviewId);
    setView('phone');
  };

  const handleOpenReport = (interviewId) => {
    if (interviewId === runningInterviewId) setRunningInterviewId('');
    setActiveInterviewId(interviewId);
    setReportMode('detail');
    setReportTab('interview');
    setView('report');
  };

  const handleViewChange = (nextView) => {
    if (nextView === 'phone') {
      if (!runningInterviewId) nextView = 'phone-choice';
      else setActiveInterviewId(runningInterviewId);
    }
    if (nextView === 'setup') nextView = 'phone-choice';
    if (nextView === 'report') {
      setReportMode('list');
      setReportTab('interview');
    }
    setView(nextView);
  };

  const handleSelectSetup = (presetKey, mode) => {
    setSetupPresetKey(presetKey);
    setSetupMode(mode);
    setView('setup');
  };

  if (user === undefined) {
    return (
      <main className="auth-shell">
        <section className="auth-loading">
          <div className="brand-mark">
            <ShieldCheck size={22} />
          </div>
          <strong>正在确认登录状态</strong>
          <span>我们会先检查当前浏览器是否已有有效的安全会话。</span>
        </section>
      </main>
    );
  }

  if (!user) {
    return <LoginPage onAuthenticated={setUser} />;
  }

  if (user.mustChangePassword) {
    return <InitialPasswordChangePage user={user} onChanged={setUser} onLogout={handleLogout} />;
  }

  return (
    <main className="app-shell v4-app-shell">
      <div className="workspace-page v4-workspace">
        <div className="topbar">
          <button type="button" className="v4-brand-button" onClick={() => handleViewChange('home')} aria-label="返回面试空间"><V4Brand /></button>
          <span className="v4-breadcrumb">Astrainterview <span>/</span> <b>{({ home: '面试空间', me: '我的', 'phone-choice': '电话面试', setup: setupMode === 'custom' ? '自主难度设置' : '确认面试', phone: '正在面试', resume: '我的简历', jobcompare: '招聘对比', profile: '个人资料', report: '历史报告', stats: '能力画像' })[view]}</b></span>
          <span className="v4-header-note"><i />专注于你的下一次成长</span>
          {runningInterviewId && view !== 'phone' && <button className="v4-continue-link" type="button" onClick={() => handleViewChange('phone')}>继续面试 ↗</button>}
          <button className="topbar-account" type="button" onClick={() => handleViewChange('me')} aria-label="打开我的空间">
            <span>{user.name}</span>
          </button>
          <button className="v4-logout" aria-label="退出登录" onClick={handleLogout}>退出登录 ↗</button>
        </div>

        {view !== 'home' && view !== 'phone' && <div className="v4-page-toolbar"><button type="button" onClick={() => handleViewChange(({ me: 'home', 'phone-choice': 'home', setup: 'phone-choice', stats: 'home', resume: 'me', jobcompare: 'me', profile: 'me', report: 'me' })[view] || 'home')}>← 返回{({ me: '面试空间', 'phone-choice': '面试空间', setup: '难度选择', stats: '面试空间', resume: '我的', jobcompare: '我的', profile: '我的', report: '我的' })[view]}</button><span>面试空间 / {({ me: '我的', 'phone-choice': '电话面试', setup: setupMode === 'custom' ? '自主难度设置' : '确认面试', stats: '能力画像', resume: '我的简历', jobcompare: '招聘对比', profile: '个人资料', report: '历史报告' })[view]}</span></div>}

        {view === 'home' && <V4HomePage user={user} onNavigate={handleViewChange} onOpenReport={handleOpenReport} />}
        {view === 'phone-choice' && <V4PhoneChoicePage onSelect={handleSelectSetup} />}
        {view === 'me' && <V4MePage onNavigate={handleViewChange} />}
        {view === 'setup' && <SetupPage key={`${setupMode}-${setupPresetKey}`} mode={setupMode} presetKey={setupPresetKey} onStart={handleStartInterview} />}
        {view === 'resume' && <ResumeAnalysisPage />}
        {view === 'jobcompare' && <JobComparePage />}
        {view === 'profile' && <ProfilePage user={user} onUserUpdate={setUser} onLogout={handleLogout} />}
        {view === 'phone' && (
          <PhoneInterviewPage
            interviewId={activeInterviewId}
            onReportReady={handleOpenReport}
            onBackToSetup={() => setView('setup')}
          />
        )}
        {view === 'report' && (
          <section className="report-view">
            <div className="report-tabs" role="tablist" aria-label="复盘报告视图切换">
              <button
                type="button"
                role="tab"
                aria-selected={reportTab === 'interview'}
                className={reportTab === 'interview' ? 'active' : ''}
                onClick={() => { setReportTab('interview'); setReportMode('list'); }}
              >
                <FileText size={15} />
                面试报告
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={reportTab === 'jobmatch'}
                className={reportTab === 'jobmatch' ? 'active' : ''}
                onClick={() => setReportTab('jobmatch')}
              >
                <BriefcaseBusiness size={15} />
                岗位对比
              </button>
            </div>
            {reportTab === 'jobmatch' ? (
              <JobMatchHistoryPage />
            ) : reportMode === 'detail' && activeInterviewId ? (
              <ReportPage interviewId={activeInterviewId} user={user} onBackToList={() => setReportMode('list')} />
            ) : (
              <HistoryPage onOpenReport={handleOpenReport} />
            )}
          </section>
        )}
        {view === 'stats' && <StatsPage onStartTraining={() => setView('phone-choice')} onOpenReport={handleOpenReport} />}
        <footer className="v4-footer"><span>© 2026 ASTRAINTERVIEW · 为每一次机会，做好准备</span><span>面试记录与报告来自你的真实账号</span></footer>
      </div>
    </main>
  );
}

const rootElement = document.getElementById('root');
const appRoot = rootElement.__appRoot || createRoot(rootElement);
rootElement.__appRoot = appRoot;
appRoot.render(<App />);
