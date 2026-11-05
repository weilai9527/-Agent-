"""面试输入结构。生产者和只读评估投影使用相同的字段合同，但在各自数据库建表。"""

SESSION = """CREATE TABLE IF NOT EXISTS interview_sessions (
    id CHAR(36) PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    target_role VARCHAR(160) NOT NULL,
    experience_level VARCHAR(80),
    interview_type VARCHAR(120),
    company_context VARCHAR(240),
    focus_areas TEXT,
    resume_context MEDIUMTEXT,
    difficulty VARCHAR(80),
    interviewer_style VARCHAR(120),
    status VARCHAR(40) NOT NULL DEFAULT 'draft',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at DATETIME NULL,
    completed_at DATETIME NULL
)"""

AGENT = """CREATE TABLE IF NOT EXISTS interview_agents (
    id CHAR(36) PRIMARY KEY,
    interview_id CHAR(36) NOT NULL,
    agent_name VARCHAR(160) NOT NULL,
    agent_type VARCHAR(80) NOT NULL,
    agent_role TEXT NOT NULL,
    strategy TEXT,
    order_index INT NOT NULL DEFAULT 0,
    status VARCHAR(40) NOT NULL DEFAULT 'pending',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE
)"""

MESSAGE = """CREATE TABLE IF NOT EXISTS interview_messages (
    id CHAR(36) PRIMARY KEY,
    interview_id CHAR(36) NOT NULL,
    agent_id CHAR(36),
    sender_type VARCHAR(40) NOT NULL,
    message_type VARCHAR(40) NOT NULL,
    content MEDIUMTEXT NOT NULL,
    transcript_text MEDIUMTEXT,
    source VARCHAR(40) NOT NULL DEFAULT 'text',
    source_ref VARCHAR(128),
    reply_to_message_id CHAR(36),
    round_agent_id CHAR(36),
    order_index INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES interview_agents(id) ON DELETE SET NULL,
    FOREIGN KEY (reply_to_message_id) REFERENCES interview_messages(id) ON DELETE SET NULL,
    FOREIGN KEY (round_agent_id) REFERENCES interview_agents(id) ON DELETE SET NULL
)"""

TURN = """CREATE TABLE IF NOT EXISTS interview_turns (
    interview_id CHAR(36) NOT NULL, submission_id VARCHAR(128) NOT NULL, question_id CHAR(36) NOT NULL,
    agent_id CHAR(36), answer_id CHAR(36), next_question_id CHAR(36), next_agent_id CHAR(36),
    action VARCHAR(32) NOT NULL, decision_json MEDIUMTEXT NOT NULL,
    PRIMARY KEY(interview_id,submission_id), FOREIGN KEY(interview_id) REFERENCES interview_sessions(id)
)"""

STRATEGY = """CREATE TABLE IF NOT EXISTS interview_strategy_snapshots (
    interview_id CHAR(36) PRIMARY KEY, config MEDIUMTEXT NOT NULL,
    FOREIGN KEY(interview_id) REFERENCES interview_sessions(id)
)"""

INPUT_TABLES = (SESSION, AGENT, MESSAGE, TURN, STRATEGY)
