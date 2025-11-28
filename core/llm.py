
import os, re
from core.configs import MODELS_CFG
from store import dao
def _heuristic_templates(samples):
    outs=[]
    for s in samples[:10]:
        text=s["key_text"]
        pattern = re.sub(r"\b\d+\b", r"\\d+", re.escape(text))
        pattern = pattern.replace(r"\/", r"\/")
        pattern = pattern.replace(r"\<NUM\>", r".+").replace(r"\<PATH\>", r".+").replace(r"\<PATH_CPP\>", r".+")
        pattern = pattern.replace(r"\.\.\.", r".*")
        outs.append({"pattern": pattern, "sample_log": text, "semantic_info": "自动生成 分类未知 建议人工复核", "version": 1})
    return outs
def generate_rules_from_samples(samples, phase="v1点0"):
    use_model = os.environ.get("OPENAI_API_KEY") or MODELS_CFG.get("default_model")
    return _heuristic_templates(samples)
def historical_negatives(signature: str, top_k: int = 50):
    c=dao.get_conn()
    try:
        cur=c.execute("SELECT key_text FROM UNMATCHED_LOG ORDER BY um_id DESC LIMIT ?", (top_k,))
        return [r[0] for r in cur.fetchall()]
    finally: c.close()
def validate_against_historical(candidate: dict, negatives: list[str]):
    try: pat = re.compile(candidate["pattern"])
    except re.error: return {"ok": False, "reason": "编译失败", "fp": 1.0}
    fp=0
    for n in negatives:
        if pat.search(n): fp+=1
    rate = fp / max(1, len(negatives))
    return {"ok": rate < 0.05, "fp": rate}
