# -*- coding: utf-8 -*-
"""
描述相关的 DAO 扩展函数

说明
- 不改动原有 store.dao
- 仅基于其连接能力, 提供模块与子模块描述相关的查询与更新接口
- 供第三遍程序 bin.p3_fill_descriptions 使用
"""

from typing import List, Tuple
import sqlite3
from . import dao as _dao  # 复用现有 DEFAULT_DB 等配置

def _conn() -> sqlite3.Connection:
    """获取一个新的数据库连接.

    优先复用 dao.get_conn, 否则退回 dao._connect 或直接根据 DEFAULT_DB 打开.
    每次调用都会返回一个新的连接, 由调用方负责关闭.
    """
    # 优先使用显式暴露的 get_conn
    if hasattr(_dao, "get_conn"):
        return _dao.get_conn()  # type: ignore[no-any-return]

    # 次优: 使用内部 _connect
    if hasattr(_dao, "_connect"):
        return _dao._connect()  # type: ignore[no-any-return]

    # 兜底: 根据 DEFAULT_DB 自行创建连接
    import os
    db_path = getattr(_dao, "DEFAULT_DB", os.environ.get("LOG_ANALYZER_DB", "./data/log_analyzer.sqlite3"))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def list_modules_without_desc(limit: int = 100) -> List[str]:
    """列出 description 为空的模块名列表.

    返回值
    - 模块名字符串列表, 按 mod 升序
    """
    c = _conn()
    try:
        cur = c.execute(
            "SELECT mod FROM module WHERE description IS NULL OR description='' ORDER BY mod ASC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
        out: List[str] = []
        for r in rows:
            if isinstance(r, sqlite3.Row):
                out.append(r["mod"])
            else:
                out.append(r[0])
        return out
    finally:
        c.close()

def list_submodules_without_desc(limit: int = 200) -> List[Tuple[str, str]]:
    """列出 description 为空的子模块.

    返回值
    - 列表, 每项为 (smod, mod)
    """
    c = _conn()
    try:
        cur = c.execute(
            "SELECT smod, mod FROM submodule WHERE description IS NULL OR description='' ORDER BY smod ASC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
        out: List[Tuple[str, str]] = []
        for r in rows:
            if isinstance(r, sqlite3.Row):
                out.append((r["smod"], r["mod"]))
            else:
                out.append((r[0], r[1]))
        return out
    finally:
        c.close()

def update_module_description(mod: str, desc: str) -> None:
    """更新单个模块的描述."""
    c = _conn()
    try:
        c.execute(
            "UPDATE module SET description=?, updated_at=datetime('now') WHERE mod=?",
            (desc, mod),
        )
        c.commit()
    finally:
        c.close()

def update_submodule_description(smod: str, desc: str) -> None:
    """更新单个子模块的描述."""
    c = _conn()
    try:
        c.execute(
            "UPDATE submodule SET description=?, updated_at=datetime('now') WHERE smod=?",
            (desc, smod),
        )
        c.commit()
    finally:
        c.close()
