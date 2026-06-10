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

  CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions(token_hash);
  CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
  CREATE INDEX IF NOT EXISTS idx_password_reset_token_hash ON password_reset_tokens(token_hash);
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
