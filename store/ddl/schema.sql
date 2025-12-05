PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS FILE_REGISTRY (
  file_id TEXT PRIMARY KEY,
  path TEXT,
  sha256 TEXT,
  size_bytes INTEGER,
  gz_mtime TEXT,
  ingested_at TEXT,
  status TEXT
);
CREATE TABLE IF NOT EXISTS RUN_SESSION (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id TEXT,
  pass_type TEXT,
  config TEXT,
  started_at TEXT,
  ended_at TEXT,
  total_lines INTEGER,
  preprocessed_lines INTEGER,
  matched_lines INTEGER,
  unmatched_lines INTEGER,
  status TEXT,
  FOREIGN KEY(file_id) REFERENCES FILE_REGISTRY(file_id)
);
CREATE TABLE IF NOT EXISTS MODULE (
  mod TEXT PRIMARY KEY,
  description TEXT,
  created_at TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS SUBMODULE (
  smod TEXT PRIMARY KEY,
  mod TEXT,
  description TEXT,
  created_at TEXT,
  updated_at TEXT,
  FOREIGN KEY(mod) REFERENCES MODULE(mod)
);
CREATE TABLE IF NOT EXISTS REGEX_TEMPLATE (
  template_id INTEGER PRIMARY KEY AUTOINCREMENT,
  pattern TEXT,
  sample_log TEXT,
  pattern_nomal TEXT,
  pattern TEXT,
  version INTEGER,
  is_active INTEGER,
  semantic_info TEXT,
  created_at TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS TEMPLATE_HISTORY (
  history_id INTEGER PRIMARY KEY AUTOINCREMENT,
  template_id INTEGER,
  pattern TEXT,
  sample_log TEXT,
  version INTEGER,
  created_at TEXT,
  source TEXT,
  note TEXT,
  FOREIGN KEY(template_id) REFERENCES REGEX_TEMPLATE(template_id)
);
CREATE TABLE IF NOT EXISTS UNMATCHED_LOG (
  um_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER,
  file_id TEXT,
  key_text TEXT,
  raw_log TEXT,
  buffered INTEGER,
  buffer_id INTEGER,
  reason TEXT,
  FOREIGN KEY(run_id) REFERENCES RUN_SESSION(run_id),
  FOREIGN KEY(file_id) REFERENCES FILE_REGISTRY(file_id)
);
CREATE TABLE IF NOT EXISTS LOG_MATCH_SUMMARY (
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
  FOREIGN KEY(run_id) REFERENCES RUN_SESSION(run_id),
  FOREIGN KEY(file_id) REFERENCES FILE_REGISTRY(file_id),
  FOREIGN KEY(template_id) REFERENCES REGEX_TEMPLATE(template_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_summary_comp
ON LOG_MATCH_SUMMARY(file_id, template_id, mod, smod, level, thread_id);
CREATE TABLE IF NOT EXISTS KEY_TIME_BUCKET (
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
  FOREIGN KEY(run_id) REFERENCES RUN_SESSION(run_id),
  FOREIGN KEY(file_id) REFERENCES FILE_REGISTRY(file_id),
  FOREIGN KEY(template_id) REFERENCES REGEX_TEMPLATE(template_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_bucket_comp
ON KEY_TIME_BUCKET(file_id, template_id, mod, smod, level, thread_id, bucket_start, bucket_granularity);
CREATE TABLE IF NOT EXISTS KEY_TIME_POINT (
  point_id INTEGER PRIMARY KEY AUTOINCREMENT,
  bucket_id INTEGER,
  file_id TEXT,
  ts TEXT,
  count_at_ts INTEGER,
  FOREIGN KEY(bucket_id) REFERENCES KEY_TIME_BUCKET(bucket_id),
  FOREIGN KEY(file_id) REFERENCES FILE_REGISTRY(file_id)
);
CREATE TABLE IF NOT EXISTS BUFFER_GROUP (
  buffer_id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope TEXT,
  size_threshold INTEGER,
  current_size INTEGER,
  created_at TEXT,
  status TEXT,
  last_triggered_at TEXT,
  new_ratio REAL,
  catalog_version TEXT
);
CREATE TABLE IF NOT EXISTS BUFFER_ITEM (
  item_id INTEGER PRIMARY KEY AUTOINCREMENT,
  buffer_id INTEGER,
  run_id INTEGER,
  key_text TEXT,
  signature TEXT,
  sample_count INTEGER,
  raw_log TEXT,
  FOREIGN KEY(buffer_id) REFERENCES BUFFER_GROUP(buffer_id),
  FOREIGN KEY(run_id) REFERENCES RUN_SESSION(run_id)
);
CREATE TABLE IF NOT EXISTS LLM_TASK (
  llm_task_id INTEGER PRIMARY KEY AUTOINCREMENT,
  use_case TEXT,
  buffer_id INTEGER,
  model TEXT,
  prompt_version TEXT,
  phase TEXT,
  started_at TEXT,
  finished_at TEXT,
  status TEXT,
  input_count INTEGER,
  output_json TEXT,
  error TEXT,
  trace_id TEXT
);
CREATE TABLE IF NOT EXISTS BUFFER_RESULT (
  result_id INTEGER PRIMARY KEY AUTOINCREMENT,
  buffer_id INTEGER,
  llm_task_id INTEGER,
  template_id INTEGER,
  meta TEXT,
  FOREIGN KEY(buffer_id) REFERENCES BUFFER_GROUP(buffer_id),
  FOREIGN KEY(llm_task_id) REFERENCES LLM_TASK(llm_task_id),
  FOREIGN KEY(template_id) REFERENCES REGEX_TEMPLATE(template_id)
);
