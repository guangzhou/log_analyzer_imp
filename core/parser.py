# -*- coding: utf-8 -*-
import re
from typing import NamedTuple, Optional

LINE_RE = re.compile(
    r'^\[(?P<date>\d{8})_(?P<time>\d{6})\]\[(?P<sec>\d+\.\d+)\]\[(?P<level>[A-Z])\]\[(?P<thr>\d+)\]\[MOD:(?P<mod>[^\]]*)\]\[SMOD:(?P<smod>[^\]]*)\](?P<rest>.*)$'
)

class ParsedLine(NamedTuple):
    ts: str
    level: str
    thread_id: str
    mod: str
    smod: str
    key_text: str
    raw: str

def parse_fields(line: str) -> Optional[ParsedLine]:
    m = LINE_RE.match(line)
    if not m:
        return None
    date = m.group("date")
    time_ = m.group("time")
    ts = f"{date} {time_}"
    level = m.group("level")
    thr = m.group("thr")
    mod = m.group("mod") or ""
    smod = m.group("smod") or ""
    rest = m.group("rest") or ""
    key_text = extract_key_text(rest)
    return ParsedLine(ts=ts, level=level, thread_id=thr, mod=mod, smod=smod, key_text=key_text, raw=line)

def extract_key_text(rest: str) -> str:
    s = rest.strip()
    while True:
        s = s.lstrip()
        if s.startswith('['):
            idx = s.find(']')
            if idx != -1:
                s = s[idx+1:]
                continue
        break
    return s.strip()
