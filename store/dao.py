# -*- coding: utf-8 -*-
"""
store.dao
数据库访问层

新增：命令行入口
  python -m store.dao --init --db ./data/log_analyzer.sqlite3
可选参数：
  --schema 指定 schema.sql 路径，默认取与本文件同目录下的 schema.sql
  --ensure-dir 若父目录不存在则自动创建
"""
import sqlite3, os, json, argparse, sys
from datetime import datetime
from typing import List, Dict, Any, Iterable, Tuple

DEFAULT_DB = os.environ.get("LOG_ANALYZER_DB", "./data/log_analyzer.sqlite3")

# 统一的数字正则，用于替换 NUMNUM 占位符
NUMERIC_PATTERN = r'[-+]?(?:\d+.\d*|.\d+|\d+)'


def _connect(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DEFAULT_DB, schema_path: str = None):
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    if not schema_path:
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    if not os.path.exists(schema_path):
        raise FileNotFoundError(f"找不到 schema 文件: {schema_path}")
    with _connect(db_path) as conn:
        with open(schema_path, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()


def register_file(file_id: str, path: str, sha256: str = "", size_bytes: int = 0, gz_mtime: str = ""):
    now = datetime.utcnow().isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO file_registry(file_id, path, sha256, size_bytes, gz_mtime, ingested_at, status)
            VALUES(?, ?, ?, ?, ?, COALESCE((SELECT ingested_at FROM file_registry WHERE file_id=?), ?), ?)
        """,
            (file_id, path, sha256, size_bytes, gz_mtime, file_id, now, "新"),
        )
        conn.commit()


def create_run_session(file_id: str, pass_type: str, config: Dict[str, Any]) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO run_session(file_id, pass_type, config_json, started_at, status)
            VALUES(?, ?, ?, ?, ?)
        """,
            (file_id, pass_type, json.dumps(config, ensure_ascii=False), datetime.utcnow().isoformat(), "运行中"),
        )
        conn.commit()
        return cur.lastrowid


def complete_run_session(run_id: int, **kwargs):
    fields = []
    values = []
    for k, v in kwargs.items():
        if k in ["total_lines", "preprocessed_lines", "unmatched_lines", "matched_lines", "status"]:
            fields.append(f"{k}=?")
            values.append(v)
    fields.append("ended_at=?")
    values.append(datetime.utcnow().isoformat())
    with _connect() as conn:
        conn.execute(f"UPDATE run_session SET {', '.join(fields)} WHERE run_id=?", (*values, run_id))
        conn.commit()


def upsert_modules(mods: Iterable[str]):
    now = datetime.utcnow().isoformat()
    with _connect() as conn:
        for m in set([x for x in mods if x]):
            conn.execute(
                """
                INSERT INTO module(mod, description, created_at, updated_at)
                VALUES(?, '', ?, ?)
                ON CONFLICT(mod) DO UPDATE SET updated_at=excluded.updated_at
            """,
                (m, now, now),
            )
        conn.commit()


def upsert_submodules(mod_smods: Iterable[Tuple[str, str]]):
    now = datetime.utcnow().isoformat()
    with _connect() as conn:
        for mod, smod in set([x for x in mod_smods if x[0] and x[1]]):
            conn.execute(
                """
                INSERT INTO submodule(smod, mod, description, created_at, updated_at)
                VALUES(?, ?, '', ?, ?)
                ON CONFLICT(smod) DO UPDATE SET mod=excluded.mod, updated_at=excluded.updated_at
            """,
                (smod, mod, now, now),
            )
        conn.commit()


def fetch_all_templates(active_only: bool = True) -> List[sqlite3.Row]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT template_id, pattern, pattern_nomal, sample_log FROM regex_template WHERE is_active=1"
            if active_only
            else "SELECT template_id, pattern,pattern_nomal, sample_log FROM regex_template"
        )
        return cur.fetchall()


