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
  const profile = db.prepare(
    `SELECT id, user_id, nickname, avatar_url, target_role, experience_level, company_type,
            target_city, expected_salary, years_of_experience, education_level, skills,
            project_keywords, resume_text, project_experience, portfolio_links,
            preferred_interview_type, preferred_difficulty, preferred_interviewer_style,
            created_at, updated_at
     FROM profiles
     WHERE user_id = ?`
  ).get(req.user.id);

  res.json({ profile });
});

app.put('/api/profile', requireAuth, (req, res) => {
  const profile = {
    nickname: String(req.body.nickname || '').trim().slice(0, 60) || req.user.name,
    avatar_url: String(req.body.avatar_url || '').trim().slice(0, 500) || null,
    target_role: String(req.body.target_role || '').trim().slice(0, 80) || null,
    experience_level: String(req.body.experience_level || '').trim().slice(0, 40) || null,
    company_type: String(req.body.company_type || '').trim().slice(0, 80) || null,
    target_city: String(req.body.target_city || '').trim().slice(0, 80) || null,
    expected_salary: String(req.body.expected_salary || '').trim().slice(0, 80) || null,
    years_of_experience: String(req.body.years_of_experience || '').trim().slice(0, 40) || null,
    education_level: String(req.body.education_level || '').trim().slice(0, 60) || null,
    skills: String(req.body.skills || '').trim().slice(0, 500) || null,
    project_keywords: String(req.body.project_keywords || '').trim().slice(0, 500) || null,
    resume_text: String(req.body.resume_text || '').trim().slice(0, 12000) || null,
    project_experience: String(req.body.project_experience || '').trim().slice(0, 12000) || null,
    portfolio_links: String(req.body.portfolio_links || '').trim().slice(0, 1000) || null,
    preferred_interview_type: String(req.body.preferred_interview_type || '').trim().slice(0, 60) || null,
    preferred_difficulty: String(req.body.preferred_difficulty || '').trim().slice(0, 40) || null,
    preferred_interviewer_style: String(req.body.preferred_interviewer_style || '').trim().slice(0, 60) || null,
  };

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

  const updatedProfile = db.prepare(
    `SELECT id, user_id, nickname, avatar_url, target_role, experience_level, company_type,
            target_city, expected_salary, years_of_experience, education_level, skills,
            project_keywords, resume_text, project_experience, portfolio_links,
            preferred_interview_type, preferred_difficulty, preferred_interviewer_style,
            created_at, updated_at
     FROM profiles
     WHERE user_id = ?`
  ).get(req.user.id);

  res.json({ profile: updatedProfile });
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

app.listen(port, '127.0.0.1', () => {
  console.log(`Auth server running at http://127.0.0.1:${port}`);
  console.log(`SQLite database: ${getDatabasePath()}`);
});
