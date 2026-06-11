import './env.js';
import express from 'express';
import { randomUUID } from 'node:crypto';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { db, getDatabasePath } from './database.js';
import {
  createToken,
  hashPassword,
  hashToken,
  isValidEmail,
  normalizeEmail,
  sanitizeUser,
  verifyPassword,
} from './security.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const app = express();
const port = Number(process.env.PORT || 3001);
const sessionCookieName = 'interview_session';
const sessionMaxAgeMs = 1000 * 60 * 60 * 24 * 7;
const resetMaxAgeMs = 1000 * 60 * 20;
const loginAttempts = new Map();
const loginWindowMs = 1000 * 60 * 15;
const maxLoginAttempts = 8;

app.disable('x-powered-by');
app.use(express.json({ limit: '128kb' }));

function cookieOptions(maxAgeMs = sessionMaxAgeMs) {
  return {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.COOKIE_SECURE === 'true',
    path: '/',
    maxAge: maxAgeMs,
  };
}

function getCookie(req, name) {
  const cookies = req.headers.cookie || '';
  const match = cookies
    .split(';')
    .map((item) => item.trim())
    .find((item) => item.startsWith(`${name}=`));

  if (!match) {
    return '';
  }

  return decodeURIComponent(match.slice(name.length + 1));
}

function createSession(res, userId, userAgent) {
  const token = createToken();
  const tokenHash = hashToken(token);
  const expiresAt = new Date(Date.now() + sessionMaxAgeMs).toISOString();

  db.prepare(
    `INSERT INTO sessions (id, user_id, token_hash, expires_at, user_agent)
     VALUES (?, ?, ?, ?, ?)`
  ).run(randomUUID(), userId, tokenHash, expiresAt, userAgent || null);

  res.cookie(sessionCookieName, token, cookieOptions());
}

function clearSession(res) {
  res.clearCookie(sessionCookieName, {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.COOKIE_SECURE === 'true',
    path: '/',
  });
}

function findUserBySession(req) {
  const token = getCookie(req, sessionCookieName);

  if (!token) {
    return null;
  }

  const tokenHash = hashToken(token);
  const row = db.prepare(
    `SELECT users.id, users.email, users.name, users.status, users.created_at, users.last_login_at
     FROM sessions
     JOIN users ON users.id = sessions.user_id
     WHERE sessions.token_hash = ?
       AND sessions.expires_at > datetime('now')
       AND users.status = 'normal'`
  ).get(tokenHash);

  return row || null;
}

function requireAuth(req, res, next) {
  const user = findUserBySession(req);

  if (!user) {
    res.status(401).json({ error: '请先登录。' });
    return;
  }

  req.user = user;
  next();
}

function loginAttemptKey(req, email) {
  return `${req.ip || req.socket.remoteAddress || 'local'}:${email}`;
}

function isLoginLimited(req, email) {
  const key = loginAttemptKey(req, email);
  const record = loginAttempts.get(key);

  if (!record) {
    return false;
  }

  if (record.resetAt <= Date.now()) {
    loginAttempts.delete(key);
    return false;
  }

  return record.count >= maxLoginAttempts;
}

function recordFailedLogin(req, email) {
  const key = loginAttemptKey(req, email);
  const now = Date.now();
  const record = loginAttempts.get(key);

  if (!record || record.resetAt <= now) {
    loginAttempts.set(key, { count: 1, resetAt: now + loginWindowMs });
    return;
  }

  record.count += 1;
}

function clearFailedLogins(req, email) {
  loginAttempts.delete(loginAttemptKey(req, email));
}

const profileTextFields = [
  ['nickname', '昵称', 60, true],
  ['target_role', '目标岗位', 80],
  ['experience_level', '经验水平', 40],
  ['company_type', '目标公司类型', 80],
  ['target_city', '目标城市', 80],
  ['expected_salary', '期望薪资', 80],
  ['years_of_experience', '工作年限', 40],
  ['education_level', '学历背景', 60],
  ['skills', '技能标签', 500],
  ['project_keywords', '项目关键词', 500],
  ['resume_text', '简历文本', 12000],
  ['project_experience', '项目经历', 12000],
  ['preferred_interview_type', '默认面试类型', 60],
  ['preferred_difficulty', '默认难度', 40],
  ['preferred_interviewer_style', '面试官风格', 60],
];

function readTextField(body, field, label, maxLength, required = false) {
  const value = String((body || {})[field] || '').trim();

  if (required && !value) {
    return { error: `${label}不能为空。` };
  }

  if (!value) {
    return { value: null };
  }

  if (value.length > maxLength) {
    return { error: `${label}不能超过 ${maxLength} 个字符。` };
  }

  return { value };
}

function readUrlField(body, field, label, maxLength, { multiline = false } = {}) {
  const value = String((body || {})[field] || '').trim();

  if (!value) {
    return { value: null };
  }

  if (value.length > maxLength) {
    return { error: `${label}不能超过 ${maxLength} 个字符。` };
  }

  const urls = multiline ? value.split(/\s+/).filter(Boolean) : [value];
  const invalidUrl = urls.find((url) => {
    try {
      const parsed = new URL(url);
      return !['http:', 'https:'].includes(parsed.protocol);
    } catch {
      return true;
    }
  });

  if (invalidUrl) {
    return { error: `${label}只支持 http 或 https 链接。` };
  }

  return { value };
}

function parseProfileInput(body, fallbackName) {
  const profile = {};

  for (const [field, label, maxLength, required] of profileTextFields) {
    const result = readTextField(body, field, label, maxLength, required);
    if (result.error) {
      return { error: result.error };
    }
    profile[field] = result.value;
  }

  profile.nickname = profile.nickname || fallbackName;

  const avatarResult = readUrlField(body, 'avatar_url', '头像链接', 500);
  if (avatarResult.error) {
    return { error: avatarResult.error };
  }
  profile.avatar_url = avatarResult.value;

  const portfolioResult = readUrlField(body, 'portfolio_links', '作品链接', 1000, { multiline: true });
  if (portfolioResult.error) {
    return { error: portfolioResult.error };
  }
  profile.portfolio_links = portfolioResult.value;

  return { profile };
}

function ensureProfile(user) {
  const existingProfile = db.prepare('SELECT id FROM profiles WHERE user_id = ?').get(user.id);

  if (existingProfile) {
    return;
  }

  db.prepare(
    `INSERT INTO profiles (id, user_id, nickname)
     VALUES (?, ?, ?)`
  ).run(randomUUID(), user.id, user.name);
}

function findProfileByUserId(userId) {
  return db.prepare(
    `SELECT id, user_id, nickname, avatar_url, target_role, experience_level, company_type,
            target_city, expected_salary, years_of_experience, education_level, skills,
            project_keywords, resume_text, project_experience, portfolio_links,
            preferred_interview_type, preferred_difficulty, preferred_interviewer_style,
            created_at, updated_at
     FROM profiles
     WHERE user_id = ?`
  ).get(userId);
}

