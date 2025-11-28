
import re
from dataclasses import dataclass
BRACKET_RE = re.compile(r"^\[[^\]]+\]")
MOD_RE = re.compile(r"\[MOD:([^\]]+)\]")
SMOD_RE = re.compile(r"\[SMOD:([^\]]+)\]")
LEVEL_RE = re.compile(r"\]\[([A-Z])\]")
@dataclass
class LineFields:
    ts: str | None
    level: str | None
    thread_id: str | None
    mod: str
    smod: str
    key_text: str
def parse_line(line: str) -> LineFields:
    ts_match = re.match(r"^\[(\d{8}_\d{6})\]", line)
    ts = ts_match.group(1) if ts_match else None
    m_level = LEVEL_RE.search(line); level = m_level.group(1) if m_level else None
    m_thread = re.search(r"\]\[(\d+)\]\[MOD:", line); thread_id = m_thread.group(1) if m_thread else None
    m_mod = MOD_RE.search(line); mod = m_mod.group(1) if m_mod else ""
    m_smod = SMOD_RE.search(line); smod = m_smod.group(1) if m_smod else ""
    rest = line
    while True:
        m = BRACKET_RE.match(rest)
        if not m: break
        rest = rest[m.end():].lstrip()
    key_text = rest.strip()
    return LineFields(ts, level, thread_id, mod, smod, key_text)
def extract_mod_smod_from_file(normal_path: str):
    mods=set(); pairs=set()
    with open(normal_path, "r", encoding="utf-8") as f:
        for line in f:
            lf = parse_line(line.rstrip("\n"))
            if lf.mod: mods.add(lf.mod)
            if lf.mod and lf.smod: pairs.add((lf.mod, lf.smod))
    return mods, pairs
