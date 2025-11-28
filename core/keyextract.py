
from .parser import parse_line
def iter_key_texts(normal_path: str):
    with open(normal_path, "r", encoding="utf-8") as f:
        for line in f:
            lf = parse_line(line.rstrip("\n"))
            yield lf.key_text, line.rstrip("\n"), lf