const interviewStatuses = new Set(['draft', 'running', 'completed']);
const agentStatuses = new Set(['pending', 'active', 'completed']);
const messageSenderTypes = new Set(['agent', 'candidate', 'system']);
const messageTypes = new Set(['question', 'answer', 'follow_up', 'system', 'transcript']);
const interviewTextFields = [
  ['target_role', '目标岗位', 80],
  ['experience_level', '经验等级', 40],
  ['interview_type', '面试类型', 60],
  ['company_context', '公司场景', 120],
  ['focus_areas', '重点方向', 500],
  ['difficulty', '难度', 40],
  ['interviewer_style', '面试官风格', 60],
];

function parseInterviewInput(body, { partial = false } = {}) {
  const interview = {};
  const source = body || {};

  for (const [field, label, maxLength] of interviewTextFields) {
    if (partial && !Object.prototype.hasOwnProperty.call(source, field)) {
      continue;
    }

    const result = readTextField(source, field, label, maxLength, field === 'target_role');
    if (result.error) {
      return { error: result.error };
    }
    interview[field] = result.value;
  }

  if (partial && Object.keys(interview).length === 0) {
    return { error: '请至少提供一个要更新的字段。' };
  }

  return { interview };
}

function findInterviewByUserId(interviewId, userId) {
  return db.prepare(
    `SELECT id, user_id, target_role, experience_level, interview_type, company_context,
            focus_areas, difficulty, interviewer_style, status, created_at, updated_at,
            started_at, completed_at
     FROM interview_sessions
     WHERE id = ? AND user_id = ?`
  ).get(interviewId, userId);
}

function normalizeStatus(status) {
  const value = String(status || '').trim();
  return interviewStatuses.has(value) ? value : null;
}

const defaultAgentTemplates = [
  {
    agent_name: '技术一面 Agent',
    agent_type: 'technical',
    agent_role: '负责考察候选人的核心技术基础、项目细节和编码思路。',
    strategy: '先围绕目标岗位确认技术栈，再根据重点方向逐步追问实现细节。',
  },
  {
    agent_name: '架构二面 Agent',
    agent_type: 'architecture',
    agent_role: '负责考察系统设计、工程权衡、性能和稳定性意识。',
    strategy: '从业务场景切入，观察候选人如何拆解模块、设计数据流和处理边界。',
  },
  {
    agent_name: 'HR Agent',
    agent_type: 'hr',
    agent_role: '负责考察职业动机、沟通表达、团队协作和岗位匹配度。',
    strategy: '用行为面试问题理解候选人的经历、偏好和稳定性。',
  },
];

const agentTextFields = [
  ['agent_name', 'Agent 名称', 80],
  ['agent_type', 'Agent 类型', 40],
  ['agent_role', 'Agent 角色', 500],
  ['strategy', '面试策略', 1000],
];

function normalizeAgentStatus(status) {
  const value = String(status || '').trim();
  return agentStatuses.has(value) ? value : null;
}

function parseOrderIndex(value) {
  if (value === undefined || value === null || value === '') {
    return null;
  }

  const number = Number(value);
  if (!Number.isInteger(number) || number < 0 || number > 99) {
    return null;
  }

  return number;
}

function parseAgentInput(body, { partial = false } = {}) {
  const agent = {};
  const source = body || {};

  for (const [field, label, maxLength] of agentTextFields) {
    if (partial && !Object.prototype.hasOwnProperty.call(source, field)) {
      continue;
    }

    const required = field !== 'strategy';
    const result = readTextField(source, field, label, maxLength, required);
    if (result.error) {
      return { error: result.error };
    }
    agent[field] = result.value;
  }

  if (Object.prototype.hasOwnProperty.call(source, 'order_index')) {
    const orderIndex = parseOrderIndex(source.order_index);
    if (orderIndex === null) {
      return { error: 'Agent 顺序必须是 0 到 99 之间的整数。' };
    }
    agent.order_index = orderIndex;
  }

  if (Object.prototype.hasOwnProperty.call(source, 'status')) {
    const status = normalizeAgentStatus(source.status);
    if (!status) {
      return { error: 'Agent 状态不正确。' };
    }
    agent.status = status;
  }

  if (partial && Object.keys(agent).length === 0) {
    return { error: '请至少提供一个要更新的字段。' };
  }

  return { agent };
}

function listAgentsByInterviewId(interviewId) {
  return db.prepare(
    `SELECT id, interview_id, agent_name, agent_type, agent_role, strategy, order_index,
            status, created_at, updated_at
     FROM interview_agents
     WHERE interview_id = ?
     ORDER BY order_index ASC, datetime(created_at) ASC`
  ).all(interviewId);
}

function findAgentByInterviewId(agentId, interviewId) {
  return db.prepare(
    `SELECT id, interview_id, agent_name, agent_type, agent_role, strategy, order_index,
            status, created_at, updated_at
     FROM interview_agents
     WHERE id = ? AND interview_id = ?`
  ).get(agentId, interviewId);
}

