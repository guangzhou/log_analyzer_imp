
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse, sqlite3, json, os
from pathlib import Path

DB_PATH = os.environ.get("LOG_DB_PATH", str(Path(__file__).resolve().parent.parent / "log_analyzer.db"))
SCHEMA_PATH = Path(__file__).resolve().parent / "ddl" / "schema.sql"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = f.read()
    conn = get_conn()
    try:
        conn.executescript(schema); conn.commit()
        print(f"Initialized DB at {DB_PATH}")
    finally:
        conn.close()

def upsert_file_registry(file_id, path, sha256, size_bytes, gz_mtime, status="新"):
    c = get_conn()
    try:
        c.execute("""
        INSERT INTO FILE_REGISTRY(file_id, path, sha256, size_bytes, gz_mtime, ingested_at, status)
        VALUES(?,?,?,?,?,datetime('now'),?)
        ON CONFLICT(file_id) DO UPDATE SET
          path=excluded.path, sha256=excluded.sha256, size_bytes=excluded.size_bytes, gz_mtime=excluded.gz_mtime, status=excluded.status
        """,(file_id, path, sha256, size_bytes, gz_mtime, status))
        c.commit()
    finally: c.close()

def new_run_session(file_id, pass_type, config):
    c = get_conn()
    try:
        cur = c.execute("""
        INSERT INTO RUN_SESSION(file_id, pass_type, config, started_at, status)
        VALUES(?,?,?,datetime('now'),'运行中')
        """,(file_id, pass_type, json.dumps(config, ensure_ascii=False)))
        rid = cur.lastrowid; c.commit(); return rid
    finally: c.close()

def finish_run_session(run_id, totals, status="成功"):
    c = get_conn()
    try:
        c.execute("""
        UPDATE RUN_SESSION SET ended_at=datetime('now'),
          total_lines=?, preprocessed_lines=?, matched_lines=?, unmatched_lines=?, status=?
        WHERE run_id=?
        """, (int(totals.get("total_lines",0)), int(totals.get("preprocessed_lines",0)),
              int(totals.get("matched_lines",0)), int(totals.get("unmatched_lines",0)), status, run_id))
        c.commit()
    finally: c.close()

def bulk_upsert_modules(mods):
    if not mods: return
    c=get_conn()
    try:
        for m in mods:
            c.execute("""
            INSERT INTO MODULE(mod, description, created_at, updated_at)
            VALUES(?, '', datetime('now'), datetime('now'))
            ON CONFLICT(mod) DO UPDATE SET updated_at=datetime('now')
            """,(m,))
        c.commit()
    finally: c.close()

def bulk_upsert_submodules(pairs):
    if not pairs: return
    c=get_conn()
    try:
        for mod, smod in pairs:
            c.execute("""
            INSERT INTO MODULE(mod, description, created_at, updated_at) 
            VALUES(?, '', datetime('now'), datetime('now'))
            ON CONFLICT(mod) DO UPDATE SET updated_at=datetime('now')
            """,(mod,))
            c.execute("""
            INSERT INTO SUBMODULE(smod, mod, description, created_at, updated_at)
            VALUES(?, ?, '', datetime('now'), datetime('now'))
            ON CONFLICT(smod) DO UPDATE SET mod=excluded.mod, updated_at=datetime('now')
            """,(smod, mod))
        c.commit()
    finally: c.close()

def insert_unmatched(run_id, file_id, key_text, raw_log, buffered, buffer_id, reason):
    c=get_conn()
    try:
        c.execute("""
        INSERT INTO UNMATCHED_LOG(run_id, file_id, key_text, raw_log, buffered, buffer_id, reason)
        VALUES(?,?,?,?,?,?,?)
        """,(run_id, file_id, key_text, raw_log or "", int(1 if buffered else 0), buffer_id, reason or ""))
        c.commit()
    finally: c.close()

def upsert_summary(run_id, file_id, template_id, mod, smod, classification, level, thread_id, first_ts, last_ts, line_count):
    c=get_conn()
    try:
        c.execute("""
        INSERT INTO LOG_MATCH_SUMMARY(run_id, file_id, template_id, mod, smod, classification, level, thread_id, first_ts, last_ts, line_count)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(file_id, template_id, mod, smod, level, thread_id) DO UPDATE SET
          run_id=excluded.run_id,
          classification=excluded.classification,
          first_ts=min(first_ts, excluded.first_ts),
          last_ts=max(last_ts, excluded.last_ts),
          line_count=LOG_MATCH_SUMMARY.line_count + excluded.line_count
        """,(run_id, file_id, template_id, mod, smod, classification, level or "", thread_id or "", first_ts, last_ts, int(line_count)))
        c.commit()
    finally: c.close()