def write_templates(cands: List[Dict[str, Any]]) -> List[int]:
    """
    将候选模板写入 regex_template / template_history。

    约定：
    - c["pattern_nomal"]：含 NUMNUM 的原始模式；若不存在则退化为 c["pattern"]
    - 写库时：
        * regex_template.pattern_nomal 保存原始模式
        * regex_template.pattern 将其中的 NUMNUM 统一替换为 NUMERIC_PATTERN
    - 按 pattern_nomal 做去重，避免插入重复正则
    """
    if not cands:
        return []

    ids: List[int] = []
    now = datetime.utcnow().isoformat()
    seen_nomal = set()

    with _connect() as conn:
        for c in cands:
            raw_pattern = c.get("pattern", "") or ""
            pattern_nomal = c.get("pattern_nomal") or raw_pattern
            pattern_nomal = pattern_nomal.strip()

            if not pattern_nomal:
                # 没有有效模式，直接跳过
                continue

            # 保证 pattern_nomal 唯一
            if pattern_nomal in seen_nomal:
                continue
            seen_nomal.add(pattern_nomal)

            # 将 NUMNUM 占位符替换为统一数字正则
            pattern_real = pattern_nomal.replace("NUMNUM", NUMERIC_PATTERN)

            sample_log = c.get("sample_log", "")
            semantic_info = c.get("semantic_info", "")
            advise = c.get("advise", "")
            source = c.get("source", "委员会")

            # 主表：存真实 pattern + 归一模式 pattern_nomal
            cur = conn.execute(
                """
                INSERT INTO regex_template(pattern, pattern_nomal, sample_log, version, is_active,
                                           semantic_info, advise, created_at, updated_at, source)
                VALUES(?, ?, ?, 1, 1, ?, ?, ?, ?, ?)
            """,
                (pattern_real, pattern_nomal, sample_log, semantic_info, advise, now, now, source),
            )
            tid = cur.lastrowid
            ids.append(tid)

            # 历史表：保留真实 pattern，后续如需要也可以扩展 pattern_nomal 字段
            conn.execute(
                """
                INSERT INTO template_history(template_id, pattern, sample_log, version, created_at, source, note)
                VALUES(?, ?, ?, 1, ?, ?, ?)
            """,
                (tid, pattern_real, sample_log, now, source, "首次创建"),
            )
        conn.commit()
    return ids


def write_unmatched(run_id: int, file_id: str, key_text: str, raw_log: str, reason: str = ""):
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO unmatched_log(run_id, file_id, key_text, raw_log, buffered, reason, created_at)
            VALUES(?, ?, ?, ?, 0, ?, ?)
        """,
            (run_id, file_id, key_text, raw_log, reason, datetime.utcnow().isoformat()),
        )
        conn.commit()


def batch_upsert_log_match_summary(rows: List[Dict[str, Any]]):
    if not rows:
        return
    now = datetime.utcnow().isoformat()
    with _connect() as conn:
        for r in rows:
            conn.execute(
                """
                INSERT INTO log_match_summary(
                    run_id,
                    file_id,
                    template_id,
                    mod,
                    smod,
                    classification,
                    level,
                    thread_id,
                    first_ts,
                    last_ts,
                    line_count,
                    updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["run_id"],
                    r["file_id"],
                    r["template_id"],
                    r.get("mod", "") or "",
                    r.get("smod", "") or "",
                    r.get("classification", "") or "",
                    r.get("level", "") or "",
                    r.get("thread_id", "") or "",
                    r.get("first_ts", "") or "",
                    r.get("last_ts", "") or "",
                    int(r.get("line_count", 0) or 0),
                    now,
                ),
            )
        conn.commit()
def batch_upsert_key_time_bucket(rows: List[Dict[str, Any]]):
    if not rows:
        return
    now = datetime.utcnow().isoformat()
    with _connect() as conn:
        for r in rows:
            conn.execute(
                """
                INSERT INTO key_time_bucket(
                    run_id,
                    file_id,
                    template_id,
                    mod,
                    smod,
                    classification,
                    level,
                    thread_id,
                    bucket_granularity,
                    bucket_start,
                    count_in_bucket,
                    updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["run_id"],
                    r["file_id"],
                    r["template_id"],
                    r.get("mod", "") or "",
                    r.get("smod", "") or "",
                    r.get("classification", "") or "",
                    r.get("level", "") or "",
                    r.get("thread_id", "") or "",
                    r.get("bucket_granularity", "") or "",
                    r.get("bucket_start", "") or "",
                    int(r.get("count_in_bucket", 0) or 0),
                    now,
                ),
            )
        conn.commit()

def get_recent_unmatched(limit: int = 200) -> List[str]:
    with _connect() as conn:
        cur = conn.execute("SELECT key_text FROM unmatched_log ORDER BY um_id DESC LIMIT ?", (limit,))
        return [r["key_text"] for r in cur.fetchall()]


def get_template_samples(limit: int = 200) -> List[str]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT sample_log FROM regex_template WHERE sample_log IS NOT NULL AND sample_log != '' ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        return [r["sample_log"] for r in cur.fetchall()]


def _cli():
    parser = argparse.ArgumentParser(description="log_analyzer 数据库工具")
    parser.add_argument("--db", default=DEFAULT_DB, help="数据库文件路径")
    parser.add_argument("--init", action="store_true", help="初始化数据库")
    parser.add_argument("--schema", default=None, help="自定义 schema.sql 路径")
    parser.add_argument("--ensure-dir", action="store_true", help="若父目录不存在则自动创建")
    args = parser.parse_args()

    db_path = args.db
    if args.ensure_dir:
        parent = os.path.dirname(os.path.abspath(db_path))
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)

    if args.init:
        try:
            init_db(db_path=db_path, schema_path=args.schema)
            print(f"[OK] 数据库已初始化: {db_path}")
            return 0
        except Exception as e:
            print(f"[ERR] 初始化失败: {e}", file=sys.stderr)
            return 2
    else:
        print("未指定操作。可用参数示例: --init --db ./data/log_analyzer.sqlite3")
        return 1


if __name__ == "__main__":
    sys.exit(_cli())