function createDefaultAgents(interviewId) {
  const insertAgent = db.prepare(
    `INSERT INTO interview_agents (
       id, interview_id, agent_name, agent_type, agent_role, strategy, order_index, status
     )
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
  );

  defaultAgentTemplates.forEach((agent, index) => {
    insertAgent.run(
      randomUUID(),
      interviewId,
      agent.agent_name,
      agent.agent_type,
      agent.agent_role,
      agent.strategy,
      index,
      'pending'
    );
  });
}

function ensureDefaultAgents(interviewId) {
  const existing = db.prepare('SELECT COUNT(*) AS count FROM interview_agents WHERE interview_id = ?').get(interviewId);

  if (existing.count === 0) {
    createDefaultAgents(interviewId);
  }
}

function nextAgentOrderIndex(interviewId) {
  const row = db.prepare('SELECT MAX(order_index) AS max_order_index FROM interview_agents WHERE interview_id = ?').get(interviewId);
  return Number.isInteger(row?.max_order_index) ? row.max_order_index + 1 : 0;
}

function normalizeMessageSenderType(senderType) {
  const value = String(senderType || '').trim();
  return messageSenderTypes.has(value) ? value : null;
}

function normalizeMessageType(messageType) {
  const value = String(messageType || '').trim();
  return messageTypes.has(value) ? value : null;
}

function parseMessageInput(body) {
  const source = body || {};
  const senderType = normalizeMessageSenderType(source.sender_type);
  const messageType = normalizeMessageType(source.message_type);
  const contentResult = readTextField(source, 'content', '消息内容', 12000, true);
  const transcriptResult = readTextField(source, 'transcript_text', '语音转写结果', 12000);
  const agentId = String(source.agent_id || '').trim() || null;

  if (!senderType) {
    return { error: '消息发送方类型不正确。' };
  }

  if (!messageType) {
    return { error: '消息类型不正确。' };
  }

  if (contentResult.error) {
    return { error: contentResult.error };
  }

  if (transcriptResult.error) {
    return { error: transcriptResult.error };
  }

  if (senderType === 'agent' && !agentId) {
    return { error: 'Agent 消息必须关联 agent_id。' };
  }

  if (senderType !== 'agent' && agentId) {
    return { error: '只有 Agent 消息可以关联 agent_id。' };
  }

  if (senderType === 'candidate' && !['answer', 'transcript'].includes(messageType)) {
    return { error: '候选人消息只能是 answer 或 transcript。' };
  }

  if (senderType === 'system' && messageType !== 'system') {
    return { error: '系统消息类型必须是 system。' };
  }

  if (senderType === 'agent' && !['question', 'follow_up', 'system'].includes(messageType)) {
    return { error: 'Agent 消息只能是 question、follow_up 或 system。' };
  }

  return {
    message: {
      agent_id: agentId,
      sender_type: senderType,
      message_type: messageType,
      content: contentResult.value,
      transcript_text: transcriptResult.value,
    },
  };
}

function listMessagesByInterviewId(interviewId) {
  return db.prepare(
    `SELECT messages.id, messages.interview_id, messages.agent_id,
            agents.agent_name, agents.agent_type,
            messages.sender_type, messages.message_type, messages.content,
            messages.transcript_text, messages.order_index, messages.created_at
     FROM interview_messages AS messages
     LEFT JOIN interview_agents AS agents ON agents.id = messages.agent_id
     WHERE messages.interview_id = ?
     ORDER BY messages.order_index ASC, datetime(messages.created_at) ASC`
  ).all(interviewId);
}

function findMessageByInterviewId(messageId, interviewId) {
  return db.prepare(
    `SELECT messages.id, messages.interview_id, messages.agent_id,
            agents.agent_name, agents.agent_type,
            messages.sender_type, messages.message_type, messages.content,
            messages.transcript_text, messages.order_index, messages.created_at
     FROM interview_messages AS messages
     LEFT JOIN interview_agents AS agents ON agents.id = messages.agent_id
     WHERE messages.id = ? AND messages.interview_id = ?`
  ).get(messageId, interviewId);
}

function nextMessageOrderIndex(interviewId) {
  const row = db.prepare('SELECT MAX(order_index) AS max_order_index FROM interview_messages WHERE interview_id = ?').get(interviewId);
  return Number.isInteger(row?.max_order_index) ? row.max_order_index + 1 : 0;
}

function clampScore(score) {
  return Math.max(1, Math.min(100, Math.round(score)));
}

function clampStatScore(score) {
  return Math.max(0, Math.min(100, Math.round(score)));
}

function generateMockEvaluation(message) {
  const content = String(message.content || '');
  const lengthScore = content.length >= 180 ? 18 : content.length >= 80 ? 12 : 6;
  const structureScore = /第一|第二|首先|其次|最后|因为|所以|例如|比如/.test(content) ? 10 : 4;
  const technicalScore = /架构|性能|数据库|缓存|并发|接口|边界|测试|部署|Agent|SQL|Node|React/i.test(content) ? 14 : 6;
  const baseScore = clampScore(58 + lengthScore + structureScore + technicalScore);
  const expressionClarity = clampScore(baseScore + (structureScore >= 10 ? 4 : -4));
  const technicalDepth = clampScore(baseScore + (technicalScore >= 14 ? 5 : -6));
  const businessUnderstanding = clampScore(baseScore + (/业务|用户|场景|指标|成本|收益|风险/.test(content) ? 5 : -5));

  const strengths = [
    content.length >= 80 ? '回答有一定展开，能够覆盖背景和做法。' : '回答能抓住问题方向，具备继续追问的基础。',
    technicalScore >= 14 ? '能提到具体技术点，便于面试官继续深挖。' : '表达保持聚焦，没有明显跑题。',
  ].join('\n');

  const issues = [
    content.length >= 180 ? '可以进一步压缩表达，让重点更突出。' : '细节还不够充分，关键方案、权衡和结果需要补充。',
    structureScore >= 10 ? '结构已经初步清晰，但结论和量化结果还可以更靠前。' : '回答结构略散，建议按背景、行动、结果组织。',
  ].join('\n');

  const suggestions = [
    '补充一个具体场景，说明你负责的模块、遇到的限制和最终结果。',
    '用 1-2 个量化指标呈现影响，例如耗时、成功率、性能或成本变化。',
    '主动说明方案取舍，展示你对边界条件和风险的判断。',
  ].join('\n');

  return {
    score: baseScore,
    strengths,
    issues,
    suggestions,
    dimension_scores: {
      technical_depth: technicalDepth,
      expression_clarity: expressionClarity,
      business_understanding: businessUnderstanding,
    },
  };
}

function parseEvaluationInput(body) {
  const messageId = String((body || {}).message_id || '').trim();

  if (!messageId) {
    return { error: '请提供要评价的 message_id。' };
  }

  return { messageId };
}

function findEvaluationByMessageId(interviewId, messageId) {
  return db.prepare(
    `SELECT evaluations.id, evaluations.interview_id, evaluations.message_id, evaluations.agent_id,
            agents.agent_name, agents.agent_type,
            evaluations.score, evaluations.strengths, evaluations.issues, evaluations.suggestions,
            evaluations.dimension_scores, evaluations.created_at, evaluations.updated_at
     FROM interview_evaluations AS evaluations
     LEFT JOIN interview_agents AS agents ON agents.id = evaluations.agent_id
     WHERE evaluations.interview_id = ? AND evaluations.message_id = ?`
  ).get(interviewId, messageId);
}

function findEvaluationById(interviewId, evaluationId) {
  return db.prepare(
    `SELECT evaluations.id, evaluations.interview_id, evaluations.message_id, evaluations.agent_id,
            agents.agent_name, agents.agent_type,
            evaluations.score, evaluations.strengths, evaluations.issues, evaluations.suggestions,
            evaluations.dimension_scores, evaluations.created_at, evaluations.updated_at
     FROM interview_evaluations AS evaluations
     LEFT JOIN interview_agents AS agents ON agents.id = evaluations.agent_id
     WHERE evaluations.interview_id = ? AND evaluations.id = ?`
  ).get(interviewId, evaluationId);
}

function listEvaluationsByInterviewId(interviewId) {
  return db.prepare(
    `SELECT evaluations.id, evaluations.interview_id, evaluations.message_id, evaluations.agent_id,
            agents.agent_name, agents.agent_type,
            evaluations.score, evaluations.strengths, evaluations.issues, evaluations.suggestions,
            evaluations.dimension_scores, evaluations.created_at, evaluations.updated_at,
            messages.content AS message_content, messages.order_index AS message_order_index
     FROM interview_evaluations AS evaluations
     LEFT JOIN interview_agents AS agents ON agents.id = evaluations.agent_id
     JOIN interview_messages AS messages ON messages.id = evaluations.message_id
     WHERE evaluations.interview_id = ?
     ORDER BY messages.order_index ASC, datetime(evaluations.created_at) ASC`
  ).all(interviewId);
}

function parseJsonObject(value, fallback = {}) {
  try {
    const parsed = JSON.parse(value || '');
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : fallback;
  } catch {
    return fallback;
  }
}

function average(numbers, fallback = 0) {
  const validNumbers = numbers.filter((number) => Number.isFinite(number));
  if (validNumbers.length === 0) {
    return fallback;
  }

  return validNumbers.reduce((sum, number) => sum + number, 0) / validNumbers.length;
}

function gradeFromScore(score) {
  if (score >= 90) return 'A';
  if (score >= 80) return 'B';
  if (score >= 70) return 'C';
  if (score >= 60) return 'D';
  return 'E';
}

function passRecommendationFromScore(score) {
  if (score >= 85) return 'strong_pass';
  if (score >= 75) return 'pass';
  if (score >= 60) return 'borderline';
  return 'no_pass';
}

function buildAbilityRadar(evaluations) {
  const dimensions = ['technical_depth', 'expression_clarity', 'business_understanding'];
  const radar = {};

  for (const dimension of dimensions) {
    radar[dimension] = clampScore(
      average(
        evaluations.map((evaluation) => parseJsonObject(evaluation.dimension_scores)[dimension]),
        70
      )
    );
  }

  return radar;
}

function buildAgentFeedback(agents, evaluations) {
  return agents.map((agent) => {
    const relatedEvaluations = evaluations.filter((evaluation) => evaluation.agent_id === agent.id);
    const score = clampScore(average(relatedEvaluations.map((evaluation) => evaluation.score), 72));

    return {
      agent_id: agent.id,
      agent_name: agent.agent_name,
      agent_type: agent.agent_type,
      score,
      comment:
        relatedEvaluations.length > 0
          ? `已完成 ${relatedEvaluations.length} 条回答复盘，整体表现${score >= 80 ? '稳定' : '仍需加强'}。`
          : '暂无关联单轮评价，后续可结合该 Agent 的追问补充更细的判断。',
    };
  });
}

function buildTimelineReview(messages, evaluations) {
  const evaluationByMessageId = new Map(evaluations.map((evaluation) => [evaluation.message_id, evaluation]));

  return messages.map((message) => ({
    message_id: message.id,
    order_index: message.order_index,
    sender_type: message.sender_type,
    message_type: message.message_type,
    agent_name: message.agent_name || null,
    content_preview: message.content.length > 80 ? `${message.content.slice(0, 80)}...` : message.content,
    score: evaluationByMessageId.get(message.id)?.score || null,
  }));
}

function generateMockReport(interview, agents, messages, evaluations) {
  const totalScore = clampScore(average(evaluations.map((evaluation) => evaluation.score), messages.length > 0 ? 72 : 60));
  const candidateAnswers = messages.filter((message) => message.sender_type === 'candidate').length;
  const agentQuestions = messages.filter((message) => message.sender_type === 'agent').length;
  const abilityRadar = buildAbilityRadar(evaluations);
  const agentFeedback = buildAgentFeedback(agents, evaluations);
  const timelineReview = buildTimelineReview(messages, evaluations);

  return {
    total_score: totalScore,
    grade: gradeFromScore(totalScore),
    pass_recommendation: passRecommendationFromScore(totalScore),
    ability_radar: abilityRadar,
    agent_feedback: agentFeedback,
    timeline_review: timelineReview,
    summary: `本次模拟面向${interview.target_role}，共记录 ${messages.length} 条消息，其中候选人回答 ${candidateAnswers} 条，Agent 提问或追问 ${agentQuestions} 条。综合当前单轮评价，整体等级为 ${gradeFromScore(totalScore)}。`,
    suggestions: [
      '继续补充回答中的项目背景、关键决策和量化结果。',
      '针对低分维度安排专项训练，优先复盘被追问但回答不充分的问题。',
      '下一次模拟可以提高难度或增加架构追问，检验方案权衡能力。',
    ].join('\n'),
  };
}

function buildRealtimeSessionConfig(interview, agents, messages) {
  const currentAgent = agents[0];
  const latestQuestion =
    [...messages].reverse().find((message) => message.sender_type === 'agent')?.content ||
    createInitialQuestion(interview, currentAgent);

  return {
    type: 'realtime',
    model: process.env.OPENAI_REALTIME_MODEL || 'gpt-realtime-2',
    instructions: [
      '你是一名中文 AI 电话面试官，正在进行一场真实语音模拟面试。',
      '请使用自然、简洁、专业的中文口语交流，每次只问一个问题。',
      '候选人回答后，先做一句短反馈，再围绕项目细节、方案取舍、量化结果或风险边界继续追问。',
      '不要一次性给出长篇评价；把节奏控制成电话面试。',
      `目标岗位：${interview.target_role || '未填写'}`,
      `面试类型：${interview.interview_type || '综合模拟'}`,
      `难度：${interview.difficulty || '标准'}`,
      `面试官风格：${interview.interviewer_style || '专业追问'}`,
      `当前面试官：${currentAgent?.agent_name || '技术面试 Agent'}`,
      `当前问题：${latestQuestion}`,
      '如果刚接通，请从当前问题开始，不要重复介绍系统功能。',
    ].join('\n'),
    audio: {
      input: {
        transcription: {
          model: process.env.OPENAI_TRANSCRIPTION_MODEL || 'gpt-realtime-whisper',
          language: 'zh',
        },
        turn_detection: {
          type: 'server_vad',
        },
      },
      output: {
        voice: process.env.OPENAI_REALTIME_VOICE || 'marin',
      },
    },
  };
}

function findReportByInterviewId(interviewId, userId) {
  return db.prepare(
    `SELECT reports.id, reports.user_id, reports.interview_id,
            interviews.target_role, interviews.interview_type, interviews.status AS interview_status,
            reports.total_score, reports.grade, reports.pass_recommendation,
            reports.ability_radar, reports.agent_feedback, reports.timeline_review,
            reports.summary, reports.suggestions, reports.created_at, reports.updated_at
     FROM interview_reports AS reports
     JOIN interview_sessions AS interviews ON interviews.id = reports.interview_id
     WHERE reports.interview_id = ? AND reports.user_id = ?`
  ).get(interviewId, userId);
}

function findReportById(reportId, userId) {
  return db.prepare(
    `SELECT reports.id, reports.user_id, reports.interview_id,
            interviews.target_role, interviews.interview_type, interviews.status AS interview_status,
            reports.total_score, reports.grade, reports.pass_recommendation,
            reports.ability_radar, reports.agent_feedback, reports.timeline_review,
            reports.summary, reports.suggestions, reports.created_at, reports.updated_at
     FROM interview_reports AS reports
     JOIN interview_sessions AS interviews ON interviews.id = reports.interview_id
     WHERE reports.id = ? AND reports.user_id = ?`
  ).get(reportId, userId);
}

function listReportsByUserId(userId) {
  return db.prepare(
    `SELECT reports.id, reports.user_id, reports.interview_id,
            interviews.target_role, interviews.interview_type, interviews.status AS interview_status,
            reports.total_score, reports.grade, reports.pass_recommendation,
            reports.summary, reports.created_at, reports.updated_at
     FROM interview_reports AS reports
     JOIN interview_sessions AS interviews ON interviews.id = reports.interview_id
     WHERE reports.user_id = ?
     ORDER BY datetime(reports.updated_at) DESC, datetime(reports.created_at) DESC`
  ).all(userId);
}

function listFullReportsByUserId(userId) {
  return db.prepare(
    `SELECT reports.id, reports.user_id, reports.interview_id,
            interviews.target_role, interviews.interview_type, interviews.status AS interview_status,
            reports.total_score, reports.ability_radar, reports.created_at, reports.updated_at
     FROM interview_reports AS reports
     JOIN interview_sessions AS interviews ON interviews.id = reports.interview_id
     WHERE reports.user_id = ?
     ORDER BY datetime(reports.updated_at) ASC, datetime(reports.created_at) ASC`
  ).all(userId);
}

function computeDimensionTrend(values) {
  if (values.length < 2) {
    return 'stable';
  }

  const delta = values[values.length - 1] - values[0];
  if (delta >= 5) return 'up';
  if (delta <= -5) return 'down';
  return 'stable';
}

function refreshUserSkillStats(userId) {
  const interviewCounts = db.prepare(
    `SELECT
       COUNT(*) AS total_interviews,
       SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_interviews
     FROM interview_sessions
     WHERE user_id = ?`
  ).get(userId);
  const reports = listFullReportsByUserId(userId);
  const dimensions = ['technical_depth', 'expression_clarity', 'business_understanding'];
  const dimensionValues = Object.fromEntries(dimensions.map((dimension) => [dimension, []]));

  for (const report of reports) {
    const radar = parseJsonObject(report.ability_radar);
    for (const dimension of dimensions) {
      const value = Number(radar[dimension]);
      if (Number.isFinite(value)) {
        dimensionValues[dimension].push(value);
      }
    }
  }

  const dimensionAverages = Object.fromEntries(
    dimensions.map((dimension) => [dimension, clampStatScore(average(dimensionValues[dimension], 0))])
  );
  const dimensionTrends = Object.fromEntries(
    dimensions.map((dimension) => [dimension, computeDimensionTrend(dimensionValues[dimension])])
  );
  const weakPoints = dimensions
    .map((dimension) => ({ dimension, score: dimensionAverages[dimension] }))
    .filter((item) => item.score > 0)
    .sort((left, right) => left.score - right.score)
    .slice(0, 2);
  const recentFocus = reports.length > 0 ? reports[reports.length - 1].target_role : null;
  const averageTotalScore = clampStatScore(average(reports.map((report) => report.total_score), 0));
  const existing = db.prepare('SELECT id FROM user_skill_stats WHERE user_id = ?').get(userId);
  const statsId = existing?.id || randomUUID();

  if (existing) {
    db.prepare(
      `UPDATE user_skill_stats
       SET total_interviews = ?, completed_interviews = ?, average_total_score = ?,
           technical_depth_avg = ?, expression_clarity_avg = ?, business_understanding_avg = ?,
           dimension_trends = ?, weak_points = ?, recent_training_focus = ?,
           updated_at = datetime('now')
       WHERE user_id = ?`
    ).run(
      interviewCounts.total_interviews || 0,
      interviewCounts.completed_interviews || 0,
      averageTotalScore,
      dimensionAverages.technical_depth,
      dimensionAverages.expression_clarity,
      dimensionAverages.business_understanding,
      JSON.stringify(dimensionTrends),
      JSON.stringify(weakPoints),
      recentFocus,
      userId
    );
  } else {
    db.prepare(
      `INSERT INTO user_skill_stats (
         id, user_id, total_interviews, completed_interviews, average_total_score,
         technical_depth_avg, expression_clarity_avg, business_understanding_avg,
         dimension_trends, weak_points, recent_training_focus
       )
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      statsId,
      userId,
      interviewCounts.total_interviews || 0,
      interviewCounts.completed_interviews || 0,
      averageTotalScore,
      dimensionAverages.technical_depth,
      dimensionAverages.expression_clarity,
      dimensionAverages.business_understanding,
      JSON.stringify(dimensionTrends),
      JSON.stringify(weakPoints),
      recentFocus
    );
  }

  return findUserSkillStats(userId);
}

