
from store import dao
def merge_templates_and_version(candidates):
    ids=[]
    for c in candidates:
        tid = dao.insert_template(
            pattern=c["pattern"],
            sample_log=c.get("sample_log",""),
            semantic_info=c.get("semantic_info","自动生成"),
            version=int(c.get("version",1)),
            is_active=True
        ); ids.append(tid)
    return ids
