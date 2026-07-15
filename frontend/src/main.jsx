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
  FileText,
  Headphones,
  History,
  KeyRound,
  LockKeyhole,
  LogIn,
  LogOut,
  Mail,
  Layers3,
  MessageSquareText,
  Mic,
  Phone,
  PhoneOff,
  Radio,
  Save,
  Send,
  ShieldCheck,
  Sparkles,
  Target,
  TrendingUp,
  Upload,
  UserPlus,
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

const authHighlights = [
  {
    title: '个人空间',
    text: '登录后只展示当前用户的简历、模拟面试记录和复盘报告。',
  },
  {
    title: '安全登录',
    text: '正式接入后密码只保存哈希，登录态使用 HttpOnly Cookie。',
  },
  {
    title: '访问隔离',
    text: '每次读取报告、简历和消息都要同时校验 interview_id 与 user_id。',
  },
];

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
};

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
const PASSWORD_RESET_ENABLED = import.meta.env.VITE_PASSWORD_RESET_ENABLED === 'true';
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
      review: item.score ? `本题得分 ${item.score}/100。建议结合报告中的能力维度和训练任务继续优化。` : '本题暂无单独评分。',
      score: Number(item.score) || 0,
      strengths: item.strengths || '',
      issues: item.issues || '',
      suggestion: item.suggestions || '',
    });
    latestQuestion = null;
  });

  return {
    candidate: user?.name || '候选人',
    role: reportData?.target_role || '目标岗位',
    result: recommendationLabels[reportData?.pass_recommendation] || '待判断',
    grade: reportData?.grade || '-',
    score: reportData?.total_score || 0,
    generatedAt: formatDateTime(reportData?.updated_at || reportData?.created_at),
    interviewId: reportData?.interview_id || '-',
    provider: reportData?.provider || 'local',
    model: reportData?.model || 'rules-v1',
    promptVersion: reportData?.prompt_version || 'legacy-local-v1',
    generationStatus: reportData?.generation_status || 'succeeded',
    reviewStatus: reportData?.review_status || 'pending',
    fallback: Boolean(reportData?.fallback),
    generationError: reportData?.generation_error || '',
    summary: reportData?.summary || '暂无报告摘要。',
    suggestions,
    radar: Object.entries(abilityRadar).map(([key, value]) => ({
      subject: dimensionLabels[key] || key,
      value: Number(value) || 0,
    })),
    metrics: Object.entries(abilityRadar).map(([key, value]) => ({
      label: dimensionLabels[key] || key,
      value: Number(value) || 0,
      note: `本场${dimensionLabels[key] || key}表现为 ${Number(value) || 0}/100，综合单题回答证据生成。`,
    })),
    interviewers: agentFeedback.map((item) => ({
      name: item.agent_name,
      decision: item.score >= 80 ? '表现稳定' : item.score >= 70 ? '继续观察' : '需要加强',
      color: item.score >= 80 ? 'green' : item.score >= 70 ? 'blue' : 'amber',
      text: item.comment,
    })),
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
    throw new Error(data.error || '请求失败，请稍后再试。');
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
        <span className="timeline-score">{item.score ? `${item.score} 分` : '待评分'}</span>
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
  const initialResetToken = PASSWORD_RESET_ENABLED
    ? new URLSearchParams(window.location.search).get('reset_token') || ''
    : '';
  const [mode, setMode] = useState(initialResetToken ? 'reset-confirm' : 'login');
  const [resetToken, setResetToken] = useState(initialResetToken);
  const [resetTokenStatus, setResetTokenStatus] = useState(initialResetToken ? 'verifying' : 'idle');
  const [form, setForm] = useState({
    email: '',
    password: '',
    confirmPassword: '',
  });
  const [authMessage, setAuthMessage] = useState('');
  const [authError, setAuthError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!resetToken || mode !== 'reset-confirm' || resetTokenStatus !== 'verifying') return;
    let active = true;
    apiRequest('/api/auth/password-reset/verify', {
      method: 'POST',
      body: JSON.stringify({ token: resetToken }),
    })
      .then(() => {
        if (active) setResetTokenStatus('valid');
      })
      .catch((error) => {
        if (!active) return;
        setResetTokenStatus('invalid');
        setAuthError(error.message);
      });
    return () => {
      active = false;
    };
  }, [mode, resetToken, resetTokenStatus]);

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

  const isRegister = mode === 'register';
  const isResetRequest = mode === 'reset';
  const isResetConfirm = mode === 'reset-confirm';
  const isReset = isResetRequest || isResetConfirm;
  const title = isResetConfirm
    ? '设置新的登录密码'
    : isResetRequest
      ? '重置登录密码'
      : isRegister
        ? '创建个人训练账号'
        : '登录个人面试空间';
  const subtitle = isResetConfirm
    ? '重置链接只能使用一次；完成后，所有旧设备上的登录状态都会失效。'
    : isResetRequest
      ? '输入注册邮箱后，系统会发送一次性的密码重置链接。'
      : '你的简历、模拟面试记录和复盘报告会保存在个人空间中，仅你可见。';

  const handleSubmit = async (event) => {
    event.preventDefault();
    setAuthMessage('');
    setAuthError('');

    if ((isRegister || isResetConfirm) && form.password !== form.confirmPassword) {
      setAuthError('两次输入的密码不一致。');
      return;
    }

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

      const endpoint = isRegister ? '/api/auth/register' : '/api/auth/login';
      const data = await apiRequest(endpoint, {
        method: 'POST',
        body: JSON.stringify({
          email: form.email,
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
    <main className="auth-shell">
      <section className="auth-page">
        <div className="auth-brand-panel">
          <div className="auth-brand-head">
            <div className="brand-mark">
              <ShieldCheck size={22} />
            </div>
            <div>
              <strong>AI Interview Intelligence</strong>
              <span>多 Agent 面试评估系统</span>
            </div>
          </div>

          <div className="auth-copy">
            <p className="eyebrow">Private Interview Workspace</p>
            <h1>进入你的个人面试训练档案</h1>
            <p>
              从登录开始建立清晰的数据边界：每位用户只能看到自己的简历、训练记录、AI 面试官配置和复盘报告。
            </p>
          </div>

          <div className="auth-highlight-list">
            {authHighlights.map((item) => (
              <div className="auth-highlight" key={item.title}>
                <CheckCircle2 size={17} />
                <div>
                  <strong>{item.title}</strong>
                  <span>{item.text}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <form className="auth-card" onSubmit={handleSubmit}>
          <div className="auth-card-head">
            <div className="auth-icon">
              {isReset ? <KeyRound size={22} /> : isRegister ? <UserPlus size={22} /> : <LogIn size={22} />}
            </div>
            <div>
              <h2>{title}</h2>
              <p>{subtitle}</p>
            </div>
          </div>

          <div className="auth-tabs" aria-label="登录模式切换">
            <button type="button" className={mode === 'login' ? 'active' : ''} onClick={() => switchMode('login')}>
              登录
            </button>
            <button
              type="button"
              className={mode === 'register' ? 'active' : ''}
              onClick={() => switchMode('register')}
            >
              注册
            </button>
          </div>

          <div className="auth-form">
            {!isResetConfirm && (
              <AuthInput
                icon={<Mail size={17} />}
                label="邮箱"
                type="email"
                value={form.email}
                onChange={(value) => updateForm('email', value)}
                placeholder="name@example.com"
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
              {PASSWORD_RESET_ENABLED && (
                <button type="button" onClick={() => switchMode('reset')}>
                  忘记密码
                </button>
              )}
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
          {authMessage && <p className="auth-alert success">{authMessage}</p>}

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
                    : '登录并进入工作台'}
          </button>

          <p className="auth-notice">
            当前已接入后端登录与 MySQL 数据库；密码使用加盐哈希保存，登录态通过 HttpOnly Cookie 维护。
          </p>
        </form>
      </section>
    </main>
  );
}

function ViewSwitch({ view, onChange }) {
  return (
    <div className="view-switch" aria-label="页面视图切换">
      <button className={view === 'setup' ? 'active' : ''} onClick={() => onChange('setup')}>
        <Layers3 size={15} />
        面试配置
      </button>
      <button className={view === 'resume' ? 'active' : ''} onClick={() => onChange('resume')}>
        <Upload size={15} />
        简历分析
      </button>
      <button className={view === 'phone' ? 'active' : ''} onClick={() => onChange('phone')}>
        <Phone size={15} />
        电话面试
      </button>
      <button className={view === 'report' ? 'active' : ''} onClick={() => onChange('report')}>
        <FileText size={15} />
        复盘报告
      </button>
      <button className={view === 'history' ? 'active' : ''} onClick={() => onChange('history')}>
        <History size={15} />
        历史记录
      </button>
      <button className={view === 'stats' ? 'active' : ''} onClick={() => onChange('stats')}>
        <TrendingUp size={15} />
        能力画像
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
    <form className="profile-page" onSubmit={handleSave}>
      <section className="profile-hero">
        <div className="profile-identity">
          <div className="profile-avatar">
            {profile.avatar_url ? <img src={profile.avatar_url} alt="" /> : <UserRound size={34} />}
          </div>
          <div>
            <p className="eyebrow">Personal Interview Profile</p>
            <h1>个人面试训练档案</h1>
            <span>你填写的信息会用于生成更贴近目标岗位的模拟面试官和复盘建议。</span>
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

function ResumeAnalysisPage({ onUseSetup }) {
  const [resumeText, setResumeText] = useState(
    '负责过中后台性能优化、低代码表单搭建和组件库治理，希望重点练习项目深挖与架构表达。'
  );
  const [fileName, setFileName] = useState('');
  const [analysis, setAnalysis] = useState(() => buildResumeAnalysis(resumeText));
  const [analyzed, setAnalyzed] = useState(true);
  const [profile, setProfile] = useState(null);
  const [structuredAnalysis, setStructuredAnalysis] = useState(null);
  const [analysisMeta, setAnalysisMeta] = useState(null);
  const [customRole, setCustomRole] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [uploading, setUploading] = useState(false);

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
          if (analysisData.stale) {
            analysisData = await apiRequest('/api/profile/resume-analysis', { method: 'POST' });
          }
          if (!mounted) return;
          const savedRecord = analysisData.resume_analysis;
          const savedAnalysis = savedRecord?.analysis;
          if (savedAnalysis) {
            setAnalysisMeta(normalizeResumeAnalysisMeta(savedRecord));
            setStructuredAnalysis(savedAnalysis);
            setAnalysis(buildResumeAnalysisFromStructured(savedResume, currentProfile.resume_filename, savedAnalysis, currentProfile.target_role));
          }
        }
      })
      .catch(() => {
        if (mounted) {
          setMessage('当前先使用页面内文本进行分析，登录资料读取失败时不会影响本次预览。');
        }
      });

    return () => {
      mounted = false;
    };
  }, []);

  const handleFileChange = async (event) => {
    const file = event.target.files?.[0];
    setFileName(file?.name || '');
    setMessage('');
    setError('');

    if (!file) {
      setAnalyzed(false);
      return;
    }

    const extension = file.name.split('.').pop()?.toLowerCase();
    const readableTextExtensions = new Set(['txt', 'md', 'json']);

    if (readableTextExtensions.has(extension)) {
      const reader = new FileReader();
      reader.onload = () => {
        const nextText = String(reader.result || '').trim();
        setResumeText(nextText);
        setAnalysis(buildResumeAnalysis(nextText, file.name));
        setStructuredAnalysis(null);
        setAnalysisMeta(null);
        setAnalyzed(true);
        setMessage(`已读取 ${file.name}，并刷新分析结果。`);
      };
      reader.onerror = () => {
        setError('文件读取失败，请重新选择文件或直接粘贴简历文本。');
      };
      reader.readAsText(file);
      return;
    }

    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const response = await fetch(apiUrl('/api/profile/resume-upload'), {
        method: 'POST',
        credentials: 'include',
        body: formData,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || data.error || '文件解析失败，请稍后再试。');
      }

      const nextText = String(data.text || '').trim();
      if (!nextText) {
        throw new Error('文件内容为空或未能提取到文本，请检查文件或直接粘贴简历文本。');
      }

      setResumeText(nextText);
      setAnalysis(buildResumeAnalysis(nextText, file.name));
      setStructuredAnalysis(null);
      setAnalysisMeta(null);
      setAnalyzed(true);
      setProfile({ ...defaultProfile, ...(data.profile || profile || {}) });
      setMessage(`已解析 ${file.name}（${data.char_count} 字符${data.truncated ? '，已保留前 12000 字符' : ''}），并刷新分析结果。`);
    } catch (uploadError) {
      setError(uploadError.message);
      setAnalyzed(false);
    } finally {
      setUploading(false);
    }
  };

  const handleAnalyze = async () => {
    setAnalyzing(true);
    setMessage('');
    setError('');

    const nextAnalysis = buildResumeAnalysis(resumeText, fileName);
    setAnalysis(nextAnalysis);
    setAnalyzed(true);

    try {
      const currentProfile = profile || defaultProfile;
      const data = await apiRequest('/api/profile', {
        method: 'PUT',
        body: JSON.stringify({
          ...currentProfile,
          resume_text: resumeText,
          project_experience: currentProfile.project_experience || resumeText,
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
      setAnalysis(buildResumeAnalysisFromStructured(resumeText, fileName, nextStructuredAnalysis, savedProfile.target_role));
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

    setMessage('');
    setError('');
    try {
      const currentProfile = profile || defaultProfile;
      const data = await apiRequest('/api/profile', {
        method: 'PUT',
        body: JSON.stringify({
          ...currentProfile,
          target_role: nextRole,
          resume_text: resumeText,
          project_experience: currentProfile.project_experience || resumeText,
        }),
      });
      const savedProfile = { ...defaultProfile, ...(data.profile || {}) };
      setProfile(savedProfile);
      setCustomRole(nextRole);
      setAnalysis(buildResumeAnalysisFromStructured(resumeText, fileName, structuredAnalysis, nextRole));
      setMessage(`已确认“${nextRole}”为本阶段训练目标，面试配置会优先使用该方向。`);
    } catch (requestError) {
      setError(requestError.message);
    }
  };

  return (
    <section className="resume-page">
      <div className="resume-hero">
        <div>
          <p className="eyebrow">P0 Resume Intelligence</p>
          <h1>简历上传与分析</h1>
          <span>
            先解析真实简历，再生成岗位匹配、亮点风险、高概率追问和推荐面试配置，让后续多 Agent 面试更贴近候选人经历。
          </span>
        </div>
        <button className="primary-action" onClick={handleAnalyze} disabled={analyzing || uploading}>
          <Sparkles size={17} />
          {analyzing ? '分析中' : '开始分析'}
        </button>
      </div>

      {(message || error) && (
        <div className={`profile-message ${error ? 'error' : 'success'}`}>{error || message}</div>
      )}

      {analysisMeta && (
        <div className={`analysis-source-note ${analysisMeta.isLocal ? 'local' : 'ai'}`}>
          <div>
            <strong>{analysisMeta.isLocal ? '当前使用本地规则辅助分析' : `当前使用 ${analysisMeta.provider.toUpperCase()} AI 语义分析`}</strong>
            <span>
              {analysisMeta.isLocal
                ? '分数表示简历证据命中程度，不等同于真实录用概率。'
                : '结果由模型结合专业、技能、项目职责与成果进行结构化判断。'}
            </span>
          </div>
          {analysisMeta.errorSummary && <small>{analysisMeta.errorSummary}，系统已自动降级。</small>}
        </div>
      )}

      <section className="resume-grid">
        <Card title="上传或粘贴简历" icon={<Upload size={18} />}>
          <div className="resume-input-panel">
            <label className="resume-upload-box">
              <Upload size={24} />
              <strong>{uploading ? '解析中...' : fileName || '上传简历文件'}</strong>
              <span>支持 txt、md、json、PDF、Word 文档；图片 OCR 需部署环境安装 Tesseract。</span>
              <input type="file" accept=".txt,.md,.json,.pdf,.doc,.docx,.png,.jpg,.jpeg" onChange={handleFileChange} disabled={uploading} />
            </label>

            <label className="brief-field">
              <span>粘贴简历 / 项目简介</span>
              <textarea value={resumeText} onChange={(event) => {
                setResumeText(event.target.value);
                setAnalyzed(false);
                setMessage('');
                setError('');
              }} />
            </label>

            <div className="privacy-note">
              <ShieldCheck size={16} />
              <span>简历分析结果会用于生成本场面试官、追问路线和复盘维度，默认只在当前用户个人空间内可见。</span>
            </div>
          </div>
        </Card>

        <Card title="岗位匹配结果" icon={<Target size={18} />}>
          <div className="match-card">
            <div className="match-score">
              <span>{analysisMeta?.isLocal ? '规则证据分' : (analysis.scoreLabel || '匹配度')}</span>
              <strong>{analysis.matchScore}</strong>
              <small>/100</small>
            </div>
            <div className="match-copy">
              <StatusTag tone="green">综合推荐第 1 方向</StatusTag>
              {analysis.directions?.[0]?.catalogStatus === 'matched'
                ? <StatusTag tone="blue">正式目录岗位 · {analysis.directions[0].catalogJobName}</StatusTag>
                : <StatusTag tone="amber">目录外 AI 建议 · 已进入待审核池</StatusTag>}
              <h2>{analysis.targetRole}</h2>
              <div className="confirmed-role-note">
                <span>学生已确认目标</span>
                <strong>{profile?.target_role || '尚未确认'}</strong>
              </div>
              <p>{analysis.summary}</p>
            </div>
          </div>
        </Card>
      </section>

      <section className="direction-panel">
        <Card title="推荐就业方向（由学生确认）" icon={<Target size={18} />}>
          {analysis.directions?.length ? (
            <div className="direction-grid">
              {analysis.directions.map((direction, index) => {
                const confirmed = profile?.target_role === direction.name;
                return (
                  <article className={`direction-card ${confirmed ? 'confirmed' : ''}`} key={direction.name}>
                    <div className="direction-card-head">
                      <StatusTag tone={index === 0 ? 'green' : 'blue'}>推荐 {index + 1}</StatusTag>
                      <strong>{direction.score} 分</strong>
                    </div>
                    <h3>{direction.name}</h3>
                    <div className={`catalog-match-note ${direction.catalogStatus}`}>
                      <strong>{direction.catalogStatus === 'matched' ? '正式目录岗位' : '目录外 AI 建议'}</strong>
                      <span>
                        {direction.catalogStatus === 'matched'
                          ? `已关联 ${direction.catalogJobName} · ${direction.abilityMatrix.length} 项正式能力要求`
                          : `${direction.nearestCatalogJobName ? `最接近：${direction.nearestCatalogJobName}；` : ''}已提交管理端待审核，当前分数来自 AI 语义分析`}
                      </span>
                    </div>
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
                      disabled={confirmed}
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
              <button type="button" className="secondary-action" onClick={() => handleConfirmDirection(customRole)}>
                确认自定义方向
              </button>
            </div>
          </div>
        </Card>
      </section>

      <section className="analysis-grid">
        <Card title="结构化解析" icon={<FileText size={18} />}>
          <div className="parsed-list">
            {analysis.parsedSections.map((item) => (
              <div key={item.label}>
                <strong>{item.label}</strong>
                <span>{item.value}</span>
              </div>
            ))}
          </div>
        </Card>

        <Card title="简历亮点" icon={<Award size={18} />}>
          <InsightList items={analysis.highlights} tone="green" />
        </Card>

        <Card title="风险点与短板" icon={<AlertTriangle size={18} />}>
          <InsightList items={analysis.risks} tone="amber" />
        </Card>

        <Card title="高概率面试题" icon={<MessageSquareText size={18} />}>
          <InsightList items={analysis.questions} tone="blue" />
        </Card>
      </section>

      <section className="resume-bottom-grid">
        <Card title="简历优化建议" icon={<Wrench size={18} />}>
          <InsightList items={analysis.suggestions} tone="blue" />
        </Card>

        <Card title="推荐面试配置" icon={<Layers3 size={18} />}>
          <div className="recommended-setup">
            {analysis.recommendedSetup.map((item) => (
              <div key={item.label}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
              </div>
            ))}
            <button className="primary-action" onClick={onUseSetup}>
              生成本场面试配置
            </button>
          </div>
        </Card>
      </section>

      {!analyzed && <div className="resume-draft-note">简历内容已更新，点击“开始分析”刷新分析结果。</div>}
    </section>
  );
}

function InsightList({ items, tone }) {
  return (
    <div className="insight-list">
      {items.map((item, index) => (
        <div className={`insight-item ${tone}`} key={item}>
          <span>{String(index + 1).padStart(2, '0')}</span>
          <p>{item}</p>
        </div>
      ))}
    </div>
  );
}

function SetupPage({ onStart }) {
  const defaultBrief = '';
  const [form, setForm] = useState({
    role: '',
    level: setupOptions.levels[2],
    interviewType: setupOptions.interviewTypes[1],
    companyScene: setupOptions.companyScenes[0],
    focusArea: setupOptions.focusAreas[0],
    intensity: setupOptions.intensity[1],
    style: setupOptions.styles[2],
    brief: defaultBrief,
  });
  const [loadingProfile, setLoadingProfile] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');
  const [recommendedRoles, setRecommendedRoles] = useState([]);
  const briefTouchedRef = useRef(false);

  useEffect(() => {
    let mounted = true;

    async function loadSetupDefaults() {
      try {
        const data = await apiRequest('/api/profile');
        if (!mounted) return;
        const profile = data.profile || {};
        const profileBrief = profile.project_experience || profile.resume_text || defaultBrief;

        setForm((current) => ({
          ...current,
          role: profile.target_role || current.role,
          level: profile.experience_level || current.level,
          interviewType: profile.preferred_interview_type || current.interviewType,
          intensity: profile.preferred_difficulty || current.intensity,
          style: profile.preferred_interviewer_style || current.style,
          brief: briefTouchedRef.current ? current.brief : profileBrief,
        }));

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

  const interviewerProfile = buildInterviewerProfile(form);

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
        <button className="primary-action" onClick={handleStart} disabled={starting || loadingProfile}>
          <Phone size={17} />
          {starting ? '创建中' : '开始电话面试'}
        </button>
      </div>

      {error && <div className="profile-message error">{error}</div>}

      <section className="setup-grid">
        <Card title="面试前配置" icon={<Layers3 size={18} />}>
          <div className="setup-form">
            <div className="role-input-group">
              <label htmlFor="setup-target-role">目标岗位</label>
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
  const [voiceProvider, setVoiceProvider] = useState('omni-webrtc');
  const [voiceStatus, setVoiceStatus] = useState('idle');
  const [voiceMessage, setVoiceMessage] = useState('点击麦克风开始真实语音通话');
  const [qwenStatus, setQwenStatus] = useState('idle');
  const [qwenMessage, setQwenMessage] = useState('提交文本回答后自动播放千问语音追问');
  const [omniStatus, setOmniStatus] = useState('idle');
  const [omniMessage, setOmniMessage] = useState('连接 Qwen-Omni API、网关或官方 WebRTC 后开始通话');
  const [omniAudioUrl, setOmniAudioUrl] = useState('');
  const [omniSignals, setOmniSignals] = useState({ text: false, audioField: false, playableAudio: false });

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

  const activeAgent = agents.find((agent) => agent.status === 'active') || agents.find((agent) => agent.status !== 'completed') || agents[0] || null;
  const currentAgentName = activeAgent?.agent_name || liveInterview.currentAgent;
  const currentQuestion =
    [...messages].reverse().find((message) => message.sender_type === 'agent')?.content ||
    createInitialQuestion(interview, activeAgent);

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
    if (connection.iceGatheringState === 'complete') return Promise.resolve();
    return new Promise((resolve) => {
      const timeoutId = window.setTimeout(resolve, 3000);
      connection.addEventListener('icegatheringstatechange', () => {
        if (connection.iceGatheringState === 'complete') {
          window.clearTimeout(timeoutId);
          resolve();
        }
      });
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
      sendOmniWebrtcSessionUpdate(channel);
      return;
    }

    if (event.type === 'session.updated') {
      omniWebrtcDataChannelRef.current = channel;
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

      peerConnection.onconnectionstatechange = () => {
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

      peerConnection.ontrack = async (event) => {
        const remoteStream = event.streams[0];
        if (!remoteStream) return;
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
        } catch {
          setOmniMessage('已收到 Qwen-Omni 远端音频轨道，请检查浏览器自动播放权限');
        }
      };

      const attachDataChannel = (channel) => {
        channel.addEventListener('message', (event) => handleOmniWebrtcDataChannelMessage(event, channel));
        channel.addEventListener('close', () => {
          if (omniWebrtcDataChannelRef.current === channel) {
            omniWebrtcDataChannelRef.current = null;
          }
        });
      };

      attachDataChannel(peerConnection.createDataChannel('oai-events'));
      peerConnection.ondatachannel = (event) => attachDataChannel(event.channel);

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      omniWebrtcStreamRef.current = stream;
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
      await waitForPeerIceGathering(peerConnection);

      const data = await apiRequest(`/api/interviews/${interviewId}/qwen/omni-realtime/sdp`, {
        method: 'POST',
        body: JSON.stringify({
          sdp: peerConnection.localDescription.sdp,
          type: peerConnection.localDescription.type,
          currentQuestion,
          activeAgent: currentAgentName,
        }),
      });

      omniWebrtcSessionUpdateRef.current = data.session_update;
      await peerConnection.setRemoteDescription({
        type: data.answer?.type || 'answer',
        sdp: normalizeSdp(data.answer?.sdp),
      });
      setOmniMessage(`Qwen-Omni WebRTC SDP 已交换，等待 ${data.model || '实时模型'} 会话创建`);
    } catch (requestError) {
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
      await apiRequest(`/api/interviews/${interviewId}/evaluations`, {
        method: 'POST',
        body: JSON.stringify({ message_id: messageData.message.id }),
      }).catch(() => {});
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
    stopRealtimeCall();
    stopOmniRealtimeCall();
    stopOmniWebrtcCall();
    stopQwenRecognition();
    stopQwenSpeech();
  }, []);

  useEffect(() => {
    if (voiceProvider === 'openai') {
      stopOmniRealtimeCall('已切换到 OpenAI 实时通话');
      stopOmniWebrtcCall('已切换到 OpenAI 实时通话');
      stopQwenRecognition();
      stopQwenSpeech();
      setVoiceMessage('点击麦克风开始真实语音通话');
    } else if (voiceProvider === 'qwen') {
      stopOmniRealtimeCall('已切换到千问 CosyVoice 对话');
      stopOmniWebrtcCall('已切换到千问 CosyVoice 对话');
      stopRealtimeCall();
      setQwenMessage('点击麦克风说出回答，或提交文本回答');
    } else if (voiceProvider === 'omni') {
      stopOmniWebrtcCall('已切换到 Qwen-Omni API 录音');
      stopRealtimeCall();
      stopQwenRecognition();
      stopQwenSpeech();
      setOmniMessage('连接 Qwen-Omni API/网关后开始录音提交');
    } else {
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

  const handleSubmitAnswer = async (submittedAnswer = null) => {
    const content = typeof submittedAnswer === 'string' ? submittedAnswer.trim() : answer.trim();
    if (!content || !interviewId || submitting) return;

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
        }),
      });
      setProcessingStage('正在生成本题评价');
      await apiRequest(`/api/interviews/${interviewId}/evaluations`, {
        method: 'POST',
        body: JSON.stringify({ message_id: answerData.message.id }),
      });
      const nextAction = decideNextInterviewAction({
        interview,
        agents,
        messages,
        activeAgent,
        lastAnswer: content,
      });

      if (nextAction.action === 'ask_follow_up' && activeAgent) {
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
      }
      if (nextAction.action === 'switch_agent' && activeAgent && nextAction.nextAgent) {
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
        if (voiceProvider === 'qwen') {
          playQwenSpeechInBackground(openingData.message.content);
        }
      }
      if (nextAction.action === 'finish_interview') {
        setProcessingStage('三轮面试已完成，正在生成综合报告');
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
        await apiRequest(`/api/interviews/${interviewId}/report`, { method: 'POST' });
        onReportReady(interviewId);
        return;
      }
      setAnswer('');
      await reloadMessages();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSubmitting(false);
      setProcessingStage('');
    }
  };

  const handleFinish = async () => {
    if (!interviewId || finishing) return;
    stopRealtimeCall();
    stopOmniRealtimeCall();
    stopOmniWebrtcCall();
    stopQwenRecognition();
    stopQwenSpeech();
    setFinishing(true);
    setError('');
    setProcessingStage('正在结束面试并生成综合报告');

    try {
      await apiRequest(`/api/interviews/${interviewId}/finish`, { method: 'POST' });
      await apiRequest(`/api/interviews/${interviewId}/report`, { method: 'POST' });
      onReportReady(interviewId);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setFinishing(false);
      setProcessingStage('');
    }
  };

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
    <section className="phone-page">
      {error && <div className="profile-message error">{error}</div>}
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
              <h1>{currentAgentName}</h1>
              <span>正在围绕项目复杂度进行追问</span>
            </div>
          </div>

          <div className="call-question">
            <div>
              <Sparkles size={16} />
              <strong>当前问题</strong>
            </div>
            <p>{currentQuestion}</p>
          </div>

          <div className="voice-mode-dropdown" aria-label="语音模式">
            <div className="dropdown-trigger">
              <span>千问 WebRTC</span>
            </div>
          </div>

          <div className="call-controls" aria-label="电话面试控制">
            <button
              className={`control-button ${
                voiceProvider === 'openai'
                  ? voiceStatus === 'connected' ? 'primary' : ''
                  : voiceProvider === 'qwen'
                    ? qwenStatus === 'listening' ? 'primary' : ''
                    : omniStatus === 'listening' || omniStatus === 'connected' || omniStatus === 'speaking' ? 'primary' : ''
              }`}
              onClick={voiceProvider === 'openai' ? startRealtimeCall : voiceProvider === 'qwen' ? startQwenVoiceConversation : voiceProvider === 'omni-webrtc' ? startOmniWebrtcCall : startOmniRealtimeCall}
              disabled={voiceProvider === 'openai' ? voiceStatus === 'connecting' : voiceProvider === 'qwen' ? qwenStatus === 'connecting' || submitting : omniStatus === 'connecting'}
              title={voiceProvider === 'openai' ? voiceStatus === 'connected' ? '断开实时语音' : '开始实时语音' : voiceProvider === 'qwen' ? qwenStatus === 'listening' ? '停止聆听' : '开始聆听候选人回答' : voiceProvider === 'omni-webrtc' ? omniStatus === 'connected' || omniStatus === 'listening' || omniStatus === 'speaking' ? '断开 Qwen 官方 WebRTC 通话' : '开始 Qwen 官方 WebRTC 通话' : omniStatus === 'listening' ? '停止录音并提交 Qwen-Omni' : '开始 Qwen-Omni 录音'}
            >
              <Mic size={20} />
            </button>
            <button className="control-button danger" onClick={handleFinish} disabled={finishing}>
              <PhoneOff size={20} />
            </button>
          </div>
          {voiceProvider === 'openai' ? (
            <div className={`voice-status ${voiceStatus}`}>
              <span>{voiceStatus === 'connected' ? '实时语音已接通' : voiceStatus === 'connecting' ? '正在连接实时语音' : voiceStatus === 'error' ? '实时语音连接失败' : '实时语音待接入'}</span>
              <small>{voiceMessage}</small>
            </div>
          ) : voiceProvider === 'qwen' ? (
            <div className={`voice-status ${qwenStatus}`}>
              <span>{qwenStatus === 'listening' ? '正在聆听回答' : qwenStatus === 'speaking' ? '千问实时播报中' : qwenStatus === 'connecting' ? '正在处理千问对话' : qwenStatus === 'error' ? '千问对话失败' : '千问实时对话待接入'}</span>
              <small>{qwenMessage}</small>
            </div>
          ) : (
            <div className={`voice-status ${omniStatus}`}>
              <span>{voiceProvider === 'omni-webrtc' ? omniStatus === 'listening' ? 'Qwen WebRTC 正在聆听' : omniStatus === 'speaking' ? 'Qwen WebRTC 正在回复' : omniStatus === 'connecting' ? 'Qwen WebRTC 正在连接' : omniStatus === 'error' ? 'Qwen WebRTC 连接失败' : omniStatus === 'connected' ? 'Qwen WebRTC 已接通' : 'Qwen WebRTC 待接入' : omniStatus === 'listening' ? 'Omni 正在接收麦克风' : omniStatus === 'speaking' ? 'Omni 正在回复' : omniStatus === 'connecting' ? 'Omni 正在处理' : omniStatus === 'error' ? 'Omni 连接失败' : omniStatus === 'connected' ? 'Omni 本轮完成' : 'Omni API 待接入'}</span>
              <small>{omniMessage}</small>
              <div className="omni-signal-row" aria-label={voiceProvider === 'omni-webrtc' ? 'Qwen WebRTC 信号' : 'Omni 实验探针'}>
                <span className={omniSignals.text ? 'ok' : ''}>{voiceProvider === 'omni-webrtc' ? '字幕事件' : '文本'}</span>
                <span className={omniSignals.audioField ? 'ok' : ''}>{voiceProvider === 'omni-webrtc' ? '音频轨道' : '音频字段'}</span>
                <span className={omniSignals.playableAudio ? 'ok' : ''}>{voiceProvider === 'omni-webrtc' ? '远端播放' : '可播放音频'}</span>
              </div>
              {omniAudioUrl && (
                <audio
                  ref={omniAudioElementRef}
                  className="omni-audio-player"
                  src={omniAudioUrl}
                  controls
                  onPlay={() => setOmniMessage('正在回放 Qwen-Omni 音频')}
                  onEnded={() => setOmniMessage('Omni 音频回放完成，可继续说话')}
                />
              )}
            </div>
          )}
        </div>

        <aside className="call-sidebar">
          <div className="session-card">
            <span>面试状态</span>
            <strong>{interview?.status === 'completed' ? '已结束' : '进行中'}</strong>
            <p>{interview?.target_role} · {interview?.interview_type || '综合模拟'}</p>
          </div>
          <div className="signal-grid">
            <div className="signal-card">
              <span>真实消息</span>
              <strong>{messages.length}</strong>
              <small>已写入后端</small>
            </div>
            <div className="signal-card">
              <span>候选回答</span>
              <strong>{messages.filter((item) => item.sender_type === 'candidate').length}</strong>
              <small>已触发单轮评价</small>
            </div>
          </div>
        </aside>
      </div>

      <section className="phone-grid">
        <Card title="实时语音转写" icon={<MessageSquareText size={18} />}>
          <div className="transcript-list">
            {messages.map((item) => (
              <TranscriptMessage item={item} key={item.id} />
            ))}
          </div>
          <div className="reply-box">
            <textarea
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              placeholder="输入候选人回答，提交后会保存消息、生成单轮评价和下一条智能追问。"
            />
            <button aria-label="提交回答" onClick={handleSubmitAnswer} disabled={submitting || finishing || !answer.trim()}>
              <Send size={15} />
            </button>
          </div>
          {processingStage && (
            <div className="interview-processing" role="status" aria-live="polite">
              <Clock3 size={18} />
              <div>
                <strong>{processingStage}</strong>
                <span>
                  已等待 {processingSeconds} 秒
                  {processingSeconds >= 12 ? '，AI 服务响应较慢，系统会自动尝试备用模型或使用本地兜底。' : '，请不要重复提交。'}
                </span>
              </div>
            </div>
          )}
        </Card>

        <Card title="面试官接入队列" icon={<Radio size={18} />}>
          <AgentRoster agents={agents} currentAgent={currentAgentName} />
        </Card>

        <Card title="追问路线" icon={<CircleDot size={18} />} className="question-route-panel">
          <div className="question-route">
            {['项目背景', '方案取舍', '结果指标', '复盘改进'].map((item, index) => (
              <div className={index === 1 ? 'current' : ''} key={item}>
                <span>{String(index + 1).padStart(2, '0')}</span>
                <strong>{item}</strong>
              </div>
            ))}
          </div>
        </Card>
      </section>
      <div className="finish-bar">
        <button className="primary-action" onClick={handleFinish} disabled={finishing || submitting}>
          <FileText size={17} />
          {finishing ? `生成报告中（${processingSeconds} 秒）` : '结束面试并生成报告'}
        </button>
      </div>
    </section>
  );
}

function ReportPage({ interviewId, user }) {
  const [reportData, setReportData] = useState(null);
  const [loading, setLoading] = useState(Boolean(interviewId));
  const [error, setError] = useState('');
  const [regenerating, setRegenerating] = useState(false);
  const [retryError, setRetryError] = useState('');

  useEffect(() => {
    let mounted = true;

    if (!interviewId) {
      setLoading(false);
      return () => {
        mounted = false;
      };
    }

    setLoading(true);
    setError('');
    apiRequest(`/api/interviews/${interviewId}/report`)
      .then((data) => {
        if (mounted) setReportData(data.report);
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
          <span>完成一场面试后，报告页会读取 `GET /api/interviews/:id/report`。</span>
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

  const currentReport = reportToViewModel(reportData, user);
  const radarData = currentReport.radar.length > 0 ? currentReport.radar : report.radar.slice(0, 3);
  const metrics = currentReport.metrics.length > 0 ? currentReport.metrics : report.metrics.slice(0, 3);
  const reportStatusLabel = currentReport.generationStatus === 'degraded'
    ? '已降级为本地规则'
    : currentReport.generationStatus === 'succeeded'
      ? (currentReport.fallback ? '已生成（兜底）' : 'AI 已生成')
      : currentReport.generationStatus;

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
                <dd>{currentReport.candidate}</dd>
              </div>
              <div>
                <dt>应聘岗位</dt>
                <dd>{currentReport.role}</dd>
              </div>
              <div>
                <dt>报告来源</dt>
                <dd>{currentReport.fallback ? `本地规则兜底 · ${currentReport.model}` : `${currentReport.provider} · ${currentReport.model}`}</dd>
              </div>
              <div>
                <dt>报告编号</dt>
                <dd>{currentReport.interviewId}</dd>
              </div>
            </dl>
          </div>
        </div>
        <div className="decision-badge">
          <span>{currentReport.result}</span>
          <strong>{currentReport.grade}</strong>
          <small>综合评分 {currentReport.score}/100</small>
        </div>
      </header>

      {currentReport.fallback && (
        <div className="report-fallback-notice">
          <div>
            <strong>当前报告由本地评分规则生成</strong>
            <span>模型服务暂时不可用，报告仍可用于复盘；网络恢复后可以重新尝试 AI 生成。</span>
          </div>
          <button type="button" onClick={regenerateReport} disabled={regenerating}>
            {regenerating ? 'AI 重新生成中...' : '重新尝试 AI 生成'}
          </button>
        </div>
      )}
      {retryError && <p className="profile-message error report-retry-error">{retryError}</p>}

      <section className="kpi-grid">
        <div className="kpi-item">
          <CircleDot size={16} />
          <span>报告状态</span>
          <strong>{reportStatusLabel}</strong>
        </div>
        <div className="kpi-item">
          <CheckCircle2 size={16} />
          <span>面试官</span>
          <strong>{currentReport.interviewers.length}</strong>
        </div>
        <div className="kpi-item">
          <Clock3 size={16} />
          <span>生成时间</span>
          <strong>{currentReport.generatedAt}</strong>
        </div>
        <div className="kpi-item">
          <Award size={16} />
          <span>复核状态</span>
          <strong>{currentReport.reviewStatus === 'approved' ? '已通过复核' : currentReport.reviewStatus === 'rejected' ? '复核未通过' : '待人工复核'}</strong>
        </div>
      </section>

      <section className="dashboard-grid">
        <Card title="核心能力模型" icon={<BarChart3 size={18} />}>
          <div className="radar-wrap">
            <CompetencyRadar data={radarData} />
          </div>
        </Card>

        <Card title="逐项得分指标" icon={<FileText size={18} />}>
          <div className="metrics-list">
            {metrics.map((item) => (
              <ProgressMetric key={item.label} item={item} />
            ))}
          </div>
        </Card>
      </section>

      <section className="dashboard-grid secondary">
        <Card title="面试官综合评价" icon={<MessageSquareText size={18} />}>
          <div className="review-list">
            {currentReport.interviewers.map((item) => (
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

        <Card title="报告结论与训练建议" icon={<AlertTriangle size={18} />}>
          <div className="risk-table">
            <div>
              <span>报告摘要</span>
              <StatusTag tone="blue">真实生成</StatusTag>
              <p>{currentReport.summary}</p>
            </div>
            {currentReport.suggestions.map((item) => (
              <div key={item}>
                <span>训练建议</span>
                <StatusTag tone="amber">下一步</StatusTag>
                <p>{item}</p>
              </div>
            ))}
          </div>
        </Card>
      </section>

      <Card title="逐题问答复盘" icon={<Clock3 size={18} />} className="timeline-panel">
        <div className="timeline">
          {(currentReport.timeline.length > 0 ? currentReport.timeline : report.timeline).map((item, index) => (
            <TimelineItem key={item.id || `${item.title}-${index}`} item={item} index={index} />
          ))}
        </div>
      </Card>
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
    <section className="history-page">
      <div className="resume-hero">
        <div>
          <p className="eyebrow">Interview History</p>
          <h1>真实面试历史记录</h1>
          <span>这里读取 `GET /api/reports`，只展示当前登录用户已经生成报告的面试。</span>
        </div>
      </div>

      {reports.length === 0 ? (
        <div className="empty-state">
          <strong>暂无报告</strong>
          <span>完成一次面试并生成报告后，历史记录会出现在这里。</span>
        </div>
      ) : (
        <div className="history-list">
          {reports.map((item) => (
            <article className="history-item" key={item.id}>
              <div>
                <strong>{item.target_role}</strong>
                <span>{item.interview_type || '综合模拟'} · {formatDateTime(item.updated_at || item.created_at)}</span>
                <p>{item.summary}</p>
              </div>
              <div className="history-score">
                <strong>{item.total_score}</strong>
                <span>{item.grade}</span>
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

function DimensionChange({ value = 0 }) {
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
        const reportItems = reportsData.reports || [];
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
  const latestScore = Number(reports[0]?.total_score) || 0;
  const previousScore = Number(reports[1]?.total_score) || latestScore;
  const scoreDelta = latestScore - previousScore;
  const targetGap = Math.max(0, 75 - overallScore);
  const confidence = completedCount >= 5 ? '高' : completedCount >= 2 ? '中等' : '待积累';
  const confidenceTone = completedCount >= 5 ? 'green' : completedCount >= 2 ? 'blue' : 'amber';
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
  const heroTitle = overallScore === 0
    ? '完成首次面试，建立你的能力基线'
    : targetGap > 0
      ? `距离建议目标还有 ${targetGap} 分`
      : '当前综合表现已达到建议目标';

  return (
    <section className="stats-page">
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
            基于 {completedCount} 场已完成面试持续更新，结合目标岗位对比能力变化，并把每个结论追溯到真实报告证据。
          </p>
          <div className="stats-overview-meta">
            <span><Target size={14} />目标岗位：{stats?.recent_training_focus || '待设置'}</span>
            <span><ShieldCheck size={14} />画像可信度：{confidence}</span>
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
          <div><span>有效样本</span><strong>{completedCount} 场</strong></div>
          <small>{reports.length} 份能力报告</small>
        </article>
        <article>
          <div className="stats-kpi-icon"><TrendingUp size={17} /></div>
          <div><span>最近一场</span><strong>{latestScore || '—'}{latestScore ? ' 分' : ''}</strong></div>
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
          <Card title="画像可信度" icon={<ShieldCheck size={18} />}>
            <div className="data-quality-card">
              <div>
                <span>当前判断</span>
                <StatusTag tone={confidenceTone}>{confidence}</StatusTag>
              </div>
              <div className="data-quality-bar"><i style={{ width: `${Math.min(100, completedCount * 20)}%` }} /></div>
              <dl>
                <div><dt>能力覆盖</dt><dd>{validDimensions.length}/{Object.keys(dimensionLabels).length} 维 · {coverage}%</dd></div>
                <div><dt>报告样本</dt><dd>{reports.length} 份</dd></div>
                <div><dt>提升建议</dt><dd>{trainingTasks.length} 项</dd></div>
              </dl>
              <p>完成 5 场以上不同类型的面试后，长期趋势判断会更稳定。</p>
            </div>
          </Card>
        </div>
      </section>

      <section className="stats-lower-grid">
        <Card title="本周提升计划" icon={<Sparkles size={18} />} action={<StatusTag tone="amber">建议先练 1 项</StatusTag>}>
          <div className="training-plan-list">
            {trainingTasks.length === 0 ? (
              <div className="training-empty">
                <strong>等待生成个性化计划</strong>
                <span>完成一次面试后，系统会把短板转化为可执行训练任务。</span>
              </div>
            ) : trainingTasks.map((task, index) => (
              <article className={index === 0 ? 'priority' : ''} key={task.key}>
                <span className="training-step">0{index + 1}</span>
                <div>
                  <div className="training-title">
                    <strong>{task.title}</strong>
                    <StatusTag tone={index === 0 ? 'amber' : 'blue'}>{task.score}/100</StatusTag>
                  </div>
                  <p>{task.text}</p>
                  <small>{index === 0 ? '建议今天完成 · 约 15 分钟' : '完成上一项后解锁'}</small>
                </div>
              </article>
            ))}
          </div>
        </Card>

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
                      <small>{item.agent_name || 'AI 面试官'} · 本题 {Number(item.score) || '—'} 分</small>
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

function App() {
  const [user, setUser] = useState(undefined);
  const [view, setView] = useState('setup');
  const [activeInterviewId, setActiveInterviewId] = useState('');
  const [downloadingReport, setDownloadingReport] = useState(false);
  const [downloadError, setDownloadError] = useState('');

  useEffect(() => {
    let mounted = true;

    apiRequest('/api/auth/me')
      .then((data) => {
        if (mounted) {
          setUser(data.user);
        }
        return apiRequest('/api/interviews?status=running')
          .then((interviewData) => {
            if (!mounted) return;
            const runningInterview = interviewData.interviews?.[0];
            if (runningInterview?.id) {
              setActiveInterviewId(runningInterview.id);
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
    setView('setup');
    setActiveInterviewId('');
  };

  const handleStartInterview = (interviewId) => {
    setActiveInterviewId(interviewId);
    setView('phone');
  };

  const handleOpenReport = (interviewId) => {
    setActiveInterviewId(interviewId);
    setView('report');
    setDownloadError('');
  };

  const canDownloadReport = view === 'report' && Boolean(activeInterviewId);

  const handleDownloadReport = async () => {
    if (!canDownloadReport || downloadingReport) return;
    setDownloadingReport(true);
    setDownloadError('');
    try {
      await apiRequest(`/api/interviews/${activeInterviewId}/report`);
      const anchor = document.createElement('a');
      anchor.href = apiUrl(`/api/interviews/${activeInterviewId}/report/download`);
      anchor.download = '';
      anchor.style.display = 'none';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } catch (requestError) {
      setDownloadError(requestError.message || '报告下载失败，请稍后重试。');
    } finally {
      setDownloadingReport(false);
    }
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
          <button
            className={`topbar-account ${view === 'profile' ? 'active' : ''}`}
            type="button"
            onClick={() => setView('profile')}
            aria-label="打开个人中心"
          >
            <UserRound size={16} />
            <span>{user.name}</span>
          </button>
          <button
            className="icon-button"
            type="button"
            aria-label={downloadingReport ? '正在下载报告' : '下载报告'}
            title={canDownloadReport ? '下载 Markdown 报告' : '请先打开一份报告'}
            onClick={handleDownloadReport}
            disabled={!canDownloadReport || downloadingReport}
          >
            <Download size={18} />
          </button>
          <button className="icon-button" aria-label="退出登录" onClick={handleLogout}>
            <LogOut size={18} />
          </button>
        </div>

        {downloadError && <div className="profile-message error" role="alert">{downloadError}</div>}

        {view === 'setup' && <SetupPage onStart={handleStartInterview} />}
        {view === 'resume' && <ResumeAnalysisPage onUseSetup={() => setView('setup')} />}
        {view === 'profile' && <ProfilePage user={user} onUserUpdate={setUser} onLogout={handleLogout} />}
        {view === 'phone' && (
          <PhoneInterviewPage
            interviewId={activeInterviewId}
            onReportReady={handleOpenReport}
            onBackToSetup={() => setView('setup')}
          />
        )}
        {view === 'report' && <ReportPage interviewId={activeInterviewId} user={user} />}
        {view === 'history' && <HistoryPage onOpenReport={handleOpenReport} />}
        {view === 'stats' && <StatsPage onStartTraining={() => setView('setup')} onOpenReport={handleOpenReport} />}
      </div>
    </main>
  );
}

const rootElement = document.getElementById('root');
const appRoot = rootElement.__appRoot || createRoot(rootElement);
rootElement.__appRoot = appRoot;
appRoot.render(<App />);