function findUserSkillStats(userId) {
  return db.prepare(
    `SELECT id, user_id, total_interviews, completed_interviews, average_total_score,
            technical_depth_avg, expression_clarity_avg, business_understanding_avg,
            dimension_trends, weak_points, recent_training_focus, updated_at
     FROM user_skill_stats
     WHERE user_id = ?`
  ).get(userId);
}

function buildUserDimensionStats(stats) {
  const trends = parseJsonObject(stats.dimension_trends);
  return [
    {
      key: 'technical_depth',
      label: '技术深度',
      average_score: stats.technical_depth_avg,
      trend: trends.technical_depth || 'stable',
    },
    {
      key: 'expression_clarity',
      label: '表达清晰度',
      average_score: stats.expression_clarity_avg,
      trend: trends.expression_clarity || 'stable',
    },
    {
      key: 'business_understanding',
      label: '业务理解',
      average_score: stats.business_understanding_avg,
      trend: trends.business_understanding || 'stable',
    },
  ];
}

app.get('/api/health', (_req, res) => {
  res.json({ ok: true, databasePath: getDatabasePath() });
});

app.get('/api/auth/me', (req, res) => {
  const user = findUserBySession(req);
  res.json({ user: sanitizeUser(user) });
});

app.post('/api/auth/register', async (req, res) => {
  const email = normalizeEmail(req.body.email);
  const password = String(req.body.password || '');
  const name = String(req.body.name || '').trim() || email.split('@')[0] || '新用户';

  if (!isValidEmail(email)) {
    res.status(400).json({ error: '请输入有效邮箱。' });
    return;
  }

  if (password.length < 8) {
    res.status(400).json({ error: '密码至少需要 8 位。' });
    return;
  }

  if (name.length > 60) {
    res.status(400).json({ error: '昵称不能超过 60 个字符。' });
    return;
  }

  const existingUser = db.prepare('SELECT id FROM users WHERE email = ?').get(email);
  if (existingUser) {
    res.status(409).json({ error: '这个邮箱已经注册。' });
    return;
  }

  const userId = randomUUID();
  const passwordHash = await hashPassword(password);

  const createUser = db.transaction(() => {
    db.prepare(
      `INSERT INTO users (id, email, password_hash, name)
       VALUES (?, ?, ?, ?)`
    ).run(userId, email, passwordHash, name);

    db.prepare(
      `INSERT INTO profiles (id, user_id, nickname)
       VALUES (?, ?, ?)`
    ).run(randomUUID(), userId, name);
  });

  createUser();
  createSession(res, userId, req.headers['user-agent']);

  const user = db.prepare(
    `SELECT id, email, name, status, created_at, last_login_at
     FROM users WHERE id = ?`
  ).get(userId);

  res.status(201).json({ user: sanitizeUser(user) });
});

