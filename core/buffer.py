
from store import dao
from core.configs import APP_CFG
def buffer_unmatched(items, run_id, scope="全局"):
    if not items: return None
    size_threshold = int(APP_CFG["buffer"]["size_threshold"])
    group_id = dao.insert_buffer_group(size_threshold=size_threshold, scope=scope, catalog_version="current")
    dao.insert_buffer_items(group_id, run_id, items)
    return group_id
def should_trigger_committee(buffer_id: int) -> bool:
    conn = dao.get_conn()
    try:
        cur = conn.execute("SELECT size_threshold, current_size FROM BUFFER_GROUP WHERE buffer_id=?", (buffer_id,))
        row = cur.fetchone()
        return bool(row and row[1] >= row[0])
    finally:
        conn.close()
def lock_buffer_group(buffer_id: int):
    return dao.lock_buffer_group(buffer_id)
def clear_buffer_group(buffer_id: int):
    return dao.clear_buffer_group(buffer_id)
