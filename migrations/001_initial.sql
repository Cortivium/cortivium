-- Cortivium initial schema for SQLite

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    name TEXT DEFAULT '',
    access_level INTEGER DEFAULT 1,
    tier TEXT DEFAULT 'free',
    created_at TEXT DEFAULT (datetime('now')),
    last_login TEXT
);

CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    owner_email TEXT,
    is_active INTEGER DEFAULT 1,
    allowed_plugins TEXT,
    rate_limit_per_minute INTEGER DEFAULT 8,
    rate_limit_per_hour INTEGER DEFAULT 45,
    rate_limit_per_day INTEGER DEFAULT 150,
    total_requests INTEGER DEFAULT 0,
    last_used_at TEXT,
    expires_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS usage_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_id INTEGER NOT NULL,
    tool_name TEXT NOT NULL DEFAULT '',
    plugin_name TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER DEFAULT 0,
    error_message TEXT,
    request_size_bytes INTEGER,
    response_size_bytes INTEGER,
    client_ip TEXT,
    user_agent TEXT,
    session_id TEXT,
    request_timestamp TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (api_key_id) REFERENCES api_keys(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_usage_logs_timestamp ON usage_logs(request_timestamp);
CREATE INDEX IF NOT EXISTS idx_usage_logs_key ON usage_logs(api_key_id);

CREATE TABLE IF NOT EXISTS plugins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    display_name TEXT,
    description TEXT,
    version TEXT DEFAULT '1.0.0',
    is_enabled INTEGER DEFAULT 1,
    is_public INTEGER DEFAULT 0,
    total_calls INTEGER DEFAULT 0,
    tool_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plugin_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    total_calls INTEGER DEFAULT 0,
    FOREIGN KEY (plugin_id) REFERENCES plugins(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ghost_scripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    display_name TEXT,
    description TEXT,
    trigger_phrases TEXT,
    type TEXT NOT NULL DEFAULT 'skill',
    instructions TEXT,
    commands TEXT,
    parameters TEXT,
    is_enabled INTEGER DEFAULT 1,
    execution_count INTEGER DEFAULT 0,
    last_executed_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(api_key_id, name),
    FOREIGN KEY (api_key_id) REFERENCES api_keys(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ghost_scripts_key ON ghost_scripts(api_key_id);
CREATE INDEX IF NOT EXISTS idx_ghost_scripts_enabled ON ghost_scripts(api_key_id, is_enabled);

CREATE TABLE IF NOT EXISTS ghost_creation_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_id INTEGER NOT NULL,
    session_token TEXT NOT NULL UNIQUE,
    name TEXT,
    display_name TEXT,
    description TEXT,
    trigger_phrases TEXT,
    commands TEXT DEFAULT '[]',
    parameters TEXT,
    state TEXT DEFAULT 'gathering_info',
    context TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT,
    FOREIGN KEY (api_key_id) REFERENCES api_keys(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ghost_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ghost_script_id INTEGER NOT NULL,
    api_key_id INTEGER NOT NULL,
    executed_at TEXT DEFAULT (datetime('now')),
    success INTEGER DEFAULT 1,
    duration_ms INTEGER,
    error_message TEXT,
    parameters_used TEXT,
    FOREIGN KEY (ghost_script_id) REFERENCES ghost_scripts(id) ON DELETE CASCADE,
    FOREIGN KEY (api_key_id) REFERENCES api_keys(id) ON DELETE CASCADE
)