app.post('/api/auth/login', async (req, res) => {
  const email = normalizeEmail(req.body.email);
  const password = String(req.body.password || '');

  if (!isValidEmail(email) || !password) {
    res.status(400).json({ error: '请输入邮箱和密码。' });
    return;
  }

  if (isLoginLimited(req, email)) {
    res.status(429).json({ error: '登录尝试过于频繁，请稍后再试。' });
    return;
  }

  const user = db.prepare(
    `SELECT id, email, password_hash, name, status, created_at, last_login_at
     FROM users WHERE email = ?`
  ).get(email);

  if (!user || user.status !== 'normal') {
    recordFailedLogin(req, email);
    res.status(401).json({ error: '邮箱或密码不正确。' });
    return;
  }

  const passwordOk = await verifyPassword(password, user.password_hash);
  if (!passwordOk) {
    recordFailedLogin(req, email);
    res.status(401).json({ error: '邮箱或密码不正确。' });
    return;
  }

  clearFailedLogins(req, email);
  db.prepare(`UPDATE users SET last_login_at = datetime('now'), updated_at = datetime('now') WHERE id = ?`).run(user.id);
  createSession(res, user.id, req.headers['user-agent']);

  const currentUser = db.prepare(
    `SELECT id, email, name, status, created_at, last_login_at
     FROM users WHERE id = ?`
  ).get(user.id);

  res.json({ user: sanitizeUser(currentUser) });
});

