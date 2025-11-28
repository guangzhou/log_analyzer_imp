
import re
from pathlib import Path
TIMESTAMP_RE = re.compile(r"^\[\d{8}_\d{6}\]")
def preprocess_to_normal(lines, file_id: str, out_dir: str | None = None):
    out_dir = out_dir or "."
    normal_path = Path(out_dir) / f"{file_id}.normal.txt"
    total = 0; kept = 0; last = None
    with open(normal_path, "w", encoding="utf-8") as w:
        for raw in lines:
            total += 1
            if TIMESTAMP_RE.match(raw):
                if last is not None:
                    w.write(last + "\n"); kept += 1
                last = raw
            else:
                if last is None:
                    continue
                last = f"{last} {raw.strip()}"
        if last is not None:
            w.write(last + "\n"); kept += 1
    return {"normal_path": str(normal_path), "total_lines": total, "preprocessed_lines": kept}
