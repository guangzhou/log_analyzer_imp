
import re, hashlib
def normalize_text(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\b\d{3,}\b", "<NUM>", s)
    s = re.sub(r"/[A-Za-z0-9_\-./]+\.cpp", "<PATH_CPP>", s)
    s = re.sub(r"/[A-Za-z0-9_\-./]+", "<PATH>", s)
    s = re.sub(r"\s+", " ", s)
    return s
def signature_of(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()[:16]
def normalize_and_sign_items(key_iter):
    seen = {}
    for key_text, raw, lf in key_iter:
        n = normalize_text(key_text); sig = signature_of(n)
        if sig not in seen:
            seen[sig] = {"key_text": n, "signature": sig, "sample_count": 1, "raw_log": raw, "lf": lf}
        else:
            seen[sig]["sample_count"] += 1
    return list(seen.values())