app.post('/api/auth/logout', (req, res) => {
  const token = getCookie(req, sessionCookieName);

  if (token) {
    db.prepare('DELETE FROM sessions WHERE token_hash = ?').run(hashToken(token));
  }

  clearSession(res);
  res.json({ ok: true });
});

app.post('/api/auth/password-reset/request', (req, res) => {
  const email = normalizeEmail(req.body.email);
  const user = isValidEmail(email)
    ? db.prepare('SELECT id FROM users WHERE email = ? AND status = ?').get(email, 'normal')
    : null;

  let devResetToken = null;

  if (user) {
    const token = createToken();
    const tokenHash = hashToken(token);
    const expiresAt = new Date(Date.now() + resetMaxAgeMs).toISOString();

    db.prepare(
      `INSERT INTO password_reset_tokens (id, user_id, token_hash, expires_at)
       VALUES (?, ?, ?, ?)`
    ).run(randomUUID(), user.id, tokenHash, expiresAt);

    if (process.env.NODE_ENV !== 'production') {
      devResetToken = token;
    }
  }

  res.json({
    ok: true,
    message: '如果邮箱存在，我们会发送密码重置链接。',
    devResetToken,
  });
});

app.get('/api/profile', requireAuth, (req, res) => {
  ensureProfile(req.user);
  const profile = findProfileByUserId(req.user.id);

  res.json({ profile });
});

app.put('/api/profile', requireAuth, (req, res) => {
  const parsed = parseProfileInput(req.body, req.user.name);

  if (parsed.error) {
    res.status(400).json({ error: parsed.error });
    return;
  }

  ensureProfile(req.user);
  const { profile } = parsed;

  db.prepare(
    `UPDATE profiles
     SET nickname = ?, avatar_url = ?, target_role = ?, experience_level = ?, company_type = ?,
         target_city = ?, expected_salary = ?, years_of_experience = ?, education_level = ?,
         skills = ?, project_keywords = ?, resume_text = ?, project_experience = ?,
         portfolio_links = ?, preferred_interview_type = ?, preferred_difficulty = ?,
         preferred_interviewer_style = ?, updated_at = datetime('now')
     WHERE user_id = ?`
  ).run(
    profile.nickname,
    profile.avatar_url,
    profile.target_role,
    profile.experience_level,
    profile.company_type,
    profile.target_city,
    profile.expected_salary,
    profile.years_of_experience,
    profile.education_level,
    profile.skills,
    profile.project_keywords,
    profile.resume_text,
    profile.project_experience,
    profile.portfolio_links,
    profile.preferred_interview_type,
    profile.preferred_difficulty,
    profile.preferred_interviewer_style,
    req.user.id
  );

  db.prepare(`UPDATE users SET name = ?, updated_at = datetime('now') WHERE id = ?`).run(profile.nickname, req.user.id);

  const updatedProfile = findProfileByUserId(req.user.id);

  res.json({ profile: updatedProfile });
});

