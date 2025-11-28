
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import streamlit as st
from store import dao
st.set_page_config(page_title="模块描述审批台", layout="wide")
st.title("模块 与 子模块 描述审批台")
conn = dao.get_conn()
st.header("模块描述为空的条目")
mods = conn.execute("SELECT mod FROM MODULE WHERE description IS NULL OR description='' ORDER BY mod ASC").fetchall()
smods = conn.execute("SELECT smod, mod FROM SUBMODULE WHERE description IS NULL OR description='' ORDER BY smod ASC").fetchall()
with st.expander("模块待补全", expanded=True):
    new_desc = {}
    for r in mods:
        m = r[0]
        desc = st.text_input(f"模块 {m} 描述", key=f"mod-{m}", value="")
        if desc: new_desc[m] = desc
    if st.button("批量提交模块描述"):
        c = dao.get_conn()
        try:
            for m, d in new_desc.items():
                c.execute("UPDATE MODULE SET description=?, updated_at=datetime('now') WHERE mod=?", (d, m))
            c.commit(); st.success("模块描述已提交")
        finally: c.close()
with st.expander("子模块待补全", expanded=True):
    new_desc2 = {}
    for r in smods:
        s, m = r[0], r[1]
        desc = st.text_input(f"子模块 {s} 所属 {m} 的描述", key=f"smod-{s}", value="")
        if desc: new_desc2[s] = desc
    if st.button("批量提交子模块描述"):
        c = dao.get_conn()
        try:
            for s, d in new_desc2.items():
                c.execute("UPDATE SUBMODULE SET description=?, updated_at=datetime('now') WHERE smod=?", (d, s))
            c.commit(); st.success("子模块描述已提交")
        finally: c.close()
conn.close()
