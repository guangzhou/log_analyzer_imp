
from pathlib import Path
import gzip
import hashlib
def compute_file_id(path: str) -> str:
    p = Path(path)
    mtime = int(p.stat().st_mtime) if p.exists() else 0
    key = f"{str(p.resolve())}|{mtime}".encode("utf-8", errors="ignore")
    return hashlib.sha256(key).hexdigest()[:32]
def open_gz_stream(path: str):
    try:
        with gzip.open(path, "rt", encoding="utf-8", errors="ignore") as f:
            for line in f:
                yield line.rstrip("\n")
    except OSError:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                yield line.rstrip("\n")