app.post('/api/interviews', requireAuth, (req, res) => {
  const parsed = parseInterviewInput(req.body);

  if (parsed.error) {
    res.status(400).json({ error: parsed.error });
    return;
  }

  const interviewId = randomUUID();
  const { interview } = parsed;

  const createInterview = db.transaction(() => {
    db.prepare(
      `INSERT INTO interview_sessions (
         id, user_id, target_role, experience_level, interview_type, company_context,
         focus_areas, difficulty, interviewer_style, status
       )
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      interviewId,
      req.user.id,
      interview.target_role,
      interview.experience_level,
      interview.interview_type,
      interview.company_context,
      interview.focus_areas,
      interview.difficulty,
      interview.interviewer_style,
      'draft'
    );

    createDefaultAgents(interviewId);
  });

  createInterview();

  const createdInterview = findInterviewByUserId(interviewId, req.user.id);
  res.status(201).json({ interview: createdInterview, agents: listAgentsByInterviewId(interviewId) });
});

app.get('/api/interviews', requireAuth, (req, res) => {
  const status = req.query.status ? normalizeStatus(req.query.status) : null;

  if (req.query.status && !status) {
    res.status(400).json({ error: '面试状态不正确。' });
    return;
  }

  const interviews = status
    ? db.prepare(
        `SELECT id, user_id, target_role, experience_level, interview_type, company_context,
                focus_areas, difficulty, interviewer_style, status, created_at, updated_at,
                started_at, completed_at
         FROM interview_sessions
         WHERE user_id = ? AND status = ?
         ORDER BY datetime(updated_at) DESC, datetime(created_at) DESC`
      ).all(req.user.id, status)
    : db.prepare(
        `SELECT id, user_id, target_role, experience_level, interview_type, company_context,
                focus_areas, difficulty, interviewer_style, status, created_at, updated_at,
                started_at, completed_at
         FROM interview_sessions
         WHERE user_id = ?
         ORDER BY datetime(updated_at) DESC, datetime(created_at) DESC`
      ).all(req.user.id);

  res.json({ interviews });
});

app.get('/api/interviews/:id', requireAuth, (req, res) => {
  const interview = findInterviewByUserId(req.params.id, req.user.id);

  if (!interview) {
    res.status(404).json({ error: '面试不存在。' });
    return;
  }

  res.json({ interview });
});

app.get('/api/interviews/:id/agents', requireAuth, (req, res) => {
  const interview = findInterviewByUserId(req.params.id, req.user.id);

  if (!interview) {
    res.status(404).json({ error: '面试不存在。' });
    return;
  }

  ensureDefaultAgents(interview.id);
  res.json({ agents: listAgentsByInterviewId(interview.id) });
});

app.post('/api/interviews/:id/agents', requireAuth, (req, res) => {
  const interview = findInterviewByUserId(req.params.id, req.user.id);

  if (!interview) {
    res.status(404).json({ error: '面试不存在。' });
    return;
  }

  if (interview.status === 'completed') {
    res.status(409).json({ error: '已完成的面试不能新增 Agent。' });
    return;
  }

  const parsed = parseAgentInput(req.body);
  if (parsed.error) {
    res.status(400).json({ error: parsed.error });
    return;
  }

  const agentId = randomUUID();
  const { agent } = parsed;
  const orderIndex = Number.isInteger(agent.order_index) ? agent.order_index : nextAgentOrderIndex(interview.id);

  db.prepare(
    `INSERT INTO interview_agents (
       id, interview_id, agent_name, agent_type, agent_role, strategy, order_index, status
     )
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(
    agentId,
    interview.id,
    agent.agent_name,
    agent.agent_type,
    agent.agent_role,
    agent.strategy,
    orderIndex,
    agent.status || 'pending'
  );

  res.status(201).json({ agent: findAgentByInterviewId(agentId, interview.id) });
});

app.patch('/api/interviews/:id/agents/:agentId', requireAuth, (req, res) => {
  const interview = findInterviewByUserId(req.params.id, req.user.id);

  if (!interview) {
    res.status(404).json({ error: '面试不存在。' });
    return;
  }

  if (interview.status === 'completed') {
    res.status(409).json({ error: '已完成的面试不能修改 Agent。' });
    return;
  }

  const existingAgent = findAgentByInterviewId(req.params.agentId, interview.id);
  if (!existingAgent) {
    res.status(404).json({ error: 'Agent 不存在。' });
    return;
  }

  const parsed = parseAgentInput(req.body, { partial: true });
  if (parsed.error) {
    res.status(400).json({ error: parsed.error });
    return;
  }

  const nextAgent = { ...existingAgent, ...parsed.agent };
  db.prepare(
    `UPDATE interview_agents
     SET agent_name = ?, agent_type = ?, agent_role = ?, strategy = ?, order_index = ?,
         status = ?, updated_at = datetime('now')
     WHERE id = ? AND interview_id = ?`
  ).run(
    nextAgent.agent_name,
    nextAgent.agent_type,
    nextAgent.agent_role,
    nextAgent.strategy,
    nextAgent.order_index,
    nextAgent.status,
    existingAgent.id,
    interview.id
  );

  res.json({ agent: findAgentByInterviewId(existingAgent.id, interview.id) });
});

app.get('/api/interviews/:id/messages', requireAuth, (req, res) => {
  const interview = findInterviewByUserId(req.params.id, req.user.id);

  if (!interview) {
    res.status(404).json({ error: '面试不存在。' });
    return;
  }

  res.json({ messages: listMessagesByInterviewId(interview.id) });
});

app.post('/api/interviews/:id/realtime/sdp', requireAuth, express.text({ type: ['application/sdp', 'text/plain'], limit: '256kb' }), async (req, res) => {
  const interview = findInterviewByUserId(req.params.id, req.user.id);

  if (!interview) {
    res.status(404).json({ error: '面试不存在。' });
    return;
  }

  if (interview.status === 'completed') {
    res.status(409).json({ error: '已完成的面试不能开启语音通话。' });
    return;
  }

  const apiKey = process.env.OPENAI_API_KEY || process.env.AI_API_KEY;
  if (!apiKey || apiKey === 'your-api-key-here') {
    res.status(500).json({ error: '服务端未配置 OPENAI_API_KEY，无法开启实时语音。' });
    return;
  }

  const sdp = String(req.body || '').trim();
  if (!sdp) {
    res.status(400).json({ error: '缺少 WebRTC SDP offer。' });
    return;
  }

  const agents = listAgentsByInterviewId(interview.id);
  const messages = listMessagesByInterviewId(interview.id);
  const formData = new FormData();
  formData.set('sdp', sdp);
  formData.set('session', JSON.stringify(buildRealtimeSessionConfig(interview, agents, messages)));

  try {
    const response = await fetch('https://api.openai.com/v1/realtime/calls', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'OpenAI-Safety-Identifier': hashToken(req.user.id),
      },
      body: formData,
    });

    const answerSdp = await response.text();
    if (!response.ok) {
      let errorMessage = '创建实时语音会话失败。';
      try {
        errorMessage = JSON.parse(answerSdp).error?.message || errorMessage;
      } catch {
        errorMessage = answerSdp || errorMessage;
      }
      res.status(response.status).json({ error: errorMessage });
      return;
    }

    res.type('application/sdp').send(answerSdp);
  } catch (error) {
    res.status(502).json({ error: `无法连接 OpenAI Realtime API：${error.message}` });
  }
});

app.post('/api/interviews/:id/messages', requireAuth, (req, res) => {
  const interview = findInterviewByUserId(req.params.id, req.user.id);

  if (!interview) {
    res.status(404).json({ error: '面试不存在。' });
    return;
  }

  if (interview.status === 'completed') {
    res.status(409).json({ error: '已完成的面试不能继续写入消息。' });
    return;
  }

  const parsed = parseMessageInput(req.body);
  if (parsed.error) {
    res.status(400).json({ error: parsed.error });
    return;
  }

  const { message } = parsed;
  if (message.agent_id && !findAgentByInterviewId(message.agent_id, interview.id)) {
    res.status(400).json({ error: 'Agent 不属于当前面试。' });
    return;
  }

  const messageId = randomUUID();
  const orderIndex = nextMessageOrderIndex(interview.id);

  db.prepare(
    `INSERT INTO interview_messages (
       id, interview_id, agent_id, sender_type, message_type, content, transcript_text, order_index
     )
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(
    messageId,
    interview.id,
    message.agent_id,
    message.sender_type,
    message.message_type,
    message.content,
    message.transcript_text,
    orderIndex
  );

  db.prepare(`UPDATE interview_sessions SET updated_at = datetime('now') WHERE id = ? AND user_id = ?`).run(interview.id, req.user.id);

  res.status(201).json({ message: findMessageByInterviewId(messageId, interview.id) });
});

app.post('/api/interviews/:id/evaluations', requireAuth, (req, res) => {
  const interview = findInterviewByUserId(req.params.id, req.user.id);

  if (!interview) {
    res.status(404).json({ error: '面试不存在。' });
    return;
  }

  const parsed = parseEvaluationInput(req.body);
  if (parsed.error) {
    res.status(400).json({ error: parsed.error });
    return;
  }

  const message = findMessageByInterviewId(parsed.messageId, interview.id);
  if (!message) {
    res.status(404).json({ error: '消息不存在。' });
    return;
  }

  if (message.sender_type !== 'candidate' || !['answer', 'transcript'].includes(message.message_type)) {
    res.status(400).json({ error: '只能评价候选人的回答消息。' });
    return;
  }

  const existingEvaluation = findEvaluationByMessageId(interview.id, message.id);
  if (existingEvaluation) {
    res.json({ evaluation: existingEvaluation });
    return;
  }

  const evaluationId = randomUUID();
  const evaluation = generateMockEvaluation(message);

  db.prepare(
    `INSERT INTO interview_evaluations (
       id, interview_id, message_id, agent_id, score, strengths, issues, suggestions, dimension_scores
     )
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(
    evaluationId,
    interview.id,
    message.id,
    message.agent_id,
    evaluation.score,
    evaluation.strengths,
    evaluation.issues,
    evaluation.suggestions,
    JSON.stringify(evaluation.dimension_scores)
  );

  db.prepare(`UPDATE interview_sessions SET updated_at = datetime('now') WHERE id = ? AND user_id = ?`).run(interview.id, req.user.id);

  res.status(201).json({ evaluation: findEvaluationById(interview.id, evaluationId) });
});

app.get('/api/interviews/:id/evaluations', requireAuth, (req, res) => {
  const interview = findInterviewByUserId(req.params.id, req.user.id);

  if (!interview) {
    res.status(404).json({ error: '面试不存在。' });
    return;
  }

  res.json({ evaluations: listEvaluationsByInterviewId(interview.id) });
});

app.post('/api/interviews/:id/report', requireAuth, (req, res) => {
  const interview = findInterviewByUserId(req.params.id, req.user.id);

  if (!interview) {
    res.status(404).json({ error: '面试不存在。' });
    return;
  }

  if (interview.status !== 'completed') {
    res.status(409).json({ error: '请先结束面试，再生成报告。' });
    return;
  }

  const agents = listAgentsByInterviewId(interview.id);
  const messages = listMessagesByInterviewId(interview.id);
  const evaluations = listEvaluationsByInterviewId(interview.id);
  const report = generateMockReport(interview, agents, messages, evaluations);
  const existingReport = findReportByInterviewId(interview.id, req.user.id);
  const reportId = existingReport?.id || randomUUID();

  if (existingReport) {
    db.prepare(
      `UPDATE interview_reports
       SET total_score = ?, grade = ?, pass_recommendation = ?, ability_radar = ?,
           agent_feedback = ?, timeline_review = ?, summary = ?, suggestions = ?,
           updated_at = datetime('now')
       WHERE id = ? AND user_id = ?`
    ).run(
      report.total_score,
      report.grade,
      report.pass_recommendation,
      JSON.stringify(report.ability_radar),
      JSON.stringify(report.agent_feedback),
      JSON.stringify(report.timeline_review),
      report.summary,
      report.suggestions,
      reportId,
      req.user.id
    );

    refreshUserSkillStats(req.user.id);
    res.json({ report: findReportById(reportId, req.user.id) });
    return;
  }

  db.prepare(
    `INSERT INTO interview_reports (
       id, user_id, interview_id, total_score, grade, pass_recommendation,
       ability_radar, agent_feedback, timeline_review, summary, suggestions
     )
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(
    reportId,
    req.user.id,
    interview.id,
    report.total_score,
    report.grade,
    report.pass_recommendation,
    JSON.stringify(report.ability_radar),
    JSON.stringify(report.agent_feedback),
    JSON.stringify(report.timeline_review),
    report.summary,
    report.suggestions
  );

  refreshUserSkillStats(req.user.id);
  res.status(201).json({ report: findReportById(reportId, req.user.id) });
});

app.get('/api/interviews/:id/report', requireAuth, (req, res) => {
  const interview = findInterviewByUserId(req.params.id, req.user.id);

  if (!interview) {
    res.status(404).json({ error: '面试不存在。' });
    return;
  }

  const report = findReportByInterviewId(interview.id, req.user.id);
  if (!report) {
    res.status(404).json({ error: '报告不存在。' });
    return;
  }

  res.json({ report });
});

app.get('/api/reports', requireAuth, (req, res) => {
  res.json({ reports: listReportsByUserId(req.user.id) });
});

app.get('/api/reports/:id', requireAuth, (req, res) => {
  const report = findReportById(req.params.id, req.user.id);

  if (!report) {
    res.status(404).json({ error: '报告不存在。' });
    return;
  }

  res.json({ report });
});

app.get('/api/stats/me', requireAuth, (req, res) => {
  const stats = refreshUserSkillStats(req.user.id);
  res.json({ stats });
});

app.get('/api/stats/me/dimensions', requireAuth, (req, res) => {
  const stats = refreshUserSkillStats(req.user.id);
  res.json({ dimensions: buildUserDimensionStats(stats) });
});

app.patch('/api/interviews/:id', requireAuth, (req, res) => {
  const interview = findInterviewByUserId(req.params.id, req.user.id);

  if (!interview) {
    res.status(404).json({ error: '面试不存在。' });
    return;
  }

  if (interview.status === 'completed') {
    res.status(409).json({ error: '已完成的面试不能继续修改。' });
    return;
  }

  const parsed = parseInterviewInput(req.body, { partial: true });
  if (parsed.error) {
    res.status(400).json({ error: parsed.error });
    return;
  }

  const nextInterview = { ...interview, ...parsed.interview };
  db.prepare(
    `UPDATE interview_sessions
     SET target_role = ?, experience_level = ?, interview_type = ?, company_context = ?,
         focus_areas = ?, difficulty = ?, interviewer_style = ?, updated_at = datetime('now')
     WHERE id = ? AND user_id = ?`
  ).run(
    nextInterview.target_role,
    nextInterview.experience_level,
    nextInterview.interview_type,
    nextInterview.company_context,
    nextInterview.focus_areas,
    nextInterview.difficulty,
    nextInterview.interviewer_style,
    interview.id,
    req.user.id
  );

  res.json({ interview: findInterviewByUserId(interview.id, req.user.id) });
});

app.post('/api/interviews/:id/start', requireAuth, (req, res) => {
  const interview = findInterviewByUserId(req.params.id, req.user.id);

  if (!interview) {
    res.status(404).json({ error: '面试不存在。' });
    return;
  }

  if (interview.status === 'completed') {
    res.status(409).json({ error: '已完成的面试不能重新开始。' });
    return;
  }

  if (interview.status === 'draft') {
    db.prepare(
      `UPDATE interview_sessions
       SET status = 'running', started_at = COALESCE(started_at, datetime('now')),
           updated_at = datetime('now')
       WHERE id = ? AND user_id = ?`
    ).run(interview.id, req.user.id);
  }

  res.json({ interview: findInterviewByUserId(interview.id, req.user.id) });
});

app.post('/api/interviews/:id/finish', requireAuth, (req, res) => {
  const interview = findInterviewByUserId(req.params.id, req.user.id);

  if (!interview) {
    res.status(404).json({ error: '面试不存在。' });
    return;
  }

  if (interview.status === 'completed') {
    res.json({ interview });
    return;
  }

  db.prepare(
    `UPDATE interview_sessions
     SET status = 'completed', started_at = COALESCE(started_at, datetime('now')),
         completed_at = COALESCE(completed_at, datetime('now')), updated_at = datetime('now')
     WHERE id = ? AND user_id = ?`
  ).run(interview.id, req.user.id);

  res.json({ interview: findInterviewByUserId(interview.id, req.user.id) });
});

const distDir = join(__dirname, '..', 'dist');
if (existsSync(distDir)) {
  app.use(express.static(distDir));
  app.use((req, res, next) => {
    if (req.path.startsWith('/api')) {
      next();
      return;
    }

    res.sendFile(join(distDir, 'index.html'));
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  app.listen(port, '127.0.0.1', () => {
    console.log(`Auth server running at http://127.0.0.1:${port}`);
    console.log(`SQLite database: ${getDatabasePath()}`);
  });
}

export default app;
