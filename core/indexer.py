
import re
from store import dao
class IndexHandle:
    def __init__(self, version: str, compiled: list[tuple[int, re.Pattern, str]]):
        self.version = version; self.compiled = compiled
_ACTIVE = None
def load_active_index() -> IndexHandle:
    global _ACTIVE
    compiled=[]
    for tid, pattern, sample_log, version, is_active, semantic_info in dao.list_templates():
        try: compiled.append((tid, re.compile(pattern), semantic_info or ""))
        except re.error: pass
    _ACTIVE = IndexHandle(version="init", compiled=compiled); return _ACTIVE
def build_index_incremental(new_template_ids: list[int]) -> IndexHandle:
    return load_active_index()
def atomic_switch_index(h: IndexHandle) -> str:
    global _ACTIVE; _ACTIVE = h; return h.version
def match_templates(items: list[dict], h: IndexHandle):
    matched=[]; unmatched=[]
    for it in items:
        key_text = it["key_text"]; hit=None
        for tid, pat, sem in h.compiled:
            if pat.search(key_text):
                hit=(tid, sem); break
        if hit:
            it2=it.copy(); it2["template_id"]=hit[0]; it2["semantic_info"]=hit[1]; matched.append(it2)
        else: unmatched.append(it)
    return matched, unmatched
