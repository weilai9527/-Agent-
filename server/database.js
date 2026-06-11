import Database from 'better-sqlite3';
import { mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const dataDir = join(__dirname, '..', 'data');
const databasePath = process.env.DATABASE_PATH || join(dataDir, 'app.sqlite');

mkdirSync(dirname(databasePath), { recursive: true });

export const db = new Database(databasePath);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'normal',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_at TEXT
  );

  CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE,
    nickname TEXT,
    target_role TEXT,
    experience_level TEXT,
    resume_text TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    user_agent TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    used_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS interview_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    target_role TEXT NOT NULL,
    experience_level TEXT,
    interview_type TEXT,
    company_context TEXT,
    focus_areas TEXT,
    difficulty TEXT,
    interviewer_style TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    started_at TEXT,
    completed_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS interview_agents (
    id TEXT PRIMARY KEY,
    interview_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    agent_role TEXT NOT NULL,
    strategy TEXT,
    order_index INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS interview_messages (
    id TEXT PRIMARY KEY,
    interview_id TEXT NOT NULL,
    agent_id TEXT,
    sender_type TEXT NOT NULL,
    message_type TEXT NOT NULL,
    content TEXT NOT NULL,
    transcript_text TEXT,
    order_index INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES interview_agents(id) ON DELETE SET NULL
  );

  CREATE TABLE IF NOT EXISTS interview_evaluations (
    id TEXT PRIMARY KEY,
    interview_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    agent_id TEXT,
    score INTEGER NOT NULL,
    strengths TEXT NOT NULL,
    issues TEXT NOT NULL,
    suggestions TEXT NOT NULL,
    dimension_scores TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(interview_id, message_id),
    FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES interview_messages(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES interview_agents(id) ON DELETE SET NULL
  );

  CREATE TABLE IF NOT EXISTS interview_reports (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    interview_id TEXT NOT NULL UNIQUE,
    total_score INTEGER NOT NULL,
    grade TEXT NOT NULL,
    pass_recommendation TEXT NOT NULL,
    ability_radar TEXT NOT NULL,
    agent_feedback TEXT NOT NULL,
    timeline_review TEXT NOT NULL,
    summary TEXT NOT NULL,
    suggestions TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS user_skill_stats (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE,
    total_interviews INTEGER NOT NULL DEFAULT 0,
    completed_interviews INTEGER NOT NULL DEFAULT 0,
    average_total_score INTEGER NOT NULL DEFAULT 0,
    technical_depth_avg INTEGER NOT NULL DEFAULT 0,
    expression_clarity_avg INTEGER NOT NULL DEFAULT 0,
    business_understanding_avg INTEGER NOT NULL DEFAULT 0,
    dimension_trends TEXT NOT NULL,
    weak_points TEXT NOT NULL,
    recent_training_focus TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
  );

  CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions(token_hash);
  CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
  CREATE INDEX IF NOT EXISTS idx_password_reset_token_hash ON password_reset_tokens(token_hash);
  CREATE INDEX IF NOT EXISTS idx_interview_sessions_user_id ON interview_sessions(user_id);
  CREATE INDEX IF NOT EXISTS idx_interview_sessions_status ON interview_sessions(status);
  CREATE INDEX IF NOT EXISTS idx_interview_agents_interview_id ON interview_agents(interview_id);
  CREATE INDEX IF NOT EXISTS idx_interview_messages_interview_id ON interview_messages(interview_id);
  CREATE INDEX IF NOT EXISTS idx_interview_messages_agent_id ON interview_messages(agent_id);
  CREATE INDEX IF NOT EXISTS idx_interview_evaluations_interview_id ON interview_evaluations(interview_id);
  CREATE INDEX IF NOT EXISTS idx_interview_evaluations_message_id ON interview_evaluations(message_id);
  CREATE INDEX IF NOT EXISTS idx_interview_reports_user_id ON interview_reports(user_id);
  CREATE INDEX IF NOT EXISTS idx_interview_reports_interview_id ON interview_reports(interview_id);
  CREATE INDEX IF NOT EXISTS idx_user_skill_stats_user_id ON user_skill_stats(user_id);
`);

const profileColumns = [
  ['avatar_url', 'TEXT'],
  ['company_type', 'TEXT'],
  ['target_city', 'TEXT'],
  ['expected_salary', 'TEXT'],
  ['years_of_experience', 'TEXT'],
  ['education_level', 'TEXT'],
  ['skills', 'TEXT'],
  ['project_keywords', 'TEXT'],
  ['project_experience', 'TEXT'],
  ['portfolio_links', 'TEXT'],
  ['preferred_interview_type', 'TEXT'],
  ['preferred_difficulty', 'TEXT'],
  ['preferred_interviewer_style', 'TEXT'],
];

const existingProfileColumns = new Set(db.prepare('PRAGMA table_info(profiles)').all().map((column) => column.name));

for (const [name, type] of profileColumns) {
  if (!existingProfileColumns.has(name)) {
    db.prepare(`ALTER TABLE profiles ADD COLUMN ${name} ${type}`).run();
  }
}

export function getDatabasePath() {
  return databasePath;
}
