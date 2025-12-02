PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS file_registry (
  file_id TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  sha256 TEXT,
  size_bytes INTEGER,
  gz_mtime TEXT,
  ingested_at TEXT,
  status TEXT
);

CREATE TABLE IF NOT EXISTS run_session (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id TEXT,
  pass_type TEXT,
  config_json TEXT,
  started_at TEXT,
  ended_at TEXT,
  total_lines INTEGER,
  preprocessed_lines INTEGER,
  unmatched_lines INTEGER,
  matched_lines INTEGER,  -- 新增：整文件匹配总数
  status TEXT,
  FOREIGN KEY(file_id) REFERENCES file_registry(file_id)
);

CREATE TABLE IF NOT EXISTS module (
  mod TEXT PRIMARY KEY,
  description TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS submodule (
  smod TEXT PRIMARY KEY,
  mod TEXT,
  description TEXT,
  created_at TEXT,
  updated_at TEXT,
  FOREIGN KEY(mod) REFERENCES module(mod)
);

CREATE TABLE IF NOT EXISTS regex_template (
  template_id INTEGER PRIMARY KEY AUTOINCREMENT,
  pattern TEXT NOT NULL,
  sample_log TEXT,
  version INTEGER DEFAULT 1,
  is_active INTEGER DEFAULT 1,
  semantic_info TEXT,
  advise TEXT,
  created_at TEXT,
  updated_at TEXT,
  source TEXT
);

CREATE TABLE IF NOT EXISTS template_history (
  history_id INTEGER PRIMARY KEY AUTOINCREMENT,
  template_id INTEGER,
  pattern TEXT,
  sample_log TEXT,
  version INTEGER,
  created_at TEXT,
  source TEXT,
  note TEXT,
  FOREIGN KEY(template_id) REFERENCES regex_template(template_id)
);

CREATE TABLE IF NOT EXISTS unmatched_log (
  um_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER,
  file_id TEXT,
  key_text TEXT,
  raw_log TEXT,
  buffered INTEGER DEFAULT 0,
  reason TEXT,
  created_at TEXT,
  FOREIGN KEY(run_id) REFERENCES run_session(run_id),
  FOREIGN KEY(file_id) REFERENCES file_registry(file_id)
);

CREATE TABLE IF NOT EXISTS log_match_summary (
  summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER,
  file_id TEXT,
  template_id INTEGER,
  mod TEXT,
  smod TEXT,
  classification TEXT,
  level TEXT,
  thread_id TEXT,
  first_ts TEXT,
  last_ts TEXT,
  line_count INTEGER,
  updated_at TEXT,
  FOREIGN KEY(run_id) REFERENCES run_session(run_id),
  FOREIGN KEY(file_id) REFERENCES file_registry(file_id),
  FOREIGN KEY(template_id) REFERENCES regex_template(template_id)
);

CREATE TABLE IF NOT EXISTS key_time_bucket (
  bucket_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER,
  file_id TEXT,
  template_id INTEGER,
  mod TEXT,
  smod TEXT,
  classification TEXT,
  level TEXT,
  thread_id TEXT,
  bucket_granularity TEXT,
  bucket_start TEXT,
  count_in_bucket INTEGER,
  updated_at TEXT,
  FOREIGN KEY(run_id) REFERENCES run_session(run_id),
  FOREIGN KEY(file_id) REFERENCES file_registry(file_id),
  FOREIGN KEY(template_id) REFERENCES regex_template(template_id)
);