def upsert_bucket(run_id, file_id, template_id, mod, smod, classification, level, thread_id, bucket_granularity, bucket_start, count_in_bucket):
    c=get_conn()
    try:
        c.execute("""
        INSERT INTO KEY_TIME_BUCKET(run_id, file_id, template_id, mod, smod, classification, level, thread_id, bucket_granularity, bucket_start, count_in_bucket)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(file_id, template_id, mod, smod, level, thread_id, bucket_start, bucket_granularity) DO UPDATE SET
          run_id=excluded.run_id,
          classification=excluded.classification,
          count_in_bucket=KEY_TIME_BUCKET.count_in_bucket + excluded.count_in_bucket
        """,(run_id, file_id, template_id, mod, smod, classification, level or "", thread_id or "", bucket_granularity, bucket_start, int(count_in_bucket)))
        c.commit()
    finally: c.close()

def insert_template(pattern, sample_log, semantic_info, version=1, is_active=True):
    c=get_conn()
    try:
        cur = c.execute("""
        INSERT INTO REGEX_TEMPLATE(pattern, sample_log, version, is_active, semantic_info, created_at, updated_at)
        VALUES(?,?,?,?,?,datetime('now'),datetime('now'))
        """,(pattern, sample_log, int(version), int(1 if is_active else 0), semantic_info))
        tid = cur.lastrowid
        c.execute("""
        INSERT INTO TEMPLATE_HISTORY(template_id, pattern, sample_log, version, created_at, source, note)
        VALUES(?,?,?,?,datetime('now'),?,?)
        """,(tid, pattern, sample_log, int(version), "初始", ""))
        c.commit(); return tid
    finally: c.close()

def list_templates():
    c=get_conn()
    try:
        cur=c.execute("SELECT template_id, pattern, sample_log, version, is_active, semantic_info FROM REGEX_TEMPLATE WHERE is_active=1 ORDER BY template_id ASC")
        return cur.fetchall()
    finally: c.close()

def insert_buffer_group(size_threshold, scope, catalog_version):
    c=get_conn()
    try:
        cur = c.execute("""
        INSERT INTO BUFFER_GROUP(scope, size_threshold, current_size, created_at, status, last_triggered_at, new_ratio, catalog_version)
        VALUES(?,?,0,datetime('now'),'收集中',null,0.0,?)
        """,(scope, size_threshold, catalog_version))
        bid=cur.lastrowid; c.commit(); return bid
    finally: c.close()

def insert_buffer_items(buffer_id, run_id, items):
    if not items: return 0
    c=get_conn()
    try:
        for it in items:
            c.execute("""
            INSERT INTO BUFFER_ITEM(buffer_id, run_id, key_text, signature, sample_count, raw_log)
            VALUES(?,?,?,?,?,?)
            """,(buffer_id, run_id, it["key_text"], it["signature"], int(it.get("sample_count",1)), it.get("raw_log","")))
        c.execute("UPDATE BUFFER_GROUP SET current_size = current_size + ? WHERE buffer_id=?", (len(items), buffer_id))
        c.commit(); return len(items)
    finally: c.close()

def lock_buffer_group(buffer_id):
    c=get_conn()
    try:
        c.execute("UPDATE BUFFER_GROUP SET status='锁定中' WHERE buffer_id=?", (buffer_id,))
        cur=c.execute("SELECT key_text, signature, sample_count FROM BUFFER_ITEM WHERE buffer_id=?", (buffer_id,))
        rows=cur.fetchall()
        return [{"key_text":r[0], "signature":r[1], "sample_count":r[2]} for r in rows]
    finally: c.close()

def clear_buffer_group(buffer_id):
    c=get_conn()
    try:
        c.execute("DELETE FROM BUFFER_ITEM WHERE buffer_id=?", (buffer_id,))
        c.execute("UPDATE BUFFER_GROUP SET current_size=0, status='待清理' WHERE buffer_id=?", (buffer_id,))
        c.commit()
    finally: c.close()

def new_llm_task(use_case, buffer_id, model, prompt_version, phase, input_count, trace_id):
    c=get_conn()
    try:
        cur = c.execute("""
        INSERT INTO LLM_TASK(use_case, buffer_id, model, prompt_version, phase, started_at, status, input_count, trace_id)
        VALUES(?,?,?,?,?,datetime('now'),'运行中',?,?)
        """,(use_case, buffer_id, model, prompt_version, phase, int(input_count), trace_id))
        tid = cur.lastrowid; c.commit(); return tid
    finally: c.close()

def finish_llm_task(llm_task_id, status, output_json, error):
    c=get_conn()
    try:
        c.execute("""
        UPDATE LLM_TASK SET finished_at=datetime('now'), status=?, output_json=COALESCE(?, output_json), error=COALESCE(?, error) WHERE llm_task_id=?
        """,(status, output_json, error, llm_task_id))
        c.commit()
    finally: c.close()

def attach_buffer_result(buffer_id, llm_task_id, template_id, meta):
    c=get_conn()
    try:
        c.execute("""
        INSERT INTO BUFFER_RESULT(buffer_id, llm_task_id, template_id, meta)
        VALUES(?,?,?,?)
        """,(buffer_id, llm_task_id, template_id, json.dumps(meta or {}, ensure_ascii=False)))
        c.commit()
    finally: c.close()

if __name__ == "__main__":
    import sys
    if "--init" in sys.argv:
        init_db()
